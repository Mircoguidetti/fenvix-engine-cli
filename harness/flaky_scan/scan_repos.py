#!/usr/bin/env python3
"""Scan each candidate repository for "living with flaky tests" signals (D21).

READ-ONLY: per repository a depth-1 blobless clone (`--filter=blob:none --no-checkout`), then a sparse checkout of
ONLY the test, config, dependency and CI files (selected from the tree listing), so only those blobs are downloaded.
Nothing from the repository is executed: files are read as bytes and matched with the regexes below.

    python3 harness/flaky_scan/scan_repos.py [--workers 8] [--limit N]

Reads candidates.jsonl, writes raw_scan.jsonl (one line per repository, appended; repos already present are skipped).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(tempfile.gettempdir()) / "flaky_scan_work"
MAX_FILES = 8000
MAX_BYTES = 1_000_000

EXCLUDE_DIR = re.compile(r"(^|/)(node_modules|vendor|third_party|third-party|site-packages|dist|build|\.venv|venv|"
                         r"fixtures|__fixtures__|testdata|test-data|__snapshots__)/")
CODE_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".py")
CFG_BASENAMES = {"package.json", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", "noxfile.py", "makefile",
                 "jenkinsfile", ".gitlab-ci.yml", ".mocharc.js", ".mocharc.cjs", ".mocharc.json", ".mocharc.yml",
                 ".mocharc.yaml", "cypress.json", "justfile", "taskfile.yml"}
CI_DIR = re.compile(r"^(\.github/workflows|\.circleci|\.buildkite|\.azure-pipelines|\.gitlab|ci|\.ci)/")
TESTISH = re.compile(r"(test|spec|e2e|conftest|cypress|playwright|vitest|jest)", re.I)


def select(path: str) -> int:
    """0 = skip; lower number = higher priority."""
    low = path.lower()
    if EXCLUDE_DIR.search(low) or low.endswith((".min.js", ".snap", ".d.ts")):
        return 0
    base = low.rsplit("/", 1)[-1]
    if CI_DIR.match(low) and base.endswith((".yml", ".yaml", ".sh")):
        return 1
    if base in CFG_BASENAMES or re.match(r"^(vite|vitest|jest|playwright|cypress|karma|mocha)[\w.-]*\.(config|workspace)", base):
        return 1
    if base.startswith("azure-pipelines") or re.match(r"^requirements.*\.(txt|in)$", base):
        return 1
    if ("quarantin" in base or "flaky" in base) and base.endswith((".txt", ".json", ".yml", ".yaml", ".toml", ".csv")):
        return 1
    if base.endswith(".sh") and TESTISH.search(low):
        return 2
    if base.endswith(CODE_EXT) and TESTISH.search(low):
        return 3
    return 0


# ---- signal regexes ---------------------------------------------------------------------------------------------
FLAKY_WORDS = re.compile(r"\bflak(?:y|iness|es?)\b|\bintermittent(?:ly)?\b|\bunstable\b|\bquarantin\w*|"
                         r"\bsometimes fail\w*|\brace condition|\braces?\b|\bracy\b", re.I)
ZERO = re.compile(r"^\s*0\s*[,;}]?\s*(//.*|#.*)?$")

SKIP_JS = re.compile(r"\b(?:it|test|describe|context|suite|bench)\.(?:skip|fixme|skipIf)\b|\bx(?:it|test|describe)\s*\(|"
                     r"\btest\.fixme\s*\(")
SKIP_PY = re.compile(r"@pytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\s*\(|@unittest\.skip\w*|"
                     r"\bself\.skipTest\s*\(|@(?:skip|skipIf|skipUnless)\s*\(")
ISSUE_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(issues|pull)/(\d+)")
ISSUE_HASH = re.compile(r"(?:^|[\s(\[])#(\d{2,7})\b|\bissues?\s*#?\s*(\d{2,7})\b", re.I)
JIRA = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b")


def mech_for_line(path: str, line: str) -> list[tuple[str, str]]:
    """Return [(mechanism, value_or_note)] for retry mechanisms on one line."""
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    out = []
    m = re.search(r"\bjest\.retryTimes\(\s*([^,)]+)", line)
    if m and not ZERO.match(m.group(1) + ","):
        out.append(("jest_retryTimes", m.group(1).strip()))
    if re.match(r"^vite(st)?[\w.-]*\.(config|workspace)", base):
        m = re.search(r"\bretry\s*:\s*([^\n]+)", line)
        if m and not ZERO.match(m.group(1)):
            out.append(("vitest_retry", m.group(1).strip()[:60]))
    if re.search(r"\b(?:it|test|describe)\b[^\n]*\{\s*retry\s*:\s*[1-9]", line):
        out.append(("vitest_retry", "per-test option"))
    if re.search(r"\bvitest\b[^\n]*--retry[= ]+[1-9]", line):
        out.append(("vitest_retry", "cli --retry"))
    if base.startswith("playwright") and re.match(r"^playwright[\w.-]*\.config", base):
        m = re.search(r"\bretries\s*:\s*([^\n]+)", line)
        if m and not ZERO.match(m.group(1)):
            v = m.group(1).strip()
            tmpl = bool(re.match(r"process\.env\.CI\s*\?\s*2\s*:\s*0", v))
            out.append(("playwright_retries", ("scaffold-default " if tmpl else "") + v[:60]))
    if re.search(r"\bplaywright\b[^\n]*--retries[= ]+[1-9]", line):
        out.append(("playwright_retries", "cli --retries"))
    if (base.startswith("cypress") and (".config" in base or base == "cypress.json")):
        m = re.search(r"[\"']?\bretries[\"']?\s*:\s*([^\n]+)", line)
        if m and not ZERO.match(m.group(1)) and not m.group(1).strip().startswith("{"):
            out.append(("cypress_retries", m.group(1).strip()[:60]))
        elif m and m.group(1).strip().startswith("{"):
            out.append(("cypress_retries", "object " + m.group(1).strip()[:50]))
    m = re.search(r"\bthis\.retries\(\s*(\d+)", line)
    if m and m.group(1) != "0":
        out.append(("mocha_retries", m.group(1)))
    if base.startswith(".mocharc"):
        m = re.search(r"[\"']?\bretries[\"']?\s*:\s*(\d+)", line)
        if m and m.group(1) != "0":
            out.append(("mocha_retries", m.group(1)))
    if re.search(r"\bmocha\b[^\n]*--retries[= ]+[1-9]", line):
        out.append(("mocha_retries", "cli --retries"))
    m = re.search(r"--reruns[= ]+([^\s\"',\]]+)", line) or re.search(r"\breruns\s*=\s*(\d+)", line)
    if m and m.group(1) != "0":
        out.append(("pytest_reruns", m.group(1)))
    if re.search(r"@pytest\.mark\.flaky\b", line):
        out.append(("pytest_mark_flaky", ""))
    if re.search(r"^\s*@flaky\b|^\s*from flaky import|^\s*import flaky\b", line):
        out.append(("flaky_plugin", ""))
    if re.search(r"\bpytest\b[^\n]*--retries[= ]+[1-9]|@pytest\.mark\.retry\b|^\s*@retry\(", line) and low.endswith(
            (".py", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh")):
        out.append(("pytest_retry", ""))
    if CI_DIR.match(low) or base in {".gitlab-ci.yml", "jenkinsfile", "makefile"} or base.startswith("azure-pipelines") \
            or (base.endswith(".sh") and "ci" in low):
        if re.search(r"nick-fields/retry@|wretry\.action|--last-failed\b|\bpytest\b[^\n]*\s--lf\b|--onlyFailures|"
                     r"rerun[-_ ]?fail|retry[-_ ]?fail|--rerun-failed", line, re.I):
            out.append(("ci_rerun", ""))
    return out


COMMENT = re.compile(r"^\s*(//|#|\*|/\*|<!--)")
TESTDEF = re.compile(r"^\s*(?:it|test|describe|context|suite|x?it|xtest|xdescribe)\b[\w.]*\s*\(|^\s*(?:async\s+)?def\s+test|"
                     r"^\s*class\s+Test|^\s*@pytest\.mark\.|^\s*@unittest\.")


def skip_window(lines: list[str], i: int, is_skip) -> str:
    """The skip line, the lines above it back to a blank line / another test or skip (max 5), and up to 2 lines
    below while they do not start another test or skip -- so a neighbour's reason is not borrowed."""
    out = [lines[i]]
    j = i - 1
    while j >= max(0, i - 5) and lines[j].strip() and not is_skip(lines[j]) and not (
            TESTDEF.search(lines[j]) and not COMMENT.match(lines[j])):
        out.insert(0, lines[j]); j -= 1
    for k in range(i + 1, min(len(lines), i + 3)):
        if not lines[k].strip() or is_skip(lines[k]) or TESTDEF.search(lines[k]):
            break
        out.append(lines[k])
    return "\n".join(out)


