#!/usr/bin/env python3
"""Cache-skip study, analysis stage.

For every transition prev -> cur between consecutive captured commits, decide
for each test of ``cur`` whether its result at ``prev`` could be reused *with
proof*, i.e. nothing it depends on changed, using the dependency map captured
at ``prev`` (fresh map) and, separately, the map captured at the last refresh
point (every ``--refresh`` commits: stale map).

Rules shared by every variant (a test must run when any holds):

* it did not exist at ``prev`` (new or renamed test);
* it is not deterministic under ``--det``: ``fingerprint_covered`` is not
  ``True`` in ``harness/results/mixed/<repo>.csv`` (tests missing there count
  as non-deterministic);
* it spawned a subprocess or connected an inet socket (dependencies invisible);
* a configuration file changed (``strict``: lockfiles, requirements,
  pyproject.toml, setup.py, setup.cfg, conftest.py, pytest.ini, tox.ini,
  noxfile.py, CI files; ``relaxed``: only a changed installed environment, a
  changed pytest configuration section, or a changed conftest.py);
* a non-Python file it opened changed, or a directory it listed gained or lost
  an entry.

Variants (Python source dependencies):

* ``closure``: any change to a repository module that was loaded when the test
  ran (``sys.modules``) or that it executed (Ekstazi-like, coarsest);
* ``file``: any change to a file the test executed (coverage, file level);
* ``line``: a change touching a statement the test executed (coverage, line
  level; changed lines are mapped to the statements that contain them);
* ``file+guard`` / ``line+guard``: as above, plus the *import-time guard*: a
  change to module-level code (the module with function bodies removed, compared
  as an AST; docstrings, signatures, defaults, decorators, class bodies,
  constants) or to lines executed at import / collection time, in a module the
  test had loaded, forces the test to run. Coverage alone cannot see a test that
  reads a constant, a class attribute or a regex table without executing a line
  of that module; the guard covers that case.

Output: ``<out>/<repo>.json`` (per transition and summary).
"""

from __future__ import annotations

import argparse
import ast
import csv
import difflib
import fnmatch
import gzip
import json
import pickle
import statistics
import subprocess
import sys
import tomllib
from configparser import ConfigParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import names as namerule  # noqa: E402
VARIANTS = ("closure", "file", "line", "file+guard", "line+guard", "file+nameguard", "line+nameguard", "line+names")
CONFIG_MODES = ("strict", "relaxed")

DEP_BASENAMES = {"uv.lock", "poetry.lock", "Pipfile", "Pipfile.lock", "pdm.lock", "pylock.toml"}
PY_CONFIG_BASENAMES = {"pyproject.toml", "setup.py", "setup.cfg"}
PYTEST_CONFIG_BASENAMES = {"pytest.ini", "tox.ini", "conftest.py", "noxfile.py", ".pytest.ini"}
CI_PATTERNS = (".github/workflows/*", ".gitlab-ci.yml", ".circleci/*", "azure-pipelines.yml", ".travis.yml",
               "appveyor.yml", ".github/actions/*")


def git(src, *args, check=True) -> str:
    return subprocess.run(["git", *args], cwd=src, capture_output=True, text=True, check=check,
                          errors="replace").stdout


def show(src, sha, path) -> str | None:
    p = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=src, capture_output=True, text=True, errors="replace")
    return p.stdout if p.returncode == 0 else None


def config_kind(path: str) -> str | None:
    base = path.rsplit("/", 1)[-1]
    if base in DEP_BASENAMES or (base.startswith(("requirements", "constraints")) and base.endswith((".txt", ".in"))) \
            or path.startswith("requirements/"):
        return "deps"
    if base in PY_CONFIG_BASENAMES and "/" not in path:
        return "pyproject"
    if base in PYTEST_CONFIG_BASENAMES:
        return "pytest"
    if any(fnmatch.fnmatch(path, p) for p in CI_PATTERNS):
        return "ci"
    return None


def pytest_section(text: str | None, path: str):
    """The pytest-relevant part of a config file (for the relaxed config rule)."""
    if text is None:
        return None
    base = path.rsplit("/", 1)[-1]
    try:
        if base == "pyproject.toml":
            d = tomllib.loads(text)
            return json.dumps(d.get("tool", {}).get("pytest"), sort_keys=True)
        if base in ("setup.cfg", "tox.ini"):
            cp = ConfigParser(interpolation=None)
            cp.read_string(text)
            return json.dumps({s: dict(cp[s]) for s in cp.sections() if s in ("tool:pytest", "pytest")},
                              sort_keys=True)
    except Exception:
        return text
    return text


