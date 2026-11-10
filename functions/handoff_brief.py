"""
title: Handoff Brief
author: Crimson
version: 1.0.0
required_open_webui_version: 0.5.0
description: Adds a button under a reply that writes a compact brief of the whole chat - goal, facts, decisions, current state, open tasks - ready to paste into a new chat and carry on with a fresh context.
"""

import inspect
import json
import re
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

SYSTEM = (
    "You write handoff briefs. A brief lets a different assistant, who has not seen the conversation, "
    "continue the work without asking the user to repeat anything."
)

INSTRUCTIONS = (
    "Write the handoff brief for the conversation above. Use exactly these headings:\n\n"
    "## Goal\nWhat the user is trying to achieve, in one or two sentences.\n\n"
    "## Context and facts\nEverything a newcomer must know: names, versions, numbers, file names, constraints, "
    "the user's stated preferences. Bullets.\n\n"
    "## Decisions made\nWhat was decided and, briefly, why. Include approaches that were tried and rejected.\n\n"
    "## Current state\nWhere things stand right now. Include the latest version of any code, text or data that is "
    "being worked on, in full, if it is needed to continue.\n\n"
    "## Open tasks\nWhat remains, in order, with the very next step first.\n\n"
    "Rules: use only what the conversation says; copy exact values, never paraphrase numbers, names or code; "
    "write in the language of the conversation; at most {words} words, not counting code; output only the brief."
)

NOISE = re.compile(r"<think>.*?</think>|<details\b[^>]*>.*?</details>", re.DOTALL | re.IGNORECASE)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "" if content is None else str(content)


def _middle_cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    return f"{text[:head]}\n[... {len(text) - limit} characters omitted ...]\n{text[len(text) - (limit - head):]}"


class Action:
    class Valves(BaseModel):
        model: str = Field("", description="Model that writes the brief. Empty = the chat's own model.")
        max_words: int = Field(600, description="Target length of the brief.")
        max_input_chars: int = Field(
            120000, description="Cap on conversation text sent to the model. Older messages are shortened first."
        )
        num_ctx: int = Field(0, description="num_ctx for the call on Ollama models. 0 = the model's own setting.")

    def __init__(self):
        self.valves = self.Valves()

    def _transcript(self, messages: list) -> str:
        items = []
        for m in messages:
            if m.get("role") not in ("user", "assistant"):
                continue
            t = NOISE.sub("", _text(m.get("content"))).strip()
            if t:
                items.append([m["role"].upper(), t])
        budget = self.valves.max_input_chars
        total = sum(len(t) for _, t in items)
        if total > budget and items:
            # Keep the last few messages whole; squeeze the older ones evenly.
            tail = items[-4:]
            head = items[:-4]
            left = max(budget - sum(len(t) for _, t in tail), budget // 4)
            per = max(left // max(len(head), 1), 300)
            for it in head:
                it[1] = _middle_cut(it[1], per)
            for it in tail:
                it[1] = _middle_cut(it[1], max(budget // 4, 2000))
        return "\n\n".join(f"{role}: {t}" for role, t in items)

    async def action(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __request__: Any = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> None:
        async def status(text: str, done: bool) -> None:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})

        messages = body.get("messages") or []
        transcript = self._transcript(messages)
        if not transcript:
            await status("Nothing to summarize yet", True)
            return
        await status("Writing handoff brief…", False)
        try:
            from open_webui.models.users import Users
            from open_webui.utils.chat import generate_chat_completion

            user = Users.get_user_by_id((__user__ or {}).get("id"))
            if inspect.isawaitable(user):
                user = await user
            model = self.valves.model or body.get("model")
            form: dict = {
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": f"<conversation>\n{transcript}\n</conversation>\n\n"
                        + INSTRUCTIONS.format(words=self.valves.max_words),
                    },
                ],
            }
            if self.valves.num_ctx > 0:
                form["options"] = {"num_ctx": self.valves.num_ctx}
            res = await generate_chat_completion(__request__, form, user=user, bypass_filter=True)
            if hasattr(res, "body"):
                res = json.loads(res.body)
            brief = NOISE.sub("", res["choices"][0]["message"].get("content") or "").strip()
            if not brief:
                raise RuntimeError("the model returned nothing")
        except Exception as e:
            await status(f"Handoff brief failed: {e}", True)
            return

        fence = "````" if "```" in brief else "```"
        block = (
            "\n\n---\n**Handoff brief** — paste this as the first message of a new chat:\n\n"
            f"{fence}markdown\nContinue this work. Here is the brief of the previous conversation.\n\n{brief}\n{fence}\n"
        )
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": block}})
        await status("Handoff brief added below the reply", True)
