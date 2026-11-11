"""
title: Memory
author: Crimson
version: 1.0.0
description: Long-term memory the model can write to and search, kept per user and split into one global list plus one list per project. Shares its store with the Auto Memory filter, so both see the same memories. Works on its own too.
"""

import difflib
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime

from pydantic import BaseModel, Field

_LOCK = threading.Lock()


def _base() -> str:
    try:
        from open_webui.env import DATA_DIR

        base = str(DATA_DIR)
    except Exception:
        base = tempfile.gettempdir()
    return os.path.join(base, "memory_store")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:60]


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


class Tools:
    class Valves(BaseModel):
        max_memories: int = Field(2000, description="Maximum memories per user. The oldest automatic ones are dropped first.")
        max_memory_chars: int = Field(600, description="Maximum length of one memory.")
        max_result_chars: int = Field(4000, description="Cap on the text returned to the model per call.")

    def __init__(self):
        self.valves = self.Valves()

    # ---- storage (same file layout as the Auto Memory filter)
    @staticmethod
    def _path(user: dict) -> str:
        uid = re.sub(r"[^A-Za-z0-9_-]", "_", str((user or {}).get("id") or "default"))
        return os.path.join(_base(), f"{uid}.json")

    def _load(self, user: dict) -> dict:
        try:
            with open(self._path(user), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"seq": 0, "items": []}

    def _save(self, user: dict, data: dict) -> None:
        os.makedirs(_base(), exist_ok=True)
        path = self._path(user)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)

    @staticmethod
    def _chat_project(metadata: dict) -> tuple:
        """Project of the current chat, as recorded by the Auto Memory filter. ('', '') if unknown."""
        chat_id = re.sub(r"[^A-Za-z0-9_-]", "_", str((metadata or {}).get("chat_id") or ""))
        if not chat_id:
            return "", ""
        try:
            with open(os.path.join(_base(), "chats", f"{chat_id}.json"), encoding="utf-8") as f:
                st = json.load(f)
            return str(st.get("project") or ""), str(st.get("project_name") or "")
        except (OSError, ValueError):
            return "", ""

    def _scope(self, project: str, metadata: dict) -> tuple:
        """Turn the model's project argument into (slug, display name). '' means global."""
        p = (project or "").strip()
        if p.lower() in ("global", "general", "all chats", "none", "user"):
            return "", ""
        if not p or p.lower() in ("current", "this", "this project", "project"):
            return self._chat_project(metadata)
        return _slug(p), p

    @staticmethod
    def _line(m: dict) -> str:
        when = datetime.fromtimestamp(m.get("updated", 0)).strftime("%Y-%m-%d")
        where = f"project {m.get('project_name') or m['project']}" if m.get("project") else "global"
        return f"#{m['id']} [{where}, {when}] {m['text']}"

    def _clip(self, s: str) -> str:
        cap = self.valves.max_result_chars
        return s if len(s) <= cap else s[:cap] + "\n[... cut; call recall with a narrower query]"

    # ---- tools
    async def remember(self, text: str, project: str = "", __user__: dict = None, __metadata__: dict = None) -> str:
        """
        Save one fact to long-term memory so it is known in later chats. Use it when the user says "remember ...",
        or states a lasting fact, preference, decision or project detail. Save one fact per call, in a full sentence.
        Do not save passwords, keys or one-off questions.

        :param text: The fact, written so it makes sense alone, for example "The user's home server runs Debian 13 on a Ryzen 5600".
        :param project: Leave empty for the current project (or global if the chat has no project). "global" = applies to all chats. Or a project name.
        :return: Confirmation with the memory id.
        """
        text = " ".join(str(text or "").split())
        if len(text) < 8:
            return "Error: text is too short. Write the fact as a full sentence."
        if len(text) > self.valves.max_memory_chars:
            return f"Error: too long ({len(text)} characters, limit {self.valves.max_memory_chars}). Save one fact per call."
        slug, name = self._scope(project, __metadata__)
        now = time.time()
        with _LOCK:
            data = self._load(__user__)
            for m in data["items"]:
                if m.get("project", "") == slug and difflib.SequenceMatcher(None, _norm(m["text"]), _norm(text)).ratio() > 0.85:
                    m.update(text=text, updated=now)
                    self._save(__user__, data)
                    return f"Updated memory #{m['id']} (it already existed)."
            data["seq"] = int(data.get("seq", 0)) + 1
            data["items"].append(
                {"id": data["seq"], "text": text, "project": slug, "project_name": name, "created": now, "updated": now, "source": "tool"}
            )
            extra = len(data["items"]) - self.valves.max_memories
            if extra > 0:
                auto = sorted((m for m in data["items"] if m.get("source") == "auto"), key=lambda m: m.get("updated", 0))[:extra]
                gone = {m["id"] for m in auto}
                data["items"] = [m for m in data["items"] if m["id"] not in gone]
            self._save(__user__, data)
        where = f"project '{name or slug}'" if slug else "global memory"
        return f"Saved memory #{data['seq']} to {where}."

    async def recall(self, query: str = "", project: str = "", __user__: dict = None, __metadata__: dict = None) -> str:
        """
        Search long-term memory. Use it before answering when the user refers to something from an earlier chat,
        asks "what do you know about ...", or when a saved fact could change the answer.

        :param query: Words to look for, for example "server backup". Empty = list the newest memories.
        :param project: Leave empty to search the current project and global memory. "all" = every project. Or a project name.
        :return: Matching memories with their ids, best match first.
        """
        items = self._load(__user__)["items"]
        if not items:
            return "Memory is empty."
        p = (project or "").strip()
        if p.lower() not in ("all", "everything", "any"):
            slug, _ = self._scope(p, __metadata__)
            items = [m for m in items if not m.get("project") or (slug and m.get("project") == slug)]
        words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 2]
        if words:
            scored = []
            for m in items:
                text = m["text"].lower()
                score = sum(min(text.count(w), 2) for w in words)
                if score:
                    scored.append((score, m.get("updated", 0), m))
            scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
            hits = [m for _, _, m in scored[:15]]
            if not hits:
                return f"No memory matches '{query}'. Try other words, or project \"all\"."
        else:
            hits = sorted(items, key=lambda m: m.get("updated", 0), reverse=True)[:25]
            if not hits:
                return "No memories in this scope."
        return self._clip("\n".join(self._line(m) for m in hits))

    async def forget(self, memory_id: int, __user__: dict = None) -> str:
        """
        Delete one memory permanently. Use it when the user says a saved fact is wrong or should be forgotten.

        :param memory_id: The number of the memory, as shown by recall.
        :return: Confirmation.
        """
        with _LOCK:
            data = self._load(__user__)
            keep = [m for m in data["items"] if m["id"] != int(memory_id)]
            if len(keep) == len(data["items"]):
                return f"Error: there is no memory #{memory_id}. Call recall to see the ids."
            gone = next(m for m in data["items"] if m["id"] == int(memory_id))
            data["items"] = keep
            self._save(__user__, data)
        return f"Forgot memory #{memory_id}: {gone['text'][:120]}"

    async def list_memory_projects(self, __user__: dict = None) -> str:
        """
        List the projects that have memories, with how many each holds.

        :return: Project names and counts.
        """
        counts: dict = {}
        for m in self._load(__user__)["items"]:
            key = (m.get("project_name") or m.get("project")) if m.get("project") else "global"
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return "Memory is empty."
        return "\n".join(f"{name}: {n}" for name, n in sorted(counts.items(), key=lambda x: -x[1]))
