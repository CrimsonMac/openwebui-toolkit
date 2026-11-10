# openwebui-toolkit

Homemade functions, tools, skills and prompts for Open WebUI, written with local models in mind (developed against qwen and gemma on Ollama). Everything is a single self-contained file or folder with no dependencies beyond the Python standard library and pydantic.

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

## Functions

| File | Type | What it does |
|---|---|---|
| [context_trim.py](functions/context_trim.py) | Filter | Lets a chat continue past the context limit: old turns are folded into a rolling summary, the cut point stays put between trims so the prompt cache survives |
| [date_context.py](functions/date_context.py) | Filter | Tells the model today's date (and optionally the time) without invalidating the prompt cache every turn |
| [output_cleanup.py](functions/output_cleanup.py) | Filter | Removes leaked chat-template tokens, cuts a reply that got stuck repeating itself, collapses blank lines; leaves code blocks alone |
| [cache_watch.py](functions/cache_watch.py) | Filter | Warns when an early change forces the backend to re-read the conversation, says what changed and roughly how long it takes |
| [quick_answer.py](functions/quick_answer.py) | Filter (switch) | A switch in the message box that turns off the thinking phase for quick questions |
| [handoff_brief.py](functions/handoff_brief.py) | Action | Button under a reply that writes a brief of the whole chat to paste into a fresh one |
| [second_opinion.py](functions/second_opinion.py) | Pipe | A model entry where one model drafts, a second reviews, and the first revises |

## Tools

| File | What the model can do with it |
|---|---|
| [calc_time.py](tools/calc_time.py) | Exact arithmetic, unit conversion, date differences, date arithmetic, current time |
| [text_utils.py](tools/text_utils.py) | Count characters, words and occurrences, word frequency, diff two texts, sort and dedupe lines, run a regex, hash and encode, validate JSON |
| [notes.py](tools/notes.py) | A persistent per-user notebook: save, search, list, read and delete notes across chats |
| [web_reader.py](tools/web_reader.py) | Fetch a web page as readable text, in parts for long pages, and list its links. Refuses local and private addresses unless allowed |
| [wikipedia.py](tools/wikipedia.py) | Search Wikipedia and read articles or single sections, in any language edition, no API key |
| [ollama_status.py](tools/ollama_status.py) | See installed and loaded Ollama models, memory use, CPU/GPU split and model parameters. Unloading is off by default |

## Skills

Skills marked with a script ship a helper the model can run when code execution is available; each also describes what to do without it.

| Skill | Use | Script |
|---|---|---|
| [clear-writing](skills/clear-writing/SKILL.md) | Edit or write prose that is clear and direct | |
| [code-review](skills/code-review/SKILL.md) | Review code for bugs, security and maintainability | |
| [csv-data-profiling](skills/csv-data-profiling/SKILL.md) | Understand and sanity-check a CSV before analysing it | `profile_csv.py` |
| [decision-matrix](skills/decision-matrix/SKILL.md) | Choose between options with weighted criteria | `decision_matrix.py` |
| [deep-summary](skills/deep-summary/SKILL.md) | Summarize long documents faithfully | |
| [docker-troubleshooting](skills/docker-troubleshooting/SKILL.md) | Debug containers and Compose setups | |
| [git-rescue](skills/git-rescue/SKILL.md) | Get a repository out of trouble safely | `git_overview.sh` |
| [json-wrangling](skills/json-wrangling/SKILL.md) | Inspect, query, diff and repair JSON | `json_tool.py` |
| [linux-troubleshooting](skills/linux-troubleshooting/SKILL.md) | Diagnose slowness, full disks, failing services | `sysinfo.sh` |
| [log-triage](skills/log-triage/SKILL.md) | Find what went wrong in a log | `log_summary.py` |
| [ollama-tuning](skills/ollama-tuning/SKILL.md) | Context size, memory, speed and Modelfiles | `vram_estimate.py`, `ollama_bench.py`, `ollama_prewarm.py` |
| [openwebui-extension-author](skills/openwebui-extension-author/SKILL.md) | Write Open WebUI tools and functions | |
| [prompt-crafting](skills/prompt-crafting/SKILL.md) | Write prompts and system prompts, including for small models | |
| [python-quality](skills/python-quality/SKILL.md) | Write good Python and check existing code | `py_check.py` |
| [regex-builder](skills/regex-builder/SKILL.md) | Build a regex and prove it on examples | `regex_test.py` |
| [research-with-sources](skills/research-with-sources/SKILL.md) | Research a question and cite what was found | |
| [shell-scripting](skills/shell-scripting/SKILL.md) | Safe, robust Bash | `bash_template.sh` |
| [sql-writing](skills/sql-writing/SKILL.md) | Write, fix and speed up SQL | |
| [systematic-debugging](skills/systematic-debugging/SKILL.md) | Find the cause of a bug before fixing it | |
| [test-writing](skills/test-writing/SKILL.md) | Write tests that can actually fail | |
| [tutor](skills/tutor/SKILL.md) | Teach a topic step by step with checks | |

The scripts are plain Python or Bash with no dependencies and work on their own too, for example `python skills/log-triage/scripts/log_summary.py app.log`.

## Prompts

`/tldr`, `/fix`, `/rewrite`, `/explain`, `/commit`, `/critique`, `/translate`, `/steps`. Most act on the clipboard, so copy the text first.

## Context Trim in detail

When a chat grows past the budget, the oldest turns are removed and replaced by a summary note in the system prompt.

- **Rolling summary.** Removed turns are summarized by the chat's own model with thinking off (set `summary_model` to `task` or a model id to change that), and each later trim folds the next batch into the same note. If the summary call fails, the turns are dropped and the note says so.
- **Stable cut point.** A trim cuts down to 70 % of the budget and then leaves the history alone until the budget is hit again. The prompt prefix stays identical in between, so Ollama can reuse its prompt cache instead of re-reading the whole chat every turn.
- **Whole turns only.** The kept history always starts on a user message, so tool calls are never separated from their results.
- **Automatic budget.** Taken from `num_ctx` on the request or the model, × 0.9, minus room for the reply. If no `num_ctx` is found it uses `fallback_token_budget`. Set `token_budget` to pin it by hand.
- **Images.** Stripped from all but the last few messages, and the kept ones count toward the budget.
- **Self-calibration.** The token estimate is corrected per model from the prompt token count the backend reports after each reply.
- **Edits and restarts.** Editing or branching before the cut point is detected and the summary rebuilt. Cut points and summaries are stored under `DATA_DIR/context_trim/`.

| Valve | Default | Note |
|---|---|---|
| `token_budget` | `0` (auto) | Pin this if `num_ctx` is not set where the filter can see it |
| `trim_to_ratio` | `0.7` | Lower trims less often but keeps less verbatim history |
| `summary_model` | chat model | `task` for Open WebUI's task model, or any model id |
| `max_reread_seconds` + `read_tokens_per_second` | off | Cap the history by how long a full re-read may take, using your measured prompt speed |
| `summary_num_ctx` | `16384` | Sent with summary calls when a different Ollama model writes them |
| `keep_images_in_last` | `4` | |

## Tests

No Open WebUI install is needed; its modules are stubbed, and network tools run against a throwaway local server.

```bash
for t in tests/test_*.py tests/check_repo.py; do python "$t" || break; done
```

`tests/check_repo.py` verifies that every skill, function, tool and prompt has the shape Open WebUI's importers expect.
