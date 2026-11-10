"""
title: Quick Answer
author: Crimson
version: 1.0.0
required_open_webui_version: 0.6.10
description: A switch in the message box that turns off the model's thinking phase for the next replies, so simple questions are answered at once. Leave it off for hard problems, where thinking is what makes the answer good. Works with Ollama models that support thinking.
"""

from typing import Optional

from pydantic import BaseModel, Field

ICON = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJjdXJy"
    "ZW50Q29sb3IiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJN"
    "MTMgMiAzIDE0aDlsLTEgOCAxMC0xMmgtOWwxLTh6Ii8+PC9zdmc+"
)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(5, description="Filter order; lower runs first.")
        temperature: float = Field(
            -1,
            description="Temperature to use while the switch is on, for models whose publisher recommends a different value without thinking. -1 = leave unchanged.",
        )
        top_p: float = Field(-1, description="top_p to use while the switch is on. -1 = leave unchanged.")

    def __init__(self):
        self.valves = self.Valves()
        self.toggle = True  # shown as a switch in the message box; the filter only runs while it is on
        self.icon = ICON

    async def inlet(self, body: dict, __model__: Optional[dict] = None, __metadata__: Optional[dict] = None) -> dict:
        if (__metadata__ or {}).get("task"):
            return body
        model = __model__ or {}
        # Other backends reject an unknown "think" field, so only touch Ollama models.
        if model.get("owned_by") not in (None, "ollama") and "ollama" not in model:
            return body
        options = body.get("options")
        if not isinstance(options, dict):
            options = {}
            body["options"] = options
        options["think"] = False
        if self.valves.temperature >= 0:
            options["temperature"] = self.valves.temperature
        if self.valves.top_p >= 0:
            options["top_p"] = self.valves.top_p
        return body
