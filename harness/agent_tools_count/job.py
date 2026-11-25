#!/usr/bin/env python3
"""Agent tools count chunk runner (inside GitHub Actions with the workflow's GITHUB_TOKEN; GET only, read-only on
every other repository).

Usage: job.py --request requests/<n>.json

Request file: {"chunk": n, "part": "probe"|"A"|"B", "items": [...], "max_minutes": 320}. ``items`` are frame
positions (part A, ``frame.jsonl``) or repositories (part B, ``b_order.json``), read in the given order; an item
already in the rows is skipped. The job stops before the next item after ``max_minutes``, at the end of Count A's
14 hours or of the 24-hour budget (both from ``budget_start``, the time of the first data request, kept in
``results/checkpoint.json``), or when the items end. Writes results/raw/<part>_<chunk>.jsonl.gz (every response,
per item), results/a_rows.jsonl or results/b_rows.jsonl, results/checkpoint.json and results/chunks.jsonl.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pipeline  # noqa: E402
import rules as R  # noqa: E402
from common import seeded_order  # noqa: E402

LAUNCH = "2026-11-25"
RACE_FROM = (dt.date.fromisoformat(LAUNCH) - dt.timedelta(days=90)).isoformat() + "T00:00:00Z"
A_HOURS = 14
BUDGET_HOURS = 24
PROBE_PRS = ["https://github.com/lxndrp/lzug/pull/254", "https://github.com/colombo-labs/movicol-frontend/pull/23",
             "https://github.com/takaraflow/drive-collector-js/pull/383",
             "https://github.com/pawelekbyra/polutek-pl/pull/1281", "https://github.com/paiml/aprender/pull/1339"]
PROBE_REPO = "lxndrp/lzug"


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def append_jsonl(p: Path, row: dict, gz: bool = False) -> None:
    op = gzip.open if gz else open
    with op(p, "at") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def frame() -> list[dict]:
    return read_jsonl(HERE / "frame.jsonl")


def b_order(fr: list[dict] | None = None) -> list[str]:
    """§2: the frame's distinct repositories in seeded_order({"all": [{"url": r} ...]}, seed=2)."""
    repos = sorted({r["repo"] for r in (fr or frame())})
    return [x["url"] for x in seeded_order({"all": [{"url": r} for r in repos]}, seed=2)]


def raw_records(part: str, res: Path | None = None) -> list[dict]:
    res = res or HERE / "results"
    return [x for p in sorted((res / "raw").glob(f"{part}_*.jsonl.gz")) for x in read_jsonl(p)]


# ---------------------------------------------------------------- probe (§0)

