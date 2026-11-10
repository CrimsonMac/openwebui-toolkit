#!/usr/bin/env python3
"""Inspect JSON without reading all of it.

Usage:
  json_tool.py shape FILE              structure with types and array sizes
  json_tool.py get FILE PATH           value at a path, e.g. items[0].name or items[*].id
  json_tool.py paths FILE [--grep X]   every leaf path with its value
  json_tool.py diff A B                what differs between two JSON files
FILE may be - for stdin. Reports the exact position of syntax errors.
"""
import json
import re
import sys

NAMES = {"dict": "object", "list": "array", "str": "string", "int": "number", "float": "number", "bool": "boolean", "NoneType": "null"}


def load(name):
    text = sys.stdin.read() if name == "-" else open(name, encoding="utf-8-sig").read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        line = text.splitlines()[e.lineno - 1] if text.splitlines() else ""
        sys.exit(f"{name}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}\n  {line[:200]}\n  {' ' * min(e.colno - 1, 200)}^")


def shape(v, indent=0, key=None, out=None):
    pad = "  " * indent
    label = f"{key}: " if key is not None else ""
    if isinstance(v, dict):
        print(f"{pad}{label}object ({len(v)} keys)")
        for k, x in v.items():
            shape(x, indent + 1, k)
    elif isinstance(v, list):
        kinds = sorted({NAMES[type(x).__name__] for x in v})
        print(f"{pad}{label}array[{len(v)}] of {', '.join(kinds) or 'nothing'}")
        if v and isinstance(v[0], (dict, list)):
            if all(isinstance(x, dict) for x in v):
                merged = {}
                for x in v:
                    for k, val in x.items():
                        merged.setdefault(k, val)
                optional = [k for k in merged if any(k not in x for x in v)]
                shape(merged, indent + 1, "[each]")
                if optional:
                    print(f"{pad}    (not in every element: {', '.join(optional)})")
            else:
                shape(v[0], indent + 1, "[0]")
    else:
        text = json.dumps(v, ensure_ascii=False)
        print(f"{pad}{label}{NAMES[type(v).__name__]} = {text[:60]}{'…' if len(text) > 60 else ''}")


TOKEN = re.compile(r"\.?([^.\[\]]+)|\[(\d+|\*)\]")


def get(v, path):
    values = [v]
    for m in TOKEN.finditer(path.lstrip("$")):
        key, index = m.group(1), m.group(2)
        nxt = []
        for cur in values:
            if key is not None:
                if isinstance(cur, dict) and key in cur:
                    nxt.append(cur[key])
                elif isinstance(cur, list) and all(isinstance(x, dict) for x in cur):
                    nxt += [x[key] for x in cur if key in x]
                else:
                    have = ", ".join(list(cur)[:15]) if isinstance(cur, dict) else type(cur).__name__
                    sys.exit(f"no key '{key}' here; available: {have}")
            elif index == "*":
                if not isinstance(cur, list):
                    sys.exit(f"[*] used on a {type(cur).__name__}, not an array")
                nxt += cur
            else:
                if not isinstance(cur, list) or int(index) >= len(cur):
                    sys.exit(f"index [{index}] out of range (array has {len(cur) if isinstance(cur, list) else 0} elements)")
                nxt.append(cur[int(index)])
        values = nxt
    return values if "*" in path or len(values) != 1 else values[0]


def leaves(v, prefix=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from leaves(x, f"{prefix}.{k}" if prefix else k)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from leaves(x, f"{prefix}[{i}]")
    else:
        yield prefix, v


def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[0] not in ("shape", "get", "paths", "diff"):
        sys.exit(__doc__)
    cmd = args[0]
    if cmd == "shape":
        shape(load(args[1]))
    elif cmd == "get":
        if len(args) < 3:
            sys.exit("usage: json_tool.py get FILE PATH")
        print(json.dumps(get(load(args[1]), args[2]), indent=2, ensure_ascii=False))
    elif cmd == "paths":
        needle = args[3].lower() if len(args) > 3 and args[2] == "--grep" else None
        for path, val in leaves(load(args[1])):
            line = f"{path} = {json.dumps(val, ensure_ascii=False)}"
            if needle is None or needle in line.lower():
                print(line[:300])
    else:
        if len(args) < 3:
            sys.exit("usage: json_tool.py diff A B")
        a, b = dict(leaves(load(args[1]))), dict(leaves(load(args[2])))
        changes = 0
        for k in sorted(set(a) | set(b)):
            if k not in b:
                print(f"- {k} = {json.dumps(a[k], ensure_ascii=False)[:200]}")
            elif k not in a:
                print(f"+ {k} = {json.dumps(b[k], ensure_ascii=False)[:200]}")
            elif a[k] != b[k]:
                print(f"~ {k}: {json.dumps(a[k], ensure_ascii=False)[:100]} → {json.dumps(b[k], ensure_ascii=False)[:100]}")
            else:
                continue
            changes += 1
        print(f"{changes} difference(s)")


if __name__ == "__main__":
    main()
