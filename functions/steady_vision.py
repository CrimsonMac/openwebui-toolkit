"""
title: Steady Vision
author: Crimson
version: 1.2.0
required_open_webui_version: 0.5.0
description: Makes answers about images consistent and stops the model from thinking in circles about them. While an image is in the recent conversation it switches the thinking phase off, lowers the sampling temperature, switches off the presence penalty that pushes the model toward unusual words, and tells the model to report only what it can clearly see. Warns when the model's own Advanced Params keep thinking on. Text-only chats are left alone. For Ollama models.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

MARK = "[Image rules:"
RULES = (
    f"{MARK} report only what is clearly visible. If a detail is small, hidden or unclear, say it is unclear "
    "instead of guessing. Copy text exactly as written. Do not name people, characters or brands unless "
    "readable text in the image names them.]"
)


def _has_image(m: dict) -> bool:
    if m.get("images"):
        return True
    c = m.get("content")
    return isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in c)


def _model_think(model: dict) -> bool:
    """True when the model's own parameters switch thinking on (True, or a level such as "high")."""
    for holder in (model.get("info"), model):
        params = (holder or {}).get("params") if isinstance(holder, dict) else None
        if isinstance(params, dict) and params.get("think") not in (None, False, "", "false", "off", "none"):
            return True
    return False


class Filter:
    class Valves(BaseModel):
        priority: int = Field(6, description="Filter order; lower runs first.")
        temperature: float = Field(0.2, description="Temperature while an image is in play. -1 = leave unchanged.")
        presence_penalty: float = Field(0.0, description="Presence penalty while an image is in play. -1 = leave unchanged.")
        repeat_penalty: float = Field(-1, description="Repeat penalty while an image is in play. -1 = leave unchanged.")
        top_p: float = Field(-1, description="top_p while an image is in play. -1 = leave unchanged.")
        seed: int = Field(
            -1,
            description="Fixed seed while an image is in play, so the same question about the same image gives the same answer. Regenerate then repeats the answer too. -1 = off.",
        )
        thinking: str = Field(
            "off",
            description="'off' answers image questions without the thinking phase. With thinking on, a model keeps re-checking a detail it cannot settle ('one more look...') and may never answer. 'leave' keeps the chat's own setting; the temperature and presence penalty are then left alone too, because lowering them makes the circling worse.",
        )
        warn_when_overridden: bool = Field(
            True,
            description="Show a notice when the model has Think set under its Advanced Params. That setting wins over this filter, so thinking stays on.",
        )
        add_rules: bool = Field(True, description="Add the 'report only what is clearly visible' rules to messages that carry an image.")
        lookback_messages: int = Field(
            8, description="The settings apply while one of the last this-many messages has an image, so follow-up questions stay steady too."
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(
        self, body: dict, __model__: Optional[dict] = None, __metadata__: Optional[dict] = None, __event_emitter__=None
    ) -> dict:
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not msgs or (__metadata__ or {}).get("task"):
            return body
        v = self.valves
        if not any(_has_image(m) for m in msgs[-max(v.lookback_messages, 1):]):
            return body

        if v.add_rules:
            # Every image message gets the same rules on every turn, so the prompt cache holds.
            for m in msgs:
                if m.get("role") != "user" or not _has_image(m):
                    continue
                c: Any = m.get("content")
                if isinstance(c, list):
                    if not any(isinstance(p, dict) and MARK in str(p.get("text", "")) for p in c):
                        m["content"] = c + [{"type": "text", "text": RULES}]
                elif MARK not in str(c or ""):
                    m["content"] = f"{c or ''}\n\n{RULES}".strip()

        model = __model__ or {}
        # Sampling options under "options" are an Ollama convention; other backends may reject them.
        if model.get("owned_by") not in (None, "ollama") and "ollama" not in model:
            return body
        # Open WebUI applies the model's own Advanced Params after the filters, so a Think set there wins.
        forced = _model_think(model)
        want_off = v.thinking.strip().lower() == "off"
        if want_off and forced and v.warn_when_overridden and __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": "Steady Vision: this model has Think switched on under its Advanced Params, which overrides the filter. "
                        "Set it to Default there, or image answers may think in circles.",
                        "done": True,
                    },
                }
            )
        thinking_stays_on = forced or not want_off

        options = body.get("options")
        if not isinstance(options, dict):
            options = {}
            body["options"] = options
        for key in ("temperature", "presence_penalty", "repeat_penalty", "top_p"):
            value = getattr(v, key)
            # A low temperature without a presence penalty is what lets a thinking phase repeat itself word for word.
            if value >= 0 and not (thinking_stays_on and key in ("temperature", "presence_penalty")):
                options[key] = value
        if v.seed >= 0:
            options["seed"] = v.seed
        if want_off:
            options["think"] = False
        return body
