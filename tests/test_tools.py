"""Tests for the tools that work offline. Run: python tests/test_tools.py

Network-facing tools are tested against a throwaway HTTP server on localhost.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
run = asyncio.run

env = types.ModuleType("open_webui.env")
env.DATA_DIR = tempfile.mkdtemp(prefix="tools_test_")
sys.modules.setdefault("open_webui", types.ModuleType("open_webui"))
sys.modules["open_webui.env"] = env


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PAGE = b"""<html><head><title>Test  Page</title><style>.x{}</style></head><body>
<nav><a href="/nav">Nav link</a></nav>
<h1>Heading</h1><p>First &amp; second.</p><script>alert(1)</script>
<ul><li>one</li><li>two</li></ul><a href="/docs/pricing">Pricing info</a> <a href="#top">top</a>
<p>""" + b"word " * 3000 + b"""</p></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/page":
            self._send(PAGE, "text/html; charset=utf-8")
        elif self.path == "/redirect-out":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/secret")
            self.end_headers()
        elif self.path == "/img":
            self._send(b"\x89PNG", "image/png")
        elif self.path == "/api/tags":
            self._send(json.dumps({"models": [{"name": "small:1b", "size": 1024**3, "details": {"parameter_size": "1B", "quantization_level": "Q4_K_M", "family": "x"}}, {"name": "big:30b", "size": 20 * 1024**3, "details": {}}]}).encode())
        elif self.path == "/api/version":
            self._send(b'{"version": "9.9.9"}')
        elif self.path == "/api/ps":
            self._send(json.dumps({"models": [{"name": "big:30b", "size": 24 * 1024**3, "size_vram": 12 * 1024**3, "context_length": 8192}]}).encode())
        else:
            self._send(b'{"error": "nope"}', code=404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show" and body.get("model") == "big:30b":
            self._send(json.dumps({"details": {"parameter_size": "30B", "quantization_level": "Q4_K_M"}, "model_info": {"general.architecture": "x", "x.context_length": 131072, "x.block_count": 64}, "parameters": "num_ctx    8192\ntemperature 0.7", "capabilities": ["completion", "tools"]}).encode())
        elif self.path == "/api/generate":
            Handler.unloaded = body
            self._send(b"{}")
        else:
            self._send(b'{"error": "model not found"}', code=404)


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}"


def test_text_utils():
    T = load("text_utils").Tools()
    out = run(T.count_text("strawberry", "r"))
    assert "characters: 10" in out and "occurs 3 time(s)" in out, out
    out = run(T.count_text("One two. Three four five!\n\nNew para?"))
    assert "words: 7" in out and "sentences: 3" in out and "paragraphs: 2" in out and "lines: 3" in out, out
    assert run(T.word_frequency("the cat and the dog and the bird", top=1)).endswith("3  the")
    assert run(T.compare_texts("a", "a")) == "The texts are identical."
    assert "'cat' → 'dog'" in run(T.compare_texts("the cat sat", "the dog sat"))
    d = run(T.compare_texts("a\nb\nc", "a\nx\nc"))
    assert "-b" in d and "+x" in d and "1 line(s) added, 1 removed" in d
    assert run(T.transform_lines("b\nA\nc", "sort")) == "A\nb\nc"
    assert run(T.transform_lines("x 10\nx 9\nx 100", "sort_numeric")) == "x 9\nx 10\nx 100"
    assert run(T.transform_lines("a\nb\na", "unique")) == "a\nb"
    assert run(T.transform_lines("a\nb\na", "duplicates")) == "2× a"
    assert run(T.transform_lines("a", "explode")).startswith("Error")
    out = run(T.regex_find(r"(\d{4})-(\d{2})", "2024-05 and 2025-11"))
    assert "groups=('2024', '05')" in out and out.count("\n") == 1
    assert run(T.regex_find("(", "x")).startswith("Error: invalid pattern")
    assert run(T.encode_decode("hello", "base64_encode")) == "aGVsbG8="
    assert run(T.encode_decode("aGVsbG8", "base64_decode")) == "hello"
    assert run(T.encode_decode("hello", "sha256")).startswith("2cf24dba5fb0a30e")
    assert run(T.encode_decode("Crème Brûlée!", "slug")) == "creme-brulee"
    assert run(T.encode_decode("a b&c", "url_encode")) == "a%20b%26c"
    assert run(T.encode_decode("x", "nope")).startswith("Error")
    assert run(T.check_json('{"a": [1, 2]}')).startswith("Valid JSON (object with 1 keys)")
    assert "Invalid JSON at line 1, column" in run(T.check_json('{"a": 1,}'))


