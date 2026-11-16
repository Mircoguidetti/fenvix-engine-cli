#!/usr/bin/env python3
"""Pick merged pull requests that change source code (GitHub REST API, $GITHUB_TOKEN).

Per repository: merged PRs since --since, newest first, authored by humans,
changing at least one non-test ``.py`` file outside docs, at most --max-files
files. Refactors are flagged by label (``refactor`` in a label name) or by
title keyword. Output: ordered candidate list (refactors first, then
round-robin by repository, newest first).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import is_test_path  # noqa: E402

REPOS = ["attrs", "click", "flask", "jinja", "werkzeug", "marshmallow", "arrow", "structlog", "more-itertools",
         "sqlparse", "isort", "toolz", "boltons", "pygments", "packaging", "jsonschema", "rich"]
TITLE_REFACTOR = re.compile(r"\b(refactor\w*|clean ?up|cleanups?|simplif\w*|tidy|reorgani[sz]\w*|restructur\w*|"
                            r"moderni[sz]\w*|rewrite|move .* to)\b", re.I)


def api(path: str, params: dict | None = None):
    url = "https://api.github.com" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 502, 503) and attempt < 4:
                time.sleep(20 * (attempt + 1))
                continue
            raise


def source_files(files: list) -> list:
    out = []
    for f in files:
        p = f["filename"]
        if not p.endswith(".py") or is_test_path(p) or p.startswith(("docs/", "doc/", "benchmarks/", "bench/")):
            continue
        if f.get("status") == "removed":
            continue
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos-json", required=True, help="engine harness/repos.json (urls, install extras)")
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--per-repo", type=int, default=6)
    ap.add_argument("--max-files", type=int, default=40)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--total", type=int, default=80)
    ap.add_argument("--max-refactors", type=int, default=20)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    meta = {r["name"]: r for r in json.loads(Path(a.repos_json).read_text())["popular"]}
    per_repo: dict = {}
    scanned: dict = {}
    for name in REPOS:
        url = meta[name]["url"]
        owner_repo = url.split("github.com/")[1]
        prs = []
        for page in range(1, a.pages + 1):
            batch = api(f"/repos/{owner_repo}/pulls", {"state": "closed", "sort": "updated", "direction": "desc",
                                                      "per_page": 100, "page": page})
            prs += batch
            if len(batch) < 100:
                break
        merged = [p for p in prs if p.get("merged_at") and p["merged_at"] >= a.since
                  and (p.get("user") or {}).get("type") != "Bot"]
        merged.sort(key=lambda p: p["merged_at"], reverse=True)
        scanned[name] = {"closed_scanned": len(prs), "merged_human_since": len(merged)}
        accepted = []
        refactors = []
        for p in merged:
            labels = [l["name"] for l in p.get("labels", [])]
            lab_ref = any("refactor" in l.lower() for l in labels)
            tit_ref = bool(TITLE_REFACTOR.search(p.get("title", "")))
            want = len(accepted) < a.per_repo or ((lab_ref or tit_ref) and len(refactors) < 3)
            if not want:
                continue
            files = api(f"/repos/{owner_repo}/pulls/{p['number']}/files", {"per_page": 100})
            srcs = source_files(files)
            if not srcs or len(files) > a.max_files:
                continue
            full = api(f"/repos/{owner_repo}/pulls/{p['number']}")
            spec = {
                "repo": name, "url": url, "number": p["number"], "title": p["title"], "labels": labels,
                "merged_at": p["merged_at"], "merge_sha": p["merge_commit_sha"], "commits": full.get("commits", 1),
                "files": sorted({f["filename"] for f in files}), "source_files": srcs,
                "test_files": sorted(f["filename"] for f in files if is_test_path(f["filename"])),
                "additions": full.get("additions"), "deletions": full.get("deletions"),
                "refactor_label": lab_ref, "refactor_title": tit_ref,
                "install": meta[name].get("install", []), "pytest_args": meta[name].get("pytest_args", []),
            }
            if lab_ref or tit_ref:
                refactors.append(spec)
            if len(accepted) < a.per_repo:
                accepted.append(spec)
            elif spec not in accepted:
                accepted.append(spec)
        per_repo[name] = accepted
        print(name, scanned[name], "accepted", len(accepted), "refactor", len(refactors), flush=True)
    # Priority order: labelled refactors, title refactors, then round-robin newest first.
    allspecs = [s for n in REPOS for s in per_repo[n]]
    order = [s for s in allspecs if s["refactor_label"]]
    order += [s for s in allspecs if s["refactor_title"] and s not in order]
    order = order[: a.max_refactors]
    while len(order) < len(allspecs):
        before = len(order)
        for n in REPOS:
            lst = [s for s in per_repo[n] if s not in order]
            if lst:
                order.append(lst[0])
        if len(order) == before:
            break
    order = order[: a.total]
    for k, s in enumerate(order):
        s["priority"] = k
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"since": a.since, "scanned": scanned, "candidates": order}, indent=1))
    print(json.dumps([[s["priority"], s["repo"], s["number"], s["refactor_label"], s["refactor_title"]]
                      for s in order]))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"matrix={json.dumps(list(range(len(order))))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
