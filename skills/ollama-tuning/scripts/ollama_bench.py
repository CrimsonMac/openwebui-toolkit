#!/usr/bin/env python3
"""Measure how an Ollama model performs at different settings on this machine.

For each combination of context size and batch size it loads the model fresh and reports:
  load      seconds to load the model
  gpu       share of the model's memory that sits in VRAM
  read      prompt processing speed in tokens/s (what you wait for before the first word)
  write     generation speed in tokens/s
  warm      seconds until the first token on a follow-up turn that reuses the prompt cache

Usage:
  ollama_bench.py MODEL --ctx 8192 32768 131072
  ollama_bench.py MODEL --ctx 32768 --batch 512 2048 --prompt-tokens 8000
  ollama_bench.py MODEL --ctx 32768 --repeat 3 --option use_mmap=false

It unloads whatever is loaded, so do not run it while the server is in use.
Standard library only.
"""
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request

WORDS = (
    "river stone market window signal orbit garden ledger harbor copper lantern meadow "
    "engine paper winter bridge thread canyon silver anchor forest marble signal valley"
).split()


def call(base, path, payload=None, timeout=3600):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def stream_first_token(base, payload, timeout=3600):
    """Run a streaming request; return (seconds to first token, final stats)."""
    req = urllib.request.Request(
        base.rstrip("/") + "/api/generate", data=json.dumps({**payload, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    start, first, last = time.monotonic(), None, {}
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            if not line.strip():
                continue
            last = json.loads(line)
            if first is None and (last.get("response") or last.get("thinking")):
                first = time.monotonic() - start
    return first if first is not None else time.monotonic() - start, last


def make_prompt(tokens, seed):
    """Random-word text. A fresh seed gives a prompt no cache can have seen."""
    rnd = random.Random(seed)
    # Roughly 1.3 tokens per word for these short words including the space.
    words = [rnd.choice(WORDS) for _ in range(int(tokens / 1.3))]
    lines = [" ".join(words[i : i + 14]) for i in range(0, len(words), 14)]
    return f"Document {seed}:\n" + "\n".join(lines)


def unload_all(base):
    for m in call(base, "/api/ps").get("models", []):
        try:
            call(base, "/api/generate", {"model": m["name"], "keep_alive": 0})
        except urllib.error.URLError:
            pass
    for _ in range(40):
        if not call(base, "/api/ps").get("models"):
            return
        time.sleep(0.5)


def tps(count, nanos):
    return count / (nanos / 1e9) if nanos else 0.0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model")
    p.add_argument("--url", default="http://localhost:11434")
    p.add_argument("--ctx", type=int, nargs="+", required=True, help="context sizes to test")
    p.add_argument("--batch", type=int, nargs="+", default=[0], help="num_batch values; 0 = the model's own setting")
    p.add_argument("--prompt-tokens", type=int, default=6000, help="approximate prompt length")
    p.add_argument("--predict", type=int, default=120, help="tokens to generate")
    p.add_argument("--option", action="append", default=[], metavar="NAME=VALUE", help="extra Ollama option for every run, e.g. --option use_mmap=false (repeatable)")
    p.add_argument("--repeat", type=int, default=1, help="run each configuration this many times; speeds vary between runs when memory is tight")
    p.add_argument("--json", help="also write the raw results to this file")
    p.add_argument("--keep-loaded", action="store_true", help="leave the last configuration loaded")
    a = p.parse_args()

    try:
        info = call(a.url, "/api/show", {"model": a.model})
    except urllib.error.HTTPError as e:
        sys.exit(f"model '{a.model}' not found ({e.code})")
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach Ollama at {a.url}: {e.reason}")
    thinking = "thinking" in (info.get("capabilities") or [])

    extra = {}
    for item in a.option:
        name, _, value = item.partition("=")
        try:
            extra[name.strip()] = json.loads(value)
        except ValueError:
            extra[name.strip()] = value

    results = []
    print(f"{a.model}: prompt of about {a.prompt_tokens} tokens, {a.predict} generated")
    print(f"{'ctx':>7} {'batch':>6} {'load':>7} {'gpu':>5} {'mem':>8} {'read':>9} {'write':>9} {'warm':>7}")
    for ctx in a.ctx:
        if a.prompt_tokens + a.predict + 300 > ctx:
            print(f"{ctx:>7}  skipped: the prompt does not fit")
            continue
        for batch in [b for b in a.batch for _ in range(max(a.repeat, 1))]:
            unload_all(a.url)
            seed = random.randrange(10**9)
            prompt = make_prompt(a.prompt_tokens, seed)
            options = {**extra, "num_ctx": ctx, "num_predict": a.predict, "temperature": 0, "seed": 1}
            if batch:
                options["num_batch"] = batch
            base = {"model": a.model, "options": options, "keep_alive": "10m"}
            if thinking:
                base["think"] = False
            question = "\n\nCount how often the word 'river' appears in the first line and describe the document in two sentences."
            try:
                cold = call(a.url, "/api/generate", {**base, "prompt": prompt + question, "stream": False})
                ps = next((m for m in call(a.url, "/api/ps").get("models", [])), {})
                # Same document, different question: only the tail has to be processed.
                warm, _ = stream_first_token(a.url, {**base, "prompt": prompt + "\n\nList three words that occur in the document."})
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:160]
                print(f"{ctx:>7} {batch or '-':>6}  failed: HTTP {e.code} {detail}")
                continue
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"{ctx:>7} {batch or '-':>6}  failed: {e}")
                continue
            size, vram = ps.get("size", 0), ps.get("size_vram", 0)
            row = {
                "ctx": ctx,
                "batch": batch,
                "load_s": cold.get("load_duration", 0) / 1e9,
                "gpu_share": vram / size if size else 0,
                "mem_gb": size / 1024**3,
                "vram_gb": vram / 1024**3,
                "prompt_tokens": cold.get("prompt_eval_count", 0),
                "read_tps": tps(cold.get("prompt_eval_count", 0), cold.get("prompt_eval_duration", 0)),
                "write_tps": tps(cold.get("eval_count", 0), cold.get("eval_duration", 0)),
                "warm_first_token_s": warm,
            }
            results.append(row)
            print(
                f"{ctx:>7} {batch or '-':>6} {row['load_s']:>6.1f}s {row['gpu_share']:>4.0%} {row['mem_gb']:>6.1f}GB "
                f"{row['read_tps']:>6.0f}t/s {row['write_tps']:>6.1f}t/s {row['warm_first_token_s']:>6.1f}s",
                flush=True,
            )
    if not a.keep_loaded:
        unload_all(a.url)
    if results:
        best = max(results, key=lambda r: r["read_tps"])
        n = results[0]["prompt_tokens"] or a.prompt_tokens
        print(f"\nFastest prompt processing: ctx {best['ctx']}" + (f", batch {best['batch']}" if best["batch"] else "") + f" at {best['read_tps']:.0f} tokens/s.")
        print("Seconds of waiting before the first word when the whole context must be re-read:")
        for r in results:
            full = r["ctx"] * 0.8 / r["read_tps"] if r["read_tps"] else float("inf")
            print(f"  ctx {r['ctx']:>7}{', batch ' + str(r['batch']) if r['batch'] else ''}: a full context (80%) takes {full / 60:5.1f} min; this {n}-token prompt took {n / r['read_tps']:.0f} s")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"model": a.model, "results": results}, f, indent=1)


if __name__ == "__main__":
    main()