def test_notes():
    T = load("notes").Tools()
    u1, u2 = {"id": "user-1"}, {"id": "../../evil"}
    assert run(T.search_notes("x", __user__=u1)) == "The notebook is empty."
    assert run(T.save_note("Server", "Runs Debian, backups at 03:00", "infra, backup", __user__=u1)) == "Saved note #1 'Server'."
    assert run(T.save_note("Coffee", "Prefers flat white", __user__=u1)).startswith("Saved note #2")
    assert run(T.save_note("server", "Runs Arch now", __user__=u1)) == "Updated note #1 'Server'."
    out = run(T.search_notes("server backup", __user__=u1))
    assert out.startswith("#1 Server [infra, backup]") and "Runs Arch now" in out
    assert "Titles in the notebook" in run(T.search_notes("zebra", __user__=u1))
    assert "2 note(s)" in run(T.list_notes(__user__=u1))
    assert "1 note(s)" in run(T.list_notes("infra", __user__=u1))
    assert "flat white" in run(T.read_note(2, __user__=u1))
    assert run(T.list_notes(__user__=u2)) == "No notes found.", "users must not see each other's notes"
    run(T.save_note("x", "y", __user__=u2))
    assert Path(T._path(u2)).parent == Path(env.DATA_DIR) / "notes_tool", "user id must not escape the folder"
    assert run(T.delete_note(1, __user__=u1)) == "Deleted note #1 'Server'."
    assert run(T.delete_note(1, __user__=u1)).startswith("Error")
    assert run(T.save_note("", "x", __user__=u1)).startswith("Error")
    assert run(T.save_note("long", "x" * 5000, __user__=u1)).startswith("Error: note too long")


def test_web_reader():
    W = load("web_reader")
    T = W.Tools()
    out = run(T.read_webpage(f"{BASE}/page"))
    assert "private or local address" in out, "local addresses are refused by default"
    assert run(T.read_webpage("file:///etc/passwd")).startswith("Error: only http and https")
    assert run(T.read_webpage("http://169.254.169.254/latest/meta-data")).startswith("Error")

    T.valves.allow_private_addresses = True
    out = run(T.read_webpage(f"{BASE}/page"))
    assert "Title: Test Page" in out and "# Heading" in out and "First & second." in out
    assert "- one" in out and "alert(1)" not in out and "Nav link" not in out and ".x{}" not in out
    assert "Call read_webpage again with start=8000" in out
    assert "Characters 8000-" in run(T.read_webpage(f"{BASE}/page", start=8000))
    assert run(T.read_webpage(f"{BASE}/img")).startswith("Error: this address returns image/png")
    assert "HTTP 404" in run(T.read_webpage(f"{BASE}/missing"))
    links = run(T.list_links(f"{BASE}/page", "pricing"))
    assert links == f"Pricing info - {BASE}/docs/pricing", links

    # A public-looking page must not be able to redirect into the private network.
    handler = W._Redirects()
    try:
        handler.redirect_request(None, None, 302, "", {}, "http://127.0.0.1:1/secret")
        raise AssertionError("redirect to a local address was allowed")
    except ValueError:
        pass


def test_ollama_status():
    T = load("ollama_status").Tools()
    T.valves.ollama_url = BASE
    out = run(T.list_installed_models())
    assert out.startswith("Ollama 9.9.9, 2 model(s), 21.0 GB") and out.index("big:30b") < out.index("small:1b")
    out = run(T.list_loaded_models())
    assert "24.0 GB total, 12.0 GB in VRAM, 50% GPU / 50% CPU" in out and "context 8192" in out
    out = run(T.show_model_details("big:30b"))
    assert "maximum context length: 131072" in out and "layers: 64" in out and "num_ctx 8192" in out
    assert "model not found" in run(T.show_model_details("ghost"))
    assert "disabled" in run(T.unload_model("big:30b")) and not hasattr(Handler, "unloaded")
    T.valves.allow_unload = True
    run(T.unload_model("big:30b"))
    assert Handler.unloaded == {"model": "big:30b", "keep_alive": 0}
    T.valves.ollama_url = "http://127.0.0.1:1"
    assert "cannot reach Ollama" in run(T.list_loaded_models())


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
