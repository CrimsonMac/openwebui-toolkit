"""
title: Wikipedia
author: Crimson
version: 1.0.0
description: Search Wikipedia and read articles in any language edition. No API key. Gives a local model a quick, citable source of facts.
"""

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, Field


def _api(lang: str, params: dict, timeout: int, user_agent: str) -> dict:
    if not lang.replace("-", "").isalnum() or len(lang) > 12:
        raise ValueError(f"'{lang}' is not a language code; use e.g. en, de, fr, es")
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _strip_html(s: str) -> str:
    import html
    import re

    return html.unescape(re.sub(r"<[^>]+>", "", s))


class Tools:
    class Valves(BaseModel):
        default_language: str = Field("en", description="Wikipedia language edition used when none is given.")
        max_chars: int = Field(6000, description="Characters of article text returned per call.")
        timeout: int = Field(15, description="Seconds before giving up.")
        user_agent: str = Field("wikipedia-tool/1.0 (Open WebUI tool)", description="User-Agent header; Wikipedia asks for a descriptive one.")

    def __init__(self):
        self.valves = self.Valves()

    async def _call(self, lang: str, params: dict) -> dict:
        return await asyncio.to_thread(_api, lang or self.valves.default_language, params, self.valves.timeout, self.valves.user_agent)

    @staticmethod
    def _error(e: Exception) -> str:
        if isinstance(e, urllib.error.HTTPError):
            return f"Error: Wikipedia answered HTTP {e.code}."
        if isinstance(e, urllib.error.URLError):
            return f"Error: could not reach Wikipedia ({e.reason})."
        return f"Error: {e}"

    async def search_wikipedia(self, query: str, language: str = "") -> str:
        """
        Search Wikipedia for articles. Use this first to find the exact article title, then read it with read_wikipedia_article.

        :param query: What to search for, for example "Treaty of Westphalia".
        :param language: Language edition code such as "en", "de", "fr". Leave empty for the default.
        :return: Up to 8 article titles with a short excerpt each.
        """
        try:
            data = await self._call(language.strip().lower(), {"action": "query", "list": "search", "srsearch": query, "srlimit": 8, "srprop": "snippet"})
        except Exception as e:
            return self._error(e)
        hits = data.get("query", {}).get("search", [])
        if not hits:
            suggestion = data.get("query", {}).get("searchinfo", {}).get("suggestion")
            return f"No articles found for '{query}'." + (f" Did you mean '{suggestion}'?" if suggestion else "")
        return "\n".join(f"- {h['title']}: {_strip_html(h.get('snippet', ''))}" for h in hits)

    async def read_wikipedia_article(self, title: str, language: str = "", section: str = "", start: int = 0) -> str:
        """
        Read a Wikipedia article as plain text. Without a section, returns the article from the top
        (the introduction comes first). Long articles come in parts; call again with the given `start` to continue.

        :param title: Exact article title as returned by search_wikipedia, for example "Photosynthesis".
        :param language: Language edition code such as "en", "de", "fr". Leave empty for the default.
        :param section: Optional heading to jump to, for example "History".
        :param start: Character position to continue from. Use 0 for the beginning.
        :return: The article text with its address, for citing.
        """
        lang = language.strip().lower() or self.valves.default_language
        try:
            data = await self._call(lang, {"action": "query", "prop": "extracts|info", "explaintext": 1, "exsectionformat": "wiki", "redirects": 1, "inprop": "url", "titles": title})
        except Exception as e:
            return self._error(e)
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") or not pages[0].get("extract"):
            return f"Error: no article titled '{title}' in the '{lang}' edition. Use search_wikipedia to find the exact title."
        page = pages[0]
        text = page["extract"]
        note = ""
        if section.strip():
            import re

            m = re.search(rf"^(=+)\s*{re.escape(section.strip())}\s*=+\s*$", text, re.MULTILINE | re.IGNORECASE)
            if m:
                level = len(m.group(1))
                rest = text[m.end():]
                end = re.search(rf"^={{1,{level}}}[^=].*=+\s*$", rest, re.MULTILINE)
                text = m.group(0) + (rest[: end.start()] if end else rest)
            else:
                heads = re.findall(r"^==\s*(.+?)\s*==\s*$", text, re.MULTILINE)
                note = f"[No section '{section}'. Sections: {', '.join(heads[:30])}]\n\n"
        start = max(0, int(start))
        cap = self.valves.max_chars
        part = text[start : start + cap]
        tail = f"\n\n[More text follows. Call read_wikipedia_article again with start={start + cap}.]" if start + cap < len(text) else ""
        return f"{page['title']} — {page.get('fullurl', '')}\nCharacters {start}-{start + len(part)} of {len(text)}\n\n{note}{part}{tail}"
