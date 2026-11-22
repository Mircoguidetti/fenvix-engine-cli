#!/usr/bin/env python3
"""D22: date every skipped/quarantined test with a flaky reason, and check the state of a referenced issue.

Per repository with skipped_flaky_tests in raw_scan.jsonl:
  * blobless clone with history since SHALLOW_SINCE (`--filter=blob:none --shallow-since`), no checkout;
  * `git blame -w --porcelain -L n,n <commit> -- file` for each skip line -> committer date of the commit that last
    wrote that line (a LOWER bound on how long the test has been skipped: a later edit of the line resets it).
    A line attributed to the shallow boundary is older than the boundary -> bucket "over 12" when the boundary is
    itself more than 12 months old (otherwise recorded as a lower bound).
  * for each issue reference: `gh api -X GET search/issues` (public read) for its state.
Nothing is executed from the repository. Writes skip_dates.jsonl.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_repos import WORK, git  # noqa: E402

HERE = Path(__file__).resolve().parent
SHALLOW_SINCE = "2025-10-01"
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def bucket(months: float) -> str:
    return "under 1" if months < 1 else "1-6" if months < 6 else "6-12" if months < 12 else "over 12"


def date_repo(rec: dict) -> list[dict]:
    repo, commit = rec["repo"], rec["commit"]
    d = WORK / ("d22__" + repo.replace("/", "__"))
    shutil.rmtree(d, ignore_errors=True)
    out = []
    try:
        r = git(["clone", "-q", "--filter=blob:none", "--no-checkout", "--single-branch", f"--shallow-since={SHALLOW_SINCE}",
                 "-c", "core.hooksPath=/dev/null", f"https://github.com/{repo}.git", str(d)], WORK, 900)
        if r.returncode:
            # repositories with no commit since SHALLOW_SINCE: one commit is enough, everything is older than it
            r = git(["clone", "-q", "--filter=blob:none", "--no-checkout", "--single-branch", "--depth", "1",
                     f"https://github.com/{repo}.git", str(d)], WORK, 600)
        ok = r.returncode == 0 and git(["cat-file", "-e", commit], d).returncode == 0
        for s in rec["skipped_flaky_tests"]:
            e = {"repo": repo, "file": s["file"], "line": s["line"], "added_commit": None, "added_date": None,
                 "boundary": None, "age_months": None, "age_bucket": "UNKNOWN", "method": "git blame -w"}
            if ok:
                try:
                    b = git(["blame", "-w", "--porcelain", "-L", f"{s['line']},{s['line']}", commit, "--", s["file"]],
                            d, 600)
                except subprocess.TimeoutExpired:
                    b = None
                if b and b.returncode == 0 and b.stdout:
                    lines = b.stdout.splitlines()
                    sha = lines[0].split()[0]
                    ct = next(int(x.split()[1]) for x in lines if x.startswith("committer-time "))
                    dt = datetime.fromtimestamp(ct, timezone.utc)
                    months = (NOW - dt).days / 30.44
                    shallow = (d / ".git" / "shallow")
                    grafts = set(shallow.read_text().split()) if shallow.exists() else set()
                    # blame flags a ROOT commit as "boundary" too; only a shallow graft makes the date a lower bound
                    e.update(added_commit=sha, added_date=dt.date().isoformat(),
                             boundary=("boundary" in lines and sha in grafts), age_months=round(months, 1))
                    if e["boundary"]:
                        e["age_bucket"] = "over 12" if months >= 12 else "lower_bound " + bucket(months)
                    else:
                        e["age_bucket"] = bucket(months)
            out.append(e)
    except subprocess.TimeoutExpired:
        for s in rec["skipped_flaky_tests"][len(out):]:
            out.append({"repo": repo, "file": s["file"], "line": s["line"], "added_commit": None, "added_date": None,
                        "boundary": None, "age_months": None, "age_bucket": "UNKNOWN", "method": "timeout"})
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"{repo}: {len(out)} dated", flush=True)
    return out


_issue_cache: dict = {}


def issue_state(repo: str, number: int) -> str:
    key = (repo.lower(), number)
    if key in _issue_cache:
        return _issue_cache[key]
    state = "UNKNOWN"
    for kind in ("is:issue", "is:pull-request"):
        for attempt in range(4):
            r = subprocess.run(["gh", "api", "-X", "GET", "search/issues", "-f",
                                f"q=repo:{repo} {kind} {number} in:number", "-f", "per_page=5"],
                               capture_output=True, text=True)
            time.sleep(2.2)
            if r.returncode == 0:
                break
            if "422" in r.stderr:  # repository not searchable (renamed, private, gone)
                r = None
                break
            time.sleep(20 * (attempt + 1))
        if r is None or r.returncode:
            break
        hit = [i for i in json.loads(r.stdout)["items"] if i["number"] == number]
        if hit:
            state = ("pr_" if kind == "is:pull-request" else "") + hit[0]["state"]
            break
    else:
        state = "not_found"
    _issue_cache[key] = state
    return state


def main() -> None:
    recs = [json.loads(l) for l in (HERE / "raw_scan.jsonl").open()]
    keep = None
    if len(sys.argv) > 1:  # optional: {repo: [[file, line], ...]} restricting to skips kept by build_scan.py
        keep = {k: {tuple(x) for x in v} for k, v in json.load(open(sys.argv[1])).items()}
        for r in recs:
            r["skipped_flaky_tests"] = [s for s in r["skipped_flaky_tests"]
                                        if (s["file"], s["line"]) in keep.get(r["repo"], set())]
    recs = [r for r in recs if r["skipped_flaky_tests"] and r["commit"]]
    with ThreadPoolExecutor(6) as ex:
        dated = [e for lst in ex.map(date_repo, recs) for e in lst]
    by = {(e["repo"], e["file"], e["line"]): e for e in dated}
    with open(HERE / "skip_dates.jsonl", "w") as f:
        for r in recs:
            for s in r["skipped_flaky_tests"]:
                e = by[(r["repo"], s["file"], s["line"])]
                states = []
                for ref in s["refs"]:
                    if ref["kind"] == "tracker":
                        states.append({**ref, "state": "UNKNOWN"})
                    else:
                        rp = ref["repo"] or r["repo"]
                        states.append({**ref, "repo": rp, "state": issue_state(rp, ref["number"])})
                e["refs"] = states
                f.write(json.dumps(e) + "\n")
    print(f"dated {len(dated)} skips in {len(recs)} repositories")


if __name__ == "__main__":
    main()
