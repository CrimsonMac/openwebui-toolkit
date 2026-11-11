"""
title: Auto Memory
author: Crimson
version: 1.0.0
required_open_webui_version: 0.5.0
description: Long-term memory that fills itself. When a chat has been idle for a while, the new turns are read once and lasting facts are saved; "/remember ..." saves at once. Saved memories are shown to the model at the start of later chats. Chats inside a folder get that folder's own project memory on top of the global one. Shares its store with the Memory tool.
"""

import asyncio
import difflib
import inspect
import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("auto_memory")

MARK = "[Memory from earlier chats."
# Options that make Ollama reload a model when they differ from the loaded runner.
LOAD_OPTIONS = ("num_ctx", "num_batch", "num_gpu", "num_thread", "use_mmap", "use_mlock", "main_gpu", "numa")
REMEMBER = re.compile(r"^\s*(?:/remember\b|remember\s*:)\s*(.+)", re.IGNORECASE | re.DOTALL)
_NOISE = re.compile(
    r"<think>.*?</think>|<details\b[^>]*type=\"(?:reasoning|tool_calls|code_interpreter)\"[^>]*>.*?</details>",
    re.DOTALL | re.IGNORECASE,
)
_SECRET = re.compile(r"(?i)\b(?:password|passwd|passphrase|api[ _-]?key|secret|token|private key)\b\s*(?:is|=|:)")
_LOCK = threading.Lock()

EXTRACT_SYSTEM = (
    "You keep the long-term memory of an AI assistant. You read the newest part of a conversation "
    "and decide what is worth remembering in future conversations."
)

EXTRACT_RULES = (
    "Write the memories to save, one per line, in exactly one of these forms:\n"
    "GLOBAL: <fact about the user that matters in any chat>\n"
    "{project_form}"
    "UPDATE <id>: <corrected text of an existing memory that is now outdated>\n"
    "NONE\n\n"
    "Rules:\n"
    "- Save only lasting things the USER stated or confirmed: who they are, their setup, preferences, "
    "goals, decisions, names, versions, paths, constraints.\n"
    "- Do not save: questions, small talk, things only the assistant said, temporary states, "
    "passwords, keys or other secrets.\n"
    "- Do not repeat anything already in <existing_memories>.\n"
    "- Each line is one full sentence that makes sense alone. At most {max_new} lines.\n"
    "- If nothing qualifies, write only NONE. Most conversations give 0 to 3 memories.\n"
    "Output only the lines, nothing else."
)


def _base() -> str:
    try:
        from open_webui.env import DATA_DIR

        base = str(DATA_DIR)
    except Exception:
        base = tempfile.gettempdir()
    return os.path.join(base, "memory_store")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:60]


