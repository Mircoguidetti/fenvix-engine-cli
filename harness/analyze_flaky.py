#!/usr/bin/env python3
"""Classify the likely cause of baseline-flaky tests that --det did not reproduce.

Classes (P-005):
  a  concurrency / timing inside Python (asyncio, threads, multiprocessing, sleeps, timeouts, clocks)
  b  external to the process (network to real services, subprocesses, filesystem/disk, environment, machine speed)
  c  order / state that Level 0 should have covered (a gap of ours): order-dependent per IDoFT, or shared
     state between tests (globals, class attributes, caches, module state)
  d  unknown

Evidence used, in this order: the IDoFT category of the test, the first diverging event between a passing and a
failing --det run, the exception type and message, and the source of the test function (fetched from the
repository at the measured commit). The rules are keyword heuristics; every decision keeps its evidence in the
output so it can be audited.

    python harness/analyze_flaky.py --results harness/results/mixed --work /tmp/flaky-src
"""

from __future__ import annotations

import argparse
import ast
import collections
import csv
import json
import re
import subprocess
from pathlib import Path

A = re.compile(r"\b(threading|Thread\(|asyncio|async def|await |multiprocessing|concurrent\.futures|ThreadPool|"
               r"ProcessPool|time\.sleep|sleep\(|timeout|Timeout|time\.time\(|monotonic|perf_counter|datetime\.now|"
               r"utcnow|Event\(\)|Lock\(|Queue\(|signal\.|alarm|gevent|trio|anyio|tornado|twisted|freeze_time)")
B = re.compile(r"\b(requests\.|urllib|urlopen|http\.client|httpx|aiohttp|socket\.|smtplib|ftplib|getaddrinfo|"
               r"https?://|\.connect\(|subprocess|Popen|os\.system|check_output|docker|redis|psycopg|pymysql|"
               r"sqlite3\.connect|mongo|boto|s3|os\.environ|getenv|shutil\.disk_usage|statvfs|os\.stat|getmtime|"
               r"st_mtime|tempfile|NamedTemporaryFile|open\(|chmod|getpass|platform\.|cpu_count|psutil)")
C = re.compile(r"\b(global |setUpClass|tearDownClass|setup_module|teardown_module|_cache|cache_clear|lru_cache|"
               r"monkeypatch|mock\.patch|registry|singleton|__class__\.|sys\.modules|importlib\.reload|"
               r"os\.chdir|sys\.path)")
EXC_A = {"TimeoutError", "Timeout", "CancelledError", "BrokenPipeError", "DeadlockError"}
EXC_B = {"ConnectionError", "ConnectionRefusedError", "ConnectionResetError", "URLError", "HTTPError", "gaierror",
         "SSLError", "NetworkBlockedError", "ReadTimeout", "ConnectTimeout", "PermissionError", "FileNotFoundError",
         "CalledProcessError", "OSError"}


_SETUP = ("setUp", "tearDown", "setUpClass", "tearDownClass", "setup_method", "teardown_method",
          "setup_class", "teardown_class", "setup", "teardown")


def test_source(repo_dir: Path, nodeid: str) -> str:
    """Source of the test function, plus what runs with it in the same module.

    Added after the review R-001 (P-009 item 4): the set-up/tear-down methods of its
    class, and the module-level functions and same-class methods it calls (one level).
    Tests that are one-line calls of a shared helper otherwise get classified from
    their single line, so the same mechanism ended up in different classes.
    """
    path, _, rest = nodeid.partition("::")
    f = repo_dir / path
    if not f.exists():
        return ""
    try:
        src = f.read_text(errors="replace")
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return ""
    parts = [p.split("[", 1)[0] for p in rest.split("::") if p]
    nodes = tree.body
    found, owner = None, None
    for name in parts:
        owner = found
        found = next((n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and n.name == name), None)
        if found is None:
            return ""
        nodes = getattr(found, "body", [])
    if found is None:
        return ""
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
    module_funcs = {n.name: n for n in tree.body if isinstance(n, funcs)}
    methods = {n.name: n for n in owner.body if isinstance(n, funcs)} if isinstance(owner, ast.ClassDef) else {}
    extra = [methods[n] for n in _SETUP if n in methods]
    for node in ast.walk(found):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in module_funcs:
            extra.append(module_funcs[fn.id])
        elif (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in ("self", "cls")
              and fn.attr in methods):
            extra.append(methods[fn.attr])
    seen, segs = {id(found)}, [ast.get_source_segment(src, found) or ""]
    for n in extra:
        if id(n) not in seen:
            seen.add(id(n))
            segs.append(ast.get_source_segment(src, n) or "")
    return "\n".join(segs)


