#!/usr/bin/env python3
"""Mutation check of the execution diff.

For one repository and one shard: install at a pinned commit, measure line
coverage once, generate line-preserving mutants (operator / constant flips)
on covered lines of non-test source files, then for each mutant of the shard
run the suite under ``--det`` (``-x``) and compare with two unmutated
``--det`` runs:

* killed: a test that passed in both baselines fails (or collection breaks);
* survived: every test keeps its baseline outcome; then the mutant is
  *flagged* by the trace diff if some test whose fingerprint was identical
  in both baselines gets another fingerprint, and flagged by the prototype
  probe (return values / calls / files) on the same rule.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import io
import json
import os
import random
import shutil
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (collect_args, first_divergence, git, install, is_test_path, locate, log,  # noqa: E402
                    read_json, read_trace, run_det, sh, short_event)

OPS = {"+": "-", "-": "+", "*": "/", "/": "*", "//": "/", "<": "<=", "<=": "<", ">": ">=", ">=": ">",
       "==": "!=", "!=": "==", "+=": "-=", "-=": "+="}
NAMES = {"and": "or", "or": "and", "True": "False", "False": "True"}
BINARY_PREV = (tokenize.NAME, tokenize.NUMBER, tokenize.STRING)


def mutants_of(path: Path, rel: str, lines: set) -> list:
    text = path.read_text()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
        tree_dump = ast.dump(ast.parse(text))
    except (SyntaxError, tokenize.TokenError, ValueError):
        return []
    src_lines = text.split("\n")
    out = []
    for i, t in enumerate(toks):
        row, col = t.start
        if row not in lines or t.start[0] != t.end[0]:
            continue
        prev = toks[i - 1] if i else None
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        new = None
        if t.type == tokenize.OP and t.string in OPS:
            if t.string in ("+", "-", "*") and not (prev and (prev.type in BINARY_PREV or prev.string in (")", "]", "}"))):
                continue  # unary / star-args
            if t.string in ("*", "/") and prev and prev.string in ("(", ","):
                continue
            new = OPS[t.string]
        elif t.type == tokenize.NAME and t.string in NAMES:
            new = NAMES[t.string]
        elif t.type == tokenize.NAME and t.string == "is" and nxt and nxt.string != "not":
            new = "is not"
        elif t.type == tokenize.NAME and t.string == "not" and prev and prev.string not in ("is",) \
                and nxt and nxt.string != "in":
            new = ""
        elif t.type == tokenize.NUMBER and t.string.isdigit():
            new = str(int(t.string) + 1)
        if new is None:
            continue
        line = src_lines[row - 1]
        if new == "":
            mutated_line = line[:col] + line[t.end[1]:].lstrip(" ")
        else:
            mutated_line = line[:col] + new + line[t.end[1]:]
        mutated = "\n".join(src_lines[:row - 1] + [mutated_line] + src_lines[row:])
        try:
            d = ast.dump(ast.parse(mutated))
        except (SyntaxError, ValueError):
            continue
        if d == tree_dump:
            continue
        out.append({"file": rel, "line": row, "col": col, "op": f"{t.string}->{new or '(removed)'}",
                    "orig_line": line, "new_line": mutated_line})
    return out


def apply(src: Path, m: dict, stamp: int) -> str:
    p = src / m["file"]
    orig = p.read_text()
    lines = orig.split("\n")
    assert lines[m["line"] - 1] == m["orig_line"], "source drifted"
    lines[m["line"] - 1] = m["new_line"]
    p.write_text("\n".join(lines))
    st = os.stat(p)
    os.utime(p, (st.st_atime, stamp))  # unique mtime: no stale .pyc can be reused
    return orig


def restore(src: Path, m: dict, orig: str, stamp: int) -> None:
    p = src / m["file"]
    p.write_text(orig)
    st = os.stat(p)
    os.utime(p, (st.st_atime, stamp))


def is_fail(o) -> bool:
    return o is not None and (o.startswith("failed") or o.startswith("error") or "teardown-error" in o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--install", default="[]")
    ap.add_argument("--pytest-args", default="[]")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--per-shard", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--work", default="/tmp/work")
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default="3.12")
    ap.add_argument("--budget", type=float, default=2400, help="seconds for the mutant loop")
    ap.add_argument("--recheck", default="",
                    help="directory of earlier shard results: re-run only their survivors, with test ids")
    ap.add_argument("--controls", type=int, default=0,
                    help="no-op mutants (same file rewritten unchanged, new mtime) run before the mutants")
    a = ap.parse_args()
    a.wheel = str(Path(a.wheel).resolve())
    import time
    t_start = time.monotonic()
    key = f"recheck-{a.repo}" if a.recheck else f"{a.repo}-s{a.shard}"
    work = Path(a.work) / key
    shutil.rmtree(work, ignore_errors=True)
    src, rundir = work / "src", work / "runs"
    rundir.mkdir(parents=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    out_path = Path(a.out) / f"{key}.json.gz"
    res = {"key": key, "repo": a.repo, "ref": a.ref, "shard": a.shard, "status": "pending", "mutants": []}

    def finish(status, detail=""):
        res["status"], res["detail"] = status, detail[-1500:]
        with gzip.open(out_path, "wt") as f:
            json.dump(res, f)
        log(f"{key}: {status} {detail[-300:]}")
        return 0

    code, out, _, _ = sh(["git", "clone", "--quiet", "--filter=blob:none", a.url, str(src)], timeout=900)
    if code != 0:
        return finish("clone-failed", out)
    git(src, "checkout", "--quiet", "--force", a.ref)
    venv = work / "venv"
    py = str(venv / "bin" / "python")
    sh(["uv", "venv", "--quiet", "--python", a.python, str(venv)], timeout=600)
    ok, how = install(src, py, a.wheel, json.loads(a.install) + ["coverage"], rundir / "install.log")
    if not ok:
        return finish("install-failed", how)
    args, n, out = collect_args(py, src, json.loads(a.pytest_args))
    if args is None:
        return finish("collect-failed", out)
    res["pytest_args"] = args
    if a.recheck:
        mine = []
        for p in sorted(Path(a.recheck).glob(f"{a.repo}-s*.json.gz")):
            with gzip.open(p, "rt") as f:
                old = json.load(f)
            mine += [{k: m[k] for k in ("file", "line", "col", "op", "orig_line", "new_line")}
                     for m in old.get("mutants", []) if m.get("status") == "survived"]
        res["candidates"] = len(mine)
        log(f"{key}: re-checking {len(mine)} survivors")
        return run_mutants(a, key, src, rundir, py, args, mine, res, finish, t_start)
    # Coverage (plain run, fixed order) -> covered lines of non-test source files.
    cov_json = rundir / "coverage.json"
    code, out, dur, _ = sh([py, "-m", "coverage", "run", f"--include={src}/*", "--data-file", str(rundir / ".cov"),
                            "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", *args],
                           cwd=src, timeout=1800)
    sh([py, "-m", "coverage", "json", "--data-file", str(rundir / ".cov"), "-o", str(cov_json)], cwd=src)
    cov = read_json(cov_json, {}) or {}
    candidates = []
    for fname, data in sorted((cov.get("files") or {}).items()):
        p = Path(fname) if os.path.isabs(fname) else src / fname
        try:
            rel = str(p.resolve().relative_to(src.resolve()))
        except ValueError:
            continue
        if is_test_path(rel) or not rel.endswith(".py") or rel.startswith(("docs/", "doc/", "setup.py", "noxfile")):
            continue
        candidates += mutants_of(p, rel, set(data.get("executed_lines", [])))
    rng = random.Random(a.seed)
    rng.shuffle(candidates)
    res["candidates"] = len(candidates)
    mine = candidates[a.shard * a.per_shard:(a.shard + 1) * a.per_shard]
    log(f"{key}: {len(candidates)} candidate mutants, shard has {len(mine)}")
    return run_mutants(a, key, src, rundir, py, args, mine, res, finish, t_start)


def run_mutants(a, key, src, rundir, py, args, mine, res, finish, t_start) -> int:
    import time
    if a.controls and mine:
        f0 = mine[0]["file"]
        line0 = (src / f0).read_text().split("\n")
        ln = next(i for i, x in enumerate(line0, 1) if x.strip())
        ctrl = {"file": f0, "line": ln, "col": 0, "op": "control", "orig_line": line0[ln - 1],
                "new_line": line0[ln - 1], "control": True}
        mine = [dict(ctrl) for _ in range(a.controls)] + mine
    # Baselines.
    base = {}
    for tag in ("base1", "base2"):
        r = run_det(py, src, rundir, tag, args, 1800)
        base[tag] = {"trace": read_trace(r["trace"])[1], "probe": read_json(r["probe"], {}) or {},
                     "dur": r["duration_s"]}
        log(f"{key}: {tag} exit={r['exit']} {r['duration_s']}s tests={len(base[tag]['trace'])}")
    b1, b2 = base["base1"]["trace"], base["base2"]["trace"]
    p1, p2 = base["base1"]["probe"], base["base2"]["probe"]
    stable_fp = {n for n in b1 if n in b2 and b1[n]["fingerprint"] == b2[n]["fingerprint"]}
    stable_out = {n for n in b1 if n in b2 and b1[n]["outcome"] == b2[n]["outcome"]}
    stable_pr = {k: {n for n in p1 if n in p2 and p1[n][k] == p2[n][k]} for k in ("calls", "rets")}
    stable_pr["files"] = {n for n in p1 if n in p2 and p1[n]["files"] == p2[n]["files"]}
    res["baseline"] = {"tests": len(b1), "fp_stable": len(stable_fp), "outcome_stable": len(stable_out),
                       "probe_stable": {k: len(v) for k, v in stable_pr.items()},
                       "duration_s": [base["base1"]["dur"], base["base2"]["dur"]],
                       "with_informative_events": sum(1 for n in b1 if b1[n]["n_events"] > 2)}
    timeout = max(60.0, 6 * max(base["base1"]["dur"], base["base2"]["dur"]))
    stamp = int(time.time()) + 1000
    for k, m in enumerate(mine):
        if time.monotonic() - t_start > a.budget:
            res["budget_exhausted_at"] = k
            break
        orig = apply(src, m, stamp + 2 * k)
        try:
            r = run_det(py, src, rundir, "mut", args, timeout, ["-x"])
        finally:
            restore(src, m, orig, stamp + 2 * k + 1)
        tr = read_trace(r["trace"])[1]
        pm = read_json(r["probe"], {}) or {}
        entry = dict(m, exit=r["exit"], duration_s=r["duration_s"])
        killers = [n for n in tr if n in stable_out and not is_fail(b1[n]["outcome"]) and is_fail(tr[n]["outcome"])]
        if r["timed_out"]:
            entry["status"] = "timeout"
        elif killers or r["exit"] not in (0, 1, 5) or not tr:
            entry["status"] = "killed"
            entry["killers"] = killers[:3]
        else:
            changed_outcome = [n for n in stable_out if n in tr and tr[n]["outcome"] != b1[n]["outcome"]]
            missing = [n for n in stable_out if n not in tr]
            if changed_outcome or missing:
                entry["status"] = "killed" if changed_outcome else "incomplete"
                entry["killers"] = changed_outcome[:3]
            else:
                entry["status"] = "survived"
                div = sorted(n for n in stable_fp if n in tr and tr[n]["fingerprint"] != b1[n]["fingerprint"])
                entry["det_flag_tests"] = len(div)
                entry["det_ids"] = div[:200]
                if div:
                    a1, h1 = b1[div[0]], tr[div[0]]
                    i, ea, eb = first_divergence(a1["events"], h1["events"])
                    entry["det_example"] = {"test": div[0], "i": i, "base": short_event(ea),
                                            "mutant": short_event(eb), "loc": locate(ea, eb, {m["file"]})}
                    from collections import Counter
                    srcs = Counter()
                    firsts = {}
                    for n in div:
                        j, x, y = first_divergence(b1[n]["events"], tr[n]["events"])
                        srcs[(x or y or {"s": "?"})["s"]] += 1
                        if len(firsts) < 200:
                            firsts[n] = {"base": short_event(x), "mutant": short_event(y),
                                         "loc": locate(x, y, {m["file"]})}
                    entry["det_sources"] = dict(srcs)
                    entry["det_firsts"] = firsts
                for kk in ("calls", "rets", "files"):
                    ids = sorted(n for n in stable_pr[kk] if n in pm and pm[n][kk] != p1[n][kk])
                    entry[f"probe_{kk}_tests"] = len(ids)
                    entry[f"probe_{kk}_ids"] = ids[:200]
                entry["tests_running_file"] = sum(1 for n in pm if m["file"] in pm[n]["files"])
        res["mutants"].append(entry)
        log(f"{key}: mutant {k} {m['file']}:{m['line']} {m['op']} -> {entry['status']}"
            + (f" det={entry.get('det_flag_tests')} rets={entry.get('probe_rets_tests')}"
               if entry["status"] == "survived" else ""))
    return finish("ok")


if __name__ == "__main__":
    sys.exit(main())
