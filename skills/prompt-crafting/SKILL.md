---
name: prompt-crafting
description: Write or improve a prompt or system prompt for a language model, including small local models. Use when the user asks for a system prompt, a model persona, a prompt template, or says a prompt gives poor or inconsistent results.
---

# Writing prompts that work

A prompt is a briefing for a capable reader who knows nothing about the situation. Most bad output comes from missing context, not from missing "rules".

## Before writing, know

1. **The task**: what goes in, what should come out.
2. **The reader of the output**: who uses it and for what.
3. **What good looks like**: ideally one real example of an ideal output.
4. **The target model**: a large model follows nuance; a small local model (under about 10B parameters) needs shorter prompts, one task at a time, and an explicit output format.

Ask the user for whichever of these is missing and cannot be guessed safely.

## Structure

1. **Situation and role** — who the model is working for and why. One or two sentences. Skip empty lines like "You are a world-class expert".
2. **The task** — in plain sentences, with the reason behind each requirement. "Keep answers under 100 words because they are read on a phone" works better than "BE BRIEF".
3. **Context and material** — put long documents in tags (`<document>…</document>`) and above the instructions that use them.
4. **Output format** — state it exactly. For anything parsed by code, show the literal shape.
5. **Examples** — one to three, in tags, varied so the model does not copy one too closely.

## Rules

- Say what to do, not what to avoid. "Write in flowing paragraphs" beats "don't use bullets".
- Give reasons. A model that knows why can handle the cases you did not list.
- No shouting. Capitals and "CRITICAL" make models over-apply a rule.
- One instruction per idea, and no contradictions. Reread for pairs like "be thorough" and "be brief".
- Tell it what to do when unsure: ask, say "unknown", or make a stated assumption.
- Use template variables for what changes per use: `{{topic}}`.

## For small local models

- Keep the system prompt under about 300 words. Long prompts push out the task.
- One task per prompt. Chain prompts for multi-step work.
- Put the most important instruction last, just before the input.
- Give the output format as a fill-in skeleton.
- Prefer a concrete example over an abstract description.

## Deliver

The prompt in one code block, ready to paste. Then two or three lines: what you assumed, and what to adjust if the output is too long, too cautious or off format.
