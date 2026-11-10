#!/usr/bin/env python3
"""Get an Ollama model ready before the first message, so the first reply is not slow.

Two steps, both optional:
  1. Read the model's files into the operating system's file cache. A freshly booted
     machine otherwise reads them from disk in the middle of your first prompt.
  2. With --load, ask Ollama to load the model with its own settings and keep it loaded.

Usage:
  ollama_prewarm.py MODEL                 # warm the file cache only
  ollama_prewarm.py MODEL --load          # also load it into memory
  ollama_prewarm.py MODEL --load --keep-alive 2h
  ollama_prewarm.py MODEL --status        # show how much of the model is cached, change nothing

Run it on the machine where Ollama runs. Standard library only; needs read access to the model files.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


def call(base, path, payload=None, timeout=1800):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def cached_fraction(path):
    """Share of a file that is in the page cache, from util-linux `fincore`. None when unavailable."""
    import shutil
    import subprocess

    if not shutil.which("fincore"):
        return None
    try:
        out = subprocess.run(
            ["fincore", "--bytes", "--noheadings", "--output", "RES,SIZE", path], capture_output=True, text=True, timeout=30
        ).stdout.split()
        return int(out[0]) / int(out[1]) if len(out) >= 2 and int(out[1]) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def read_into_cache(path, chunk=8 * 1024 * 1024):
    size = os.path.getsize(path)
    done, start = 0, time.monotonic()
    with open(path, "rb", buffering=0) as f:
        try:
            os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_SEQUENTIAL)
        except (AttributeError, OSError):
            pass
        buf = bytearray(chunk)
        while True:
            n = f.readinto(buf)
            if not n:
                break
            done += n
            if sys.stderr.isatty():
                sys.stderr.write(f"\r  {done / size:5.1%}")
    took = time.monotonic() - start
    if sys.stderr.isatty():
        sys.stderr.write("\r")
    return size, took


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model", nargs="+")
    p.add_argument("--url", default="http://localhost:11434")
    p.add_argument("--load", action="store_true", help="also load the (first) model into memory")
    p.add_argument("--keep-alive", default="", help="how long Ollama keeps it loaded, e.g. 30m, 2h, -1 for ever. Default: the server's setting")
    p.add_argument("--status", action="store_true", help="only report how much is cached")
    a = p.parse_args()

    for model in a.model:
        try:
            info = call(a.url, "/api/show", {"model": model})
        except urllib.error.HTTPError:
            sys.exit(f"model '{model}' not found")
        except urllib.error.URLError as e:
            sys.exit(f"cannot reach Ollama at {a.url}: {e.reason}")
        files = [f for f in re.findall(r"^FROM\s+(/\S+)", info.get("modelfile", ""), re.MULTILINE) if os.path.isfile(f)]
        if not files:
            print(f"{model}: the model files are not on this machine (or not readable); skipping the file cache step")
        for path in files:
            size = os.path.getsize(path)
            frac = cached_fraction(path)
            label = f"{model}: {os.path.basename(path)[:19]}… {size / 1024**3:.1f} GB"
            if a.status:
                print(f"{label}: " + (f"{frac:.0%} in the file cache" if frac is not None else "cache state cannot be measured (needs util-linux fincore and ownership of the files); a fast read below means it was cached"))
                continue
            if frac is not None and frac > 0.97:
                print(f"{label}: already cached")
                continue
            if not os.access(path, os.R_OK):
                print(f"{label}: no read permission; skipping")
                continue
            _, took = read_into_cache(path)
            after = cached_fraction(path)
            note = f", {after:.0%} now cached" if after is not None else ""
            print(f"{label}: read in {took:.0f} s ({size / 1024**2 / max(took, 0.01):.0f} MB/s){note}")
            if after is not None and after < 0.9:
                print("  The cache did not keep all of it: there is not enough free memory. Close other programs or use a smaller model.")

    if a.load and not a.status:
        model = a.model[0]
        payload = {"model": model}
        if a.keep_alive:
            payload["keep_alive"] = int(a.keep_alive) if re.fullmatch(r"-?\d+", a.keep_alive) else a.keep_alive
        start = time.monotonic()
        try:
            call(a.url, "/api/generate", payload)
        except urllib.error.HTTPError as e:
            sys.exit(f"loading failed: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:200]}")
        ps = next((m for m in call(a.url, "/api/ps").get("models", []) if m.get("name", "").split(":")[0] == model.split(":")[0]), {})
        ctx = f", context {ps['context_length']}" if ps.get("context_length") else ""
        print(f"{model}: loaded in {time.monotonic() - start:.0f} s{ctx}. It reloads if a request asks for different settings (context size, batch size).")


if __name__ == "__main__":
    main()
