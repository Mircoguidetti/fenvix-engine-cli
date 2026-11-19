#!/usr/bin/env python3
"""Walk a window of commits with `detjs --det --det-cache` and measure skip with proof.

Per commit i (after install and build):

* **skip run** (i > first of the shard): a copy of the cache as it was after commit i-1; detjs decides with proof
  and runs only the files it cannot reuse. Wall time and the reused files are recorded.
Runners: Vitest and Jest (their JSON reports), `node --test` and Mocha (`"runner": "node-test" | "mocha"`; runner
args in `args`, file patterns in `patterns`, per-file outcomes from detjs' cache summary).

* **verify run**: the same cache state (before the skip run), `--det-cache-verify`: detjs takes the same decisions
  (same inputs, same cache) but runs every file and compares every result it would have reused with the fresh
  result at the same commit (0 wrong = no mismatch). Its records become the cache for commit i+1. Its per-file
  durations price the time skipped.
* **overhead** (first commit of a shard and every `--overhead-every` commits): plain runner (the project's own
  parallel command), `detjs --det` without cache (serial Level 0) and the cold capture run (empty cache), then a warm
  run (skip mode right after the verify run at the same commit).
* **Nx** (when `--nx`): projects affected between commit i-1 and i (`nx show projects --affected`, package-based
  inference from the workspace), mapped to test files by project root: the test time Nx's affected selection would
  skip at the same transition.

Output: one JSON per shard (appended after every commit).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", ".."))
DETJS = os.path.join(ENGINE, "node", "bin", "detjs.js")


def sh(cmd, cwd=None, timeout=None, env=None, check=False, capture=True):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), timeout=timeout, env=env,
                           stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None,
                           text=True, errors="replace")
    except subprocess.TimeoutExpired as e:
        out = e.output.decode(errors="replace") if isinstance(e.output, bytes) else (e.output or "")
        return 124, out + f"\n[timeout after {timeout} s]", time.time() - t0
    dt = time.time() - t0
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd} -> {r.returncode}\n{(r.stdout or '')[-4000:]}")
    return r.returncode, (r.stdout or ""), dt


def files_digest(root, patterns):
    import glob

    h = hashlib.sha256()
    for pat in patterns:
        for p in sorted(glob.glob(os.path.join(root, pat))):
            if os.path.isfile(p):
                h.update(p.encode())
                with open(p, "rb") as fh:
                    h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def load_json(p):
    try:
        with open(p) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def summary_of(repo):
    s = load_json(os.path.join(repo, ".detjs", "cache-summary.json")) or {}
    keep = ("reused_files", "reused_tests", "reused_files_list", "reused_recorded_seconds", "missed_files", "miss_reasons",
            "recorded", "not_cached", "not_cached_top", "identity_seconds", "check_seconds", "record_seconds", "config",
            "runtime", "runtime_parts", "verified", "verify_mismatches", "ran_files", "error", "notes", "startup",
            "uncacheable_projects", "misses")
    out = {k: s.get(k) for k in keep}
    pk = s.get("packages") or {}
    out["packages"] = {k: pk.get(k) for k in ("files", "bytes", "hashed", "links", "followed")}
    return out


# Runners that detjs runs on another runtime (src/runners): `detjs <cmd>`, report as JUnit XML (one <testsuite> per
# test file at the top level). Added by the all-runners work (node-c: bun test, deno test); separate dispatch branches.
RUNTIME_RUNNERS = {
    "bun-test": {"cmd": "bun-test", "report": lambda p: ["--reporter=junit", f"--reporter-outfile={p}"], "version": ["bun", "--revision"]},
    "deno-test": {"cmd": "deno-test", "report": lambda p: [f"--junit-path={p}"], "version": ["deno", "--version"]},
}
# runners whose detjs shell has no JSON report of its own: outcomes come from detjs' cache summary (ran_files).
# node-a: node-test, mocha; node-b: tap, ava, jasmine, uvu (src/runners/<name>.js)
SUMMARY_RUNNERS = ("node-test", "mocha", "tap", "ava", "jasmine", "uvu")


def junit_outcomes(report_path):
    """{test file: {"ok", "tests", "failed"}} from a JUnit report whose top-level suites are test files."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(report_path).getroot()
    except (OSError, ET.ParseError):
        return {}
    suites = [root] if root.tag == "testsuite" else list(root)
    out = {}
    for s in suites:
        if s.tag != "testsuite":
            continue
        name = (s.get("file") or s.get("name") or "").removeprefix("./")
        cases = list(s.iter("testcase"))
        failed = sum(1 for c in cases if c.find("failure") is not None or c.find("error") is not None)
        prev = out.get(name, {"ok": True, "tests": 0, "failed": 0})
        out[name] = {"ok": prev["ok"] and failed == 0, "tests": prev["tests"] + len(cases), "failed": prev["failed"] + failed}
    return out


