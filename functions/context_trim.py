"""
title: Context Trim
author: Crimson
version: 2.3.0
required_open_webui_version: 0.5.0
description: Lets a chat continue past the context limit. Old turns are folded into a rolling summary, the cut point stays put between trims (so the prompt cache survives), old images are dropped, and token estimates calibrate themselves against real usage.
"""

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import tempfile
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("context_trim")

IMAGE_PLACEHOLDER = "[image removed from history]"
MAX_SUMMARY_CHUNKS = 8
MAX_CHATS_IN_MEMORY = 512
# Options that make Ollama reload a model when they differ from the loaded runner.
LOAD_OPTIONS = ("num_ctx", "num_batch", "num_gpu", "num_thread", "use_mmap", "use_mlock", "main_gpu", "numa")

_NOISE = re.compile(
    r"<think>.*?</think>|<details\b[^>]*type=\"(?:reasoning|tool_calls|code_interpreter)\"[^>]*>.*?</details>",
    re.DOTALL | re.IGNORECASE,
)

SUMMARY_SYSTEM = (
    "You maintain the long-term memory of an AI assistant. You are given the "
    "existing memory note (possibly empty) and the next part of the conversation, "
    "which is about to be deleted from the assistant's context. Write the updated "
    "memory note."
)

SUMMARY_INSTRUCTIONS = (
    "Write the updated memory note now. The assistant will rely on it to continue the work "
    "without the deleted messages, so it must say what was asked, what was done and where things stand. Rules:\n"
    "- Merge the existing note with the new messages; do not lose facts that are still relevant.\n"
    "- Be specific. Keep exact names, numbers, dates, versions, file paths, commands, code identifiers, "
    "URLs and error messages. Never write 'various' or 'several' in place of the actual items.\n"
    "- Record the work, not just the topic: which tools were called and what they returned, which commands "
    "were run and their results, what was tried and failed, what was written or changed.\n"
    "- Drop: greetings, filler, superseded drafts, and reasoning that led nowhere.\n"
    "- Use short bullet points under these headings, leaving out empty ones: "
    "Goal, Facts, Work done, Decisions, Current state, Open tasks.\n"
    "- Write in the language the conversation is held in.\n"
    "- At most {words} words. Output only the note, with no preamble."
)

BUILTIN_MARK = "[CONVERSATION SUMMARY]"
PRUNED = (
    "[... {n} characters of this tool result were removed to save context. "
    "To see them: read_chat_message(number={k}) if you have the chat history tool, or call the tool again ...]"
)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return "" if content is None else str(content)


def _image_count(m: dict) -> int:
    n = len(m.get("images") or [])
    c = m.get("content")
    if isinstance(c, list):
        n += sum(1 for p in c if isinstance(p, dict) and p.get("type") == "image_url")
    return n


def _without_images(m: dict) -> dict:
    """Copy of the message with images replaced by a placeholder."""
    out = dict(m)
    out.pop("images", None)
    c = m.get("content")
    if isinstance(c, list):
        parts = [
            p for p in c if not (isinstance(p, dict) and p.get("type") == "image_url")
        ]
        parts.append({"type": "text", "text": IMAGE_PLACEHOLDER})
        out["content"] = parts
    else:
        out["content"] = f"{_text(c)}\n{IMAGE_PLACEHOLDER}".strip()
    return out


def _middle_cut(text: str, limit: int) -> str:
    """Keep the head and tail of a text, dropping the middle."""
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = max(limit - head, 0)
    dropped = len(text) - head - tail
    return f"{text[:head]}\n[... {dropped} characters omitted ...]\n{text[len(text) - tail:]}"


def _fingerprint(msgs: list, upto: int) -> str:
    """Cheap identity of a message prefix, used to notice edited or branched history."""
    h = hashlib.blake2b(digest_size=12)
    for m in msgs[:upto]:
        t = _text(m.get("content"))
        h.update(
            f"{m.get('role')}|{len(t)}|{t[:200]}|{t[-80:]}\x00".encode("utf-8", "ignore")
        )
    return h.hexdigest()


def _find_num_ctx(body: dict, model: Optional[dict]) -> int:
    model = model or {}
    info = model.get("info") or {}
    for d in (
        body.get("options"),
        body.get("params"),
        body,
        info.get("params"),
        model.get("params"),
    ):
        if isinstance(d, dict):
            try:
                n = int(d.get("num_ctx") or 0)
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                return n
    return 0


