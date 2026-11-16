"""Name-read rule (study 2, finer proof rule).

A module-level change in a library module no longer forces every test that loaded the module to rerun.
Instead the change is reduced to the *names* whose value it changes, those names are propagated through
module-level code of every loaded repository module (which runs once, at import), and a test reruns only
when code it executed refers to one of those names.

Per changed module, ``module_change(old, new, special, hooks, path)`` returns:

* ``hard``: reasons the change cannot be reduced to names (all tests that loaded the module rerun):
  - a module-level or class-level statement with possible side effects changed (expression statement,
    assignment to an attribute or subscript, a call to a function that is not on the pure list);
  - a decorator that is not on the pure list changed, was added or removed;
  - a class header (bases, metaclass, keywords, decorators) changed;
  - the body of a *special* class changed (metaclass other than type/ABCMeta, a base with
    ``__init_subclass__``: user code runs over the class body when the class is created);
  - a class was added whose bases name a class that hooks subclass creation;
  - a dunder name (implicitly read by the interpreter) was bound, changed or removed, ``__all__``
    included;
  - a module-level compound statement (if/try/with/for/while) changed, except ``if TYPE_CHECKING:``;
  - the file does not parse.
* ``qual``: {name} module-level bindings of this module whose value changed (added, removed, changed);
* ``attrs``: attribute names whose value changed on some object (class attributes and module globals,
  which other modules reach as ``module.name``);
* ``doc``: a docstring changed (doctests of that file rerun; readers of ``__doc__`` rerun).

``propagate`` then walks the module-level code of all loaded modules: a statement that refers to a changed
name binds changed names itself, or is hard when it can have side effects. A function whose body refers to a
changed name makes module-level calls to it changed as well (transitively).
"""

from __future__ import annotations

import ast
from functools import lru_cache

PURE_CALLS = {
    "getLogger", "TypeVar", "ParamSpec", "TypeVarTuple", "NewType", "compile", "frozenset", "set", "dict", "list",
    "tuple", "namedtuple", "partial", "object", "property", "staticmethod", "classmethod", "cast", "str", "int",
    "float", "bool", "bytes", "len", "sorted", "sum", "min", "max", "range", "enumerate", "zip", "map", "filter",
    "isinstance", "issubclass", "getattr", "hasattr", "escape", "join", "Path", "PurePath", "get", "field",
    "Field", "ib", "attrib", "deque", "OrderedDict", "defaultdict", "Counter", "Enum", "IntEnum", "StrEnum",
    "Flag", "IntFlag", "auto", "Decimal", "Fraction", "datetime", "date", "time", "timedelta", "timezone",
    "MappingProxyType", "Literal", "Union", "Optional", "Annotated", "Callable", "TypeAlias", "dataclass",
    "total_ordering", "lru_cache", "cache", "wraps", "reduce", "chain", "repeat", "count", "itemgetter",
    "attrgetter", "methodcaller", "abspath", "dirname", "basename", "realpath", "normpath", "splitext",
    "format", "upper", "lower", "strip", "split", "replace", "encode", "decode", "keys", "values", "items",
    "fromkeys", "copy", "union", "intersection", "difference", "getenv", "version_info", "platform",
    "python_version", "Pattern", "Match", "Lock", "RLock", "local", "WeakKeyDictionary", "WeakValueDictionary",
    "WeakSet", "ref", "count", "ord", "chr", "hex", "repr", "type", "slice", "iter", "next", "reversed",
    "any", "all", "abs", "round", "divmod", "pow", "hash", "id", "vars", "callable", "super", "NamedTuple",
    "TypedDict", "Protocol", "Generic", "overload", "final", "override", "runtime_checkable", "deprecated",
}
PURE_DECORATORS = {
    "property", "staticmethod", "classmethod", "cached_property", "abstractmethod", "abstractproperty",
    "overload", "override", "final", "wraps", "lru_cache", "cache", "setter", "getter", "deleter",
    "runtime_checkable", "deprecated", "total_ordering", "no_type_check", "contextmanager",
    "asynccontextmanager", "singledispatchmethod",
}
IMPLICIT_OK = {"__doc__", "__version__", "__author__", "__license__", "__copyright__", "__email__", "__url__",
               "__title__", "__description__", "__status__", "__maintainer__", "__credits__", "__date__"}


def _callee(node) -> str:
    f = node.func
    while isinstance(f, ast.Call):
        f = f.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _impure_call(node) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and _callee(n) not in PURE_CALLS:
            return True
        if isinstance(n, (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)):
            return True
    return False


