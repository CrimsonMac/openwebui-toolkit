"""
title: Output Cleanup
author: Crimson
version: 1.0.0
required_open_webui_version: 0.5.0
description: Tidies replies from local models after they finish - removes leaked chat-template tokens, cuts a paragraph that got stuck repeating, and collapses runs of blank lines. Code blocks are left untouched.
"""

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

# Control tokens of common chat templates that sometimes leak into the visible reply.
TOKENS = re.compile(
    r"<\|start_header_id\|>\w*<\|end_header_id\|>|<\|im_start\|>(?:assistant|user|system)?"
    r"|<start_of_turn>(?:model|user)?"
    r"|<\|(?:im_start|im_end|endoftext|eot_id|end_of_text|begin_of_text|start_header_id|end_header_id|end|user|assistant|system|eom_id|python_tag)\|>"
    r"|</?(?:start_of_turn|end_of_turn|bos|eos)>"
    r"|\[/?INST\]|<</?SYS>>|</s>(?=\s|$)|<｜(?:end▁of▁sentence|begin▁of▁sentence|User|Assistant)｜>"
)
ROLE_LINE = re.compile(r"^(?:assistant|model|user)\s*$", re.MULTILINE)
FENCE = re.compile(r"(```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)|`[^`\n]+`)", re.DOTALL)
DETAILS = re.compile(r"(<details\b.*?</details>)", re.DOTALL)


def _outside_code(text: str, fn) -> str:
    """Apply fn only to the parts that are not code or collapsed detail blocks."""
    out = []
    for i, part in enumerate(DETAILS.split(text)):
        if i % 2:
            out.append(part)
            continue
        for j, piece in enumerate(FENCE.split(part)):
            out.append(piece if j % 2 else fn(piece))
    return "".join(out)


def _cut_repetition(text: str, min_repeats: int, min_chars: int):
    """If the reply ends in the same block repeated over and over, keep one copy."""
    blocks = text.rstrip().split("\n\n")
    if len(blocks) >= min_repeats:
        last = blocks[-1].strip()
        n = 0
        # The final block is often cut off mid-way, so compare it by prefix.
        probe = blocks[-2].strip() if len(blocks) > 1 and blocks[-2].strip().startswith(last) else last
        if len(probe) >= min_chars:
            for b in reversed(blocks[:-1] if probe != last else blocks):
                if b.strip() == probe:
                    n += 1
                else:
                    break
            if n >= min_repeats:
                drop = n - 1 + (1 if probe != last else 0)
                return "\n\n".join(blocks[: len(blocks) - drop]), drop
    # Same line repeated at the end (lists and single-line loops).
    lines = text.rstrip().split("\n")
    if len(lines) >= min_repeats * 2:
        probe = lines[-2].strip() if lines[-2].strip().startswith(lines[-1].strip()) and lines[-2].strip() else lines[-1].strip()
        if len(probe) >= min_chars:
            body = lines[:-1] if probe != lines[-1].strip() else lines
            n = 0
            for ln in reversed(body):
                if ln.strip() == probe:
                    n += 1
                else:
                    break
            if n >= min_repeats * 2:
                drop = n - 1 + (1 if probe != lines[-1].strip() else 0)
                return "\n".join(lines[: len(lines) - drop]), drop
    return text, 0


class Filter:
    class Valves(BaseModel):
        priority: int = Field(0, description="Filter order; lower runs first.")
        strip_tokens: bool = Field(True, description="Remove leaked chat-template tokens such as <|im_end|> or <end_of_turn>.")
        cut_repetition: bool = Field(True, description="When a reply ends in the same paragraph or line repeated, keep one copy.")
        min_repeats: int = Field(3, description="How many identical paragraphs in a row count as a loop (lines need twice as many).")
        min_repeat_chars: int = Field(20, description="Ignore repeats shorter than this, such as list bullets or blank table rows.")
        collapse_blank_lines: bool = Field(True, description="Reduce three or more blank lines to one.")
        note_when_cut: bool = Field(True, description="Add a short note to the reply when repetition was removed.")

    def __init__(self):
        self.valves = self.Valves()

    def clean(self, text: str) -> str:
        v = self.valves
        original = text
        if v.strip_tokens:
            def strip(s: str) -> str:
                had = TOKENS.search(s)
                s = TOKENS.sub("", s)
                return ROLE_LINE.sub("", s) if had else s

            text = _outside_code(text, strip)
        if v.collapse_blank_lines:
            text = _outside_code(text, lambda s: re.sub(r"\n[ \t]*(?:\n[ \t]*){2,}", "\n\n", s))
        if v.cut_repetition and text.count("```") % 2 == 0:
            text, dropped = _cut_repetition(text, max(v.min_repeats, 2), max(v.min_repeat_chars, 1))
            if dropped and v.note_when_cut:
                text = text.rstrip() + f"\n\n*[The model got stuck repeating itself; {dropped} repeated block(s) removed.]*"
        text = text.strip() if text != original else text
        return text or original

    async def outlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        try:
            msgs = body.get("messages") or []
            if msgs and msgs[-1].get("role") == "assistant" and isinstance(msgs[-1].get("content"), str):
                msgs[-1]["content"] = self.clean(msgs[-1]["content"])
        except Exception:
            # Cosmetic filter: never break a reply over it.
            logging.getLogger("output_cleanup").debug("cleanup skipped", exc_info=True)
        return body
