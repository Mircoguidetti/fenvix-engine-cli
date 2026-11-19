"""Exact-culprit finder, prototype (validation of idea 2 only; not the product).

Input: one red test, the proof key of its red run and the proof key of its last green run (both written by
``pytest --det --det-cache=DIR --det-cache-keys=PATH``), and how to rebuild each side (commit, CI variables,
installed distributions). Output: one commit or one input.

1. Diff the two keys: every input whose digest differs (code units, module skeletons, conftest hooks, files read,
   environment variables read, installed distributions, interpreter, configuration, time zone and locale).
2. Prune: a distribution is a candidate only if the test's process loaded it; a commit is a candidate only if it
   changes one of the differing code or data inputs (checked per unit: the commit must change that unit's digest).
3. Search with one deterministic replay per step (``--det``, fixed epoch, empty cache): first "red code in the
   green environment" when both kinds of candidate exist, then a binary search over the candidate commits or a
   binary split of the candidate inputs. Single-culprit assumption.
4. Every replay records the runtime identity; a replay meant to run in the green environment counts as an exact
   rebuild only when its runtime digest equals the green key's.
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
    t = d["tests"].get(nodeid)
    if t is None:  # parametrised: the first entry of the same function
        base = nodeid.split("[", 1)[0]
        for k, v in d["tests"].items():
            if k.split("[", 1)[0] == base:
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


def commit_candidates(repo, commits: list[str], changes: list[dict]) -> list[str]:
    """Commits of ``commits`` (oldest first) that change at least one of the differing in-repository inputs."""
    items = [c for c in changes if c["kind"] == "code" or (c["kind"] == "data" and c.get("inrepo"))]
    if not items:
        return []
    by_path: dict[str, list[dict]] = {}
    for c in items:
        by_path.setdefault(c["path"], []).append(c)
    dirs = [c for c in items if c["kind"] == "data"]
    out = []
    for sha in commits:
        touched = set(git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent",
                          sha).split())
        hit = False
        for path in touched & set(by_path):
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
class Finder:
    """side = {"sha", "env": {var: value or None}, "venv": Path or None, "key": path}"""

    def __init__(self, repo, nodeid: str, green: dict, red: dict, builder: EnvBuilder | None = None,
                 prune_dists=True, det_args=(), commits: list[str] | None = None):
        self.repo, self.nodeid, self.green, self.red = Path(repo), nodeid, green, red
        self.builder = builder
        self.prune_dists = prune_dists
        self.det_args = list(det_args)
        self.commits = commits
        self.steps: list[dict] = []
        self.rebuilds: list[dict] = []

    # -- one replay
    def _replay(self, sha: str, env_vars: dict, dists: dict | None, venv: Path | None, expect_runtime=None,
                why="", args=None):
        if dists is not None:
            at = self.green.get("prefix") if dists == self._green_dists else None
            venv, secs, fresh = self.builder.venv_for(self.repo, dists, at=at)
            if fresh:
                self.rebuilds.append({"seconds": secs})
        checkout(self.repo, sha)
        with tempfile.TemporaryDirectory() as td:
            kp = os.path.join(td, "k.json")
            r = run_det(self.repo, venv, self.nodeid, env_vars, keys=kp,
                        args=self.det_args if args is None else args)
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
        return r["outcome"]

    def run(self) -> dict:
        t0 = time.perf_counter()
        g = load_key(self.green["key"], self.nodeid)
        r = load_key(self.red["key"], self.nodeid)
        res = {"nodeid": self.nodeid}
        if g["test"] is None:
            return {**res, "culprit": None, "why": "no green key for the test", "executions": 0}
        commits = self.commits if self.commits is not None else \
            [x for x in git(self.repo, "rev-list", "--first-parent", "--reverse",
                            f"{self.green['sha']}..{self.red['sha']}").split() if x]
        if r["test"] is None:
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
        # a file outside the repository that only one run read, with the value that run recorded still on disk:
        # the read differs (something else changed what the test does), not the file
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
        res.update({"commits_in_range": len(commits), "commit_candidates": len(cands),
                    "input_candidates": [c["id"] for c in inputs], "pruned_inputs": pruned})
        green_env = dict(self.green.get("env") or {})
        red_env = dict(self.red.get("env") or {})
        need_env = bool(inputs)
        green_dists = {n: v for n, (v, _) in g["dists"].items()}
        self._green_dists = green_dists
        # "env:*" (the test enumerated the environment): the candidates are the variables the two jobs set
        # differently, known from the job definitions
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
        # the green environment is rebuilt from the green key's distribution list when a distribution is a
        # candidate, or when no green environment is at hand (the honest case: the CI machine is gone)
        build = self.builder is not None and (any(c["kind"] == "dist" for c in inputs) or g_venv is None)
        culprit = None
        if cands and need_env:
            # does the code alone explain the red? red commit, green environment
            o = self._replay(self.red["sha"], green_env, green_dists if build else None, g_venv,
                             expect_runtime=g["runtime"], why="red code, green environment")
            if o == "fail":
                need_env = False
            else:
                cands = []
        if cands:
            env_vars = green_env if bool(inputs) else red_env
            if build:  # replays in the environment rebuilt from the green key, at the CI path
                dists, venv = green_dists, None
            else:
                dists, venv = None, (g_venv if inputs else self.red.get("venv"))
            expect = g["runtime"]
            lo, hi = -1, len(cands) - 1  # cands[hi] is known red (nothing after it changes an input)
            while hi - lo > 1:
                mid = (lo + hi) // 2
                o = self._replay(cands[mid], env_vars, dists, venv, expect_runtime=expect, why="bisect candidates")
                if o == "fail":
                    hi = mid
                else:
                    lo = mid
            culprit = {"commit": cands[hi]}
        elif inputs:
            cur = list(inputs)
            while len(cur) > 1:
                half = cur[: len(cur) // 2]
                env_vars, dists = self._apply(green_env, red_env, green_dists, r, half)
                args = self.red.get("det_args") if any(c["kind"] == "epoch" for c in half) else None
                o = self._replay(self.red["sha"], env_vars, dists if build else None, g_venv,
                                 why=f"apply {[c['id'] for c in half]}", args=args)
                cur = half if o == "fail" else cur[len(cur) // 2:]
            culprit = {"input": cur[0]["id"], "detail": cur[0]}
        else:
            res["why"] = "no candidate: no differing input explains the red"
        res["culprit"] = culprit
        res["executions"] = len(self.steps)
        ex = [s["exact"] for s in self.steps if "exact" in s]
        res["green_env_replays"] = len(ex)
        res["rebuilt_exactly"] = all(ex) if ex else None
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
