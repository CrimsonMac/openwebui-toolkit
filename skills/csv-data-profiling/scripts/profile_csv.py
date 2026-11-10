#!/usr/bin/env python3
"""Profile a CSV or TSV file: row count, and per column the type, missing values,
distinct values, range and most common values.

Usage: profile_csv.py FILE [--delimiter ,] [--max-rows 200000] [--top 5]
"""
import argparse
import csv
import statistics
import sys
from collections import Counter
from datetime import datetime

MISSING = {"", "na", "n/a", "nan", "null", "none", "-", "?"}
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y")


def to_number(s):
    t = s.replace(" ", "")
    if t.count(",") == 1 and "." not in t:
        t = t.replace(",", ".")  # decimal comma
    else:
        t = t.replace(",", "")  # thousands separator
    try:
        return float(t)
    except ValueError:
        return None


def to_date(s):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("file")
    p.add_argument("--delimiter")
    p.add_argument("--max-rows", type=int, default=200000)
    p.add_argument("--top", type=int, default=5)
    a = p.parse_args()

    with open(a.file, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(65536)
        f.seek(0)
        delim = a.delimiter
        if not delim:
            try:
                delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delim = ","
        reader = csv.reader(f, delimiter=delim)
        try:
            header = next(reader)
        except StopIteration:
            sys.exit("file is empty")
        cols = [[] for _ in header]
        rows = ragged = 0
        truncated = False
        seen, duplicates = set(), 0
        for row in reader:
            if rows >= a.max_rows:
                truncated = True
                break
            rows += 1
            if len(row) != len(header):
                ragged += 1
            key = tuple(row)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
            for i in range(len(header)):
                cols[i].append(row[i].strip() if i < len(row) else "")

    print(f"file: {a.file}")
    print(f"delimiter: {delim!r}   columns: {len(header)}   rows: {rows}{' (stopped at --max-rows)' if truncated else ''}")
    if ragged:
        print(f"WARNING: {ragged} rows have a different number of fields than the header")
    if duplicates:
        print(f"WARNING: {duplicates} fully duplicated rows")
    if len(set(header)) != len(header):
        print("WARNING: duplicate column names")
    print()

    for name, values in zip(header, cols):
        present = [v for v in values if v.lower() not in MISSING]
        missing = len(values) - len(present)
        distinct = len(set(present))
        nums = [n for n in (to_number(v) for v in present) if n is not None]
        line = f"[{name}]"
        if not present:
            print(f"{line} empty column")
            continue
        pct = f"{missing} missing ({missing / len(values):.1%})" if missing else "no missing"
        if len(nums) >= 0.95 * len(present):
            kind = "integer" if all(n.is_integer() for n in nums) else "number"
            q = statistics.quantiles(nums, n=4) if len(nums) >= 4 else [min(nums), statistics.median(nums), max(nums)]
            print(f"{line} {kind}, {pct}, {distinct} distinct")
            print(f"    min {min(nums):g}  q1 {q[0]:g}  median {statistics.median(nums):g}  q3 {q[2]:g}  max {max(nums):g}  mean {statistics.fmean(nums):g}")
            if len(nums) >= 4:
                iqr = q[2] - q[0]
                out = [n for n in nums if n < q[0] - 3 * iqr or n > q[2] + 3 * iqr] if iqr else []
                if out:
                    print(f"    {len(out)} extreme outliers, e.g. {sorted(set(out))[:3]}")
            if len(nums) < len(present):
                bad = [v for v in present if to_number(v) is None][:3]
                print(f"    {len(present) - len(nums)} non-numeric values, e.g. {bad}")
            continue
        dates = [d for d in (to_date(v) for v in present[:2000]) if d]
        if len(dates) >= 0.95 * min(len(present), 2000):
            print(f"{line} date, {pct}, {distinct} distinct, from {min(dates):%Y-%m-%d} to {max(dates):%Y-%m-%d}")
            continue
        kind = "id-like text (all distinct)" if distinct == len(present) else ("category" if distinct <= 50 else "text")
        lengths = [len(v) for v in present]
        print(f"{line} {kind}, {pct}, {distinct} distinct, length {min(lengths)}-{max(lengths)}")
        if distinct != len(present):
            top = ", ".join(f"{v!r}×{c}" for v, c in Counter(present).most_common(a.top))
            print(f"    most common: {top}")
        variants = Counter(v.lower() for v in set(present))
        clash = [k for k, c in variants.items() if c > 1][:3]
        if clash:
            print(f"    same value in different casing: {clash}")


if __name__ == "__main__":
    main()
