#!/usr/bin/env python3
"""Upload the knowledge/ folder to Open WebUI as knowledge bases, one per subfolder.

    export OPENWEBUI_API_KEY=sk-...          # Settings -> Account -> API keys
    python scripts/upload_knowledge.py http://localhost:3000
    python scripts/upload_knowledge.py http://localhost:3000 --only security --prefix "Ref: "

Run it again after pulling new files: files already in a knowledge base (same name) are skipped.
Needs only the Python standard library.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DESCRIPTIONS = {
    "security": "Reference sheets for authorized security testing: ports, nmap, web flaws, privilege escalation, Active Directory, hash cracking, CVSS.",
    "reference": "General technical reference sheets.",
}


def call(base, key, method, path, body=None, files=None, timeout=300):
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    data = None
    if files:
        boundary = uuid.uuid4().hex
        parts = []
        for field, (name, content) in files.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
                "Content-Type: text/markdown\r\n\r\n".encode() + content + b"\r\n"
            )
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} failed: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {base}: {e.reason}")


def as_list(value):
    """List endpoints return a plain list on older versions and {"items": [...]} on newer ones."""
    if isinstance(value, dict):
        value = value.get("items") or value.get("files") or []
    return value if isinstance(value, list) else []


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url", help="Address of Open WebUI, for example http://localhost:3000")
    ap.add_argument("--key", default=os.environ.get("OPENWEBUI_API_KEY", ""), help="API key (default: $OPENWEBUI_API_KEY)")
    ap.add_argument("--folder", default=str(Path(__file__).resolve().parent.parent / "knowledge"), help="Folder to upload")
    ap.add_argument("--only", action="append", help="Upload only this subfolder (repeatable)")
    ap.add_argument("--prefix", default="", help="Text put before each knowledge base name")
    args = ap.parse_args()
    if not args.key:
        raise SystemExit("No API key. Set OPENWEBUI_API_KEY or pass --key.")
    root = Path(args.folder)
    groups = sorted(p for p in root.iterdir() if p.is_dir() and (not args.only or p.name in args.only))
    if not groups:
        raise SystemExit(f"No subfolders to upload in {root}")

    existing = {k.get("name"): k for k in as_list(call(args.url, args.key, "GET", "/api/v1/knowledge/"))}
    for group in groups:
        name = f"{args.prefix}{group.name}"
        kb = existing.get(name)
        if kb is None:
            kb = call(args.url, args.key, "POST", "/api/v1/knowledge/create",
                      {"name": name, "description": DESCRIPTIONS.get(group.name, f"Reference files: {group.name}")})
            print(f"created knowledge base '{name}'")
            have = set()
        else:
            detail = call(args.url, args.key, "GET", f"/api/v1/knowledge/{kb['id']}") or {}
            listed = as_list(detail.get("files")) or as_list(call(args.url, args.key, "GET", f"/api/v1/knowledge/{kb['id']}/files"))
            have = {(f.get("filename") or (f.get("meta") or {}).get("name") or "") for f in listed}
        for path in sorted(group.glob("*.md")) + sorted(group.glob("*.txt")):
            if path.name in have:
                print(f"  skip {path.name} (already there)")
                continue
            up = call(args.url, args.key, "POST", "/api/v1/files/?process=true&process_in_background=false",
                      files={"file": (path.name, path.read_bytes())})
            call(args.url, args.key, "POST", f"/api/v1/knowledge/{kb['id']}/file/add", {"file_id": up["id"]})
            print(f"  added {path.name}")
    print("done")


if __name__ == "__main__":
    sys.exit(main())
