"""Tests for the security tools and the knowledge uploader. Run: python tests/test_security.py

The CVE lookup and the uploader run against a throwaway HTTP server on localhost.
"""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
run = asyncio.run

spec = importlib.util.spec_from_file_location("sec_tools", ROOT / "tools" / "sec_tools.py")
sec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sec)

NVD = {"vulnerabilities": [{"cve": {
    "id": "CVE-2021-44228", "published": "2021-12-10T10:15:09.143", "vulnStatus": "Analyzed",
    "cisaExploitAdd": "2021-12-10", "cisaRequiredAction": "Apply updates.",
    "descriptions": [{"lang": "es", "value": "no"}, {"lang": "en", "value": "Apache Log4j2 JNDI features do not protect against attacker controlled LDAP endpoints."}],
    "metrics": {"cvssMetricV31": [{"cvssData": {"version": "3.1", "baseScore": 10.0, "baseSeverity": "CRITICAL", "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"}}]},
    "weaknesses": [{"description": [{"lang": "en", "value": "CWE-502"}, {"lang": "en", "value": "CWE-20"}]}],
    "references": [{"url": "https://logging.apache.org/log4j/2.x/security.html"}],
}}]}

uploads = {"bases": {}, "files": {}, "added": []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/nvd"):
            return self._send(NVD if "CVE-2021-44228" in self.path else {"vulnerabilities": []})
        if self.path.startswith("/epss"):
            return self._send({"data": [{"cve": "CVE-2021-44228", "epss": "0.944", "percentile": "0.999"}]})
        if self.headers.get("Authorization") != "Bearer test-key":
            return self._send({"detail": "no"}, 401)
        if self.path == "/api/v1/knowledge/":
            return self._send({"items": list(uploads["bases"].values()), "total": len(uploads["bases"])})
        kb = self.path.split("/")[4]
        return self._send(dict(uploads["bases"][kb], files=[{"id": i, "filename": uploads["files"][i]} for k, i in uploads["added"] if k == kb]))

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/api/v1/knowledge/create":
            form = json.loads(body)
            kb = {"id": f"kb{len(uploads['bases']) + 1}", "name": form["name"], "description": form["description"]}
            uploads["bases"][kb["id"]] = kb
            return self._send(kb)
        if self.path.startswith("/api/v1/files/"):
            assert b"multipart/form-data" in self.headers["Content-Type"].encode() and b'name="file"' in body
            name = body.split(b'filename="')[1].split(b'"')[0].decode()
            fid = f"file{len(uploads['files']) + 1}"
            uploads["files"][fid] = name
            return self._send({"id": fid, "filename": name})
        kb = self.path.split("/")[4]
        uploads["added"].append((kb, json.loads(body)["file_id"]))
        return self._send(uploads["bases"][kb])


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}"


def test_cvss_scores_match_the_published_ones():
    T = sec.Tools()
    for vector, score, sev in (
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "9.8", "Critical"),
        ("AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", "10.0", "Critical"),
        ("AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N", "9.1", "Critical"),
        ("AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", "8.8", "High"),
        ("AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", "7.8", "High"),
        ("AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", "6.5", "Medium"),
        ("AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", "6.1", "Medium"),
        ("AV:N/AC:L/PR:L/UI:R/S:C/C:L/I:L/A:N", "5.4", "Medium"),
        ("AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H", "7.5", "High"),
        ("AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N", "5.3", "Medium"),
        ("AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H", "8.1", "High"),
        ("AV:P/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", "0.0", "None"),
    ):
        out = run(T.cvss_score(vector))
        assert out.startswith(f"Base score {score} ({sev})"), (vector, out)
    assert "lacks UI" in run(T.cvss_score("AV:N/AC:L/PR:N/S:U/C:H/I:H/A:H"))
    assert "'X' is not a valid value" in run(T.cvss_score("AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"))