def _deco_name(d) -> str:
    while isinstance(d, ast.Call):
        d = d.func
    if isinstance(d, ast.Attribute):
        return d.attr
    if isinstance(d, ast.Name):
        return d.id
    return "?"


def _pure_decos(decos) -> bool:
    return all(_deco_name(d) in PURE_DECORATORS for d in decos)


def _is_doc(node) -> bool:
    return isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
        and isinstance(node.value.value, str)


def _dunder(n: str) -> bool:
    return n.startswith("__") and n.endswith("__") and n not in IMPLICIT_OK


def _binds(stmt) -> set:
    out = set()
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    out.add(n.id)
    elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
        for a in stmt.names:
            out.add((a.asname or a.name).split(".")[0])
    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        out.add(stmt.name)
    elif hasattr(ast, "TypeAlias") and isinstance(stmt, ast.TypeAlias):
        out.add(stmt.name.id)
    return out


def _side_effect(stmt) -> str | None:
    """Why a module/class-level statement can act beyond the names it binds, or None."""
    if isinstance(stmt, ast.Expr):
        return None if _is_doc(stmt) else "expression statement"
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, (ast.Attribute, ast.Subscript)):
                    return "assignment to attribute/subscript"
        if stmt.value is not None and _impure_call(stmt.value):
            return "call in assignment"
        return None
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        if isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names):
            return "star import"
        return None
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if not _pure_decos(stmt.decorator_list):
            return "decorator"
        for d in stmt.args.defaults + [x for x in stmt.args.kw_defaults if x is not None]:
            if _impure_call(d):
                return "call in default"
        return None
    if isinstance(stmt, ast.ClassDef):
        return "class"  # handled by the caller
    if hasattr(ast, "TypeAlias") and isinstance(stmt, ast.TypeAlias):
        return None
    if isinstance(stmt, (ast.Pass, ast.Global, ast.Nonlocal)):
        return None
    if isinstance(stmt, ast.If) and _type_checking(stmt):
        return None
    return "compound statement"


