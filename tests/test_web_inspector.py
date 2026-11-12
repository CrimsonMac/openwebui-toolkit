"""Tests for the Web Inspector tool. Run: python tests/test_web_inspector.py

Everything runs against a throwaway server on localhost: a small site with a login, cookies, redirects,
a section that answers missing pages with status 200, and (when the openssl program is installed) a
second copy behind a self-signed certificate.
"""

import asyncio
import gzip
import importlib.util
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
run = asyncio.run

spec = importlib.util.spec_from_file_location("web_inspector", ROOT / "tools" / "web_inspector.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

HOME = b"""<html><head><title>Shop</title><meta name="generator" content="WordPress 6.4.2">
<script src="/wp-includes/js/jquery/jquery-3.7.1.min.js"></script><script>fetch("/api/v2/items?page=1")</script></head>
<body><!-- TODO remove test account before launch --><h1>Welcome</h1><p>Hello &amp; welcome. Browse our shelves and order what you like today.</p>
<form action="/login" method="post"><input type="hidden" name="csrf" value="tok123"><input name="user"><input type="password" name="pass"></form>
<a href="/about">About</a> <a href="https://cdn.example.org/x">CDN</a></body></html>"""
NGINX_404 = b"<html><head><title>404 Not Found</title></head><body><center><h1>404 Not Found</h1></center><hr><center>nginx/1.24.0</center></body></html>"


class Site(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen: list = []

    def log_message(self, *a):
        pass

    def reply(self, code, body=b"", ctype="text/html; charset=utf-8", headers=()):
        self.send_response_only(code)
        self.send_header("Server", "nginx/1.24.0")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        Site.seen.append((self.command, self.path, dict(self.headers)))
        cookie = self.headers.get("Cookie", "")
        path = self.path.split("?")[0]
        if path == "/":
            self.reply(200, HOME, headers=[("X-Powered-By", "PHP/8.2.1"), ("Set-Cookie", "PHPSESSID=abc; path=/")])
        elif path == "/about":
            self.reply(200, b"<html><title>About us</title><body><p>" + b"We sell things. " * 40 + b"</p></body></html>")
        elif path == "/account":
            if "session=s3cr3t" in cookie:
                self.reply(200, b"<html><title>Account</title><body>Logged in as alice</body></html>")
            else:
                self.reply(302, headers=[("Location", "/login")])
        elif path == "/login":
            self.reply(200, b"<html><title>Log in</title><body><form method=post action=/login><input name=user></form></body></html>")
        elif path == "/echo":
            self.reply(200, ("cookie=" + cookie + "|x=" + self.headers.get("X-Test", "")).encode(), "text/plain")
        elif path == "/gz":
            self.reply(200, gzip.compress(b'{"items": [1, 2, 3]}'), "application/json", [("Content-Encoding", "gzip")])
        elif path == "/admin":
            self.reply(403, b"<html><title>403 Forbidden</title><body>Forbidden</body></html>")
        elif path == "/app.js":
            self.reply(200, b'var a=1;function load(){return fetch("/api/v2/secret-report");}var apiKey="k-12345";' + b"x=1;" * 900, "application/javascript")
        elif path == "/soft/real":
            self.reply(200, b"<html><title>Real page</title><body><h1>Prices</h1><p>" + b"Item list and prices. " * 30 + b"</p></body></html>")
        elif path.startswith("/soft/"):
            # A custom error page with status 200 that repeats the address asked for.
            self.reply(200, ("<html><title>Oops</title><body><h1>Sorry</h1><p>We could not find " + path + " on our site. Try the search or go back to the start page.</p></body></html>").encode())
        elif path.startswith("/catch/"):
            self.reply(302, headers=[("Location", "/")])
        else:
            self.reply(404, NGINX_404)

    do_HEAD = do_GET

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        Site.seen.append(("POST", self.path, dict(self.headers), body))
        if self.path == "/login" and "user=alice" in body and "pass=pw" in body:
            self.reply(303, headers=[("Location", "/account"), ("Set-Cookie", "session=s3cr3t; Path=/; HttpOnly"), ("Set-Cookie", "old=1; Max-Age=0")])
        else:
            self.reply(401, b"bad login", "text/plain", [("WWW-Authenticate", "Form")])


class Quiet(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # clients that reject the certificate hang up; that is expected


def serve(tls_ctx=None):
    server = Quiet(("127.0.0.1", 0), Site)
    if tls_ctx:
        server.socket = tls_ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_port


BASE = f"http://127.0.0.1:{serve()}"
META = {"chat_id": "chat-1"}


def tools():
    T = W.Tools()
    T.valves.allow_private_addresses = True
    T.valves.delay_seconds = 0
    return T


def test_refuses_local_by_default():
    T = W.Tools()
    assert "private or local address" in run(T.http_request(f"{BASE}/"))
    assert "private or local address" in run(T.site_profile(f"{BASE}/"))
    assert "private or local address" in run(T.check_paths(f"{BASE}/", "admin"))
    assert run(T.http_request("file:///etc/passwd")).startswith("Error: only http and https")
    assert run(T.http_request("http://169.254.169.254/latest/meta-data/")).startswith("Error")


def test_request_shows_the_response():
    T = tools()
    out = run(T.http_request(f"{BASE}/", __metadata__=META))
    assert f"GET {BASE}/ -> 200 OK" in out and "no TLS" in out
    assert "X-Powered-By: PHP/8.2.1" in out and "Set-Cookie: PHPSESSID=abc" in out and "Title: Shop" in out
    assert "# Welcome" in out and "Hello & welcome." in out and "fetch(" not in out
    raw = run(T.http_request(f"{BASE}/", show="raw", __metadata__=META))
    assert "TODO remove test account" in raw and 'fetch("/api/v2/items' in raw
    assert "Body" not in run(T.http_request(f"{BASE}/", show="headers", __metadata__=META))
    assert "Body: empty" in run(T.http_request(f"{BASE}/", method="HEAD", __metadata__=META))
    out = run(T.http_request(f"{BASE}/gz", __metadata__=META))
    assert '"items": [' in out, "gzip is unpacked and JSON is laid out"
    out = run(T.http_request(f"{BASE}/nothing-here", __metadata__=META))
    assert "-> 404 Not Found" in out and "default page of nginx" in out
    out = run(T.http_request(f"{BASE}/admin", __metadata__=META))
    assert "-> 403" in out and "403 has two readings" in out
    out = run(T.http_request(f"{BASE}/soft/missing-thing", __metadata__=META))
    assert "-> 200" in out and "soft 404" in out
    assert "switched off" in run(T.http_request(f"{BASE}/", method="DELETE", __metadata__=META))
    assert "connection refused" in run(T.http_request("http://127.0.0.1:1/", __metadata__=META))


def test_headers_cookies_and_login():
    T = tools()
    meta = {"chat_id": "chat-login"}
    out = run(T.http_request(f"{BASE}/echo", headers="X-Test: hello\nUser-Agent: probe/1", cookies="a=1; b=2", __metadata__=meta))
    assert "cookie=a=1; b=2|x=hello" in out and "Cookies sent: a, b" in out
    assert Site.seen[-1][2]["User-Agent"] == "probe/1"
    assert "x=json" in run(T.http_request(f"{BASE}/echo", headers='{"X-Test": "json"}', __metadata__=meta))

    out = run(T.http_request(f"{BASE}/account", __metadata__=meta))
    assert "Title: Log in" in out and "ended on a login page" in out and f"{BASE}/account [302]" in out
    out = run(T.http_request(f"{BASE}/account", follow_redirects=False, __metadata__=meta))
    assert "-> 302" in out and "Location: /login" in out

    assert "-> 401" in run(T.http_request(f"{BASE}/login", "POST", body="user=alice&pass=wrong", __metadata__=meta))
    out = run(T.http_request(f"{BASE}/login", "POST", body="user=alice&pass=pw", __metadata__=meta))
    assert Site.seen[-2][2]["Content-Type"] == "application/x-www-form-urlencoded"
    assert "Logged in as alice" in out and "[303]" in out, "the POST turns into a GET after 303 and the new cookie is sent"
    assert "Logged in as alice" in run(T.http_request(f"{BASE}/account", __metadata__=meta)), "the session is kept for the chat"
    jar = run(T.cookie_jar(__metadata__=meta))
    assert "session=s3cr3t" in jar and "old=" not in jar
    assert "Log in" in run(T.http_request(f"{BASE}/account", __metadata__={"chat_id": "someone-else"})), "another chat has its own cookies"
    assert "Deleted" in run(T.cookie_jar(clear=True, __metadata__=meta))
    assert "Title: Log in" in run(T.http_request(f"{BASE}/account", __metadata__=meta))
    run(T.http_request(f"{BASE}/login", "POST", body='{"user": "x"}', __metadata__=meta))
    assert Site.seen[-1][2]["Content-Type"] == "application/json"


def test_site_profile():
    T = tools()
    out = run(T.site_profile(f"{BASE}/", __metadata__={"chat_id": "p"}))
    assert '- WordPress 6.4.2 [PHP CMS] - likely, two kinds of evidence agree: generator meta tag "WordPress 6.4.2"' in out, out
    assert "- nginx 1.24.0 [web server] - likely, two kinds of evidence agree" in out, out
    assert "- PHP 8.2.1 [language] - likely, two kinds of evidence agree" in out
    assert "- jQuery 3.7.1" in out and "Python" not in out and "built by JavaScript" not in out
    assert "TLS: none" in out and "Content-Security-Policy" in out
    assert "returns 404 Not Found with the default page of nginx" in out and "Status codes can be trusted" in out
    assert "robots.txt:\n- none" in out
    out = run(T.site_profile(f"{BASE}/soft/real", __metadata__={"chat_id": "p"}))
    assert "Technology:" in out


def test_check_paths_sees_through_custom_error_pages():
    T = tools()
    out = run(T.check_paths(f"{BASE}/", "about, admin, nope, account, /about", __metadata__={"chat_id": "c1"}))
    assert "answers a path that cannot exist: 404" in out
    assert 'about: 200' in out and 'EXISTS, title "About us"' in out
    assert "admin: 403" in out and "EXISTS but access is denied" in out
    assert "nope: 404" in out and "not found" in out
    assert "account: 302" in out and "needs login" in out

    out = run(T.check_paths(f"{BASE}/soft/", "real\nghost\nimages/logo.png", __metadata__={"chat_id": "c2"}))
    assert "This is not a 404" in out
    assert "real: 200" in out and 'EXISTS, title "Real page"' in out
    assert out.count("soft 404") == 2, out

    out = run(T.check_paths(f"{BASE}/catch/", "one, two", __metadata__={"chat_id": "c3"}))
    assert out.count("soft 404") == 2 and "redirect to /" in out, out
    T.valves.max_paths = 1
    assert "1 paths were not tried" in run(T.check_paths(f"{BASE}/", "about, admin", __metadata__={"chat_id": "c4"}))


def test_find_in_page_and_structure():
    T = tools()
    out = run(T.find_in_page(f"{BASE}/app.js", r"api/v\d|apikey"))
    assert '>>api/v2<<' in out and '>>apiKey<<' in out and "2 matching lines" in out, out
    assert "No match" in run(T.find_in_page(f"{BASE}/app.js", "nothing-like-this"))
    assert "searched as plain text" in run(T.find_in_page(f"{BASE}/", "welcome("))
    out = run(T.find_in_page(f"{BASE}/gone.js", "x"))
    assert "error page" in out

    out = run(T.page_structure(f"{BASE}/"))
    assert f"- POST {BASE}/login" in out and 'csrf [hidden] = "tok123"' in out and "pass [password]" in out
    assert "jquery-3.7.1.min.js" in out and "plus 1 inline scripts" in out
    assert "/api/v2/items?page=1" in out and "TODO remove test account" in out
    assert "generator=WordPress 6.4.2" in out and "cdn.example.org (1)" in out and "/about" in out


def test_tls():
    if not shutil.which("openssl"):
        print("      (openssl not installed, TLS test skipped)")
        return
    tmp = tempfile.mkdtemp(prefix="wi_tls_")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{tmp}/k.pem", "-out", f"{tmp}/c.pem", "-days", "5",
         "-subj", "/CN=lab.internal/O=Test Lab", "-addext", "subjectAltName=DNS:lab.internal,DNS:admin.lab.internal"],
        check=True, capture_output=True,
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(f"{tmp}/c.pem", f"{tmp}/k.pem")
    port = serve(ctx)
    shutil.rmtree(tmp)
    T = tools()
    out = run(T.http_request(f"https://127.0.0.1:{port}/about", __metadata__={"chat_id": "t"}))
    assert "-> 200 OK" in out and "TLSv1" in out and "About us" in out
    assert "certificate did NOT verify" in out
    out = run(T.tls_certificate("127.0.0.1", port))
    assert "Verification: FAILED" in out and "commonName=lab.internal" in out and "self-signed" in out
    assert "admin.lab.internal" in out and "days left" in out and "SHA-256 fingerprint" in out
    out = run(T.site_profile(f"https://127.0.0.1:{port}/", __metadata__={"chat_id": "t"}))
    assert "TLS:\n- Connection: TLSv1" in out and "Strict-Transport-Security" in out
    T.valves.continue_on_bad_certificate = False
    W._BAD_CERT.clear()
    assert "did not verify" in run(T.http_request(f"https://127.0.0.1:{port}/about", __metadata__={"chat_id": "t"}))
    assert "TLS handshake failed" in run(T.http_request(f"https://127.0.0.1:{BASE.rsplit(':', 1)[1]}/", __metadata__={"chat_id": "t"}))


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
