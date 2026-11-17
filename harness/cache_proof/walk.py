#!/usr/bin/env python3
"""Cache-proof walk: measure ``pytest --det --det-cache=DIR`` over consecutive commits.

For every commit of a repository (first-parent, oldest first) the walker checks out, reinstalls when a dependency
spec changed, and runs:

* **A, cache run**: ``pytest --det --det-cache=C`` with one cache directory ``C`` kept across commits: reused
  results (with receipts), misses with their reasons, wall time;
* **B, full run**: ``pytest --det`` without the cache: the ground truth outcome and duration of every test, wall
  time. Every result A reused is compared with B's outcome at the same commit; a difference is re-run once more
  (B') to tell a wrong reuse (B' agrees with B) from a flaky test;
* every 10th commit (and the first), **capture overhead**: a run with an empty cache directory (everything recorded)
  and a second plain ``--det`` run.

``mode: suite`` runs the selected test files in one pytest process (the 14 libraries, sharded apps);
``mode: files`` runs one process per test file (Home Assistant, as in skip study 2); there, B runs every unit at
every 10th commit and a random sample of the units with reused results at the other commits.

    python harness/cache_proof/walk.py --spec harness/cache_proof/specs/sqlparse.json --work /tmp/w \\
        --out /tmp/sqlparse.json --wheel dist/detpy-*.whl --commits 5
"""

from __future__ import annotations

import argparse
import fnmatch
import glob
import gzip
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "harness"))
from detpy_harness import clean_env, detect_install  # noqa: E402

DEP_SPEC_NAMES = ("pyproject.toml", "setup.py", "setup.cfg", "uv.lock", "poetry.lock", "Pipfile.lock",
                  "pdm.lock", "tox.ini")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None, shell=False):
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                           errors="replace", stdin=subprocess.DEVNULL, shell=shell)
        return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out, time.perf_counter() - t0


def git(src, *args, check=True) -> str:
    return subprocess.run(["git", *args], cwd=src, capture_output=True, text=True, check=check,
                          errors="replace").stdout