def scan_text(path: str, text: str, res: dict) -> None:
    lines = text.splitlines()
    low = path.lower()
    is_py = low.endswith(".py")
    is_code = low.endswith(CODE_EXT)
    for i, line in enumerate(lines):
        if len(line) > 600:
            continue
        if COMMENT.match(line):
            continue
        lo, hi = max(0, i - 5), min(len(lines), i + 6)
        window = "\n".join(lines[lo:hi])
        for mech, val in mech_for_line(path, line):
            w = FLAKY_WORDS.findall(window)
            res["signals"].append({"mechanism": mech, "file": path, "line": i + 1, "text": line.strip()[:300],
                                   "value": val, "stated": bool(w), "words": sorted({x.lower() for x in w})})
        skre = SKIP_PY if is_py else SKIP_JS
        if is_code and skre.search(line):
            window = skip_window(lines, i, lambda x: bool(skre.search(x)) and not COMMENT.match(x))
            w = FLAKY_WORDS.findall(window)
            if w:
                refs = []
                for m in ISSUE_URL.finditer(window):
                    refs.append({"kind": m.group(2), "repo": m.group(1), "number": int(m.group(3))})
                for m in ISSUE_HASH.finditer(window):
                    n = m.group(1) or m.group(2)
                    if n and not any(r.get("number") == int(n) for r in refs):
                        refs.append({"kind": "hash", "repo": None, "number": int(n)})
                for m in JIRA.finditer(window):
                    refs.append({"kind": "tracker", "key": m.group(0)})
                res["skipped_flaky_tests"].append({"file": path, "line": i + 1, "text": line.strip()[:300],
                                                   "words": sorted({x.lower() for x in w}), "refs": refs[:5]})
        if re.search(r"quarantin", line, re.I) and (CI_DIR.match(low) or low.rsplit("/", 1)[-1] in CFG_BASENAMES):
            res["signals"].append({"mechanism": "quarantine_ci", "file": path, "line": i + 1,
                                   "text": line.strip()[:300], "value": "", "stated": True, "words": ["quarantine"]})
    base = low.rsplit("/", 1)[-1]
    if ("quarantin" in base or re.match(r"^flaky", base)) and not is_code:
        res["signals"].append({"mechanism": "quarantine_list", "file": path, "line": 1,
                               "text": (lines[0].strip()[:300] if lines else ""), "value": f"{len(lines)} lines",
                               "stated": True, "words": ["quarantine" if "quarantin" in base else "flaky"]})


