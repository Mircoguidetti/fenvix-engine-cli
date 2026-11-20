#!/usr/bin/env python3
"""Go skip with proof over a commit history (P-021 step 5b).

One repository, one shard of its packages (package import path hashed mod N), the last 50 first-parent commits
before a fixed date. At every commit:

1. `fenvix-go test --skip-cache C --skip-verify -json <shard>`: every test runs (fresh outcome), and fenvix
   records which tests its key would have reused with proof (decisions file). Every such reuse is checked against
   the fresh outcome: a reuse is wrong when the cached outcome (always "passed") differs from the fresh one; a
   wrong-looking reuse is re-run 3 times alone to separate flaky tests from wrong reuses.
2. `go test -json <shard>` with a GOCACHE kept across commits: the packages Go's own test cache reports as
   "(cached)". Their tests are compared with the fresh fenvix outcomes the same way.

Share of test time skipped = sum of the fresh elapsed time of the reused tests / sum over all tests (both rules
weighted with the same fresh per-test times).

    python3 harness/go/skip_walk.py --spec spec.json --shard 0 --shards 4 --fenvix fenvix-go --work /tmp/w --out out.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, file=sys.stderr, flush=True)


def sh(cmd, cwd=None, env=None, timeout=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out, "TIMEOUT"


def git(cwd, *args, timeout=1800):
    return sh(["git", *args], cwd=cwd, timeout=timeout)


def parse_go_json(out):
    """-> {pkg: {"cached": bool, "ok": bool|None, "tests": {name: outcome}, "elapsed": s}}"""
    res = {}
    for line in out.splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        pkg = ev.get("Package")
        if not pkg:
            continue
        r = res.setdefault(pkg, {"cached": False, "ok": None, "tests": {}, "elapsed": None})
        act, test = ev.get("Action"), ev.get("Test")
        if act == "output" and not test and "(cached)" in (ev.get("Output") or ""):
            r["cached"] = True
        if test and "/" not in test and act in ("pass", "fail", "skip"):
            r["tests"][test] = {"pass": "passed", "fail": "failed", "skip": "skipped"}[act]
        elif not test and act in ("pass", "fail", "skip"):
            r["ok"] = act != "fail"
            r["elapsed"] = ev.get("Elapsed")
    return res


def in_shard(pkg, shard, shards):
    return int(hashlib.sha1(pkg.encode()).hexdigest(), 16) % shards == shard


def commit_partial(path, msg):
    """Commit and push the partial result, so a runner that dies keeps what it measured."""
    repo = Path(__file__).resolve().parents[2]
    sh(["git", "add", path], cwd=repo)
    if sh(["git", "commit", "-qm", f"Go harness: {msg}"], cwd=repo)[0] != 0:
        return
    for k in range(6):
        if sh(["git", "pull", "--rebase", "-q"], cwd=repo, timeout=300)[0] == 0 and \
                sh(["git", "push", "-q"], cwd=repo, timeout=300)[0] == 0:
            return
        time.sleep(5 * (k + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--fenvix", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--commits", type=int, default=50)
    ap.add_argument("--budget", type=float, default=320 * 60)
    ap.add_argument("--commit-every", type=int, default=0, help="commit and push the partial result every N commits")
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    src = work / "src"
    cache = work / "fenvix-skip"
    result = {"spec": spec, "shard": a.shard, "shards": a.shards, "commits": [], "notes": []}

    def flush():
        result["seconds"] = round(time.time() - T0, 1)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(a.out, "wt") as f:
            json.dump(result, f, separators=(",", ":"))

    if not src.exists():
        url = spec.get("local_path") or f"https://github.com/{spec['repo']}"
        code, out, err = sh(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", url, str(src)], timeout=3600)
        if code != 0:
            result["error"] = err[-2000:]
            flush()
            return
    branch = spec.get("branch", "HEAD")
    code, out, _ = git(src, "rev-list", "--first-parent", f"-n{a.commits + 1}", f"--before={spec['before']}",
                       f"origin/{branch}" if branch != "HEAD" else "origin/HEAD")
    commits = list(reversed(out.split()))
    result["window"] = commits
    log(spec["repo"], "shard", a.shard, "/", a.shards, len(commits), "commits")
    env = dict(os.environ)
    env["GOCACHE"] = str(work / "gocache")
    for k, v in (spec.get("env") or {}).items():
        env[k] = v
    moddir_rel = spec.get("module_dir", ".")
    timeout = spec.get("timeout", "20m")
    go_args = spec.get("go_args", [])
    exclude = spec.get("exclude", [])
    for i, sha in enumerate(commits):
        if time.time() - T0 > a.budget:
            result["notes"].append(f"budget reached at commit {i}")
            break
        t_commit = time.time()
        git(src, "checkout", "-q", "-f", sha)
        moddir = src / moddir_rel
        row = {"i": i, "sha": sha}
        code, out, err = sh(["go", "list", "-e", "-f", "{{if or .TestGoFiles .XTestGoFiles}}{{.ImportPath}}{{end}}",
                             "./..."], cwd=moddir, env=env, timeout=1800)
        pkgs = sorted(p for p in out.split() if p and not p.startswith("go:")
                      and in_shard(p, a.shard, a.shards) and not any(x in p for x in exclude))
        row["packages"] = len(pkgs)
        if not pkgs:
            row["status"] = "no-packages"
            row["error"] = err[-1500:]
            result["commits"].append(row)
            flush()
            continue
        # 1. fenvix: every test runs, decisions say which would be reused
        report = work / f"decisions-{i}.jsonl"
        code, out, err = sh([a.fenvix, "test", f"--skip-cache={cache}", "--skip-verify", f"--skip-report={report}",
                             f"--skip-commit={sha}", "-json", f"-timeout={timeout}", *go_args, *pkgs],
                            cwd=moddir, env=env, timeout=4 * 3600)
        fresh = parse_go_json(out)
        row["fenvix_exit"] = code
        row["fenvix_wall"] = round(time.time() - t_commit, 1)
        if code not in (0, 1) and not fresh:
            row["fenvix_tail"] = (out + err)[-2500:]
        decisions = []
        try:
            with open(report) as f:
                decisions = [json.loads(l) for l in f if l.strip()]
        except OSError:
            row["notes"] = "no decisions file"
        # 2. go's own test cache (it does not cache results that read files modified in the last 2 s)
        time.sleep(max(0.0, 2.1 - (time.time() - t_commit)))
        t = time.time()
        code2, out2, _ = sh(["go", "test", "-json", f"-timeout={timeout}", *go_args, *pkgs], cwd=moddir, env=env,
                            timeout=4 * 3600)
        gores = parse_go_json(out2)
        row["go_wall"] = round(time.time() - t, 1)
        go_cached = sorted(p for p, r in gores.items() if r["cached"])
        # per test rows
        tests = []
        for d in decisions:
            tests.append({"pkg": d["pkg"], "test": d["test"], "reuse": d["reuse"], "why": d.get("why", ""),
                          "reuse_own": d.get("reuse_own", False), "why_own": d.get("why_own", ""),
                          "cached": d.get("cached", ""), "fresh": d.get("fresh", ""), "elapsed": d.get("elapsed", 0),
                          "go_cached": d["pkg"] in go_cached,
                          # the plain go test outcome of the same commit (R-025b S1: broken by skip mode)
                          "plain": gores.get(d["pkg"], {}).get("tests", {}).get(d["test"], "")})
        # wrong-looking reuses: re-run alone 3 times (plain go test) to separate flaky tests
        checks = []
        for tr in tests:
            for rule, reused in (("fenvix", tr["reuse"]), ("own", tr.get("reuse_own")), ("go", tr["go_cached"])):
                if not reused or i == 0 or tr["fresh"] in ("", "skipped"):
                    continue
                cached_outcome = tr["cached"] if rule in ("fenvix", "own") else "passed"
                if tr["fresh"] == cached_outcome:
                    continue
                pkgdir = None
                code3, out3, _ = sh(["go", "list", "-f", "{{.Dir}}", tr["pkg"]], cwd=moddir, env=env, timeout=600)
                pkgdir = out3.strip() or str(moddir)
                outs, fouts = [], []
                for _ in range(3):
                    c4, o4, _ = sh(["go", "test", "-count=1", "-json", "-run", f"^{tr['test']}$", f"-timeout={timeout}",
                                    *go_args, "."], cwd=pkgdir, env=env, timeout=3600)
                    outs.append(parse_go_json(o4).get(tr["pkg"], {}).get("tests", {}).get(tr["test"], "missing"))
                    # the same, under fenvix's skip mode (its clock and process): R-025b S1, R-022's blind spot
                    fc = work / f"rerun-cache-{i}"
                    shutil.rmtree(fc, ignore_errors=True)
                    c5, o5, _ = sh([a.fenvix, "test", f"--skip-cache={fc}", "--skip-verify", "-json", "-run",
                                    f"^{tr['test']}$", f"-timeout={timeout}", *go_args, "."], cwd=pkgdir, env=env,
                                   timeout=3600)
                    fouts.append(parse_go_json(o5).get(tr["pkg"], {}).get("tests", {}).get(tr["test"], "missing"))
                plain_ok = cached_outcome in outs
                fenvix_ok = cached_outcome in fouts
                verdict = "flaky" if plain_ok and fenvix_ok else ("broken-by-skip" if plain_ok else "wrong")
                checks.append({"rule": rule, "pkg": tr["pkg"], "test": tr["test"], "cached": cached_outcome,
                               "fresh": tr["fresh"], "reruns": outs, "fenvix_reruns": fouts, "verdict": verdict})
        row.update({"status": "ok", "tests": tests, "go_cached_packages": go_cached, "checks": checks,
                    "seconds": round(time.time() - t_commit, 1)})
        n = len(tests)
        reused = sum(1 for x in tests if x["reuse"])
        log(f"[{i}] {sha[:10]} pkgs {len(pkgs)} tests {n} fenvix-reuse {reused} go-cached-pkgs {len(go_cached)} "
            f"checks {len(checks)} {row['seconds']}s")
        result["commits"].append(row)
        flush()
        if a.commit_every and i % a.commit_every == a.commit_every - 1:
            commit_partial(a.out, f"{spec['name']} shard {a.shard}/{a.shards}: {i + 1} commits (partial)")
    flush()


if __name__ == "__main__":
    main()
