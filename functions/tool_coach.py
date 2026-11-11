"""
title: Tool Coach
author: Crimson
version: 1.0.0
required_open_webui_version: 0.5.0
description: Gets local models to actually use what they have. Adds short rules on when to call tools and load skills, and marks each user message with the tools and skills that fit it, picked by matching the message against their descriptions. The marks are the same on every turn, so the prompt cache is kept.
"""

import inspect
import logging
import re
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("tool_coach")

MARK = "[Using tools and skills]"
HINT = "[Hint:"

RULES = (
    f"{MARK}\n"
    "- A tool result beats a guess. Call a tool for arithmetic, dates, current facts, web pages, files, "
    "saved notes or memories, and anything else you cannot know for sure.\n"
    "- Skills are instruction packs for a kind of task. When a task matches a skill's description, "
    "load it with view_skill first, then follow it.\n"
    "- Just make the call. Do not ask for permission, and do not describe a call instead of making it.\n"
    "- Chain calls when one result is needed for the next. Several tools in one answer is normal.\n"
    "- After a result, check that it answers the question. If a call fails, read the error, fix the "
    "arguments and try once more; then say plainly what failed.\n"
    "- Never invent a tool name or a tool result. If nothing fits, answer normally.\n"
    "- A line starting with [Hint: in a user message names tools or skills that may fit. It is a suggestion, not an order."
)

STOP = set(
    "the and for with that this from are was were been have has had not but you your they them their its into about "
    "use used using when what which who how why where can could should would will may might must also any all each "
    "more most other some such than then there these those only one two user users asks ask asked wants want need "
    "needs give given get gets make makes made does doing done like just out via per e.g example examples model "
    "tool tools skill skills call calls let lets them it's etc both either before after over under same new own "
    "something anything everything help helps please tell show know see say find way thing things explain work works "
    "working write writing fix build got goes going keep keeps data file files text next now here still really very "
    "much many well good better best right wrong sure okay yes shows showing look looks try tried".split()
)

# Addresses, dates and links contain "/" and "-" without being arithmetic.
NOT_MATH = re.compile(r"https?://\S+|\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b|\b\d{4}-\d{2}-\d{2}\b|\bCVE-\d{4}-\d+\b", re.I)