def git(args, cwd, timeout=180):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin",
                               "HOME": str(WORK), "GIT_LFS_SKIP_SMUDGE": "1",
                               **{k: v for k, v in __import__("os").environ.items()
                                  if k.lower() in ("https_proxy", "http_proxy", "no_proxy", "ssl_cert_file",
                                                   "git_ssl_cainfo", "requests_ca_bundle")}})


def esc(p: str) -> str:
    return "/" + re.sub(r"([*?\[\]\\!#])", r"\\\1", p)


def scan_repo(repo: str) -> dict:
    res = {"repo": repo, "commit": None, "scan_status": "ok", "files_selected": 0, "files_read": 0,
           "truncated": False, "signals": [], "skipped_flaky_tests": []}
    d = WORK / repo.replace("/", "__")
    shutil.rmtree(d, ignore_errors=True)
    try:
        r = git(["clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", "--single-branch",
                 "-c", "core.hooksPath=/dev/null", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=",
                 "-c", "filter.lfs.required=false",
                 f"https://github.com/{repo}.git", str(d)], WORK, 240)
        if r.returncode:
            res["scan_status"] = "clone_failed: " + r.stderr.strip()[-200:]
            return res
        res["commit"] = git(["rev-parse", "HEAD"], d).stdout.strip()
        names = git(["ls-tree", "-r", "-z", "--name-only", "HEAD"], d).stdout.split("\0")
        pri = sorted((select(n), n) for n in names if n and select(n))
        if len(pri) > MAX_FILES:
            res["truncated"] = True
            pri = pri[:MAX_FILES]
        chosen = [n for _, n in pri]
        res["files_selected"] = len(chosen)
        if not chosen:
            return res
        git(["sparse-checkout", "init", "--no-cone"], d)
        (d / ".git" / "info" / "sparse-checkout").write_text("\n".join(esc(p) for p in chosen) + "\n")
        r = git(["-c", "core.hooksPath=/dev/null", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=",
                 "-c", "filter.lfs.required=false", "checkout", "-q", "HEAD"], d, 600)
        if r.returncode:
            res["scan_status"] = "checkout_failed: " + r.stderr.strip()[-200:]
            return res
        for p in chosen:
            fp = d / p
            try:
                if fp.is_symlink() or not fp.is_file() or fp.stat().st_size > MAX_BYTES:
                    continue
                text = fp.read_bytes().decode("utf-8", errors="ignore")
            except OSError:
                continue
            res["files_read"] += 1
            scan_text(p, text, res)
    except subprocess.TimeoutExpired:
        res["scan_status"] = "timeout"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    WORK.mkdir(exist_ok=True)
    out = HERE / "raw_scan.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(l)["repo"] for l in out.open() if l.strip()}
    cands = [json.loads(l)["repo"] for l in (HERE / "candidates.jsonl").open()]
    if a.only:
        cands = a.only.split(",")
        done = set()
    todo = [c for c in cands if c not in done]
    if a.limit:
        todo = todo[:a.limit]
    lock = threading.Lock()
    n = [0]

    def job(repo):
        res = scan_repo(repo)
        with lock:
            with out.open("a") as f:
                f.write(json.dumps(res) + "\n")
            n[0] += 1
            print(f"[{n[0]}/{len(todo)}] {repo} {res['scan_status'][:40]} files={res['files_read']} "
                  f"sig={len(res['signals'])} skips={len(res['skipped_flaky_tests'])}", flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(job, todo))


if __name__ == "__main__":
    main()
