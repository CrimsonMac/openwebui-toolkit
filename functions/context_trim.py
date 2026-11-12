"""
title: Context Trim
author: Crimson
version: 3.0.0
required_open_webui_version: 0.5.0
description: Keeps long agentic chats inside the context window without losing the thread. Works on every tool round, not only on the first request of a turn. Old tool results are shortened first, then the oldest work is folded into a rolling summary while the current request stays pinned. Everything removed stays readable through the Chat History tool, and token estimates are corrected from the real counts the backend reports.
"""

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import tempfile
import time
import urllib.request
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("context_trim")

IMAGE_PLACEHOLDER = "[image removed from history]"
MAX_SUMMARY_CHUNKS = 6
MAX_CHATS_IN_MEMORY = 512
# Options that make Ollama reload a model when they differ from the loaded runner.
LOAD_OPTIONS = ("num_ctx", "num_batch", "num_gpu", "num_thread", "use_mmap", "use_mlock", "main_gpu", "numa")

_NOISE = re.compile(
    r"<think>.*?</think>|<details\b[^>]*type=\"(?:reasoning|tool_calls|code_interpreter)\"[^>]*>.*?</details>",
    re.DOTALL | re.IGNORECASE,
)

SUMMARY_SYSTEM = (
    "You maintain the working memory of an AI assistant that is in the middle of a long task. "
    "You are given the existing memory note (possibly empty), the request the assistant is "
    "currently working on, and the next part of the conversation, which is about to be deleted "
    "from the assistant's context. Write the updated memory note."
)

SUMMARY_INSTRUCTIONS = (
    "Write the updated memory note now. The assistant will rely on it to continue the work "
    "without the deleted messages, so it must say what was asked, what was done and where things stand. Rules:\n"
    "- Merge the existing note with the new messages; do not lose facts that are still relevant.\n"
    "- Be specific. Keep exact names, numbers, dates, versions, file paths, commands, code identifiers, "
    "URLs and error messages. Never write 'various' or 'several' in place of the actual items.\n"
    "- Record the work, not just the topic: which tools were called and what they returned, which commands "
    "were run and their results, what was written or changed.\n"
    "- Record every approach that failed and why, so it is not tried again.\n"
    "- If a task is still in progress, list the finished steps in order and state the exact next step.\n"
    "- Drop: greetings, filler, superseded drafts, and reasoning that led nowhere.\n"
    "- Use short bullet points under these headings, leaving out empty ones: "
    "Goal, Facts, Work done, Failed attempts, Decisions, Current state, Next step.\n"
    "- Write in the language the conversation is held in.\n"
    "- At most {words} words. Output only the note, with no preamble."
)

BUILTIN_MARK = "[CONVERSATION SUMMARY]"

# The note this filter leaves in the system prompt. The tags let it find and replace its own
# note when it sees an already trimmed conversation again, which happens on every tool round.
NOTE_OPEN = "<context_note>"
NOTE_CLOSE = "</context_note>"
NOTE_SUMMARY_HEAD = "Summary of the removed messages:"
_NOTE_RE = re.compile(r"\n\n<context_note>.*?</context_note>", re.DOTALL)
_NOTE_COUNT_RE = re.compile(r"The first (\d+) messages")

PRUNED = (
    "\n[... part of this tool result was removed to save context. Full text: "
    "read_chat_message(number={k}) if you have the chat history tool, or call the tool again ...]\n"
)
_PRUNED_RE = re.compile(r"\n\[\.\.\. part of this tool result was removed to save context\. Full text: read_chat_message\(number=(\d+)\)[^\]]*\]\n")


_ALNUM = re.compile(r"[^\W_]+", re.UNICODE)
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"  +")
_token_cache: "OrderedDict[tuple, float]" = OrderedDict()


def _count_tokens(text: str) -> float:
    """Estimate the tokens in a text from what it is made of.

    Bytes per token is not a constant: measured on a Qwen tokenizer, prose and code take
    about 4 bytes per token, but JSON, log lines, numbers and hex ids only about 1.5,
    because digits and punctuation are one token each. A single ratio therefore counts
    tool output at half its real size. The weights below were fitted to real token counts
    of 16 kinds of text and land between 0.85 and 1.25 of the truth on each.
    """
    if len(text) < 64:
        return len(text) / 2.5
    key = (len(text), hash(text))
    hit = _token_cache.get(key)
    if hit is not None:
        return hit
    words = letters = wide = odd = digits = 0
    for run in _ALNUM.findall(text):
        n = len(run)
        if n <= 14 and run.isalpha():
            words += 1
            letters += n
            if not run.isascii():
                wide += sum(1 for c in run if ord(c) > 127)
        elif run.isdigit():
            digits += n
        else:
            # Ids, hex, base64 and other runs that are not words break into many tokens.
            d = sum(1 for c in run if c.isdigit())
            digits += d
            odd += n - d
    punct = len(_PUNCT.findall(text))
    breaks = text.count("\n") + len(_SPACES.findall(text))
    tokens = 0.4 * words + 0.17 * letters + 0.45 * wide + 0.75 * odd + 1.05 * digits + 0.8 * punct + 1.0 * breaks
    _token_cache[key] = tokens
    if len(_token_cache) > 8192:
        _token_cache.popitem(last=False)
    return tokens


