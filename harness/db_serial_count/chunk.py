"""§2-§3 chunk (in the workflow): read the listed candidates in order, append rows and raw responses.

Request: {"chunk": n, "candidates": [idx, ...], "max_minutes": 300}. Candidates already in results/rows.jsonl are
skipped (a re-run resumes). Stops before the next candidate after max_minutes so the job commits before its timeout.
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


def run_chunk(req: dict) -> int:
    chunk = req["chunk"]
    maxm = float(req.get("max_minutes", 300))
    out = RES / "debug" if req.get("debug") else RES
    if req.get("debug"):
        # debug run: candidates given as repository names, rows kept apart from the count
        cands = {i: {"idx": i, "repo": r, "html_url": f"https://github.com/{r}"} for i, r in enumerate(req["repos"])}
        req = {**req, "candidates": list(cands)}
        done = set()
    else:
        cands = {c["idx"]: c for c in read_jsonl(RES / "candidates.jsonl")}
        done = {r["idx"] for r in read_jsonl(RES / "rows.jsonl")}
    (out / "raw").mkdir(parents=True, exist_ok=True)
    client = ghapi.from_env()
    t0 = time.time()
    n, stopped = 0, None
    per_cand = []
    for idx in req["candidates"]:
        if idx in done:
            continue
        if (time.time() - t0) / 60 > maxm:
            stopped = f"time limit {maxm} min"
            break
        src = pipeline.LiveSource(client)
        r0 = client.n_requests
        try:
            row = pipeline.run_candidate(src, cands[idx])
        except Exception as e:
            row = {"idx": idx, "repo": cands[idx]["repo"], "html_url": cands[idx]["html_url"], "cls": "uncertain",
                   "stage": "error", "error": f"{type(e).__name__}: {str(e)[:200]}",
                   "trace": traceback.format_exc()[-800:]}
        row["chunk"] = chunk
        row["requests"] = client.n_requests - r0
        row["read_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        per_cand.append(row["requests"])
        with gzip.open(out / "raw" / f"{chunk}.jsonl.gz", "at") as f:
            f.write(json.dumps({"idx": idx, "repo": row["repo"], "responses": src.responses}, sort_keys=True) + "\n")
        with open(out / "rows.jsonl", "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        n += 1
        print(f"{idx} {row['repo']}: {row['cls']} {row.get('stage')} ({row['requests']} req)", flush=True)
    with open(out / "chunks.jsonl", "a") as f:
        f.write(json.dumps({"chunk": chunk, "candidates": n, "requests": client.n_requests,
                            "requests_per_candidate": round(client.n_requests / n, 2) if n else None,
                            "rate_limit": client.limit, "remaining": client.remaining,
                            "minutes": round((time.time() - t0) / 60, 1), "stopped": stopped,
                            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
                           sort_keys=True) + "\n")
    print(f"chunk {chunk}: {n} candidates, {client.n_requests} requests, limit {client.limit}")
    return 0
