"""
title: Second Opinion
author: Crimson
version: 1.0.0
required_open_webui_version: 0.5.0
description: A model entry that answers with one model, has a second model review the draft for errors, and lets the first revise. Slower (three generations, and Ollama swaps models if both do not fit in memory), but catches mistakes a single model misses.
"""

import inspect
import json
import re
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

NOISE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

REVIEW_SYSTEM = (
    "You are a careful reviewer. You are shown a conversation and a draft reply to its last message. "
    "Find what is wrong with the draft. Do not rewrite it."
)

REVIEW_TASK = (
    "Review the draft reply. Look for: factual errors, wrong calculations, bugs in code, steps that do not follow, "
    "parts of the question left unanswered, and claims stated with more certainty than is justified.\n\n"
    "List each problem as one bullet: what is wrong, and what would be right. Most serious first. "
    "Only real problems; no style remarks, no praise. "
    "If the draft has no real problems, reply with exactly: NO ISSUES"
)

REVISE_TASK = (
    "A reviewer checked your draft reply and raised the points below. Consider each one on its merits: "
    "fix what is really wrong, and keep what was right even if the reviewer objected. "
    "Then write the final reply to the user. Output only that reply, with no mention of the draft or the review.\n\n"
    "<review>\n{review}\n</review>"
)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "" if content is None else str(content)


class Pipe:
    class Valves(BaseModel):
        answer_model: str = Field("", description="Model id that writes the draft and the final reply. Required.")
        review_model: str = Field("", description="Model id that reviews the draft. Empty = the answer model reviews itself.")
        show_work: bool = Field(True, description="Append the draft and the review in a collapsed section.")
        review_context_chars: int = Field(24000, description="How much of the conversation the reviewer sees.")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list:
        return [{"id": "second-opinion", "name": "Second Opinion"}]

    async def _complete(self, request: Any, user: Any, model: str, messages: list) -> str:
        from open_webui.utils.chat import generate_chat_completion

        res = await generate_chat_completion(
            request, {"model": model, "messages": messages, "stream": False}, user=user, bypass_filter=True
        )
        if hasattr(res, "body"):
            res = json.loads(res.body)
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(str(res["error"]))
        return NOISE.sub("", res["choices"][0]["message"].get("content") or "").strip()

    async def pipe(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __request__: Any = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> str:
        v = self.valves

        async def status(text: str, done: bool = False) -> None:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})

        if not v.answer_model:
            return "Second Opinion is not configured: set `answer_model` (and optionally `review_model`) in this function's valves."
        reviewer = v.review_model or v.answer_model
        messages = [
            {"role": m.get("role"), "content": m.get("content")}
            for m in body.get("messages", [])
            if m.get("role") in ("system", "user", "assistant")
        ]
        if not messages:
            return "There is no message to answer."

        try:
            from open_webui.models.users import Users

            user = Users.get_user_by_id((__user__ or {}).get("id"))
            if inspect.isawaitable(user):
                user = await user

            await status(f"Drafting with {v.answer_model}…")
            draft = await self._complete(__request__, user, v.answer_model, messages)
            if not draft:
                raise RuntimeError("the answer model returned nothing")

            await status(f"Reviewing with {reviewer}…")
            convo = "\n\n".join(
                f"{m['role'].upper()}: {_text(m['content'])}" for m in messages if m["role"] != "system"
            )[-v.review_context_chars:]
            review = await self._complete(
                __request__,
                user,
                reviewer,
                [
                    {"role": "system", "content": REVIEW_SYSTEM},
                    {
                        "role": "user",
                        "content": f"<conversation>\n{convo}\n</conversation>\n\n<draft_reply>\n{draft}\n</draft_reply>\n\n{REVIEW_TASK}",
                    },
                ],
            )

            if not review or re.fullmatch(r"\W*NO ISSUES\W*", review, re.IGNORECASE):
                final, verdict = draft, "The reviewer found no issues."
            else:
                await status(f"Revising with {v.answer_model}…")
                final = await self._complete(
                    __request__,
                    user,
                    v.answer_model,
                    messages
                    + [
                        {"role": "assistant", "content": draft},
                        {"role": "user", "content": REVISE_TASK.format(review=review)},
                    ],
                )
                verdict = review
                if not final:
                    final, verdict = draft, review + "\n\n(The revision came back empty, so the draft is shown.)"
        except Exception as e:
            await status("Second Opinion failed", True)
            return f"Second Opinion failed: {e}"

        await status("Done", True)
        if not v.show_work:
            return final
        work = f"**Review by {reviewer}**\n\n{verdict}"
        if final != draft:
            work += f"\n\n**First draft by {v.answer_model}**\n\n{draft}"
        return f"{final}\n\n<details>\n<summary>Draft and review</summary>\n\n{work}\n\n</details>"