def _chars_per_token(text: str) -> float:
    """How dense a text is, judged by its first 800 characters so the answer is the same
    for a tool result and for an already shortened copy of it."""
    head = text[:800]
    if len(head) < 64:
        return 3.0
    return min(max(len(head) / max(_count_tokens(head), 1.0), 1.2), 5.0)


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


def _key(m: dict) -> str:
    """Identity of a message that survives everything this filter does to it.

    Built from the role, the tool call ids and the start of the text, so a message is
    recognised both in the full history and in an already trimmed copy of it.
    """
    text = _text(m.get("content")).replace(IMAGE_PLACEHOLDER, "").strip()
    calls = ",".join(str((c or {}).get("id") or "") for c in m.get("tool_calls") or [] if isinstance(c, dict))
    raw = f"{m.get('role')}|{m.get('tool_call_id') or ''}|{calls}|{text[:300]}"
    return hashlib.blake2b(raw.encode("utf-8", "ignore"), digest_size=10).hexdigest()


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


def _same_model(a: str, b: str) -> bool:
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return False
    return a == b or a.split(":latest")[0] == b.split(":latest")[0]


def _ollama_context(urls: list, names: list, timeout: float = 3.0) -> int:
    """Ask Ollama what context size a model runs with. Blocking; call it in a thread."""
    for base in urls:
        base = str(base or "").rstrip("/")
        if not base:
            continue
        try:
            # A loaded model reports the context it was really started with.
            with urllib.request.urlopen(f"{base}/api/ps", timeout=timeout) as r:
                loaded = json.load(r).get("models") or []
            for entry in loaded:
                if any(_same_model(entry.get("name"), n) or _same_model(entry.get("model"), n) for n in names):
                    n = int(entry.get("context_length") or 0)
                    if n > 0:
                        return n
        except Exception as e:
            log.debug("context_trim: /api/ps failed on %s: %s", base, e)
        for name in names:
            try:
                req = urllib.request.Request(
                    f"{base}/api/show",
                    json.dumps({"model": name}).encode("utf-8"),
                    {"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    shown = json.load(r)
                found = re.search(r"^\s*num_ctx\s+(\d+)", str(shown.get("parameters") or ""), re.MULTILINE)
                if found:
                    return int(found.group(1))
            except Exception as e:
                log.debug("context_trim: /api/show failed on %s: %s", base, e)
    return 0


class Filter:
    class Valves(BaseModel):
        priority: int = Field(0, description="Filter order; lower runs first.")
        enabled: bool = Field(True, description="Master switch.")
        token_budget: int = Field(
            0,
            description="Max prompt tokens. 0 = automatic: context size × context_safety − reserve_output_tokens.",
        )
        fallback_token_budget: int = Field(
            200000,
            description="Budget used when token_budget is 0 and no context size is known, for models that are not served by Ollama.",
        )
        ollama_fallback_token_budget: int = Field(
            28000,
            description="Budget used for an Ollama model whose context size could not be found on the request, the model or by asking Ollama. Kept small on purpose: a prompt larger than the context is cut by Ollama without notice. A warning is shown when this is used.",
        )
        context_safety: float = Field(
            0.9, description="Fraction of the context size to fill at most."
        )
        reserve_output_tokens: int = Field(
            8192, description="Room left for the reply (thinking included) when the budget is automatic."
        )
        trim_to_ratio: float = Field(
            0.7,
            description="Shortening old tool results must bring the chat below this fraction of the budget; if it does not, the oldest messages are removed as well.",
        )
        cut_to_ratio: float = Field(
            0.5,
            description="When messages are removed, remove enough to get down to this fraction of the budget. Lower = fewer trims and longer-lived prompt cache, but less history kept word for word.",
        )
        keep_images_in_last: int = Field(
            4, description="Keep images only in the last N messages."
        )
        image_tokens: int = Field(1000, description="Estimated cost of one kept image.")
        summarize: bool = Field(
            True,
            description="Fold removed messages into a rolling summary instead of just deleting them.",
        )
        summary_model: str = Field(
            "",
            description="Model that writes summaries. Empty = the chat's own model (already loaded, no model swap). 'task' = Open WebUI's task model. Or any model id.",
        )
        prune_tool_results: bool = Field(
            True,
            description="When over budget, first shorten old tool results (fetched pages, command output) and keep the conversation itself. Messages are only removed if that is not enough.",
        )
        keep_full_tool_results: int = Field(
            4, description="The newest this-many tool results are never shortened. Results the model has not answered yet are never shortened either."
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
            description="Assumed cost of what Open WebUI adds after this filter (tool definitions, skill list, documents) until real token counts have been seen for the chat.",
        )
        archive: bool = Field(
            True,
            description="Keep everything that was shortened or removed on disk, so the Chat History tool can still search and read it.",
        )
        summary_max_tokens: int = Field(
            0, description="Size cap of the summary. 0 = automatic: 3 % of the budget, between 1200 and 4000 tokens."
        )
        summary_chunk_tokens: int = Field(
            24000, description="How much removed history is fed to the summary model per call."
        )
        summary_num_ctx: int = Field(
            32768,
            description="num_ctx sent with summary calls when the summary model is a different Ollama model than the chat's. 0 = leave that model's own setting.",
        )
        summary_timeout: int = Field(240, description="Seconds allowed per summary call.")
        auto_calibrate: bool = Field(
            True,
            description="Correct the token estimate from the prompt token counts the backend reports after every request.",
        )
        ollama_url: str = Field(
            "",
            description="Where to ask for a model's context size when the request does not carry num_ctx. Empty = Open WebUI's own Ollama connections.",
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
        self._archives: "OrderedDict[str, dict]" = OrderedDict()
        self._factor: Optional[dict] = None
        self._ctx_cache: dict = {}
        self._warned: "OrderedDict[str, bool]" = OrderedDict()

    # ---------------------------------------------------------------- estimates

    def _raw_tokens(self, m: dict, images: bool = True) -> float:
        """Token estimate before calibration: every field that is sent counts, not only the text."""
        tokens = _count_tokens(_text(m.get("content"))) + 4
        extra = {k: v for k, v in m.items() if k not in ("role", "content", "images")}
        if extra:
            tokens += _count_tokens(json.dumps(extra, default=str, ensure_ascii=False))
        if images:
            tokens += _image_count(m) * self.valves.image_tokens
        return tokens

    def _factors(self) -> dict:
        if self._factor is None:
            self._factor = {}
            if self.valves.persist_state:
                try:
                    with open(os.path.join(_state_dir(), "calibration.json"), encoding="utf-8") as f:
                        data = json.load(f)
                    self._factor = {str(k): float(x) for k, x in data.items()}
                except (OSError, ValueError, TypeError, AttributeError):
                    self._factor = {}
        return self._factor

    def _k(self, model_id: str) -> float:
        if not self.valves.auto_calibrate:
            return 1.0
        return min(max(self._factors().get(model_id, 1.0), 0.85), 2.5)

    def _overhead(self, st: dict, model_id: str) -> float:
        """Tokens the backend counts on top of the messages: tool definitions, template, skills."""
        sample = st.get("sample") if self.valves.auto_calibrate else None
        if isinstance(sample, dict) and sample.get("model") == model_id:
            seen = float(sample.get("actual") or 0) - self._k(model_id) * float(sample.get("raw") or 0)
            return min(max(seen, 0.0), 60000.0)
        return float(max(self.valves.overhead_tokens, 0))

    def _record_usage(self, chat_id: str, usage: Any) -> None:
        """Compare the estimate of the request just sent with what the backend counted."""
        if not self.valves.auto_calibrate or not isinstance(usage, dict):
            return
        actual = usage.get("prompt_tokens") or usage.get("prompt_eval_count") or usage.get("input_tokens")
        try:
            actual = int(actual or 0)
        except (TypeError, ValueError):
            return
        pending = self._pending.pop(chat_id, None)
        if not pending or actual <= 0:
            return
        model_id, raw, has_images, ctx = pending
        # A prompt at the context limit was cut by the backend, and image costs are a guess.
        if has_images or raw < 500 or (ctx and actual >= ctx * 0.97):
            return
        if not 0.4 <= actual / raw <= 6.0 and raw > 4000:
            return
        st = self._get_state(chat_id)
        prev = st.get("sample")
        if isinstance(prev, dict) and prev.get("model") == model_id:
            d_raw = raw - float(prev.get("raw") or 0)
            d_actual = actual - float(prev.get("actual") or 0)
            if abs(d_raw) >= 2000:
                k = d_actual / d_raw
                if 0.5 <= k <= 2.5:
                    factors = self._factors()
                    old = factors.get(model_id)
                    factors[model_id] = k if old is None else old * 0.7 + k * 0.3
                    self._save_factors()
        st = {**st, "sample": {"model": model_id, "raw": round(raw, 1), "actual": actual}}
        self._put_state(chat_id, st)

    def _save_factors(self) -> None:
        if not self.valves.persist_state:
            return
        try:
            os.makedirs(_state_dir(), exist_ok=True)
            path = os.path.join(_state_dir(), "calibration.json")
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self._factor or {}, f)
            os.replace(path + ".tmp", path)
        except OSError as e:
            log.warning("context_trim: could not save calibration: %s", e)

    async def _context_size(self, body: dict, model: Optional[dict], request: Any) -> int:
        """The context size the model really runs with: from the request, the model settings, or Ollama."""
        n = _find_num_ctx(body, model)
        if n:
            return n
        model_id = str(body.get("model") or "")
        cached = self._ctx_cache.get(model_id)
        if cached and time.monotonic() - cached[1] < (600 if cached[0] else 60):
            return cached[0]
        names = [model_id]
        base_id = ((model or {}).get("info") or {}).get("base_model_id")
        if base_id:
            names.append(str(base_id))
        urls = [u.strip() for u in self.valves.ollama_url.split(";") if u.strip()]
        if not urls:
            try:
                urls = list(request.app.state.config.OLLAMA_BASE_URLS or [])
            except Exception:
                urls = []
        n = 0
        if urls and model_id:
            try:
                n = await asyncio.to_thread(_ollama_context, urls, names)
            except Exception as e:
                log.debug("context_trim: context size lookup failed: %s", e)
        self._ctx_cache[model_id] = (n, time.monotonic())
        return n

    def _budget(self, n: int, ollama: bool = False) -> int:
        v = self.valves
        if v.token_budget > 0:
            budget = v.token_budget
        elif n:
            budget = max(1024, int(n * v.context_safety) - min(v.reserve_output_tokens, n // 4))
        else:
            budget = v.ollama_fallback_token_budget if ollama else v.fallback_token_budget
        if v.max_reread_seconds > 0 and v.read_tokens_per_second > 0:
            # A context that fits in memory can still be too big to wait for.
            budget = min(budget, max(1024, int(v.max_reread_seconds * v.read_tokens_per_second)))
        return budget

    @staticmethod
    def _is_ollama(model_id: str, model: Optional[dict], request: Any) -> bool:
        model = model or {}
        if model.get("owned_by") == "ollama" or "ollama" in model:
            return True
        try:
            return (request.app.state.MODELS.get(model_id) or {}).get("owned_by") == "ollama"
        except Exception:
            return False

    def _summary_cap(self, budget: int) -> int:
        if self.valves.summary_max_tokens > 0:
            return self.valves.summary_max_tokens
        return min(max(int(budget * 0.03), 1200), 4000)

    # ------------------------------------------------------------------ archive

    def _archive_path(self, chat_id: str) -> str:
        name = hashlib.sha1(chat_id.encode("utf-8", "ignore")).hexdigest()
        return os.path.join(_state_dir(), "archive", f"{name}.json")

    def _archive_load(self, chat_id: str) -> dict:
        """The stored messages of a chat: {"data": number -> entry, "index": hash -> number}."""
        if chat_id in self._archives:
            self._archives.move_to_end(chat_id)
            return self._archives[chat_id]
        data: dict = {}
        if self._archive_on(chat_id):
            try:
                with open(self._archive_path(chat_id), encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, ValueError):
                data = {}
        index = {}
        for number, entry in data.items():
            if isinstance(entry, dict) and entry.get("h"):
                index[entry["h"]] = int(number)
        arc = {"data": data, "index": index, "dirty": False}
        self._remember(self._archives, chat_id, arc)
        return arc

    def _archive_on(self, chat_id: str) -> bool:
        return bool(self.valves.archive and self.valves.persist_state and not chat_id.startswith("anon:"))

    def _archive_add(self, chat_id: str, m: dict) -> int:
        """Store the full text of a message and return the number it can be read back with.

        The number belongs to the content, not to a position, so the same message gets the
        same number whether it is seen in the full history or in a trimmed copy.
        """
        text = _text(m.get("content"))
        for call in m.get("tool_calls") or []:
            fn = (call or {}).get("function") or {}
            args = fn.get("arguments")
            args = args if isinstance(args, str) else json.dumps(args, default=str)
            text = f"{text}\n[called tool {fn.get('name', '?')} with {args}]".strip()
        if not text:
            return 0
        arc = self._archive_load(chat_id)
        h = hashlib.blake2b(
            f"{m.get('role')}|{m.get('tool_call_id') or ''}|{text}".encode("utf-8", "ignore"), digest_size=12
        ).hexdigest()
        if h in arc["index"]:
            return arc["index"][h]
        number = max((int(n) for n in arc["data"]), default=0) + 1
        arc["data"][str(number)] = {"role": m.get("role"), "name": m.get("name") or "", "text": text, "h": h}
        arc["index"][h] = number
        arc["dirty"] = True
        return number

    def _archive_flush(self, chat_id: str) -> None:
        arc = self._archives.get(chat_id)
        if not arc or not arc["dirty"]:
            return
        arc["dirty"] = False
        if not self._archive_on(chat_id):
            return
        path = self._archive_path(chat_id)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(arc["data"], f, ensure_ascii=False)
            os.replace(path + ".tmp", path)
        except OSError as e:
            log.warning("context_trim: could not write the archive: %s", e)

    def _shorten(self, chat_id: str, m: dict, keep: int) -> dict:
        """Tool message with the middle of a long result removed.

        Gives the same text whether it starts from the original result or from a copy that
        was already shortened less, so the prompt stays identical from one request to the next.
        """
        text = _text(m.get("content"))
        keep = max(keep, 200)
        mark = _PRUNED_RE.search(text)
        if mark:
            head, tail, number = text[: mark.start()], text[mark.end():], int(mark.group(1))
            if len(head) + len(tail) <= keep + 300:
                return m
        else:
            if len(text) <= keep + 300:
                return m
            head = tail = text
            number = self._archive_add(chat_id, m)
        h = int(keep * 0.7)
        t = keep - h
        return {**m, "content": f"{head[:h]}{PRUNED.format(k=number)}{tail[len(tail) - t:]}"}

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
        if not isinstance(st, dict) or (st.get("cut") and not st.get("anchor")):
            # Unknown or pre-3.0 state (position based): start over rather than misread it.
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
        """Render removed messages as transcript chunks sized for the summary model."""
        chunk_chars = int(self.valves.summary_chunk_tokens * 3)
        per_msg = max(chunk_chars // 6, 400)
        chunks: list = []
        for _ in range(2):
            chunks, cur, size = [], [], 0
            for m in msgs:
                t = _NOISE.sub("", _text(m.get("content"))).strip()
                role = str(m.get("role", "user")).upper()
                if m.get("role") == "tool":
                    # What a tool returned is part of what was done; an excerpt is enough.
                    role = f"TOOL RESULT ({m.get('name') or 'tool'})"
                    t = _middle_cut(t, min(per_msg, 2000))
                for call in m.get("tool_calls") or []:
                    fn = (call or {}).get("function") or {}
                    args = fn.get("arguments")
                    args = args if isinstance(args, str) else json.dumps(args, default=str)
                    t = f"{t}\n[called tool {fn.get('name', '?')} with {_middle_cut(args or '', 400)}]".strip()
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
        current_request: str = "",
    ) -> str:
        from open_webui.models.users import Users

        user = Users.get_user_by_id((user_info or {}).get("id"))
        if inspect.isawaitable(user):
            user = await user

        v = self.valves
        model = self._summary_model(request, chat_model)
        instructions = SUMMARY_INSTRUCTIONS.format(words=int(cap * 0.6))
        task = _middle_cut(_NOISE.sub("", current_request).strip(), 3000)
        summary = previous
        for chunk in self._chunks(dropped):
            prompt = (
                f"<existing_note>\n{summary or '(empty)'}\n</existing_note>\n\n"
                f"<current_request>\n{task or '(none)'}\n</current_request>\n\n"
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
        return _middle_cut(summary, int(cap * 4))

    # ----------------------------------------------------------------- trimming

    def _squeeze(self, kept: list, costs: list, excess: float, k: float) -> None:
        """Last resort: what must be kept is still over budget, so cut the middle out of its biggest messages."""
        for i in sorted(range(len(kept)), key=lambda j: costs[j], reverse=True):
            if excess <= 0:
                return
            m = kept[i]
            text = _text(m.get("content"))
            if len(text) < 2000:
                continue
            bpt = len(text) / max(_count_tokens(text), 1.0)
            remove_chars = min(int(excess / k * bpt) + 200, len(text) - 1000)
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
            excess -= (len(text) - len(new_text)) / bpt * k

    @staticmethod
    def _note(dropped: int, summary: str) -> str:
        head = (
            f"{NOTE_OPEN}\nThe first {dropped} messages of this conversation were removed to fit the context window. "
            "Their full text is still stored: if you need an exact detail from them and have the chat history tool, "
            "use search_chat_history or read_chat_message instead of guessing or repeating the work. "
            "Work listed below as done is finished: do not do it again, continue from the current state."
        )
        if summary:
            return f"{head}\n{NOTE_SUMMARY_HEAD}\n{summary}\n{NOTE_CLOSE}"
        return f"{head}\nNo summary is available.\n{NOTE_CLOSE}"

    @staticmethod
    def _take_note(system: list) -> tuple:
        """Remove this filter's own note from the system messages. Returns (system, note text or '')."""
        found = ""
        out = []
        for m in system:
            c = m.get("content")
            if isinstance(c, str) and NOTE_OPEN in c:
                hit = _NOTE_RE.search(c)
                if hit:
                    found = hit.group(0)
                    c = _NOTE_RE.sub("", c)
                    if not c:
                        continue  # a system message that only held the note
                    m = {**m, "content": c}
            elif isinstance(c, list):
                parts = []
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text" and NOTE_OPEN in str(p.get("text")):
                        hit = _NOTE_RE.search(p["text"])
                        if hit:
                            found = hit.group(0)
                            continue
                    parts.append(p)
                if len(parts) != len(c):
                    m = {**m, "content": parts}
            out.append(m)
        return out, found

    @staticmethod
    def _swap_note(system: list, old: str, new: str) -> list:
        """Put the current note exactly where the previous one stood."""
        out = []
        for m in system:
            c = m.get("content")
            if isinstance(c, str) and old in c:
                c = c.replace(old, new, 1)
                if not c:
                    continue
                m = {**m, "content": c}
            elif isinstance(c, list):
                parts = []
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text" and old in str(p.get("text")):
                        text = p["text"].replace(old, new, 1)
                        if not text:
                            continue
                        p = {**p, "text": text}
                    parts.append(p)
                m = {**m, "content": parts}
            out.append(m)
        return out

    @staticmethod
    def _with_note(system: list, note: str) -> list:
        if not system:
            return [{"role": "system", "content": f"\n\n{note}"}]
        first = dict(system[0])
        c = first.get("content")
        if isinstance(c, list):
            first["content"] = c + [{"type": "text", "text": f"\n\n{note}"}]
        else:
            first["content"] = f"{_text(c)}\n\n{note}"
        return [first] + system[1:]

    @staticmethod
    def _locate(conv: list, keys: list, key: str, after: str, want: Optional[int]) -> int:
        """Index of the message with this key, or -1. `after` and `want` settle duplicates."""
        hits = [i for i, k in enumerate(keys) if k == key and conv[i].get("role") != "tool"]
        if not hits:
            return -1
        if len(hits) > 1 and after:
            exact = [i for i in hits if i + 1 < len(keys) and keys[i + 1] == after]
            hits = exact or hits
        if want is None:
            return hits[0]
        return min(hits, key=lambda i: abs(i - want))

    async def _status(self, emit: Any, text: str, done: bool = True) -> None:
        if emit and self.valves.show_status:
            try:
                await emit({"type": "status", "data": {"description": text, "done": done}})
            except Exception:
                pass

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
        chat_id = str(meta.get("chat_id") or "") or "anon:" + _key(conv[0])
        k = self._k(model_id)

        # Open WebUI's built-in compaction runs before filters, with its own threshold
        # (80k tokens by default) and keeps 40 % of the messages. Two compactors on one
        # chat means the history is cut far earlier than this filter would.
        if v.warn_builtin_compaction and emit and chat_id not in self._warned:
            if any(BUILTIN_MARK in _text(m.get("content")) for m in system):
                self._remember(self._warned, chat_id, True)
                await self._status(
                    emit,
                    "Open WebUI's own context compaction already cut this chat (Admin Panel → Settings → Interface → Context Compaction). Turn it off to let Context Trim manage the context.",
                )

        # On tool rounds Open WebUI hands back the conversation as this filter left it at
        # the start of the turn, note included. Take the note out; the current one goes back in below.
        # It is replaced where it stands: other filters may have added their own text after it,
        # and moving the note would change the start of the prompt and cost the prompt cache.
        placed = system
        system, old_note = self._take_note(system)
        st = self._get_state(chat_id)
        keys = [_key(m) for m in conv]

        # Where the kept part starts. Found by content, so it works on the full history
        # and on an already trimmed copy alike.
        cut = 0
        if st.get("anchor"):
            want = None if old_note else int(st.get("dropped") or 0)
            cut = self._locate(conv, keys, st["anchor"], st.get("anchor_next") or "", want)
            if cut < 0:
                cut = 0
                if not old_note:
                    # The message the cut was made at is gone: the history was edited or branched.
                    st = {"sample": st.get("sample")} if st.get("sample") else {}
                    self._put_state(chat_id, st)
        elif old_note:
            # Trimmed earlier but the stored state is gone (restart without persistence):
            # keep what the note said rather than lose it.
            body_text = old_note.split(NOTE_SUMMARY_HEAD, 1)
            count = _NOTE_COUNT_RE.search(old_note)
            st = {
                **st,
                "dropped": int(count.group(1)) if count else 1,
                "summary": body_text[1].replace(NOTE_CLOSE, "").strip() if len(body_text) > 1 else "",
            }
        summary = st.get("summary") or ""
        dropped_total = int(st.get("dropped") or 0)

        work = list(conv)

        # Old images out.
        for i in range(cut, len(conv) - max(v.keep_images_in_last, 0)):
            if _image_count(conv[i]):
                work[i] = _without_images(conv[i])

        # One oversized tool result is cut the moment it shows up, and the same way on every
        # later request, so it never costs the prompt cache.
        if v.max_tool_result_tokens > 0:
            for i in range(cut, len(conv)):
                if conv[i].get("role") == "tool":
                    dense = _chars_per_token(_text(conv[i].get("content")))
                    work[i] = self._shorten(chat_id, work[i], int(v.max_tool_result_tokens * dense))

        # Tool results shortened on an earlier request stay shortened, in exactly the same way.
        prune = cut
        if v.prune_tool_results and st.get("prune"):
            at = self._locate(conv, keys, st["prune"], "", len(conv))
            prune = max(at, cut)
        for i in range(cut, prune):
            if conv[i].get("role") == "tool":
                work[i] = self._shorten(chat_id, work[i], v.pruned_tool_chars)

        raws: list = []
        suffix: list = []

        def measure() -> None:
            raws[:] = [self._raw_tokens(m) for m in work]
            suffix[:] = [0.0] * (len(work) + 1)
            for i in range(len(work) - 1, -1, -1):
                suffix[i] = suffix[i + 1] + raws[i]

        def pin_for(c: int) -> int:
            """The request that started the work the kept part belongs to, or -1 if it is kept anyway."""
            if c <= 0 or conv[c].get("role") == "user":
                return -1
            for i in range(c - 1, -1, -1):
                if conv[i].get("role") == "user":
                    return i
            return -1

        def note_raw(n: int, s: str) -> float:
            if not n:
                return 0.0
            return _count_tokens(self._note(n, s))

        measure()
        sys_raw = sum(self._raw_tokens(m) for m in system)
        overhead = self._overhead(st, model_id)

        def total(c: int, n: int, s_raw: float) -> float:
            p = pin_for(c)
            return overhead + k * (sys_raw + s_raw + (raws[p] if p >= 0 else 0.0) + suffix[c])

        ctx = await self._context_size(body, model, request)
        ollama = self._is_ollama(model_id, model, request)
        budget = self._budget(ctx, ollama)
        if not ctx and ollama and v.token_budget <= 0 and chat_id + "|ctx" not in self._warned:
            self._remember(self._warned, chat_id + "|ctx", True)
            await self._status(
                emit,
                f"Context Trim could not find the context size of {model_id}; using a small budget of {budget} tokens. Set num_ctx on the model in Open WebUI, or token_budget or ollama_url in this filter's valves.",
            )
        before = total(cut, dropped_total, note_raw(dropped_total, summary))
        over = before > budget

        if over and v.prune_tool_results:
            # Step 1: tool results are the bulk of an agentic chat and the least missed.
            # Shorten all but the newest few; the conversation itself stays word for word.
            keep = max(v.keep_full_tool_results, 1)
            tools = [i for i in range(cut, len(work)) if work[i].get("role") == "tool"]
            if len(tools) > keep:
                # Stop at the assistant message that made the calls, so a round of results
                # is never half shortened and unread results stay whole.
                limit = tools[-keep]
                while limit > cut and conv[limit].get("role") == "tool":
                    limit -= 1
                if limit > prune:
                    shortened = 0
                    for i in tools:
                        if prune <= i < limit:
                            short = self._shorten(chat_id, work[i], v.pruned_tool_chars)
                            if short is not work[i]:
                                work[i] = short
                                shortened += 1
                    prune = limit
                    st = {**st, "prune": keys[limit]}
                    self._put_state(chat_id, st)
                    if shortened:
                        measure()
                        after = total(cut, dropped_total, note_raw(dropped_total, summary))
                        await self._status(
                            emit,
                            f"Context: shortened {shortened} old tool results, ~{before / 1000:.1f}k → ~{after / 1000:.1f}k tokens",
                        )
                        before = after

        # Step 2 also runs when step 1 got under the budget but not far: a chat that sits
        # near the limit would be trimmed again within a few requests, and every trim makes
        # the backend re-read part of the conversation.
        ratio = min(max(v.trim_to_ratio, 0.1), 1.0)
        target = budget * min(max(v.cut_to_ratio, 0.1), ratio)
        if over and before > budget * ratio:
            cap = self._summary_cap(budget)
            reserve = float(cap if v.summarize else 60)
            # The newest point a cut may be made at: the last request, or the assistant
            # message whose tool results are the newest thing in the chat.
            last = len(conv) - 1
            while last > cut and conv[last].get("role") == "tool":
                last -= 1
            new_cut = cut
            for i in range(cut + 1, last + 1):
                if conv[i].get("role") == "tool":
                    continue
                new_cut = i
                if total(i, 0, reserve) <= target:
                    break

            if new_cut > cut:
                gone = work[cut:new_cut]
                for m in gone:
                    if not _PRUNED_RE.search(_text(m.get("content"))):
                        self._archive_add(chat_id, m)
                failed = False
                if v.summarize and request is not None:
                    await self._status(emit, f"Condensing {len(gone)} older messages…", done=False)
                    try:
                        options = body.get("options") if isinstance(body.get("options"), dict) else None
                        users = [m for m in conv if m.get("role") == "user"]
                        summary = await self._summarize(
                            request,
                            user_info,
                            model_id,
                            summary,
                            gone,
                            options,
                            cap,
                            _text(users[-1].get("content")) if users else "",
                        )
                    except Exception as e:
                        failed = True
                        log.warning("context_trim: summary failed, dropping instead: %s", e)
                dropped_total += new_cut - cut
                cut = new_cut
                prune = max(prune, cut)
                st = {
                    **st,
                    "anchor": keys[cut],
                    "anchor_next": keys[cut + 1] if cut + 1 < len(keys) else "",
                    "dropped": dropped_total,
                    "summary": summary,
                }
                self._put_state(chat_id, st)
                after = total(cut, dropped_total, note_raw(dropped_total, summary))
                how = "dropped (summary failed)" if failed else (
                    "summarized" if v.summarize and request is not None else "dropped"
                )
                await self._status(
                    emit,
                    f"Context trimmed: {len(gone)} older messages {how}, ~{before / 1000:.1f}k → ~{after / 1000:.1f}k tokens",
                )

        self._archive_flush(chat_id)

        pin = pin_for(cut)
        if pin >= 0 and _image_count(work[pin]):
            work[pin] = _without_images(work[pin])
        kept = ([work[pin]] if pin >= 0 else []) + work[cut:]
        kept_raws = ([raws[pin]] if pin >= 0 else []) + raws[cut:]
        final = total(cut, dropped_total, note_raw(dropped_total, summary))
        if final > budget:
            self._squeeze(kept, kept_raws, final - budget, k)

        note = self._note(dropped_total, summary) if dropped_total else ""
        if old_note:
            system = self._swap_note(placed, old_note, f"\n\n{note}" if note else "")
        elif note:
            system = self._with_note(system, note)
        out = system + kept

        if v.auto_calibrate:
            raw = sum(self._raw_tokens(m, images=False) for m in out)
            has_images = any(_image_count(m) for m in out)
            self._remember(self._pending, chat_id, (model_id, raw, has_images, ctx))
        return out

    # -------------------------------------------------------------------- hooks

    async def _run(
        self,
        body: dict,
        user: Optional[dict],
        metadata: Optional[dict],
        model: Optional[dict],
        request: Any,
        emit: Optional[Callable[[dict], Awaitable[None]]],
    ) -> dict:
        msgs = body.get("messages") if isinstance(body, dict) else None
        meta = metadata or (body.get("metadata") if isinstance(body, dict) else None) or {}
        if (
            not self.valves.enabled
            or not isinstance(msgs, list)
            or len(msgs) < 2
            or meta.get("task")
        ):
            return body
        try:
            body["messages"] = await self._trim(body, msgs, meta, user, model, request, emit)
        except Exception:
            # A trimming bug must never take the chat down with it.
            log.exception("context_trim: trimming failed, sending history untouched")
        return body

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __request__: Any = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        """First request of a turn."""
        return await self._run(body, __user__, __metadata__, __model__, __request__, __event_emitter__)

    async def request(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __request__: Any = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        """Every request to the model, including each round of a tool loop (Open WebUI 0.13 and later).

        Without this hook nothing watches the context while the model works through tool
        calls, and one long turn can outgrow the context window.
        """
        return await self._run(body, __user__, __metadata__, __model__, __request__, __event_emitter__)

    def stream(self, event: Any, __metadata__: Optional[dict] = None) -> Any:
        """Pick the real prompt token count out of the response stream."""
        try:
            usage = event.get("usage") if isinstance(event, dict) else None
            if usage:
                self._record_usage(str((__metadata__ or {}).get("chat_id") or ""), usage)
        except Exception:
            log.debug("context_trim: usage not read from stream", exc_info=True)
        return event

    async def outlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        """Fallback for backends that report usage only at the end of the turn."""
        if not self.valves.auto_calibrate:
            return body
        try:
            chat_id = str(body.get("chat_id") or (__metadata__ or {}).get("chat_id") or "")
            last = (body.get("messages") or [{}])[-1]
            usage = last.get("usage") or (last.get("info") or {}).get("usage") or last.get("info") or {}
            self._record_usage(chat_id, usage)
        except Exception:
            log.debug("context_trim: calibration skipped", exc_info=True)
        return body
