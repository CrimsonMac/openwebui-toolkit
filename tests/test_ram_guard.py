"""Tests for skills/ollama-tuning/scripts/ollama_ram_guard.py against a fake Ollama. Run: python tests/test_ram_guard.py"""

import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "skills" / "ollama-tuning" / "scripts" / "ollama_ram_guard.py")
loaded = ["big:latest", "small:latest"]
unloads = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"models": [{"name": n} for n in loaded]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        unloads.append(body)
        if body["model"] in loaded:
            loaded.remove(body["model"])
        self._send({"done": True})


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
HOST = f"http://127.0.0.1:{server.server_port}"


def guard(available_kb, *extra):
    with tempfile.NamedTemporaryFile("w", suffix=".meminfo", delete=False) as f:
        f.write(f"MemTotal:       31936000 kB\nMemFree:          100000 kB\nMemAvailable:   {available_kb} kB\n")
    return subprocess.run([sys.executable, SCRIPT, "--once", "--host", HOST, "--meminfo", f.name, *extra], capture_output=True, text=True)


def test_leaves_models_alone_when_memory_is_fine():
    res = guard(8 * 1024 * 1024)
    assert res.returncode == 0 and not unloads and len(loaded) == 2


def test_unloads_everything_below_the_reserve():
    res = guard(1500 * 1024)
    assert res.returncode == 1, res.stderr
    assert [u["model"] for u in unloads] == ["big:latest", "small:latest"] and all(u["keep_alive"] == 0 for u in unloads)
    assert "1500 MB available, below the 2048 MB reserve: unloaded big:latest, small:latest" in res.stdout
    assert not loaded
    # Nothing loaded any more: low memory is then someone else's doing, and nothing is reported as unloaded.
    assert guard(1500 * 1024).returncode == 0


def test_reserve_is_adjustable_and_dead_server_is_survived():
    loaded.append("big:latest")
    unloads.clear()
    assert guard(3000 * 1024).returncode == 0 and not unloads
    assert guard(3000 * 1024, "--reserve-mb", "4000").returncode == 1 and unloads
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write("MemAvailable:   1000 kB\n")
    res = subprocess.run([sys.executable, SCRIPT, "--once", "--host", "http://127.0.0.1:1", "--meminfo", f.name], capture_output=True, text=True)
    assert res.returncode == 0 and "cannot be reached" in res.stdout


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                import traceback

                traceback.print_exc()
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