# ---------------------------------------------------------------------------
# Python source analysis
class _Skeleton(ast.NodeTransformer):
    def _strip(self, node):
        doc = node.body[0] if node.body and isinstance(node.body[0], ast.Expr) and isinstance(
            getattr(node.body[0], "value", None), ast.Constant) and isinstance(node.body[0].value.value, str) else None
        node.body = [doc] if doc else []
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)  # decorators, defaults, annotations
        return self._strip(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def skeleton(text: str) -> str | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    return ast.dump(_Skeleton().visit(tree))


def ast_dump(text: str) -> str | None:
    try:
        return ast.dump(ast.parse(text))
    except SyntaxError:
        return None


def stmt_index(text: str):
    """[(start, end, report_line)] for every statement: a changed line L maps to report_line of each
    statement whose own span contains L (simple statements: whole span; compound: header only)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        start, end = node.lineno, node.end_lineno or node.lineno
        decos = getattr(node, "decorator_list", None)
        if decos:
            start = min([start] + [d.lineno for d in decos])
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.stmt):
            end = max(node.lineno, body[0].lineno - 1)
        spans.append((start, end, node.lineno))
    return spans


def _code_line(text: str) -> bool:
    t = text.strip()
    return bool(t) and not t.startswith("#")


def changed_old_lines(old: list[str], new: list[str], full_spans=None) -> tuple[set, list]:
    """Old-side line numbers that were replaced/deleted, plus, for each insertion, what control must have
    executed to reach the inserted code: the previous and next code lines (blank and comment lines skipped)
    and the first line of every statement that encloses the previous code line (a loop or ``if`` whose nested
    block ends just before the insertion). Returns (lines, opcodes)."""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    ops = sm.get_opcodes()
    out = set()
    for tag, i1, i2, _j1, _j2 in ops:
        if tag in ("replace", "delete"):
            out.update(range(i1 + 1, i2 + 1))
        if tag in ("insert", "replace"):
            p = i1  # 1-based number of the old line just before the insertion point
            while p >= 1 and not _code_line(old[p - 1]):
                p -= 1
            q = (i2 if tag == "replace" else i1) + 1
            while q <= len(old) and not _code_line(old[q - 1]):
                q += 1
            if p >= 1:
                out.add(p)
                for a, b in full_spans or ():
                    if a <= p <= b:
                        out.add(a)
            if q <= len(old):
                out.add(q)
    return out, ops


def full_spans(text: str):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    return [(n.lineno, n.end_lineno or n.lineno) for n in ast.walk(tree) if isinstance(n, ast.stmt)]


def map_lines(ops, lines) -> set:
    """Map old line numbers to new ones through equal blocks; lines in changed regions are dropped."""
    out = set()
    eq = [(i1, i2, j1) for tag, i1, i2, j1, _ in ops if tag == "equal"]
    for ln in lines:
        k = ln - 1
        for i1, i2, j1 in eq:
            if i1 <= k < i2:
                out.add(j1 + (k - i1) + 1)
                break
    return out



def _is_doc(node) -> bool:
    return isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
        and isinstance(node.value.value, str)


class _NoAnn(ast.NodeTransformer):
    def visit_arg(self, node):
        node.annotation = None
        return node


def _items(body, ns, out):
    if body and _is_doc(body[0]):
        out[("doc", ns)] = body[0].value.value
        body = body[1:]
    stmts = []
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[("def", ns + node.name)] = node
        elif isinstance(node, ast.ClassDef):
            out[("class", ns + node.name)] = node
            _items(node.body, ns + node.name + ".", out)
        else:
            stmts.append(ast.dump(node))
    out[("stmts", ns)] = stmts


def _fparts(n):
    hard = ast.dump(ast.Module(body=list(n.decorator_list) + ([n.returns] if n.returns else []) + [
        a.annotation for a in (n.args.posonlyargs + n.args.args + n.args.kwonlyargs
                               + [x for x in (n.args.vararg, n.args.kwarg) if x]) if a.annotation],
        type_ignores=[])) + type(n).__name__
    soft = ast.dump(_NoAnn().visit(ast.parse(ast.unparse(n.args).join(("def f(", "): pass")))))
    doc = n.body[0].value.value if n.body and _is_doc(n.body[0]) else None
    return hard, soft, doc


def name_level(old: str, new: str):
    """Name-level comparison of the module-level structure.

    Returns (hard, soft_lines, doc_changed, why):
    * hard: a change whose effect is not confined to callers of a function: module or class body statements
      (assignments, imports, class attributes, ``__all__``...), class headers, decorators, annotations, added
      decorated functions, added methods (they can override), added module-level names the old module referenced;
    * soft_lines: old line span of every function whose argument list / defaults changed (only callers, who
      execute its body, can observe that);
    * doc_changed: a docstring changed (doctests of the module, introspection).
    """
    try:
        to, tn = ast.parse(old), ast.parse(new)
    except SyntaxError:
        return True, set(), True, "syntax"
    io, inn = {}, {}
    _items(to.body, "", io)
    _items(tn.body, "", inn)
    soft, doc, why = set(), False, []
    old_names = {n.id for n in ast.walk(to) if isinstance(n, ast.Name)} | {
        a.name for n in ast.walk(to) if isinstance(n, ast.ImportFrom) for a in n.names if a.name == "*"}
    for key in set(io) | set(inn):
        kind, q = key
        a, b = io.get(key), inn.get(key)
        if kind == "stmts":
            if (a or []) != (b or []):
                why.append("stmts:" + (q or "<module>"))
        elif kind == "doc":
            if a != b:
                doc = True
        elif kind == "class":
            if a is None or b is None:
                why.append(("added" if a is None else "removed") + " class " + q)
            else:
                ha = ast.dump(ast.Module(body=a.bases + [k.value for k in a.keywords] + a.decorator_list, type_ignores=[]))
                hb = ast.dump(ast.Module(body=b.bases + [k.value for k in b.keywords] + b.decorator_list, type_ignores=[]))
                if ha != hb or [k.arg for k in a.keywords] != [k.arg for k in b.keywords]:
                    why.append("class header " + q)
        elif kind == "def":
            if a is None:
                if b.decorator_list:
                    why.append("added decorated def " + q)
                elif "." in q:
                    why.append("added method " + q)
                elif q in old_names or "*" in old_names:
                    why.append("added def shadows a name " + q)
            elif b is not None:
                (ha, sa, da), (hb, sb, db) = _fparts(a), _fparts(b)
                if ha != hb:
                    why.append("def header " + q)
                elif sa != sb:
                    soft.update(range(a.lineno, (a.end_lineno or a.lineno) + 1))
                if da != db:
                    doc = True
            # removed def: its lines are changed lines, callers executed them
    return bool(why), soft, doc, ";".join(sorted(why))[:300]


class FileChange:
    __slots__ = ("path", "status", "lines", "stmt_lines", "module_level", "ast_equal", "ops", "hard", "soft_lines",
                 "doc_changed", "why", "body_lines", "import_lines")

    def __init__(self, path, status, old, new):
        self.path, self.status = path, status
        self.lines, self.stmt_lines, self.ops = set(), set(), None
        self.module_level, self.ast_equal = True, False
        self.hard, self.soft_lines, self.doc_changed, self.why = True, set(), True, status
        self.body_lines = None
        self.import_lines = None
        if status == "M" and old is not None and new is not None:
            ol, nl = old.splitlines(), new.splitlines()
            self.lines, self.ops = changed_old_lines(ol, nl, full_spans(old))
            spans = stmt_index(old)
            core = changed_old_lines(ol, nl)[0]  # without enclosing headers: for the import-time check

            def to_stmts(lines):
                st = set(lines)
                for ln in lines:
                    for s, e, rep in spans:
                        if s <= ln <= e:
                            st.add(rep)
                            st.add(s)
                return st
            if spans is not None:
                self.stmt_lines = to_stmts(self.lines)
                self.import_lines = to_stmts(core)
            else:
                self.stmt_lines = None  # unparsable: treat every executed line as hit
            so, sn = skeleton(old), skeleton(new)
            self.module_level = so is None or sn is None or so != sn
            self.ast_equal = so is not None and ast_dump(old) == ast_dump(new)
            self.hard, self.soft_lines, self.doc_changed, self.why = name_level(old, new)
            try:
                self.body_lines = set()
                for n in ast.walk(ast.parse(old)):
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                        b = n.body if isinstance(n.body, list) else [n.body]
                        self.body_lines.update(range(b[0].lineno, (n.end_lineno or b[0].lineno) + 1))
            except SyntaxError:
                self.body_lines = None
            if self.stmt_lines is not None:
                self.soft_lines = self.soft_lines | self.stmt_lines

    def hits(self, linesets, extra=False) -> bool:
        if self.status != "M" or self.stmt_lines is None:
            return True
        lines = self.soft_lines if extra else self.stmt_lines
        return any(not s.isdisjoint(lines) for s in linesets)


# ---------------------------------------------------------------------------
# Dependency map at one commit
class DepMap:
    def __init__(self, stem: Path):
        cap = json.loads(Path(str(stem) + ".cap.json").read_text())
        with gzip.open(str(stem) + ".cov.pkl.gz", "rb") as fh:
            cov = pickle.load(fh)
        self.files = cov["files"]
        blobs = [(self.files[fi], frozenset(lines)) for fi, lines in cov["blobs"]]
        ctx = {c: [blobs[b] for b in ids] for c, ids in cov["ctx"].items()}
        self.tests = {nid: rec for nid, rec in cap["tests"].items() if rec.get("idx", -1) >= 0}
        self.first_seen = cap.get("first_seen", {})
        nm = cap.get("names")
        self.has_names = nm is not None
        self.special = set(cap.get("marks", {}).get("special", []))
        self.hooks = set(cap.get("marks", {}).get("hooks", []))
        self.tmask = {}
        self.ident_codes = {}
        if nm:
            fixcodes = nm.get("fixtures", {})
            for k, row in enumerate(nm["codes"]):
                for j in row:
                    self.ident_codes.setdefault(nm["idents"][j], []).append(k)
            for nid, rec in cap["tests"].items():
                if rec.get("idx", -1) < 0:
                    continue
                codes = set(rec.get("codes", ()))
                for fx in rec.get("fixtures", ()):
                    codes.update(fixcodes.get(fx, ()))
                m = 0
                for k in codes:
                    m |= 1 << k
                self.tmask[nid] = m
        fs = cap.get("fs", {})
        spawn, net = cap.get("spawn", {}), cap.get("net", {})
        self.importtime: dict[str, set] = {}
        for c, bl in ctx.items():
            if c.startswith(("c|", "s|")) or c == "":
                for f, lines in bl:
                    self.importtime.setdefault(f, set()).update(lines)
        self.cov: dict[str, dict[str, list]] = {}
        self.run: dict[str, dict[str, list]] = {}  # lines executed while the test ran (no collection context)
        self.opens: dict[str, set] = {}
        self.lists: dict[str, set] = {}
        self.unprovable: dict[str, str] = {}
        self.inv: dict[str, set] = {}
        for nid, rec in self.tests.items():
            ctxs = ["t|" + nid, "c|" + nid.split("::")[0]] + rec.get("fixtures", [])
            per: dict[str, list] = {}
            run: dict[str, list] = {}
            op, li = set(), set()
            for c in ctxs:
                for f, lines in ctx.get(c, ()):
                    per.setdefault(f, []).append(lines)
                    if not c.startswith("c|"):
                        run.setdefault(f, []).append(lines)
                d = fs.get(c)
                if d:
                    op.update(d.get("open", ()))
                    li.update(d.get("list", ()))
            self.cov[nid] = per
            self.run[nid] = run
            self.opens[nid], self.lists[nid] = op, li
            for f in per:
                self.inv.setdefault(f, set()).add(nid)
            if spawn.get("t|" + nid) or any(spawn.get(c) for c in rec.get("fixtures", [])):
                self.unprovable[nid] = "subprocess"
            elif net.get("t|" + nid) or any(net.get(c) for c in rec.get("fixtures", [])):
                self.unprovable[nid] = "network"

    def loaded_before(self, f: str, nid: str) -> bool:
        fs = self.first_seen.get(f)
        return fs is not None and fs <= self.tests[nid]["idx"]

    def remap(self, file_ops: dict) -> "DepMap":
        """A copy whose line numbers are moved through ``file_ops`` {path: opcodes or None (deleted)}."""
        new = object.__new__(DepMap)
        new.__dict__.update(self.__dict__)
        cache = {}

        def mv(f, s):
            if f not in file_ops:
                return s
            key = (f, id(s))
            if key not in cache:
                ops = file_ops[f]
                cache[key] = frozenset() if ops is None else frozenset(map_lines(ops, s))
            return cache[key]

        new.cov = {nid: {f: [mv(f, s) for s in ls] for f, ls in per.items()} for nid, per in self.cov.items()}
        new.run = {nid: {f: [mv(f, s) for s in ls] for f, ls in per.items()} for nid, per in self.run.items()}
        new.importtime = {f: set(mv(f, frozenset(s))) for f, s in self.importtime.items()}
        return new


# ---------------------------------------------------------------------------
def load_det(repo: str) -> dict:
    p = ROOT / "harness" / "results" / "mixed" / f"{repo}.csv"
    if not p.exists():
        return {}
    return {r["nodeid"]: r["fingerprint_covered"] == "True" for r in csv.DictReader(p.open())}


def changes_between(src, a, b):
    out = []
    for line in git(src, "diff", "--no-renames", "--name-status", a, b).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append((parts[0][0], parts[-1]))
    return out


def listing_changes(src, a, b, changes) -> set:
    """Directories whose entry list differs between a and b."""
    ta = set(git(src, "ls-tree", "-r", "--name-only", a).splitlines())
    tb = set(git(src, "ls-tree", "-r", "--name-only", b).splitlines())

    def dirs(tree):
        d = {"."}
        for p in tree:
            parts = p.split("/")[:-1]
            for k in range(1, len(parts) + 1):
                d.add("/".join(parts[:k]))
        return d
    da, db = dirs(ta), dirs(tb)
    out = set()
    for st, p in changes:
        if st not in ("A", "D"):
            continue
        d = p.rsplit("/", 1)[0] if "/" in p else "."
        while True:
            out.add(d)
            if d == "." or (d in da and d in db):
                break
            d = d.rsplit("/", 1)[0] if "/" in d else "."
    return out


def decide(m: DepMap, nid: str, fcs: dict, data_changed: set, list_changed: set, variant: str,
           scope: dict | None = None, names_ctx: dict | None = None) -> str | None:
    """Reason the test must run, or None if skippable (given shared rules already passed)."""
    if not m.opens[nid].isdisjoint(data_changed):
        return "data-file"
    if not m.lists[nid].isdisjoint(list_changed):
        return "dir-listing"
    per = m.cov[nid]
    if variant.endswith("+names") and names_ctx:
        if not m.has_names:
            return "names-missing"
        for p in names_ctx["hard_loaded"]:
            if p in per or m.loaded_before(p, nid):
                return "names-hard"
        if nid.split("::")[0] in names_ctx["test_modules_hit"]:
            return "names-testmodule"
    guard = variant.endswith("+guard")
    nameguard = variant.endswith("+nameguard")
    names = variant.endswith("+names")
    for f, fc in fcs.items():
        executed = f in per
        if variant == "closure":
            if executed or (m.loaded_before(f, nid) and not (scope and f in scope and nid.split("::")[0] not in scope[f])):
                return "source"
            continue
        if executed:
            if variant.startswith("file") or fc.hits(per[f], extra=nameguard):
                return "source"
        if scope and f in scope and nid.split("::")[0] not in scope[f] and not executed:
            continue  # a test module is loaded by the collector: only its own tests and its importers depend on it
        if names and (executed or m.loaded_before(f, nid)):
            is_test_module = bool(scope and f in scope)
            if fc.status != "M":
                return "import-guard"
            if fc.module_level:
                if is_test_module:
                    return "import-guard"
                nr = (names_ctx or {}).get("files", {}).get(f)
                if nr is None or nr["hard"]:
                    return "names-hard"
                if (names_ctx or {}).get("mask", 0) & m.tmask.get(nid, -1):
                    return "names-read"
                if nr["doc"] and nid.split("::")[0] == f:
                    return "docstring"
            it = m.importtime.get(f)
            if it:
                if fc.stmt_lines is None or fc.body_lines is None:
                    return "import-guard"
                if not it.isdisjoint(fc.import_lines & fc.body_lines):
                    return "import-guard"
            continue
        if (guard or nameguard) and (executed or m.loaded_before(f, nid)):
            if fc.status != "M" or (fc.module_level if guard else fc.hard):
                return "import-guard"
            it = m.importtime.get(f)
            if it:
                if fc.stmt_lines is None or fc.body_lines is None:
                    return "import-guard"
                # module-level code is compared structurally above; this catches function bodies run at import
                lines = fc.import_lines & fc.body_lines
                if not it.isdisjoint(lines):
                    return "import-guard"
            if nameguard and fc.doc_changed and nid.split("::")[0] == f:
                return "docstring"
    return None


def analyze(repo: str, work: Path, refresh: int) -> dict:
    meta = json.loads((work / "meta.json").read_text())
    src = work / "src"
    caps = work / "caps"
    det = load_det(repo)
    steps = meta["steps"]
    stems = {}
    for st in steps:
        stem = caps / f"{st['i']:03d}-{st['sha'][:12]}"
        done = Path(str(stem) + ".done")
        if done.exists():
            st.update(json.loads(done.read_text()))
        if st.get("status") == "ok":
            stems[st["i"]] = stem
    det_local = {}
    for st in steps:
        if st["i"] in stems and Path(str(stems[st["i"]]) + ".det.json").exists():
            det_local[st["i"]] = json.loads(Path(str(stems[st["i"]]) + ".det.json").read_text())
    det_source_count: dict[str, int] = {}

    def is_det(nid, i_prev):
        if nid in det:
            return det[nid], "csv"
        order = sorted((r for r in det_local if r <= i_prev), reverse=True) + sorted(r for r in det_local if r > i_prev)
        for r in order:
            if nid in det_local[r]:
                return det_local[r][nid]["covered"], "det-check"
        return None, "unknown"

    maps: dict[int, DepMap] = {}

    def get_map(i):
        if i not in maps:
            maps[i] = DepMap(stems[i])
            keep = {i, i - 1, i - 2, ((i - 1) // refresh) * refresh, ((i - 2) // refresh) * refresh}
            for k in [k for k in maps if k not in keep]:
                del maps[k]
        return maps[i]

    timings = {}

    def get_time(i):
        if i not in timings:
            timings[i] = json.loads(Path(str(stems[i]) + ".time.json").read_text())
        return timings[i]

    transitions = []
    stale_cache_ops: dict = {}
    for i in range(1, len(steps)):
        prev, cur = steps[i - 1], steps[i]
        row = {"i": i, "sha": cur["sha"], "date": cur.get("date")}
        if i not in stems or (i - 1) not in stems:
            row["status"] = "not-evaluated"
            row["why"] = f"prev {prev.get('status')}, cur {cur.get('status')}"
            transitions.append(row)
            continue
        m = get_map(i - 1)
        tcur = get_time(i)
        tprev = get_time(i - 1)
        ch = changes_between(src, prev["sha"], cur["sha"])
        row["changed_files"] = len(ch)
        kinds = sorted({k for _, p in ch if (k := config_kind(p))})
        row["config_kinds"] = kinds
        strict_hit = bool(kinds)
        # relaxed: environment changed, pytest section changed, conftest changed
        relaxed_why = []
        if prev.get("freeze") is not None and cur.get("freeze") is not None and prev["freeze"] != cur["freeze"]:
            relaxed_why.append("environment")
        for st, p in ch:
            base = p.rsplit("/", 1)[-1]
            if base in ("conftest.py", "pytest.ini", ".pytest.ini"):
                relaxed_why.append(base)
            elif base in ("pyproject.toml", "setup.cfg", "tox.ini") and "/" not in p:
                if pytest_section(show(src, prev["sha"], p), p) != pytest_section(show(src, cur["sha"], p), p):
                    relaxed_why.append(base + ":pytest")
        row["relaxed_config"] = sorted(set(relaxed_why))
        py = {p: st for st, p in ch if p.endswith(".py")}
        fcs = {}
        for p, st in py.items():
            if st == "A":
                continue
            fcs[p] = FileChange(p, "M" if st in ("M", "T") else st,
                                show(src, prev["sha"], p), show(src, cur["sha"], p) if st != "D" else None)
        row["py_changed"] = len(fcs)
        row["py_formatting_only"] = sum(1 for fc in fcs.values() if fc.ast_equal)
        row["py_module_level"] = sum(1 for fc in fcs.values() if fc.module_level)
        row["py_hard"] = sum(1 for fc in fcs.values() if fc.hard)
        row["py_why"] = {p: fc.why for p, fc in fcs.items() if fc.hard}
        test_files = {n.split("::")[0] for n in m.tests}
        scope = {}
        for p in fcs:
            if p in test_files:
                base = p.rsplit("/", 1)[-1][:-3]
                hits = git(src, "grep", "-l", "-E", rf"^\s*(from|import)\s.*\b{base}\b", prev["sha"], "--", "*.py",
                           check=False).splitlines()
                scope[p] = {p} | {h.split(":", 1)[1] for h in hits if ":" in h}
        row["test_file_scope"] = {p: len(v) for p, v in scope.items()}
        data_changed = {p for st, p in ch if not p.endswith(".py")}
        list_changed = listing_changes(src, prev["sha"], cur["sha"], ch)
        names_ctx = build_names_ctx(src, m, fcs, scope, test_files, prev["sha"], cur["sha"])
        row["names"] = {k: (sorted(v)[:40] if isinstance(v, (set, list)) else v) for k, v in names_ctx.items()
                        if k in ("hard_loaded", "test_modules_hit", "n_names", "names_sample", "file_hard")}

        cur_tests = {n: r for n, r in tcur["tests"].items() if r.get("idx", -1) >= 0}
        total = sum(r["dur"] for r in cur_tests.values())
        row.update(tests=len(cur_tests), test_time=total, wall=cur.get("time_wall"), cap_wall=cur.get("cap_wall"))
        base_reason = {}
        for nid in cur_tests:
            if nid not in m.tests:
                base_reason[nid] = "new"
            else:
                ok_det, how = is_det(nid, i - 1)
                det_source_count[how] = det_source_count.get(how, 0) + 1
                if ok_det is None:
                    base_reason[nid] = "det-unknown"
                elif not ok_det:
                    base_reason[nid] = "not-deterministic"
            if nid not in base_reason and nid in m.unprovable:
                base_reason[nid] = m.unprovable[nid]
        row["base_reasons"] = _count(base_reason.values())
        row["base_reasons_time"] = _sum_by(base_reason, cur_tests)
        res = {}
        for cm in CONFIG_MODES:
            hit = strict_hit if cm == "strict" else bool(relaxed_why)
            for v in VARIANTS:
                skip, reasons = [], {}
                for nid in cur_tests:
                    r = base_reason.get(nid) or ("config" if hit else None) or decide(m, nid, fcs, data_changed,
                                                                                       list_changed, v, scope, names_ctx)
                    if r:
                        reasons[nid] = r
                    else:
                        skip.append(nid)
                ts = sum(cur_tests[n]["dur"] for n in skip)
                o_changed = [n for n in skip if (tprev["tests"].get(n) or {}).get("outcome") != cur_tests[n]["outcome"]]
                res[f"{cm}/{v}"] = {
                    "skip": len(skip), "skip_time": ts,
                    "share_count": len(skip) / len(cur_tests) if cur_tests else 0.0,
                    "share_time": ts / total if total else 0.0,
                    "share_wall": ts / cur["time_wall"] if cur.get("time_wall") else None,
                    "reasons": _count(reasons.values()),
                    "outcome_changed": len(o_changed), "outcome_changed_examples": o_changed[:5],
                }
        row["results"] = res
        # ground truth on executed paths: for skipped tests (strict/line+guard and strict/file), compare the
        # lines they execute at cur with the lines they executed at prev moved to cur's numbering
        if (i in stems):
            mc = get_map(i)
            ops = {p: fc.ops for p, fc in fcs.items() if fc.status == "M"}
            ops.update({p: None for p, fc in fcs.items() if fc.status == "D"})
            moved = m.remap(ops) if ops else m
            for key in ("strict/closure", "strict/line+guard", "strict/line+nameguard", "strict/line+names", "strict/line",
                        "strict/file", "relaxed/line+names", "relaxed/line+guard", "relaxed/line"):
                cm, v = key.split("/")
                hit = strict_hit
                diff, checked, examples, ids = 0, 0, [], []
                for nid in cur_tests:
                    if base_reason.get(nid) or hit or decide(m, nid, fcs, data_changed, list_changed, v, scope, names_ctx):
                        continue
                    checked += 1
                    a = {f: frozenset().union(*ls) for f, ls in moved.run[nid].items()}
                    b = {f: frozenset().union(*ls) for f, ls in mc.run.get(nid, {}).items()}
                    if a != b:
                        diff += 1
                        ids.append(nid)
                        if len(examples) < 3:
                            fd = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f))
                            examples.append({"test": nid, "files": fd[:3]})
                res[key]["path_changed"] = diff
                res[key]["path_checked"] = checked
                res[key]["path_changed_examples"] = examples
                res[key]["path_changed_ids"] = ids
        # stale map (last refresh point)
        r0 = ((i - 1) // refresh) * refresh
        if r0 != i - 1 and r0 in stems:
            ms = get_map(r0)
            sops = {}
            for st, p in changes_between(src, steps[r0]["sha"], prev["sha"]):
                if not p.endswith(".py"):
                    continue
                if st == "D":
                    sops[p] = None
                elif st in ("M", "T"):
                    key = (r0, i - 1, p)
                    if key not in stale_cache_ops:
                        o, n = show(src, steps[r0]["sha"], p), show(src, prev["sha"], p)
                        stale_cache_ops[key] = difflib.SequenceMatcher(
                            None, (o or "").splitlines(), (n or "").splitlines(), autojunk=False).get_opcodes()
                    sops[p] = stale_cache_ops[key]
            ms_moved = ms.remap(sops) if sops else ms
            stale = {}
            for v in ("file", "line", "file+guard", "line+guard", "line+nameguard"):
                unsafe = wasted = 0
                unsafe_t = 0.0
                for nid in cur_tests:
                    if base_reason.get(nid) or strict_hit:
                        continue
                    fresh_run = decide(m, nid, fcs, data_changed, list_changed, v, scope, names_ctx) is not None
                    if nid not in ms_moved.tests:
                        stale_run = True
                    else:
                        stale_run = decide(ms_moved, nid, fcs, data_changed, list_changed, v, scope, names_ctx) is not None
                    if fresh_run and not stale_run:
                        unsafe += 1
                        unsafe_t += cur_tests[nid]["dur"]
                    elif stale_run and not fresh_run:
                        wasted += 1
                stale[v] = {"age": i - 1 - r0, "unsafe": unsafe, "unsafe_time": unsafe_t, "wasted": wasted}
            row["stale"] = stale
        row["status"] = "ok"
        transitions.append(row)
        print(f"[{repo} {i}] {cur['sha'][:10]} tests {len(cur_tests)} changed {len(ch)} cfg {kinds} "
              + " ".join(f"{v}={res['strict/' + v]['share_time']:.2f}" for v in VARIANTS), flush=True)
    summary = summarize(transitions, steps)
    summary["det_source"] = det_source_count
    summary["det_checks"] = {i: st.get("det") for i, st in enumerate(steps) if st.get("det")}
    return {"repo": repo, "meta": {k: v for k, v in meta.items() if k != "steps"}, "steps": steps,
            "transitions": transitions, "summary": summary}


class _Cat:
    """git cat-file --batch for many small reads."""

    def __init__(self, src):
        self.p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=src, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE)

    def get(self, sha, path):
        self.p.stdin.write(f"{sha}:{path}\n".encode())
        self.p.stdin.flush()
        header = self.p.stdout.readline().decode()
        if header.endswith("missing\n"):
            return None
        size = int(header.split()[2])
        data = self.p.stdout.read(size + 1)[:-1]
        return data.decode("utf-8", "replace")


_CAT = {}


def build_names_ctx(src, m, fcs, scope, test_files, prev_sha, cur_sha):
    """Changed names for the name-read rule: seeds from changed library modules, propagated through the
    module-level code of every repository module the previous run had loaded."""
    cat = _CAT.get(str(src)) or _CAT.setdefault(str(src), _Cat(src))
    files = {}
    for f, fc in fcs.items():
        if fc.status == "M" and fc.module_level and not (scope and f in scope):
            files[f] = namerule.module_change(cat.get(prev_sha, f) or "", cat.get(cur_sha, f) or "",
                                              m.special, m.hooks, f)
    ctx = {"files": files, "hard_loaded": set(), "test_modules_hit": set(), "mask": 0, "n_names": 0,
           "file_hard": {f: r["hard"][:3] for f, r in files.items() if r["hard"]}}
    seeds = {f: r for f, r in files.items() if not r["hard"]}
    if not seeds:
        return ctx
    loaded = [p for p in m.first_seen if p.endswith(".py")]
    sources = {}
    for p in loaded:
        t = cat.get(cur_sha, p)
        if t is not None:
            sources[p] = t
    qual, attrs, hard = namerule.propagate(seeds, sources)
    ctx["hard_loaded"] = set(hard)
    ctx["test_modules_hit"] = {p for (p, n) in qual if p in test_files}
    allnames = attrs | {n for (_, n) in qual}
    ctx["n_names"] = len(allnames)
    ctx["names_sample"] = sorted(allnames)[:40]
    mask = 0
    for n in allnames:
        for k in m.ident_codes.get(n, ()):
            mask |= 1 << k
    ctx["mask"] = mask
    return ctx


def _count(values) -> dict:
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _sum_by(reasons: dict, tests: dict) -> dict:
    out = {}
    for n, r in reasons.items():
        out[r] = out.get(r, 0.0) + tests[n]["dur"]
    return out


def _stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"median": statistics.median(xs), "mean": statistics.fmean(xs), "min": min(xs), "max": max(xs),
            "n": len(xs)}


def summarize(transitions, steps) -> dict:
    ok = [t for t in transitions if t.get("status") == "ok"]
    s = {"transitions": len(transitions), "evaluated": len(ok),
         "config_strict": sum(1 for t in ok if t["config_kinds"]),
         "config_relaxed": sum(1 for t in ok if t["relaxed_config"]),
         "config_kinds": _count(k for t in ok for k in t["config_kinds"])}
    for key in ok[0]["results"] if ok else []:
        s[key] = {m: _stats([t["results"][key][m] for t in ok]) for m in ("share_time", "share_count", "share_wall")}
        s[key]["outcome_changed"] = sum(t["results"][key]["outcome_changed"] for t in ok)
        if "path_changed" in ok[0]["results"][key]:
            s[key]["path_changed"] = sum(t["results"][key].get("path_changed", 0) for t in ok)
            s[key]["skipped_total"] = sum(t["results"][key]["skip"] for t in ok)
            s[key]["path_checked"] = sum(t["results"][key].get("path_checked", 0) for t in ok)
    st = [t for t in ok if "stale" in t]
    s["stale"] = {v: {"transitions": len(st), "unsafe_tests": sum(t["stale"][v]["unsafe"] for t in st),
                      "transitions_with_unsafe": sum(1 for t in st if t["stale"][v]["unsafe"]),
                      "wasted_tests": sum(t["stale"][v]["wasted"] for t in st)}
                  for v in ("file", "line", "file+guard", "line+guard", "line+nameguard")} if st else {}
    oks = [x for x in steps if x.get("status") == "ok"]
    s["overhead"] = _stats([x["cap_wall"] / x["time_wall"] - 1 for x in oks if x.get("time_wall")])
    s["plain_wall"] = _stats([x["time_wall"] for x in oks])
    s["base_reasons_mean"] = {}
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--refresh", type=int, default=10)
    a = ap.parse_args(argv)
    res = analyze(a.repo, Path(a.work).resolve() / a.repo, a.refresh)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.repo}.json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