def test_identify_hash():
    T = sec.Tools()
    assert "-m 0 (MD5), 1000 (NTLM)" in run(T.identify_hash("5f4dcc3b5aa765d61d8327deb882cf99"))
    assert "SHA-1" in run(T.identify_hash("5baa61e4c9b93f3f0682250b6cf8331b7ee68fd8"))
    assert "SHA-256" in run(T.identify_hash("5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"))
    assert "-m 3200" in run(T.identify_hash("$2b$12$KIXQJ9C7m0a3Qd1uXkYv3eW1G5yq0Cw8m2o7eQ8n1h2vB3xLr9T7K"))
    assert "-m 1800" in run(T.identify_hash("$6$saltsalt$" + "a" * 86))
    assert "-m 13100" in run(T.identify_hash("$krb5tgs$23$*svc$CORP$http/web*$abcd$1234"))
    assert "-m 5600" in run(T.identify_hash("admin::CORP:1122334455667788:" + "a" * 32 + ":0101000000"))
    assert "Unknown format" in run(T.identify_hash("hello world"))


def test_decode_and_jwt():
    T = sec.Tools()
    out = run(T.decode_text("ZmxhZ3t0ZXN0X2ZsYWd9"))
    assert "Base64 -> flag{test_flag}" in out
    layered = run(T.decode_text("NjY2YzYxNjc3YjZjNjE3OTY1NzI3Mzdk"))  # Base64 of hex of flag{layers}
    assert "Base64 ->" in layered and "hex -> flag{layers}" in layered
    assert "URL-decoding -> a b&c" in run(T.decode_text("a%20b%26c"))
    assert "ROT13 would give: Hello, World" in run(T.decode_text("Uryyb, Jbeyq"))

    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    out = run(T.jwt_decode(token))
    assert '"alg": "HS256"' in out and '"name": "John Doe"' in out and "never expires" in out and "16500" in out
    assert "three dot-separated" in run(T.jwt_decode("abc"))
    assert "JSON Web Token" in run(T.identify_hash(token))


def test_subnet():
    T = sec.Tools()
    out = run(T.subnet_info("10.20.30.77/27"))
    assert "network 10.20.30.64/27" in out and "broadcast 10.20.30.95" in out and "Usable hosts: 30 (10.20.30.65 - 10.20.30.94)" in out and "private" in out
    assert "Usable hosts: 2 (192.0.2.0 - 192.0.2.1)" in run(T.subnet_info("192.0.2.0/31"))
    assert "public" in run(T.subnet_info("8.8.8.8"))
    assert "Prefix /64" in run(T.subnet_info("fd00::1/64"))
    assert run(T.subnet_info("300.1.1.1/24")).startswith("Error")


def test_cve_lookup():
    T = sec.Tools()
    T.valves.nvd_url, T.valves.epss_url = f"{BASE}/nvd", f"{BASE}/epss"
    out = run(T.cve_lookup("what about cve-2021-44228?"))
    assert out.startswith("CVE-2021-44228 (published 2021-12-10")
    assert "Apache Log4j2" in out and "CVSS 3.1: 10.0 CRITICAL" in out and "CWE-20, CWE-502" in out
    assert "on the CISA KEV list since 2021-12-10" in out and "94.40 %" in out and "logging.apache.org" in out
    assert "not in NVD" in run(T.cve_lookup("CVE-1999-0000"))
    assert run(T.cve_lookup("log4shell")).startswith("Error")
    T.valves.nvd_url = "http://127.0.0.1:1/nvd"
    assert run(T.cve_lookup("CVE-2021-44228")).startswith("Error: could not reach NVD")


def test_upload_knowledge():
    script = str(ROOT / "scripts" / "upload_knowledge.py")
    env = dict(os.environ, OPENWEBUI_API_KEY="test-key")
    first = subprocess.run([sys.executable, script, BASE], env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    names = sorted(b["name"] for b in uploads["bases"].values())
    assert names == sorted(p.name for p in (ROOT / "knowledge").iterdir() if p.is_dir())
    on_disk = sorted(p.name for p in (ROOT / "knowledge").glob("*/*.md"))
    assert sorted(uploads["files"].values()) == on_disk and len(uploads["added"]) == len(on_disk)

    again = subprocess.run([sys.executable, script, BASE], env=env, capture_output=True, text=True)
    assert again.returncode == 0 and "added" not in again.stdout and len(uploads["added"]) == len(on_disk), "a second run must not duplicate files"

    bad = subprocess.run([sys.executable, script, BASE, "--key", "wrong"], capture_output=True, text=True)
    assert bad.returncode != 0 and "HTTP 401" in bad.stderr


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