# Things a message can ask for without naming them, as (pattern, words to add).
INTENTS = (
    (re.compile(r"\d\s*[-+*/^×÷]\s*\(?\d|\d\s*%\s*of\b|\bsquare root\b|\bhow much is\b", re.I), "arithmetic calculate calculation math"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b|\bsubnet\b|\bnetmask\b", re.I), "subnet cidr netmask"),
    (re.compile(r"https?://|\bwww\.\w", re.I), "url web page fetch link"),
    (re.compile(r"\b(today|tomorrow|yesterday|what day|weekday|how many days|days (until|since|between)|what time)\b", re.I), "date time days"),
    (re.compile(r"\b(remember|don't forget|do not forget|keep in mind|from now on)\b", re.I), "remember memory save"),
    (re.compile(r"\b(last time|earlier chat|previous chat|we talked|i told you|you know about)\b", re.I), "recall memory search"),
    (re.compile(r"\bCVE-\d{4}-\d+\b", re.I), "cve vulnerability lookup"),
    (re.compile(r"\b(nmap|masscan|port scan|open ports?)\b", re.I), "pentest methodology scan"),
)


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def _words(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-z][a-z0-9]{2,}", text.lower()) if w not in STOP}


def _text(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return str(content or "")


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Filter:
    class Valves(BaseModel):
        priority: int = Field(20, description="Filter order; lower runs first.")
        add_rules: bool = Field(True, description="Add the short rules on using tools and skills to the system prompt.")
        add_hints: bool = Field(True, description="Mark user messages with the tools and skills that fit them.")
        min_score: int = Field(
            2, description="How well a tool or skill must match a message to be named. One point per shared word, two if the word is in its name, half if many tools share the word."
        )
        max_hints: int = Field(3, description="At most this many tools and this many skills are named per message.")
        include_skills: bool = Field(True, description="Also match against the skills the user can use.")
        catalog_seconds: int = Field(300, description="How long the list of tools and skills is kept before it is read again.")

    def __init__(self):
        self.valves = self.Valves()
        self._catalogs: dict = {}  # key -> (time, entries)

    # ------------------------------------------------------------------ catalog
    async def _catalog(self, user_id: str, tool_ids: list) -> list:
        """Returns (entries, rare). Entries: (kind, name, name words, description words). rare: words few entries share."""
        key = (user_id, tuple(sorted(tool_ids)), self.valves.include_skills)
        hit = self._catalogs.get(key)
        if hit and time.time() - hit[0] < self.valves.catalog_seconds:
            return hit[1]
        entries: list = []
        try:
            from open_webui.models.tools import Tools

            for tid in tool_ids:
                tool = await _maybe(Tools.get_tool_by_id(tid))
                for spec in getattr(tool, "specs", None) or []:
                    name = str(spec.get("name") or "")
                    if name:
                        entries.append(("tool", name, _words(name.replace("_", " ")), _words(str(spec.get("description") or ""))))
        except Exception:
            log.debug("tool_coach: could not read tool specs", exc_info=True)
        if self.valves.include_skills:
            try:
                from open_webui.models.skills import Skills

                for s in await _maybe(Skills.get_skills(user_id=user_id)) or []:
                    if getattr(s, "is_active", True) and getattr(s, "name", ""):
                        entries.append(("skill", s.name, _words(s.name.replace("-", " ")), _words(str(getattr(s, "description", "") or ""))))
            except Exception:
                log.debug("tool_coach: could not read skills", exc_info=True)
        # A word that most entries share says nothing about which one fits.
        if len(entries) >= 5:
            common = {w for w in set().union(*(e[3] for e in entries)) if sum(w in e[3] for e in entries) > len(entries) * 0.4}
            entries = [(k, n, nw, dw - common) for k, n, nw, dw in entries]
        every = set().union(*(e[2] | e[3] for e in entries)) if entries else set()
        rare = {w for w in every if sum(w in e[2] or w in e[3] for e in entries) <= 3}
        if len(self._catalogs) > 64:
            self._catalogs.clear()
        self._catalogs[key] = (time.time(), (entries, rare))
        return entries, rare

    # -------------------------------------------------------------------- hints
    def _hint(self, text: str, entries: list, rare: set) -> str:
        words = _words(text)
        for n, (pattern, extra) in enumerate(INTENTS):
            if pattern.search(NOT_MATH.sub(" ", text) if n == 0 else text):
                words |= {_stem(w) for w in extra.split()}
        if not words:
            return ""
        scored = []
        for kind, name, name_words, desc_words in entries:
            # A word that only a few entries use says more than one that many share.
            score = 2 * len(words & name_words) + sum(1 if w in rare else 0.5 for w in words & (desc_words - name_words))
            if score >= self.valves.min_score:
                scored.append((score, kind, name))
        if not scored:
            return ""
        scored.sort(key=lambda x: (-x[0], x[2]))
        # Weak tag-alongs next to a clear winner are noise.
        scored = [x for x in scored if x[0] >= scored[0][0] * 0.6]
        tools = [n for _, k, n in scored if k == "tool"][: self.valves.max_hints]
        skills = [n for _, k, n in scored if k == "skill"][: self.valves.max_hints]
        parts = []
        if tools:
            parts.append("tools " + ", ".join(tools))
        if skills:
            parts.append("skills " + ", ".join(skills) + " (load with view_skill first)")
        return f"{HINT} these may fit this message: {'; '.join(parts)}. Use them if they help.]"

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        msgs = body.get("messages")
        meta = __metadata__ or body.get("metadata") or {}
        if not isinstance(msgs, list) or not msgs or meta.get("task"):
            return body
        try:
            model_meta = ((__model__ or {}).get("info") or {}).get("meta") or {}
            tool_ids = list(dict.fromkeys(list(body.get("tool_ids") or meta.get("tool_ids") or []) + list(model_meta.get("toolIds") or [])))
            # External tool servers have ids like "server:..."; only local tools have stored specs.
            tool_ids = [t for t in tool_ids if isinstance(t, str) and ":" not in t]
            entries, rare = await self._catalog(str((__user__ or {}).get("id") or ""), tool_ids)
            features = body.get("features") or meta.get("features") or {}
            if not entries and not any(features.values()):
                return body

            if self.valves.add_rules:
                system = next((m for m in msgs if m.get("role") == "system"), None)
                if system is None:
                    msgs.insert(0, {"role": "system", "content": RULES})
                elif MARK not in _text(system.get("content")):
                    c = system.get("content")
                    if isinstance(c, list):
                        system["content"] = c + [{"type": "text", "text": RULES}]
                    else:
                        system["content"] = f"{c or ''}\n\n{RULES}".strip()

            if self.valves.add_hints and entries:
                # Every user message gets the hint its own text earns, on every turn, so
                # earlier messages look the same as last time and the prompt cache holds.
                for m in msgs:
                    if m.get("role") != "user":
                        continue
                    text = _text(m.get("content"))
                    if HINT in text:
                        continue
                    hint = self._hint(text, entries, rare)
                    if not hint:
                        continue
                    c = m.get("content")
                    if isinstance(c, list):
                        m["content"] = c + [{"type": "text", "text": hint}]
                    else:
                        m["content"] = f"{c or ''}\n\n{hint}"
        except Exception:
            log.exception("tool_coach: failed, request passed through unchanged")
        return body
