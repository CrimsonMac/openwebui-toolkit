"""
title: Cache Watch
author: Crimson
version: 1.0.0
required_open_webui_version: 0.5.0
description: Warns when something changed early in the conversation and forces the backend to re-read it instead of reusing its prompt cache - the usual reason a reply suddenly takes minutes to start. Says what changed and roughly how long the re-read will take.
"""

import hashlib
import logging
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

MAX_CHATS = 256


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                if p.get("type") == "text":
                    parts.append(p.get("text", ""))
                elif p.get("type") == "image_url":
                    url = (p.get("image_url") or {}).get("url", "")
                    parts.append(f"[image {len(url)} {url[-32:]}]")
        return "\n".join(parts)
    return "" if content is None else str(content)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            100, description="Filter order. Keep this higher than your other filters so it sees what they changed."
        )
        min_tokens: int = Field(
            3000, description="Only warn when at least this many previously cached tokens have to be re-read."
        )
        read_tokens_per_second: float = Field(
            0,
            description="Prompt processing speed of your setup, to estimate the wait. 0 = report tokens only.",
        )
        bytes_per_token: float = Field(3.3, description="Rough UTF-8 bytes per token for the estimate.")
        report_hits: bool = Field(False, description="Also show a status line when the cache is reused (for debugging).")

    def __init__(self):
        self.valves = self.Valves()
        self._seen: "OrderedDict[str, list]" = OrderedDict()

    def _signature(self, msgs: list) -> list:
        out = []
        for m in msgs:
            t = _text(m.get("content"))
            extra = str(m.get("tool_calls") or "") + str(len(m.get("images") or []))
            digest = hashlib.blake2b((t + "\x00" + extra).encode("utf-8", "ignore"), digest_size=10).hexdigest()
            tokens = len(t.encode("utf-8", "ignore")) / max(self.valves.bytes_per_token, 0.5) + 4
            out.append((m.get("role"), digest, tokens))
        return out

    @staticmethod
    def _reason(prev: list, now: list, i: int) -> str:
        role = now[i][0] if i < len(now) else prev[i][0]
        if role == "system" or prev[i][0] == "system":
            return "the system prompt changed (a date or time variable, memory, or a filter that edits it)"
        prev_ids = [d for _, d, _ in prev]
        # Did the old tail survive further down or further up? Then messages were removed or inserted.
        if i < len(now) and now[i][1] in prev_ids[i + 1 :]:
            removed = prev_ids.index(now[i][1], i + 1) - i
            return f"{removed} earlier message(s) were removed (trimmed or deleted)"
        now_ids = [d for _, d, _ in now]
        if prev[i][1] in now_ids[i + 1 :]:
            return "a message was inserted earlier in the conversation"
        return f"message {i + 1} ({role}) is different from last time (edited, or rewritten by a filter)"

    async def inlet(
        self,
        body: dict,
        __metadata__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        try:
            meta = __metadata__ or {}
            msgs = body.get("messages")
            chat_id = meta.get("chat_id")
            if not chat_id or not isinstance(msgs, list) or meta.get("task"):
                return body
            key = f"{chat_id}|{body.get('model')}"
            now = self._signature(msgs)
            prev = self._seen.get(key)
            self._seen[key] = now
            self._seen.move_to_end(key)
            while len(self._seen) > MAX_CHATS:
                self._seen.popitem(last=False)
            if not prev or not __event_emitter__:
                return body

            shared = min(len(prev), len(now))
            i = next((k for k in range(shared) if prev[k][1] != now[k][1]), None)
            if i is None:
                if self.valves.report_hits:
                    kept = sum(t for _, _, t in now[:shared])
                    await __event_emitter__(
                        {"type": "status", "data": {"description": f"Prompt cache reused (~{kept / 1000:.1f}k tokens)", "done": True}}
                    )
                return body

            # Tokens that were in the cache last turn and now sit behind the first change.
            lost = sum(t for _, _, t in prev[i:])
            if lost < self.valves.min_tokens:
                return body
            reread = sum(t for _, _, t in now[i:])
            text = f"Prompt cache miss: {self._reason(prev, now, i)}. About {reread / 1000:.0f}k tokens to re-read"
            speed = self.valves.read_tokens_per_second
            if speed > 0:
                secs = reread / speed
                text += f", roughly {secs / 60:.0f} min" if secs >= 90 else f", roughly {secs:.0f} s"
            await __event_emitter__({"type": "status", "data": {"description": text + ".", "done": True}})
        except Exception:
            # Diagnostics only; never get in the way of the request.
            logging.getLogger("cache_watch").debug("check skipped", exc_info=True)
        return body