def checkout(work: Path, url: str, commit: str) -> Path | None:
    d = work / re.sub(r"[^A-Za-z0-9_.-]", "_", url.rstrip("/").split("/")[-1] + "-" + commit)
    if (d / ".git").exists():
        return d
    d.mkdir(parents=True, exist_ok=True)
    for cmd in (["git", "init", "-q"], ["git", "remote", "add", "origin", url],
                ["git", "fetch", "-q", "--depth", "1", "origin", commit], ["git", "checkout", "-q", "FETCH_HEAD"]):
        if subprocess.run(cmd, cwd=d, capture_output=True).returncode != 0:
            # short commit ids cannot be fetched directly: fall back to a full clone
            subprocess.run(["rm", "-rf", str(d)])
            r = subprocess.run(["git", "clone", "-q", url, str(d)], capture_output=True)
            if r.returncode != 0:
                return None
            subprocess.run(["git", "checkout", "-q", commit], cwd=d, capture_output=True)
            return d
    return d


# Filesystem state in a fixed directory (not a per-test temporary one): under the xdist
# baseline two workers share it (cross-process race that a serial --det run never has).
FS_WRITE = re.compile(r"\b(shutil\.rmtree|rmtree\(|os\.remove|os\.unlink|os\.makedirs|os\.mkdir|\.mkdir\(|"
                      r"\.unlink\(|\.write_text\(|open\([^)]*['\"][wa]b?['\"])")
FS_TEMP = re.compile(r"\b(tmp_path|tmpdir|tempfile|mkdtemp|TemporaryDirectory|tmp_path_factory)")


_BEST_SEED = re.compile(r"seed\s*(\d+)\s*:\s*(\d+)\s*/\s*(\d+)")


def _seed_failures(row: dict) -> int:
    """Failures in the serial --det seed runs (best_attempt "seed S:k/n"): a failure
    there happened in one process, so it is not a cross-process race (N4)."""
    m = _BEST_SEED.search(row.get("best_attempt", "") or "")
    return int(m.group(2)) if m else 0


TIME_IN_ID = re.compile(r"\[[^\]]*\d{1,4}[-/:]\d{1,2}[-/:]\d{1,4}[^\]]*\]")


