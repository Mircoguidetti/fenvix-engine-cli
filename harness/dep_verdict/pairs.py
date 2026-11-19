#!/usr/bin/env python3
"""Dependency-update verdict, steps 2 to 5: measure the cache with proof on dependency-only commits.

For every dependency-only commit C (``commits.json``, from ``find_commits.py``) with its first parent P:

1. at P: fresh environment (the market-test install commands), then every sampled test file in its own process:
   * ``D0``: ``pytest --det --det-cache=CD --det-cache-dists`` (prototype: per-distribution identity, cold);
   * ``T0``: ``pytest --det --det-cache=CT`` (today's engine: one digest of the whole environment, cold);
2. at C: fresh environment again, then per test file:
   * ``D1`` and ``T1``: the same commands with the caches recorded at P: which results each reuses with proof;
   * ``B``: ``pytest --det`` without a cache at the caches' epoch: the fresh outcome of every test. Every reused
     result of D1 and T1 is compared with B; a difference is run once more (``B2``) to tell wrong from flaky;
3. the installed distributions at P and C (name, version, RECORD digest): what the commit changed;
4. for the tests D1 reran because a distribution they used changed: their recorded footprint at P and at C
   (files read outside the identity files, environment variables read, refusal reasons such as a connection).

    python3 harness/dep_verdict/pairs.py --spec harness/dep_verdict/specs/prefect.json \\
        --commits harness/dep_verdict/commits.json --work /tmp/w --out /tmp/prefect.json --wheel dist/detpy-*.whl
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TIMES = ROOT / "harness" / "cache_proof"  # times_plugin.py
OK = ("passed", "skipped", "xfailed")

SNAPSHOT = r'''
import hashlib, json, os, sys
from importlib import metadata
out = {}
for d in metadata.distributions():
    try:
        n = d.metadata["Name"]
    except Exception:
        continue
    if not n:
        continue
    k = n.lower().replace("_", "-").replace(".", "-")
    if k in out:
        continue
    try:
        du = json.loads(d.read_text("direct_url.json") or "{}")
    except Exception:
        du = {}
    url = du.get("url", "")
    if url.startswith("file://") and (os.path.realpath(url[7:]) + "/").startswith(os.path.realpath(os.getcwd()) + "/"):
        continue  # the project's own install (editable): not a dependency
    rec = d.read_text("RECORD") or ""
    out[k] = [d.version, hashlib.sha256(rec.encode()).hexdigest()[:16]]
json.dump(out, open(sys.argv[1], "w"))
'''

ENTRIES = r'''
import json, sys
from detpy import _core
cache, root, ids, out = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3])), sys.argv[4]
s = _core.ProofCache(cache, root)
res = {}
for nid in ids:
    try:
        e = json.loads(s.entry(nid))
    except Exception:
        continue
    res[nid] = {"data": [p for p, _ in e.get("data", [])], "env": [k for k, _ in e.get("env", [])]}
json.dump(res, open(out, "w"))
'''


def norm_name(n: str) -> str:
    return n.lower().replace("_", "-").replace(".", "-")


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
    repo = ROOT
    branch = os.environ.get("DV_BRANCH", "")
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


class Pairs:
    def __init__(self, spec, pairs, work, out, budget_min, wheel, max_units):
        self.spec = spec
        self.name = spec["name"]
        self.pairs = pairs
        self.work = Path(work).resolve() / self.name
        self.repo = self.work / spec.get("src_dir", "repo")  # the clone, where tests run (Ansible layout: src_dir)
        self.src = self.repo
        self.use_venv("P")
        self.out = Path(out).resolve()
        self.budget = budget_min * 60
        self.wheel = os.path.abspath(wheel) if wheel else ""
        self.max_units = max_units
        self.t0 = time.time()
        self.result = {"spec": spec, "engine": os.environ.get("GITHUB_SHA", ""), "runner": os.environ.get(
            "RUNNER_NAME", ""), "cpus": os.cpu_count(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pairs": []}

    def use_venv(self, tag: str) -> None:
        # one path for both environments, as on a CI runner: entry-point scripts embed the interpreter's path in
        # their bytes (and so in RECORD), so two paths would make every distribution with a script look changed
        self.venv = self.work / "venv"
        self.py = str(self.venv / "bin" / "python")

    def fmt(self, s: str) -> str:
        return (s.replace("{py}", self.py).replace("{venv}", str(self.venv)).replace("{src}", str(self.src))
                .replace("{work}", str(self.work)).replace("{harness}", str(HERE)))

    # -- setup ---------------------------------------------------------------------
    def clone(self):
        self.repo.parent.mkdir(parents=True, exist_ok=True)
        if not (self.repo / ".git").exists():
            code, out, _ = sh(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", self.spec["url"],
                               str(self.repo)], timeout=3600)
            if code:
                raise RuntimeError(f"clone failed: {out[-400:]}")

    def checkout(self, sha):
        if not git(self.repo, "rev-parse", "-q", "--verify", f"{sha}^{{commit}}", check=False).strip():
            sh(["git", "fetch", "-q", "origin", sha], cwd=self.repo, timeout=900)
        git(self.repo, "checkout", "-q", "--force", sha)
        git(self.repo, "clean", "-qffd", check=False)

    def env(self) -> dict:
        e = {k: v for k, v in os.environ.items()
             if k not in ("PYTHONHASHSEED", "DETPY_REEXEC", "VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS",
                          "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "DETPY_PRECOMPILE_S")
             and not k.startswith(("PYTEST_", "COV_"))}
        e.update({k: self.fmt(v) for k, v in self.spec.get("env", {}).items()})
        e["VIRTUAL_ENV"] = str(self.venv)
        e["PATH"] = f"{self.venv}/bin:" + e.get("PATH", "")
        e["PYTHONPATH"] = str(TIMES) + (":" + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
        e["CI"] = self.spec.get("ci_env", "true")
        e["COLUMNS"] = "160"
        return e

    def install(self) -> tuple[bool, str]:
        shutil.rmtree(self.venv, ignore_errors=True)
        logs = []
        for cmd in self.spec["install"]:
            code, out, dt = sh(self.fmt(cmd), cwd=self.src, env=dict(os.environ, **{
                k: self.fmt(v) for k, v in self.spec.get("install_env", {}).items()}), timeout=5400, shell=True)
            logs.append(f"$ {cmd[:120]} -> {code} ({dt:.0f}s)")
            if code:
                return False, "\n".join(logs) + "\n" + out[-1500:]
        if not Path(self.py).exists():
            return False, "no interpreter after install"
        code, out, _ = sh(["uv", "pip", "install", "-q", "--python", self.py, "--reinstall-package", "detpy",
                           "--no-deps", self.wheel], timeout=900)
        if code:
            return False, "wheel: " + out[-500:]
        return True, "\n".join(logs)

    def build(self) -> None:
        for cmd in self.spec.get("build", []):
            code, out, _ = sh(self.fmt(cmd), cwd=self.src, env=self.env(), timeout=3600, shell=True)
            if code:
                log(f"build step failed (ignored): {cmd[:60]} -> {code} {out[-300:]}")

    def snapshot(self, tag) -> dict:
        p = self.work / f"dists-{tag}.json"
        code, out, _ = sh([self.py, "-c", SNAPSHOT, str(p)], cwd=self.src, env=self.env(), timeout=600)
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return {"error": out[-500:]}

    def extra_args(self) -> list[str]:
        has = lambda mod: sh([self.py, "-c", f"import {mod}"], env=self.env())[0] == 0  # noqa: E731
        a = ["-p", "times_plugin", "-rN", "--tb=no"]
        if has("xdist"):
            a += ["-n", "0"]
        if has("pytest_cov") and not any("--no-cov" in c for c in self.spec["cmd"]):
            a += ["--no-cov"]
        if has("pytest_timeout"):
            a += ["--timeout=300"]
        return a

    def units(self) -> list[str]:
        u = self.spec["units"]
        files = git(self.repo, "ls-files").splitlines()
        sel = [f for f in files if any(fnmatch.fnmatch(f, p) for p in u["include"])
               and not any(fnmatch.fnmatch(f, p) for p in u.get("exclude", []))]
        frac, seed = u.get("sample", 1.0), u.get("seed", "s2")
        sel = [x for x in sel if hfrac(seed, x) < frac]
        if self.max_units and len(sel) > self.max_units:
            sel = sorted(sel, key=lambda x: hfrac("dv-cap", x))[:self.max_units]
        return sorted(sel)

    # -- runs -----------------------------------------------------------------------
    def run(self, unit, tag, cache=None, dists=False, epoch=()) -> dict:
        git(self.repo, "clean", "-qffd", check=False)
        outp, tim, rec = (self.work / f"{x}-{tag}.json" for x in ("o", "t", "r"))
        for p in (outp, tim, rec):
            p.unlink(missing_ok=True)
        det = ["--det", "--det-urandom", f"--det-outcomes={outp}"]
        if cache is not None:
            det.append(f"--det-cache={cache}")
            det.append(f"--det-cache-receipts={rec}")
            if dists:
                det.append("--det-cache-dists")
        det += list(epoch) + self.args
        cmd = []
        for c in self.spec["cmd"]:
            c = self.fmt(c)
            if c == "{unit}":
                cmd.append(unit)
                continue
            if "-p s2_report" in c:  # a shell string (airflow): splice detpy's arguments in
                c = c.replace("-p s2_report", " ".join(shlex.quote(x) for x in det))
            cmd.append(c.replace("{unit}", unit))
        if "s2_report" in cmd:
            i = cmd.index("s2_report")
            cmd[i - 1:i + 1] = det
        env = self.env()
        env["CP_TIMES_OUT"] = str(tim)
        if dists:
            env["DETPY_DIST_SETS"] = "1"
        code, out, wall = sh(cmd, cwd=self.src, env=env, timeout=self.spec.get("unit_timeout", 900))
        r = {"exit": code, "wall": round(wall, 2)}
        try:
            o = json.loads(outp.read_text())
            r["outcomes"] = o.get("outcomes", {})
            r["cache"] = o.get("cache")
        except (OSError, ValueError):
            r["outcomes"] = {}
            r["tail"] = out[-1200:]
        try:
            r["times"] = {k: v[0] for k, v in json.loads(tim.read_text())["tests"].items()}
        except (OSError, ValueError, KeyError):
            r["times"] = {}
        r["reused"] = sorted((r.get("cache") or {}).get("reused_ids", ()))
        if not r["reused"] and rec.exists():
            ids = []
            for line in rec.read_text().splitlines():
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if x.get("reused"):
                    ids.append(x["nodeid"])
            r["reused"] = sorted(ids)
        r["misses"] = {}
        if rec.exists():
            for line in rec.read_text().splitlines():
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if not x.get("reused"):
                    r["misses"][x["nodeid"]] = x.get("why", "")[-300:]
        return r

    @staticmethod
    def epoch_args(r) -> list[str]:
        ep = (r.get("cache") or {}).get("epoch_ns")
        if not ep:
            return []
        import datetime as dt
        t = dt.datetime.fromtimestamp(ep // 1_000_000_000, tz=dt.timezone.utc)
        return [f"--det-epoch={t.strftime('%Y-%m-%dT%H:%M:%S')}"]

    @staticmethod
    def slim_cache(c):
        c = c or {}
        return {k: c.get(k) for k in ("reused", "ran", "recorded", "miss_reasons", "not_cached", "not_cached_detail",
                                      "check_seconds", "record_seconds", "error", "dists", "epoch_ns")}

    # -- one pair ---------------------------------------------------------------------
    def pair(self, k, pc) -> dict:
        P, C = pc["parent"], pc["sha"]
        st = {"k": k, "index": pc.get("index"), "sha": C, "parent": P, "date": pc["date"], "subject": pc["subject"],
              "files": pc["files"]}
        cd, ct = self.work / "cache-d", self.work / "cache-t"
        for d in (cd, ct, self.work / "cache-d0"):
            shutil.rmtree(d, ignore_errors=True)
        # -- both environments first (C, then P, which the P runs use; C is installed again before its runs): what
        # the commit changes in the installed distributions
        for tag, sha in (("C", C), ("P", P)):
            self.checkout(sha)
            self.use_venv(tag)
            t = time.time()
            ok, how = self.install()
            st[f"install_s_{tag}"] = round(time.time() - t)
            if not ok:
                st["status"] = f"install-failed-{tag}"
                st["install"] = how[-2000:]
                return st
            st[f"dists_{tag}"] = self.snapshot(tag)
        dp, dc = st["dists_P"], st["dists_C"]
        changed = sorted(n for n in set(dp) | set(dc) if dp.get(n) != dc.get(n) and n not in ("detpy", "error"))
        st["env_changed"] = changed
        # today's engine keys every result on one digest of all installed distributions: when any changed, it
        # reuses nothing (runtime miss). It is run in full where nothing changed, and on the first pair of every
        # shard as a check of that rule; elsewhere its C run doubles as the fresh run.
        run_t = (not changed) or k == 0
        st["T_mode"] = "full" if run_t else "skipped: environment changed (runtime digest differs by construction)"
        # -- P (its environment is the one just installed)
        self.checkout(P)
        self.build()
        self.args = self.extra_args()
        units = self.units()
        st["units"] = units
        u0 = {}
        t_p = time.time()
        for u in units:
            d0 = self.run(u, "D0", cd, dists=True)
            u0[u] = {"D0": {"exit": d0["exit"], "wall": d0["wall"], "n": len(d0["outcomes"]),
                            "cache": self.slim_cache(d0.get("cache")), "tail": d0.get("tail")},
                     "outcomes_P": d0["outcomes"], "times_P": d0["times"]}
            if run_t:
                t0 = self.run(u, "T0", ct)
                u0[u]["T0"] = {"exit": t0["exit"], "wall": t0["wall"], "n": len(t0["outcomes"]),
                               "cache": self.slim_cache(t0.get("cache"))}
        st["t_P"] = round(time.time() - t_p)
        if cd.exists():
            shutil.copytree(cd, self.work / "cache-d0", dirs_exist_ok=True)
        # -- C
        self.checkout(C)
        self.use_venv("C")
        ok, how = self.install()
        if not ok:
            st["status"] = "install-failed-C2"
            st["install"] = how[-2000:]
            return st
        again = self.snapshot("C2")
        if again != st["dists_C"]:
            st["dists_C2_differs"] = sorted(n for n in set(again) | set(st["dists_C"])
                                            if again.get(n) != st["dists_C"].get(n))
        self.build()
        self.args = self.extra_args()
        t_c = time.time()
        per = {}
        affected_ids = []
        for u in units:
            if not (self.repo / u).exists():
                continue
            d1 = self.run(u, "D1", cd, dists=True)
            ea = self.epoch_args(d1)
            if run_t:
                t1 = self.run(u, "T1", ct)
                ea = ea or self.epoch_args(t1)
            else:
                t1 = {"exit": None, "wall": 0.0, "outcomes": {}, "reused": [], "misses": {}, "cache": None}
            b = self.run(u, "B", None, epoch=ea)
            fresh = b["outcomes"]
            rec = {"D0": u0[u]["D0"], "T0": u0[u].get("T0"), "times_P": u0[u]["times_P"],
                   "D1": {"exit": d1["exit"], "wall": d1["wall"], "cache": self.slim_cache(d1.get("cache")),
                          "tail": d1.get("tail")},
                   "T1": {"exit": t1["exit"], "wall": t1["wall"], "cache": self.slim_cache(t1.get("cache"))},
                   "B": {"exit": b["exit"], "wall": b["wall"], "n": len(fresh), "tail": b.get("tail")},
                   "times": b["times"], "fresh": fresh, "outcomes_P": u0[u]["outcomes_P"],
                   "D1_reused": d1["reused"], "T1_reused": t1["reused"],
                   "D1_cached": {n: d1["outcomes"].get(n) for n in d1["reused"]},
                   "T1_cached": {n: t1["outcomes"].get(n) for n in t1["reused"]},
                   "D1_miss": d1["misses"], "T1_miss_kinds": {}}
            for n, why in t1["misses"].items():
                kk = why.split(":", 1)[0]
                rec["T1_miss_kinds"][kk] = rec["T1_miss_kinds"].get(kk, 0) + 1
            # verification of every reuse against the fresh run
            mism = []
            for mode in ("D1", "T1"):
                for n, o in rec[f"{mode}_cached"].items():
                    if n in fresh and fresh[n] != o:
                        mism.append((mode, n, o))
            if mism:
                b2 = self.run(u, "B2", None, epoch=ea)["outcomes"]
                rec["mismatches"] = [{"mode": m, "nodeid": n, "cached": o, "fresh": fresh.get(n), "fresh2": b2.get(n),
                                      "verdict": "wrong" if b2.get(n) == fresh.get(n) else "flaky"} for m, n, o in mism]
            rec["unverified"] = sorted(n for n in set(d1["reused"]) | set(t1["reused"]) if n not in fresh)
            # dist-sets of the D runs (per-test identity keys, not-cached reasons)
            for n, why in d1["misses"].items():
                if "dist-identity/" in why:
                    affected_ids.append(n)
            per[u] = rec
        st["t_C"] = round(time.time() - t_c)
        st["per_unit"] = per
        # footprints of the affected tests before (cache-d0) and after (cache-d)
        if affected_ids:
            ids = self.work / "aff.json"
            ids.write_text(json.dumps(sorted(set(affected_ids))))
            fp = {}
            for tag, d in (("P", self.work / "cache-d0"), ("C", cd)):
                o = self.work / f"fp-{tag}.json"
                code, out, _ = sh([self.py, "-c", ENTRIES, str(d), str(self.src), str(ids), str(o)], env=self.env(),
                                  timeout=600)
                try:
                    fp[tag] = json.loads(o.read_text())
                except (OSError, ValueError):
                    fp[tag] = {"error": out[-300:]}
            st["footprint"] = fp
        # per-test identity sets recorded at P (for the analysis: which distributions each test depends on)
        sets = {}
        for f in sorted((self.work / "cache-d0").glob("dist-sets-*.json")):
            try:
                d = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            for n, v in d.get("tests", {}).items():
                sets[n] = v
        st["dist_sets_P"] = {n: {"proof": [x for x in v["proof"] if not x.startswith("m/")],
                                 "own": [x for x in v["own"] if not x.startswith("m/")],
                                 "n_m": sum(1 for x in v["proof"] if x.startswith("m/"))} for n, v in sets.items()}
        st["status"] = "ok"
        return st

    def save(self):
        self.result["elapsed_s"] = round(time.time() - self.t0)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.result).encode()
        with (gzip.open(self.out, "wb") if str(self.out).endswith(".gz") else open(self.out, "wb")) as fh:
            fh.write(data)

    def walk(self):
        self.clone()
        log(f"{self.name}: {len(self.pairs)} pairs")
        for k, pc in enumerate(self.pairs):
            if time.time() - self.t0 > self.budget:
                self.result["stopped"] = f"budget at pair {k}"
                log(self.result["stopped"])
                break
            t = time.time()
            try:
                st = self.pair(k, pc)
            except Exception as e:  # keep going
                import traceback
                st = {"k": k, "sha": pc["sha"], "status": "error", "error": traceback.format_exc()[-1500:]}
            st["elapsed"] = round(time.time() - t)
            self.result["pairs"].append(st)
            nre = sum(len(r.get("D1_reused", ())) for r in (st.get("per_unit") or {}).values())
            ntr = sum(len(r.get("T1_reused", ())) for r in (st.get("per_unit") or {}).values())
            nt = sum(len(r.get("fresh", ())) for r in (st.get("per_unit") or {}).values())
            log(f"[{k}] {pc['sha'][:10]} {st.get('status')}: units {len(st.get('units') or [])}, tests {nt}, "
                f"reused D {nre} T {ntr}, {st['elapsed']}s")
            self.save()
            if os.environ.get("DV_COMMIT"):
                commit_results([self.out], f"dep-verdict: {self.name} pair {k + 1}/{len(self.pairs)}")
        self.result["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.save()
        if os.environ.get("DV_COMMIT"):
            commit_results([self.out], f"dep-verdict: {self.name} ({len(self.result['pairs'])} pairs, final)")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--commits", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--only", default="", help="comma-separated pair indices (0 = newest)")
    ap.add_argument("--budget-min", type=float, default=330)
    ap.add_argument("--max-units", type=int, default=0)
    a = ap.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text())
    pairs = json.loads(Path(a.commits).read_text())[spec.get("repo", spec["name"])]["dep_commits"]
    for i, p in enumerate(pairs):
        p["index"] = i
    s, n = (int(x) for x in a.shard.split("/"))
    pairs = [p for i, p in enumerate(pairs) if i % n == s]
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        pairs = [p for p in pairs if p["index"] in keep]
    Pairs(spec, pairs, a.work, a.out, a.budget_min, a.wheel, a.max_units or spec.get("max_units", 0)).walk()
    return 0


if __name__ == "__main__":
    sys.exit(main())
