#!/usr/bin/env python3
"""Test a regular expression against sample strings.

Usage:
  regex_test.py PATTERN [--flags imsx] [--should-match S ...] [--should-not-match S ...]
  regex_test.py PATTERN --file samples.txt        # one sample per line, shows what matches

Exit code 0 when every expectation holds, 1 otherwise.
"""
import argparse
import re
import sys

FLAGS = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}


def describe(m):
    out = f"matched {m.group(0)!r} at {m.start()}-{m.end()}"
    if m.groupdict():
        out += f" named={m.groupdict()}"
    elif m.groups():
        out += f" groups={m.groups()}"
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pattern")
    p.add_argument("--flags", default="", help="any of: i m s x")
    p.add_argument("--full", action="store_true", help="require the whole string to match")
    p.add_argument("--should-match", nargs="*", default=[])
    p.add_argument("--should-not-match", nargs="*", default=[])
    p.add_argument("--file", help="file with one sample per line")
    a = p.parse_args()

    flags = 0
    for ch in a.flags:
        if ch not in FLAGS:
            sys.exit(f"unknown flag {ch!r}; use any of i m s x")
        flags |= FLAGS[ch]
    try:
        rx = re.compile(a.pattern, flags)
    except re.error as e:
        pointer = " " * (e.pos or 0) + "^"
        sys.exit(f"invalid pattern: {e.msg}\n  {a.pattern}\n  {pointer}")

    find = rx.fullmatch if a.full else rx.search
    failures = 0
    for s in a.should_match:
        m = find(s)
        ok = m is not None
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} should match     {s!r}: {describe(m) if m else 'no match'}")
    for s in a.should_not_match:
        m = find(s)
        ok = m is None
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} should not match {s!r}: {describe(m) if m else 'no match'}")
    if a.file:
        with open(a.file, encoding="utf-8", errors="replace") as f:
            lines = [line.rstrip("\n") for line in f]
        hits = 0
        for n, line in enumerate(lines, 1):
            m = find(line)
            if m:
                hits += 1
                print(f"line {n}: {describe(m)}")
        print(f"{hits} of {len(lines)} lines matched")
    if not (a.should_match or a.should_not_match or a.file):
        print("pattern compiles; give --should-match / --should-not-match / --file to test it")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
