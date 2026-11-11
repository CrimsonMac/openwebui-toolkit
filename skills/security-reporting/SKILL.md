---
name: security-reporting
description: Write up security findings clearly - a pentest report, a single finding, a bug bounty submission, or a CTF writeup. Use when the user has found something and wants it documented, or pastes notes and asks for a report, summary for management, or remediation advice.
---

# Security reporting

A report is read by two people: one decides, one fixes. Give each what they need, and nothing that cannot be reproduced.

## One finding

Use these parts, in this order:

1. **Title**: what and where. "SQL injection in the `id` parameter of /api/orders", not "Injection issue".
2. **Severity**: rating plus CVSS vector and score (compute it with the `cvss_score` tool if available) and one sentence on why.
3. **Affected**: host, URL, parameter, version.
4. **Description**: what the flaw is, in two to four sentences.
5. **Steps to reproduce**: numbered, with the exact requests or commands and the observed result. Someone else must be able to repeat it.
6. **Impact**: what an attacker gains here, concretely. No "could potentially possibly".
7. **Remediation**: the specific fix first, then hardening. Name the setting, function or version.
8. **References**: CWE, vendor advisory.

Mask passwords, tokens and personal data in evidence.

## Full report

1. Executive summary: scope, dates, overall result in plain words, the three things to fix first. One page, no jargon.
2. Scope and method: what was tested, what was not, limits.
3. Findings table: id, title, severity, status.
4. Findings in detail, most severe first.
5. Appendix: tool output, hosts and ports, cleanup done (accounts, files, changes made during the test).

## Bug bounty submission

Lead with impact and a minimal reproduction. One issue per report. State what you did not do (no data accessed beyond your own account).

## CTF writeup

Challenge name and category, the idea in one sentence, then the steps with commands and why each was tried, including the dead end that led to the solution, and the final script.

## Checks before sending

Every claim has evidence; severity matches the described impact; steps work from a clean start; nothing from outside the scope appears.
