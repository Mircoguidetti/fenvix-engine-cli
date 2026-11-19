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
from common import checkout, git, git_out, run_det, sh  # noqa: E402

import subprocess  # noqa: E402

_FACTS_CACHE: dict = {}
# detpy's own files that a key may list as data: the bytecode cache (derived from the sources, which are inputs
# themselves) and the per-run cache directory of this harness (clock shim)
_OWN_FILES = ("/.cache/detpy/", "/detrun-")


# ---------------------------------------------------------------------------- keys
def norm_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def load_key(path: str, nodeid: str) -> dict | None:
    with open(path) as fh:
        d = json.load(fh)
    def same(a: str, b: str) -> bool:  # node ids are relative to pytest's rootdir, which may be a subdirectory
        return a == b or a.endswith("/" + b) or b.endswith("/" + a)

    t = d["tests"].get(nodeid)
    if t is None:
        t = next((v for k, v in d["tests"].items() if same(k, nodeid)), None)
    if t is None:  # parametrised: the first entry of the same function
        base = nodeid.split("[", 1)[0]
        for k, v in d["tests"].items():
            if same(k.split("[", 1)[0], base):
                t = v
                break
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
# flags of a key that make one replay no proof: the test read a source --det does not control
NONDET_FLAGS = ("rclock", "connect", "csock", "dns", "entropy", "net")
GREEN_REPEATS = 5  # replays of the green side when the key flags an uncontrolled source
RETOUCH_CAP = 6  # later commits that touch the named commit's inputs again, probed for a newer transition;
#               beyond it the answer is withheld (unknown, ambiguous) rather than stated
MAX_ROUNDS = 6


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
        self._memo: dict = {}

    # -- one replay
    def _replay(self, sha: str, env_vars: dict, dists: dict | None, venv: Path | None, expect_runtime=None,
                why="", args=None, memo=True):
        args = self.det_args if args is None else list(args) + [a for a in self.det_args if a not in args]
        mk = (sha, tuple(sorted((k, v) for k, v in (env_vars or {}).items())),
              tuple(sorted((dists or {}).items())) if dists is not None else None, str(venv), tuple(args))
        if memo and mk in self._memo:
            return self._memo[mk]
        if dists is not None:
            at = self.green.get("prefix") if dists == self._green_dists else None
            venv, secs, fresh = self.builder.venv_for(self.repo, dists, at=at)
            if fresh:
                self.rebuilds.append({"seconds": secs})
        checkout(self.repo, sha)
        with tempfile.TemporaryDirectory() as td:
            kp = os.path.join(td, "k.json")
            r = run_det(self.repo, venv, self.nodeid, env_vars, keys=kp, args=args)
            runtime = None
            try:
                with open(kp) as fh:
                    kd = json.load(fh)
                runtime = kd.get("runtime")
            except (OSError, ValueError):
                pass
        step = {"sha": sha, "why": why, "outcome": r["outcome"], "wall": round(r["wall"], 2), "runtime": runtime}
        if expect_runtime is not None:
            step["exact"] = runtime == expect_runtime
        self.steps.append(step)
        self._memo[mk] = r["outcome"]
        return r["outcome"]

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
        * a later candidate that changes C's inputs again is probed (up to RETOUCH_CAP): if it passes, the red at
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
            # non-monotonic history: a later commit that touches C's inputs again may have fixed it
            ix = [k for k, (a, b) in enumerate(zip(self._vector(self._parent(c)), vec[c])) if a != b]
            later = [j for j in range(hi + 1, n)
                     if any(vec[cands[j]][k] != vec[cands[j - 1]][k] for k in ix)]
            # commits whose diff undoes part of C's diff (a revert, or a fix folded into other work) first,
            # all of them; then the other re-touching commits, up to RETOUCH_CAP
            undo = [j for j in range(hi + 1, n) if self._undoes(c, cands[j])]
            order = undo + [j for j in later if j not in undo]
            budget = len(undo) + RETOUCH_CAP
            restarted = False
            for j in order[:budget]:
                if outcome(j, "re-touch check") == "pass":
                    notes.append(f"{c[:10]} re-broken later: candidate {cands[j][:10]} passes")
                    lo, hi = j, n - 1
                    restarted = True
                    break
            if restarted:
                continue
            if len(order) > budget:
                unchecked = len(order) - budget
                return None, "unknown", "; ".join(notes + [
                    f"ambiguous: {c[:10]} is confirmed, but {unchecked} later commits change its inputs again and "
                    f"were not replayed (one of them may fix it, and a newer commit break it again)",
                    f"suspect {c}"])
            return {"commit": c}, "confirmed", "; ".join(notes)
        return None, "unknown", "the history changes outcome more than %d times" % MAX_ROUNDS

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
        if self._probe(p, side, "confirm: parent passes") != "pass":
            return False, "parent fails"
        if self._probe(c, side, "confirm: culprit fails") != "fail":
            return False, "culprit passes"
        return True, ""

    def _bisect_all(self, commits, lo: int, hi: int, side, notes) -> tuple[dict | None, str, str]:
        """Plain binary search over every first-parent commit in (commits[lo], commits[hi]] (lo = -1: green),
        no pruning, every probe replayed; commits[hi] is known red, commits[lo] known green. Then confirmed."""
        notes = notes + ["footprint pruning missed an input: searched every commit"]
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
        return {"commit": c}, "confirmed", "; ".join(notes)

    def _probe(self, sha, side, why):
        env_vars, dists, venv, expect = side
        return self._replay(sha, env_vars, dists, venv, expect_runtime=expect, why=why)

    # -- input search --------------------------------------------------------------------------------------
    def _search_inputs(self, inputs, g, r, green_env, red_env, green_dists, build, g_venv):
        """Optimistic binary split, the named input confirmed alone; when it does not reproduce the red alone,
        ddmin over the candidates finds the smallest set that does (inputs needed together, review R-019 H1)."""
        tried: dict = {}

        def test(subset, why):
            key = tuple(sorted(c["id"] for c in subset))
            if key in tried:
                return tried[key]
            env_vars, dists = self._apply(green_env, red_env, green_dists, r, subset)
            args = self.red.get("det_args") if any(c["kind"] == "epoch" for c in subset) else None
            o = self._replay(self.red["sha"], env_vars, dists if build else None, g_venv, why=why, args=args)
            tried[key] = o
            return o

        if self.confirm and test([], "confirm: red code, green environment passes") != "pass":
            return None, "unknown", "the red code fails in the green environment too"
        cur = list(inputs)
        while len(cur) > 1:
            half = cur[: len(cur) // 2]
            cur = half if test(half, f"apply {[c['id'] for c in half]}") == "fail" else cur[len(cur) // 2:]
        if not self.confirm:
            return {"input": cur[0]["id"], "detail": cur[0]}, "confirmed", "unconfirmed (confirmation off)"
        if test(cur, f"confirm: {cur[0]['id']} alone fails") == "fail":
            return {"input": cur[0]["id"], "detail": cur[0]}, "confirmed", ""
        if test(inputs, "apply all candidate inputs") != "pass" and len(inputs) > 1:
            found = self._ddmin(list(inputs), test)
            ids = sorted(c["id"] for c in found)
            if len(found) == 1:
                return {"input": ids[0], "detail": found[0]}, "confirmed", "found by ddmin"
            return {"input": ids[0], "inputs": ids, "together": True}, "confirmed", \
                f"{len(ids)} inputs needed together (each alone leaves the test green)"
        return None, "unknown", "the differing inputs applied to the green environment do not reproduce the red"

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

    # -- uncontrolled sources (review R-019, H3) -----------------------------------------------------------
    def _uncontrolled(self, g, r, green_env, red_env, green_dists, build, g_venv):
        """None when the replays are proofs; else (status, why). A flagged test is replayed at green up to
        GREEN_REPEATS times; if it ever fails there, there is no culprit. An entropy-only test is then searched
        with entropy controlled (``--det-urandom``) if green passes and red fails under it."""
        flags = set((g["test"] or {}).get("flags", [])) | set((r["test"] or {}).get("flags", []))
        nondet = sorted(f for f in flags if f in NONDET_FLAGS)
        if not nondet:
            return None
        gd = green_dists if build else None
        for i in range(GREEN_REPEATS):
            if self._replay(self.green["sha"], green_env, gd, g_venv, why="green repeated (uncontrolled source)",
                            memo=False) == "fail":
                return "unknown", f"flaky: reads {nondet}; fails at the green commit (green replay {i + 1})"
        if nondet != ["entropy"]:
            return "unknown", f"reads {nondet}, which --det does not control: one replay per step is no proof"
        self.det_args.append("--det-urandom")
        og = self._replay(self.green["sha"], green_env, gd, g_venv, why="green, entropy controlled")
        orr = self._replay(self.red["sha"], red_env, None, self.red.get("venv") or g_venv,
                           why="red, entropy controlled")
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
