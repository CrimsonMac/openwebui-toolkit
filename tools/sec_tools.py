"""
title: Security Tools
author: Crimson
version: 1.0.0
description: Helpers for security work that a model should not do from memory - look up a CVE (NVD, EPSS, known-exploited flag), compute a CVSS 3.x score from a vector, identify a hash type, peel encodings off a string, decode a JWT, and work out a subnet.
"""

import asyncio
import base64
import binascii
import ipaddress
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, Field

CVSS = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "CIA": {"H": 0.56, "L": 0.22, "N": 0.0},
    "PR": {"U": {"N": 0.85, "L": 0.62, "H": 0.27}, "C": {"N": 0.85, "L": 0.68, "H": 0.5}},
}

# (pattern, name, hashcat mode, john format)
HASHES = (
    (r"\$2[abxy]\$\d\d\$[./A-Za-z0-9]{53}", "bcrypt", "3200", "bcrypt"),
    (r"\$1\$[^$]{1,8}\$[./A-Za-z0-9]{22}", "md5crypt", "500", "md5crypt"),
    (r"\$5\$(rounds=\d+\$)?[^$]{1,16}\$[./A-Za-z0-9]{43}", "sha256crypt", "7400", "sha256crypt"),
    (r"\$6\$(rounds=\d+\$)?[^$]{1,16}\$[./A-Za-z0-9]{86}", "sha512crypt", "1800", "sha512crypt"),
    (r"\$y\$.+", "yescrypt", "none", "crypt"),
    (r"\$argon2(id|i|d)\$.+", "Argon2", "see hashcat --help", "argon2"),
    (r"\$apr1\$[^$]{1,8}\$[./A-Za-z0-9]{22}", "Apache apr1 MD5", "1600", "md5crypt-long"),
    (r"\$[PH]\$[./A-Za-z0-9]{31}", "phpass (WordPress, phpBB)", "400", "phpass"),
    (r"\$krb5tgs\$23\$.+", "Kerberos 5 TGS-REP etype 23 (Kerberoasting)", "13100", "krb5tgs"),
    (r"\$krb5asrep\$23\$.+", "Kerberos 5 AS-REP etype 23 (AS-REP roasting)", "18200", "krb5asrep"),
    (r"[^:]+::[^:]*:[0-9A-Fa-f]{16}:[0-9A-Fa-f]{32}:[0-9A-Fa-f]+", "NetNTLMv2", "5600", "netntlmv2"),
    (r"[^:]+::[^:]*:[0-9A-Fa-f]{48}:[0-9A-Fa-f]{48}:[0-9A-Fa-f]{16}", "NetNTLMv1", "5500", "netntlm"),
    (r"\{SSHA\}[A-Za-z0-9+/=]{32,}", "LDAP salted SHA-1", "111", "salted-sha1"),
    (r"\*[0-9A-Fa-f]{40}", "MySQL 4.1+", "300", "mysql-sha1"),
    (r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", "JSON Web Token", "16500", "HMAC-SHA256"),
    (r"[0-9A-Fa-f]{32}:[0-9A-Fa-f]{32}", "LM:NT pair from a Windows dump (crack the second half as NTLM)", "1000", "nt"),
    (r"[0-9A-Fa-f]{16}", "MySQL 3.23, or half of an LM hash", "200", "mysql"),
    (r"[0-9A-Fa-f]{32}", "MD5, or NTLM if it came from Windows (also MD4, LM)", "0 (MD5), 1000 (NTLM)", "raw-md5 / nt"),
    (r"[0-9A-Fa-f]{40}", "SHA-1 (also RIPEMD-160)", "100", "raw-sha1"),
    (r"[0-9A-Fa-f]{56}", "SHA-224", "1300", "raw-sha224"),
    (r"[0-9A-Fa-f]{64}", "SHA-256 (also SHA3-256)", "1400", "raw-sha256"),
    (r"[0-9A-Fa-f]{96}", "SHA-384", "10800", "raw-sha384"),
    (r"[0-9A-Fa-f]{128}", "SHA-512 (also Whirlpool)", "1700", "raw-sha512"),
)


def _roundup(x: float) -> float:
    i = round(x * 100000)
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def _severity(score: float) -> str:
    return "None" if score == 0 else "Low" if score < 4 else "Medium" if score < 7 else "High" if score < 9 else "Critical"


def _printable(b: bytes) -> str:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    good = sum(c.isprintable() or c in "\r\n\t" for c in s)
    return s if s and good / len(s) > 0.95 else ""


def _b64(s: str) -> bytes:
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4), validate=True)


