---
name: python-quality
description: Write Python that is correct, readable and idiomatic, and check existing Python for common bugs. Use when writing new Python code, refactoring or cleaning up Python, or when the user asks to improve, lint or modernize a Python file.
---

# Writing good Python

## When writing

- **Target Python 3.10+** unless told otherwise. Use f-strings, `pathlib.Path`, `dataclasses`, `match` where it reads better, and `X | None` type hints.
- **Type-hint every function signature.** Skip hints on obvious locals.
- **One function, one job**, short enough to read without scrolling. Return early instead of nesting.
- **Names say what a thing is**: `user_ids`, not `data` or `lst`. No abbreviations a reader must decode.
- **Handle errors where you can do something about them.** Catch the specific exception. Let the rest propagate. Never `except: pass`.
- **Use context managers** for files, locks and connections: `with open(path, encoding="utf-8") as f:`.
- **No mutable default arguments.** Use `None` and create the list or dict inside.
- **Prefer the standard library**: `collections.Counter`, `itertools`, `json`, `csv`, `argparse`, `subprocess.run([...], check=True)` with a list, never a shell string built from input.
- **A script has** a `main()` and `if __name__ == "__main__":`, and exits non-zero on failure.
- **Comments explain why**, not what. Docstrings on public functions, one line when that is enough.
- **Write the code that was asked for.** No speculative options, layers or classes.

## When reviewing or cleaning up

If you can run code, check first:

```
python scripts/py_check.py file.py
python scripts/py_check.py src/
```

It needs no installation and reports: syntax errors, unused imports, mutable default arguments, bare or silent `except`, `== None`, `is` used on strings or numbers, shadowed builtins, unreachable code, duplicate dict keys, assert on a tuple, and `eval`/`exec`. It exits 1 when it finds something. It is a quick net, not a replacement for `ruff`, `mypy` or tests; use those too when they are installed.

Fix what it reports, then read the code for what no tool sees: wrong logic, missing edge cases (empty input, None, very large input), and resources not released.

## Do not

- Rewrite working code in a different style without being asked.
- Add dependencies for what ten lines of standard library do.
- Change behaviour while "cleaning up". If a cleanup changes behaviour, say so explicitly.

## Answer format

Give complete, runnable code, not fragments with "rest stays the same", unless the file is long and the change is small. After the code, list what you changed and why in a few lines, and how to run or test it.