def report_args(runner, report):
    if runner in RUNTIME_RUNNERS:
        return RUNTIME_RUNNERS[runner]["report"](report)
    if runner in SUMMARY_RUNNERS:
        return []  # the spec's own reporter args; outcomes from detjs' summary
    return ["--reporter=json", f"--outputFile={report}"] if runner == "vitest" else ["--json", f"--outputFile={report}"]


def detjs_cmd(runner):
    if runner in RUNTIME_RUNNERS:
        return ["node", DETJS, RUNTIME_RUNNERS[runner]["cmd"]]
    return ["node", DETJS, runner] + (["run"] if runner == "vitest" else [])


def outcomes_of(report_path, runner, repo=None):
    """{test file: {"ok": bool, "tests": n, "failed": n}} from the runner's JSON report (Vitest, Jest), its JUnit
    report (bun test, deno test) or, for the SUMMARY_RUNNERS (node-test, Mocha, tap, AVA, Jasmine, uvu), from the
    files detjs ran (`.detjs/cache-summary.json`, `ran_files`)."""
    if runner in RUNTIME_RUNNERS:
        return junit_outcomes(report_path)
    if runner in SUMMARY_RUNNERS:
        if repo is None:
            return {}
        s = load_json(os.path.join(repo, ".detjs", "cache-summary.json")) or {}
        return {k: {"ok": bool(v.get("ok")), "tests": v.get("tests", 0), "failed": 0 if v.get("ok") else None}
                for k, v in (s.get("ran_files") or {}).items()}
    j = load_json(report_path) or {}
    out = {}
    for f in j.get("testResults") or []:
        name = f.get("name") or ""
        res = f.get("assertionResults") or []
        failed = sum(1 for a in res if a.get("status") == "failed")
        out[name] = {"ok": f.get("status") == "passed" or (failed == 0 and f.get("status") != "failed"), "tests": len(res),
                     "failed": failed}
    return out


