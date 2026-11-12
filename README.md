# openwebui-toolkit

Homemade functions, tools, skills, prompts and knowledge files for Open WebUI, written with local models in mind (developed against qwen and gemma on Ollama). Everything is a single self-contained file or folder with no dependencies beyond the Python standard library and pydantic.

## Importing

**Skills** — Workspace → Skills → Import, and paste one of:

| To import | URL |
|---|---|
| All skills | `https://github.com/CrimsonMac/openwebui-toolkit/tree/main/skills` |
| One skill | `https://github.com/CrimsonMac/openwebui-toolkit/tree/main/skills/regex-builder` |

Each skill is a folder with a `SKILL.md` and, for some, a `scripts/` folder that is imported along with it.

**Functions and tools** — Admin Panel → Functions (or Workspace → Tools) → Import from link, with the raw file URL:

```
https://raw.githubusercontent.com/CrimsonMac/openwebui-toolkit/main/functions/context_trim.py
```

Replace the path with any file from the tables below. Pasting the file's content into a new function or tool works too. After importing a function, switch it on, and for filters enable it globally or per model.

**Prompts** — download [prompts/prompts.json](prompts/prompts.json) and use Workspace → Prompts → Import.

**Knowledge** — see [Knowledge](#knowledge) below; one command uploads the whole folder.

## Functions

| File | Type | What it does |
|---|---|---|
| [context_trim.py](functions/context_trim.py) | Filter | Keeps long agentic chats inside the context window on every tool round: old tool results are shortened first, then the oldest work is folded into a rolling summary while the current request stays pinned; token counts are corrected from what the backend reports |
| [date_context.py](functions/date_context.py) | Filter | Tells the model today's date (and optionally the time) without invalidating the prompt cache every turn |
| [output_cleanup.py](functions/output_cleanup.py) | Filter | Removes leaked chat-template tokens, cuts a reply that got stuck repeating itself, collapses blank lines; leaves code blocks alone |
| [cache_watch.py](functions/cache_watch.py) | Filter | Warns when an early change forces the backend to re-read the conversation, says what changed and roughly how long it takes |
| [auto_memory.py](functions/auto_memory.py) | Filter | Long-term memory that fills itself: reads a chat once it has gone idle and saves lasting facts, saves at once on `/remember ...`, and shows saved memories to the model in later chats. Chats in a folder get that folder's own project memory. Details [below](#memory-in-detail) |
| [tool_coach.py](functions/tool_coach.py) | Filter | Gets the model to use its tools and skills: short rules in the system prompt, plus a hint on each message naming the tools and skills whose descriptions match it |
| [steady_vision.py](functions/steady_vision.py) | Filter | Consistent answers about images without thinking in circles: while an image is in play, thinking is off, the temperature is low, there is no presence penalty, and a rule says to report only what is clearly visible |
| [quick_answer.py](functions/quick_answer.py) | Filter (switch) | A switch in the message box that turns off the thinking phase for quick questions |
| [handoff_brief.py](functions/handoff_brief.py) | Action | Button under a reply that writes a brief of the whole chat to paste into a fresh one |
| [second_opinion.py](functions/second_opinion.py) | Pipe | A model entry where one model drafts, a second reviews, and the first revises |

## Tools

| File | What the model can do with it |
|---|---|
| [calc_time.py](tools/calc_time.py) | Exact arithmetic, unit conversion, date differences, date arithmetic, current time |
| [text_utils.py](tools/text_utils.py) | Count characters, words and occurrences, word frequency, diff two texts, sort and dedupe lines, run a regex, hash and encode, validate JSON |
| [memory.py](tools/memory.py) | Long-term memory with one global list and one list per project: remember, recall, forget, list projects. Same store as the Auto Memory filter |
| [sec_tools.py](tools/sec_tools.py) | Look up a CVE (NVD, EPSS, known-exploited flag), compute a CVSS 3.x score from a vector, identify a hash type with its hashcat mode, peel encodings off a string, decode a JWT, work out a subnet |
| [chat_history.py](tools/chat_history.py) | Search and read the parts of the current chat that Context Trim shortened or removed, so nothing in a long chat is out of reach |
| [notes.py](tools/notes.py) | A persistent per-user notebook: save, search, list, read and delete notes across chats |
| [web_reader.py](tools/web_reader.py) | Fetch a web page as readable text, in parts for long pages, and list its links. Refuses local and private addresses unless allowed |
| [web_inspector.py](tools/web_inspector.py) | Send any HTTP request with its own method, headers, cookies and body, with cookies kept per chat so a login carries over; profile a site (server, framework, language, TLS certificate, security headers); tell real pages from custom "not found" pages; search page source with a regex; list forms, scripts and comments; read TLS certificates. Runs on the server with full TLS, which the browser code interpreter does not have |
| [wikipedia.py](tools/wikipedia.py) | Search Wikipedia and read articles or single sections, in any language edition, no API key |
| [ollama_status.py](tools/ollama_status.py) | See installed and loaded Ollama models, memory use, CPU/GPU split and model parameters. Unloading is off by default |

## Skills

Skills marked with a script ship a helper the model can run when code execution is available; each also describes what to do without it.

| Skill | Use | Script |
|---|---|---|
| [clear-writing](skills/clear-writing/SKILL.md) | Edit or write prose that is clear and direct | |
| [code-review](skills/code-review/SKILL.md) | Review code for bugs, security and maintainability | |
| [ctf-solving](skills/ctf-solving/SKILL.md) | Work through CTF tasks by category without inventing flags | |
| [csv-data-profiling](skills/csv-data-profiling/SKILL.md) | Understand and sanity-check a CSV before analysing it | `profile_csv.py` |
| [decision-matrix](skills/decision-matrix/SKILL.md) | Choose between options with weighted criteria | `decision_matrix.py` |
| [deep-summary](skills/deep-summary/SKILL.md) | Summarize long documents faithfully | |
| [docker-troubleshooting](skills/docker-troubleshooting/SKILL.md) | Debug containers and Compose setups | |
| [git-rescue](skills/git-rescue/SKILL.md) | Get a repository out of trouble safely | `git_overview.sh` |
| [incident-triage](skills/incident-triage/SKILL.md) | Investigate a suspected compromise: preserve, look, timeline, contain | |
| [json-wrangling](skills/json-wrangling/SKILL.md) | Inspect, query, diff and repair JSON | `json_tool.py` |
| [linux-troubleshooting](skills/linux-troubleshooting/SKILL.md) | Diagnose slowness, full disks, failing services | `sysinfo.sh` |
| [log-triage](skills/log-triage/SKILL.md) | Find what went wrong in a log | `log_summary.py` |
| [ollama-tuning](skills/ollama-tuning/SKILL.md) | Context size, memory, speed and Modelfiles | `vram_estimate.py`, `ollama_bench.py`, `ollama_prewarm.py`, `ollama_ram_wall.py` |
| [openwebui-extension-author](skills/openwebui-extension-author/SKILL.md) | Write Open WebUI tools and functions | |
| [pentest-methodology](skills/pentest-methodology/SKILL.md) | Run an authorized test or lab box phase by phase | |
| [privilege-escalation](skills/privilege-escalation/SKILL.md) | Get from a low-privileged shell to root or SYSTEM | |
| [prompt-crafting](skills/prompt-crafting/SKILL.md) | Write prompts and system prompts, including for small models | |
| [python-quality](skills/python-quality/SKILL.md) | Write good Python and check existing code | `py_check.py` |
| [regex-builder](skills/regex-builder/SKILL.md) | Build a regex and prove it on examples | `regex_test.py` |
| [research-with-sources](skills/research-with-sources/SKILL.md) | Research a question and cite what was found | |
| [security-reporting](skills/security-reporting/SKILL.md) | Write up findings, pentest reports, bounty submissions, CTF writeups | |
| [shell-scripting](skills/shell-scripting/SKILL.md) | Safe, robust Bash | `bash_template.sh` |
| [sql-writing](skills/sql-writing/SKILL.md) | Write, fix and speed up SQL | |
| [systematic-debugging](skills/systematic-debugging/SKILL.md) | Find the cause of a bug before fixing it | |
| [test-writing](skills/test-writing/SKILL.md) | Write tests that can actually fail | |
| [tutor](skills/tutor/SKILL.md) | Teach a topic step by step with checks | |
| [vulnerability-triage](skills/vulnerability-triage/SKILL.md) | Decide whether a CVE or scanner finding applies and how urgent it is | |
| [web-app-testing](skills/web-app-testing/SKILL.md) | Test a web app or API: access control, auth, injection, files, SSRF | |
| [website-analysis](skills/website-analysis/SKILL.md) | Read a site from its responses: stack and language, custom error pages, what a status code proves, and checking each conclusion twice | |

The scripts are plain Python or Bash with no dependencies and work on their own too, for example `python skills/log-triage/scripts/log_summary.py app.log`.

## Prompts

`/tldr`, `/fix`, `/rewrite`, `/explain`, `/commit`, `/critique`, `/translate`, `/steps`. Most act on the clipboard, so copy the text first.

## Presets

Model setups to copy: what to attach, a system prompt, parameters, and the reasoning.

| Preset | For |
|---|---|
| [security-analyst](presets/security-analyst.md) | Authorized testing, CTFs, vulnerability triage and incident response, using the security tools, skills and knowledge here |
| [vision](presets/vision.md) | Consistent answers about images, with the measurements behind the settings |
| [web-investigator](presets/web-investigator.md) | Inspecting websites with the Web Inspector tool, and what to do about the code interpreter having no network |

## Knowledge

Reference sheets written to be retrieved in pieces: every section stands on its own. Each subfolder of [knowledge/](knowledge) becomes one knowledge base.

| Folder | Files |
|---|---|
| [security](knowledge/security) | Ports and what to check on each, nmap, web vulnerabilities, Linux privilege escalation, Windows and Active Directory, hash cracking, CVSS and identifiers |
| [reference](knowledge/reference) | HTTP methods, status codes, headers and curl |

To add them, either create a knowledge base under Workspace → Knowledge and drop the folder's files in, or let the script do it. It needs an API key (Settings → Account) and only the Python standard library:

```bash
OPENWEBUI_API_KEY=sk-... python scripts/upload_knowledge.py http://localhost:3000
```

It creates one knowledge base per subfolder and skips files that are already there, so it is safe to run again after pulling. `--only security` limits it to one folder. Then attach the knowledge base to a model (Workspace → Models → Knowledge) or pull it into a chat with `#`.

To add your own, put `.md` or `.txt` files in a subfolder: a `# Title` line first, then `## ` sections that each make sense alone. `tests/check_repo.py` checks the shape.

## Memory in detail

Two pieces share one store under `DATA_DIR/memory_store/`, and each works without the other:

- **Auto Memory** (filter) saves and shows memories without the model having to do anything.
- **Memory** (tool) lets the model save, search and delete on request.

How saving happens:

- **When idle.** After a reply the filter waits `idle_seconds` (120). If no new message arrives, the turns since the last pass are read once and lasting facts are saved: who the user is, their setup, preferences, decisions. Questions, small talk and anything that looks like a password or key are not saved. A new message before the time is up cancels the pass, so it never competes with a chat in progress.
- **When told.** `/remember I use fish, not bash` (or `remember: ...`) is saved as written, at once. The model can also call the tool's `remember` when asked in plain words.
- **Corrections.** The idle pass sees the existing memories and can replace one that has become outdated instead of adding a second.

How projects work: a chat inside an Open WebUI folder belongs to the project named after that folder. Facts about the project are stored under it and only shown in chats in the same folder; facts about the user are global and shown everywhere. Chats outside folders use global memory only. The tool takes a `project` argument for anything else.

How memories reach the model: at the start of a chat the newest memories (up to `max_inject_chars`) are added to the system prompt. A chat keeps that block unchanged until it has been quiet for `refresh_after_minutes`, because a changed system prompt would make the backend re-read the whole conversation. Older memories stay searchable through the tool's `recall`.

| Valve | Default | Note |
|---|---|---|
| `idle_seconds` | `120` | Quiet time before a chat is read for memories |
| `memory_model` | chat model | `task` for Open WebUI's task model, or a model id. The chat's own model is already loaded and is asked with thinking off |
| `min_new_chars` | `200` | A pass is skipped when the user wrote less than this since the last one |
| `use_projects` | on | Off = one global memory for everything |
| `auto_save` / `inject` | on | Switch either half off |

Temporary chats are never read for memories.

The idle pass does not cost the chat its prompt cache: measured on Ollama, a 30,000-token conversation was picked up again instantly after an unrelated short request in between.

## Context Trim in detail

Built for long agentic chats: many tool calls in one reply, many replies in one chat. When the chat grows past the budget, the filter frees room in two steps, least harmful first.

**Turn off Open WebUI's own compaction when using this filter** (Admin Panel → Settings → Interface → Context Compaction). It runs before any filter, starts at 80,000 tokens by default whatever the model's context size is, and keeps only 40 % of the messages each time. The filter shows a one-time notice in the chat when it sees that the built-in compaction has already cut the history.

- **It watches every tool round.** Open WebUI 0.13 calls a filter's `inlet` only on the first request of a reply; each following tool round goes through a separate `request` hook. The filter implements both, so a reply with 80 tool calls is checked 80 times. Without that, one long reply outgrows the context window, and Ollama then drops the oldest messages without any notice and leaves almost no room for the answer.
- **Step 1: shorten old tool results.** Fetched pages and command output are most of an agentic chat and the least missed. All but the newest few are cut to their first and last lines, with a note that names the message number to read the rest. Everything the user and the model wrote stays word for word, and the model still sees which tools it called and roughly what came back. Results the model has not answered yet are never touched.
- **Step 2: fold the oldest messages into a summary**, if step 1 left the chat above 70 % of the budget. The cut may fall inside the current reply: the request the model is working on is then pinned in front of the kept messages, so the model always sees what it was asked. A cut goes down to half the budget, so the next one is far away.
- **Nothing is lost.** Everything shortened or removed is kept on disk under `DATA_DIR/context_trim/archive/`. With the [Chat History](tools/chat_history.py) tool attached, the model can search it (`search_chat_history`) and read any earlier message in full by its number (`read_chat_message`). Attach the tool to every model that uses this filter.
- **One huge result cannot fill the context.** A single tool result over `max_tool_result_tokens` (8000) is cut to that size the moment it arrives, with the rest readable through the tool.
- **Rolling summary.** The note records the goal, the facts, the work done (tools called and what they returned, commands and results), every failed attempt and why, decisions, the current state and the exact next step. It tells the model that finished work is finished. Its size grows with the budget, from 1200 up to 4000 tokens. It is written by the chat's own model with thinking off (set `summary_model` to `task` or a model id to change that), and each later trim folds the next batch into the same note. If the summary call fails, the messages are dropped and the note says so.
- **The prompt cache survives.** Between two trims the prompt only grows at the end, so Ollama reuses its cache instead of re-reading the chat. The filter recognises its own work: seeing an already trimmed conversation again (which is what a tool round hands it) changes nothing, and the next reply starts with exactly the prompt the last one ended on. In a simulated session of 366 requests at a 131,072 context with 2,000-token tool results, the cache was broken 11 times.
- **Token counts that match the model.** Bytes per token is not a constant. Measured on a Qwen tokenizer, prose and code take about 4 bytes per token, but JSON, log lines, numbers and hex ids only about 1.5. The filter estimates from what the text is made of (within 0.85 to 1.25 of the real count on 16 kinds of text), then corrects itself from the prompt token count the backend reports after every request, tool rounds included.
- **Automatic budget.** Context size × 0.9, minus 8192 tokens for the reply. The context size is taken from `num_ctx` on the request or the model; if it is only set in the Ollama Modelfile, the filter asks Ollama (`/api/ps`, then `/api/show`) through Open WebUI's own Ollama connection. If an Ollama model's context size cannot be found at all, a small budget is used and a notice says so. Set `token_budget` to pin it by hand.
- **Images.** Stripped from all but the last few messages, and the kept ones count toward the budget.
- **Edits and restarts.** The cut point is remembered by the content of the message it was made at, not by a position, so it holds in the full history and in a trimmed copy alike. If that message is gone (edited or branched history), the filter starts over. State is stored under `DATA_DIR/context_trim/`.

| Valve | Default | Note |
|---|---|---|
| `token_budget` | `0` (auto) | Pin the budget by hand |
| `context_safety`, `reserve_output_tokens` | `0.9`, `8192` | How much of the context to fill, and the room left for the reply |
| `max_tool_result_tokens` | `8000` | Size limit for one tool result; `0` = none |
| `prune_tool_results` | on | Step 1. `keep_full_tool_results` (4) and `pruned_tool_chars` (1200) tune it |
| `trim_to_ratio` | `0.7` | Step 2 runs when step 1 leaves the chat above this fraction of the budget |
| `cut_to_ratio` | `0.5` | Step 2 cuts down to this fraction. Lower = fewer trims, less word-for-word history |
| `summary_model` | chat model | `task` for Open WebUI's task model, or any model id |
| `summary_max_tokens` | `0` (auto) | 3 % of the budget, between 1200 and 4000 |
| `ollama_url` | empty | Where to ask for the context size; empty = Open WebUI's Ollama connections |
| `ollama_fallback_token_budget` | `28000` | Budget for an Ollama model whose context size is unknown |
| `overhead_tokens` | `6000` | Assumed cost of tool definitions and skills until real counts are seen |
| `max_reread_seconds` + `read_tokens_per_second` | off | Cap the history by how long a full re-read may take |
| `keep_images_in_last` | `4` | |

## Tests

No Open WebUI install is needed; its modules are stubbed, and network tools run against a throwaway local server.

```bash
for t in tests/test_*.py tests/check_repo.py; do python "$t" || break; done
```

`tests/check_repo.py` verifies that every skill, function, tool and prompt has the shape Open WebUI's importers expect.