def _state_dir() -> str:
    try:
        from open_webui.env import DATA_DIR

        base = str(DATA_DIR)
    except Exception:
        base = tempfile.gettempdir()
    return os.path.join(base, "context_trim")


class Filter:
    class Valves(BaseModel):
        priority: int = Field(0, description="Filter order; lower runs first.")
        enabled: bool = Field(True, description="Master switch.")
        token_budget: int = Field(
            0,
            description="Max prompt tokens. 0 = automatic: num_ctx × context_safety − reserve_output_tokens.",
        )
        fallback_token_budget: int = Field(
            200000,
            description="Budget used when token_budget is 0 and no num_ctx can be found on the request or model.",
        )
        context_safety: float = Field(
            0.9, description="Fraction of num_ctx to trust, since estimates are rough."
        )
        reserve_output_tokens: int = Field(
            4096, description="Room left for the reply when the budget is automatic."
        )
        trim_to_ratio: float = Field(
            0.7,
            description="When over budget, trim down to this fraction of it. Lower = fewer trims and longer-lived prompt cache, but less history kept.",
        )
        keep_images_in_last: int = Field(
            4, description="Keep images only in the last N messages."
        )
        image_tokens: int = Field(1000, description="Estimated cost of one kept image.")
        summarize: bool = Field(
            True,
            description="Fold dropped messages into a rolling summary instead of just deleting them.",
        )
        summary_model: str = Field(
            "",
            description="Model that writes summaries. Empty = the chat's own model (already loaded, no model swap). 'task' = Open WebUI's task model. Or any model id.",
        )
        prune_tool_results: bool = Field(
            True,
            description="When over budget, first shorten old tool results (fetched pages, command output) and keep the conversation itself. Turns are only removed if that is not enough.",
        )
        keep_full_tool_results: int = Field(
            3, description="The newest this-many tool results are never shortened."
        )
        pruned_tool_chars: int = Field(
            1200, description="How much of a shortened tool result is kept (its start and its end)."
        )
        max_tool_result_tokens: int = Field(
            8000,
            description="A single tool result larger than this is cut to this size as soon as it appears, so one huge page cannot fill the context. 0 = no limit.",
        )
        overhead_tokens: int = Field(
            6000,
            description="Room left for what Open WebUI adds after this filter: tool definitions, the skill list, retrieved documents.",
        )
        archive: bool = Field(
            True,
            description="Keep everything that was shortened or removed on disk, so the Chat History tool can still search and read it.",
        )
        summary_max_tokens: int = Field(
            0, description="Size cap of the summary. 0 = automatic: 2.5 % of the budget, between 1200 and 3000 tokens."
        )
        summary_chunk_tokens: int = Field(
            12000, description="How much dropped history is fed to the summary model per call."
        )
        summary_num_ctx: int = Field(
            16384,
            description="num_ctx sent with summary calls when the summary model is a different Ollama model than the chat's. 0 = leave that model's own setting.",
        )
        summary_timeout: int = Field(180, description="Seconds allowed per summary call.")
        bytes_per_token: float = Field(
            3.3, description="Starting guess for UTF-8 bytes per token."
        )
        auto_calibrate: bool = Field(
            True,
            description="Correct the token estimate per model from the prompt token counts the backend reports.",
        )
        show_status: bool = Field(True, description="Show a status line when a trim happens.")
        warn_builtin_compaction: bool = Field(
            True,
            description="Say so once per chat when Open WebUI's own context compaction has already cut the history before this filter saw it.",
        )
        persist_state: bool = Field(
            True, description="Save cut points and summaries to disk so they survive restarts."
        )
        max_reread_seconds: int = Field(
            0,
            description="Cap the budget by time instead of size: never keep more history than the backend can re-read in this many seconds after a cache miss (model reload, chat switch, trim). 0 = off. Needs read_tokens_per_second.",
        )
        read_tokens_per_second: float = Field(
            0,
            description="Prompt processing speed of your setup in tokens per second, as measured by a benchmark. Used with max_reread_seconds.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._state: "OrderedDict[str, dict]" = OrderedDict()
        self._pending: "OrderedDict[str, tuple]" = OrderedDict()
        self._calibration: dict = {}
        self._warned: "OrderedDict[str, bool]" = OrderedDict()

    # ---------------------------------------------------------------- estimates

    def _raw_tokens(self, m: dict, images: bool = True) -> float:
        size = len(_text(m.get("content")).encode("utf-8", "ignore"))
        if m.get("tool_calls"):
            size += len(json.dumps(m["tool_calls"], default=str))
        tokens = size / max(self.valves.bytes_per_token, 0.5) + 4
        if images:
            tokens += _image_count(m) * self.valves.image_tokens
        return tokens

    def _budget(self, body: dict, model: Optional[dict]) -> int:
        v = self.valves
        if v.token_budget > 0:
            budget = v.token_budget
        else:
            n = _find_num_ctx(body, model)
            budget = (
                # The overhead allowance is capped at 5 % so small contexts keep a usable budget.
                max(1024, int(n * v.context_safety) - v.reserve_output_tokens - min(max(v.overhead_tokens, 0), n // 20))
                if n
                else v.fallback_token_budget
            )
        if v.max_reread_seconds > 0 and v.read_tokens_per_second > 0:
            # A context that fits in memory can still be too big to wait for.
            budget = min(budget, max(1024, int(v.max_reread_seconds * v.read_tokens_per_second)))
        return budget

    def _summary_cap(self, budget: int) -> int:
        if self.valves.summary_max_tokens > 0:
            return self.valves.summary_max_tokens
        return min(max(int(budget * 0.025), 1200), 3000)

    @staticmethod
    def _shorten(m: dict, keep: int, number: int) -> dict:
        """Copy of a tool message with the middle of a long result removed. Same input, same output."""
        text = _text(m.get("content"))
        keep = max(keep, 200)
        if len(text) <= keep + 300:
            return m
        head = int(keep * 0.7)
        tail = keep - head
        short = f"{text[:head]}\n{PRUNED.format(n=len(text) - keep, k=number)}\n{text[len(text) - tail:]}"
        return {**m, "content": short}

    def _pruned(self, m: dict, number: int) -> dict:
        return self._shorten(m, self.valves.pruned_tool_chars, number)

    # ------------------------------------------------------------------ archive

    def _archive_path(self, chat_id: str) -> str:
        name = hashlib.sha1(chat_id.encode("utf-8", "ignore")).hexdigest()
        return os.path.join(_state_dir(), "archive", f"{name}.json")

    def _archive(self, chat_id: str, conv: list, indexes: Any, reset: bool = False) -> None:
        """Store the full text of messages that are about to be shortened or removed.

        Keyed by the message's number in the chat (1 = first message), which is what the
        notes left in the context refer to. Read by the Chat History tool.
        """
        if not self.valves.archive or not self.valves.persist_state or chat_id.startswith("anon:"):
            return
        path = self._archive_path(chat_id)
        try:
            data: dict = {}
            if not reset:
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    data = {}
            changed = reset
            for i in indexes:
                key = str(i + 1)
                if key in data:
                    continue
                m = conv[i]
                text = _text(m.get("content"))
                for call in m.get("tool_calls") or []:
                    fn = (call or {}).get("function") or {}
                    args = fn.get("arguments")
                    args = args if isinstance(args, str) else json.dumps(args, default=str)
                    text = f"{text}\n[called tool {fn.get('name', '?')} with {args}]".strip()
                if text:
                    data[key] = {"role": m.get("role"), "name": m.get("name") or "", "text": text}
                    changed = True
            if changed:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(path + ".tmp", path)
        except OSError as e:
            log.warning("context_trim: could not write the archive: %s", e)

    # -------------------------------------------------------------------- state

    def _state_path(self, chat_id: str) -> str:
        name = hashlib.sha1(chat_id.encode("utf-8", "ignore")).hexdigest()
        return os.path.join(_state_dir(), f"{name}.json")

    def _get_state(self, chat_id: str) -> dict:
        if chat_id in self._state:
            self._state.move_to_end(chat_id)
            return self._state[chat_id]
        st: dict = {}
        if self.valves.persist_state:
            try:
                with open(self._state_path(chat_id), encoding="utf-8") as f:
                    st = json.load(f)
            except (OSError, ValueError):
                st = {}
        self._remember(self._state, chat_id, st)
        return st

    def _put_state(self, chat_id: str, st: dict) -> None:
        self._remember(self._state, chat_id, st)
        if not self.valves.persist_state:
            return
        try:
            os.makedirs(_state_dir(), exist_ok=True)
            path = self._state_path(chat_id)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(path + ".tmp", path)
        except OSError as e:
            log.warning("context_trim: could not save state: %s", e)

    @staticmethod
    def _remember(store: OrderedDict, key: str, value: Any) -> None:
        store[key] = value
        store.move_to_end(key)
        while len(store) > MAX_CHATS_IN_MEMORY:
            store.popitem(last=False)

    # ------------------------------------------------------------ summarization

    def _summary_model(self, request: Any, chat_model: str) -> str:
        wanted = self.valves.summary_model.strip()
        if not wanted:
            # The chat model is already loaded and is about to re-read the trimmed
            # history anyway, so it is the cheapest model to ask, and usually the best.
            return chat_model
        try:
            models = request.app.state.MODELS
            if wanted.lower() == "task":
                cfg = request.app.state.config
                is_ollama = (models.get(chat_model) or {}).get("owned_by") == "ollama"
                wanted = cfg.TASK_MODEL if is_ollama else cfg.TASK_MODEL_EXTERNAL
            if wanted and wanted in models:
                return wanted
        except Exception as e:
            log.debug("context_trim: could not look up the summary model: %s", e)
        return chat_model

    def _chunks(self, msgs: list) -> list:
        """Render dropped messages as transcript chunks sized for the summary model."""
        chunk_chars = int(self.valves.summary_chunk_tokens * self.valves.bytes_per_token)
        per_msg = max(chunk_chars // 4, 400)
        chunks: list = []
        for _ in range(2):
            chunks, cur, size = [], [], 0
            for m in msgs:
                t = _NOISE.sub("", _text(m.get("content"))).strip()
                role = str(m.get("role", "user")).upper()
                if m.get("role") == "tool":
                    # What a tool returned is part of what was done; a short excerpt is enough.
                    role = f"TOOL RESULT ({m.get('name') or 'tool'})"
                    t = _middle_cut(t, min(per_msg, 1500))
                for call in m.get("tool_calls") or []:
                    fn = (call or {}).get("function") or {}
                    args = fn.get("arguments")
                    args = args if isinstance(args, str) else json.dumps(args, default=str)
                    t = f"{t}\n[called tool {fn.get('name', '?')} with {_middle_cut(args or '', 300)}]".strip()
                if not t:
                    continue
                line = f"{role}: {_middle_cut(t, per_msg)}"
                if cur and size + len(line) > chunk_chars:
                    chunks.append("\n\n".join(cur))
                    cur, size = [], 0
                cur.append(line)
                size += len(line)
            if cur:
                chunks.append("\n\n".join(cur))
            if len(chunks) <= MAX_SUMMARY_CHUNKS:
                break
            # Too much to summarize in a sane number of calls: clip messages harder.
            per_msg = max(per_msg * MAX_SUMMARY_CHUNKS // len(chunks), 200)
        return chunks[-MAX_SUMMARY_CHUNKS:]

    async def _complete(
        self,
        request: Any,
        user: Any,
        model: str,
        messages: list,
        chat_model: str = "",
        chat_options: Optional[dict] = None,
        cap: int = 1200,
    ) -> str:
        from open_webui.utils.chat import generate_chat_completion

        form: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            # Generous, because thinking models spend output tokens before answering.
            "max_tokens": cap * 3,
        }
        try:
            is_ollama = (request.app.state.MODELS.get(model) or {}).get("owned_by") == "ollama"
        except Exception:
            is_ollama = False
        options: dict = {}
        if model == chat_model:
            # Same model as the chat: reuse the chat's own load settings, because any
            # difference makes Ollama reload the model, which costs far more than the summary.
            options = {k: v for k, v in (chat_options or {}).items() if k in LOAD_OPTIONS}
        elif is_ollama and self.valves.summary_num_ctx > 0:
            options = {"num_ctx": self.valves.summary_num_ctx}
        if is_ollama:
            options["think"] = False  # a summary needs no reasoning phase; this makes it several times faster
        if options:
            form["options"] = options

        res = await generate_chat_completion(request, form, user=user, bypass_filter=True)
        if hasattr(res, "body"):
            res = json.loads(res.body)
        content = res["choices"][0]["message"].get("content") or ""
        return _NOISE.sub("", content).strip()

    async def _summarize(
        self,
        request: Any,
        user_info: Optional[dict],
        chat_model: str,
        previous: str,
        dropped: list,
        chat_options: Optional[dict] = None,
        cap: int = 1200,
    ) -> str:
        from open_webui.models.users import Users

        user = Users.get_user_by_id((user_info or {}).get("id"))
        if inspect.isawaitable(user):
            user = await user

        v = self.valves
        model = self._summary_model(request, chat_model)
        instructions = SUMMARY_INSTRUCTIONS.format(words=int(cap * 0.6))
        summary = previous
        for chunk in self._chunks(dropped):
            prompt = (
                f"<existing_note>\n{summary or '(empty)'}\n</existing_note>\n\n"
                f"<new_messages>\n{chunk}\n</new_messages>\n\n{instructions}"
            )
            out = await asyncio.wait_for(
                self._complete(
                    request,
                    user,
                    model,
                    [
                        {"role": "system", "content": SUMMARY_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    chat_model,
                    chat_options,
                    cap,
                ),
                timeout=v.summary_timeout,
            )
            if not out:
                raise RuntimeError("summary model returned nothing")
            summary = out
        return _middle_cut(summary, int(cap * v.bytes_per_token))

    # ----------------------------------------------------------------- trimming

    def _squeeze(self, kept: list, costs: list, excess: float, scale: float) -> None:
        """Last resort: the newest turn alone is over budget, so cut the middle out of its biggest messages."""
        bpt = self.valves.bytes_per_token
        for i in sorted(range(len(kept)), key=lambda k: costs[k], reverse=True):
            if excess <= 0:
                return
            m = kept[i]
            text = _text(m.get("content"))
            if len(text) < 2000:
                continue
            remove_chars = min(int(excess / scale * bpt) + 200, len(text) - 1000)
            new_text = _middle_cut(text, len(text) - remove_chars)
            content = m.get("content")
            if isinstance(content, list):
                others = [
                    p for p in content if not (isinstance(p, dict) and p.get("type") == "text")
                ]
                new_content: Any = others + [{"type": "text", "text": new_text}]
            else:
                new_content = new_text
            kept[i] = {**m, "content": new_content}
            excess -= (len(text) - len(new_text)) / bpt * scale

    @staticmethod
    def _note(cut: int, summary: str) -> str:
        head = (
            f"[Context note: messages 1 to {cut} of this conversation were removed to fit the context window. "
            "Their full text is still stored: if you need an exact detail from them and have the chat history tool, "
            "use search_chat_history or read_chat_message instead of guessing."
        )
        if summary:
            return f"{head} What they contained:]\n{summary}"
        return f"{head} No summary is available.]"

    @staticmethod
    def _with_note(system: list, note: str) -> list:
        if not system:
            return [{"role": "system", "content": note}]
        first = dict(system[0])
        c = first.get("content")
        if isinstance(c, list):
            first["content"] = c + [{"type": "text", "text": note}]
        else:
            first["content"] = f"{_text(c)}\n\n{note}".strip()
        return [first] + system[1:]

    async def _trim(
        self,
        body: dict,
        msgs: list,
        meta: dict,
        user_info: Optional[dict],
        model: Optional[dict],
        request: Any,
        emit: Optional[Callable[[dict], Awaitable[None]]],
    ) -> list:
        v = self.valves
        system = [m for m in msgs if m.get("role") == "system"]
        conv = [m for m in msgs if m.get("role") != "system"]
        if not conv:
            return msgs

        model_id = str(body.get("model") or "")
        scale = self._calibration.get(model_id, 1.0) if v.auto_calibrate else 1.0
        chat_id = str(meta.get("chat_id") or "") or "anon:" + _fingerprint(conv, 1)

        # Open WebUI's built-in compaction runs before filters, with its own threshold
        # (80k tokens by default) and keeps 40 % of the messages. Two compactors on one
        # chat means the history is cut far earlier than this filter would.
        if v.warn_builtin_compaction and emit and chat_id not in self._warned:
            if any(BUILTIN_MARK in _text(m.get("content")) for m in system):
                self._remember(self._warned, chat_id, True)
                await emit(
                    {
                        "type": "status",
                        "data": {
                            "description": "Open WebUI's own context compaction already cut this chat (Admin Panel → Settings → Interface → Context Compaction). Turn it off to let Context Trim manage the context.",
                            "done": True,
                        },
                    }
                )

        # Reuse the previous cut point unless the history before it was edited.
        st = self._get_state(chat_id)
        cut = int(st.get("cut") or 0)
        if cut and (cut >= len(conv) or _fingerprint(conv, cut) != st.get("fp")):
            # Edited or branched: message numbers no longer mean the same thing.
            st, cut = {}, 0
            self._archive(chat_id, conv, [], reset=True)
        summary = st.get("summary") or ""

        # Old images out. Copies only, so fingerprints of the originals stay valid.
        work = list(conv)
        for i in range(cut, len(conv) - max(v.keep_images_in_last, 0)):
            if _image_count(conv[i]):
                work[i] = _without_images(conv[i])

        # One oversized tool result is cut the moment it shows up, and the same way on every
        # later turn, so it never costs the prompt cache.
        cap_chars = int(v.max_tool_result_tokens * v.bytes_per_token) if v.max_tool_result_tokens > 0 else 0
        if cap_chars:
            capped = int(st.get("capped") or 0)
            fresh = []
            for i in range(cut, len(conv)):
                if conv[i].get("role") == "tool":
                    short = self._shorten(conv[i], cap_chars, i + 1)
                    if short is not conv[i]:
                        work[i] = short
                        if i >= capped:
                            fresh.append(i)
            if fresh:
                self._archive(chat_id, conv, fresh)
                st = {**st, "capped": fresh[-1] + 1}
                self._put_state(chat_id, st)

        # Tool results shortened on an earlier turn stay shortened, in exactly the same way.
        prune = min(max(int(st.get("prune") or 0), cut), len(conv)) if v.prune_tool_results else cut
        for i in range(cut, prune):
            if conv[i].get("role") == "tool":
                work[i] = self._pruned(conv[i], i + 1)

        costs: list = []
        suffix: list = []

        def measure() -> None:
            costs[:] = [self._raw_tokens(m) * scale for m in work]
            suffix[:] = [0.0] * (len(work) + 1)
            for i in range(len(work) - 1, -1, -1):
                suffix[i] = suffix[i + 1] + costs[i]

        measure()
        sys_cost = sum(self._raw_tokens(m) for m in system) * scale

        def note_cost(c: int, s: str) -> float:
            if not c:
                return 0.0
            return (len(self._note(c, s).encode("utf-8", "ignore")) / v.bytes_per_token) * scale

        budget = self._budget(body, model)
        before = sys_cost + note_cost(cut, summary) + suffix[cut]
        over = before > budget

        if over and v.prune_tool_results:
            # Step 1: tool results are the bulk of an agentic chat and the least missed.
            # Shorten all but the newest few; the conversation itself stays word for word.
            keep = max(v.keep_full_tool_results, 0)
            tools = [i for i in range(cut, len(work)) if work[i].get("role") == "tool"]
            limit = len(work) if not keep else (tools[-keep] if len(tools) > keep else prune)
            if limit > prune:
                shortened = []
                for i in tools:
                    if prune <= i < limit:
                        short = self._pruned(conv[i], i + 1)
                        if short is not conv[i]:
                            work[i] = short
                            shortened.append(i)
                self._archive(chat_id, conv, shortened)
                shortened = len(shortened)
                prune = limit
                measure()
                st = {**st, "cut": cut, "fp": st.get("fp") or "", "summary": summary, "prune": prune}
                self._put_state(chat_id, st)
                after = sys_cost + note_cost(cut, summary) + suffix[cut]
                if shortened and emit and v.show_status:
                    await emit(
                        {
                            "type": "status",
                            "data": {
                                "description": f"Context: shortened {shortened} old tool results, ~{before / 1000:.1f}k → ~{after / 1000:.1f}k tokens",
                                "done": True,
                            },
                        }
                    )
                before = after

        # Step 2 also runs when step 1 only just got under the budget: a chat that sits at
        # the limit would be trimmed again on the next turn, and every trim makes the
        # backend re-read the conversation.
        ratio = min(max(v.trim_to_ratio, 0.1), 1.0)
        if over and before > budget * (1 + ratio) / 2:
            # Step 2: cut well below the budget so the next trim is many turns away and
            # the backend can keep reusing its prompt cache in between.
            cap = self._summary_cap(budget)
            reserve = cap if v.summarize else 40
            room = budget * ratio - sys_cost - reserve
            users = [i for i, m in enumerate(work) if m.get("role") == "user"]
            last_user = users[-1] if users else len(work) - 1
            new_cut = max(last_user, cut)
            for i in users:
                if i > cut and suffix[i] <= room:
                    new_cut = i
                    break

            if new_cut > cut:
                dropped = work[cut:new_cut]
                self._archive(chat_id, conv, range(cut, new_cut))
                failed = False
                if v.summarize and request is not None:
                    if emit and v.show_status:
                        await emit(
                            {
                                "type": "status",
                                "data": {
                                    "description": f"Condensing {len(dropped)} older messages…",
                                    "done": False,
                                },
                            }
                        )
                    try:
                        options = body.get("options") if isinstance(body.get("options"), dict) else None
                        summary = await self._summarize(
                            request, user_info, model_id, summary, dropped, options, cap
                        )
                    except Exception as e:
                        failed = True
                        log.warning("context_trim: summary failed, dropping instead: %s", e)
                cut = new_cut
                prune = max(prune, cut)
                st = {**st, "cut": cut, "fp": _fingerprint(conv, cut), "summary": summary, "prune": prune}
                self._put_state(chat_id, st)
                if emit and v.show_status:
                    after = sys_cost + note_cost(cut, summary) + suffix[cut]
                    how = "dropped (summary failed)" if failed else (
                        "summarized" if v.summarize and request is not None else "dropped"
                    )
                    await emit(
                        {
                            "type": "status",
                            "data": {
                                "description": f"Context trimmed: {len(dropped)} older messages {how}, ~{before / 1000:.1f}k → ~{after / 1000:.1f}k tokens",
                                "done": True,
                            },
                        }
                    )

        kept = work[cut:]
        kept_costs = costs[cut:]
        total = sys_cost + note_cost(cut, summary) + suffix[cut]
        if total > budget:
            self._squeeze(kept, kept_costs, total - budget, scale)

        if cut:
            system = self._with_note(system, self._note(cut, summary))
        out = system + kept

        if v.auto_calibrate:
            raw = sum(self._raw_tokens(m, images=False) for m in out)
            has_images = any(_image_count(m) for m in out)
            self._remember(self._pending, chat_id, (model_id, raw, has_images))
        return out

    # -------------------------------------------------------------------- hooks

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __request__: Any = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        msgs = body.get("messages")
        meta = __metadata__ or body.get("metadata") or {}
        if (
            not self.valves.enabled
            or not isinstance(msgs, list)
            or len(msgs) < 2
            or meta.get("task")
        ):
            return body
        try:
            body["messages"] = await self._trim(
                body, msgs, meta, __user__, __model__, __request__, __event_emitter__
            )
        except Exception:
            # A trimming bug must never take the chat down with it.
            log.exception("context_trim: trimming failed, sending history untouched")
        return body

    async def outlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        """Compare our estimate with the prompt token count the backend reported."""
        if not self.valves.auto_calibrate:
            return body
        try:
            chat_id = str(body.get("chat_id") or (__metadata__ or {}).get("chat_id") or "")
            pending = self._pending.pop(chat_id, None)
            last = (body.get("messages") or [{}])[-1]
            usage = last.get("usage") or (last.get("info") or {}).get("usage") or last.get("info") or {}
            actual = usage.get("prompt_tokens") or usage.get("prompt_eval_count")
            if pending and actual:
                model_id, raw, has_images = pending
                # Small prompts are dominated by fixed overhead, and image costs are a
                # guess, so neither makes a trustworthy sample.
                if raw >= 8000 and not has_images:
                    sample = float(actual) / raw
                    # Outside this range something else is going on (RAG or tool specs
                    # added after us, a truncated prompt, cached-token under-reporting).
                    # Tool specs and skill lists are a fixed cost, not a factor: a wide range
                    # here would make the whole history look bigger than it is.
                    if 0.7 <= sample <= 1.4:
                        old = self._calibration.get(model_id)
                        self._calibration[model_id] = (
                            sample if old is None else old * 0.7 + sample * 0.3
                        )
        except Exception:
            log.debug("context_trim: calibration skipped", exc_info=True)
        return body
