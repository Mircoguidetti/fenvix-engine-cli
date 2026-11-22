#!/usr/bin/env python3
"""For every repository that lives with flaky tests (scan.jsonl), find deliberate SERIAL test execution and count
tests. Same read-only partial fetch as scan_repos.py (depth-1 blobless clone, sparse checkout of test/config/CI
files, nothing executed). Writes serial_scan.jsonl.

Serial signals (value must force one worker):
  jest      --runInBand / -i / --maxWorkers=1 / maxWorkers: 1
  vitest    fileParallelism: false / --no-file-parallelism / singleThread|singleFork: true / maxThreads|maxForks|
            maxWorkers: 1 / --pool.*single / poolOptions single
  playwright workers: 1 (also `process.env.CI ? 1 : undefined`, the scaffold default, flagged as such) /
            --workers=1 / fullyParallel: false
  cypress/mocha are serial by default and are not flagged; mocha `parallel: false` is not a decision either.
  pytest    -n 0 / -p no:xdist / --dist no / xdist_group / @pytest.mark.serial / pytest-serial
A reason is "stated" when the comment on or directly above/below the line (3 lines) has one of REASON_WORDS.
Test count (ESTIMATED): lines that open a JS test (`it(`/`test(` and their .only/.skip/.each forms) or a Python
`def test_` in the selected files.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from build_scan import PATH_EXCLUDE as PATH_EXCLUDE_RE
from scan_repos import COMMENT, MAX_BYTES, MAX_FILES, WORK, esc, git, select

HERE = Path(__file__).resolve().parent
# Words that give a REASON (why serial), not ones that only restate it ("serially", "in parallel").
REASON_WORDS = re.compile(r"\bflak\w*|\bintermittent\w*|\bunstable\b|\brac(?:e|es|y|ing)\b|\bshared\b|\bshares?\b|"
                          r"\bdatabases?\b|\b(?:db|postgres\w*|mysql|redis|mongo\w*|sqlite)\b|\bports?\b|\bconflict\w*|"
                          r"\binterfer\w*|\bconcurren\w*|\bdeadlock\w*|\block(?:s|ing)?\b|\btiming\b|\bmemory\b|"
                          r"\bOOM\b|\bresources?\b|\bcollid\w*|\bcollision\w*|\bclobber\w*|\bsingleton\b|"
                          r"\bcontention\b|\bstomp\w*|\bleak\w*|\bsame (?:file|dir\w*|server|instance|account)\b", re.I)
# Comments Playwright's generator writes next to `workers` / `fullyParallel`: not a decision, not a reason.
SCAFFOLD_COMMENT = re.compile(r"Opt out of parallel tests on CI|Run tests in files in parallel", re.I)
# a trailing comment starts after whitespace or at line start: `http://host` and `"#id"` are not comments
TRAILING = re.compile(r"(?:^|\s)(?://|#)\s+(.*)$")


def comment_text(lines: list[str], i: int) -> str:
    """Comment text on line i (trailing) and in the comment lines directly above/below it (max 3 each way)."""
    parts = []
    m = TRAILING.search(lines[i])
    if m:
        parts.append(m.group(1))
    for rng in (range(i - 1, max(-1, i - 4), -1), range(i + 1, min(len(lines), i + 4))):
        for j in rng:
            if COMMENT.match(lines[j]):
                parts.append(lines[j])
            else:
                break
    return "\n".join(x for x in parts if not SCAFFOLD_COMMENT.search(x))
TEST_JS = re.compile(r"^\s*(?:it|test)(?:\.(?:only|skip|each|concurrent|fixme|todo|fails|skipIf|runIf)\b[^(]*)?\s*\(")
TEST_PY = re.compile(r"^\s*(?:async\s+)?def\s+test_\w*\s*\(")


def serial_for_line(path: str, line: str) -> list[tuple[str, str]]:
    base = path.lower().rsplit("/", 1)[-1]
    out = []
    if re.search(r"\bjest\b[^\n]*(--runInBand\b|\s-i\b|--maxWorkers[= ]+1\b|-w[= ]+1\b)", line):
        out.append(("jest_runInBand", "cli"))
    if re.match(r"^jest[\w.-]*\.config", base) or base == "package.json":
        if re.search(r"[\"']?\bmaxWorkers[\"']?\s*:\s*[\"']?1\b(?!\d|%)", line):
            out.append(("jest_maxWorkers1", "config"))
    if re.match(r"^vite(st)?[\w.-]*\.(config|workspace)", base):
        if re.search(r"\bfileParallelism\s*:\s*false\b", line):
            out.append(("vitest_fileParallelism_false", ""))
        if re.search(r"\bsingle(?:Thread|Fork)\s*:\s*true\b", line):
            out.append(("vitest_single", ""))
        if re.search(r"\bmax(?:Threads|Forks|Workers|Concurrency)\s*:\s*1\b(?!\d)", line):
            out.append(("vitest_max1", ""))
    if re.search(r"\bvitest\b[^\n]*(--no-file-parallelism|--fileParallelism[= ]false|--maxWorkers[= ]+1\b|"
                 r"--pool(?:Options)?[.=\w]*single|--(?:single-?thread|singleThread))", line):
        out.append(("vitest_cli_serial", ""))
    if re.match(r"^playwright[\w.-]*\.config", base):
        m = re.search(r"\bworkers\s*:\s*([^\n,]+)", line)
        if m:
            v = m.group(1).strip()
            if re.fullmatch(r"process\.env\.CI\s*\?\s*1\s*:\s*undefined", v):
                out.append(("playwright_workers1", "scaffold-default CI ? 1 : undefined"))
            elif re.fullmatch(r"1|['\"]1['\"]", v) or re.search(r"\?\s*1\s*:\s*1\b", v):
                out.append(("playwright_workers1", v[:60]))
            elif re.search(r"\?\s*1\s*:", v) or re.search(r":\s*1\s*$", v):
                out.append(("playwright_workers1", "conditional " + v[:50]))
        if re.search(r"\bfullyParallel\s*:\s*false\b", line):
            out.append(("playwright_fullyParallel_false", ""))
    if re.search(r"\bplaywright\b[^\n]*--workers[= ]+1\b", line):
        out.append(("playwright_workers1", "cli"))
    if re.search(r"(?:^|[\s\"'])-n[= ]?0\b|-p[= ]?no:xdist\b|--dist[= ]no\b", line) and re.search(r"pytest|addopts", line):
        out.append(("pytest_no_xdist", ""))
    if re.search(r"@pytest\.mark\.(serial|xdist_group)\b|\bpytest-serial\b", line):
        out.append(("pytest_serial_mark", ""))
    return out


def scan_repo(repo: str) -> dict:
    res = {"repo": repo, "serial_status": "ok", "serial_signals": [], "test_count": 0, "test_files": 0}
    d = WORK / ("ser__" + repo.replace("/", "__"))
    shutil.rmtree(d, ignore_errors=True)
    try:
        r = git(["clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", "--single-branch",
                 f"https://github.com/{repo}.git", str(d)], WORK, 240)
        if r.returncode:
            res["serial_status"] = "clone_failed"
            return res
        names = git(["ls-tree", "-r", "-z", "--name-only", "HEAD"], d).stdout.split("\0")
        chosen = [n for _, n in sorted((select(n), n) for n in names if n and select(n))][:MAX_FILES]
        if not chosen:
            return res
        git(["sparse-checkout", "init", "--no-cone"], d)
        (d / ".git" / "info" / "sparse-checkout").write_text("\n".join(esc(p) for p in chosen) + "\n")
        r = git(["-c", "core.hooksPath=/dev/null", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=",
                 "-c", "filter.lfs.required=false", "checkout", "-q", "HEAD"], d, 600)
        if r.returncode:
            res["serial_status"] = "checkout_failed"
            return res
        for p in chosen:
            fp = d / p
            if PATH_EXCLUDE_RE.search(p):
                continue
            try:
                if fp.is_symlink() or not fp.is_file() or fp.stat().st_size > MAX_BYTES:
                    continue
                lines = fp.read_bytes().decode("utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            low = p.lower()
            tre = TEST_PY if low.endswith(".py") else TEST_JS if low.endswith(
                (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")) else None
            n_here = 0
            for i, line in enumerate(lines):
                if len(line) > 600 or COMMENT.match(line):
                    continue
                if tre and tre.search(line):
                    n_here += 1
                for mech, val in serial_for_line(p, line):
                    words = sorted({w.lower() for w in REASON_WORDS.findall(comment_text(lines, i))})
                    res["serial_signals"].append({"mechanism": mech, "file": p, "line": i + 1,
                                                  "text": line.strip()[:300], "value": val,
                                                  "reason_stated": bool(words), "reason_words": words})
            if n_here:
                res["test_files"] += 1
                res["test_count"] += n_here
    except subprocess.TimeoutExpired:
        res["serial_status"] = "timeout"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return res


def main() -> None:
    rows = [json.loads(l) for l in (HERE / "scan.jsonl").open()]
    todo = [r["repo"] for r in rows if r["lives_with_flaky"]]
    out = HERE / "serial_scan.jsonl"
    done = {json.loads(l)["repo"] for l in out.open()} if out.exists() else set()
    todo = [t for t in todo if t not in done]
    lock = threading.Lock()

    def job(repo):
        res = scan_repo(repo)
        with lock, out.open("a") as f:
            f.write(json.dumps(res) + "\n")
            print(repo, res["serial_status"], len(res["serial_signals"]), res["test_count"], flush=True)

    with ThreadPoolExecutor(10) as ex:
        list(ex.map(job, todo))


if __name__ == "__main__":
    main()
