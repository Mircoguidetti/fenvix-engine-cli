#!/usr/bin/env python3
"""Count 2 chunk runner (inside GitHub Actions, with the workflow's GITHUB_TOKEN; read-only on other repositories).

Usage: job.py --request requests/<n>.json

Request file: {"chunk": "<n>", "probe": bool, "max_prs": int|null, "max_minutes": int|null}. Resumes from results/checkpoint.json, walks
draw.jsonl.gz in order applying the quota (40 rateable per family), the 3-per-repository cap and the 1,500 hard cap,
reads each selected PR with pipeline.run_pr, and stops before the next PR when X-RateLimit-Remaining < 20% of the
limit, when ``max_prs`` PRs were read in this chunk, after ``max_minutes`` (so the
results are committed before the job's 340-minute timeout), or when the prepared draw ends. Writes
results/raw/<chunk>.jsonl.gz (every response, per PR), results/rows.jsonl, results/excluded_cap.jsonl,
results/checkpoint.json and results/chunks.jsonl.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pipeline  # noqa: E402
import rules as R  # noqa: E402

QUOTA = 40
HARD_CAP = 1500
CAP_PER_REPO = 3
FAMILIES = ["copilot", "devin", "jules", "codex", "claude_code"]


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def new_state() -> dict:
    return {"next": 0, "read": 0, "per_repo": {}, "rateable": {f: 0 for f in FAMILIES}, "stopped": None}


def next_action(state: dict, draw: list[dict], complete: bool):
    """Advance ``state`` past skipped positions; return ("read", row), ("cap", row) or ("stop", reason).

    Used by the job and by verify_count2.py (simulation of the selection from committed verdicts)."""
    while True:
        if all(state["rateable"][f] >= QUOTA for f in FAMILIES):
            return "stop", "quota met"
        if state["read"] >= HARD_CAP:
            return "stop", "hard cap 1500"
        i = state["next"]
        if i >= len(draw):
            return "stop", "draw exhausted" if complete else "prepared draw ended"
        d = draw[i]
        if d["excluded"] or state["rateable"][d["family"]] >= QUOTA:
            state["next"] += 1
            continue
        if state["per_repo"].get(d["repo"].lower(), 0) >= CAP_PER_REPO:
            state["next"] += 1
            return "cap", d
        return "read", d


def record_read(state: dict, d: dict, verdict: str) -> None:
    state["next"] += 1
    state["read"] += 1
    k = d["repo"].lower()
    state["per_repo"][k] = state["per_repo"].get(k, 0) + 1
    if verdict in R.RATEABLE:
        state["rateable"][d["family"]] += 1


def raw_records(res: Path | None = None) -> list[dict]:
    """Committed raw JSON per PR: results/raw/*.jsonl.gz, with the responses of results/supplement/*.jsonl.gz
    (reads added by a supplement chunk) merged into the same PR's record."""
    res = res or HERE / "results"
    raws = [x for p in sorted((res / "raw").glob("*.jsonl.gz")) for x in read_jsonl(p)]
    by_url = {x["url"]: x for x in raws}
    for p in sorted((res / "supplement").glob("*.jsonl.gz")):
        for x in read_jsonl(p):
            by_url[x["url"]]["responses"].update(x["responses"])
    return raws


class HybridSource:
    """Committed responses first; a path not recorded is read live and kept as a supplement response."""

    def __init__(self, recorded: dict, live):
        self.recorded, self.live, self.new = recorded, live, {}

    def has(self, path: str) -> bool:
        return path in self.recorded or path in self.new

    def get(self, path: str):
        if path in self.recorded:
            rec = self.recorded[path]
            return rec["status"], rec.get("data", rec.get("error"))
        self.live.responses = {}
        st, d = self.live.get(path)
        self.new[path] = self.live.responses[path]
        return st, d


def supplement(chunk: str) -> int:
    """Re-run every PR already read against its committed responses (the current pipeline code), reading live only
    the responses it lacks; rewrite rows.jsonl and checkpoint rateable counts from the new outcomes."""
    res = HERE / "results"
    (res / "supplement").mkdir(parents=True, exist_ok=True)
    src = pipeline.LiveSource(pipeline.token())
    t0 = time.time()
    raws = {x["url"]: x for x in raw_records(res)}
    rows = read_jsonl(res / "rows.jsonl")
    state = json.loads((res / "checkpoint.json").read_text())
    new_rows, changes = [], []
    for row in rows:
        raw = raws[row["url"]]
        h = HybridSource(raw["responses"], src)
        out = pipeline.run_pr(h, {"repo": raw["repo"], "number": raw["number"]}, probe=raw["probe"])
        if h.new:
            with gzip.open(res / "supplement" / f"{chunk}.jsonl.gz", "at") as f:
                f.write(json.dumps({"url": row["url"], "repo": raw["repo"], "number": raw["number"],
                                    "chunk": chunk, "responses": h.new}, sort_keys=True) + "\n")
        keep = {k: row[k] for k in ("idx", "url", "family", "repo", "number", "state", "month", "chunk", "probe")}
        nr = {**keep, **out}
        if nr["verdict"] != row["verdict"] or h.new:
            changes.append({"url": row["url"], "family": row["family"], "old": row["verdict"],
                            "new": nr["verdict"], "new_reads": sorted(h.new)})
        new_rows.append(nr)
    rate = Counter()
    for r in new_rows:
        if r["verdict"] in (R.ALREADY_RED, R.NEW_RED):
            rate[r["family"]] += 1
    state["rateable"] = {f: rate[f] for f in FAMILIES}
    with open(res / "rows.jsonl", "w") as f:
        for r in new_rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    with open(res / "supplement" / f"{chunk}_changes.jsonl", "w") as f:
        for c in changes:
            f.write(json.dumps(c, sort_keys=True) + "\n")
    (res / "checkpoint.json").write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    with open(res / "chunks.jsonl", "a") as f:
        f.write(json.dumps({"chunk": chunk, "supplement": True, "requests": src.n_requests,
                            "remaining": src.remaining, "limit": src.limit, "reset": src.reset,
                            "seconds": round(time.time() - t0), "changed": len(changes)}, sort_keys=True) + "\n")
    print(f"supplement {chunk}: {src.n_requests} requests, {len(changes)} PRs changed", flush=True)
    for c in changes:
        print(json.dumps(c), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    req = json.loads(Path(a.request).read_text())
    if req.get("supplement"):
        return supplement(str(req["chunk"]))
    chunk, probe, max_prs = str(req["chunk"]), bool(req.get("probe")), req.get("max_prs")
    max_minutes = req.get("max_minutes")
    res = HERE / "results"
    (res / "raw").mkdir(parents=True, exist_ok=True)
    ck = res / "checkpoint.json"
    state = json.loads(ck.read_text()) if ck.exists() else new_state()
    draw = read_jsonl(HERE / "draw.jsonl.gz")
    complete = json.loads((HERE / "draw_meta.json").read_text())["complete"]
    src = pipeline.LiveSource(pipeline.token())
    t0, n0, n_chunk, stop = time.time(), state["read"], 0, None
    raw_path = res / "raw" / f"{chunk}.jsonl.gz"
    while True:
        act, d = next_action(state, draw, complete)
        if act == "stop":
            stop = d
            break
        if act == "cap":
            with open(res / "excluded_cap.jsonl", "a") as f:
                f.write(json.dumps({"idx": d["idx"], "url": d["url"], "family": d["family"],
                                    "reason": "repository cap (3 per repository) reached"}, sort_keys=True) + "\n")
            ck.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
            continue
        if max_prs is not None and n_chunk >= max_prs:
            stop = f"chunk limit {max_prs} PRs"
            break
        if max_minutes is not None and time.time() - t0 > 60 * max_minutes:
            stop = f"chunk time limit {max_minutes} min"
            break
        if src.low():
            stop = f"rate limit: remaining {src.remaining} < 20% of {src.limit}"
            break
        src.responses = {}
        before = src.n_requests
        out = pipeline.run_pr(src, d, probe=probe)
        raw = {"idx": d["idx"], "url": d["url"], "repo": d["repo"], "number": d["number"], "probe": probe,
               "chunk": chunk, "requests": src.n_requests - before, "responses": src.responses}
        with gzip.open(raw_path, "at") as f:
            f.write(json.dumps(raw, sort_keys=True) + "\n")
        row = {"idx": d["idx"], "url": d["url"], "family": d["family"], "repo": d["repo"], "number": d["number"],
               "state": d["state"], "month": d["month"], "chunk": chunk, "probe": probe, **out}
        with open(res / "rows.jsonl", "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        record_read(state, d, out["verdict"])
        n_chunk += 1
        print(f"#{state['read']} idx={d['idx']} {d['family']} {d['url']} {out['verdict']} "
              f"req={raw['requests']} remaining={src.remaining}/{src.limit} rateable={state['rateable']}",
              flush=True)
        ck.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    state["stopped"] = stop
    ck.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    with open(res / "chunks.jsonl", "a") as f:
        f.write(json.dumps({"chunk": chunk, "probe": probe, "read_from": n0, "read_to": state["read"],
                            "requests": src.n_requests, "remaining": src.remaining, "limit": src.limit,
                            "reset": src.reset, "seconds": round(time.time() - t0), "stopped": stop},
                           sort_keys=True) + "\n")
    print("stopped:", stop, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
