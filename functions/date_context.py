"""
title: Date Context
author: Crimson
version: 1.0.0
required_open_webui_version: 0.5.0
description: Tells the model today's date so it stops guessing from its training data. The date goes in the system prompt and changes once a day, which keeps the prompt cache intact; the exact time is optional.
"""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

MARK = "[Current date:"


class Filter:
    class Valves(BaseModel):
        priority: int = Field(10, description="Filter order; lower runs first.")
        timezone: str = Field("", description="IANA timezone such as Europe/Berlin. Empty = the server's local timezone.")
        include_time: bool = Field(
            False,
            description="Also add the current time to the newest user message. Costs a little prompt cache on every turn.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _now(self) -> datetime:
        if self.valves.timezone.strip():
            try:
                return datetime.now(ZoneInfo(self.valves.timezone.strip()))
            except (KeyError, ValueError):
                return datetime.now().astimezone()  # unknown zone name: fall back to local time
        return datetime.now().astimezone()

    async def inlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not msgs or (__metadata__ or {}).get("task"):
            return body
        now = self._now()
        note = f"{MARK} {now:%A, %Y-%m-%d}, ISO week {now.isocalendar().week}. Use it for anything that depends on today's date.]"

        system = next((m for m in msgs if m.get("role") == "system"), None)
        if system is None:
            msgs.insert(0, {"role": "system", "content": note})
        elif MARK not in str(system.get("content")):
            c = system.get("content")
            if isinstance(c, list):
                system["content"] = c + [{"type": "text", "text": note}]
            else:
                system["content"] = f"{c or ''}\n\n{note}".strip()

        if self.valves.include_time:
            for m in reversed(msgs):
                if m.get("role") == "user":
                    zone = now.tzname() or ""
                    stamp = f"\n\n[Sent at {now:%H:%M} {zone}]".rstrip("] ") + "]"
                    c = m.get("content")
                    if isinstance(c, list):
                        m["content"] = c + [{"type": "text", "text": stamp.strip()}]
                    else:
                        m["content"] = f"{c or ''}{stamp}"
                    break
        return body
