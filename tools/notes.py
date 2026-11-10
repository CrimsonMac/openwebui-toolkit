"""
title: Notes
author: Crimson
version: 1.0.0
description: A persistent notebook the model can write to and search, kept per user on the server. For facts, preferences and project details that should survive across chats.
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime

from pydantic import BaseModel, Field


def _dir() -> str:
    try:
        from open_webui.env import DATA_DIR

        base = str(DATA_DIR)
    except Exception:
        base = tempfile.gettempdir()
    return os.path.join(base, "notes_tool")


class Tools:
    class Valves(BaseModel):
        max_notes: int = Field(500, description="Maximum notes per user.")
        max_note_chars: int = Field(4000, description="Maximum length of one note.")
        max_result_chars: int = Field(4000, description="Cap on the text returned to the model per call.")

    def __init__(self):
        self.valves = self.Valves()

    # ---- storage
    def _path(self, user: dict) -> str:
        uid = re.sub(r"[^A-Za-z0-9_-]", "_", str((user or {}).get("id") or "default"))
        return os.path.join(_dir(), f"{uid}.json")

    def _load(self, user: dict) -> list:
        try:
            with open(self._path(user), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, user: dict, notes: list) -> None:
        os.makedirs(_dir(), exist_ok=True)
        path = self._path(user)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)

    @staticmethod
    def _line(n: dict, full: bool = False) -> str:
        when = datetime.fromtimestamp(n.get("updated", 0)).strftime("%Y-%m-%d")
        tags = f" [{', '.join(n['tags'])}]" if n.get("tags") else ""
        body = n["content"] if full else (n["content"][:160] + ("…" if len(n["content"]) > 160 else ""))
        return f"#{n['id']} {n['title']}{tags} ({when})\n{body}"

    def _clip(self, s: str) -> str:
        cap = self.valves.max_result_chars
        return s if len(s) <= cap else s[:cap] + "\n[... cut; use search_notes with a narrower query or read_note]"

    # ---- tools
    async def save_note(self, title: str, content: str, tags: str = "", __user__: dict = None) -> str:
        """
        Save a note to the user's persistent notebook. Use it when the user asks you to remember something,
        or states a lasting fact, preference or project detail that will matter in later chats.
        If a note with the same title exists, it is replaced.

        :param title: Short title, for example "Home server setup".
        :param content: The note itself. Write it so it makes sense on its own later.
        :param tags: Optional comma-separated tags, for example "server, network".
        :return: Confirmation with the note id.
        """
        title, content = title.strip(), content.strip()
        if not title or not content:
            return "Error: title and content are both required."
        if len(content) > self.valves.max_note_chars:
            return f"Error: note too long ({len(content)} characters, limit {self.valves.max_note_chars}). Shorten it or split it."
        notes = self._load(__user__)
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        now = time.time()
        for n in notes:
            if n["title"].lower() == title.lower():
                n.update(content=content, tags=tag_list or n.get("tags", []), updated=now)
                self._save(__user__, notes)
                return f"Updated note #{n['id']} '{n['title']}'."
        if len(notes) >= self.valves.max_notes:
            return f"Error: notebook is full ({self.valves.max_notes} notes). Delete some first."
        new_id = max((n["id"] for n in notes), default=0) + 1
        notes.append({"id": new_id, "title": title, "content": content, "tags": tag_list, "created": now, "updated": now})
        self._save(__user__, notes)
        return f"Saved note #{new_id} '{title}'."

    async def search_notes(self, query: str, __user__: dict = None) -> str:
        """
        Search the user's notebook. Use it before answering when the user refers to something they told you
        in an earlier chat, or asks "what do you know about ...".

        :param query: Words to look for in titles, tags and content, for example "server backup".
        :return: Matching notes, best match first.
        """
        notes = self._load(__user__)
        if not notes:
            return "The notebook is empty."
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
        if not words:
            return "Error: give at least one search word."
        scored = []
        for n in notes:
            title, tags, content = n["title"].lower(), " ".join(n.get("tags", [])), n["content"].lower()
            score = sum(5 * (w in title) + 3 * (w in tags) + min(content.count(w), 3) for w in words)
            if score:
                scored.append((score, n.get("updated", 0), n))
        if not scored:
            return f"No notes match '{query}'. Titles in the notebook: " + ", ".join(n["title"] for n in notes[:40])
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return self._clip("\n\n".join(self._line(n, full=len(scored) <= 3) for _, _, n in scored[:10]))

    async def list_notes(self, tag: str = "", __user__: dict = None) -> str:
        """
        List the titles of all notes in the user's notebook, optionally only those with a tag.

        :param tag: Optional tag to filter by.
        :return: Note ids, titles, tags and dates.
        """
        notes = self._load(__user__)
        if tag.strip():
            notes = [n for n in notes if tag.strip().lower() in n.get("tags", [])]
        if not notes:
            return "No notes found."
        notes.sort(key=lambda n: n.get("updated", 0), reverse=True)
        lines = [
            f"#{n['id']} {n['title']}" + (f" [{', '.join(n['tags'])}]" if n.get("tags") else "")
            + f" ({datetime.fromtimestamp(n.get('updated', 0)):%Y-%m-%d})"
            for n in notes
        ]
        return self._clip(f"{len(notes)} note(s):\n" + "\n".join(lines))

    async def read_note(self, note_id: int, __user__: dict = None) -> str:
        """
        Read one note in full.

        :param note_id: The number of the note, as shown by list_notes or search_notes.
        :return: The full note.
        """
        for n in self._load(__user__):
            if n["id"] == int(note_id):
                return self._clip(self._line(n, full=True))
        return f"Error: there is no note #{note_id}."

    async def delete_note(self, note_id: int, __user__: dict = None) -> str:
        """
        Delete one note permanently. Only do this when the user asks for it.

        :param note_id: The number of the note to delete.
        :return: Confirmation.
        """
        notes = self._load(__user__)
        keep = [n for n in notes if n["id"] != int(note_id)]
        if len(keep) == len(notes):
            return f"Error: there is no note #{note_id}."
        self._save(__user__, keep)
        gone = next(n for n in notes if n["id"] == int(note_id))
        return f"Deleted note #{note_id} '{gone['title']}'."