class Tools:
    class Valves(BaseModel):
        nvd_url: str = Field("https://services.nvd.nist.gov/rest/json/cves/2.0", description="NVD CVE API address.")
        epss_url: str = Field("https://api.first.org/data/v1/epss", description="EPSS API address. Empty = skip EPSS.")
        nvd_api_key: str = Field("", description="Optional NVD API key for a higher rate limit.")
        timeout: int = Field(20, description="Seconds to wait for a lookup.")

    def __init__(self):
        self.valves = self.Valves()

    def _get(self, url: str, headers: dict = None) -> dict:
        req = urllib.request.Request(url, headers=dict({"User-Agent": "sec-tools/1.0"}, **(headers or {})))
        with urllib.request.urlopen(req, timeout=self.valves.timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    async def cve_lookup(self, cve_id: str) -> str:
        """
        Look up a CVE in the US National Vulnerability Database. Always use this instead of describing a CVE from memory.
        Returns the description, CVSS score and vector, weakness type, EPSS exploit probability,
        whether it is on the CISA known-exploited list, and reference links.

        :param cve_id: The id, for example "CVE-2021-44228".
        :return: The CVE record as text.
        """
        m = re.search(r"CVE-\d{4}-\d{4,}", str(cve_id).upper())
        if not m:
            return 'Error: give an id like "CVE-2021-44228".'
        cid = m.group(0)
        headers = {"apiKey": self.valves.nvd_api_key} if self.valves.nvd_api_key else {}
        try:
            data = await asyncio.to_thread(self._get, f"{self.valves.nvd_url}?cveId={cid}", headers)
        except urllib.error.HTTPError as e:
            return f"Error: NVD answered HTTP {e.code}. If 403 or 429, wait 30 seconds and try once more."
        except Exception as e:
            return f"Error: could not reach NVD ({type(e).__name__}: {e})."
        vulns = data.get("vulnerabilities") or []
        if not vulns:
            return f"{cid} is not in NVD. It may be reserved, rejected or misspelled."
        cve = vulns[0].get("cve", {})
        desc = next((d.get("value", "") for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")
        out = [f"{cid} (published {str(cve.get('published', ''))[:10]}, status {cve.get('vulnStatus', '?')})", desc.strip()]
        metrics = cve.get("metrics", {})
        for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if metrics.get(key):
                d = metrics[key][0].get("cvssData", {})
                sev = d.get("baseSeverity") or metrics[key][0].get("baseSeverity") or ""
                out.append(f"CVSS {d.get('version', '')}: {d.get('baseScore')} {sev} {d.get('vectorString', '')}".rstrip())
                break
        cwes = sorted({d.get("value") for w in cve.get("weaknesses", []) for d in w.get("description", []) if str(d.get("value", "")).startswith("CWE-")})
        if cwes:
            out.append("Weakness: " + ", ".join(cwes))
        if cve.get("cisaExploitAdd"):
            out.append(f"Known exploited: yes, on the CISA KEV list since {cve['cisaExploitAdd']}. Required action: {cve.get('cisaRequiredAction', '?')}")
        else:
            out.append("Known exploited: not on the CISA KEV list.")
        if self.valves.epss_url:
            try:
                e = await asyncio.to_thread(self._get, f"{self.valves.epss_url}?cve={cid}")
                row = (e.get("data") or [{}])[0]
                if row.get("epss"):
                    out.append(
                        f"EPSS: {float(row['epss']) * 100:.2f} % chance of exploitation in the next 30 days "
                        f"(higher than {float(row.get('percentile', 0)) * 100:.0f} % of all CVEs)"
                    )
            except Exception:
                out.append("EPSS: lookup failed.")
        refs = [r.get("url") for r in cve.get("references", []) if r.get("url")]
        if refs:
            out.append("References:\n" + "\n".join(f"- {u}" for u in list(dict.fromkeys(refs))[:8]))
        return "\n".join(out)

    async def cvss_score(self, vector: str) -> str:
        """
        Compute the CVSS 3.0/3.1 base score and severity from a vector string. Use this instead of estimating a score.

        :param vector: For example "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H". The "CVSS:3.1/" prefix is optional.
        :return: Base score, severity, and the impact and exploitability sub-scores.
        """
        parts = dict(p.split(":", 1) for p in str(vector).upper().strip().split("/") if ":" in p and not p.startswith("CVSS"))
        missing = [k for k in ("AV", "AC", "PR", "UI", "S", "C", "I", "A") if k not in parts]
        if missing:
            return f"Error: the vector lacks {', '.join(missing)}. All of AV, AC, PR, UI, S, C, I, A are required."
        try:
            s = parts["S"]
            if s not in ("U", "C"):
                raise KeyError(s)
            av, ac, ui = CVSS["AV"][parts["AV"]], CVSS["AC"][parts["AC"]], CVSS["UI"][parts["UI"]]
            pr = CVSS["PR"][s][parts["PR"]]
            c, i, a = (CVSS["CIA"][parts[k]] for k in ("C", "I", "A"))
        except KeyError as e:
            return f"Error: '{e.args[0]}' is not a valid value in this vector. Example: AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        iss = 1 - (1 - c) * (1 - i) * (1 - a)
        impact = 6.42 * iss if s == "U" else 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
        expl = 8.22 * av * ac * pr * ui
        if impact <= 0:
            score = 0.0
        else:
            score = _roundup(min(impact + expl, 10)) if s == "U" else _roundup(min(1.08 * (impact + expl), 10))
        return f"Base score {score:.1f} ({_severity(score)}). Impact {max(impact, 0):.1f}, exploitability {expl:.1f}."

    async def identify_hash(self, value: str) -> str:
        """
        Say what kind of hash or token a string is, with the hashcat mode and John the Ripper format to use.
        Identification by shape is a guess when several algorithms share a length; the answer lists them.

        :param value: One hash or token, for example "5f4dcc3b5aa765d61d8327deb882cf99".
        :return: Likely types, hashcat mode and john format.
        """
        v = str(value).strip()
        hits = [(n, hc, jn) for pat, n, hc, jn in HASHES if re.fullmatch(pat, v)]
        if not hits:
            return f"Unknown format ({len(v)} characters). It may be salted, truncated, encoded (try decode_text) or not a hash."
        return "\n".join(f"{n}: hashcat -m {hc}, john --format={jn}" for n, hc, jn in hits)

    async def decode_text(self, value: str) -> str:
        """
        Try to decode a string that looks encoded: Base64, Base64url, hex, URL-encoding, Base32, ROT13.
        Layers are peeled one after another, for example Base64 inside URL-encoding.

        :param value: The encoded text.
        :return: Each decoding step that gave readable text.
        """
        cur, steps = str(value).strip(), []
        for _ in range(6):
            nxt = None
            compact = re.sub(r"\s+", "", cur)
            tries = []
            if re.search(r"%[0-9A-Fa-f]{2}", cur):
                tries.append(("URL-decoding", lambda: urllib.parse.unquote(cur)))
            if re.fullmatch(r"(?:0x)?(?:[0-9A-Fa-f]{2})+", compact) and len(compact) >= 8:
                tries.append(("hex", lambda: _printable(binascii.unhexlify(compact[2:] if compact.lower().startswith("0x") else compact))))
            if re.fullmatch(r"[A-Z2-7]+=*", compact) and len(compact) >= 16 and len(compact) % 8 == 0:
                tries.append(("Base32", lambda: _printable(base64.b32decode(compact))))
            if re.fullmatch(r"[A-Za-z0-9+/_-]+=*", compact) and len(compact) >= 8:
                tries.append(("Base64", lambda: _printable(_b64(compact))))
            for name, fn in tries:
                try:
                    out = fn()
                except (ValueError, binascii.Error):
                    out = ""
                if out and out != cur:
                    nxt = (name, out)
                    break
            if not nxt:
                break
            steps.append(f"{nxt[0]} -> {nxt[1][:1500]}")
            cur = nxt[1]
        if not steps:
            rot = cur.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm"))
            return f"No standard encoding decoded to readable text. ROT13 would give: {rot[:500]}"
        return "\n".join(steps)

    async def jwt_decode(self, token: str) -> str:
        """
        Decode the header and payload of a JSON Web Token without checking the signature, and point out weak settings.

        :param token: The JWT, three parts separated by dots.
        :return: Header, payload and notes.
        """
        parts = str(token).strip().split(".")
        if len(parts) != 3:
            return "Error: a JWT has three dot-separated parts."
        try:
            header, payload = (json.loads(_b64(p)) for p in parts[:2])
        except (ValueError, binascii.Error):
            return "Error: header or payload is not Base64url-encoded JSON."
        notes = []
        alg = str(header.get("alg", "")).lower()
        if alg == "none" or not parts[2]:
            notes.append('alg is "none" or the signature is empty: the token is unsigned.')
        if alg.startswith("hs"):
            notes.append("HMAC-signed: the secret can be tested offline (hashcat -m 16500).")
        for k in ("jku", "x5u", "kid", "jwk"):
            if k in header:
                notes.append(f'header has "{k}": check whether the server trusts a value you control.')
        if "exp" not in payload:
            notes.append("no exp claim: the token never expires.")
        text = f"Header: {json.dumps(header)}\nPayload: {json.dumps(payload)}"
        return text + ("\nNotes:\n" + "\n".join(f"- {n}" for n in notes) if notes else "")

    async def subnet_info(self, cidr: str) -> str:
        """
        Work out a network from an address in CIDR form: network, netmask, broadcast, usable range and host count.
        Also says whether an address is private, loopback or link-local.

        :param cidr: For example "10.20.30.77/27" or "fd00::1/64". A bare address is treated as a single host.
        :return: The network details.
        """
        try:
            iface = ipaddress.ip_interface(str(cidr).strip())
        except ValueError as e:
            return f"Error: {e}"
        net, ip = iface.network, iface.ip
        kind = "loopback" if ip.is_loopback else "link-local" if ip.is_link_local else "private" if ip.is_private else "public"
        out = [f"Address {ip} ({kind}), network {net}"]
        if net.version == 4:
            usable = max(net.num_addresses - 2, 0) if net.prefixlen < 31 else net.num_addresses
            first = net.network_address + (1 if net.prefixlen < 31 else 0)
            last = net.broadcast_address - (1 if net.prefixlen < 31 else 0)
            out.append(f"Netmask {net.netmask}, wildcard {net.hostmask}, broadcast {net.broadcast_address}")
            out.append(f"Usable hosts: {usable} ({first} - {last})")
        else:
            out.append(f"Prefix /{net.prefixlen}, {net.num_addresses} addresses, first {net.network_address}, last {net.broadcast_address}")
        return "\n".join(out)
