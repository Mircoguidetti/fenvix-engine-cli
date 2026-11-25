"""§2-§4.3 chunk (in the workflow): read the listed candidates in order, append rows and raw responses.

Request: {"chunk": n, "candidates": [idx, ...], "max_minutes": 300, "issues_route": "session"|"workflow"}.
Candidates already in results/rows.jsonl are skipped (a re-run resumes). Stops before the next candidate after
max_minutes so the job commits before its timeout. Debug request: {"chunk": "debug-x", "debug": true, "repos": [...]}
(repositories named in the tests only; rows kept in results/debug/, never counted).
Writes results/rows.jsonl, results/raw/<chunk>.jsonl.gz (every response per candidate), results/chunks.jsonl.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import time
import traceback
from pathlib import Path

import ghapi
import pipeline

HERE = Path(__file__).resolve().parent
RES = HERE / "results"


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def opts_of(req: dict) -> dict:
    return {"issues_route": req.get("issues_route", "session"), "no_exclude": bool(req.get("no_exclude"))}


def run_chunk(req: dict) -> int:
    chunk = req["chunk"]
    maxm = float(req.get("max_minutes", 300))
    debug = bool(req.get("debug"))
    out = RES / "debug" if debug else RES
    if debug:
        cands = {i: {"idx": i, "repo": r, "html_url": f"https://github.com/{r}"} for i, r in enumerate(req["repos"])}
        order, done = list(cands), set()
    else:
        cands = {c["idx"]: c for c in read_jsonl(RES / "candidates.jsonl")}
        order = req["candidates"]
        done = {r["idx"] for r in read_jsonl(RES / "rows.jsonl")}
    (out / "raw").mkdir(parents=True, exist_ok=True)
    log: list = []
    client = ghapi.from_env()
    client.log = log
    t0 = time.time()
    n, stopped, per_cand, per_running = 0, None, [], []
    for idx in order:
        if idx in done:
            continue
        if (time.time() - t0) / 60 > maxm:
            stopped = f"time limit {maxm} min"
            break
        src = pipeline.LiveSource(client)
        r0 = client.n_requests
        try:
            row = pipeline.run_candidate(src, cands[idx], opts_of(req))
        except Exception as e:
            row = {"idx": idx, "repo": cands[idx]["repo"], "html_url": cands[idx].get("html_url"),
                   "cls": "uncertain", "mclass": "error", "error": f"{type(e).__name__}: {str(e)[:200]}",
                   "trace": traceback.format_exc()[-800:]}
        row["chunk"] = chunk
        row["requests"] = client.n_requests - r0
        row["read_at"] = now()
        per_cand.append(row["requests"])
        if row.get("cls") == "running":
            per_running.append(row["requests"])
        with gzip.open(out / "raw" / f"{chunk}.jsonl.gz", "at") as f:
            f.write(json.dumps({"idx": idx, "repo": row["repo"], "opts": opts_of(req), "responses": src.responses},
                               sort_keys=True) + "\n")
        with open(out / "rows.jsonl", "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        n += 1
        print(f"{idx} {row['repo']}: {row.get('cls')} {row.get('mclass')} ({row['requests']} req)", flush=True)
    methods = sorted({x["method"] for x in log})
    with open(out / "chunks.jsonl", "a") as f:
        f.write(json.dumps({"chunk": chunk, "candidates": n, "requests": client.n_requests,
                            "requests_per_candidate": round(sum(per_cand) / n, 2) if n else None,
                            "requests_per_running": round(sum(per_running) / len(per_running), 2)
                            if per_running else None,
                            "search_requests": client.n_search, "methods": methods,
                            "rate_limit": client.limit, "remaining": client.remaining,
                            "minutes": round((time.time() - t0) / 60, 1), "stopped": stopped, "at": now()},
                           sort_keys=True) + "\n")
    print(f"chunk {chunk}: {n} candidates, {client.n_requests} requests, methods {methods}, "
          f"remaining {client.remaining}")
    return 0