def probe(res: Path) -> int:
    """Raw (untrimmed) JSON of every endpoint the scan uses, on one Count 2 pull request per family and one
    repository; records the pull request and commit author logins per family."""
    out_dir = res / "probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    src = pipeline.LiveSource(pipeline.token(), raw=True)
    fr = {r["url"]: r for r in frame()}
    table, logins = [], {}

    def get(path, label, fam):
        st, d = src.get(path)
        table.append({"family": fam, "endpoint": label, "path": path, "status": st,
                      "n": len(d) if isinstance(d, list) else None})
        return st, d

    for url in PROBE_PRS:
        r = fr[url]
        repo, n, fam = r["repo"], r["number"], r["family"]
        st, pull = get(f"repos/{repo}/pulls/{n}", "pulls/{n}", fam)
        st, commits = get(f"repos/{repo}/pulls/{n}/commits?per_page=100", "pulls/{n}/commits", fam)
        get(f"repos/{repo}/pulls/{n}/files?per_page=20", "pulls/{n}/files", fam)
        get(f"repos/{repo}/pulls/{n}/reviews?per_page=100", "pulls/{n}/reviews", fam)
        get(f"repos/{repo}/issues/{n}/timeline?per_page=100&page=1", "issues/{n}/timeline", fam)
        sha = pull["head"]["sha"]
        st, crs = get(f"repos/{repo}/commits/{sha}/check-runs?per_page=100&page=1", "commits/{sha}/check-runs", fam)
        get(f"repos/{repo}/commits/{sha}/status", "commits/{sha}/status", fam)
        st, runs = get(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100", "actions/runs?head_sha=", fam)
        if st == 200 and runs["workflow_runs"]:
            rid = runs["workflow_runs"][0]["id"]
            get(f"repos/{repo}/actions/runs/{rid}/jobs?per_page=100", "actions/runs/{id}/jobs", fam)
            get(f"repos/{repo}/actions/runs/{rid}", "actions/runs/{id}", fam)
        if st == 200 and crs.get("check_runs"):
            failed = [c for c in crs["check_runs"] if c.get("conclusion") in R.FAILED_RUN] or crs["check_runs"]
            cid = failed[0]["id"]
            get(f"repos/{repo}/check-runs/{cid}", "check-runs/{id}", fam)
            get(f"repos/{repo}/check-runs/{cid}/annotations?per_page=100", "check-runs/{id}/annotations", fam)
        get(f"repos/{repo}/commits/{sha}", "commits/{sha}", fam)
        st, tree = get(f"repos/{repo}/git/trees/{sha}?recursive=1", "git/trees/{sha}?recursive=1", fam)
        if st == 200:
            blob = next((t["path"] for t in tree["tree"] if t["type"] == "blob"), None)
            tree["tree"] = tree["tree"][:200]  # stored excerpt (the full tree is not needed for the probe)
            if blob:
                get(f"repos/{repo}/contents/{blob}?ref={sha}", "contents", fam)
        logins[fam] = {"pr_author": (pull.get("user") or {}).get("login"),
                       "commit_authors": sorted({(c.get("author") or {}).get("login") or "(none)"
                                                 for c in commits or []}),
                       "commit_committers": sorted({(c.get("committer") or {}).get("login") or "(none)"
                                                    for c in commits or []}),
                       "claude_trailer_commits": sum(1 for c in commits or []
                                                     if R.CLAUDE_COMMIT_RE.search(c["commit"]["message"] or "")),
                       "head_ref": pull["head"]["ref"]}
    get(f"repos/{PROBE_REPO}/issues?state=closed&since={RACE_FROM}&sort=updated&direction=desc&per_page=100",
        "repos/{r}/issues?state=closed&since=", "repo")
    get(f"repos/{PROBE_REPO}/pulls?state=all&sort=created&direction=desc&per_page=100", "repos/{r}/pulls", "repo")
    (out_dir / "raw.json").write_text(json.dumps(src.responses, indent=1, sort_keys=True))
    (out_dir / "endpoints.json").write_text(json.dumps(table, indent=1))
    (out_dir / "logins.json").write_text(json.dumps(logins, indent=1, sort_keys=True))
    append_jsonl(res / "chunks.jsonl", {"chunk": "probe", "part": "probe", "requests": src.n_requests,
                                        "remaining": src.remaining, "limit": src.limit})
    for t in table:
        print(t["family"], t["endpoint"], t["status"], flush=True)
    print(json.dumps(logins, indent=1), flush=True)
    return 0


# ---------------------------------------------------------------- data chunks

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    req = json.loads(Path(a.request).read_text())
    res = HERE / "results"
    (res / "raw").mkdir(parents=True, exist_ok=True)
    if req["part"] == "probe":
        return probe(res)
    chunk, part, max_minutes = str(req["chunk"]), req["part"], req.get("max_minutes", 320)
    ck_path = res / "checkpoint.json"
    ck = json.loads(ck_path.read_text()) if ck_path.exists() else {"budget_start": None}
    if not ck.get("budget_start"):
        ck["budget_start"] = R.iso(dt.datetime.now(dt.timezone.utc))
        ck_path.write_text(json.dumps(ck, indent=1, sort_keys=True) + "\n")
    start = R.ts(ck["budget_start"])
    a_end = start + dt.timedelta(hours=A_HOURS)
    b_end = start + dt.timedelta(hours=BUDGET_HOURS)
    src = pipeline.LiveSource(pipeline.token())
    t0 = time.time()
    raw_path = res / "raw" / f"{part.lower()}_{chunk}.jsonl.gz"
    rows_path = res / ("a_rows.jsonl" if part == "A" else "b_rows.jsonl")
    done = {r["item"] for r in read_jsonl(rows_path)}
    fr = frame()
    n_done, stop, first, last = 0, "items ended", None, None

    def limit():
        now = dt.datetime.now(dt.timezone.utc)
        if part == "A" and now >= a_end:
            return "budget", f"Count A budget ({A_HOURS} h) reached"
        if now >= b_end:
            return "budget", f"budget ({BUDGET_HOURS} h) reached"
        if time.time() - t0 > 60 * max_minutes:
            return "chunk", f"chunk time limit {max_minutes} min"
        return None, None

    for item in req["items"]:
        if item in done:
            continue
        kind, why = limit()
        if kind:
            stop = why
            break
        src.responses = {}
        before = src.n_requests
        t_item = time.time()
        if part == "A":
            pr = fr[item]
            out = pipeline.count_a(src, pr)
            row = {"item": item, "url": pr["url"], "repo": pr["repo"], "number": pr["number"],
                   "family": pr["family"], "c2_verdict": pr["c2_verdict"], "chunk": chunk, **out}
            label = f"{pr['family']} {pr['url']} {out['result']}"
        else:
            def should_stop():
                k, _ = limit()
                return k
            try:
                out = pipeline.count_b(src, item, RACE_FROM, should_stop)
            except pipeline.Interrupted:
                stop = "chunk time limit inside a repository (re-read next chunk)"
                break
            row = {"item": item, "repo": item, "chunk": chunk, **out}
            label = f"{item} {out['status']} issues={out.get('n_issues_read')} " \
                    f"addressed={len(out.get('issues') or [])}"
        nreq = src.n_requests - before
        row["requests"] = nreq
        row["seconds"] = round(time.time() - t_item, 1)
        append_jsonl(raw_path, {"item": item, "part": part, "chunk": chunk, "requests": nreq,
                                "responses": src.responses}, gz=True)
        append_jsonl(rows_path, row)
        done.add(item)
        n_done += 1
        first = item if first is None else first
        last = item
        print(f"[{part}{chunk}] #{n_done} {label} req={nreq} remaining={src.remaining}/{src.limit}", flush=True)
    else:
        stop = "items ended"
    append_jsonl(res / "chunks.jsonl", {
        "chunk": chunk, "part": part, "items_done": n_done, "first": first, "last": last, "requests": src.n_requests,
        "remaining": src.remaining, "limit": src.limit, "reset": src.reset, "slept": round(src.slept),
        "seconds": round(time.time() - t0), "stopped": stop, "started": R.iso(dt.datetime.fromtimestamp(t0,
                                                                                                         dt.timezone.utc))})
    ck_path.write_text(json.dumps(ck, indent=1, sort_keys=True) + "\n")
    print("stopped:", stop, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
