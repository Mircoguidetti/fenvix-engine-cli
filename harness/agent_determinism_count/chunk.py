"""Workflow chunks (GITHUB_TOKEN, GET only, read-only on every other repository).

Requests (harness/agent_determinism_count/requests/<n>.json):
  {"chunk": n, "candidates": [idx, ...], "max_minutes": 300}           §2-§3.1 rows of the listed candidates; with
      "text_route": "workflow" (the §0.2c probe chose the workflow for issues/commits search) the §3.2 searches and
      the comment pass of each member run here too.
  {"chunk": "<n>c", "comments": n}                                      comment pass for chunk n's members, after the
      session committed their repository searches (session route).
  {"chunk": "debug-<x>", "debug": true, "repos": [...]}                 pipeline check on repositories named in the
      tests only; rows kept in results/debug/, never counted.
Candidates already in results/rows.jsonl are skipped (a re-run resumes). The chunk stops before the next candidate
after max_minutes so the job commits before its timeout.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import time
import traceback
from pathlib import Path

import discover
import ghapi
import pipeline
import rules as R
import texts as T

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
probe_config = discover.probe_config


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def opts_of(cfg: dict) -> dict:
    return {"recording_packages": cfg.get("recording_packages") or [],
            "excluded_repos": cfg.get("excluded_repos") or []}


def candidates() -> dict:
    return {c["idx"]: c for c in read_jsonl(RES / "candidates.jsonl.gz")}


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".gz":
        with gzip.open(p, "at") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    else:
        with open(p, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")


def text_pass(client, row: dict, cand: dict, chunk, cfg: dict, out: Path, search: bool) -> None:
    """§3.2 for one member: repository searches (when ``search``) then the comment pass."""
    repo = (row.get("meta") or {}).get("full_name") or row["repo"]
    if search:
        src = pipeline.LiveSource(client)
        res = T.run_searches(src, repo, cfg)
        rec = {"repo": row["repo"], "query_repo": repo, "chunk": chunk, "route": "workflow", "at": now(), **res}
        _append(out / "texts_search_wf.jsonl", rec)
        _append(out / "texts_raw_wf" / f"{chunk}.jsonl.gz",
                {"repo": row["repo"], "at": rec["at"], "cfg": cfg, "responses": src.responses})
    else:
        rec = search_record(row["repo"])
    if rec is None:
        return
    tx = T.member_texts(repo, cand.get("hits") or [], rec)
    used = row.get("core_requests") or 0
    src = pipeline.LiveSource(client, used=used)
    cr = T.comments_pass(src, repo, tx)
    at = now()
    _append(out / "comments.jsonl", {"repo": row["repo"], "chunk": chunk, "at": at, "used": used, **cr})
    _append(out / "comments_raw" / f"{chunk}.jsonl.gz",
            {"repo": row["repo"], "at": at, "used": used, "responses": src.responses})


def search_record(repo: str):
    recs = [r for f in ("texts_search.jsonl", "texts_search_wf.jsonl") for r in read_jsonl(RES / f)
            if r["repo"].lower() == repo.lower()]
    return recs[-1] if recs else None


def needs_texts(row: dict) -> bool:
    return row.get("cls") == "member" and not (row.get("recordings") or {}).get("yes")


def run_chunk(req: dict) -> int:
    chunk = req["chunk"]
    maxm = float(req.get("max_minutes", 300))
    cfg = probe_config()
    debug = bool(req.get("debug"))
    out = RES / "debug" if debug else RES
    log: list = []
    client = ghapi.from_env()
    client.log = log
    t0 = time.time()
    n, stopped, per_cand = 0, None, []
    if req.get("comments") is not None:
        cands = candidates()
        done = {r["repo"].lower() for r in read_jsonl(RES / "comments.jsonl")}
        for row in read_jsonl(RES / "rows.jsonl"):
            if str(row.get("chunk")) != str(req["comments"]) or not needs_texts(row) or row["repo"].lower() in done:
                continue
            if (time.time() - t0) / 60 > maxm:
                stopped = f"time limit {maxm} min"
                break
            text_pass(client, row, cands[row["idx"]], req["comments"], cfg, RES, search=False)
            n += 1
    else:
        if debug:
            cands = {i: {"idx": i, "repo": r, "html_url": f"https://github.com/{r}", "stratum": "debug", "hits": []}
                     for i, r in enumerate(req["repos"])}
            order, done = list(cands), set()
        else:
            cands = candidates()
            order = req["candidates"]
            done = {r["idx"] for r in read_jsonl(RES / "rows.jsonl")}
        wf_text = req.get("text_route") == "workflow"
        for idx in order:
            if idx in done:
                continue
            if (time.time() - t0) / 60 > maxm:
                stopped = f"time limit {maxm} min"
                break
            src = pipeline.LiveSource(client)
            r0 = client.n_requests
            opts = {**opts_of(cfg), "no_exclude": debug}
            try:
                row = pipeline.run_candidate(src, cands[idx], opts)
            except Exception as e:
                row = {"idx": idx, "repo": cands[idx]["repo"], "html_url": cands[idx].get("html_url"),
                       "stratum": cands[idx].get("stratum"), "cls": "uncertain", "stage": "error",
                       "error": f"{type(e).__name__}: {str(e)[:200]}", "trace": traceback.format_exc()[-800:],
                       "core_requests": src.core}
            row["chunk"] = chunk
            row["requests"] = client.n_requests - r0
            row["read_at"] = now()
            per_cand.append(row["requests"])
            _append(out / "raw" / f"{chunk}.jsonl.gz",
                    {"idx": idx, "repo": row["repo"], "opts": opts, "responses": src.responses})
            _append(out / "rows.jsonl", row)
            if wf_text and needs_texts(row):
                text_pass(client, row, cands[idx], chunk, cfg, out, search=True)
            n += 1
            print(f"{idx} {row['repo']}: {row.get('cls')} {row.get('stage')} ({row['requests']} req)", flush=True)
    _append(out / "chunks.jsonl", {
        "chunk": chunk, "items": n, "requests": client.n_requests, "search_requests": client.n_search,
        "requests_per_candidate": sorted(per_cand), "methods": sorted({x["method"] for x in log}),
        "rate_limit": client.limit, "remaining": client.remaining, "minutes": round((time.time() - t0) / 60, 1),
        "stopped": stopped, "at": now()})
    print(f"chunk {chunk}: {n} items, {client.n_requests} requests, methods {sorted({x['method'] for x in log})}, "
          f"remaining {client.remaining}")
    return 0


__all__ = ["run_chunk", "read_jsonl", "probe_config", "R"]
