#!/usr/bin/env python3
"""Release smoke test: one small real repository per language, under --det (twice, traces verified identical) and
under skip with proof (twice: the second run must reuse at least one test with proof and report no test outcome
that differs from the first run).

    python3 release/smoke.py --lang python|node|go|jvm --engine . --work /tmp/smoke --out smoke-<lang>.json

Every command and its output are logged under --work/logs; the JSON names the repository, the commit, the commands,
their exit codes and the checks. Exit code 0 only when every check passed. Runs on GitHub Actions
(.github/workflows/release-1.yml, job `smoke`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

# One small real repository per language, pinned to a tag (DECLARED choice; docs/RELEASE-1.md).
REPOS = {
    "python": {"url": "https://github.com/pallets/itsdangerous", "ref": "2.2.0"},
    "node": {"url": "https://github.com/simple-statistics/simple-statistics", "ref": "v7.9.3"},
    "go": {"url": "https://github.com/google/uuid", "ref": "v1.6.0"},
    "jvm": {"url": "https://github.com/google/gson", "ref": "gson-parent-2.11.0"},
}


class Smoke:
    def __init__(self, lang, engine, work):
        self.lang, self.engine, self.work = lang, os.path.abspath(engine), os.path.abspath(work)
        self.repo = os.path.join(self.work, "repo")
        self.log = os.path.join(self.work, "logs")
        self.steps: list[dict] = []
        self.checks: dict[str, dict] = {}
        os.makedirs(self.log, exist_ok=True)
        # every engine command goes through the release's single CLI entry, on the installed image layout
        # (release/install-image.sh; FENVIX_HOME)
        self.fx = [sys.executable, os.path.join(self.engine, "release", "fenvix")]

    def sh(self, name, cmd, cwd=None, env=None, timeout=3600):
        t = time.time()
        e = dict(os.environ, **(env or {}))
        try:
            p = subprocess.run(cmd, cwd=cwd or self.repo, env=e, shell=isinstance(cmd, str), text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
            rc, out = p.returncode, p.stdout
        except subprocess.TimeoutExpired as x:
            rc, out = "timeout", (x.stdout or b"").decode(errors="replace") if isinstance(x.stdout, bytes) else (x.stdout or "")
        with open(os.path.join(self.log, f"{name}.log"), "w") as fh:
            fh.write(out)
        self.steps.append({"name": name, "cmd": cmd, "rc": rc, "seconds": round(time.time() - t, 1)})
        print(f"[{self.lang}] {name}: rc={rc} ({time.time() - t:.1f}s)", flush=True)
        print("\n".join(out.splitlines()[-15:]), flush=True)
        return rc, out

    def check(self, name, ok, detail):
        self.checks[name] = {"ok": bool(ok), "detail": detail}
        print(f"[{self.lang}] check {name}: {'OK' if ok else 'FAILED'} {detail}", flush=True)

    def clone(self):
        r = REPOS[self.lang]
        shutil.rmtree(self.repo, ignore_errors=True)
        self.sh("clone", ["git", "clone", "-q", "--depth", "1", "--branch", r["ref"], r["url"], self.repo], cwd=self.work)
        _, sha = self.sh("sha", ["git", "rev-parse", "HEAD"])
        return {**r, "commit": sha.strip()}

    def verify(self, t1, t2):
        if not (os.path.exists(t1) and os.path.exists(t2)):
            self.check("det_traces_identical", False, f"trace missing: {t1} {os.path.exists(t1)}, {t2} {os.path.exists(t2)}")
            return
        rc, out = self.sh("verify", self.fx + ["verify", t1, t2])
        self.check("det_traces_identical", rc == 0 and os.path.getsize(t1) > 0,
                   (out.strip().splitlines() or [""])[-1][:300])

    def same_outcomes(self, a: dict, b: dict, reused: int):
        diff = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        self.check("cache_reused", reused > 0, f"{reused} reused with proof in the second run")
        self.check("cache_same_outcomes", not diff and len(b) >= len(a) > 0,
                   f"{len(a)} / {len(b)} outcomes; differing: {diff[:10]}")

    # -- Python: pytest plugin ------------------------------------------------------------------------------------
    def python(self):
        self.sh("install", [sys.executable, "-m", "pip", "install", "-q", ".", "pytest", "freezegun"])
        traces = []
        for i in (1, 2):
            t = os.path.join(self.work, f"det{i}.jsonl")
            self.sh(f"det{i}", self.fx + ["python", "-q", "-p", "no:cacheprovider", "--det",
                                f"--det-trace={t}", "tests"])
            traces.append(t)
        self.verify(*traces)
        cache = os.path.join(self.work, "cache")
        outs, reused = [], 0
        for i in (1, 2):
            o = os.path.join(self.work, f"outcomes{i}.json")
            _, out = self.sh(f"cache{i}", self.fx + ["python", "-q", "-p", "no:cacheprovider", "--det",
                                           f"--det-cache={cache}", f"--det-outcomes={o}", "tests"])
            # --det-outcomes: {"outcomes": {nodeid: outcome}, "durations": ..., "cache": ...}
            outs.append((json.load(open(o)).get("outcomes") or {}) if os.path.exists(o) else {})
            m = re.search(r"reused (\d+) result", out)
            reused = int(m.group(1)) if m else 0
        self.same_outcomes(outs[0], outs[1], reused)

    # -- Node: detjs (node --test runner) -------------------------------------------------------------------------
    def node(self):
        self.sh("install", "npm install --no-audit --no-fund --ignore-scripts")
        args = ["--experimental-test-isolation=none", "test/*.test.js"]
        traces = []
        for i in (1, 2):
            t = os.path.join(self.work, f"det{i}.jsonl")
            # --det-epoch=fixed: the two runs are verified against each other, so they share one epoch (opt-out of the
            # host-time default, spec det-host-values 2026-11-23)
            self.sh(f"det{i}", self.fx + ["node", "node-test", "--det", "--det-epoch=fixed", f"--det-trace={t}"] + args)
            traces.append(t)
        self.verify(*traces)
        cache = os.path.join(self.work, "cache")
        outs, reused = [], 0
        for i in (1, 2):
            _, out = self.sh(f"cache{i}", self.fx + ["node", "node-test", "--det", f"--det-cache={cache}"] + args)
            rec = os.path.join(self.repo, ".detjs", "receipts.jsonl")
            o, n = {}, 0
            for line in open(rec) if os.path.exists(rec) else ():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                nid = str(d.get("id") or d.get("nodeid") or d.get("test") or "")
                if d.get("kind") == "file" or not nid:
                    continue
                o[nid] = d.get("outcome")
                n += bool(d.get("reused"))
            m = re.search(r"reused (\d+)", out)
            outs.append(o)
            reused = max(n, int(m.group(1)) if m else 0)
        self.same_outcomes(outs[0], outs[1], reused)

    # -- Go: fenvix-go overlay ------------------------------------------------------------------------------------
    def go(self):
        fx = self.fx + ["go"]
        traces = []
        for i in (1, 2):
            t = os.path.join(self.work, f"det{i}.jsonl")
            self.sh(f"det{i}", fx + ["test", "--det", f"--det-trace={t}", "."])
            traces.append(t)
        self.verify(*traces)
        cache = os.path.join(self.work, "cache")
        outs, reused = [], 0
        for i in (1, 2):
            _, out = self.sh(f"cache{i}", fx + ["test", f"--skip-cache={cache}", "-json", "."])
            o, n = {}, 0
            for line in out.splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("Test") and "/" not in d["Test"] and d.get("Action") in ("pass", "fail", "skip"):
                    o[d["Test"]] = d["Action"]
                if d.get("Test") and "reused" in (d.get("Output") or "").lower():
                    n += 1
            m = re.search(r"(\d+) (?:tests? )?reused|reused[: ]+(\d+)", out)
            outs.append(o)
            reused = max(n, int(next(g for g in m.groups() if g)) if m else 0)
        self.same_outcomes(outs[0], outs[1], reused)

    # -- JVM: agent (Maven) + fenvix-skip decider -----------------------------------------------------------------
    def _fenvix_copy(self, dst):
        """Move the run's .fenvix directory (trace, deps) out of the checkout."""
        src = os.path.join(self.repo, ".fenvix")
        shutil.rmtree(dst, ignore_errors=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
            shutil.rmtree(src, ignore_errors=True)
        return dst

    def jvm(self):
        mvn = ["mvn", "-q", "-B", "test", "-pl", "gson", "-am", "-Dmaven.javadoc.skip=true", "-Denforcer.skip=true"]
        self.sh("install", ["mvn", "-q", "-B", "-DskipTests", "install", "-pl", "gson", "-am"])
        traces = []
        for i in (1, 2):
            self.sh(f"det{i}", self.fx + ["jvm", "run", "--det", "--"] + mvn)
            d = self._fenvix_copy(os.path.join(self.work, f"det{i}"))
            traces.append(os.path.join(d, "trace.jsonl"))
        self.verify(*traces)
        deps = []
        for i in (1, 2):
            self.sh(f"cache{i}", self.fx + ["jvm", "run", "--det", "--deps", "--"] + mvn)
            deps.append(os.path.join(self._fenvix_copy(os.path.join(self.work, f"deps{i}")), "deps"))
        j = os.path.join(self.work, "decide.json")
        self.sh("decide", self.fx + ["jvm", "decide", deps[0], deps[1], "--root-b", self.repo, "--json", j])
        rows = json.load(open(j)) if os.path.exists(j) else []
        # B's measurement ran every test: B's own capture holds its fresh outcome
        fresh = {}
        for fn in sorted(os.listdir(deps[1])) if os.path.isdir(deps[1]) else ():
            for line in open(os.path.join(deps[1], fn)):
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("id") and d.get("outcome"):
                    fresh[d["id"]] = d["outcome"]
        reused = [r for r in rows if r.get("reusable")]
        wrong = [r.get("id") for r in reused if fresh.get(r.get("id"), "passed") != "passed"]
        self.check("cache_reused", len(reused) > 0, f"{len(reused)} of {len(rows)} tests reusable with proof")
        self.check("cache_same_outcomes", bool(rows) and not wrong,
                   f"{len(wrong)} reusable tests whose fresh outcome in B is not passed: {wrong[:10]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=sorted(REPOS))
    ap.add_argument("--engine", default=".")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    s = Smoke(a.lang, a.engine, a.work)
    info = s.clone()
    try:
        getattr(s, a.lang)()
    except Exception as e:  # recorded, never hidden
        import traceback

        traceback.print_exc()
        s.check("harness", False, f"{type(e).__name__}: {e}")
    ok = bool(s.checks) and all(c["ok"] for c in s.checks.values())
    res = {"lang": a.lang, "repo": info, "ok": ok, "checks": s.checks, "steps": s.steps,
           "run_id": os.environ.get("GITHUB_RUN_ID"), "runner": os.environ.get("RUNNER_NAME"),
           "platform": sys.platform, "machine": os.uname().machine}
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps({"lang": a.lang, "ok": ok, "checks": s.checks}, indent=1))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