class Walk:
    def __init__(self, a):
        self.a = a
        self.spec = load_json(a.spec)
        self.repo = os.path.abspath(a.repo)
        self.work = os.path.abspath(a.work)
        os.makedirs(self.work, exist_ok=True)
        self.cache = os.path.join(self.work, "cache")
        self.out = a.out
        self.res = load_json(self.out) or {"spec": self.spec, "shard": a.shard, "commits": [], "runner": os.environ.get("RUNNER_NAME"),
                                           "cpus": os.cpu_count(), "node": None}
        self.install_digest = None
        self.env = dict(os.environ)
        if self.spec.get("unset_ci"):
            for k in ("CI", "GITHUB_ACTIONS"):
                self.env.pop(k, None)
        self.env["FENVIX_RUNTIME_MEMO"] = os.path.join(self.work, "runtime-memo.json")
        # environment the project's test script sets (`NODE_ENV=test uvu ...`)
        self.env.update(self.spec.get("env") or {})

    def save(self):
        tmp = self.out + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.res, fh, indent=1)
        os.replace(tmp, self.out)

    def prepare(self, sha):
        info = {}
        sh(["git", "checkout", "-q", "-f", sha], cwd=self.repo, check=True)
        sh(["git", "clean", "-q", "-ffdx", "-e", "node_modules", "-e", ".detjs"], cwd=self.repo)
        for dst, srcf in (self.spec.get("setup_files") or {}).items():
            shutil.copyfile(os.path.join(ENGINE, srcf), os.path.join(self.repo, dst))
        d = files_digest(self.repo, self.spec.get("install_files", ["package.json"]))
        if d != self.install_digest:
            t0 = time.time()
            for c in self.spec.get("install", []):
                rc, out, _ = sh(c, cwd=self.repo, timeout=1800, env=self.env)
                if rc != 0:
                    info["install_error"] = out[-2000:]
            info["install_seconds"] = round(time.time() - t0, 1)
            self.install_digest = d
            info["installed"] = True
        t0 = time.time()
        for c in self.spec.get("build", []):
            rc, out, _ = sh(c, cwd=self.repo, timeout=1800, env=self.env)
            if rc != 0:
                info["build_error"] = out[-2000:]
        info["build_seconds"] = round(time.time() - t0, 1)
        return info

    def report_args(self, report):
        return report_args(self.spec["runner"], report)

    def runner_args(self, files=None):
        """The spec's runner args, then its file patterns (node-test, mocha) or the given files instead."""
        return list(self.spec.get("args", [])) + list(files if files is not None else self.spec.get("patterns", []))

    def detjs(self, cache_dir, extra, report):
        args = detjs_cmd(self.spec["runner"])
        args += ["--det", f"--det-cache={cache_dir}"] + extra + self.runner_args()
        args += self.report_args(report)
        rc, out, dt = sh(args, cwd=self.repo, timeout=self.a.run_timeout, env=self.env)
        return rc, out, dt

    def plain(self, report):
        cmd = self.spec["plain"].replace("{report}", report)
        rc, out, dt = sh(cmd, cwd=self.repo, timeout=self.a.run_timeout, env=self.env)
        return rc, dt

    def det_nocache(self, report):
        args = detjs_cmd(self.spec["runner"]) + ["--det"]
        args += self.runner_args()
        args += self.report_args(report)
        rc, out, dt = sh(args, cwd=self.repo, timeout=self.a.run_timeout, env=self.env)
        return rc, dt

    def nx_affected(self, base, head):
        """Projects Nx's affected selection keeps for base..head (Nx installed aside, linked in only for this step)."""
        nxv = self.spec.get("nx_version", "22")
        tool = os.path.join(self.work, "nxtool")
        if not os.path.exists(os.path.join(tool, "node_modules", "nx", "package.json")):
            os.makedirs(tool, exist_ok=True)
            with open(os.path.join(tool, "package.json"), "w") as fh:
                fh.write('{"private": true}\n')
            sh(["npm", "install", f"nx@{nxv}", "--no-audit", "--no-fund", "--silent"], cwd=tool, timeout=900, env=self.env)
        link = os.path.join(self.repo, "node_modules", "nx")
        made_link = False
        if not os.path.exists(link):
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.symlink(os.path.join(tool, "node_modules", "nx"), link)
            made_link = True
        created = False
        if not os.path.exists(os.path.join(self.repo, "nx.json")) and not os.path.exists(os.path.join(self.repo, "lerna.json")):
            with open(os.path.join(self.repo, "nx.json"), "w") as fh:
                fh.write("{}\n")
            created = True
        env = dict(self.env, NX_DAEMON="false", NX_NO_CLOUD="true", NX_SKIP_NX_CACHE="true", NX_TUI="false", NX_ISOLATE_PLUGINS="false")
        binrel = (load_json(os.path.join(link, "package.json")) or {}).get("bin", {}).get("nx", "bin/nx.js")
        nx = ["node", os.path.join(link, binrel)]
        try:
            rc, out, dt = sh(nx + ["show", "projects", "--json"], cwd=self.repo, timeout=600, env=env)
            allp = json.loads(out[out.index("["):]) if rc == 0 and "[" in out else None
            rc2, out2, dt2 = sh(nx + ["show", "projects", "--affected", f"--base={base}", f"--head={head}", "--json"],
                                cwd=self.repo, timeout=600, env=env)
            aff = json.loads(out2[out2.index("["):]) if rc2 == 0 and "[" in out2 else None
            roots = {}
            gfile = os.path.join(self.work, "nx-graph.json")
            if allp:
                sh(nx + ["graph", f"--file={gfile}"], cwd=self.repo, timeout=600, env=env)
                g = load_json(gfile) or {}
                for name, node in (g.get("graph", {}).get("nodes", {}) or {}).items():
                    roots[name] = (node.get("data") or {}).get("root")
            return {"all": allp, "affected": aff, "roots": roots, "seconds": round(dt + dt2, 1),
                    "error": None if aff is not None else (out2[-1500:] if rc2 else out[-1500:])}
        finally:
            if created:
                os.remove(os.path.join(self.repo, "nx.json"))
            if made_link:
                os.remove(link)
            shutil.rmtree(os.path.join(self.repo, ".nx"), ignore_errors=True)

    def run(self, shas):
        done = {c["sha"] for c in self.res["commits"]}
        first = True
        prev = None
        rc, nv, _ = sh(["node", "--version"])
        self.res["node"] = nv.strip()
        if self.spec["runner"] in RUNTIME_RUNNERS:
            rc, rv, _ = sh(RUNTIME_RUNNERS[self.spec["runner"]]["version"])
            self.res["runtime"] = rv.strip().splitlines()[0] if rv.strip() else None
        for i, sha in enumerate(shas):
            if sha in done:
                prev = sha
                first = False
                continue
            rec = {"i": self.a.offset + i, "sha": sha, "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            rec.update(self.prepare(sha))
            rec["changed_files"] = None
            if prev:
                _, diff, _ = sh(["git", "diff", "--name-only", prev, sha], cwd=self.repo)
                rec["changed_files"] = [x for x in diff.splitlines() if x][:400]
            overhead = (first and not getattr(self.a, "no_first_overhead", False)) or bool(self.a.overhead_every and i % self.a.overhead_every == 0)
            if overhead:
                rp = os.path.join(self.work, "plain.json")
                rc, dt = self.plain(rp)
                rec["plain"] = {"rc": rc, "seconds": round(dt, 2), "outcomes": outcomes_of(rp, self.spec["runner"])
                                if self.spec["runner"] not in SUMMARY_RUNNERS else {}}
                rp = os.path.join(self.work, "det.json")
                rc, dt = self.det_nocache(rp)
                rec["det_nocache"] = {"rc": rc, "seconds": round(dt, 2)}
            if first:
                shutil.rmtree(self.cache, ignore_errors=True)
            else:
                skip_cache = os.path.join(self.work, "cache-skip")
                shutil.rmtree(skip_cache, ignore_errors=True)
                shutil.copytree(self.cache, skip_cache)
                rp = os.path.join(self.work, "skip.json")
                rc, out, dt = self.detjs(skip_cache, [], rp)
                rec["skip"] = {"rc": rc, "seconds": round(dt, 2), "summary": summary_of(self.repo),
                               "outcomes": outcomes_of(rp, self.spec["runner"], self.repo), "tail": out[-1500:] if rc else ""}
            rp = os.path.join(self.work, "verify.json")
            rc, out, dt = self.detjs(self.cache, ["--det-cache-verify"], rp)
            rec["verify"] = {"rc": rc, "seconds": round(dt, 2), "summary": summary_of(self.repo), "cold": first,
                             "outcomes": outcomes_of(rp, self.spec["runner"], self.repo), "tail": out[-3000:] if rc else ""}
            mism = rec["verify"]["summary"].get("verify_mismatches") or []
            if mism:
                rec["recheck"] = self.recheck(mism)
            if overhead:
                skip_cache = os.path.join(self.work, "cache-warm")
                shutil.rmtree(skip_cache, ignore_errors=True)
                shutil.copytree(self.cache, skip_cache)
                rp = os.path.join(self.work, "warm.json")
                rc, out, dt = self.detjs(skip_cache, [], rp)
                rec["warm"] = {"rc": rc, "seconds": round(dt, 2), "summary": summary_of(self.repo)}
            if prev and self.a.nx:
                try:
                    rec["nx"] = self.nx_affected(prev, sha)
                except Exception as e:  # noqa: BLE001
                    rec["nx"] = {"error": str(e)[-1500:]}
            self.res["commits"].append(rec)
            self.save()
            print(f"[{rec['i']}] {sha[:10]} verify {rec['verify']['seconds']}s reused "
                  f"{rec['verify']['summary'].get('reused_files')} files; skip {rec.get('skip', {}).get('seconds')}s; "
                  f"mismatches {len(mism)}", flush=True)
            prev = sha
            first = False

    def recheck(self, mism):
        """Run each test file with a mismatch 3 more times at the same commit (flaky or wrong?)."""
        files = sorted({m["nodeid"].split("::", 1)[0].split("@@", 1)[0] for m in mism})[:10]
        out = {}
        for f in files:
            runs = []
            for k in range(3):
                rp = os.path.join(self.work, f"recheck{k}.json")
                args = detjs_cmd(self.spec["runner"]) + ["--det"]
                if self.spec["runner"] in SUMMARY_RUNNERS:
                    # an empty cache: every file runs (fresh), and the summary says how each one ended; node-test
                    # runs the one file, Mocha its configured specs (a positional file adds to them)
                    fresh = os.path.join(self.work, f"recheck-cache{k}")
                    shutil.rmtree(fresh, ignore_errors=True)
                    args += [f"--det-cache={fresh}"]
                    # tap, AVA, Jasmine, uvu: the file as a positional argument unless the spec says the runner
                    # takes none (`no_file_args`: its configuration selects the files)
                    one = self.spec["runner"] != "mocha" and not self.spec.get("no_file_args")
                    args += self.runner_args([f] if one else None)
                else:
                    args += list(self.spec.get("args", [])) + [f]
                args += self.report_args(rp)
                rc, _, _ = sh(args, cwd=self.repo, timeout=900, env=self.env)
                outs = outcomes_of(rp, self.spec["runner"], self.repo)
                if self.spec["runner"] in SUMMARY_RUNNERS:
                    outs = {k2: v for k2, v in outs.items() if k2 == f}
                runs.append({"rc": rc if self.spec["runner"] not in SUMMARY_RUNNERS else (0 if all(v["ok"] for v in outs.values()) and outs else 1),
                             "outcomes": outs})
            out[f] = runs
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--commits", required=True, help="JSON list of shas (oldest first)")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--overhead-every", type=int, default=10)
    ap.add_argument("--run-timeout", type=int, default=3600)
    ap.add_argument("--nx", action="store_true")
    ap.add_argument("--budget", type=int, default=19800, help="stop starting commits after this many seconds")
    ap.add_argument("--nx-only", action="store_true", help="only Nx affected per transition (no install, no test runs)")
    ap.add_argument("--no-first-overhead", action="store_true")
    ap.add_argument("--window", default="", help="LO:HI slice of the commit list (overrides the spec's window)")
    a = ap.parse_args()
    shas = load_json(a.commits)
    spec = load_json(a.spec)
    if a.window:
        spec["window"] = [int(x) for x in a.window.split(":")]
    if spec.get("window") and not a.nx_only:
        lo0, hi0 = spec["window"]
        base_offset = lo0
        shas = shas[lo0:hi0]
    else:
        base_offset = 0
    if spec.get("run_timeout"):
        a.run_timeout = int(spec["run_timeout"])
    if spec.get("overhead") == "shard0" and a.shard != 0:
        a.overhead_every = 0
        a.no_first_overhead = True
    if a.nx_only:
        a.shard = 0
        w = Walk(a)
        w.res = {"spec": w.spec, "mode": "nx-only", "transitions": []}
        for i in range(1, len(shas)):
            sh(["git", "checkout", "-q", "-f", shas[i]], cwd=w.repo, check=True)
            sh(["git", "clean", "-q", "-ffdx", "-e", "node_modules"], cwd=w.repo)
            try:
                r = w.nx_affected(shas[i - 1], shas[i])
            except Exception as e:  # noqa: BLE001
                r = {"error": str(e)[-1500:]}
            r.update(i=i, sha=shas[i])
            w.res["transitions"].append(r)
            w.save()
            print(f"[{i}] {shas[i][:10]} affected {None if r.get('affected') is None else len(r['affected'])} of {len(r.get('all') or [])}", flush=True)
        return
    n = len(shas)
    # shards overlap by one commit so that every transition i-1 -> i is measured once
    per = -(-(n - 1) // a.nshards)
    lo = a.shard * per
    hi = min(n, lo + per + 1)
    a.offset = base_offset + lo
    w = Walk(a)
    t0 = time.time()
    sub = shas[lo:hi]
    w.res["window"] = [lo, hi]
    for k in range(len(sub)):
        if time.time() - t0 > a.budget:
            w.res["stopped"] = f"budget after {k} commits"
            w.save()
            break
        w.run(sub[: k + 1])
    w.save()


if __name__ == "__main__":
    main()
