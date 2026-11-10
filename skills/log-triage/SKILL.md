---
name: log-triage
description: Find what went wrong in a log file or long command output. Use when the user pastes or attaches logs, journal output, a build or CI log, or a crash dump and asks what happened, why it failed, or what the errors mean.
---

# Log triage

Logs are mostly noise. The job is to find the first thing that went wrong, not the loudest.

## Steps

1. **Condense first.** If you can run code:

   ```
   python scripts/log_summary.py app.log
   python scripts/log_summary.py app.log --level error --top 30
   python scripts/log_summary.py app.log --grep 'worker-3'
   journalctl -u myservice -n 5000 | python scripts/log_summary.py -
   ```

   It groups lines that differ only in numbers, ids, addresses and timestamps, counts each group, lists errors before warnings, and tells you the line number of the first error.

2. **Go to the first error and read upward.** The cause is usually in the 20 lines before it: a config value, a refused connection, a missing file, a restart. Later errors are often only consequences.

3. **Separate cause from cascade.** One failed database connection can produce a thousand request errors. Report the one, mention the thousand as a consequence.

4. **Check the timeline.** When did it start? Was it sudden or gradual? Does it line up with a deploy, a restart, a cron job, a full disk?

## Reading rules

- Quote the exact line you base a conclusion on, with its line number or timestamp.
- In a stack trace, the useful frame is the deepest one in the user's own code, and the message of the innermost "Caused by".
- Many identical warnings that also appear in healthy runs are background noise. Say so and move on.
- "Killed", exit code 137 or "OOM" means out of memory. Exit 139 is a segfault. "Connection refused" means nothing is listening; "timed out" means something is in the way or overloaded.
- If the log is cut off before the failure or starts after it, say what part is missing and ask for it.
- Do not explain an error from general knowledge when the log does not show it. Mark guesses as guesses.

## Answer format

**What failed:** one sentence.
**First sign:** the quoted line, with where it is.
**Most likely cause:** with how sure you are, and what in the log supports it.
**Consequences:** the follow-on errors, briefly.
**Next step:** the one check or fix to try.
