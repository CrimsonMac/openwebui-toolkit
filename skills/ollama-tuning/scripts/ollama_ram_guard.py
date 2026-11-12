#!/usr/bin/env python3
"""Keep a reserve of RAM free on a machine that runs Ollama: when available memory falls
below the reserve, unload the loaded models instead of letting the machine swap itself to a halt.

    python ollama_ram_guard.py                      # watch, keep 2048 MB free
    python ollama_ram_guard.py --reserve-mb 3000 --host http://localhost:11434
    python ollama_ram_guard.py --once               # check one time and exit (0 = fine, 1 = unloaded)
    python ollama_ram_guard.py --install            # run it at login as a systemd user service

An unloaded model stops mid-answer; the next message loads it again. That costs a reload,
which is far cheaper than a frozen desktop. Needs no root and only the standard library. Linux only.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

UNIT = """[Unit]
Description=Unload Ollama models when free RAM runs low

[Service]
ExecStart={python} {script} --reserve-mb {reserve} --host {host}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def available_mb(path="/proc/meminfo"):
    with open(path) as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    raise RuntimeError("MemAvailable not found in " + path)


def call(host, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(host.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def unload_all(host):
    """Ask Ollama to drop every loaded model. Returns the names it was asked to drop."""
    names = [m.get("name") or m.get("model") for m in (call(host, "/api/ps") or {}).get("models", [])]
    for name in names:
        try:
            call(host, "/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
        except Exception as e:  # the answer does not matter, only that the request was made
            print(f"unload request for {name} failed: {e}", flush=True)
    return [n for n in names if n]


def check(args):
    """One check. Returns the list of models unloaded (empty if memory is fine)."""
    free = available_mb(args.meminfo)
    if free >= args.reserve_mb:
        return []
    try:
        names = unload_all(args.host)
    except Exception as e:
        print(f"{free} MB available, below the {args.reserve_mb} MB reserve, but Ollama cannot be reached: {e}", flush=True)
        return []
    if names:
        print(f"{free} MB available, below the {args.reserve_mb} MB reserve: unloaded {', '.join(names)}", flush=True)
    return names


def install(args):
    if not shutil.which("systemctl"):
        raise SystemExit("systemctl not found; start the script yourself at login instead.")
    home = os.path.expanduser("~")
    target = os.path.join(home, ".local", "bin", "ollama_ram_guard.py")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.abspath(__file__) != target:
        shutil.copyfile(os.path.abspath(__file__), target)
    unit_dir = os.path.join(home, ".config", "systemd", "user")
    os.makedirs(unit_dir, exist_ok=True)
    with open(os.path.join(unit_dir, "ollama-ram-guard.service"), "w") as f:
        f.write(UNIT.format(python=sys.executable, script=target, reserve=args.reserve_mb, host=args.host))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "ollama-ram-guard.service"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "ollama-ram-guard.service"], check=True)
    print(f"Installed and started. Keeps {args.reserve_mb} MB free. Log: journalctl --user -u ollama-ram-guard")


def main():
    ap = argparse.ArgumentParser(description="Unload Ollama models when free RAM falls below a reserve.")
    ap.add_argument("--reserve-mb", type=int, default=2048, help="RAM to keep available, in MB (default 2048)")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434"), help="Ollama address")
    ap.add_argument("--interval", type=float, default=1.0, help="Seconds between checks (default 1)")
    ap.add_argument("--cooldown", type=float, default=15.0, help="Seconds to wait after an unload before checking again")
    ap.add_argument("--meminfo", default="/proc/meminfo", help=argparse.SUPPRESS)
    ap.add_argument("--once", action="store_true", help="Check one time and exit")
    ap.add_argument("--install", action="store_true", help="Install as a systemd user service and start it")
    args = ap.parse_args()
    if args.install:
        return install(args)
    if args.once:
        return 1 if check(args) else 0
    print(f"watching: unload Ollama models when less than {args.reserve_mb} MB is available", flush=True)
    while True:
        try:
            unloaded = check(args)
        except Exception as e:
            print(f"check failed: {e}", flush=True)
            unloaded = []
        time.sleep(args.cooldown if unloaded else args.interval)


if __name__ == "__main__":
    sys.exit(main())
