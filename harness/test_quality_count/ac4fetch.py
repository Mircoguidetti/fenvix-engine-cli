#!/usr/bin/env python3
"""AC4 evidence fetch (workflow route, GITHUB_TOKEN, GET only; CHANGES.md 20).

The work session cannot read other repositories through the REST API, so the workflow fetches, for every AC4 sample
item in results/ac4_items.jsonl: the repository's workflow files (and root build files that hold scripts), the latest
runs of each workflow that the pipeline recorded for the item or whose text names a mutation tool, the jobs (with
steps) of up to 2 of those runs from 2026, and the issue / pull request / commit texts named by the item. The session
then judges each item by hand from results/ac4_wf/fetch.jsonl.gz. Nothing here decides a verdict.
"""
from __future__ import annotations

import base64
import datetime as dt
import gzip
import json
import posixpath
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghapi  # noqa: E402

RES = HERE / "results"
OUT = RES / "ac4_wf"
MUT_RE = re.compile(r"stryker|mutmut|cosmic[-_ ]?ray|pitest|mutationCoverage|cargo[- ]mutants|infection|mutant|"
                    r"go-mutesting|gremlins|mull|muter|mutatest|mutation", re.I)
ROOT_FILES = ["package.json", "composer.json", "Makefile", "pyproject.toml", "tox.ini", "noxfile.py", "Rakefile",
              "justfile", "Taskfile.yml", "build.gradle", "build.gradle.kts", "pom.xml"]
MAX_TEXT = 200_000


def _text(c, repo, path):
    st, d, _ = c.get(f"repos/{repo}/contents/{urllib.parse.quote(path)}")
    if st != 200 or not isinstance(d, dict) or "content" not in d:
        return st, None
    try:
        return st, base64.b64decode(d["content"]).decode("utf-8", "replace")[:MAX_TEXT]
    except Exception:  # noqa: BLE001
        return st, None


def _runs(c, repo, wf_file, errors):
    name = posixpath.basename(wf_file)
    st, d, _ = c.get(f"repos/{repo}/actions/workflows/{urllib.parse.quote(name)}/runs?per_page=20")
    if st != 200 or not isinstance(d, dict):
        errors.append(f"runs {name}: HTTP {st}")
        return {"total_count": None, "runs": []}
    runs = [{k: r.get(k) for k in ("id", "event", "status", "conclusion", "created_at", "html_url", "head_branch")}
            for r in d.get("workflow_runs") or []]
    picked = [r for r in runs if (r["created_at"] or "") >= "2026-01-01" and r["status"] == "completed"][:2]
    for r in picked:
        st, j, _ = c.get(f"repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100&filter=all")
        if st != 200 or not isinstance(j, dict):
            errors.append(f"jobs {r['id']}: HTTP {st}")
            continue
        r["jobs"] = [{"name": x.get("name"), "status": x.get("status"), "conclusion": x.get("conclusion"),
                      "started_at": x.get("started_at"), "completed_at": x.get("completed_at"),
                      "html_url": x.get("html_url"),
                      "steps": [{k: s.get(k) for k in ("number", "name", "conclusion", "started_at", "completed_at")}
                                for s in x.get("steps") or []]} for x in j.get("jobs") or []]
    return {"total_count": d.get("total_count"), "runs": runs[:10], "picked": [r["id"] for r in picked],
            "runs_detail": picked}


def _url_text(c, repo, url, errors):
    m = re.search(r"/(issues|pull)/(\d+)", url or "")
    if m:
        st, d, _ = c.get(f"repos/{repo}/issues/{m.group(2)}")
        if st == 200 and isinstance(d, dict):
            return {"title": d.get("title"), "body": (d.get("body") or "")[:MAX_TEXT], "created_at": d.get("created_at"),
                    "pull": bool(d.get("pull_request"))}
        errors.append(f"issue {m.group(2)}: HTTP {st}")
        return None
    m = re.search(r"/commit/([0-9a-f]{7,40})", url or "")
    if m:
        st, d, _ = c.get(f"repos/{repo}/commits/{m.group(1)}")
        if st == 200 and isinstance(d, dict):
            return {"message": ((d.get("commit") or {}).get("message") or "")[:MAX_TEXT],
                    "date": ((d.get("commit") or {}).get("committer") or {}).get("date"),
                    "files": [f.get("filename") for f in d.get("files") or []][:100]}
        errors.append(f"commit {m.group(1)[:7]}: HTTP {st}")
    return None


def fetch_item(c, it: dict) -> dict:
    repo, errors = it["repo"], []
    rec = {"repo": repo, "sample": it["sample"], "key": it["key"], "files": {}, "runs": {}, "texts": {},
           "errors": errors, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    st, d, _ = c.get(f"repos/{repo}")
    rec["meta"] = {k: d.get(k) for k in ("default_branch", "archived", "fork", "pushed_at", "html_url")} \
        if st == 200 and isinstance(d, dict) else {"status": st}
    st, d, _ = c.get(f"repos/{repo}/contents/.github/workflows")
    wfs = sorted(x["path"] for x in d if isinstance(x, dict) and x.get("name", "").endswith((".yml", ".yaml"))) \
        if st == 200 and isinstance(d, list) else []
    if st != 200:
        errors.append(f"workflows dir: HTTP {st}")
    for p in wfs[:40]:
        _, t = _text(c, repo, p)
        rec["files"][p] = t
    for p in ROOT_FILES:
        s2, t = _text(c, repo, p)
        if t is not None and MUT_RE.search(t):
            rec["files"][p] = t
    want = {t["run_file"] for j in it.get("jobs") or [] for t in j.get("targets") or [] if t.get("run_file")}
    want |= {p for p, t in rec["files"].items() if p.startswith(".github/workflows/") and t and MUT_RE.search(t)}
    for p in sorted(want)[:8]:
        rec["runs"][p] = _runs(c, repo, p, errors)
    urls = [h.get("url") for h in it.get("confirmed_handreads") or []]
    if it.get("handread"):
        urls.append(it["handread"].get("url"))
    for u in dict.fromkeys(u for u in urls if u):
        rec["texts"][u] = _url_text(c, repo, u, errors)
    return rec


def main(req: dict) -> int:
    items = [json.loads(x) for x in (RES / "ac4_items.jsonl").read_text().splitlines() if x.strip()]
    c = ghapi.from_env()
    OUT.mkdir(parents=True, exist_ok=True)
    out = []
    for it in items:
        out.append(fetch_item(c, it))
        print(f"{it['sample']} {it['repo']}: files {len(out[-1]['files'])}, runs {len(out[-1]['runs'])}, "
              f"errors {len(out[-1]['errors'])}", flush=True)
    with gzip.open(OUT / "fetch.jsonl.gz", "wt") as f:
        for r in out:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    (OUT / "done.json").write_text(json.dumps({"items": len(out), "requests": c.n_requests,
                                               "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
                                   + "\n")
    print(f"ac4 fetch: {len(out)} items, {c.n_requests} requests")
    return 0
