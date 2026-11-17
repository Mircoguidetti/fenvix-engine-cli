"""Facts about one version of a source file, for the cache with proof.

* **units**: one per outermost function (methods of classes included, nested
  functions belong to their enclosing unit), with the line range of its body
  and the digest of its syntax tree. A line a test executed inside a unit body
  makes the unit a dependency of the test.
* **skeleton**: digest of the module with every function body removed
  (docstrings, signatures, defaults, decorators, class bodies, assignments,
  imports kept). Module-level state is built from it at import time and can be
  read by a test without executing a line of the module, so it is a dependency
  of every test that had the module loaded (the "import-time guard" of the
  cache-skip study).
* **hooks**: digest of the pytest hook surface of a conftest (top-level
  ``pytest_*`` functions and ``pytest_plugins``): hooks can act on every test.
* **imports**: absolute names of the modules the file imports (any scope).

Syntax trees are compared with :func:`ast.dump`, so comments and formatting do
not count. A file that is not valid Python (a template compiled to code, ...)
has no units and its skeleton is its content digest: any change counts.
"""

from __future__ import annotations

import ast

from . import _core

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _digest(text: str) -> str:
    return _core.digest(text.encode("utf-8", "surrogateescape"))


def _is_doc(node) -> bool:
    return isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
        and isinstance(node.value.value, str)


class _Skeleton(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)  # decorators, defaults, annotations
        node.body = [node.body[0]] if node.body and _is_doc(node.body[0]) else []
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


def _units(body, prefix: str, out: list, seen: dict) -> None:
    for node in body:
        if isinstance(node, _FUNCS):
            q = prefix + node.name
            n = seen.get(q, 0)
            seen[q] = n + 1
            if n:
                q = f"{q}#{n}"
            first = node.body[0]
            start = first.lineno
            out.append((q, start, node.end_lineno or start, _digest(ast.dump(node))))
        elif isinstance(node, ast.ClassDef):
            _units(node.body, prefix + node.name + ".", out, seen)
        else:
            # functions defined under if/try/with/for/while at module or class level
            for field in ("body", "orelse", "finalbody", "handlers"):
                sub = getattr(node, field, None)
                if isinstance(sub, list) and sub:
                    if field == "handlers":
                        for h in sub:
                            _units(h.body, prefix, out, seen)
                    else:
                        _units(sub, prefix, out, seen)
            for case in getattr(node, "cases", ()) or ():
                _units(case.body, prefix, out, seen)


def _hooks(tree) -> str:
    parts = []
    for node in tree.body:
        if isinstance(node, _FUNCS) and node.name.startswith("pytest_"):
            parts.append(ast.dump(node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in targets):
                parts.append(ast.dump(node))
    return _digest("\n".join(parts))


def _imports(tree, modname: str | None, is_pkg: bool) -> list:
    out = set()
    pkg = (modname or "") if is_pkg else (modname or "").rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = pkg.split(".") if pkg else []
                if node.level - 1:
                    parts = parts[: len(parts) - (node.level - 1)] if node.level - 1 <= len(parts) else []
                base = ".".join([*parts, *([base] if base else [])])
            if base:
                out.add(base)
            for a in node.names:
                if a.name != "*":
                    out.add(f"{base}.{a.name}" if base else a.name)
    return sorted(out)


def facts(text: str, content: str, modname: str | None = None, is_pkg: bool = False):
    """``(skeleton, hooks, units, imports)`` of a source text whose bytes digest is ``content``."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return content, content, [], []
    units: list = []
    _units(tree.body, "", units, {})
    units.sort(key=lambda u: u[1])
    hooks = _hooks(tree)
    imports = _imports(tree, modname, is_pkg)
    skeleton = _digest(ast.dump(_Skeleton().visit(tree)))
    return skeleton, hooks, units, imports


def read_facts(path: str, content: str, modname: str | None = None, is_pkg: bool = False):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return content, content, [], []
    return facts(text, content, modname, is_pkg)
