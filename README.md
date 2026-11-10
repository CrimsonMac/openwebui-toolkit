# openwebui-toolkit

Homemade functions, tools, skills and prompts for my Open WebUI (qwen3.6:35B, gemma4:25B, and qwen3.5:2B as the task model).

| Path | What | Install in Open WebUI |
|---|---|---|
| [functions/context_trim.py](functions/context_trim.py) | Filter that lets chats continue past the context limit | Admin Panel → Functions → New, paste, enable, then turn on globally or per model |
| [tools/calc_time.py](tools/calc_time.py) | Calculator, unit conversion, date maths, current time | Workspace → Tools → New, paste, then enable on the models |
| [skills/](skills) | Five skills written for local models | Workspace → Skills → import each `.md` |
| [prompts/prompts.json](prompts/prompts.json) | Eight slash commands | Workspace → Prompts → Import |

## Context Trim

When a chat grows past the budget, the oldest turns are removed and replaced by a summary note in the system prompt.

- **Rolling summary.** Removed turns are summarized by the task model, and each later trim folds the next batch into the same note. If the summary call fails, the turns are dropped and the note says so.
- **Stable cut point.** A trim cuts down to 70 % of the budget and then leaves the history alone until the budget is hit again. The prompt prefix stays identical in between, so Ollama can reuse its prompt cache instead of re-reading the whole chat every turn.
- **Whole turns only.** The kept history always starts on a user message, so tool calls are never separated from their results.
- **Automatic budget.** Taken from `num_ctx` on the request or the model, × 0.9, minus room for the reply. If no `num_ctx` is found it uses `fallback_token_budget` (200 000). Set `token_budget` to pin it by hand.
- **Images.** Stripped from all but the last few messages, and the kept ones count toward the budget.
- **Self-calibration.** The token estimate is corrected per model from the prompt token count the backend reports after each reply.
- **Edits and restarts.** Editing or branching before the cut point is detected and the summary rebuilt. Cut points and summaries are stored under `DATA_DIR/context_trim/`.

The valves worth a look:

| Valve | Default | Note |
|---|---|---|
| `token_budget` | `0` (auto) | Pin this if `num_ctx` is not set where the filter can see it |
| `trim_to_ratio` | `0.7` | Lower trims less often but keeps less verbatim history |
| `summary_model` | task model | Any model id; a larger model writes better summaries but is slower |
| `summary_num_ctx` | `16384` | Sent with summary calls to Ollama so the small model does not truncate its input |
| `keep_images_in_last` | `4` | |

## Tests

No Open WebUI install needed; its modules are stubbed.

```bash
python tests/test_context_trim.py
```

```bash
python tests/test_calc_time.py
```
