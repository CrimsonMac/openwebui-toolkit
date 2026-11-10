---
name: regex-builder
description: Build, explain or fix a regular expression and prove it works on examples. Use when the user asks for a regex or pattern to match, extract, validate or replace text, or when a regex they have matches the wrong things.
---

# Regex builder

A regex that has not been run against examples is a guess. Always test it.

## Steps

1. **Collect examples.** You need strings that must match and strings that must not. If the user gave none, write three of each from their description and show them, so a misunderstanding is caught early.
2. **Ask which engine** if it matters and is not obvious: Python `re`, JavaScript, PCRE (grep -P, PHP), POSIX (grep -E, sed), Go/RE2. Lookbehind, named groups and `\d` differ between them.
3. **Write the simplest pattern** that separates the two lists. Prefer explicit character classes (`[0-9]{4}`) over `.*`.
4. **Test it.** If you can run code, use the bundled script:

   ```
   python scripts/regex_test.py 'PATTERN' --should-match "a" "b" --should-not-match "c" "d"
   python scripts/regex_test.py 'PATTERN' --flags i --full --should-match "..."
   python scripts/regex_test.py 'PATTERN' --file samples.txt
   ```

   It prints what each sample matched, with groups, and exits 1 if any expectation fails. If you cannot run code, trace each example through the pattern by hand and show the trace.
5. **Fix and re-test** until every example passes. Then give the answer.

## Common mistakes to check

- No anchors: `\d{4}` also matches inside `123456`. Use `^…$`, `\b`, or `--full`.
- Greedy `.*` swallowing too much. Use a negated class (`[^"]*`) or a lazy `.*?`.
- Unescaped `.`, `+`, `?`, `(`, `[`, `|`, `$` meant literally.
- `^` and `$` matching only at string ends without the multiline flag.
- Nested quantifiers like `(a+)+` that hang on long non-matching input.
- Validating emails, URLs or HTML with one giant regex. Use a loose check or a real parser instead, and say so.

## Answer format

The pattern in a code block, the engine and flags it needs, a one-line explanation of each part, and the examples it was tested on. Mention the edge cases it deliberately does not handle.
