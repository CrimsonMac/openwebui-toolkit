"""
title: Context Trim
author: Crimson
version: 2.1.0
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
    "Write the updated memory note now. Rules:\n"
    "- Merge the existing note with the new messages; do not lose facts that are still relevant.\n"
    "- Keep: the user's goals and preferences, names, numbers, dates, decisions made, "
    "file names, code identifiers, exact error messages, and anything left unfinished.\n"
    "- Drop: greetings, filler, superseded drafts, and reasoning that led nowhere.\n"
    "- Use short bullet points grouped under: Facts, Decisions, Open tasks.\n"
    "- Write in the language the conversation is held in.\n"
    "- At most {words} words. Output only the note, with no preamble."
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
        summary_max_tokens: int = Field(1000, description="Size cap of the summary.")
        summary_chunk_tokens: int = Field(
            8000, description="How much dropped history is fed to the summary model per call."
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
            budget = max(1024, int(n * v.context_safety) - v.reserve_output_tokens) if n else v.fallback_token_budget
        if v.max_reread_seconds > 0 and v.read_tokens_per_second > 0:
            # A context that fits in memory can still be too big to wait for.
            budget = min(budget, max(1024, int(v.max_reread_seconds * v.read_tokens_per_second)))
        return budget

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
                if not t:
                    continue
                line = f"{str(m.get('role', 'user')).upper()}: {_middle_cut(t, per_msg)}"
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
        self, request: Any, user: Any, model: str, messages: list, chat_model: str = "", chat_options: Optional[dict] = None
    ) -> str:
        from open_webui.utils.chat import generate_chat_completion

        form: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            # Generous, because thinking models spend output tokens before answering.
            "max_tokens": self.valves.summary_max_tokens * 3,
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
    ) -> str:
        from open_webui.models.users import Users

        user = Users.get_user_by_id((user_info or {}).get("id"))
        if inspect.isawaitable(user):
            user = await user

        v = self.valves
        model = self._summary_model(request, chat_model)
        instructions = SUMMARY_INSTRUCTIONS.format(words=int(v.summary_max_tokens * 0.6))
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
                ),
                timeout=v.summary_timeout,
            )
            if not out:
                raise RuntimeError("summary model returned nothing")
            summary = out
        return _middle_cut(summary, int(v.summary_max_tokens * v.bytes_per_token))

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
        head = f"[Context note: the first {cut} messages of this conversation were removed to fit the context window."
        if summary:
            return f"{head} What they contained:]\n{summary}"
        return f"{head} No summary is available; ask the user if something from them is needed.]"

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

        # Reuse the previous cut point unless the history before it was edited.
        st = self._get_state(chat_id)
        cut = int(st.get("cut") or 0)
        if cut and (cut >= len(conv) or _fingerprint(conv, cut) != st.get("fp")):
            st, cut = {}, 0
        summary = st.get("summary") or ""

        # Old images out. Copies only, so fingerprints of the originals stay valid.
        work = list(conv)
        for i in range(cut, len(conv) - max(v.keep_images_in_last, 0)):
            if _image_count(conv[i]):
                work[i] = _without_images(conv[i])

        costs = [self._raw_tokens(m) * scale for m in work]
        suffix = [0.0] * (len(work) + 1)
        for i in range(len(work) - 1, -1, -1):
            suffix[i] = suffix[i + 1] + costs[i]
        sys_cost = sum(self._raw_tokens(m) for m in system) * scale

        def note_cost(c: int, s: str) -> float:
            if not c:
                return 0.0
            return (len(self._note(c, s).encode("utf-8", "ignore")) / v.bytes_per_token) * scale

        budget = self._budget(body, model)
        before = sys_cost + note_cost(cut, summary) + suffix[cut]

        if before > budget:
            # Cut well below the budget so the next trim is many turns away and the
            # backend can keep reusing its prompt cache in between.
            reserve = v.summary_max_tokens if v.summarize else 40
            room = budget * min(max(v.trim_to_ratio, 0.1), 1.0) - sys_cost - reserve
            users = [i for i, m in enumerate(work) if m.get("role") == "user"]
            last_user = users[-1] if users else len(work) - 1
            new_cut = max(last_user, cut)
            for i in users:
                if i > cut and suffix[i] <= room:
                    new_cut = i
                    break

            if new_cut > cut:
                dropped = work[cut:new_cut]
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
                            request, user_info, model_id, summary, dropped, options
                        )
                    except Exception as e:
                        failed = True
                        log.warning("context_trim: summary failed, dropping instead: %s", e)
                cut = new_cut
                self._put_state(
                    chat_id,
                    {"cut": cut, "fp": _fingerprint(conv, cut), "summary": summary},
                )
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
                if raw >= 2000 and not has_images:
                    sample = float(actual) / raw
                    # Outside this range something else is going on (RAG or tool specs
                    # added after us, a truncated prompt, cached-token under-reporting).
                    if 0.6 <= sample <= 2.0:
                        old = self._calibration.get(model_id)
                        self._calibration[model_id] = (
                            sample if old is None else old * 0.7 + sample * 0.3
                        )
        except Exception:
            log.debug("context_trim: calibration skipped", exc_info=True)
        return body
