#!/usr/bin/env python3
"""Agent-like sequences: walk the commits *inside* pull requests opened by coding agents.

Discovers pull requests with the GitHub search API (GITHUB_TOKEN), keeps those with at least
``--min-commits`` commits, and for each one walks base -> commit 1 -> ... -> head with walk.py's Walker
(fresh dependency records per pull request: the base commit runs every unit, then every push is decided
against the records).

    python agent_walk.py --spec specs/home-assistant.json --query "author:app/copilot-swe-agent" \
        --max-prs 8 --work /tmp/a --out results/agent/home-assistant-copilot.json.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import walk  # noqa: E402


def api(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "skip-study2"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # rate limits: back off
            walk.log(f"api retry {attempt}: {e}")
            time.sleep(20 * (attempt + 1))
    return None


def discover(repo, query, min_commits, max_commits, want, since):
    q = f"repo:{repo} is:pr {query} created:>={since}"
    out, page = [], 1
    while len(out) < want and page <= 5:
        d = api("https://api.github.com/search/issues?" + urllib.parse.urlencode(
            {"q": q, "sort": "created", "order": "desc", "per_page": 50, "page": page}))
        if not d or not d.get("items"):
            break
        for it in d["items"]:
            pr = api(f"https://api.github.com/repos/{repo}/pulls/{it['number']}")
            if not pr:
                continue
            n = pr.get("commits", 0)
            if min_commits <= n <= max_commits:
                out.append({"number": it["number"], "title": it["title"][:120], "commits": n,
                            "merged": bool(pr.get("merged_at")), "state": pr.get("state"),
                            "author": (pr.get("user") or {}).get("login"), "head_ref": pr["head"]["ref"],
                            "changed_files": pr.get("changed_files"), "created_at": pr.get("created_at"),
                            "base_ref": (pr.get("base") or {}).get("ref"),
                            "base_sha": (pr.get("base") or {}).get("sha")})
                if len(out) >= want:
                    break
            time.sleep(1)
        page += 1
        time.sleep(3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--max-prs", type=int, default=8)
    ap.add_argument("--min-commits", type=int, default=3)
    ap.add_argument("--max-commits", type=int, default=25)
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--sample", type=float, default=None, help="override the spec's unit sample")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget-min", type=float, default=330)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    repo = spec["url"].split("github.com/")[1].removesuffix(".git")
    if a.sample is not None and spec["lang"] != "go":
        spec["units"]["sample"] = a.sample
    spec["plain_baseline"] = False
    spec["verify"] = max(spec.get("verify", 0.1), 0.15)
    prs = discover(repo, a.query, a.min_commits, a.max_commits, a.max_prs, a.since)
    walk.log(f"{repo} {a.query}: {len(prs)} pull requests: {[p['number'] for p in prs]}")
    res = {"repo": repo, "query": a.query, "label": a.label, "spec": spec["name"], "prs": []}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    w = None
    for pr in prs:
        if time.time() - walk.T_START > a.budget_min * 60 * 0.85:
            res["note"] = "budget reached"
            break
        s = dict(spec, seq={"kind": "pr", "pr": pr["number"], "base_sha": pr.get("base_sha"),
                            "max": a.max_commits})
        nw = walk.Walker(s, a.work, Path(a.work) / "pr.json", 0, 1, a.budget_min, "agent")
        if w is not None:  # keep the installed environment and the Go cache
            nw._last_dep = w._last_dep
        nw.push = False
        w = nw
        try:
            w.walk()
            r = w.result
        except Exception as e:  # one broken pull request must not stop the others
            walk.log(f"PR {pr['number']} failed: {e}")
            r = {"error": str(e)[:500]}
        r.pop("spec", None)
        res["prs"].append({"pr": pr, "result": r})
        out.write_bytes(gzip.compress(json.dumps(res, separators=(",", ":")).encode(), 9))
        if os.environ.get("S2_COMMIT"):
            walk.commit_results([out], f"Skip study 2 (agent PRs): {repo} PR {pr['number']}")
    out.write_bytes(gzip.compress(json.dumps(res, separators=(",", ":")).encode(), 9))
    if os.environ.get("S2_COMMIT"):
        walk.commit_results([out], f"Skip study 2 (agent PRs): {repo} {a.label} done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
