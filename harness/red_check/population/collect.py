#!/usr/bin/env python3
"""C5.3 steps 2.3-2.6 and 2.8, inside the workflow with GITHUB_TOKEN (PREREG.md).

Request files:
  {"kind": "collect", "chunk": "<name>", "max_minutes": int}   resume from results/checkpoint.json
  {"kind": "oracle", "chunk": "<name>"}                         2.8 for selected.json's PRs

A collect chunk walks the repositories in 2.4's order from results/pool.jsonl.gz, fetching repository metadata
lazily, and reads PRs until a final stop (30 repositories read, 10,000 requests, order exhausted) or a chunk stop
(X-RateLimit-Remaining < 20% of the limit, max_minutes). Writes results/prs.jsonl.gz (appended),
results/excerpts/<job_id>.txt.gz, results/checkpoint.json, results/chunks.jsonl, and full logs to logs/ (artifact).
"""
from __future__ import annotations

import base64
import datetime as dt
import gzip
import hashlib
import json
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghrest  # noqa: E402
import rules as R  # noqa: E402

MAX_REPOS = 30
MAX_REQUESTS = 10_000
MAX_PRS_PER_REPO = 40
MAX_LOGS_PER_PR = 3


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


# ---------------------------------------------------------------- one PR


def _yaml(src, repo: str, path: str, ref: str):
    """(status, parsed workflow | None, reason | None)."""
    import yaml
    st, d = src.get_json(f"repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(ref, safe='')}")
    if st != 200:
        return st, None, ("job_absent_at_base" if st == 404 else "workflow_unreadable")
    try:
        text = base64.b64decode(d.get("content") or "").decode("utf-8", errors="replace")
        wf = yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        return st, None, "workflow_unparseable"
    if not isinstance(wf, dict) or not isinstance(wf.get("jobs"), dict):
        return st, None, "workflow_unparseable"
    return st, wf, None


def read_pr(src, pr: dict, store_log=None, version: int = 1) -> dict:
    """Run 2.4 steps 1-6 for one pool PR. ``store_log(job_id, body, text, idx, candidate)`` keeps the log (excerpt,
    artifact)."""
    repo, n = pr["repo"], pr["number"]
    out = {k: pr.get(k) for k in ("url", "repo", "number", "family", "families", "created_at")}
    st, p = src.get_json(f"repos/{repo}/pulls/{n}")
    if st != 200:
        return {**out, "verdict": "pr_unreadable", "reason": f"pulls HTTP {st}"}
    out.update(head_sha=p["head"]["sha"], base_sha=p["base"]["sha"], base_ref=p["base"]["ref"],
               pr_created_at=p.get("created_at"), state=p.get("state"), merged=bool(p.get("merged_at")))
    st, runs = src.get_json(f"repos/{repo}/actions/runs?head_sha={out['head_sha']}&per_page=100")
    if st != 200:
        return {**out, "verdict": "runs_unreadable", "reason": f"runs HTTP {st}"}
    wruns = runs.get("workflow_runs", [])
    failed_runs = [r for r in wruns if r.get("conclusion") in R.FAILED]
    out["n_runs"], out["failed_runs"] = len(wruns), [
        {"id": r["id"], "path": r.get("path"), "name": r.get("name"), "conclusion": r.get("conclusion"),
         "event": r.get("event")} for r in failed_runs]
    paths = {r["id"]: r.get("path") for r in failed_runs}
    jobs = []
    for r in failed_runs:
        st, js = src.get_json(f"repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100")
        if st != 200:
            out.setdefault("jobs_errors", []).append({"run": r["id"], "status": st})
            continue
        jobs += js.get("jobs", [])
    cands = sorted((j for j in jobs if R.candidate(j)), key=lambda j: j["id"])
    out["n_failed_jobs"] = sum(j.get("conclusion") in R.FAILED for j in jobs)
    out["candidates"] = []
    if not cands:
        return {**out, "verdict": "no_candidate_job", "reason": None}
    for j in cands[:MAX_LOGS_PER_PR]:
        lg = src.get_log(repo, j["id"])
        body = lg["body"] or b""
        c = {"id": j["id"], "name": j.get("name"), "run_id": j.get("run_id"), "labels": j.get("labels"),
             "conclusion": j.get("conclusion"), "api_status": lg["api_status"], "blob_status": lg["blob_status"],
             "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest() if body else None, "runner": None}
        if lg["blob_status"] == 200 and body:
            text = body.decode("utf-8", errors="replace")
            runner, idx = R.detect_runner(text, version)
            c["runner"] = runner
            c["summary_line"] = R.clean_lines(text, version)[idx] if idx is not None else None
            if store_log:
                store_log(j["id"], body, text, idx, c)
        out["candidates"].append(c)
    out["n_candidates"] = len(cands)
    readable = [c for c in out["candidates"] if c["runner"] is not None]
    single = [c for c in readable if c["runner"] not in (R.NO_RUNNER, R.AMBIGUOUS)]
    if not readable:
        return {**out, "verdict": "no_readable_log", "reason": None}
    if not single:
        return {**out, "verdict": "no_single_runner", "reason": None}
    q = min(single, key=lambda c: c["id"])
    out.update(job_id=q["id"], job_name=q["name"], runner=q["runner"], run_id=q["run_id"])
    path = (paths.get(q["run_id"]) or "").split("@", 1)[0]
    out["workflow_path"] = path
    st, cmp_ = src.get_json(f"repos/{repo}/compare/{out['base_sha']}...{out['head_sha']}")
    if st != 200:
        return {**out, "verdict": "compare_unreadable", "reason": f"compare HTTP {st}"}
    b0 = (cmp_.get("merge_base_commit") or {}).get("sha")
    out["B0"] = b0
    if not b0:
        return {**out, "verdict": "compare_unreadable", "reason": "no merge_base_commit"}
    _st, head_wf, _r = _yaml(src, repo, path, out["head_sha"])
    st, wf, reason = _yaml(src, repo, path, b0)
    if reason:
        why = "YAML is not a mapping with a jobs mapping" if reason == "workflow_unparseable" else f"HTTP {st}"
        return {**out, "verdict": reason, "reason": f"workflow at B0: {why}"}
    found, key = R.match_job(wf, q["name"] or "")
    if found != R.FOUND:
        return {**out, "verdict": found, "reason": key}
    job = wf["jobs"][key]
    out.update(job_key=key, features=R.features(job))
    if head_wf is not None:
        hf, hk = R.match_job(head_wf, q["name"] or "")
        out["differs_at_head"] = None if hf != R.FOUND else head_wf["jobs"][hk] != job
    else:
        out["differs_at_head"] = None
    return {**out, "verdict": "qualifying", "reason": None}


# ---------------------------------------------------------------- chunk


class Store:
    def __init__(self, res: Path, logs: Path):
        self.res, self.logs = res, logs
        (res / "excerpts").mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)

    def __call__(self, job_id, body: bytes, text: str, idx, c: dict) -> None:
        (self.logs / f"{job_id}.log").write_bytes(body)
        if idx is None:
            return
        head = f"# job {job_id} sha256 {c['sha256']} bytes {c['bytes']} runner {c['runner']} line {idx}\n"
        with gzip.open(self.res / "excerpts" / f"{job_id}.txt.gz", "wt") as f:
            f.write(head + R.excerpt(text, idx))