def hfrac(seed: str, x: str) -> float:
    return int(hashlib.sha1(f"{seed}:{x}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def commit_results(paths, msg):
    """Commit result files to the current branch with rebase-retry (inside GitHub Actions)."""
    repo = Path(os.environ.get("CP_REPO", str(ROOT)))
    branch = os.environ.get("CP_BRANCH", "claude/loving-maxwell-58mv2w")
    for _ in range(12):
        sh(["git", "fetch", "-q", "origin", branch], cwd=repo)
        sh(["git", "reset", "-q", "--soft", f"origin/{branch}"], cwd=repo)
        sh(["git", "reset", "-q"], cwd=repo)
        for p in paths:
            sh(["git", "add", "-f", str(p)], cwd=repo)
        code, out, _ = sh(["git", "commit", "-q", "-m", msg], cwd=repo)
        if code and "nothing to commit" in out:
            return True
        code, out, _ = sh(["git", "push", "-q", "origin", f"HEAD:{branch}"], cwd=repo)
        if code == 0:
            return True
        time.sleep(5 + random.random() * 20)
    log("could not push results")
    return False


class Walk:
    def __init__(self, spec: dict, work: str, out: str, shard: int, nshards: int, budget_min: float, wheel: str,
                 commits: int | None, commit_every: int):
        self.spec = spec
        self.name = spec["name"]
        self.work = Path(work).resolve() / f"{self.name}-{shard}"
        self.src = self.work / "src"
        self.venv = self.work / "venv"
        self.py = str(self.venv / "bin" / "python")
        self.cache = self.work / "cache"
        self.out = Path(out).resolve()
        self.shard, self.nshards = shard, nshards
        self.budget = budget_min * 60
        self.wheel = os.path.abspath(wheel) if wheel else ""
        self.n = commits or spec.get("commits", 51)
        self.commit_every = commit_every
        self.t0 = time.time()
        self.mode = spec.get("mode", "suite")
        self.rng = random.Random(f"cache-proof:{self.name}:{shard}")
        self.result = {"spec": spec, "shard": shard, "nshards": nshards, "runner": os.environ.get("RUNNER_NAME", ""),
                       "cpus": os.cpu_count(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "steps": []}
        self.last_dep = None
        self.args: list[str] = []

    # -- setup -------------------------------------------------------------------
    def fmt(self, s: str) -> str:
        return s.replace("{py}", self.py).replace("{venv}", str(self.venv)).replace("{src}", str(self.src)) \
            .replace("{harness}", str(HERE))

    def clone(self) -> list[str]:
        self.work.mkdir(parents=True, exist_ok=True)
        if not (self.src / ".git").exists():
            code, out, _ = sh(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", self.spec["url"],
                               str(self.src)], timeout=1800)
            if code:
                raise RuntimeError(f"clone failed: {out[-400:]}")
        head = self.spec.get("head") or git(self.src, "rev-parse", "origin/HEAD").strip()
        if git(self.src, "rev-parse", "-q", "--verify", f"{head}^{{commit}}", check=False).strip() == "":
            sh(["git", "fetch", "-q", "origin", head], cwd=self.src, timeout=900)
        return git(self.src, "rev-list", "--first-parent", "-n", str(self.n), head).split()[::-1]

    def dep_hash(self) -> str:
        h = hashlib.sha256()
        pats = self.spec.get("install_files")
        if pats:
            files = sorted({f for p in pats for f in glob.glob(str(self.src / p), recursive=True)})
            for f in files:
                h.update(os.path.relpath(f, self.src).encode() + b"\0" + Path(f).read_bytes())
            return h.hexdigest()
        files = sorted(p for p in self.src.rglob("*") if p.is_file() and ".git" not in p.parts and (
            p.name in DEP_SPEC_NAMES or (p.name.startswith("requirements") and p.suffix in (".txt", ".in"))
            or (p.parent.name == "requirements" and p.suffix in (".txt", ".in"))) and len(p.relative_to(self.src).parts) <= 3)
        for p in files:
            h.update(str(p.relative_to(self.src)).encode() + b"\0" + p.read_bytes())
        return h.hexdigest()

    def env(self) -> dict:
        env = clean_env(self.py, self.spec.get("env", {}))
        env["PYTHONPATH"] = str(HERE)
        env.pop("PYTHONHASHSEED", None)
        return env

    def install(self) -> tuple[bool, str]:
        logf = self.work / "install.log"
        if self.spec.get("install"):
            for cmd in self.spec["install"]:
                code, out, _ = sh(self.fmt(cmd), cwd=self.src, env=dict(os.environ), timeout=5400, shell=True)
                with open(logf, "a") as fh:
                    fh.write(f"$ {cmd}\n-> {code}\n{out[-3000:]}\n")
                if code:
                    return False, f"{cmd[:60]}: {out[-300:]}"
            how = "spec"
        else:
            if not Path(self.py).exists():
                code, out, _ = sh(["uv", "venv", "-q", "--python", self.spec.get("python", "3.13"), str(self.venv)],
                                  timeout=600)
                if code:
                    return False, "venv: " + out[-300:]
            base = ["uv", "pip", "install", "-q", "--python", self.py]
            args, groups, reqs = detect_install(self.src)
            extra = self.spec.get("pip", [])
            how, out = None, ""
            for attempt in (args + groups + reqs + extra, args + groups + extra, args + reqs + extra, args + extra,
                            ["-e", "."] + extra):
                code, out, _ = sh(base + attempt + ["pytest"], cwd=self.src, timeout=1800)
                with open(logf, "a") as fh:
                    fh.write(" ".join(attempt) + f"\n-> {code}\n{out[-2000:]}\n")
                if code == 0:
                    how = " ".join(attempt)
                    break
            if how is None:
                return False, "install: " + out[-300:]
        if self.wheel:
            code, out, _ = sh(["uv", "pip", "install", "-q", "--python", self.py, "--reinstall-package", "detpy",
                               "--no-deps", self.wheel], timeout=600)
            if code:
                return False, "wheel: " + out[-300:]
        for cmd in self.spec.get("build", []):
            code, out, _ = sh(self.fmt(cmd), cwd=self.src, env=self.env(), timeout=3600, shell=True)
            if code:
                log(f"build step failed (ignored): {cmd[:60]} -> {code} {out[-300:]}")
        return True, how

    def pytest_args(self) -> list[str]:
        has = lambda mod: sh([self.py, "-c", f"import {mod}"], env=self.env())[0] == 0  # noqa: E731
        args = list(self.spec.get("pytest_args", [])) + ["-p", "times_plugin", "-p", "no:cacheprovider", "-q",
                                                           "-rN", "--tb=no"]
        if has("xdist"):
            args += ["-n", "0"]
        if has("pytest_cov"):
            args += ["--no-cov"]
        if has("pytest_timeout") and not any(a.startswith("--timeout") for a in args):
            args += ["--timeout=120"]
        for d in self.spec.get("deselect", []):
            args += ["--deselect", d]
        return args

    def units(self) -> list[str]:
        u = self.spec.get("units")
        if not u:
            return []
        files = git(self.src, "ls-files").splitlines()
        sel = [f for f in files if any(fnmatch.fnmatch(f, p) for p in u["include"])
               and not any(fnmatch.fnmatch(f, p) for p in u.get("exclude", []))]
        frac, seed = u.get("sample", 1.0), u.get("seed", "s2")
        out = []
        for x in sel:
            if hfrac(seed, x) < frac and int(hashlib.sha1(f"shard:{x}".encode()).hexdigest()[:8], 16) \
                    % self.nshards == self.shard:
                out.append(x)
        return sorted(out)

    # -- runs ----------------------------------------------------------------------
    def run(self, targets: list[str], tag: str, cache: Path | None, receipts: Path | None = None,
            extra: list[str] = ()) -> dict:
        git(self.src, "clean", "-qfd", check=False)
        outp = self.work / f"o-{tag}.json"
        tim = self.work / f"t-{tag}.json"
        outp.unlink(missing_ok=True)
        tim.unlink(missing_ok=True)
        cmd = [self.py, *self.spec.get("python_flags", []), "-m", "pytest", "--det", f"--det-outcomes={outp}"]
        if cache is not None:
            cmd.append(f"--det-cache={cache}")
            if receipts is not None:
                cmd.append(f"--det-cache-receipts={receipts}")
        cmd += [*self.args, *extra, *targets]
        env = self.env()
        env["CP_TIMES_OUT"] = str(tim)
        code, out, wall = sh(cmd, cwd=self.src, env=env, timeout=self.spec.get("timeout", 3000))
        r = {"exit": code, "wall": wall}
        try:
            o = json.loads(outp.read_text())
            r["outcomes"] = o.get("outcomes", {})
            r["cache"] = o.get("cache")
        except (OSError, ValueError):
            r["outcomes"] = {}
            r["tail"] = out[-1500:]
        try:
            r["times"] = {k: v[0] for k, v in json.loads(tim.read_text())["tests"].items()}
        except (OSError, ValueError, KeyError):
            r["times"] = {}
        return r

    # -- one commit --------------------------------------------------------------------
    def step(self, i: int, sha: str) -> dict:
        st = {"i": i, "sha": sha, "date": git(self.src, "show", "-s", "--format=%cI", sha).strip()}
        git(self.src, "checkout", "-q", "--force", sha)
        git(self.src, "clean", "-qfd", check=False)
        h = self.dep_hash()
        if h != self.last_dep:
            ok, how = self.install()
            st["install"] = how
            if not ok:
                st["status"] = "install-failed"
                self.last_dep = None
                return st
            self.args = self.pytest_args()
            self.last_dep = h
        units = self.units()
        st["units"] = len(units)
        if self.mode == "files":
            return self.step_files(st, units, i)
        return self.step_suite(st, units, i)

    def compare(self, cached: dict, fresh: dict, ids, confirm) -> dict:
        v = {"checked": 0, "same": 0, "mismatches": []}
        for nid in ids:
            if nid not in fresh:
                continue
            v["checked"] += 1
            if fresh[nid] == cached.get(nid):
                v["same"] += 1
            else:
                v["mismatches"].append({"nodeid": nid, "cached": cached.get(nid), "fresh": fresh[nid]})
        if v["mismatches"]:
            again = confirm()
            for m in v["mismatches"]:
                m["fresh2"] = again.get(m["nodeid"])
                m["verdict"] = "wrong" if m["fresh2"] == m["fresh"] else "flaky"
        return v

    @staticmethod
    def cache_info(r: dict) -> dict:
        c = r.get("cache") or {}
        return {k: c.get(k) for k in ("reused", "ran", "recorded", "miss_reasons", "not_cached", "check_seconds",
                                      "record_seconds", "stale_reuses", "reused_recorded_seconds")}

    def step_suite(self, st: dict, units: list[str], i: int) -> dict:
        a = self.run(units, "A", self.cache)
        b = self.run(units, "B", None)
        st["A"] = {"exit": a["exit"], "wall": a["wall"], **self.cache_info(a)}
        st["B"] = {"exit": b["exit"], "wall": b["wall"]}
        if not b["outcomes"] or not a["outcomes"]:
            st["status"] = "run-failed"
            st["tail"] = (a.get("tail") or b.get("tail") or "")[-1500:]
            return st
        reused = set((a.get("cache") or {}).get("reused_ids", ()))
        tb = b["times"]
        st["n_tests"] = len(b["outcomes"])
        st["time_total"] = sum(tb.values())
        st["time_reused"] = sum(tb.get(n, 0.0) for n in reused)
        st["n_reused"] = len(reused)
        st["n_reused_in_B"] = sum(1 for n in reused if n in b["outcomes"])
        st["verify"] = self.compare(a["outcomes"], b["outcomes"], sorted(reused),
                                    lambda: self.run(units, "B2", None)["outcomes"])
        # executed in A but outcome differs from B: an order effect of skipping (a reused test no longer sets
        # state a later test relied on), or flakiness
        diff = [n for n, o in a["outcomes"].items() if n not in reused and n in b["outcomes"] and b["outcomes"][n] != o]
        st["ran_diff"] = {"n": len(diff), "ids": diff[:20]}
        st["fail_B"] = sum(1 for o in b["outcomes"].values() if o not in ("passed", "skipped", "xfailed"))
        if i % 10 == 0 or i == self.n - 1:
            cold = self.work / "cold-cache"
            shutil.rmtree(cold, ignore_errors=True)
            c = self.run(units, "C", cold)
            p2 = self.run(units, "P2", None)
            shutil.rmtree(cold, ignore_errors=True)
            st["overhead"] = {"cold_wall": c["wall"], "plain_walls": [b["wall"], p2["wall"]],
                              "cold_record_s": (c.get("cache") or {}).get("record_seconds"),
                              "cold_check_s": (c.get("cache") or {}).get("check_seconds")}
        st["status"] = "ok"
        return st

    def step_files(self, st: dict, units: list[str], i: int) -> dict:
        full = i % 10 == 0 or i == self.n - 1
        agg = {"wall": 0.0, "reused": 0, "ran": 0, "recorded": 0, "miss_reasons": {}, "not_cached": {},
               "check_seconds": 0.0, "record_seconds": 0.0, "failed_units": 0}
        outcomes, reused, times = {}, {}, {}
        b_wall = 0.0
        ver = {"checked": 0, "same": 0, "mismatches": [], "units": 0}
        a_by_unit = {}
        for u in units:
            rc = self.work / "receipts.jsonl"
            rc.unlink(missing_ok=True)
            a = self.run([u], "A", self.cache, receipts=rc)
            agg["wall"] += a["wall"]
            c = a.get("cache") or {}
            if not a["outcomes"]:
                agg["failed_units"] += 1
            for k in ("reused", "ran", "recorded"):
                agg[k] += c.get(k) or 0
            for k in ("check_seconds", "record_seconds"):
                agg[k] += c.get(k) or 0.0
            for k in ("miss_reasons", "not_cached"):
                for kk, vv in (c.get(k) or {}).items():
                    agg[k][kk] = agg[k].get(kk, 0) + vv
            outcomes.update(a["outcomes"])
            times.update(a["times"])
            ru = set(c.get("reused_ids", ()))
            if ru and rc.exists():
                for line in rc.read_text().splitlines():
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("reused"):
                        reused[r["nodeid"]] = r.get("duration", 0.0)
            a_by_unit[u] = (a["outcomes"], ru)
        verify_units = units if full else [u for u in units if a_by_unit[u][1] and self.rng.random() < self.spec.get("verify", 0.1)]
        for u in verify_units:
            b = self.run([u], "B", None)
            b_wall += b["wall"]
            ao, ru = a_by_unit[u]
            v = self.compare(ao, b["outcomes"], sorted(ru), lambda: self.run([u], "B2", None)["outcomes"])
            ver["units"] += 1
            ver["checked"] += v["checked"]
            ver["same"] += v["same"]
            ver["mismatches"] += [dict(m, unit=u) for m in v["mismatches"]]
        st["A"] = agg
        st["B"] = {"wall": b_wall, "units": len(verify_units), "full": full}
        st["n_tests"] = len(outcomes)
        st["n_reused"] = len(reused)
        st["time_reused"] = sum(reused.values())
        st["time_total"] = st["time_reused"] + sum(t for n, t in times.items() if n not in reused)
        st["verify"] = ver
        st["status"] = "ok" if outcomes else "run-failed"
        return st

    # -- walk -----------------------------------------------------------------------------
    def save(self, final=False):
        self.result["elapsed_s"] = time.time() - self.t0
        self.out.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.result, indent=None).encode()
        if str(self.out).endswith(".gz"):
            with gzip.open(self.out, "wb") as fh:
                fh.write(data)
        else:
            self.out.write_bytes(data)

    def walk(self):
        commits = self.clone()
        self.result["commits"] = commits
        log(f"{self.name} shard {self.shard}/{self.nshards}: {len(commits)} commits, mode {self.mode}")
        for i, sha in enumerate(commits):
            if time.time() - self.t0 > self.budget:
                self.result["stopped"] = f"budget at commit {i}"
                log(self.result["stopped"])
                break
            try:
                st = self.step(i, sha)
            except Exception as e:  # keep walking
                st = {"i": i, "sha": sha, "status": "error", "error": repr(e)[:500]}
            self.result["steps"].append(st)
            tt = st.get("time_total") or 0
            log(f"[{i}] {sha[:10]} {st.get('status')}: tests {st.get('n_tests')}, reused {st.get('n_reused')} "
                f"({100 * (st.get('time_reused', 0) / tt) if tt else 0:.0f}% of time), A {st.get('A', {}).get('wall', 0):.1f}s "
                f"B {st.get('B', {}).get('wall', 0):.1f}s, verify {st.get('verify', {}).get('checked')}/"
                f"{len(st.get('verify', {}).get('mismatches', []))} mismatches; "
                f"miss {st.get('A', {}).get('miss_reasons')} nc {st.get('A', {}).get('not_cached')}")
            self.save()
            if os.environ.get("CP_COMMIT") and (i + 1) % self.commit_every == 0:
                commit_results([self.out], f"cache-proof: {self.name} shard {self.shard} ({i + 1} commits)")
        self.result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.save(final=True)
        if os.environ.get("CP_COMMIT"):
            commit_results([self.out], f"cache-proof: {self.name} shard {self.shard} "
                                       f"({len(self.result['steps'])} commits, final)")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wheel", default="")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--budget-min", type=float, default=330)
    ap.add_argument("--commits", type=int, default=0)
    ap.add_argument("--commit-every", type=int, default=10)
    a = ap.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text())
    s, n = (int(x) for x in a.shard.split("/"))
    Walk(spec, a.work, a.out, s, n, a.budget_min, a.wheel, a.commits or None, a.commit_every).walk()
    return 0


if __name__ == "__main__":
    sys.exit(main())
