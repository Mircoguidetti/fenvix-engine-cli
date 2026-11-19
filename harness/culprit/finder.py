"""Exact-culprit finder, prototype (validation of idea 2 only; not the product).

Input: one red test, the proof key of its red run and the proof key of its last green run (both written by
``pytest --det --det-cache=DIR --det-cache-keys=PATH``), and how to rebuild each side (commit, CI variables,
installed distributions). Output: one commit, one input, a set of inputs needed together, or unknown.

1. Diff the two keys: every input whose digest differs (code units, module skeletons, conftest hooks, files read,
   environment variables read, installed distributions, interpreter, configuration, time zone and locale).
2. Prune: a distribution is a candidate only if the test's process loaded it; a commit is a candidate only if it
   changes one of the differing code or data inputs (checked per unit: the commit must change that unit's digest).
   A commit that changes a file mode is always a candidate (modes are not inputs of the key).
3. Search with one deterministic replay per step (``--det``, fixed epoch, empty cache): first "red code in the
   green environment" when both kinds of candidate exist, then a binary search over the candidate commits or a
   binary split of the candidate inputs.
4. Confirm before answering (review R-019): a commit is named only if its parent passes and it fails when
   replayed, and no later commit that touches its inputs again passes (a newer transition); an input is named
   only if the red code passes in the green environment and fails with that input alone; inputs needed together
   are found by ddmin; a test whose key flags an uncontrolled source (entropy, network, real clock) is replayed at
   green first and searched only under controlled entropy. A failed confirmation falls back to a search over
   every commit, or ends in "unknown". A confident wrong culprit is worse than none.
   Red side (review R-019b; round 4): a commit is named only if every later commit up to the red head fails. A
   later commit is decided without a replay when a replay of the same side (or the CI key of that side) recorded
   inputs that all have the same value there (key validity, with guards for what the key does not record); the
   rest is replayed RED_WORKERS at a time, each in its own copy of the repository mounted at the repository's path,
   up to RED_BUDGET replays per case. An undecided rest withholds the answer (unknown, with the suspect).
5. Every replay records the runtime identity; a replay meant to run in the green environment counts as an exact
   rebuild only when its runtime digest equals the green key's. An answer from an inexact rebuild is withheld.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import checkout, git, git_out, run_det, sh, worktrees  # noqa: E402

import subprocess  # noqa: E402

_FACTS_CACHE: dict = {}
# detpy's own files that a key may list as data: the bytecode cache (derived from the sources, which are inputs
# themselves) and the per-run cache directory of this harness (clock shim)
_OWN_FILES = ("/.cache/detpy/", "/detrun-")


# ---------------------------------------------------------------------------- keys
def norm_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def test_entry(d: dict, nodeid: str) -> dict | None:
    """The entry of one test in a key dump (``--det-cache-keys``)."""
    def same(a: str, b: str) -> bool:  # node ids are relative to pytest's rootdir, which may be a subdirectory
        return a == b or a.endswith("/" + b) or b.endswith("/" + a)

    tests = d.get("tests") or {}
    t = tests.get(nodeid)
    if t is None:
        t = next((v for k, v in tests.items() if same(k, nodeid)), None)
    if t is None:  # parametrised: the first entry of the same function
        base = nodeid.split("[", 1)[0]
        for k, v in tests.items():
            if same(k.split("[", 1)[0], base):
                t = v
                break
    return t


def load_key(path: str, nodeid: str) -> dict | None:
    with open(path) as fh:
        d = json.load(fh)
    t = test_entry(d, nodeid)
    dists = {}
    for s in d.get("distributions", []):
        nv, _, rec = s.rpartition(":")
        n, _, v = nv.partition("==")
        dists[norm_dist(n)] = (v, rec)
    return {"test": t, "config_info": d.get("config_info", {}), "runtime": d.get("runtime"),
            "runtime_info": d.get("runtime_info", {}), "dists": dists,
            "loaded": {norm_dist(x) for x in d.get("loaded_distributions", [])}, "epoch": d.get("epoch"),
            "root": d.get("root"), "interpreter": d.get("interpreter") or {}}


def diff_keys(g: dict, r: dict) -> list[dict]:
    """Every input whose value differs between the green and the red key of one test."""
    ch: list[dict] = []
    gt, rt = g["test"] or {}, r["test"] or {}
    if gt and rt:
        for k in sorted(set(gt.get("code", {})) | set(rt.get("code", {}))):
            if gt["code"].get(k) != rt["code"].get(k):
                kind, rest = k.split(":", 1)
                ch.append({"kind": "code", "id": k, "what": kind, "path": rest.split("::", 1)[0],
                           "unit": rest.split("::", 1)[1] if "::" in rest else None})
        for p in sorted(set(gt.get("data", {})) | set(rt.get("data", {}))):
            if any(x in p for x in _OWN_FILES):
                continue  # detpy's own derived files (bytecode cache, the run's cache dir)
            if gt["data"].get(p) != rt["data"].get(p):
                ch.append({"kind": "data", "id": f"data:{p}", "path": p, "inrepo": not os.path.isabs(p)})
        for n in sorted(set(gt.get("env", {})) | set(rt.get("env", {}))):
            if gt["env"].get(n) != rt["env"].get(n):
                ch.append({"kind": "env", "id": f"env:{n}", "name": n})
        if (gt.get("clock") or rt.get("clock")) and g["epoch"] != r["epoch"]:
            ch.append({"kind": "epoch", "id": "epoch"})
    gi, ri = g["runtime_info"], r["runtime_info"]
    for f in ("python", "cache_tag", "executable", "libpython", "system", "machine", "libc", "stdlib"):
        if gi.get(f) != ri.get(f):
            ch.append({"kind": "runtime", "id": f"runtime:{f}", "field": f})
    for n in sorted(set(g["dists"]) | set(r["dists"])):
        if n == "detpy":
            continue
        if g["dists"].get(n) != r["dists"].get(n):
            ch.append({"kind": "dist", "id": f"dist:{n}", "name": n,
                       "green": (g["dists"].get(n) or (None,))[0], "red": (r["dists"].get(n) or (None,))[0]})
    gp, rp = g.get("interpreter", {}), r.get("interpreter", {})
    gpe, rpe = gp.get("env", {}), rp.get("env", {})
    for n in sorted(set(gpe) | set(rpe)):
        if gpe.get(n) != rpe.get(n):
            ch.append({"kind": "env", "id": f"env:{n}", "name": n, "startup": True})
    for f in ("xoptions", "flags"):
        if json.dumps(gp.get(f), sort_keys=True) != json.dumps(rp.get(f), sort_keys=True):
            ch.append({"kind": "interp", "id": f"interpreter:{f}", "field": f})
    gc, rc = g["config_info"], r["config_info"]
    for f in ("ini", "inifile", "options", "level0"):
        if json.dumps(gc.get(f), sort_keys=True) != json.dumps(rc.get(f), sort_keys=True):
            ch.append({"kind": "config", "id": f"config:{f}", "field": f})
    gtz, rtz = gc.get("tz_locale", {}) or {}, rc.get("tz_locale", {}) or {}
    for v in sorted(set(gtz) | set(rtz)):
        if gtz.get(v) != rtz.get(v):
            ch.append({"kind": "tzlocale", "id": f"tzlocale:{v}", "name": v})
    seen, out = set(), []
    for c in ch:
        if c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    return out


# ---------------------------------------------------------------------------- commit pruning
def _facts_of(repo, sha: str, path: str):
    """(skeleton, hooks, {unit: digest}, content digest) of ``path`` at ``sha``; None when absent."""
    key = (str(repo), sha, path)
    if key in _FACTS_CACHE:
        return _FACTS_CACHE[key]
    try:
        blob = git_out(repo, "rev-parse", f"{sha}:{path}").strip()
    except RuntimeError:
        _FACTS_CACHE[key] = None
        return None
    bkey = ("blob", blob, path)
    if bkey in _FACTS_CACHE:
        _FACTS_CACHE[key] = _FACTS_CACHE[bkey]
        return _FACTS_CACHE[bkey]
    p = __import__("subprocess").run(["git", "-C", str(repo), "cat-file", "blob", blob], capture_output=True)
    if p.returncode != 0:  # a directory (listing input) or an unreadable object: its object id is its value
        res = (blob, blob, {}, blob)
        _FACTS_CACHE[bkey] = res
        _FACTS_CACHE[key] = res
        return res
    raw = p.stdout
    content = hashlib.sha256(raw).hexdigest()
    res = (content, content, {}, content)
    if path.endswith(".py"):
        try:
            from detpy import _codefacts

            text = raw.decode("utf-8")
            mod = path[:-3].replace("/", ".")
            if mod.startswith("src."):
                mod = mod[4:]
            is_pkg = mod.endswith(".__init__")
            if is_pkg:
                mod = mod[: -len(".__init__")]
            f = _codefacts.facts(text, content, mod, is_pkg)
            if f is not None:
                res = (f[0], f[1], {u[0]: u[3] for u in f[2]}, content)
        except Exception:
            pass
    _FACTS_CACHE[bkey] = res
    _FACTS_CACHE[key] = res
    return res


def _item_value(facts, change: dict):
    if facts is None:
        return None
    sk, hk, units, content = facts
    w = change.get("what")
    if change["kind"] == "data":
        return content
    if w == "unit":
        return units.get(change["unit"])
    if w == "skeleton":
        return sk
    if w == "hooks":
        return hk
    return content


_RAW_CACHE: dict = {}


def touched_paths(repo, sha: str) -> dict:
    """{path: (old mode, new mode)} of one commit against its first parent."""
    key = (str(repo), sha)
    if key not in _RAW_CACHE:
        out = git(repo, "diff-tree", "--no-commit-id", "-r", "-m", "--first-parent", "--no-renames", sha)
        res = {}
        for line in out.splitlines():
            if not line.startswith(":") or "\t" not in line:
                continue
            meta, path = line.split("\t", 1)
            f = meta[1:].split()
            res[path] = (f[0], f[1])
        _RAW_CACHE[key] = res
    return _RAW_CACHE[key]


def mode_changes(repo, sha: str) -> list[str]:
    """Paths whose mode (executable bit, symlink) a commit changes while the path exists on both sides."""
    return sorted(p for p, (a, b) in touched_paths(repo, sha).items() if a != b and a != "000000" and b != "000000")


def mode_at(repo, sha: str, path: str) -> str | None:
    key = ("mode", str(repo), sha, path)
    if key not in _FACTS_CACHE:
        out = git(repo, "ls-tree", sha, "--", path, check=False).split()
        _FACTS_CACHE[key] = out[0] if out else None
    return _FACTS_CACHE[key]


def commit_candidates(repo, commits: list[str], changes: list[dict]) -> list[str]:
    """Commits of ``commits`` (oldest first) that change at least one of the differing in-repository inputs, or
    the mode of any file: ``os.access``/``os.stat`` are not recorded in the key, so a mode change cannot be pruned
    by the footprint (review R-019, H2)."""
    items = [c for c in changes if c["kind"] == "code" or (c["kind"] == "data" and c.get("inrepo"))]
    by_path: dict[str, list[dict]] = {}
    for c in items:
        by_path.setdefault(c["path"], []).append(c)
    dirs = [c for c in items if c["kind"] == "data"]
    out = []
    for sha in commits:
        tp = touched_paths(repo, sha)
        touched = set(tp)
        hit = bool(mode_changes(repo, sha))
        for path in (touched & set(by_path)) if not hit else ():
            before, after = _facts_of(repo, sha + "^", path), _facts_of(repo, sha, path)
            for c in by_path[path]:
                if _item_value(before, c) != _item_value(after, c):
                    hit = True
                    break
            if hit:
                break
        if not hit:
            # a listing or a missing-path input: any added or removed path under it
            for c in dirs:
                p = c["path"].rstrip("/")
                if any(t == p or t.startswith(p + "/") for t in touched):
                    hit = True
                    break
        if hit:
            out.append(sha)
    return out


def dep_holds(path: str, dep: str) -> bool:
    """Does the recorded data dependency still hold on this machine?"""
    from detpy import _core
    try:
        if dep == "missing":
            return not os.path.lexists(path)
        if dep.startswith("f:"):
            return _core.file_digest(path) == dep[2:]
        if dep.startswith("d:"):
            return _core.listing_digest(path) == dep[2:]
        if dep.startswith("s:"):
            return os.path.lexists(path)
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------- input groups
_TZ_FILES = ("/usr/share/zoneinfo/", "/etc/localtime", "/etc/timezone")
_LOCALE_FILES = ("/usr/lib/locale/", "/usr/share/locale/", "/usr/share/i18n/")
_RUNNER_DISTS = {"pytest", "pluggy", "iniconfig", "packaging"}


def group_inputs(inputs: list[dict], genv: dict, renv: dict) -> tuple[list[dict], dict]:
    """Fold the consequences of one change into the change itself, using the two job definitions.

    * a variable the two jobs set to the same value is not a candidate, even when only one run read it (the read
      differs because something else changed);
    * a variable the jobs set differently heads a group: its ``tzlocale`` twin, and for TZ / LANG / LC_* the zone or
      locale files the C library read;
    * a change of pytest's options or ini values follows a change of pytest or of a pytest plugin distribution.
    Returns (candidates, {head: [folded ids]}).
    """
    changed_vars = {n for n in set(genv) | set(renv) if genv.get(n) != renv.get(n)}
    dists = {c["name"] for c in inputs if c["kind"] == "dist"}
    plugin_change = bool(dists & _RUNNER_DISTS) or any(n.startswith("pytest-") for n in dists)
    heads, folded, out = {}, {}, []
    for c in inputs:
        var_like = c["kind"] in ("env", "tzlocale") and c.get("name") not in ("*", "tzfile") \
            and "/" not in c.get("name", "/")
        if var_like and c["name"] not in changed_vars:
            folded.setdefault("(same value in both jobs)", []).append(c["id"])
            continue
        if var_like and c.get("name") in changed_vars:
            h = f"env:{c['name']}"
            if h not in heads:
                heads[h] = {"kind": "env", "id": h, "name": c["name"]}
                out.append(heads[h])
            if c["id"] != h:
                folded.setdefault(h, []).append(c["id"])
            continue
        if (c["kind"] == "tzlocale" and c.get("name") in ("tzfile", "/etc/localtime")) or \
                (c["kind"] == "data" and c["path"].startswith(_TZ_FILES)):
            if "TZ" in changed_vars:
                folded.setdefault("env:TZ", []).append(c["id"])
                if "env:TZ" not in heads:
                    heads["env:TZ"] = {"kind": "env", "id": "env:TZ", "name": "TZ"}
                    out.append(heads["env:TZ"])
                continue
        if c["kind"] == "data" and c["path"].startswith(_LOCALE_FILES):
            lv = sorted(v for v in changed_vars if v == "LANG" or v.startswith("LC_"))
            if lv:
                h = f"env:{lv[0]}"
                folded.setdefault(h, []).append(c["id"])
                if h not in heads:
                    heads[h] = {"kind": "env", "id": h, "name": lv[0]}
                    out.append(heads[h])
                continue
        if c["kind"] == "config" and c["field"] in ("ini", "options") and plugin_change:
            folded.setdefault("(pytest or plugin distribution)", []).append(c["id"])
            continue
        out.append(c)
    return out, folded


# ---------------------------------------------------------------------------- environments
class EnvBuilder:
    """Builds the environment a replay runs in: CI variables plus a virtualenv with a given distribution set."""

    def __init__(self, project_install: list[str], wheel: str, root: str, python="3.13"):
        self.project_install = project_install  # e.g. ["-e", "."] run in the checkout
        self.wheel = wheel
        self.root = Path(root)
        self.python = python
        self.root.mkdir(parents=True, exist_ok=True)

    def own_names(self, repo) -> set:
        import tomllib
        out = set()
        args = self.project_install
        for i, x in enumerate(args):
            if x == "-e" and i + 1 < len(args):
                d = Path(repo) / args[i + 1].split("[")[0]
                try:
                    out.add(norm_dist(tomllib.loads((d / "pyproject.toml").read_text())["project"]["name"]))
                    continue
                except Exception:
                    pass
                for f, pat in (("setup.cfg", r"^name\s*=\s*(\S+)"), ("setup.py", r"name\s*=\s*['\"]([^'\"]+)['\"]")):
                    try:
                        m = re.search(pat, (d / f).read_text(), re.M)
                    except OSError:
                        m = None
                    if m:
                        out.add(norm_dist(m.group(1)))
                        break
        return out

    def venv_for(self, repo, dists: dict, at: Path | None = None) -> tuple[Path, float, bool]:
        """A virtualenv with exactly ``dists`` (name -> version) plus detpy and the project (editable).

        ``at``: build it at that path (the green job's own virtualenv path, free because its machine is gone):
        console scripts embed the virtualenv path, so a rebuild elsewhere never has the same runtime identity.
        """
        own = self.own_names(repo)  # the repository's own packages come from the checkout (editable)
        spec = sorted(f"{n}=={v}" for n, v in dists.items() if n not in ("detpy",) and n not in own and v)
        h = hashlib.sha256("\n".join(spec).encode()).hexdigest()[:16]
        venv = Path(at) if at else self.root / h
        if at and (venv / ".ok").exists() and (venv / ".spec").read_text() != h:
            import shutil
            shutil.rmtree(venv)
        if (venv / ".ok").exists():
            return venv, 0.0, False
        t0 = time.perf_counter()
        sh(["uv", "venv", "-q", "--python", self.python, str(venv)], check=True)
        req = venv / "req.txt"
        req.write_text("\n".join(spec) + "\n")
        code, out = sh(["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), "--no-deps",
                        "-r", str(req), self.wheel], cwd=repo, timeout=1800)
        if code != 0:
            raise RuntimeError(f"rebuild failed: {out[-1500:]}")
        code, out = sh(["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), "--no-deps",
                        *self.project_install], cwd=repo, timeout=1800)
        if code != 0:
            raise RuntimeError(f"project install failed: {out[-1500:]}")
        (venv / ".spec").write_text(h)
        (venv / ".ok").write_text("ok")
        return venv, time.perf_counter() - t0, True


# ---------------------------------------------------------------------------- the finder
# ---------------------------------------------------------------------------- the finder
# flags of a key that make one replay no proof: the test read a source --det does not control. ``spawn`` is a
# child process the engine did not follow, or followed and found reading the network, the clock or /dev (review
# R-019b, N3): like in-process entropy, its outcome may change from run to run.
NONDET_FLAGS = ("rclock", "connect", "csock", "dns", "entropy", "net", "spawn")
REPEATABLE_FLAGS = ("entropy", "spawn")  # searched (with repeated confirmations) once green and red are stable
GREEN_REPEATS = 5  # replays of the green (and red) side when the key flags an uncontrolled source
# round 3's RETOUCH_CAP and FALLBACK_CAP (6 each) are replaced by RED_BUDGET (round 4, below)
MAX_ROUNDS = 6
_LOADER_READS = ("/etc/ld.so.cache", "/etc/ld.so.preload")  # read by the dynamic loader of every exec'd program


def child_processes(test: dict | None) -> list[str]:
    """Evidence in a test's key that it ran a child process the engine followed.

    The engine flags ``spawn`` only for a child it could not follow (or that read the network, the clock or /dev).
    A followed child's own entropy (``getrandom``: every interpreter draws some at start-up) is counted, not
    flagged, and the key keeps no per-test count; what the key does keep are the child's inputs: the program
    file (under a ``bin`` directory) and the dynamic loader's reads. In-process code reads neither during a test.
    """
    data = (test or {}).get("data", {})
    return sorted(p for p in data if p in _LOADER_READS or re.search(r"/s?bin/[^/]+$", p))


# ---------------------------------------------------------------------------- key validity (round 4)
# A deterministic run is a function of the inputs its key records: a run at commit j that sees, for every input
# recorded by an earlier run R on the same side (environment, distributions, interpreter, arguments), the value R
# saw, replays R step by step and ends with R's outcome. This is the proof-cache premise of the engine, applied to
# one test across commits. It lets the red-side check infer most later commits instead of replaying them.
# Round 5 (review R-019c, F-1): the key does not record every input (import probes, existence checks, binaries),
# so inference also needs the two commits' trees to differ only in changed recorded inputs (``agrees``: diff rule).
# Earlier guards, kept (now implied by the diff rule, except the run-side checks):
#   * pytest configuration files (rootdir and ini discovery, options) at the repository root and the key root;
#   * every conftest.py and __init__.py on the path from the root to the test file (conftest discovery, rootdir
#     and package detection);
#   * the names in every directory on the path of each code or data input (a new module or package shadowing an
#     import is not in the key: the import system's directory reads are not recorded);
#   * the mode of every path whose mode a commit of the range changes (``os.access`` and ``os.stat`` are not
#     inputs of the key);
#   * no inference from a run the engine itself does not treat as a proof (not cached for a reason other than its
#     outcome) or that reads a source --det does not control.
RED_WORKERS = int(os.environ.get("CULPRIT_WORKERS", "4"))  # red-side probes replayed at the same time
RED_BUDGET = int(os.environ.get("CULPRIT_RED_BUDGET", "32"))  # red-side probes per case (every round), beyond undo
_CONFIG_NAMES = ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", ".pytest.ini")
_TREES: dict = {}


def tree_of(repo, sha: str) -> dict:
    """{path: (mode, object id)} of every file and directory of a commit (``ls-tree -r -t``)."""
    key = (str(repo), sha)
    if key not in _TREES:
        out = git_out(repo, "ls-tree", "-r", "-t", "--full-tree", sha)
        t = {}
        for line in out.splitlines():
            meta, _, path = line.partition("\t")
            f = meta.split()
            if len(f) >= 3:
                t[path] = (f[0], f[2])
        names: dict = {}
        for path in t:
            d, _, base = path.rpartition("/")
            names.setdefault(d, set()).add(base)
        _TREES[key] = (t, {d: frozenset(v) for d, v in names.items()})
    return _TREES[key]


_FILES: dict = {}


def _files_of(repo, sha: str) -> dict:
    """{path: (mode, blob)} of every file (no directory entries) of a commit."""
    key = (str(repo), sha)
    if key not in _FILES:
        t, _ = tree_of(repo, sha)
        _FILES[key] = {p: e for p, e in t.items() if e[0] != "040000"}
    return _FILES[key]


def _ancestors(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(len(parts) + 1)]


class Run:
    """One replay usable for inference: its commit, outcome and the in-repository inputs its key recorded."""

    def __init__(self, sha: str, outcome: str, items: dict, dirs: set, source: str):
        self.sha, self.outcome, self.items, self.dirs, self.source = sha, outcome, items, dirs, source


def run_from_key(repo, sha: str, outcome: str, kd: dict, entry: dict | None, nodeid: str, source: str):
    """A ``Run`` from a key dump, or None when the key is no proof of the outcome (see the guards above)."""
    if entry is None or outcome not in ("pass", "fail"):
        return None
    nc = entry.get("not_cached")
    if nc is not None and not str(nc).startswith("outcome "):
        return None
    # entropy under --det-urandom is controlled: the engine's own verdict (not_cached above) decides; every other
    # uncontrolled source makes the key no proof
    if set(entry.get("flags") or ()) & (set(NONDET_FLAGS) - {"entropy"}):
        return None
    try:
        rel = os.path.relpath(os.path.realpath(kd.get("root") or str(repo)), os.path.realpath(str(repo)))
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    pre = "" if rel == "." else rel.replace(os.sep, "/") + "/"
    items: dict = {}
    for k in (entry.get("code") or {}):
        kind, rest = k.split(":", 1)
        path, _, unit = rest.partition("::")
        if os.path.isabs(path):
            continue  # outside the repository (a distribution): the same on one side
        items.setdefault(pre + path, set()).add((kind, unit or None))
    for p in (entry.get("data") or {}):
        if os.path.isabs(p) or any(x in p for x in _OWN_FILES):
            continue
        items.setdefault(pre + p.rstrip("/"), set()).add(("data", None))
    test_file = pre + nodeid.split("::", 1)[0]
    extra = {n for n in _CONFIG_NAMES} | {pre + n for n in _CONFIG_NAMES}
    inif = ((kd.get("config_info") or {}).get("inifile") or "")
    if inif and not os.path.isabs(inif):
        extra.add(pre + inif)
    for d in _ancestors(test_file):
        for n in ("conftest.py", "__init__.py"):
            extra.add(f"{d}/{n}" if d else n)
    items.setdefault(test_file, set()).add(("content", None))
    for p in extra:
        items.setdefault(p, set()).add(("content", None))
    dirs: set = set()
    for p in items:
        dirs.update(_ancestors(p))
    return Run(sha, outcome, items, dirs, source)


def agrees(repo, sha: str, run: Run, mode_paths=()) -> bool:
    """Does commit ``sha`` give every input ``run`` recorded the value it had at ``run.sha``?"""
    if sha == run.sha:
        return True
    tj, nj = tree_of(repo, sha)
    tr, nr = tree_of(repo, run.sha)
    # Diff rule (review R-019c, F-1): the key misses inputs (failed import probes, existence checks, namespace
    # packages, zip archives, native libraries...), and nothing bounds where they sit. So no inference across a
    # pair of commits whose trees differ by an added, deleted or renamed path, or by a changed path that is not a
    # recorded input of the run (whatever its kind, binary or not). Only changes to recorded inputs are then
    # compared, finely (unit, skeleton, hooks digests).
    fj, fr = _files_of(repo, sha), _files_of(repo, run.sha)
    if fj.keys() != fr.keys():
        return False
    for path, e in fj.items():
        if fr[path] != e and path not in run.items:
            return False
    for d in run.dirs:
        if nj.get(d) != nr.get(d):
            return False
    for p in mode_paths:
        if (tj.get(p) or (None,))[0] != (tr.get(p) or (None,))[0]:
            return False
    for path, kinds in run.items.items():
        a, b = tj.get(path), tr.get(path)
        if a == b:
            continue
        if a is None or b is None or a[0] != b[0] or a[0] == "040000":
            return False
        fa, fb = _facts_of(repo, sha, path), _facts_of(repo, run.sha, path)
        for kind, unit in kinds:
            if kind in ("content", "data"):
                return False
            c = {"kind": "code", "what": kind, "unit": unit}
            if _item_value(fa, c) is None or _item_value(fa, c) != _item_value(fb, c):
                return False
    return True



def critical_wall(steps: list[dict]) -> float:
    """Seconds of replay on the critical path: every replay in sequence, a batch of parallel replays as its
    longest one (machine contention aside)."""
    tot, seen = 0.0, set()
    for s in steps:
        b = s.get("batch")
        if b is None:
            tot += s.get("wall") or 0.0
        elif b not in seen:
            seen.add(b)
            tot += max((x.get("wall") or 0.0) for x in steps if x.get("batch") == b)
    return round(tot, 2)


class Finder:
    """side = {"sha", "env": {var: value or None}, "venv": Path or None, "key": path}

    Output (``run()``): ``culprit`` is a commit, an input, or a set of inputs needed together, and only when the
    answer is confirmed by replays (``status == "confirmed"``). Otherwise ``culprit`` is None and ``status`` is
    ``"unknown"`` with the reason in ``why``: a confident wrong culprit is worse than none (review R-019).
    """

    def __init__(self, repo, nodeid: str, green: dict, red: dict, builder: EnvBuilder | None = None,
                 prune_dists=True, det_args=(), commits: list[str] | None = None, confirm=True):
        self.repo, self.nodeid, self.green, self.red = Path(repo), nodeid, green, red
        self.builder = builder
        self.prune_dists = prune_dists
        self.det_args = list(det_args)
        self.commits = commits
        self.confirm = confirm
        self.steps: list[dict] = []
        self.rebuilds: list[dict] = []
        self.inferred = 0
        self.reps = 1  # replays per confirmation step (GREEN_REPEATS when the key flags a child process)
        self._memo: dict = {}
        self.runs: dict = {}  # side id -> [Run]: replays (and CI keys) usable for inference (round 4)
        self.workers = RED_WORKERS
        self.budget = RED_BUDGET
        self.red_probes = 0
        self.red_inferred: set = set()
        self.batches = 0
        self.infer_keys = True  # key-validity inference in the red-side check (off: footprint vectors only)

    # -- one replay
    def _replay(self, sha: str, env_vars: dict, dists: dict | None, venv: Path | None, expect_runtime=None,
                why="", args=None, memo=True):
        args = self.det_args if args is None else list(args) + [a for a in self.det_args if a not in args]
        mk = self._mk(sha, env_vars, dists, venv, args)
        if memo and mk in self._memo:
            return self._memo[mk]
        if dists is not None:
            at = self.green.get("prefix") if dists == self._green_dists else None
            venv, secs, fresh = self.builder.venv_for(self.repo, dists, at=at)
            if fresh:
                self.rebuilds.append({"seconds": secs})
        checkout(self.repo, sha)
        r, kd = self._run_one(self.repo, None, sha, env_vars, venv, args)
        return self._record(mk, sha, env_vars, dists, venv, args, r, kd, why, expect_runtime)

    def _run_one(self, repo, worktree, sha, env_vars, venv, args):
        with tempfile.TemporaryDirectory() as td:
            kp = os.path.join(td, "k.json")
            r = run_det(repo, venv, self.nodeid, env_vars, keys=kp, args=args, worktree=worktree)
            kd = None
            try:
                with open(kp) as fh:
                    kd = json.load(fh)
            except (OSError, ValueError):
                pass
        return r, kd

    def _record(self, mk, sha, env_vars, dists, venv, args, r, kd, why, expect_runtime, extra=None):
        runtime = (kd or {}).get("runtime")
        step = {"sha": sha, "why": why, "outcome": r["outcome"], "wall": round(r["wall"], 2), "runtime": runtime}
        if extra:
            step.update(extra)
        if expect_runtime is not None:
            step["exact"] = runtime == expect_runtime
        self.steps.append(step)
        self._memo[mk] = r["outcome"]
        if kd is not None and (expect_runtime is None or runtime == expect_runtime):
            run = run_from_key(self.repo, sha, r["outcome"], kd, test_entry(kd, self.nodeid), self.nodeid,
                               f"replay {len(self.steps)}")
            if run is not None:
                self.runs.setdefault(self._sid(env_vars, dists, venv, args), []).append(run)
        return r["outcome"]

    @staticmethod
    def _sid(env_vars, dists, venv, args) -> tuple:
        """The side a replay runs on (everything but the commit)."""
        return (tuple(sorted((k, v) for k, v in (env_vars or {}).items())),
                tuple(sorted(dists.items())) if dists is not None else None,
                None if dists is not None else str(venv), tuple(args))

    def _side_sid(self, side) -> tuple:
        env_vars, dists, venv, _ = side
        return self._sid(env_vars, dists, venv, self.det_args)

    def _infer(self, sha: str, side, mode_paths=()) -> tuple[str | None, str]:
        """(outcome, source) of ``sha`` on ``side`` without a replay: an earlier replay of the same commit, or a run
        whose recorded inputs all have the same value at ``sha`` (key validity). (None, "") when neither."""
        k = self._known(sha, side)
        if k in ("pass", "fail"):
            return k, "replayed"
        if not self.infer_keys:
            return None, ""
        for run in self.runs.get(self._side_sid(side), ()):
            if agrees(self.repo, sha, run, mode_paths):
                return run.outcome, run.source
        return None, ""

    def _probe_many(self, shas: list[str], side, why) -> list[str]:
        """Replay several commits on one side at the same time, each in its own copy of the repository mounted at
        the repository's path (``run_det(worktree=...)``): the runs see the same paths as a replay in place."""
        if len(shas) <= 1 or self.workers <= 1:
            return [self._probe(x, side, why) for x in shas]
        env_vars, dists, venv, expect = side
        args = self.det_args
        if dists is not None:
            at = self.green.get("prefix") if dists == self._green_dists else None
            venv, secs, fresh = self.builder.venv_for(self.repo, dists, at=at)
            if fresh:
                self.rebuilds.append({"seconds": secs})
        wts = worktrees(self.repo, len(shas))
        for w, x in zip(wts, shas):
            checkout(w, x)
        from concurrent.futures import ThreadPoolExecutor

        self.batches += 1
        t0 = time.perf_counter()
        with ThreadPoolExecutor(len(shas)) as ex:
            futs = [ex.submit(self._run_one, self.repo, w, x, env_vars, venv, args) for w, x in zip(wts, shas)]
            res = [f.result() for f in futs]
        bw = round(time.perf_counter() - t0, 2)
        outs = []
        for i, (x, (r, kd)) in enumerate(zip(shas, res)):
            mk = self._mk(x, env_vars, dists, venv if dists is None else None, args)
            outs.append(self._record(mk, x, env_vars, dists, venv if dists is None else None, args, r, kd, why,
                                     expect, extra={"batch": self.batches, "worker": i, "batch_wall": bw}))
        return outs

    @staticmethod
    def _mk(sha, env_vars, dists, venv, args) -> tuple:
        return (sha, tuple(sorted((k, v) for k, v in (env_vars or {}).items())),
                tuple(sorted((dists or {}).items())) if dists is not None else None, str(venv), tuple(args))

    def _known(self, sha: str, side) -> str | None:
        """The outcome of an earlier replay of ``sha`` on ``side``, or None (no execution)."""
        env_vars, dists, venv, _ = side
        return self._memo.get(self._mk(sha, env_vars, dists, venv, self.det_args))

    # -- footprint state of a commit: the value of every differing in-repository input (and file modes)
    def _vector(self, sha: str) -> tuple:
        out = []
        for c in self._items:
            if c["kind"] == "mode":
                out.append(mode_at(self.repo, sha, c["path"]))
            else:
                out.append(_item_value(_facts_of(self.repo, sha, c["path"]), c))
        return tuple(out)

    def _parent(self, sha: str) -> str:
        return git(self.repo, "rev-parse", f"{sha}^")

    # -- commit search -------------------------------------------------------------------------------------
    def _search_commits(self, commits, cands, side) -> tuple[dict | None, str, str]:
        """Binary search over candidate commits with footprint-state inference, then confirmation.

        * a candidate whose footprint state equals the green state passes, one equal to the red state fails, one
          equal to an already replayed state has that outcome (no execution): a reverted breakage is skipped;
        * the answer C is confirmed by replaying C's parent (must pass) and C (must fail); a failed confirmation
          means the footprint missed an input (or the history is not monotonic), and the search falls back to all
          commits of the narrowed range;
        * a later candidate that changes C's inputs again is probed (round 4: every later commit, see _red_check): if it passes, the red at
          the head comes from a newer transition and the search restarts above it.
        """
        n = len(cands)
        vec = {sha: self._vector(sha) for sha in [self.green["sha"], self.red["sha"], *cands]}
        known = {vec[self.green["sha"]]: "pass", vec[self.red["sha"]]: "fail"}

        def outcome(i: int, why: str) -> str:
            if i < 0:
                return "pass"
            v = vec[cands[i]]
            if v in known:
                self.inferred += 1
                return known[v]
            o = self._probe(cands[i], side, why)
            known[v] = o
            return o

        lo = max([i for i in range(n) if vec[cands[i]] == vec[self.green["sha"]]], default=-1)
        hi = n - 1
        notes = []
        pos_all = {x: i for i, x in enumerate(commits)}
        for _round in range(MAX_ROUNDS):
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if outcome(mid, "bisect candidates") == "fail":
                    hi = mid
                else:
                    lo = mid
            if hi <= lo or hi < 0:
                return None, "unknown", "no candidate commit fails"
            c = cands[hi]
            if not self.confirm:
                return {"commit": c}, "confirmed", "unconfirmed (confirmation off)"
            ok, why = self._confirm_commit(c, side)
            if not ok:
                notes.append(why)
                pos = {s: i for i, s in enumerate(commits)}
                if why == "parent fails":
                    low = pos.get(cands[lo], -1) if lo >= 0 else -1
                    return self._bisect_all(commits, low, pos[c] - 1, side, notes)
                return self._bisect_all(commits, pos[c], len(commits) - 1, side, notes)
            # non-monotonic history, red side (review R-019b, N1; round 4): C is the answer only if every commit
            # of (C, red] fails. A later commit is inferred when an earlier replay on this side (or the CI key of
            # this side) recorded inputs that all have the same value there (key validity); the others are
            # replayed, several at a time, up to the budget. A pass restarts the search above it; an unchecked
            # rest withholds the answer.
            st, info = self._red_check(commits, pos_all[c], side, infer=True, undo_of=c)
            if st == "pass":
                j = info
                notes.append(f"{c[:10]} fixed later: {commits[j][:10]} passes")
                rest_c = [x for x in cands if pos_all[x] > j]
                if not rest_c:
                    return self._bisect_all(commits, j, len(commits) - 1, side, notes)
                cands = [commits[j]] + rest_c
                n = len(cands)
                vec[commits[j]] = self._vector(commits[j])
                for x in rest_c:
                    vec.setdefault(x, self._vector(x))
                known.setdefault(vec[commits[j]], "pass")
                lo, hi = 0, n - 1
                continue
            if st == "unchecked":
                return None, "unknown", "; ".join(notes + [
                    f"ambiguous: {c[:10]} is confirmed, but {info} later commits were neither replayed nor inferred "
                    f"(one of them may fix it, and a newer commit break it again)",
                    f"suspect {c}"])
            return {"commit": c}, "confirmed", "; ".join(notes)
        return None, "unknown", "the history changes outcome more than %d times" % MAX_ROUNDS

    def _red_check(self, commits, c_pos: int, side, infer: bool, undo_of: str) -> tuple[str, int | None]:
        """Every commit of (commits[c_pos], red] must fail on ``side``. Returns ("ok", None), ("pass", j) with j the
        newest commit found passing, or ("unchecked", count) when the budget ran out.

        Inferred (no replay): the red head; a commit replayed before on this side; with ``infer``, a commit whose
        values of every input recorded by a replay (or CI key) of this side equal that run's (``agrees``). The
        rest is grouped by its values of every input any such run recorded (one replay decides a group), and
        replayed ``self.workers`` at a time: groups holding a commit that undoes the named one first, then newest
        first. After each batch the inference is redone with the new replays' keys."""
        last = len(commits) - 1
        mode_paths = sorted({p for x in commits[c_pos + 1:] for p in mode_changes(self.repo, x)})
        undo = {j for j in range(c_pos + 1, last) if self._undoes(undo_of, commits[j])}
        while True:
            pending = []
            for j in range(last - 1, c_pos, -1):
                o, _src = self._infer(commits[j], side, mode_paths) if infer else (self._known(commits[j], side), "")
                if o == "pass":
                    self.inferred += 0 if _src == "replayed" else 1
                    return "pass", j
                if o is None:
                    pending.append(j)
                elif _src not in ("replayed", ""):
                    self.red_inferred.add(commits[j])  # decided by key validity, no replay
            if not pending:
                return "ok", None
            groups: dict = {}
            runs = self.runs.get(self._side_sid(side), ()) if infer else ()
            if runs:
                paths = sorted({p for r in runs for p in r.items})
                dirs = sorted({d for r in runs for d in r.dirs})
                for j in pending:
                    t, nm = tree_of(self.repo, commits[j])
                    sig = (tuple(t.get(p) for p in paths), tuple(nm.get(d) for d in dirs),
                           tuple((t.get(p) or (None,))[0] for p in mode_paths))
                    groups.setdefault(sig, []).append(j)
            else:
                for j in pending:
                    groups[(j,)] = [j]
            order = sorted(groups.values(), key=lambda g: (not any(j in undo for j in g), -max(g)))
            left = self.budget + len(undo) - self.red_probes
            if left <= 0:
                return "unchecked", len(pending)
            batch = [max(g) for g in order[: min(self.workers, left)]]
            self.red_probes += len(batch)
            outs = self._probe_many([commits[j] for j in batch], side, "red-side check")
            passed = [j for j, o in zip(batch, outs) if o == "pass"]
            if passed:
                return "pass", max(passed)
            # "missing" (the test does not exist there) counts as not passing, as in the ground truth (a walk back
            # to the newest passing commit)
            bad = [j for j, o in zip(batch, outs) if o not in ("fail", "missing")]
            if bad:  # the commit cannot be decided
                return "unchecked", len(pending)

    def _ci_runs(self, side, g, r, inputs: bool, build: bool) -> None:
        """The CI keys as runs of the commit-search side, where they are valid there: the green key always (the
        side is the green environment, or no non-code input differs), the red key only when the side is the red
        job's own environment with the same runtime identity."""
        sid = self._side_sid(side)
        for side_ok, key, sha, outcome in (
                (True, self.green["key"], self.green["sha"], "pass"),
                (not inputs and not build and r.get("runtime") == g.get("runtime"), self.red["key"], self.red["sha"],
                 "fail")):
            if not side_ok:
                continue
            try:
                with open(key) as fh:
                    kd = json.load(fh)
            except (OSError, ValueError):
                continue
            run = run_from_key(self.repo, sha, outcome, kd, test_entry(kd, self.nodeid), self.nodeid,
                               f"CI key ({outcome})")
            if run is not None:
                self.runs.setdefault(sid, []).append(run)

    def _hunks(self, sha: str) -> tuple[set, set]:
        """(added lines, removed lines) of a commit against its first parent, stripped, blank lines left out."""
        key = ("hunks", str(self.repo), sha)
        if key not in _FACTS_CACHE:
            out = git(self.repo, "diff", "--no-color", "-U0", f"{sha}^", sha, check=False)
            add, rem = set(), set()
            for line in out.splitlines():
                if line.startswith(("+++", "---")):
                    continue
                if line.startswith("+") and line[1:].strip():
                    add.add(line[1:].strip())
                elif line.startswith("-") and line[1:].strip():
                    rem.add(line[1:].strip())
            _FACTS_CACHE[key] = (add, rem)
        return _FACTS_CACHE[key]

    def _undoes(self, c: str, d: str) -> bool:
        """Does commit d take back part of commit c's change (removes a line c added and, if c removed lines,
        adds one of them back)?"""
        ca, cr = self._hunks(c)
        da, dr = self._hunks(d)
        return bool(ca & dr) and (not cr or bool(cr & da))

    def _confirm_commit(self, c: str, side) -> tuple[bool, str]:
        p = self._parent(c)
        po = self._probe_n(p, side, "confirm: parent passes")
        if po != "pass":
            return False, "parent fails" if po == "fail" else "parent flaky (passes and fails)"
        co = self._probe_n(c, side, "confirm: culprit fails")
        if co != "fail":
            return False, "culprit passes" if co == "pass" else "culprit flaky (passes and fails)"
        return True, ""

    def _probe_n(self, sha, side, why) -> str:
        """``self.reps`` replays (the first may be a memoised one): "pass", "fail" or "flaky"."""
        outs = {self._probe(sha, side, why)}
        env_vars, dists, venv, expect = side
        for i in range(1, self.reps):
            outs.add(self._replay(sha, env_vars, dists, venv, expect_runtime=expect, why=f"{why} (repeat {i + 1})",
                                  memo=False))
        return outs.pop() if len(outs) == 1 else "flaky"

    def _bisect_all(self, commits, lo: int, hi: int, side, notes) -> tuple[dict | None, str, str]:
        """Plain binary search over every first-parent commit in (commits[lo], commits[hi]] (lo = -1: green),
        no pruning, every probe replayed; commits[hi] is known red, commits[lo] known green. Then confirmed.

        Red side (review R-019b, N2): the answer must also be the newest transition, so every commit after it up
        to the red head must fail. With no footprint to infer from, each unreplayed later commit is probed, newest
        first, up to RED_BUDGET (round 4); a pass restarts the search above it, and an unprobed rest withholds the answer.
        """
        notes = notes + ["footprint pruning missed an input: searched every commit"]
        last = len(commits) - 1
        for _round in range(MAX_ROUNDS):
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if self._probe(commits[mid], side, "bisect all commits") == "fail":
                    hi = mid
                else:
                    lo = mid
            if hi < 0 or hi <= lo:
                return None, "unknown", "; ".join(notes + ["no commit fails"])
            c = commits[hi]
            ok, why = self._confirm_commit(c, side)
            if not ok:
                return None, "unknown", "; ".join(notes + [f"{c[:10]}: {why} (outcomes are not monotonic)"])
            # no footprint to trust here (the search fell back because the key missed an input, or found no
            # differing input): no key-validity inference, every later commit is replayed (several at a time)
            st, info = self._red_check(commits, hi, side, infer=False, undo_of=c)
            if st == "pass":
                notes.append(f"{c[:10]} fixed later: {commits[info][:10]} passes")
                lo, hi = info, last
                continue
            if st == "unchecked":
                return None, "unknown", "; ".join(notes + [
                    f"ambiguous: {c[:10]} is confirmed, but {info} later commits were not replayed "
                    f"(one of them may fix it, and a newer commit break it again)", f"suspect {c}"])
            return {"commit": c}, "confirmed", "; ".join(notes)
        return None, "unknown", "; ".join(notes + ["the history changes outcome more than %d times" % MAX_ROUNDS])

    def _probe(self, sha, side, why):
        env_vars, dists, venv, expect = side
        return self._replay(sha, env_vars, dists, venv, expect_runtime=expect, why=why)

    # -- input search --------------------------------------------------------------------------------------
    def _search_inputs(self, inputs, g, r, green_env, red_env, green_dists, build, g_venv):
        """Optimistic binary split, then confirmation on both sides (review R-019 H1, R-019b N4).

        A set S of inputs (one input, or inputs needed together, found by ddmin) is named only if
        * green side: S applied alone to the green environment fails, and
        * red side: the red environment without S (every other candidate input applied) passes.
        When the red side still fails, another input (or set) breaks the test on its own, and S may only be masked
        (e.g. a flag whose compatibility shim is also set): the search continues with ddmin over the rest R (which
        fails, as just replayed). A set found twice, or no set found, ends in "unknown"."""
        tried: dict = {}

        def test(subset, why, reps=1):
            key = tuple(sorted(c["id"] for c in subset))
            env_vars, dists = self._apply(green_env, red_env, green_dists, r, subset)
            args = self.red.get("det_args") if any(c["kind"] == "epoch" for c in subset) else None
            outs = set()
            if key in tried:
                outs.add(tried[key])
            else:
                o = self._replay(self.red["sha"], env_vars, dists if build else None, g_venv, why=why, args=args)
                tried[key] = o
                outs.add(o)
            for i in range(1, reps):
                outs.add(self._replay(self.red["sha"], env_vars, dists if build else None, g_venv,
                                      why=f"{why} (repeat {i + 1})", args=args, memo=False))
            return outs.pop() if len(outs) == 1 else "flaky"

        if self.confirm and test([], "confirm: red code, green environment passes", self.reps) != "pass":
            return None, "unknown", "the red code fails in the green environment too"
        cur = list(inputs)
        while len(cur) > 1:
            half = cur[: len(cur) // 2]
            cur = half if test(half, f"apply {[c['id'] for c in half]}") == "fail" else cur[len(cur) // 2:]
        if not self.confirm:
            return {"input": cur[0]["id"], "detail": cur[0]}, "confirmed", "unconfirmed (confirmation off)"
        notes = []
        if test(cur, f"confirm: {cur[0]['id']} alone fails", self.reps) == "fail":
            found = cur
        elif len(inputs) > 1 and test(inputs, "apply all candidate inputs") == "fail":
            found = self._ddmin(list(inputs), test)
            notes.append("found by ddmin")
        else:
            return None, "unknown", "the differing inputs applied to the green environment do not reproduce the red"
        seen = []
        for _round in range(MAX_ROUNDS):
            ids = sorted(c["id"] for c in found)
            if ids in seen:
                return None, "unknown", "; ".join(notes + [
                    f"more than one input breaks the test on its own: {seen}; removing any one of them leaves the "
                    "red job red"])
            seen.append(ids)
            if len(found) > 1 and test(found, f"confirm: {ids} together fail", self.reps) != "fail":
                return None, "unknown", "; ".join(notes + [f"{ids} together do not reproduce the red"])
            rest = [c for c in inputs if c["id"] not in ids]
            ro = test(rest, f"confirm: red environment without {ids} passes", self.reps) if rest else "pass"
            if ro == "pass":
                if len(found) == 1:
                    return {"input": ids[0], "detail": found[0]}, "confirmed", "; ".join(notes)
                return {"input": ids[0], "inputs": ids, "together": True}, "confirmed", "; ".join(notes + [
                    f"{len(ids)} inputs needed together (each alone leaves the test green)"])
            if ro != "fail":
                return None, "unknown", "; ".join(notes + [f"red environment without {ids}: {ro}"])
            notes.append(f"{ids} reproduces the red alone, but the red environment without it still fails "
                         "(masked, or another input breaks it too): searched the other inputs")
            found = self._ddmin(rest, test)
        return None, "unknown", "; ".join(notes + ["no input set explains the red on both sides"])

    @staticmethod
    def _ddmin(c: list, test) -> list:
        """Zeller's ddmin: a 1-minimal subset of ``c`` (which fails) that still fails."""
        n = 2
        while len(c) >= 2:
            size = len(c) // n
            chunks = [c[i * size: (i + 1) * size] if i < n - 1 else c[i * size:] for i in range(n)]
            nxt = None
            for ch in chunks:
                if test(ch, f"ddmin {[x['id'] for x in ch]}") == "fail":
                    nxt, n = ch, 2
                    break
            if nxt is None and n > 2:
                for ch in chunks:
                    comp = [x for x in c if x not in ch]
                    if test(comp, f"ddmin {[x['id'] for x in comp]}") == "fail":
                        nxt, n = comp, max(n - 1, 2)
                        break
            if nxt is None:
                if n >= len(c):
                    break
                n = min(len(c), 2 * n)
            else:
                c = nxt
        return c

    # -- uncontrolled sources (review R-019 H3, R-019b N3) ------------------------------------------------
    def _uncontrolled(self, g, r, green_env, red_env, green_dists, build, g_venv):
        """None when the search may go on; else (status, why).

        A flagged test is replayed at green GREEN_REPEATS times; if it ever fails there, there is no culprit
        ("unknown: flaky"). Flags other than entropy and child processes end in "unknown" (one replay is no
        proof). A child process (``spawn``: not followed, or followed and found reading the network, the clock or
        /dev) cannot be controlled either: the red side is replayed GREEN_REPEATS times too (it must fail every
        time), and every later confirmation replays GREEN_REPEATS times (all pass at the parent, all fail at the
        culprit). In-process entropy alone is then searched under controlled entropy (``--det-urandom``)."""
        flags = set((g["test"] or {}).get("flags", [])) | set((r["test"] or {}).get("flags", []))
        if child_processes(g["test"]) or child_processes(r["test"]):
            flags.add("spawn")  # a followed child: its outcome may change from run to run as well
        nondet = sorted(f for f in flags if f in NONDET_FLAGS)
        if not nondet:
            return None
        gd = green_dists if build else None
        for i in range(GREEN_REPEATS):
            if self._replay(self.green["sha"], green_env, gd, g_venv, why="green repeated (uncontrolled source)",
                            memo=False) == "fail":
                return "unknown", f"flaky: reads {nondet}; fails at the green commit (green replay {i + 1})"
        if any(f not in REPEATABLE_FLAGS for f in nondet):
            return "unknown", f"reads {nondet}, which --det does not control: one replay per step is no proof"
        r_venv = self.red.get("venv") or g_venv
        if "spawn" in nondet:
            for i in range(GREEN_REPEATS):
                if self._replay(self.red["sha"], red_env, None, r_venv, why="red repeated (child process)",
                                memo=False) == "pass":
                    return "unknown", f"flaky: reads {nondet}; passes at the red commit (red replay {i + 1})"
            self.reps = GREEN_REPEATS
        if "entropy" in nondet:
            self.det_args.append("--det-urandom")
            og = self._replay(self.green["sha"], green_env, gd, g_venv, why="green, entropy controlled")
            orr = self._replay(self.red["sha"], red_env, None, r_venv, why="red, entropy controlled")
            if not (og == "pass" and orr == "fail"):
                return "unknown", f"flaky: reads entropy; under controlled entropy green={og}, red={orr}"
        return None

    # -- main ----------------------------------------------------------------------------------------------
    def run(self) -> dict:
        t0 = time.perf_counter()
        g = load_key(self.green["key"], self.nodeid)
        res = {"nodeid": self.nodeid}
        try:
            r = load_key(self.red["key"], self.nodeid)
        except (OSError, ValueError):
            # the red run wrote no key (the session failed before the end, e.g. a configuration warning turned
            # into an error): the red side is the green key minus the test, plus the two job definitions
            r = {**g, "test": None}
            res["red_key"] = "missing (the red run wrote no key)"
        if g["test"] is None:
            return {**res, "culprit": None, "status": "unknown", "why": "no green key for the test",
                    "executions": 0}
        commits = self.commits if self.commits is not None else \
            [x for x in git(self.repo, "rev-list", "--first-parent", "--reverse",
                            f"{self.green['sha']}..{self.red['sha']}").split() if x]
        if res.get("red_key", "").startswith("missing (the red run wrote"):
            gt = g["test"]
            changes = [{"kind": "code", "id": k, "what": k.split(":", 1)[0], "path": k.split(":", 1)[1].split("::")[0],
                        "unit": k.split("::", 1)[1] if "::" in k else None} for k in gt.get("code", {})]
            changes += [{"kind": "data", "id": f"data:{p}", "path": p, "inrepo": True}
                        for p in gt.get("data", {}) if not os.path.isabs(p)]
            ge, re_ = self.green.get("env") or {}, self.red.get("env") or {}
            changes += [{"kind": "env", "id": f"env:{n}", "name": n} for n in sorted(set(ge) | set(re_))
                        if ge.get(n) != re_.get(n)]
        elif r["test"] is None:
            # the test never ran in red (collection or import error): every input of the green key is suspect
            gt = g["test"]
            changes = [{"kind": "code", "id": k, "what": k.split(":", 1)[0], "path": k.split(":", 1)[1].split("::")[0],
                        "unit": k.split("::", 1)[1] if "::" in k else None} for k in gt.get("code", {})]
            changes += [{"kind": "data", "id": f"data:{p}", "path": p, "inrepo": not os.path.isabs(p)}
                        for p in gt.get("data", {})]
            changes += diff_keys({**g, "test": None}, {**r, "test": None})
            res["red_key"] = "missing (test did not run in red)"
        else:
            changes = diff_keys(g, r)
        res["changed_inputs"] = len(changes)
        loaded = g["loaded"] | r["loaded"]
        plugins = {norm_dist(p.split("==")[0]) for p in (g["config_info"].get("plugins", []) +
                                                         r["config_info"].get("plugins", []))}
        inputs, pruned = [], []
        for c in changes:
            if c["kind"] in ("code",) or (c["kind"] == "data" and c.get("inrepo")):
                continue
            if c["kind"] == "dist" and self.prune_dists and c["name"] not in loaded | plugins | {"pytest"}:
                pruned.append(c["id"])
                continue
            inputs.append(c)
        one_side = []
        for c in list(inputs):
            if c["kind"] == "data" and not c.get("inrepo"):
                gd, rd = (g["test"] or {}).get("data", {}), (r["test"] or {}).get("data", {})
                if (c["path"] in gd) != (c["path"] in rd):
                    dep = gd.get(c["path"]) or rd.get(c["path"])
                    if dep_holds(c["path"], dep):
                        one_side.append(c["id"])
                        inputs.remove(c)
        inputs, grouped = group_inputs(inputs, self.green.get("env") or {}, self.red.get("env") or {})
        if one_side:
            grouped["(file read by one run only, content unchanged)"] = one_side
        res["grouped_inputs"] = grouped
        cands = commit_candidates(self.repo, commits, changes)
        self._items = [c for c in changes if c["kind"] == "code" or (c["kind"] == "data" and c.get("inrepo"))]
        mode_paths = sorted({p for sha in cands for p in mode_changes(self.repo, sha)})
        self._items += [{"kind": "mode", "id": f"mode:{p}", "path": p} for p in mode_paths]
        res.update({"commits_in_range": len(commits), "commit_candidates": len(cands),
                    "input_candidates": [c["id"] for c in inputs], "pruned_inputs": pruned,
                    "mode_candidates": mode_paths, "candidates": cands})
        green_env = dict(self.green.get("env") or {})
        red_env = dict(self.red.get("env") or {})
        need_env = bool(inputs)
        green_dists = {n: v for n, (v, _) in g["dists"].items()}
        self._green_dists = green_dists
        if any(c["id"] == "env:*" for c in inputs):
            named = {c["name"] for c in inputs if c["kind"] == "env"}
            ge, re_ = self.green.get("env") or {}, self.red.get("env") or {}
            extra = [{"kind": "env", "id": f"env:{n}", "name": n} for n in sorted(set(ge) | set(re_))
                     if ge.get(n) != re_.get(n) and n not in named]
            inputs = [c for c in inputs if c["id"] != "env:*"] + extra
            if not any(c["kind"] == "env" for c in inputs):
                inputs.append({"kind": "env", "id": "env:*", "name": "*"})
            res["input_candidates"] = [c["id"] for c in inputs]
        g_venv = self.green.get("venv")
        build = self.builder is not None and (any(c["kind"] == "dist" for c in inputs) or g_venv is None)
        culprit, status, why = None, "unknown", ""
        unc = self._uncontrolled(g, r, green_env, red_env, green_dists, build, g_venv) if self.confirm else None
        res["uncontrolled"] = sorted(f for f in set((g["test"] or {}).get("flags", []))
                                     | set((r["test"] or {}).get("flags", [])) if f in NONDET_FLAGS)
        if child_processes(g["test"]) or child_processes(r["test"]):
            res["uncontrolled"] = sorted(set(res["uncontrolled"]) | {"spawn"})
            res["child_evidence"] = (child_processes(r["test"]) or child_processes(g["test"]))[:4]
        res["repeats"] = self.reps
        if unc is not None:
            status, why = unc
        else:
            if cands and need_env:
                o = self._replay(self.red["sha"], green_env, green_dists if build else None, g_venv,
                                 expect_runtime=g["runtime"], why="red code, green environment")
                if o == "fail":
                    need_env = False
                else:
                    res["code_needed_check"] = True
                    cands = []
            if cands:
                env_vars = green_env if inputs else red_env
                if build:  # replays in the environment rebuilt from the green key, at the CI path
                    side = (env_vars, green_dists, None, g["runtime"])
                else:
                    side = (env_vars, None, g_venv if inputs else self.red.get("venv"), g["runtime"])
                self._ci_runs(side, g, r, bool(inputs), build)
                culprit, status, why = self._search_commits(commits, cands, side)
            elif inputs:
                culprit, status, why = self._search_inputs(inputs, g, r, green_env, red_env, green_dists, build,
                                                           g_venv)
                if culprit and res.get("code_needed_check") and self.confirm:
                    # the inputs were searched on the red code: do they break the green code alone too?
                    sub = [c for c in inputs if c["id"] in (culprit.get("inputs") or [culprit["input"]])]
                    ev, dd = self._apply(green_env, red_env, green_dists, r, sub)
                    if self._replay(self.green["sha"], ev, dd if build else None, g_venv,
                                    why="confirm: input breaks the green code") != "fail":
                        culprit, status, why = None, "unknown", \
                            f"{culprit['input']} reproduces the red only with code from the range"
            elif commits:
                # nothing in the key explains the red: an input outside the key (file mode, a subprocess's
                # reads...). Plain search over every commit, confirmed.
                culprit, status, why = self._bisect_all(commits, -1, len(commits) - 1,
                                                        (red_env, None, self.red.get("venv") or g_venv,
                                                         g["runtime"]), ["no differing input in the key"])
            else:
                why = "no candidate: no differing input explains the red"
        ex = [s["exact"] for s in self.steps if "exact" in s]
        if culprit is not None and build and ex and not all(ex):
            culprit, status, why = None, "unknown", "green environment not rebuilt exactly: answer not confirmed"
        res["culprit"] = culprit
        res["status"] = status if culprit is not None else "unknown"
        res["why"] = why
        res["executions"] = len(self.steps)
        res["inferred"] = self.inferred
        res["red_probes"] = self.red_probes
        res["red_inferred"] = len(self.red_inferred)
        res["workers"], res["budget"], res["batches"] = self.workers, self.budget, self.batches
        res["infer_keys"] = self.infer_keys
        res["wall_critical"] = critical_wall(self.steps)
        exa = [s["exact"] for s in self.steps if "exact" in s]
        res["green_env_replays"] = len(exa)
        res["rebuilt_exactly"] = all(exa) if exa else None
        res["rebuilds"] = self.rebuilds
        res["steps"] = self.steps
        res["wall"] = round(time.perf_counter() - t0, 2)
        return res

    @staticmethod
    def _apply(green_env, red_env, green_dists, r, subset):
        env_vars = dict(green_env)
        dists = dict(green_dists)
        for c in subset:
            if c["id"] == "env:*":
                env_vars.update(red_env)
                env_vars.update({k: None for k in green_env if k not in red_env})
            elif c["kind"] in ("env", "tzlocale"):
                env_vars[c["name"]] = red_env.get(c["name"])
            elif c["kind"] == "dist":
                if c["red"] is None:
                    dists.pop(c["name"], None)
                else:
                    dists[c["name"]] = c["red"]
        return env_vars, dists
