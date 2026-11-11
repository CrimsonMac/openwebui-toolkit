# CVSS, severity ratings and related identifiers

## CVSS 3.1 base metrics

A vector looks like `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`.

| Metric | Values | Question it answers |
|---|---|---|
| AV Attack Vector | N network, A adjacent, L local, P physical | From where can it be attacked? |
| AC Attack Complexity | L low, H high | Does it need conditions outside the attacker's control (race, special configuration)? |
| PR Privileges Required | N none, L low, H high | What access must the attacker already have? |
| UI User Interaction | N none, R required | Must a victim do something (click, open)? |
| S Scope | U unchanged, C changed | Does the impact reach beyond the vulnerable component (for example sandbox escape, XSS into the browser)? |
| C Confidentiality | H, L, N | How much data can be read? |
| I Integrity | H, L, N | How much can be changed? |
| A Availability | H, L, N | How much can be taken down? |

## Severity bands

| Score | Rating |
|---|---|
| 0.0 | None |
| 0.1 - 3.9 | Low |
| 4.0 - 6.9 | Medium |
| 7.0 - 8.9 | High |
| 9.0 - 10.0 | Critical |

## Typical vectors

| Finding | Vector | Score |
|---|---|---|
| Unauthenticated remote code execution | AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H | 9.8 |
| The same, breaking out to other components | AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H | 10.0 |
| SQL injection, unauthenticated, data read and change | AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N | 9.1 |
| Remote code execution as a logged-in user | AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H | 8.8 |
| Local privilege escalation to root | AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H | 7.8 |
| IDOR reading other users' data, logged in | AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N | 6.5 |
| Reflected XSS | AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N | 6.1 |
| Stored XSS by a logged-in user | AV:N/AC:L/PR:L/UI:R/S:C/C:L/I:L/A:N | 5.4 |
| Unauthenticated denial of service | AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H | 7.5 |
| Information disclosure of minor data | AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N | 5.3 |

## What CVSS does not say

The base score rates the flaw in general, not the risk in one environment. Combine it with:

- **Reachability**: is the component exposed, the feature enabled?
- **EPSS** (Exploit Prediction Scoring System): the estimated probability, 0 to 1, that the CVE is exploited in the wild in the next 30 days. Most CVEs are below 0.01.
- **CISA KEV** (Known Exploited Vulnerabilities catalog): CVEs with confirmed exploitation. Anything on it and reachable is urgent.
- **Asset value**: what the affected system holds and can reach.

## Identifiers

- **CVE**: one specific vulnerability in one product, for example CVE-2021-44228 (Log4Shell).
- **CWE**: a class of weakness. Common ones: CWE-79 XSS, CWE-89 SQL injection, CWE-78 OS command injection, CWE-22 path traversal, CWE-287 improper authentication, CWE-862 missing authorization, CWE-639 IDOR, CWE-918 SSRF, CWE-502 deserialization of untrusted data, CWE-611 XXE, CWE-352 CSRF, CWE-434 unrestricted file upload, CWE-798 hard-coded credentials, CWE-200 information exposure, CWE-119 / CWE-787 memory corruption, CWE-416 use after free.
- **CPE**: a product and version identifier used to match software to CVEs.
- **MITRE ATT&CK**: a catalog of attacker behaviour. Tactics in order: Reconnaissance, Resource Development, Initial Access, Execution, Persistence, Privilege Escalation, Defense Evasion, Credential Access, Discovery, Lateral Movement, Collection, Command and Control, Exfiltration, Impact.

## OWASP Top 10 (2021)

A01 Broken Access Control, A02 Cryptographic Failures, A03 Injection, A04 Insecure Design, A05 Security Misconfiguration, A06 Vulnerable and Outdated Components, A07 Identification and Authentication Failures, A08 Software and Data Integrity Failures, A09 Security Logging and Monitoring Failures, A10 Server-Side Request Forgery.
