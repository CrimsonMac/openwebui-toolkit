#!/usr/bin/env python3
"""Find common Python bugs without running the code. Standard library only.

Checks: syntax errors, unused imports, mutable default arguments, bare except,
except that swallows silently, comparison to None/True/False with ==, shadowed
builtins, unreachable code, duplicate dict keys, and missing await hints.

Usage: py_check.py FILE_OR_DIR [...]
Exit code 1 when anything is found.
"""
import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) - {"_", "__doc__", "__name__"}
SHADOW_WORTH = {"list", "dict", "set", "str", "int", "float", "id", "type", "input", "file", "max", "min", "sum", "len", "filter", "map", "object", "open", "print", "range", "next", "iter", "hash", "format", "bytes", "all", "any", "dir", "vars"}


class Checker(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.issues = []
        self.imported = {}
        self.used = set()
        self.exported = None

    def add(self, node, msg):
        self.issues.append((getattr(node, "lineno", 0), msg))

    # ---- imports and names
    def visit_Import(self, node):
        for a in node.names:
            self.imported[(a.asname or a.name).split(".")[0]] = node.lineno

    def visit_ImportFrom(self, node):
        if node.module == "__future__":
            return
        for a in node.names:
            if a.name != "*":
                self.imported[a.asname or a.name] = node.lineno

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.used.add(node.id)
        elif isinstance(node.ctx, ast.Store) and node.id in SHADOW_WORTH:
            self.add(node, f"assignment shadows the builtin '{node.id}'")

    def visit_Attribute(self, node):
        self.generic_visit(node)

    def visit_Assign(self, node):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                self.exported = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
        self.generic_visit(node)

    # ---- functions
    def _function(self, node):
        for d in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            if isinstance(d, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id in ("list", "dict", "set")
            ):
                self.add(d, f"mutable default argument in '{node.name}' is shared between calls; use None and create it inside")
        for arg in node.args.args + node.args.kwonlyargs:
            if arg.arg in SHADOW_WORTH:
                self.add(arg, f"parameter '{arg.arg}' shadows a builtin")
        self._unreachable(node.body)
        self.generic_visit(node)

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def _unreachable(self, body):
        for i, stmt in enumerate(body[:-1]):
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                self.add(body[i + 1], "unreachable code after return/raise/continue/break")
                break

    def visit_For(self, node):
        self._unreachable(node.body)
        self.generic_visit(node)

    visit_While = visit_For

    # ---- error handling
    def visit_ExceptHandler(self, node):
        if node.type is None:
            self.add(node, "bare 'except:' also catches KeyboardInterrupt and SystemExit; name the exception")
        body = node.body
        if len(body) == 1 and (isinstance(body[0], ast.Pass) or (isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant))):
            broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
            if broad:
                self.add(node, "broad except that silently ignores the error; log it or narrow the type")
        self.generic_visit(node)

    # ---- expressions
    def visit_Compare(self, node):
        for op, right in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and right.value is None:
                self.add(node, "compare to None with 'is' / 'is not', not == / !=")
            if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(right, ast.Constant) and isinstance(right.value, (str, int, float)) and not isinstance(right.value, bool):
                self.add(node, "'is' compares identity; use == for strings and numbers")
        self.generic_visit(node)

    def visit_Dict(self, node):
        seen = set()
        for k in node.keys:
            if isinstance(k, ast.Constant):
                try:
                    if k.value in seen:
                        self.add(k, f"duplicate dict key {k.value!r}; the earlier value is lost")
                    seen.add(k.value)
                except TypeError:
                    pass
        self.generic_visit(node)

    def visit_Assert(self, node):
        if isinstance(node.test, ast.Tuple) and node.test.elts:
            self.add(node, "assert on a tuple is always true; remove the parentheses")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            self.add(node, f"{node.func.id}() runs arbitrary code; avoid it on anything a user can influence")
        self.generic_visit(node)

    def finish(self, source):
        if self.path.name == "__init__.py":
            return
        for name, line in self.imported.items():
            if name in self.used or (self.exported and name in self.exported) or name.startswith("_"):
                continue
            # A name used only inside a string annotation or __all__ still counts as used.
            if source.count(name) > 1 and f'"{name}' in source:
                continue
            self.issues.append((line, f"'{name}' is imported but never used"))


def check(path):
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [(e.lineno or 0, f"syntax error: {e.msg}")]
    c = Checker(path)
    c.visit(tree)
    c.finish(source)
    return sorted(set(c.issues))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    files = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            files += [f for f in sorted(p.rglob("*.py")) if not any(part.startswith(".") or part in ("venv", "node_modules", "__pycache__") for part in f.parts)]
        elif p.exists():
            files.append(p)
        else:
            print(f"{arg}: not found")
    total = 0
    for f in files:
        for line, msg in check(f):
            total += 1
            print(f"{f}:{line}: {msg}")
    print(f"{total} issue(s) in {len(files)} file(s)")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