def classify(row: dict, src: str) -> tuple[str, str]:
    cat = row.get("idoft_category", "")
    hist = dict(kv.split("=") for kv in row.get("baseline_outcomes", "").split(";") if "=" in kv)
    if "missing" in hist and TIME_IN_ID.search(row["nodeid"]):
        return "a", "test id contains the wall-clock time at collection: it changes every run (stable under --det)"
    if hist and all(k.startswith(("failed", "error")) for k in hist):
        return "d", ("fails in every baseline run; only the failing phase changes "
                     f"({', '.join(sorted(hist))}): not flaky in outcome")
    shared_fs = (row.get("_xdist") and row.get("_never_under_det") and not _seed_failures(row)
                 and FS_WRITE.search(src) and not FS_TEMP.search(src))
    if shared_fs and not (cat.startswith("OD") or cat == "NIO"):
        hits = sorted(set(m.group(0) for m in FS_WRITE.finditer(src)))
        return "b", ("filesystem state in a fixed (non-temporary) directory, written by the test or its "
                     f"set-up/helpers ({', '.join(hits[:3])}): the xdist baseline workers share it, a serial "
                     "--det run never does (cross-process, outside Level 0)")
    reason = row.get("pass_fail_reason", "") or row.get("det_reason", "")
    exc = row.get("det_exception") or row.get("baseline_exception") or ""
    msg = row.get("det_exception_message", "")
    if cat.startswith("OD") or cat == "NIO":
        extra = (" (brittle: fails when its state-setter did not run first; in the baseline xdist can place them "
                 "on different workers, which a permutation of the full suite never does)") if cat == "OD-Brit" else ""
        return "c", f"IDoFT category {cat} (order/state dependent) not reproduced by the explored seeds{extra}"
    if reason in ("net",) or exc in EXC_B or B.search(msg):
        return "b", f"exception {exc or '-'} / diverging event {reason or '-'}"
    if reason in ("thread", "time") or exc in EXC_A:
        return "a", f"exception {exc or '-'} / diverging event {reason or '-'}"
    hits_b = sorted(set(B.findall(src)))
    hits_a = sorted(set(A.findall(src)))
    if hits_b and not hits_a:
        return "b", f"test source uses {', '.join(hits_b[:4])}"
    if hits_a:
        return "a", f"test source uses {', '.join(hits_a[:4])}" + (f"; also {', '.join(hits_b[:3])}" if hits_b else "")
    hits_c = sorted(set(C.findall(src)))
    if hits_c or reason in ("random", "fs", "entropy"):
        return "c", (f"test source uses {', '.join(hits_c[:4])}" if hits_c else f"diverging event {reason}")
    if cat == "NOD":
        return "d", "IDoFT category NOD, no concurrency/external marker found"
    return "d", "no marker in the source, exception or fingerprint" + ("" if src else " (source not found)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    res, work = Path(args.results), Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    summaries = {json.loads(p.read_text())["name"]: json.loads(p.read_text()) for p in res.glob("*.summary.json")}
    out_rows, counts, by_pool = [], collections.Counter(), collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    idoft = []
    for name, s in sorted(summaries.items()):
        rows = list(csv.DictReader(open(res / f"{name}.csv")))
        repo_dir = None
        unstable = [r for r in rows if r["baseline_unstable"] == "True" and r["reproduced"] != "True"]
        if unstable:
            repo_dir = checkout(work, s["url"], s["commit"])
        for r in unstable:
            src = test_source(repo_dir, r["nodeid"]) if repo_dir else ""
            never = all(not o.startswith(("failed", "error")) for o in
                        [x.split("=")[0] for x in r["det_outcomes"].split(";")])
            never = never and not _seed_failures(r)
            cls, why = classify({**r, "_xdist": bool(s.get("xdist")), "_never_under_det": never}, src)
            out_rows.append({"repo": name, "pool": s["kind"], "nodeid": r["nodeid"], "class": cls, "evidence": why,
                             "idoft_category": r.get("idoft_category", ""), "under_det": "never fails" if never
                             else "fails sometimes/always", "baseline_outcomes": r["baseline_outcomes"],
                             "det_exception": r.get("det_exception", ""), "baseline_exception": r.get("baseline_exception", ""),
                             "pass_fail_reason": r.get("pass_fail_reason", "")})
            counts[cls] += 1
            by_pool[s["kind"]][cls] += 1
            if len(examples[cls]) < 6:
                examples[cls].append(f"{name}: `{r['nodeid']}` ({why})")
        if s["kind"] == "flaky":
            idoft.append({"repo": name, "commit": s["commit"], "python": s["python"], "xdist": s["xdist"],
                          "known": s["known_flaky"], "present": s["known_present"],
                          "flaky_in_baseline": s["known_unstable_baseline"], "reproduced": s["known_reproduced"],
                          "categories": s.get("known_categories", {}), "unstable_baseline_all": s["unstable_baseline"]})
    with open(res / "not-reproduced-causes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else ["repo"])
        w.writeheader()
        w.writerows(out_rows)
    (res / "not-reproduced-causes.json").write_text(json.dumps(
        {"counts": dict(counts), "by_pool": {k: dict(v) for k, v in by_pool.items()},
         "examples": dict(examples), "idoft": idoft}, indent=2))
    print(json.dumps({"counts": dict(counts), "by_pool": {k: dict(v) for k, v in by_pool.items()}}, indent=1))


if __name__ == "__main__":
    main()
