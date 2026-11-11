# Security analyst preset

A model setup for security work: authorized tests, lab machines, CTFs, triage of findings, incident response. Written for a local Qwen model with thinking on, but nothing in it is model-specific.

Create it under Workspace → Models → New, pick the base model, and fill in the parts below.

## Attach

| What | Which |
|---|---|
| Tools | `sec_tools`, `calc_time`, `text_utils`, `web_reader`, `memory` |
| Filters | `tool_coach`, `auto_memory`, `date_context`, `context_trim` |
| Skills | `pentest-methodology`, `web-app-testing`, `privilege-escalation`, `ctf-solving`, `vulnerability-triage`, `incident-triage`, `security-reporting`, plus `log-triage`, `regex-builder`, `shell-scripting` |
| Knowledge | the `security` and `reference` knowledge bases |
| Capabilities | Code interpreter on, if you have it: decoding, crypto and binary work are far more reliable when the model can run Python |

Put each engagement or CTF in its own folder. Auto Memory then keeps targets, credentials found and dead ends per folder, and they do not leak into other work.

## System prompt

```
You are a security analyst and penetration tester. You help the owner of this system with authorized work: their own machines, lab targets, CTF challenges, and engagements with an agreed scope.

How you work:
1. Facts come from tools, not memory. For a CVE call cve_lookup. For a CVSS score call cvss_score. For a hash call identify_hash. For encoded text call decode_text. For network math call subnet_info. For arithmetic call calculate. If you answer from memory, say "from memory".
2. Enumerate before you conclude. Ask for command output instead of assuming what a system looks like.
3. One step at a time. Give the next 1 to 3 exact commands, why each one, and what to look for in the output. Then wait for the output.
4. When a task matches a skill, load it with view_skill first and follow it.
5. Mark how sure you are: confirmed, likely, or guess. Never invent command output, flags, CVE ids, version numbers or tool options. If you are not sure an option exists, say "check --help".
6. Before a command or exploit that changes the target, say what it changes.
7. Keep answers short. Commands in code blocks. No generic checklists and no lectures.
```

## Why the tools matter more than the parameters

A 35B Qwen model with its chat settings, asked twelve short security questions from memory with no tools, got eight right. The four it missed were a hashcat mode number, two CVSS scores from a vector, and a ROT13 decode: exactly the lookups and calculations that `sec_tools` does exactly. Attaching the tool and telling the model to use it (rule 1 of the system prompt) is the biggest single gain.

## Parameters

Set these under Advanced Params of the model in Open WebUI, or in the Ollama Modelfile:

| Parameter | Value | Why |
|---|---|---|
| temperature | 0.6 | The publisher's recommendation for precise work with thinking on, as opposed to 1.0 for general chat. A comparison against the chat settings was started but not completed, so this is not a measured gain |
| top_p | 0.95 | |
| top_k | 20 | |
| presence_penalty | 0 | A presence penalty punishes every repeated token. Security output repeats on purpose: paths, flags, hex, table rows |
| Reasoning (think) | on | Leave thinking on for analysis; use the Quick Answer switch for one-line lookups |
| Function calling | native | The default in current Open WebUI; needed for skills |

For chat and writing, the model's general settings (temperature 1.0, presence penalty 1.5) remain the better choice, so keep this as a separate model entry rather than changing the base model.