def new_state(pool: list[dict]) -> dict:
    return {"order": [[r, c] for r, c in R.repo_order(pool)], "next": 0, "repos": {}, "meta": {},
            "repos_read": 0, "requests": 0, "stopped": None}


def collect(src, state: dict, pool: list[dict], emit, store_log=None, deadline: float | None = None,
            seen: set | None = None) -> str:
    """Advance ``state``; ``emit(row)`` records each PR row. ``seen``: URLs already in prs.jsonl.gz (never read again).
    Returns why this chunk stopped."""
    seen = seen or set()
    base = src.n_requests
    used = lambda: state["requests"] + src.n_requests - base  # noqa: E731
    by_repo: dict[str, list[dict]] = {}
    for r in pool:
        by_repo.setdefault(r["repo"].lower(), []).append(r)
    try:
        while True:
            if state["repos_read"] >= MAX_REPOS:
                state["stopped"] = f"{MAX_REPOS} repositories read"
                return state["stopped"]
            if state["next"] >= len(state["order"]):
                state["stopped"] = "repository order exhausted"
                return state["stopped"]
            name, _count = state["order"][state["next"]]
            key = name.lower()
            rs = state["repos"].setdefault(key, {"name": name, "status": "reading", "read": 0, "done_urls": []})
            if rs["status"] in ("excluded", "done"):
                state["next"] += 1
                continue
            for check in ("cap", "low", "time"):
                why = _chunk_stop(check, used(), src, deadline)
                if why:
                    if check == "cap":
                        state["stopped"] = why
                    return why
            if key not in state["meta"]:
                st, m = src.get_json(f"repos/{name}")
                state["meta"][key] = {"status": st, **({k: m.get(k) for k in ("fork", "archived", "private",
                                                                              "created_at", "full_name")}
                                                       if st == 200 else {})}
            meta = state["meta"][key]
            why = R.repo_exclusion(meta["status"], meta if meta["status"] == 200 else None)
            if why:
                rs.update(status="excluded", reason=why)
                state["next"] += 1
                continue
            prs = sorted(by_repo.get(key, []), key=lambda r: (r["created_at"], r["url"]), reverse=True)
            eligible = []
            for p in prs:
                if R.too_young(meta["created_at"], p["created_at"]):
                    if p["url"] not in rs["done_urls"]:
                        emit({**{k: p.get(k) for k in ("url", "repo", "number", "family", "families", "created_at")},
                              "verdict": "repo_too_young", "reason": f"repository created {meta['created_at']}",
                              "requests": 0})
                        rs["done_urls"].append(p["url"])
                else:
                    eligible.append(p)
            for p in eligible[:MAX_PRS_PER_REPO]:
                if p["url"] in rs["done_urls"] or p["url"] in seen:
                    continue
                for check in ("repos", "cap", "low", "time"):
                    why = _chunk_stop(check, used(), src, deadline, state)
                    if why:
                        if check in ("repos", "cap"):
                            state["stopped"] = why
                        return why
                before = src.n_requests
                row = read_pr(src, p, store_log)
                row["requests"] = src.n_requests - before
                emit(row)
                rs["done_urls"].append(p["url"])
                if rs["read"] == 0:
                    state["repos_read"] += 1
                rs["read"] += 1
            rs["status"] = "done"
            state["next"] += 1
    finally:
        state["requests"] = used()


