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
import os
import time
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
    """JSON lines; a truncated last line or gzip member (a job killed mid-write) is dropped."""
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    out = []
    try:
        with op(p, "rt") as f:
            for x in f:
                if x.strip():
                    try:
                        out.append(json.loads(x))
                    except json.JSONDecodeError:
                        pass
    except (EOFError, OSError):
        pass
    return out


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def opts_of(cfg: dict) -> dict:
    return {"recording_packages": cfg.get("recording_packages") or [],
            "excluded_repos": cfg.get("excluded_repos") or []}


def candidates(only=None) -> dict:
    """Candidate records by idx; ``only``: keep just these idx (the full file is ~0.9 GB uncompressed: run 45820191350
    held two full copies and the runner was shut down)."""
    keep = None if only is None else set(only)
    return {c["idx"]: c for c in read_jsonl(RES / "candidates.jsonl.gz") if keep is None or c["idx"] in keep}


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".gz":
        with gzip.open(p, "at") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    else:
        with open(p, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")


def text_pass(client, row: dict, cand: dict, chunk, cfg: dict, out: Path, search: bool,
              searches: dict | None = None) -> None:
    """§3.2 for one member: repository searches (when ``search``) then the comment pass. ``searches``: repo ->
    latest search record (session route). An error leaves no record (pain at most unknown: texts-missing /
    comments-missing) and is logged in chunk_errors.jsonl; a later request resumes the member."""
    repo = (row.get("meta") or {}).get("full_name") or row["repo"]
    try:
        if search:
            src = pipeline.LiveSource(client)
            res = T.run_searches(src, repo, cfg)
            rec = {"repo": row["repo"], "query_repo": repo, "chunk": chunk, "route": "workflow", "at": now(), **res}
            _append(out / "texts_raw_wf" / f"{chunk}.jsonl.gz",
                    {"repo": row["repo"], "at": rec["at"], "cfg": cfg, "responses": src.responses})
            _append(out / "texts_search_wf.jsonl", rec)
        else:
            rec = (searches or {}).get(row["repo"].lower())
        if rec is None:
            return
        tx = T.member_texts(repo, cand.get("hits") or [], rec)
        used = row.get("core_requests") or 0
        src = pipeline.LiveSource(client, used=used)
        cr = T.comments_pass(src, repo, tx)
        at = now()
        _append(out / "comments_raw" / f"{chunk}.jsonl.gz",
                {"repo": row["repo"], "at": at, "used": used, "search_at": rec["at"], "responses": src.responses})
        _append(out / "comments.jsonl", {"repo": row["repo"], "chunk": chunk, "at": at, "used": used,
                                          "search_at": rec["at"], **cr})
    except ghapi.DeadlineReached:
        raise
    except Exception as e:
        _append(out / "chunk_errors.jsonl", {"repo": row["repo"], "chunk": chunk, "at": now(), "stage": "texts",
                                              "error": f"{type(e).__name__}: {str(e)[:200]}"})


def search_records() -> dict:
    out = {}
    for f in ("texts_search.jsonl", "texts_search_wf.jsonl"):
        for r in read_jsonl(RES / f):
            out[r["repo"].lower()] = r
    return out


def needs_texts(row: dict) -> bool:
    return row.get("cls") == "member" and not (row.get("recordings") or {}).get("yes")


def mark_done(name: str, rec: dict) -> None:
    """Request marker (results/<ADC_DONE or requests_done>/<name>): the workflow runs every request file without one
    (the S1 code workflow keeps its own markers in requests_done_code, so neither workflow commits the other's)."""
    p = RES / (os.environ.get("ADC_DONE") or "requests_done") / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, sort_keys=True) + "\n")


def run_chunk(req: dict, name: str | None = None) -> int:
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

    def over() -> bool:
        return (time.time() - t0) / 60 > maxm or bool(client.deadline and time.time() > client.deadline - 600)
    try:
        if req.get("comments") is not None:
            cands = candidates(r["idx"] for r in read_jsonl(RES / "rows.jsonl")
                               if str(r.get("chunk")) == str(req["comments"]))
            done = {r["repo"].lower() for r in read_jsonl(RES / "comments.jsonl")}
            searches = search_records()
            for row in read_jsonl(RES / "rows.jsonl"):
                if str(row.get("chunk")) != str(req["comments"]) or not needs_texts(row) \
                        or row["repo"].lower() in done:
                    continue
                if over():
                    stopped = "time limit"
                    break
                text_pass(client, row, cands[row["idx"]], req["comments"], cfg, RES, False, searches)
                n += 1
        else:
            if debug:
                cands = {i: {"idx": i, "repo": r, "html_url": f"https://github.com/{r}", "stratum": "debug",
                             "hits": []} for i, r in enumerate(req["repos"])}
                order = list(cands)
            else:
                order = req["candidates"]
                cands = candidates(order)
            rows = {r["idx"]: r for r in read_jsonl(out / "rows.jsonl")}
            wf_text = req.get("text_route") == "workflow"
            searched = {r["repo"].lower() for r in read_jsonl(out / "texts_search_wf.jsonl")}
            for idx in order:
                if over():
                    stopped = "time limit"
                    break
                if idx in rows:  # resume: a member whose text pass did not run
                    row = rows[idx]
                    if wf_text and needs_texts(row) and row["repo"].lower() not in searched:
                        text_pass(client, row, cands[idx], chunk, cfg, out, True)
                    continue
                src = pipeline.LiveSource(client)
                r0 = client.n_requests
                opts = {**opts_of(cfg), "no_exclude": debug}
                row = pipeline.run_candidate(src, cands[idx], opts)
                row["chunk"] = chunk
                row["requests"] = client.n_requests - r0
                row["read_at"] = now()
                per_cand.append(row["requests"])
                # raw first, then the row: a kill in between leaves a raw record without a row (ignored by
                # verify; the candidate is read again and its last raw record kept)
                _append(out / "raw" / f"{chunk}.jsonl.gz",
                        {"idx": idx, "repo": row["repo"], "opts": opts, "responses": src.responses})
                _append(out / "rows.jsonl", row)
                if wf_text and needs_texts(row):
                    text_pass(client, row, cands[idx], chunk, cfg, out, True)
                n += 1
                print(f"{idx} {row['repo']}: {row.get('cls')} {row.get('stage')} ({row['requests']} req)",
                      flush=True)
    except ghapi.DeadlineReached as e:
        stopped = f"deadline: {e}"
    rec = {"chunk": chunk, "items": n, "requests": client.n_requests, "search_requests": client.n_search,
           "requests_per_candidate": sorted(per_cand), "methods": sorted({x["method"] for x in log}),
           "rate_limit": client.limit, "remaining": client.remaining, "minutes": round((time.time() - t0) / 60, 1),
           "stopped": stopped, "at": now(), "request": name,
           # coordinator 17:53Z: rate-limited answers (429, or 403 rate limit) and seconds slept, by cause
           "n_429": getattr(client, "n_429", None),
           "sleep_s": {k: round(v, 1) for k, v in (getattr(client, "slept", None) or {}).items()}}
    _append(out / "chunks.jsonl", rec)
    if name and not stopped:
        mark_done(name, rec)
    print(f"chunk {chunk}: {n} items, {client.n_requests} requests, methods {rec['methods']}, stopped {stopped}, "
          f"remaining {client.remaining}")
    return 0


__all__ = ["run_chunk", "read_jsonl", "probe_config", "R"]
