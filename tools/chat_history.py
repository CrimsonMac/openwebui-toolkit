"""
title: Chat History
author: Crimson
version: 1.0.0
description: Lets the model look up parts of the current chat that the Context Trim filter shortened or removed to save context - search them by words, or read one message in full by its number. Needs the Context Trim filter, which stores them.
"""

import hashlib
import json
import os
import re
import tempfile

from pydantic import BaseModel, Field


def _archive_path(chat_id: str) -> str:
    try:
        from open_webui.env import DATA_DIR

        base = str(DATA_DIR)
    except Exception:
        base = tempfile.gettempdir()
    name = hashlib.sha1(str(chat_id).encode("utf-8", "ignore")).hexdigest()
    return os.path.join(base, "context_trim", "archive", f"{name}.json")


class Tools:
    class Valves(BaseModel):
        part_chars: int = Field(6000, description="How much of a message read_chat_message returns per call.")
        max_results: int = Field(6, description="How many matches search_chat_history returns.")
        snippet_chars: int = Field(500, description="How much text is shown around each match.")

    def __init__(self):
        self.valves = self.Valves()

    @staticmethod
    def _load(metadata: dict) -> dict:
        chat_id = (metadata or {}).get("chat_id")
        if not chat_id:
            return {}
        try:
            with open(_archive_path(chat_id), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _label(number: str, entry: dict) -> str:
        role = str(entry.get("role") or "?")
        who = f"tool result ({entry.get('name') or 'tool'})" if role == "tool" else role
        return f"Message {number}, {who}, {len(entry.get('text', ''))} characters"

    async def search_chat_history(self, query: str, __metadata__: dict = None) -> str:
        """
        Search the parts of this chat that were removed or shortened to save context: earlier messages and long tool results.
        Use it when you need an exact detail from earlier in this chat (a number, a name, a command, an error, a page you fetched)
        and it is no longer in front of you. Do not guess such details.

        :param query: Words to look for, for example "nginx error 502" or "invoice total".
        :return: The best matching passages with their message numbers. Read more with read_chat_message.
        """
        data = self._load(__metadata__)
        if not data:
            return "Nothing from this chat has been removed or shortened, so everything is still in the conversation above."
        words = list(dict.fromkeys(w for w in re.findall(r"\w+", str(query).lower()) if len(w) > 1))
        if not words:
            return "Error: give at least one search word."
        scored = []
        for number, entry in data.items():
            low = entry.get("text", "").lower()
            hits = [w for w in words if w in low]
            if hits:
                score = len(hits) * 10 + sum(min(low.count(w), 5) for w in hits)
                scored.append((score, int(number), number, entry, hits))
        if not scored:
            numbers = sorted(int(n) for n in data)
            return f"No stored message contains those words. Stored messages: {numbers[0]} to {numbers[-1]} ({len(numbers)} in total). Try other words."
        scored.sort(key=lambda x: (-x[0], -x[1]))
        out = []
        size = self.valves.snippet_chars
        for _, _, number, entry, hits in scored[: self.valves.max_results]:
            text = entry["text"]
            low = text.lower()
            # Show the place where the rarest matched word first appears.
            at = min((low.find(w) for w in hits), default=0)
            start = max(at - size // 3, 0)
            piece = text[start : start + size].strip()
            out.append(f"{self._label(number, entry)}:\n{'...' if start else ''}{piece}{'...' if start + size < len(text) else ''}")
        return "\n\n".join(out)

    async def read_chat_message(self, number: int, part: int = 1, __metadata__: dict = None) -> str:
        """
        Read one earlier message of this chat in full, by its number. Use the number given in a note such as
        "read_chat_message(number=12)" or returned by search_chat_history. Long messages come in parts.

        :param number: The message number.
        :param part: Which part of a long message, starting at 1.
        :return: The text of that message, or of the requested part.
        """
        data = self._load(__metadata__)
        entry = data.get(str(int(number)))
        if entry is None:
            if not data:
                return "Nothing from this chat has been removed or shortened, so everything is still in the conversation above."
            numbers = sorted(int(n) for n in data)
            return f"Message {number} is not stored. It is either still in the conversation above, or does not exist. Stored: {numbers[0]} to {numbers[-1]}."
        text = entry.get("text", "")
        size = max(self.valves.part_chars, 500)
        parts = max((len(text) + size - 1) // size, 1)
        part = min(max(int(part), 1), parts)
        piece = text[(part - 1) * size : part * size]
        more = f"\n[part {part} of {parts}; call read_chat_message(number={int(number)}, part={part + 1}) for the next]" if part < parts else ""
        return f"{self._label(str(int(number)), entry)}:\n{piece}{more}"
