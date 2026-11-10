"""Checks that everything in the repo can be imported into Open WebUI. Run: python tests/check_repo.py

- every skill is a folder with a SKILL.md whose YAML frontmatter has a matching name and a description
- every script a SKILL.md mentions exists
- every function and tool has the metadata header and the right class
- Python files avoid f-string syntax that only works on Python 3.12+ (Open WebUI runs 3.11)
- prompts.json has the fields the importer needs
"""

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
problems = []


def bad(path, msg):
    problems.append(f"{Path(path).relative_to(ROOT)}: {msg}")


def frontmatter(text):
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if not m:
        return None
    try:
        import yaml

        value = yaml.safe_load(m.group(1))
        return value if isinstance(value, dict) else None
    except ImportError:
        out = {}
        for line in m.group(1).splitlines():
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip()
        return out
    except Exception:
        return None


def check_skills():
    names = []
    for entry in sorted((ROOT / "skills").iterdir()):
        if not entry.is_dir():
            bad(entry, "loose file in skills/; each skill must be a folder containing SKILL.md")
            continue
        skill = entry / "SKILL.md"
        if not skill.exists():
            bad(entry, "no SKILL.md")
            continue
        text = skill.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm is None:
            bad(skill, "frontmatter missing or not valid YAML")
            continue
        if fm.get("name") != entry.name:
            bad(skill, f"name '{fm.get('name')}' does not match folder '{entry.name}'")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry.name):
            bad(skill, "name must be lowercase letters, digits and single hyphens")
        desc = fm.get("description")
        if not isinstance(desc, str) or not 40 <= len(desc) <= 1024:
            bad(skill, "description must be a string of 40-1024 characters")
        if len(text) > 20000:
            bad(skill, "longer than 20000 characters; Open WebUI pages it")
        for ref in set(re.findall(r"scripts/[\w.-]+\.(?:py|sh)", text)):
            if not (entry / ref).exists():
                bad(skill, f"mentions {ref}, which does not exist")
        for script in (entry / "scripts").glob("*") if (entry / "scripts").exists() else []:
            if script.name not in text:
                bad(script, "not mentioned in SKILL.md, so the model will never find it")
        names.append(entry.name)
    return names


def check_fstrings(path, source):
    """Flag f-strings that need Python 3.12: a backslash or the outer quote inside {...}."""
    stack = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            name = tokenize.tok_name[tok.type]
            if name == "FSTRING_START":
                quote = tok.string.lstrip("rRbBfFuU")
                if stack and quote == stack[-1] and len(quote) == 1:
                    bad(path, f"line {tok.start[0]}: nested f-string reuses the outer quote (needs Python 3.12)")
                stack.append(quote)
            elif name == "FSTRING_END":
                stack.pop()
            elif stack and name != "FSTRING_MIDDLE":
                outer = stack[-1]
                if "\\" in tok.string:
                    bad(path, f"line {tok.start[0]}: backslash inside an f-string expression (needs Python 3.12)")
                elif name == "STRING" and len(outer) == 1 and tok.string.lstrip("rRbBuU")[:1] == outer:
                    bad(path, f"line {tok.start[0]}: f-string expression reuses the outer quote (needs Python 3.12)")
    except tokenize.TokenError as e:
        bad(path, f"cannot tokenize: {e}")


def check_python(folder, classes):
    found = []
    for path in sorted((ROOT / folder).glob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            bad(path, f"syntax error on line {e.lineno}: {e.msg}")
            continue
        doc = ast.get_docstring(tree) or ""
        for field in ("title", "author", "version", "description"):
            if not re.search(rf"^{field}:\s*\S", doc, re.MULTILINE):
                bad(path, f"metadata header lacks '{field}:'")
        if not source.startswith('"""'):
            bad(path, "the metadata docstring must be the very first thing in the file")
        top = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        kind = next((c for c in classes if c in top), None)
        if kind is None:
            bad(path, f"no class named {' or '.join(classes)}")
            continue
        if kind == "Tools":
            for fn in top[kind].body:
                if isinstance(fn, ast.AsyncFunctionDef) and not fn.name.startswith("_"):
                    fdoc = ast.get_docstring(fn) or ""
                    if not fdoc:
                        bad(path, f"{fn.name}: no docstring; the model would not know what it does")
                    for arg in fn.args.args[1:]:
                        if arg.arg.startswith("__"):
                            continue
                        if arg.annotation is None:
                            bad(path, f"{fn.name}: parameter '{arg.arg}' has no type hint")
                        if f":param {arg.arg}:" not in fdoc:
                            bad(path, f"{fn.name}: parameter '{arg.arg}' is not described with :param")
        check_fstrings(path, source)
        found.append(path.name)
    return found


def check_scripts():
    for path in sorted((ROOT / "skills").glob("*/scripts/*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            bad(path, f"syntax error on line {e.lineno}: {e.msg}")
        check_fstrings(path, source)


def check_prompts():
    path = ROOT / "prompts" / "prompts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        bad(path, f"invalid JSON: {e}")
        return 0
    commands = set()
    for p in data:
        for field in ("command", "content"):
            if not p.get(field):
                bad(path, f"a prompt lacks '{field}'")
        if not (p.get("title") or p.get("name")):
            bad(path, f"{p.get('command')}: no title")
        if not str(p.get("command", "")).startswith("/"):
            bad(path, f"{p.get('command')}: command must start with /")
        if p.get("command") in commands:
            bad(path, f"{p.get('command')}: duplicate command")
        commands.add(p.get("command"))
    return len(data)


if __name__ == "__main__":
    skills = check_skills()
    functions = check_python("functions", ("Filter", "Pipe", "Action"))
    tools = check_python("tools", ("Tools",))
    check_scripts()
    prompts = check_prompts()
    for line in problems:
        print("FAIL ", line)
    print(f"{len(skills)} skills, {len(functions)} functions, {len(tools)} tools, {prompts} prompts; {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
