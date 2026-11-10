#!/usr/bin/env python3
"""Condense a log file: group lines that differ only in numbers, ids and timestamps,
count them, and show the first occurrence of each error pattern.

Usage: log_summary.py FILE [--top 20] [--level error|warn|all] [--grep REGEX]
       some_command | log_summary.py -
"""
import argparse
import re
import sys
from collections import OrderedDict

MASKS = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"), "<TIME>"),
    (re.compile(r"\b[A-Z][a-z]{2}\s+\d{1,2}\s\d{2}:\d{2}:\d{2}\b"), "<TIME>"),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<TIME>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<IP>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<HEX>"),
    (re.compile(r"\b[0-9a-f]{12,}\b"), "<HASH>"),
    (re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])"), "<N>"),
]
LEVELS = [
    ("error", re.compile(r"\b(?:FATAL|CRITICAL|ERROR|ERR|PANIC|Traceback|Exception|panic:|segfault)\b|\bfailed\b", re.I)),
    ("warn", re.compile(r"\b(?:WARN|WARNING|deprecated|timeout|timed out|retry(?:ing)?)\b", re.I)),
]
TIME = MASKS[0][0]


def level_of(line):
    for name, rx in LEVELS:
        if rx.search(line):
            return name
    return "info"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("file", help="log file, or - for stdin")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--level", choices=["error", "warn", "all"], default="warn", help="lowest level to list (default warn)")
    p.add_argument("--grep", help="only consider lines matching this regex")
    a = p.parse_args()

    grep = re.compile(a.grep) if a.grep else None
    stream = sys.stdin if a.file == "-" else open(a.file, encoding="utf-8", errors="replace")
    groups = OrderedDict()
    totals = {"error": 0, "warn": 0, "info": 0}
    n = 0
    first_time = last_time = None
    with stream:
        for n, raw in enumerate(stream, 1):
            line = raw.rstrip("\n")
            if not line.strip() or (grep and not grep.search(line)):
                continue
            t = TIME.search(line)
            if t:
                first_time = first_time or t.group(0)
                last_time = t.group(0)
            lvl = level_of(line)
            totals[lvl] += 1
            key = line
            for rx, token in MASKS:
                key = rx.sub(token, key)
            key = key[:300]
            g = groups.get(key)
            if g is None:
                groups[key] = {"count": 1, "level": lvl, "first": n, "last": n, "example": line[:400]}
            else:
                g["count"] += 1
                g["last"] = n

    print(f"{n} lines, {len(groups)} distinct patterns; errors {totals['error']}, warnings {totals['warn']}, other {totals['info']}")
    if first_time:
        print(f"time span: {first_time} → {last_time}")
    wanted = {"error": ("error",), "warn": ("error", "warn"), "all": ("error", "warn", "info")}[a.level]
    order = {"error": 0, "warn": 1, "info": 2}
    chosen = sorted(
        (g for g in groups.values() if g["level"] in wanted),
        key=lambda g: (order[g["level"]], -g["count"]),
    )
    if not chosen:
        print("nothing at this level; try --level all")
        return
    print()
    for g in chosen[: a.top]:
        where = f"line {g['first']}" if g["count"] == 1 else f"lines {g['first']}–{g['last']}"
        print(f"{g['count']:>6}×  {g['level'].upper():5}  {where}")
        print(f"         {g['example']}")
    if len(chosen) > a.top:
        print(f"... {len(chosen) - a.top} more patterns; raise --top to see them")
    errors = [g for g in groups.values() if g["level"] == "error"]
    if errors:
        first = min(errors, key=lambda g: g["first"])
        print(f"\nfirst error is at line {first['first']}; read the lines just before it for the trigger")


if __name__ == "__main__":
    main()