def _chunk_stop(check: str, used: int, src, deadline, state: dict | None = None) -> str | None:
    if check == "repos" and state is not None and state["repos_read"] >= MAX_REPOS:
        return f"{MAX_REPOS} repositories read"
    if check == "cap" and used >= MAX_REQUESTS:
        return f"{MAX_REQUESTS} requests made"
    if check == "low" and src.low():
        return f"rate limit low ({src.remaining} of {src.limit})"
    if check == "time" and deadline is not None and time.time() > deadline:
        return "max_minutes"
    return None


# ---------------------------------------------------------------- 2.8 oracle


def oracle(src, pr: dict) -> dict:
    repo, b0, path, name = pr["repo"], pr["B0"], pr["workflow_path"], pr["job_name"]
    out = {"url": pr["url"], "B0": b0, "workflow_path": path, "job_name": name}
    st, runs = src.get_json(f"repos/{repo}/actions/runs?head_sha={b0}&event=push&per_page=100")
    if st != 200:
        return {**out, "status": f"runs HTTP {st}", "has_job": False}
    same = [r for r in runs.get("workflow_runs", []) if r.get("status") == "completed"
            and (r.get("path") or "").split("@", 1)[0] == path]
    out["n_completed_runs"] = len(same)
    if not same:
        return {**out, "status": "no completed push run of the workflow at B0", "has_job": False}
    run = max(same, key=lambda r: (r.get("created_at") or "", r["id"]))
    st, js = src.get_json(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
    if st != 200:
        return {**out, "run_id": run["id"], "status": f"jobs HTTP {st}", "has_job": False}
    hit = [j for j in js.get("jobs", []) if j.get("name") == name]
    if not hit:
        return {**out, "run_id": run["id"], "status": "no job of that name", "has_job": False}
    return {**out, "run_id": run["id"], "job_id": hit[0]["id"], "conclusion": hit[0].get("conclusion"),
            "status": "ok", "has_job": True}


# ---------------------------------------------------------------- entry


def main(argv: list[str]) -> int:
    req = json.loads(Path(argv[1]).read_text())
    res = HERE / "results"
    res.mkdir(exist_ok=True)
    src = ghrest.Client(ghrest.token())
    t0 = time.time()
    cp = res / "checkpoint.json"
    if req["kind"] == "oracle":
        sel = json.loads((HERE / "selected.json").read_text())
        rows = [oracle(src, p) for r in sel["repositories"] for p in r["prs"]]
        with open(res / "oracle.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True) + "\n")
        state = json.loads(cp.read_text())
        state["oracle_requests"] = state.get("oracle_requests", 0) + src.n_requests
        cp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
        why = f"oracle: {len(rows)} PRs"
    else:
        pool = read_jsonl(res / "pool.jsonl.gz")
        state = json.loads(cp.read_text()) if cp.exists() else new_state(pool)
        if state.get("stopped"):
            print(f"already stopped: {state['stopped']}")
            return 0
        deadline = t0 + 60 * req["max_minutes"] if req.get("max_minutes") else None
        rows: list[dict] = []
        seen = {r["url"] for r in read_jsonl(res / "prs.jsonl.gz")}

        def emit(row):
            row["chunk"] = req["chunk"]
            rows.append(row)
        try:
            why = collect(src, state, pool, emit, Store(res, HERE / "logs"), deadline, seen)
        finally:
            # The chunk's rows and its checkpoint are written together, at its end: a chunk killed before this point
            # leaves both as they were, and the next chunk reads the same PRs again (nothing duplicated or lost).
            with gzip.open(res / "prs.jsonl.gz", "at") as f:
                for row in rows:
                    f.write(json.dumps(row, sort_keys=True) + "\n")
            cp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
        why = f"{why}; {len(rows)} PR rows"
    with open(res / "chunks.jsonl", "a") as f:
        f.write(json.dumps({"chunk": req["chunk"], "kind": req["kind"], "requests": src.n_requests,
                            "remaining": src.remaining, "limit": src.limit, "reset": src.reset,
                            "seconds": round(time.time() - t0), "stop": why,
                            "at": dt.datetime.now(dt.timezone.utc).isoformat()}, sort_keys=True) + "\n")
    print(why)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
