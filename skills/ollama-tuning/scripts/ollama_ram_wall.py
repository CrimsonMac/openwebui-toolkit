#!/usr/bin/env python3
"""A memory wall for Ollama: a fixed amount of RAM that Ollama can never go past, sized so
that Ollama never needs to. The rest of the RAM always stays with the rest of the PC.

    python ollama_ram_wall.py                         # show the wall and whether it holds
    python ollama_ram_wall.py --measure MODEL         # load MODEL and measure what it needs
    python ollama_ram_wall.py --plan --keep-free-mb 9000 --model-mb 17500
                                                      # print the settings for a wall (applies nothing)

How it works. The kernel enforces the wall (systemd MemoryMax on ollama.service, with swap
off for Ollama so model weights are never pushed into swap). Nothing is unloaded and nothing
is killed as long as Ollama's own appetite is smaller than the wall, and that appetite is
fixed by settings: the loaded model (constant after loading) + the prompt cache
(LLAMA_ARG_CACHE_RAM) + context checkpoints (LLAMA_ARG_CTX_CHECKPOINTS). --plan sizes those
so the total stays below the wall. Reading needs no root; applying the plan does.
Standard library only. Linux with systemd and cgroup v2.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

MB = 1024 * 1024


def mem_total_mb(path="/proc/meminfo"):
    with open(path) as f:
        for line in f:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    raise RuntimeError("MemTotal not found in " + path)


def systemctl_show(unit, prop):
    try:
        out = subprocess.run(["systemctl", "show", unit, "-p", prop, "--value"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def cgroup_dir(unit):
    group = systemctl_show(unit, "ControlGroup") or f"/system.slice/{unit}"
    return "/sys/fs/cgroup" + group


def read_int(path):
    """A cgroup value in MB. None = no limit ('max') or not readable."""
    try:
        with open(path) as f:
            text = f.read().strip()
    except OSError:
        return None
    return None if text == "max" or not text.isdigit() else int(text) // MB


def read_table(path):
    table = {}
    try:
        with open(path) as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2 and parts[1].isdigit():
                    table[parts[0]] = int(parts[1])
    except OSError:
        pass
    return table


def read_wall(cgroup, env):
    """Everything known about the wall, in MB."""
    stat = read_table(os.path.join(cgroup, "memory.stat"))
    events = read_table(os.path.join(cgroup, "memory.events"))

    def setting(name, default):
        found = re.search(name + r"=(\d+)", env or "")
        return int(found.group(1)) if found else default

    swap = None
    try:
        with open(os.path.join(cgroup, "memory.swap.max")) as f:
            swap = f.read().strip()
    except OSError:
        pass
    return {
        "wall": read_int(os.path.join(cgroup, "memory.max")),
        "swap_off": swap == "0",
        "now": read_int(os.path.join(cgroup, "memory.current")),
        "peak": read_int(os.path.join(cgroup, "memory.peak")),
        # What cannot be given back: the model and its caches. File cache can, so it does not count.
        "held": (stat.get("anon", 0) + stat.get("shmem", 0)) // MB,
        "file": max(stat.get("file", 0) - stat.get("shmem", 0), 0) // MB,
        "hit": events.get("max", 0),
        "killed": events.get("oom_kill", 0),
        # llama.cpp defaults when the variables are not set.
        "cache": setting("LLAMA_ARG_CACHE_RAM", 8192),
        "checkpoints": setting("LLAMA_ARG_CTX_CHECKPOINTS", 32),
    }


def worst_case(model_mb, cache_mb, checkpoints, checkpoint_mb, spare_mb):
    return model_mb + cache_mb + checkpoints * checkpoint_mb + spare_mb


def plan(total_mb, keep_free_mb, model_mb, checkpoints, checkpoint_mb, spare_mb, max_cache_mb=4096):
    """Settings for a wall that leaves keep_free_mb to the PC. Returns (settings, problem)."""
    wall = total_mb - keep_free_mb
    room = wall - model_mb - checkpoints * checkpoint_mb - spare_mb
    if room < 0:
        # Give up checkpoints before giving up.
        checkpoints = max(int((wall - model_mb - spare_mb) // checkpoint_mb), 0) if wall - model_mb - spare_mb > 0 else 0
        room = wall - model_mb - checkpoints * checkpoint_mb - spare_mb
    if room < 0:
        short = -room
        return None, (
            f"The model alone needs {model_mb} MB plus {spare_mb} MB spare, which is {short} MB more than a wall of {wall} MB allows. "
            f"Keep at most {total_mb - model_mb - spare_mb} MB free, or use a smaller model or quantization."
        )
    return {"wall": wall, "cache": min(int(room), max_cache_mb), "checkpoints": checkpoints}, ""


def drop_in(settings):
    return (
        "[Service]\n"
        f"MemoryMax={settings['wall']}M\n"
        "MemorySwapMax=0\n"
        f"Environment=\"LLAMA_ARG_CACHE_RAM={settings['cache']}\"\n"
        f"Environment=\"LLAMA_ARG_CTX_CHECKPOINTS={settings['checkpoints']}\"\n"
    )


def report(w, total_mb, model_mb, checkpoint_mb, spare_mb):
    """Human-readable status. Returns (text, ok)."""
    lines = ["Ollama memory wall", f"  RAM in this machine      {total_mb} MB"]
    ok = True
    if w["wall"] is None:
        lines.append("  Wall (MemoryMax)         NOT SET: Ollama may take all RAM")
        ok = False
    else:
        lines.append(f"  Wall (MemoryMax)         {w['wall']} MB, so at least {total_mb - w['wall']} MB always stay with the rest of the PC")
    if w["swap_off"]:
        lines.append("  Swap for Ollama          off (model weights are never pushed into swap)")
    else:
        lines.append("  Swap for Ollama          ALLOWED: weights can be swapped, which stalls the PC. Set MemorySwapMax=0")
        ok = False
    if w["now"] is not None:
        lines.append(f"  In use now               {w['now']} MB ({w['held']} MB model and caches, {w['file']} MB file cache that is given back on demand)")
    if w["peak"] is not None and w["wall"] is not None:
        lines.append(f"  Highest since start      {w['peak']} MB ({w['wall'] - w['peak']} MB below the wall)")
    lines.append(f"  Wall reached             {w['hit']} times, processes killed at it: {w['killed']}")
    lines.append(f"  Prompt cache limit       {w['cache']} MB, context checkpoints {w['checkpoints']}")
    if w["killed"]:
        ok = False
    if model_mb and w["wall"] is not None:
        need = worst_case(model_mb, w["cache"], w["checkpoints"], checkpoint_mb, spare_mb)
        lines.append(
            f"  Most Ollama can ask for  {need} MB = model {model_mb} + prompt cache {w['cache']} + "
            f"checkpoints {w['checkpoints']} x {checkpoint_mb} + spare {spare_mb}"
        )
        if need <= w["wall"]:
            lines.append(f"Result: the wall holds. Ollama stays {w['wall'] - need} MB below it even in the worst case, so nothing is ever killed or unloaded.")
        else:
            lines.append(f"Result: NOT SAFE. Ollama can ask for {need - w['wall']} MB more than the wall allows and would be killed there. Run --plan.")
            ok = False
    elif ok:
        lines.append("Result: the wall is in place. Add --model-mb (from --measure) to check that Ollama always stays below it.")
    else:
        lines.append("Result: the wall is not complete. Run --plan to get the settings.")
    return "\n".join(lines), ok


def measure(host, model, cgroup, wait=3.0):
    """Load a model with an empty prompt and return what it holds in MB."""
    body = json.dumps({"model": model, "prompt": "", "stream": False}).encode()
    req = urllib.request.Request(host.rstrip("/") + "/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        r.read()
    time.sleep(wait)
    stat = read_table(os.path.join(cgroup, "memory.stat"))
    return (stat.get("anon", 0) + stat.get("shmem", 0)) // MB


def main(argv=None):
    ap = argparse.ArgumentParser(description="Show, check or plan a hard RAM limit for Ollama that never kills it.")
    ap.add_argument("--unit", default="ollama.service", help="systemd unit of Ollama")
    ap.add_argument("--model-mb", type=int, default=0, help="RAM the loaded model holds, in MB (get it with --measure)")
    ap.add_argument("--checkpoint-mb", type=int, default=64, help="Size of one context checkpoint in MB (see 'created context checkpoint' in the log)")
    ap.add_argument("--spare-mb", type=int, default=768, help="Extra room for buffers, in MB")
    ap.add_argument("--measure", metavar="MODEL", help="Load this model and print what it holds")
    ap.add_argument("--host", default="http://127.0.0.1:11434", help="Ollama address, for --measure")
    ap.add_argument("--plan", action="store_true", help="Print the settings for a wall; changes nothing")
    ap.add_argument("--keep-free-mb", type=int, default=0, help="With --plan: RAM that must always stay with the rest of the PC")
    ap.add_argument("--checkpoints", type=int, default=8, help="With --plan: context checkpoints to allow")
    ap.add_argument("--cgroup", default="", help=argparse.SUPPRESS)
    ap.add_argument("--meminfo", default="/proc/meminfo", help=argparse.SUPPRESS)
    ap.add_argument("--env", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    cgroup = args.cgroup or cgroup_dir(args.unit)
    total = mem_total_mb(args.meminfo)

    if args.measure:
        held = measure(args.host, args.measure, cgroup)
        print(f"{args.measure} holds {held} MB after loading. Use: --model-mb {held}")
        return 0

    if args.plan:
        if not args.model_mb or not args.keep_free_mb:
            print("--plan needs --keep-free-mb and --model-mb (get the second with --measure MODEL).")
            return 2
        settings, problem = plan(total, args.keep_free_mb, args.model_mb, args.checkpoints, args.checkpoint_mb, args.spare_mb)
        if problem:
            print(problem)
            return 1
        need = worst_case(args.model_mb, settings["cache"], settings["checkpoints"], args.checkpoint_mb, args.spare_mb)
        print(f"Wall at {settings['wall']} MB: {total - settings['wall']} MB always stay free of Ollama. Most Ollama can ask for: {need} MB.")
        print("Put this in /etc/systemd/system/ollama.service.d/zz-memory-wall.conf (needs root), then")
        print("run: sudo systemctl daemon-reload && sudo systemctl restart ollama\n")
        print(drop_in(settings))
        return 0

    env = args.env if args.env is not None else systemctl_show(args.unit, "Environment")
    text, ok = report(read_wall(cgroup, env), total, args.model_mb, args.checkpoint_mb, args.spare_mb)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