def _type_checking(stmt) -> bool:
    t = stmt.test
    return (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING") or (
        isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING")


def _refs(node, skip_bodies=True):
    """(global names loaded, attribute names, ImportFrom (module, name) pairs) at module level of ``node``:
    function bodies are skipped (decorators, defaults and annotations are evaluated at definition time)."""
    names, attrs, froms, called = set(), set(), set(), set()
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and skip_bodies:
            if not isinstance(n, ast.Lambda):
                stack.extend(n.decorator_list)
                called.update(_deco_name(d) for d in n.decorator_list)
                stack.extend(a.annotation for a in n.args.posonlyargs + n.args.args + n.args.kwonlyargs
                             if a.annotation is not None)
                if n.returns is not None:
                    stack.append(n.returns)
                stack.extend(n.args.defaults)
                stack.extend(x for x in n.args.kw_defaults if x is not None)
            else:
                stack.extend(n.args.defaults)
            continue
        if isinstance(n, ast.Call):
            called.add(_callee(n))
        if isinstance(n, ast.ClassDef) and n is node:
            called.update(_deco_name(d) for d in n.decorator_list)
            called.update(_base_name(b) for b in n.bases)  # class creation runs base hooks
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            attrs.add(n.attr)
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                froms.add((n.module or "", n.level, a.name))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.isidentifier():
            attrs.add(n.value)
        stack.extend(ast.iter_child_nodes(n))
    return names, attrs, froms, called


@lru_cache(maxsize=8192)
def parse(text: str):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def _items(body, ns, out):
    """Flatten module and class bodies: {(kind, qualified name or statement position): node}."""
    stmts = []
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[("def", ns + node.name)] = node
        elif isinstance(node, ast.ClassDef):
            out[("class", ns + node.name)] = node
            _items(node.body, ns + node.name + ".", out)
        elif _is_doc(node) and not stmts:
            out[("doc", ns)] = node.value.value
        else:
            stmts.append(node)
    out[("stmts", ns)] = stmts


def module_change(old: str, new: str, special: set, hooks: set, path: str):
    to, tn = parse(old), parse(new)
    res = {"hard": [], "qual": set(), "attrs": set(), "doc": False}
    if to is None or tn is None:
        res["hard"].append("syntax")
        return res
    io, inn = {}, {}
    _items(to.body, "", io)
    _items(tn.body, "", inn)
    hook_names = {h.split("::", 1)[1].rsplit(".", 1)[-1] for h in hooks}

    def changed_name(ns, name):
        if _dunder(name):
            res["hard"].append(f"dunder {ns}{name}")
        if ns == "":
            res["qual"].add(name)
        else:
            cls = ns[:-1]
            res["qual"].add(cls.split(".")[0])
        res["attrs"].add(name)

    def special_class(ns):
        return ns and (path + "::" + ns[:-1]) in special

    for key in set(io) | set(inn):
        kind, q = key
        a, b = io.get(key), inn.get(key)
        ns, _, name = q.rpartition(".")
        ns = ns + "." if ns else ""
        if kind == "stmts":
            da = [ast.dump(x) for x in (a or [])]
            db = [ast.dump(x) for x in (b or [])]
            if da == db:
                continue
            if special_class(q):
                res["hard"].append(f"special class body {q}")
                continue
            sa, sb = set(da), set(db)
            for x in (a or []):
                if ast.dump(x) not in sb:
                    _stmt_change(x, q, res, changed_name)
            for x in (b or []):
                if ast.dump(x) not in sa:
                    _stmt_change(x, q, res, changed_name)
        elif kind == "doc":
            if a != b:
                res["doc"] = True
                res["attrs"].add("__doc__")
        elif kind == "class":
            if a is None or b is None:
                node = a or b
                if node.decorator_list or node.keywords:
                    res["hard"].append(f"class with decorator/keywords added or removed {q}")
                elif any(_base_name(x) in hook_names for x in node.bases):
                    res["hard"].append(f"subclass of a creation hook added or removed {q}")
                if special_class(q + "."):
                    res["hard"].append(f"special class removed {q}")
                changed_name(ns, name)
                for k in (io if a is not None else inn):
                    if k[0] in ("def", "class") and k[1].startswith(q + "."):
                        changed_name(q + ".", k[1][len(q) + 1:].split(".")[0])
            else:
                ha = ast.dump(ast.Module(body=a.bases + [k.value for k in a.keywords] + a.decorator_list, type_ignores=[]))
                hb = ast.dump(ast.Module(body=b.bases + [k.value for k in b.keywords] + b.decorator_list, type_ignores=[]))
                if ha != hb or [k.arg for k in a.keywords] != [k.arg for k in b.keywords]:
                    res["hard"].append(f"class header {q}")
        elif kind == "def":
            if a is None or b is None:
                node = a or b
                if special_class(ns):
                    res["hard"].append(f"method added/removed in special class {q}")
                if not _pure_decos(node.decorator_list):
                    res["hard"].append(f"decorated def added/removed {q}")
                changed_name(ns, name)
            else:
                hdr_a = ast.dump(ast.Module(body=list(a.decorator_list), type_ignores=[]))
                hdr_b = ast.dump(ast.Module(body=list(b.decorator_list), type_ignores=[]))
                if hdr_a != hdr_b:
                    if not (_pure_decos(a.decorator_list) and _pure_decos(b.decorator_list)):
                        res["hard"].append(f"decorator {q}")
                    changed_name(ns, name)
                sig_a = ast.dump(a.args) + ast.dump(a.returns) if a.returns else ast.dump(a.args)
                sig_b = ast.dump(b.args) + ast.dump(b.returns) if b.returns else ast.dump(b.args)
                if sig_a != sig_b:
                    # defaults and annotations live on the function object: callers and introspection
                    changed_name(ns, name)
                    res["attrs"].update({"__defaults__", "__kwdefaults__", "__annotations__", "__signature__",
                                         "signature", "get_type_hints", "getfullargspec", "__annotate__"})
                    if special_class(ns):
                        res["hard"].append(f"signature in special class {q}")
                da = a.body[0].value.value if a.body and _is_doc(a.body[0]) else None
                db = b.body[0].value.value if b.body and _is_doc(b.body[0]) else None
                if da != db:
                    res["doc"] = True
                    res["attrs"].add("__doc__")
    return res


def _base_name(x) -> str:
    if isinstance(x, ast.Attribute):
        return x.attr
    if isinstance(x, ast.Name):
        return x.id
    if isinstance(x, ast.Subscript):
        return _base_name(x.value)
    return "?"


def _stmt_change(stmt, ns, res, changed_name):
    why = _side_effect(stmt)
    if why == "compound statement" and isinstance(stmt, ast.If) and _type_checking(stmt):
        return
    if why:
        res["hard"].append(f"{why} in {ns or '<module>'}")
        return
    if isinstance(stmt, ast.If) and _type_checking(stmt):
        return
    for n in _binds(stmt):
        changed_name(ns + "." if ns else "", n)
    if isinstance(stmt, (ast.AnnAssign,)) or (isinstance(stmt, ast.Assign) and False):
        res["attrs"].update({"__annotations__", "__annotate__", "get_type_hints"})


def module_level_statements(tree):
    """[(scope, stmt)] for module and class bodies, recursively; function bodies excluded."""
    out = []

    def walk(body, scope):
        for n in body:
            out.append((scope, n))
            if isinstance(n, ast.ClassDef):
                walk(n.body, scope + n.name + ".")
            elif isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for f in ("body", "orelse", "finalbody"):
                    walk(getattr(n, f, []) or [], scope)
                for h in getattr(n, "handlers", []) or []:
                    walk(h.body, scope)
    walk(tree.body, "")
    return out


def functions(tree):
    """[(qualname, node)] for functions reachable without entering a function body."""
    out = []
    for scope, n in module_level_statements(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((scope + n.name, n))
    return out


def body_refs(fn):
    names, attrs = set(), set()
    for st in fn.body:
        for n in ast.walk(st):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                attrs.add(n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.isidentifier():
                attrs.add(n.value)
    return names, attrs


def module_name(path: str) -> str:
    p = path[:-3] if path.endswith(".py") else path
    parts = p.split("/")
    if parts and parts[0] in ("src", "lib"):
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def propagate(seeds: dict, sources: dict):
    """seeds: {path: module_change result}; sources: {path: text} of every loaded repository module (new
    commit). Returns (qual {(path, name)}, attrs set, hard {path: [reasons]})."""
    qual = {(p, n) for p, r in seeds.items() for n in r["qual"]}
    attrs = set().union(*[r["attrs"] for r in seeds.values()]) if seeds else set()
    hard = {}
    by_mod = {module_name(p): p for p in sources}
    trees = {p: parse(t) for p, t in sources.items()}
    stmts = {p: module_level_statements(t) for p, t in trees.items() if t is not None}
    funcs = {p: [(q, body_refs(fn)) for q, fn in functions(t)] for p, t in trees.items() if t is not None}
    refs_cache = {}
    derived = set()  # (path, function qualname) whose body refers to a changed name
    derived_names = set()
    for _ in range(50):
        grew = False
        for p, fl in funcs.items():
            for q, (nm, at) in fl:
                if (p, q) in derived:
                    continue
                if (nm & {n for (pp, n) in qual if pp == p}) or (nm & derived_names) or (at & attrs) \
                        or (at & derived_names):
                    derived.add((p, q))
                    derived_names.add(q.split(".")[-1])
                    if "." in q:  # a method: instantiating or subclassing its class can run it
                        derived_names.add(q.split(".")[0])
                    grew = True
        for p, sl in stmts.items():
            qp = {n for (pp, n) in qual if pp == p}
            for k, (scope, st) in enumerate(sl):
                if isinstance(st, (ast.If, ast.Try, ast.With, ast.For, ast.While)) and not \
                        (isinstance(st, ast.If) and _type_checking(st)):
                    key_refs = refs_cache.get((p, k))
                    if key_refs is None:
                        key_refs = refs_cache[(p, k)] = _refs(ast.Module(body=[st], type_ignores=[]))
                else:
                    key_refs = refs_cache.get((p, k))
                    if key_refs is None:
                        key_refs = refs_cache[(p, k)] = _refs(st)
                names, at, froms, called = key_refs
                hit = bool(names & qp) or bool(at & attrs) or bool(called & derived_names)
                if not hit:
                    for mod, level, n in froms:
                        src = by_mod.get(_resolve(mod, level, p))
                        if src is not None and ((src, n) in qual or (n == "*" and any(pp == src for pp, _ in qual))):
                            hit = True
                            break
                if not hit:
                    continue
                why = _side_effect(st)
                if isinstance(st, ast.ClassDef):
                    why = None if _pure_decos(st.decorator_list) else "decorated class"
                if why and why != "compound statement":
                    hard.setdefault(p, []).append(f"{why} refers to a changed name")
                    continue
                new = set()
                if isinstance(st, ast.ClassDef):
                    new.add(st.name)
                else:
                    new = _binds(st)
                    if why == "compound statement":
                        for sub in ast.walk(st):
                            if isinstance(sub, ast.stmt) and sub is not st:
                                new |= _binds(sub)
                if scope:
                    new.add(scope.split(".")[0])
                for n in new:
                    if (p, n) not in qual:
                        qual.add((p, n))
                        attrs.add(n)
                        grew = True
        if not grew:
            break
    return qual, attrs, hard


def _resolve(mod: str, level: int, path: str) -> str:
    if not level:
        return mod
    base = module_name(path).split(".")
    if not path.endswith("__init__.py"):
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join(base + ([mod] if mod else []))