def _safe(s: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(s or ""))


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _text(content: Any) -> str:
    if isinstance(content, list):
        content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return _NOISE.sub("", str(content or "")).strip()


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Filter:
    class Valves(BaseModel):
        priority: int = Field(15, description="Filter order; lower runs first.")
        inject: bool = Field(True, description="Show saved memories to the model in the system prompt.")
        max_inject_chars: int = Field(3000, description="Upper size of the memory block in the system prompt.")
        refresh_after_minutes: int = Field(
            30,
            description="A chat keeps the memory block it started with, so the prompt cache survives. After this long without a message the block is rebuilt.",
        )
        auto_save: bool = Field(True, description="Save lasting facts by itself when a chat goes idle.")
        idle_seconds: int = Field(120, description="How long a chat must be quiet before its new turns are read for memories.")
        min_new_chars: int = Field(200, description="Skip the idle pass when the user wrote less than this since the last one.")
        max_read_chars: int = Field(12000, description="At most this much of the newest conversation is read per pass.")
        max_new_per_pass: int = Field(5, description="At most this many memories are saved per pass.")
        memory_model: str = Field(
            "",
            description="Model that picks the memories. Empty = the chat's own model (already loaded). 'task' = Open WebUI's task model. Or a model id.",
        )
        use_projects: bool = Field(True, description="Give chats inside a folder their own project memory, named after the folder.")
        max_memories: int = Field(2000, description="Maximum memories per user. The oldest automatic ones are dropped first.")
        show_status: bool = Field(True, description="Show a short status line when something was saved.")
        timeout: int = Field(120, description="Seconds to wait for the memory model.")

    def __init__(self):
        self.valves = self.Valves()
        self._seq: dict = {}  # chat_id -> counter, bumped on every message; an idle task quits if it changed
        self._tasks: dict = {}
        self._options: dict = {}  # chat_id -> load options of the chat's last request
        self._projects: dict = {}  # chat_id -> (slug, name)

    # ------------------------------------------------------------------ storage
    @staticmethod
    def _store_path(user_id: str) -> str:
        return os.path.join(_base(), f"{_safe(user_id) or 'default'}.json")

    def _load(self, user_id: str) -> dict:
        try:
            with open(self._store_path(user_id), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"seq": 0, "items": []}

    def _save(self, user_id: str, data: dict) -> None:
        os.makedirs(_base(), exist_ok=True)
        path = self._store_path(user_id)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)

    @staticmethod
    def _chat_path(chat_id: str) -> str:
        return os.path.join(_base(), "chats", f"{_safe(chat_id)}.json")

    def _chat_state(self, chat_id: str) -> dict:
        try:
            with open(self._chat_path(chat_id), encoding="utf-8") as f:
                st = json.load(f)
            return st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            return {}

    def _put_chat_state(self, chat_id: str, st: dict) -> None:
        try:
            os.makedirs(os.path.join(_base(), "chats"), exist_ok=True)
            path = self._chat_path(chat_id)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(path + ".tmp", path)
        except OSError:
            log.debug("auto_memory: could not write chat state", exc_info=True)

    def _add(self, user_id: str, entries: list, project: tuple, source: str, chat_id: str = "") -> list:
        """entries: (kind, id_or_None, text) with kind GLOBAL, PROJECT or UPDATE. Returns the texts saved."""
        saved = []
        now = time.time()
        with _LOCK:
            data = self._load(user_id)
            for kind, ref, text in entries:
                text = " ".join(text.split())[:600]
                if len(text) < 8 or _SECRET.search(text):
                    continue
                if kind == "UPDATE":
                    old = next((m for m in data["items"] if m["id"] == ref), None)
                    if old is not None:
                        old.update(text=text, updated=now)
                        saved.append(text)
                    continue
                slug, name = project if kind == "PROJECT" else ("", "")
                twin = next(
                    (
                        m
                        for m in data["items"]
                        if m.get("project", "") in ("", slug)
                        and difflib.SequenceMatcher(None, _norm(m["text"]), _norm(text)).ratio() > 0.85
                    ),
                    None,
                )
                if twin is not None:
                    twin["updated"] = now
                    continue
                data["seq"] = int(data.get("seq", 0)) + 1
                data["items"].append(
                    {
                        "id": data["seq"],
                        "text": text,
                        "project": slug,
                        "project_name": name,
                        "created": now,
                        "updated": now,
                        "source": source,
                        "chat_id": chat_id,
                    }
                )
                saved.append(text)
            extra = len(data["items"]) - self.valves.max_memories
            if extra > 0:
                auto = sorted((m for m in data["items"] if m.get("source") == "auto"), key=lambda m: m.get("updated", 0))[:extra]
                gone = {m["id"] for m in auto}
                data["items"] = [m for m in data["items"] if m["id"] not in gone]
            if saved or extra > 0:
                self._save(user_id, data)
        return saved

    # ----------------------------------------------------------------- projects
    async def _project(self, chat_id: str, user_id: str, meta: dict) -> tuple:
        """(slug, name) of the folder the chat is in, or ('', '')."""
        if not self.valves.use_projects or not chat_id:
            return "", ""
        if chat_id in self._projects:
            return self._projects[chat_id]
        result = ("", "")
        try:
            folder_id = meta.get("folder_id")
            if not folder_id and not chat_id.startswith("local:"):
                from open_webui.models.chats import Chats

                if hasattr(Chats, "get_chat_folder_id"):
                    folder_id = await _maybe(Chats.get_chat_folder_id(chat_id, user_id))
                else:
                    chat = await _maybe(Chats.get_chat_by_id(chat_id))
                    folder_id = getattr(chat, "folder_id", None)
            if folder_id:
                from open_webui.models.folders import Folders

                folder = await _maybe(Folders.get_folder_by_id_and_user_id(folder_id, user_id))
                name = str(getattr(folder, "name", "") or "").strip()
                if name:
                    result = (_slug(name), name)
        except Exception:
            log.debug("auto_memory: folder lookup failed", exc_info=True)
        if len(self._projects) > 512:
            self._projects.clear()
        self._projects[chat_id] = result
        return result

    # ---------------------------------------------------------------- injection
    def _block(self, user_id: str, project: tuple) -> str:
        items = self._load(user_id)["items"]
        slug, name = project
        newest = lambda ms: sorted(ms, key=lambda m: m.get("updated", 0), reverse=True)
        glob = newest(m for m in items if not m.get("project"))
        proj = newest(m for m in items if slug and m.get("project") == slug)
        if not glob and not proj:
            return ""
        budget = self.valves.max_inject_chars
        # Half the room for each list when both exist; whatever one leaves over goes to the other.
        share = budget // 2 if glob and proj else budget

        def take(ms, room):
            out, used = [], 0
            for m in ms:
                if used + len(m["text"]) + 3 > room:
                    break
                out.append(m)
                used += len(m["text"]) + 3
            return out, used

        g, used_g = take(glob, share)
        p, used_p = take(proj, budget - used_g)
        if len(g) < len(glob):
            g, used_g = take(glob, budget - used_p)
        lines = [f"{MARK} Treat it as background knowledge. If the user says something different now, the user is right.]"]
        if g:
            lines.append("About the user (all chats):")
            lines += [f"- {m['text']}" for m in g]
        if p:
            lines.append(f'Project "{name}":')
            lines += [f"- {m['text']}" for m in p]
        left = len(glob) + len(proj) - len(g) - len(p)
        if left:
            lines.append(f"({left} older memories are not shown. Use the recall tool to search them, if you have it.)")
        lines.append("[End of memory]")
        return "\n".join(lines)

    @staticmethod
    def _with_block(msgs: list, block: str) -> None:
        system = next((m for m in msgs if m.get("role") == "system"), None)
        if system is None:
            msgs.insert(0, {"role": "system", "content": block})
            return
        c = system.get("content")
        if MARK in str(c):
            return
        if isinstance(c, list):
            system["content"] = c + [{"type": "text", "text": block}]
        else:
            system["content"] = f"{c or ''}\n\n{block}".strip()

    # --------------------------------------------------------------- extraction
    def _model(self, request: Any, chat_model: str) -> str:
        wanted = self.valves.memory_model.strip()
        if not wanted:
            return chat_model
        try:
            models = request.app.state.MODELS
            if wanted.lower() == "task":
                cfg = request.app.state.config
                is_ollama = (models.get(chat_model) or {}).get("owned_by") == "ollama"
                wanted = cfg.TASK_MODEL if is_ollama else cfg.TASK_MODEL_EXTERNAL
            if wanted and wanted in models:
                return wanted
        except Exception:
            log.debug("auto_memory: could not look up the memory model", exc_info=True)
        return chat_model

    async def _ask(self, request: Any, user_id: str, model: str, chat_model: str, chat_id: str, prompt: str) -> str:
        from open_webui.models.users import Users
        from open_webui.utils.chat import generate_chat_completion

        user = await _maybe(Users.get_user_by_id(user_id))
        form: dict = {
            "model": model,
            "messages": [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 1200,
        }
        try:
            is_ollama = (request.app.state.MODELS.get(model) or {}).get("owned_by") == "ollama"
        except Exception:
            is_ollama = False
        options: dict = {}
        if model == chat_model:
            # Same load settings as the chat, or Ollama reloads the model.
            options = dict(self._options.get(chat_id) or {})
        if is_ollama:
            options["think"] = False
        if options:
            form["options"] = options
        res = await asyncio.wait_for(generate_chat_completion(request, form, user=user, bypass_filter=True), timeout=self.valves.timeout)
        if hasattr(res, "body"):
            res = json.loads(res.body)
        return _NOISE.sub("", res["choices"][0]["message"].get("content") or "").strip()

    @staticmethod
    def _parse(reply: str, has_project: bool, limit: int) -> list:
        out = []
        for line in reply.splitlines():
            line = line.strip().lstrip("-*• ").strip()
            m = re.match(r"(?i)^(GLOBAL|PROJECT|UPDATE)\s*#?(\d+)?\s*:\s*(.+)$", line)
            if not m:
                continue
            kind, ref, text = m.group(1).upper(), m.group(2), m.group(3).strip().strip("<>")
            if kind == "UPDATE" and not ref:
                continue
            if kind == "PROJECT" and not has_project:
                kind = "GLOBAL"
            out.append((kind, int(ref) if ref else None, text))
            if len(out) >= limit:
                break
        return out

    async def _extract(self, chat_id: str, user_id: str, chat_model: str, messages: list, request: Any, emitter: Any) -> int:
        v = self.valves
        st = self._chat_state(chat_id)
        done = int(st.get("read_upto") or 0)
        if done > len(messages):  # the chat was edited or branched; start over from the last few turns
            done = max(len(messages) - 6, 0)
        fresh = [m for m in messages[done:] if m.get("role") in ("user", "assistant")]
        user_chars = sum(len(_text(m.get("content"))) for m in fresh if m.get("role") == "user")
        if user_chars < v.min_new_chars:
            return 0
        parts, used = [], 0
        for m in reversed(fresh):
            t = _text(m.get("content"))
            if not t:
                continue
            # The assistant's side is context only, so a short piece of it is enough.
            t = t[:4000] if m["role"] == "user" else t[:800]
            if used + len(t) > v.max_read_chars:
                break
            parts.append(f"{m['role'].upper()}: {t}")
            used += len(t)
        parts.reverse()
        project = (st.get("project") or "", st.get("project_name") or "")
        items = self._load(user_id)["items"]
        known = [m for m in items if not m.get("project") or m.get("project") == project[0]]
        known = sorted(known, key=lambda m: m.get("updated", 0), reverse=True)[:60]
        existing = "\n".join(f"#{m['id']} {m['text']}" for m in known) or "(none)"
        project_form = f"PROJECT: <fact that only matters for the project \"{project[1]}\">\n" if project[0] else ""
        prompt = (
            f"<existing_memories>\n{existing}\n</existing_memories>\n\n"
            f"<new_conversation>\n{chr(10).join(parts)}\n</new_conversation>\n\n"
            + EXTRACT_RULES.format(project_form=project_form, max_new=v.max_new_per_pass)
        )
        reply = await self._ask(request, user_id, self._model(request, chat_model), chat_model, chat_id, prompt)
        saved = self._add(user_id, self._parse(reply, bool(project[0]), v.max_new_per_pass), project, "auto", chat_id)
        st = self._chat_state(chat_id)
        st["read_upto"] = len(messages)
        self._put_chat_state(chat_id, st)
        if saved and v.show_status and emitter:
            try:
                await emitter({"type": "status", "data": {"description": f"Saved to memory: {'; '.join(saved)}"[:300], "done": True}})
            except Exception:
                pass
        return len(saved)

    async def _idle(self, chat_id: str, token: int, *args) -> None:
        try:
            await asyncio.sleep(max(self.valves.idle_seconds, 0))
            if self._seq.get(chat_id) != token:
                return  # the chat went on; the next quiet moment will cover these turns too
            await self._extract(chat_id, *args)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("auto_memory: idle pass failed", exc_info=True)
        finally:
            if self._tasks.get(chat_id) is asyncio.current_task():
                self._tasks.pop(chat_id, None)

    # -------------------------------------------------------------------- hooks
    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        msgs = body.get("messages")
        meta = __metadata__ or body.get("metadata") or {}
        if not isinstance(msgs, list) or not msgs or meta.get("task"):
            return body
        try:
            user_id = str((__user__ or {}).get("id") or "default")
            chat_id = str(meta.get("chat_id") or body.get("chat_id") or "")
            self._seq[chat_id] = self._seq.get(chat_id, 0) + 1
            task = self._tasks.pop(chat_id, None)
            if task:
                task.cancel()
            if isinstance(body.get("options"), dict):
                self._options[chat_id] = {k: v for k, v in body["options"].items() if k in LOAD_OPTIONS}
            project = await self._project(chat_id, user_id, meta)

            # "/remember ..." saves the text as it is, without waiting for the model to call a tool.
            last = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
            if last is not None and isinstance(last.get("content"), str):
                hit = REMEMBER.match(last["content"])
                if hit:
                    kind = "PROJECT" if project[0] else "GLOBAL"
                    saved = self._add(user_id, [(kind, None, hit.group(1))], project, "user", chat_id)
                    where = f'project "{project[1]}"' if project[0] else "global"
                    note = f"saved to {where} memory" if saved else "already in memory or not saveable"
                    last["content"] = f"{hit.group(1).strip()}\n\n[This was {note}. Confirm in one short sentence.]"

            st = self._chat_state(chat_id) if chat_id else {}
            now = time.time()
            if self.valves.inject:
                stale = now - float(st.get("seen") or 0) > self.valves.refresh_after_minutes * 60
                if "block" not in st or stale or st.get("project") != project[0]:
                    st["block"] = self._block(user_id, project)
                if st["block"]:
                    self._with_block(msgs, st["block"])
            st.update(seen=now, project=project[0], project_name=project[1])
            if chat_id:
                self._put_chat_state(chat_id, st)
        except Exception:
            # Memory is an extra; a bug here must never block the chat.
            log.exception("auto_memory: inlet failed, request passed through unchanged")
        return body

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __request__: Any = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        try:
            meta = __metadata__ or {}
            chat_id = str(body.get("chat_id") or meta.get("chat_id") or "")
            msgs = body.get("messages") or []
            # Temporary chats are meant to leave no trace.
            if not self.valves.auto_save or not chat_id or chat_id.startswith("local:") or __request__ is None or not msgs:
                return body
            user_id = str((__user__ or {}).get("id") or "default")
            old = self._tasks.pop(chat_id, None)
            if old:
                old.cancel()
            token = self._seq.get(chat_id, 0)
            snapshot = [{"role": m.get("role"), "content": m.get("content")} for m in msgs]
            self._tasks[chat_id] = asyncio.create_task(
                self._idle(chat_id, token, user_id, str(body.get("model") or ""), snapshot, __request__, __event_emitter__)
            )
        except Exception:
            log.debug("auto_memory: could not schedule the idle pass", exc_info=True)
        return body
