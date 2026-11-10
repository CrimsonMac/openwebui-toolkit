"""
title: Text Utilities
author: Crimson
version: 1.0.0
description: Exact text operations that language models get wrong by eye - counting, comparing, sorting, regex matching, hashing, encoding and JSON validation. No dependencies, no network.
"""

import base64
import difflib
import hashlib
import json
import re
import unicodedata
import urllib.parse
from collections import Counter

MAX_OUT = 6000


def _clip(s: str) -> str:
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f"\n[... output cut, {len(s) - MAX_OUT} more characters]"


class Tools:
    def __init__(self):
        pass

    async def count_text(self, text: str, find: str = "") -> str:
        """
        Count characters, words, lines and sentences in a text exactly. Optionally count how often a word,
        letter or phrase occurs. Use this for ANY counting question ("how many r in strawberry", "how long is this").

        :param text: The text to measure.
        :param find: Optional letter, word or phrase to count inside the text, for example "r". Case-insensitive.
        :return: The counts.
        """
        words = re.findall(r"\w+(?:['’-]\w+)*", text)
        sentences = [s for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s]
        no_space = re.sub(r"\s", "", text)
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        out = [
            f"characters: {len(text)} ({len(no_space)} without whitespace)",
            f"words: {len(words)}",
            f"lines: {len(text.splitlines()) or (1 if text else 0)}",
            f"sentences: {len(sentences)}",
            f"paragraphs: {len(paragraphs)}",
            f"reading time: about {max(1, round(len(words) / 220))} min",
        ]
        if find:
            n = text.lower().count(find.lower())
            positions = [m.start() + 1 for m in re.finditer(re.escape(find.lower()), text.lower())][:30]
            out.append(f"'{find}' occurs {n} time(s)" + (f" at character position(s) {positions}" if n else ""))
            if len(find) > 1:
                whole = len(re.findall(rf"(?<!\w){re.escape(find)}(?!\w)", text, re.IGNORECASE))
                out.append(f"as a whole word: {whole} time(s)")
        return "\n".join(out)

    async def word_frequency(self, text: str, top: int = 15, min_length: int = 3) -> str:
        """
        List the most frequent words in a text with exact counts.

        :param text: The text to analyse.
        :param top: How many words to list.
        :param min_length: Ignore words shorter than this many letters.
        :return: Words with their counts, most frequent first.
        """
        words = [w.lower() for w in re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", text) if len(w) >= min_length]
        if not words:
            return "No words found."
        counts = Counter(words).most_common(max(1, min(top, 100)))
        return f"{len(words)} words, {len(set(words))} distinct\n" + "\n".join(f"{c:>5}  {w}" for w, c in counts)

    async def compare_texts(self, text_a: str, text_b: str) -> str:
        """
        Show exactly what differs between two texts, line by line, plus a similarity percentage.
        Use this instead of comparing by eye.

        :param text_a: The first (old) text.
        :param text_b: The second (new) text.
        :return: A unified diff, or a note that the texts are identical.
        """
        if text_a == text_b:
            return "The texts are identical."
        ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
        a, b = text_a.splitlines(), text_b.splitlines()
        diff = list(difflib.unified_diff(a, b, "A", "B", lineterm="", n=1))
        if a == b:
            return f"Same lines; they differ only in line endings or trailing whitespace. Similarity {ratio:.1%}."
        if len(a) == 1 and len(b) == 1:
            sm = difflib.SequenceMatcher(None, text_a, text_b)
            parts = [
                f"{tag}: {text_a[i1:i2]!r} → {text_b[j1:j2]!r}"
                for tag, i1, i2, j1, j2 in sm.get_opcodes()
                if tag != "equal"
            ]
            return _clip(f"Similarity {ratio:.1%}\n" + "\n".join(parts))
        added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        return _clip(f"Similarity {ratio:.1%}, {added} line(s) added, {removed} removed\n" + "\n".join(diff))

    async def transform_lines(self, text: str, operation: str) -> str:
        """
        Apply an exact operation to the lines of a text.

        :param text: The text, one item per line.
        :param operation: One of "sort", "sort_desc", "sort_numeric", "unique", "reverse", "trim", "remove_empty", "number", "upper", "lower", "title", "duplicates" (list lines that occur more than once).
        :return: The transformed text.
        """
        lines = text.splitlines()
        op = operation.strip().lower()

        def num(s):
            m = re.search(r"-?\d+(?:[.,]\d+)?", s)
            return float(m.group(0).replace(",", ".")) if m else float("inf")

        if op == "sort":
            lines = sorted(lines, key=str.casefold)
        elif op == "sort_desc":
            lines = sorted(lines, key=str.casefold, reverse=True)
        elif op == "sort_numeric":
            lines = sorted(lines, key=num)
        elif op == "unique":
            lines = list(dict.fromkeys(lines))
        elif op == "reverse":
            lines = lines[::-1]
        elif op == "trim":
            lines = [x.strip() for x in lines]
        elif op == "remove_empty":
            lines = [x for x in lines if x.strip()]
        elif op == "number":
            lines = [f"{i}. {x}" for i, x in enumerate(lines, 1)]
        elif op in ("upper", "lower", "title"):
            lines = [getattr(x, op)() for x in lines]
        elif op == "duplicates":
            dup = [(x, c) for x, c in Counter(lines).items() if c > 1]
            return "\n".join(f"{c}× {x}" for x, c in dup) or "No duplicate lines."
        else:
            return "Error: unknown operation. Use sort, sort_desc, sort_numeric, unique, reverse, trim, remove_empty, number, upper, lower, title or duplicates."
        return _clip("\n".join(lines))

    async def regex_find(self, pattern: str, text: str, ignore_case: bool = False) -> str:
        """
        Run a regular expression (Python syntax) against a text and list every match with its groups.
        Use this to test a regex or to extract all emails, numbers, dates and similar from a text.

        :param pattern: The regular expression, for example "\\b\\d{4}-\\d{2}-\\d{2}\\b".
        :param text: The text to search.
        :param ignore_case: True to match case-insensitively.
        :return: The matches, or the position of the syntax error in the pattern.
        """
        try:
            rx = re.compile(pattern, re.MULTILINE | (re.IGNORECASE if ignore_case else 0))
        except re.error as e:
            return f"Error: invalid pattern at position {e.pos}: {e.msg}"
        if len(text) > 200000:
            return "Error: text too long (limit 200000 characters)."
        out = []
        for i, m in enumerate(rx.finditer(text), 1):
            if i > 100:
                out.append("[... more than 100 matches, list cut]")
                break
            line = f"{i}. {m.group(0)!r} at {m.start()}-{m.end()}"
            if m.groupdict():
                line += f" {m.groupdict()}"
            elif m.groups():
                line += f" groups={m.groups()}"
            out.append(line)
        return _clip("\n".join(out)) if out else "No matches."

    async def encode_decode(self, text: str, method: str) -> str:
        """
        Encode, decode or hash a text exactly.

        :param text: The input text.
        :param method: One of "base64_encode", "base64_decode", "url_encode", "url_decode", "hex_encode", "hex_decode", "md5", "sha1", "sha256", "sha512", "rot13", "reverse", "slug", "unicode_names".
        :return: The result.
        """
        m = method.strip().lower()
        try:
            if m == "base64_encode":
                return base64.b64encode(text.encode()).decode()
            if m == "base64_decode":
                return _clip(base64.b64decode(text.strip() + "=" * (-len(text.strip()) % 4)).decode("utf-8", "replace"))
            if m == "url_encode":
                return urllib.parse.quote(text, safe="")
            if m == "url_decode":
                return urllib.parse.unquote_plus(text)
            if m == "hex_encode":
                return text.encode().hex()
            if m == "hex_decode":
                return _clip(bytes.fromhex(re.sub(r"\s|0x", "", text)).decode("utf-8", "replace"))
            if m in ("md5", "sha1", "sha256", "sha512"):
                return hashlib.new(m, text.encode()).hexdigest()
            if m == "rot13":
                import codecs

                return codecs.encode(text, "rot13")
            if m == "reverse":
                return text[::-1]
            if m == "slug":
                s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
                return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
            if m == "unicode_names":
                return _clip("\n".join(f"U+{ord(c):04X} {unicodedata.name(c, 'UNKNOWN')} {c!r}" for c in text[:200]))
        except Exception as e:
            return f"Error: {e}"
        return "Error: unknown method. Use base64_encode, base64_decode, url_encode, url_decode, hex_encode, hex_decode, md5, sha1, sha256, sha512, rot13, reverse, slug or unicode_names."

    async def check_json(self, text: str) -> str:
        """
        Validate JSON and pretty-print it. On invalid JSON, reports the exact line and column of the error.

        :param text: The JSON text to check.
        :return: The formatted JSON, or where and why it is invalid.
        """
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            lines = text.splitlines() or [""]
            bad = lines[min(e.lineno - 1, len(lines) - 1)]
            return f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}\n{bad[:200]}\n{' ' * min(e.colno - 1, 200)}^"
        kind = f"object with {len(data)} keys" if isinstance(data, dict) else f"array with {len(data)} elements" if isinstance(data, list) else type(data).__name__
        return _clip(f"Valid JSON ({kind}).\n" + json.dumps(data, indent=2, ensure_ascii=False))
