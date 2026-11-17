"""Python source comparison for the function-level rules.

* ``skeleton(text)``: the module AST with every function body removed (docstrings, signatures,
  defaults, decorators, class bodies and module statements kept). Equal skeletons mean only function
  bodies changed.
* ``defs(text)``: {qualname: dump} for every function reachable without entering a function body
  (module level, class bodies, module-level if/try/with blocks), qualnames as Python builds them
  (``Cls.meth``).
"""

from __future__ import annotations

import ast
from functools import lru_cache


class _Strip(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        doc = node.body[0] if node.body and isinstance(node.body[0], ast.Expr) and isinstance(
            getattr(node.body[0], "value", None), ast.Constant) and isinstance(node.body[0].value.value, str) else None
        node.body = [doc] if doc else []
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


@lru_cache(maxsize=4096)
def skeleton(text: str) -> str | None:
    try:
        return ast.dump(_Strip().visit(ast.parse(text)))
    except (SyntaxError, ValueError, RecursionError):
        return None


@lru_cache(maxsize=4096)
def defs(text: str) -> dict | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    out = {}

    def walk(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + node.name
                out[q] = out.get(q, "") + ast.dump(node)
            elif isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + ".")
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.While)) or (
                    hasattr(ast, "TryStar") and isinstance(node, ast.TryStar)):
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(node, field, []) or [], prefix)
                for h in getattr(node, "handlers", []) or []:
                    walk(h.body, prefix)
            elif hasattr(ast, "Match") and isinstance(node, ast.Match):
                for c in node.cases:
                    walk(c.body, prefix)
    walk(tree.body, "")
    return out


def top_qualname(q: str) -> str:
    """``f.<locals>.g`` -> ``f``; ``C.m.<locals>.<lambda>`` -> ``C.m``."""
    k = q.find(".<locals>")
    return q if k < 0 else q[:k]


def changed_functions(old: str, new: str):
    """(skeleton_equal, set of qualnames whose definition changed or vanished, parse_ok)."""
    so, sn = skeleton(old), skeleton(new)
    if so is None or sn is None:
        return False, set(), False
    do, dn = defs(old), defs(new)
    ch = {q for q, d in do.items() if dn.get(q) != d}
    return so == sn, ch, True
