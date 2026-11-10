---
name: shell-scripting
description: Write or fix Bash shell scripts and one-liners that are safe and robust. Use when the user asks for a shell script, a bash command, a cron job, automation on Linux or macOS, or has a script that fails or behaves oddly.
---

# Shell scripting

Shell scripts fail silently and destroy data easily. Write them defensively.

## Start from the template

`scripts/bash_template.sh` is a working skeleton with strict mode, usage text, option parsing, logging to stderr, a dry-run flag, a dependency check, and cleanup of temp files on exit. Copy it and replace the marked section.

## Rules

- First lines: `#!/usr/bin/env bash` and `set -euo pipefail`.
- **Quote every expansion**: `"$var"`, `"$@"`, `"$(cmd)"`. Unquoted variables break on spaces and expand wildcards.
- Use `--` before file arguments that come from variables: `rm -- "$file"`.
- Never `rm -rf "$dir/"` without checking that `$dir` is set and non-empty: `rm -rf -- "${dir:?}/"`.
- Test with `[[ ... ]]`. Compare numbers with `-eq`, `-lt`; strings with `==`.
- Loop over files with a glob, not `ls`: `for f in ./*.txt; do [ -e "$f" ] || continue; ...; done`.
- Read lines with `while IFS= read -r line; do ...; done < file`.
- Use `$(...)`, not backticks. Use `local` inside functions.
- Check that tools exist: `command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }`.
- Temp files: `tmp=$(mktemp)` plus `trap 'rm -f "$tmp"' EXIT`.
- Errors and progress go to stderr (`>&2`); only the result goes to stdout.
- Exit non-zero on failure, and say why.
- For anything that deletes, moves or overwrites, add a dry-run option and make the user run it first.

## Common traps

- `cd somewhere` without `|| exit`: the following commands run in the wrong place.
- A pipeline's exit code is the last command's unless `pipefail` is set.
- `local x=$(cmd)` hides the exit code of `cmd`. Declare and assign on separate lines.
- `cat file | while read ...; do count=...; done` runs the loop in a subshell; the variable is lost afterwards.
- Cron runs with a minimal `PATH` and no terminal. Use absolute paths and redirect output to a log.
- `[ $a == $b ]` breaks when a variable is empty. Quote, or use `[[ ]]`.
- `sudo cmd > /root/file` fails: the redirect runs as the user. Use `cmd | sudo tee /root/file`.

## When Bash is the wrong tool

Past about 100 lines, or once you need data structures, JSON, arithmetic on decimals, or real error handling, write it in Python and say why.

## Answer format

The complete script in one code block, how to run it (including the dry run), what it needs installed, and what it changes on the system. For a destructive one-liner, show the harmless version first (`echo`, `ls`, `find` without `-delete`).
