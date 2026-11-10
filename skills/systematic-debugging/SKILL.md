---
name: systematic-debugging
description: Find the real cause of a bug before proposing a fix. Use when the user shares an error message, stack trace, failing test, or says code "doesn't work", "broke", or behaves unexpectedly.
---

# Systematic debugging

Do not guess a fix. A fix that is not tied to a proven cause usually hides the bug or adds a second one.

## Steps

1. **Read the evidence exactly.** Quote the error line and the innermost stack frame that is in the user's own code. State what the message literally says, before interpreting it.
2. **State expected versus actual** in one sentence each. If either is unknown, ask for it. That is the one question worth stopping for.
3. **List two or three possible causes**, most likely first, and for each say what observation would confirm or rule it out.
4. **Pick the cheapest check** that splits the candidates: a print of one variable, the smallest input that still fails, one command. Ask the user to run it, or run it if you have a tool for that.
5. **Only when one cause is confirmed**, give the fix. Show the changed lines only, and explain in one sentence why this cause produces this exact symptom.
6. **Say how to verify** the fix, and name anything nearby that has the same flaw.

## Rules

- If you have not seen the code that fails, ask for it. Do not invent what it probably looks like.
- Never suggest several unrelated changes "to see if it helps".
- Never silence an error with a broad try/except, a retry or a sleep unless the cause is understood and that is the right handling.
- Version mismatches, wrong working directory, stale caches and unsaved files are common. Consider them when the code looks correct.
- If your first cause is ruled out, say so plainly and go back to step 3. Do not bend the evidence to fit.

## Reply format

**Symptom:** what fails, quoted.
**Most likely cause:** one sentence, with how sure you are.
**Check:** the one thing to run or look at.
**Fix:** once confirmed.
