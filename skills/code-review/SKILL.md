---
name: code-review
description: Review code or a diff for bugs, security holes and maintainability problems. Use when the user asks to review, check, audit or critique code, or asks "is this ok?" about code they pasted.
---

# Code review

Find what is wrong or risky. Praise and style opinions are not the job.

## Order of work

1. Say in one or two sentences what the code does. If you cannot, say what is unclear; that is a finding.
2. Walk through it with concrete inputs: the normal case, an empty input, the largest input, a malformed input, two calls at once.
3. Report findings, most serious first.

## What to look for

**Correctness** — off-by-one and boundary errors; None/null and empty collections; wrong operator or inverted condition; mutated shared state or default arguments; unhandled error paths; resources not closed; async calls not awaited; races.

**Security** — user input reaching SQL, shell, file paths, HTML or `eval`; secrets in code or logs; missing permission checks; unsafe deserialization; disabled TLS verification.

**Performance** — only when it matters at realistic sizes: queries or requests inside loops, quadratic loops over large data, loading everything into memory, blocking calls in async code.

**Maintainability** — only what will cause a future bug: duplicated logic that must stay in sync, misleading names, dead code, a function doing unrelated things.

## Rules

- Every finding names the line or function, says what input triggers it and what goes wrong, and gives the fix.
- Report only what you can show from the code in front of you. If it depends on code you cannot see, say "check that…" instead of asserting a bug.
- Do not list formatting or naming taste. Do not pad. Three real findings beat ten weak ones.
- If you find nothing serious, say so in one line and name what you did check.

## Reply format

One line: what the code does.

Then per finding:

**[Critical | Major | Minor] Short title** — `function or line`
What happens and when. The fix, as code if it is short.

End with a one-line verdict: safe to use, safe after the listed fixes, or needs rework.
