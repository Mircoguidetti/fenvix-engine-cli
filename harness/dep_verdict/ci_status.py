#!/usr/bin/env python3
"""Step 4 input: the projects' own CI verdict on every dependency-only commit and on its parent.

For each pair of ``commits.json`` it asks the GitHub API (inside GitHub Actions, with the workflow's token) for the
check runs and the combined commit status of P and C. A pair is a *known breakage* candidate when C has a failed
check run that P does not have (same check name) or when a later commit reverts C (``find_reverts`` in
``analyze.py``). For failed GitHub Actions jobs the job log is fetched when the API allows it and the pytest
``FAILED``/``ERROR`` lines are kept (the tests that broke).

    GITHUB_TOKEN=... python3 harness/dep_verdict/ci_status.py --commits harness/dep_verdict/commits.json --out ci.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
FAILED = re.compile(r"(?:FAILED|ERROR) ((?:[\w./-]+\.py)(?:::[^\s]+)?)")


def get(url, token, raw=False):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "dep-verdict"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                return data.decode(errors="replace") if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 3 and "rate limit" in (e.read().decode(errors="replace") or "").lower():
                time.sleep(60)
                continue
            return {"error": e.code}
        except Exception as e:  # network
            if attempt == 3:
                return {"error": str(e)[:200]}
            time.sleep(5)
    return {"error": "retries"}


def checks(owner, repo, sha, token):
    runs = []
    for page in (1, 2, 3):
        d = get(f"{API}/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100&page={page}", token)
        if not isinstance(d, dict) or "check_runs" not in d:
            return {"error": d.get("error") if isinstance(d, dict) else "?", "runs": runs}
        runs += [{"name": r["name"], "conclusion": r["conclusion"], "status": r["status"], "id": r["id"],
                  "app": (r.get("app") or {}).get("slug"), "url": r.get("html_url")} for r in d["check_runs"]]
        if len(d["check_runs"]) < 100:
            break
    st = get(f"{API}/repos/{owner}/{repo}/commits/{sha}/status", token)
    statuses = [{"context": s["context"], "state": s["state"]} for s in (st.get("statuses") or [])] \
        if isinstance(st, dict) else []
    return {"runs": runs, "statuses": statuses, "state": st.get("state") if isinstance(st, dict) else None}


def failed_names(c):
    out = {r["name"] for r in c.get("runs", []) if r["conclusion"] in ("failure", "timed_out")}
    out |= {s["context"] for s in c.get("statuses", []) if s["state"] in ("failure", "error")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--logs", type=int, default=6, help="max failed job logs fetched per pair")
    a = ap.parse_args(argv)
    token = os.environ["GITHUB_TOKEN"]
    allc = json.loads(Path(a.commits).read_text())
    res = {}
    for name, r in allc.items():
        owner, repo = r["url"].rstrip("/").split("/")[-2:]
        rows = []
        for pc in r["dep_commits"]:
            cp = checks(owner, repo, pc["parent"], token)
            cc = checks(owner, repo, pc["sha"], token)
            new_fail = sorted(failed_names(cc) - failed_names(cp))
            row = {"sha": pc["sha"], "parent": pc["parent"], "P_failed": sorted(failed_names(cp)),
                   "C_failed": sorted(failed_names(cc)), "new_failed": new_fail,
                   "P_n": len(cp.get("runs", [])), "C_n": len(cc.get("runs", [])),
                   "errors": [x.get("error") for x in (cp, cc) if x.get("error")]}
            tests = {}
            for run in [x for x in cc.get("runs", []) if x["name"] in new_fail and x["app"] == "github-actions"][:a.logs]:
                txt = get(f"{API}/repos/{owner}/{repo}/actions/jobs/{run['id']}/logs", token, raw=True)
                if isinstance(txt, dict):
                    tests[run["name"]] = {"error": txt.get("error")}
                    continue
                found = sorted({m.group(1) for m in FAILED.finditer(txt)})
                tests[run["name"]] = {"failed_tests": found[:300], "tail": txt[-1500:] if not found else ""}
            row["logs"] = tests
            rows.append(row)
            print(f"{name} {pc['sha'][:10]}: P fail {len(row['P_failed'])}/{row['P_n']}, C fail "
                  f"{len(row['C_failed'])}/{row['C_n']}, new {new_fail[:4]}", flush=True)
        res[name] = rows
        Path(a.out).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
