"""Part 1 reading (in the workflow): agent candidates in frame order (§1.1), each read by §1.2, then its control
(§1.3), serially; stops at 200 complete pairs, at the request's time limit, or at the reading deadline.

Request: {"kind": "pairs", "n": k, "max_minutes": 280, "deadline": "<ISO UTC>"}.
State (resumable, committed back): results/pairs_state.json; rows: results/agents.jsonl (one per agent candidate
read), results/control_checks.jsonl, results/control_search/<agent id>.json.gz, results/chunks.jsonl.
"""
from __future__ import annotations

import base64
import datetime as dt
import gzip
import json
import time
import traceback
from pathlib import Path

import ghapi
import md_rules as M

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
LAUNCH = dt.date(2026, 11, 24)
T0_MIN = dt.date(2026, 4, 1)
MAX_PAIRS = 200


class ApiError(Exception):
    pass


class Drop(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Source:
    """GitHub reads for one repository with caches (contents by (ref, path) and by blob sha)."""

    blobs: dict[str, str] = {}

    def __init__(self, client: ghapi.Client, repo: str):
        self.c, self.repo = client, repo
        self.files: dict[tuple[str, str], str | None] = {}

    def get(self, path: str, ok404: bool = False):
        st, data, hd = self.c.get(path)
        if st == 200:
            return data, hd
        if st in (404, 409) and ok404:   # 409: empty repository
            return None, hd
        st, data, hd = self.c.get(path)  # one retry
        if st == 200:
            return data, hd
        if st in (404, 409) and ok404:
            return None, hd
        raise ApiError(f"{st} on {path[:120]}: {json.dumps(data)[:200]}")

    def pages(self, path: str, key: str | None = None, ok404: bool = False, max_pages: int = 10 ** 6) -> list:
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while page <= max_pages:
            data, hd = self.get(f"{path}{sep}page={page}", ok404)
            if data is None:
                return out
            items = data.get(key) if key else data
            out += items or []
            link = {k.lower(): v for k, v in hd.items()}.get("link", "")
            if 'rel="next"' not in link or not items:
                return out
            page += 1
        return out

    def _decode(self, data: dict) -> str | None:
        sha = data.get("sha")
        if sha in Source.blobs:
            return Source.blobs[sha]
        if data.get("encoding") == "base64" and data.get("content") is not None and data.get("size", 0) <= 1_000_000:
            text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        else:
            b, _ = self.get(f"repos/{self.repo}/git/blobs/{sha}")
            text = base64.b64decode(b.get("content") or "").decode("utf-8", errors="replace")
        Source.blobs[sha] = text
        return text

    def read(self, ref: str, path: str) -> str | None:
        k = (ref, path)
        if k not in self.files:
            if not path:
                self.files[k] = None
            else:
                data, _ = self.get(f"repos/{self.repo}/contents/{ghapi.q(path).replace('%2F', '/')}?ref={ref}",
                                   ok404=True)
                self.files[k] = self._decode(data) if isinstance(data, dict) and data.get("type") == "file" else None
        return self.files[k]

    def reader(self, ref: str):
        return lambda p: self.read(ref, p)

    def listdir(self, ref: str, path: str) -> list[dict] | None:
        data, _ = self.get(f"repos/{self.repo}/contents/{path}?ref={ref}", ok404=True)
        return data if isinstance(data, list) else None

    def blob(self, sha: str) -> str:
        if sha not in Source.blobs:
            b, _ = self.get(f"repos/{self.repo}/git/blobs/{sha}")
            Source.blobs[sha] = base64.b64decode(b.get("content") or "").decode("utf-8", errors="replace")
        return Source.blobs[sha]

    def commit_at(self, branch: str, until: dt.datetime) -> str | None:
        data, _ = self.get(f"repos/{self.repo}/commits?sha={ghapi.q(branch)}&until={M.iso(until)}&per_page=1",
                           ok404=True)
        return data[0]["sha"] if data else None


# ------------------------------------------------------------------------------------------------ §1.2 steps 3-6

def test_job_at(src: Source, branch: str, t0: dt.datetime) -> dict:
    sha = src.commit_at(branch, t0)
    if not sha:
        raise Drop("no_test_step", "no commit at T0")
    ls = src.listdir(sha, ".github/workflows")
    if ls is None:
        raise Drop("no_test_step", "no .github/workflows at T0")
    files = [(e["path"], src.blob(e["sha"])) for e in sorted(ls, key=lambda e: e["path"])
             if e.get("type") == "file" and e["name"].endswith((".yml", ".yaml"))]
    mj = M.measured_job(files, src.reader(sha))
    if "reason" in mj:
        raise Drop(mj["reason"], "; ".join(mj["detail"])[:300])
    mj["t0_commit"] = sha
    return mj


def list_runs_fn(src: Source, wf_file: str, branch: str, log: list):
    base = f"repos/{src.repo}/actions/workflows/{ghapi.q(wf_file)}/runs?branch={ghapi.q(branch)}&status=success"

    def one(s, e, unit):
        q = f"{base}&created={M.iso(s)}..{M.iso(e)}&per_page=100"
        first, _ = src.get(q + "&page=1", ok404=True)
        if first is None:
            log.append({"s": M.iso(s), "e": M.iso(e), "total": None, "note": "404"})
            return []
        tc = first.get("total_count") or 0
        log.append({"s": M.iso(s), "e": M.iso(e), "total": tc})
        if tc > 1000 and unit != "hour":
            out = []
            for a, b in M.split_range(s, e, "day" if unit == "week" else "hour"):
                out += one(a, b, "day" if unit == "week" else "hour")
            return out
        runs = list(first.get("workflow_runs") or [])
        page = 2
        while len(runs) < min(tc, 1000) and page <= 10:
            d, _ = src.get(f"{q}&page={page}", ok404=True)
            items = (d or {}).get("workflow_runs") or []
            if not items:
                break
            runs += items
            page += 1
        return runs

    return lambda s, e: one(s, e, "week")


def timing(src: Source, branch: str, t0: dt.datetime, mj: dict, read_time: dt.datetime) -> dict:
    """1.2 steps 4-6 with the measured job ``mj``. Returns D0, D1, g, level, run ids; raises Drop."""
    wf_file = mj["WF"].rsplit("/", 1)[-1]
    run_log: list = []
    lister = list_runs_fn(src, wf_file, branch, run_log)
    cache_runs: dict = {}

    def lr(s, e):
        k = (s, e)
        if k not in cache_runs:
            cache_runs[k] = lister(s, e)
        return cache_runs[k]

    jobs_cache: dict = {}

    def value_fn(level):
        def value_of(run):
            sha = run["head_sha"]
            wf_text = src.read(sha, mj["WF"])
            if wf_text is None:
                return None
            if run["id"] not in jobs_cache:
                jobs_cache[run["id"]] = src.pages(
                    f"repos/{src.repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100", "jobs")
            return M.run_value(wf_text, mj["key"], src.reader(sha), jobs_cache[run["id"]], level)
        return value_of

    windows = {"D0": (M.d0_subranges(t0), True, False), "D1": (M.d1_subranges(t0, read_time), False, True)}
    for level in ("step", "job"):
        try:
            sel = {w: M.select_window(sr, lr, value_fn(level), newest_first=nf, closed_last=cl)
                   for w, (sr, nf, cl) in windows.items()}
            break
        except M.JobLevel:
            continue
    for w, (sr, _, _) in windows.items():
        if len(sel[w]) < 10:
            end = sr[0][1] if w == "D0" else sr[-1][1]
            data, _ = src.get(f"repos/{src.repo}/actions/runs?created=%3C{M.iso(end)}&per_page=1")
            if (data.get("total_count") or 0) == 0:
                raise Drop("retention", f"{w}: no listed run before {M.iso(end)}")
            raise Drop("too_few_runs", f"{w}: {len(sel[w])} runs with a value")
    d0 = M.median10([v for _, v in sel["D0"]])
    d1 = M.median10([v for _, v in sel["D1"]])
    if d0 == 0:
        raise Drop("zero_duration", "D0 = 0")
    return {"level": level, "D0": d0, "D1": d1, "g": d1 / d0,
            "D0_runs": [[r["id"], r["created_at"], v] for r, v in sel["D0"]],
            "D1_runs": [[r["id"], r["created_at"], v] for r, v in sel["D1"]],
            "run_queries": len(run_log)}


def eval_setup_at(src: Source, branch: str, when: dt.datetime) -> dict:
    sha = src.commit_at(branch, when)
    if not sha:
        return {"eval_setup": False, "why": ["no commit"], "commit": None}
    tree, _ = src.get(f"repos/{src.repo}/git/trees/{sha}?recursive=1")
    files = {}
    for e in tree.get("tree") or []:
        p = e.get("path", "")
        if e.get("type") == "blob" and (M.is_dep_file(p) or M.is_promptfoo_config(p)):
            files[p] = "" if M.is_promptfoo_config(p) else src.blob(e["sha"])
    ok, why = M.eval_setup(files)
    return {"eval_setup": ok, "why": why, "commit": sha, "tree_truncated": bool(tree.get("truncated"))}


# ------------------------------------------------------------------------------------------------ agent / control

def read_agent(c: ghapi.Client, cand: dict, read_time: dt.datetime) -> dict:
    repo = cand["repo"]
    src = Source(c, repo)
    meta, _ = src.get(f"repos/{repo}", ok404=False)
    row = {"repo": repo, "id": meta.get("id"), "stars": meta.get("stargazers_count"), "language": meta.get("language"),
           "default_branch": meta.get("default_branch"), "fork": meta.get("fork"), "archived": meta.get("archived"),
           "pushed_at": meta.get("pushed_at")}
    if meta.get("full_name") and meta["full_name"] != repo:
        row["renamed_to"] = meta["full_name"]
        repo = src.repo = meta["full_name"]
    r = M.excluded(meta, LAUNCH)
    if r:
        raise Drop(r, json.dumps({k: row[k] for k in ("stars", "fork", "archived", "pushed_at", "language")}))
    br = meta["default_branch"]
    lists = [src.pages(f"repos/{repo}/commits?path={f}&sha={ghapi.q(br)}&per_page=100", ok404=True)
             for f in ("AGENTS.md", "CLAUDE.md")]
    t0 = M.t0_of(lists)
    row["n_agent_file_commits"] = [len(x) for x in lists]
    if t0 is None:
        raise Drop("no_root_file", "no commit touching root AGENTS.md/CLAUDE.md on the default branch")
    row["T0"] = M.iso(t0)
    if not M.t0_in_range(t0, T0_MIN):
        raise Drop("t0_out_of_range", row["T0"])
    mj = test_job_at(src, br, t0)
    row.update(WF=mj["WF"], job_key=mj["key"], t0_commit=mj["t0_commit"], test_steps=mj["steps"])
    row.update(timing(src, br, t0, mj, read_time))
    return row


def read_control(c: ghapi.Client, item: dict, t0: dt.datetime, read_time: dt.datetime, used: set) -> dict:
    """Note 11 order: 9 agent-path checks, then 1.2 step 3, then runs. Returns the check record."""
    repo, br = item["full_name"], item.get("default_branch") or "main"
    src = Source(c, repo)
    rec = {"repo": repo, "id": item["id"], "stars": item.get("stargazers_count"), "language": item.get("language"),
           "default_branch": br, "until": M.iso(t0 + dt.timedelta(days=272)), "paths": {}}
    until = M.iso(t0 + dt.timedelta(days=272))
    for p in M.AGENT_PATHS:
        data, _ = src.get(f"repos/{repo}/commits?sha={ghapi.q(br)}&path={ghapi.q(p.rstrip('/'))}"
                          f"&until={until}&per_page=1", ok404=True)
        rec["paths"][p] = [x["sha"] for x in (data or [])]
        if data:
            rec["outcome"] = f"agent_file:{p}"
            return rec
    if repo in used:
        rec["outcome"] = "already_used"
        return rec
    try:
        mj = test_job_at(src, br, t0)
        rec.update(WF=mj["WF"], job_key=mj["key"], t0_commit=mj["t0_commit"], test_steps=mj["steps"])
        rec.update(timing(src, br, t0, mj, read_time))
        rec["outcome"] = "eligible"
    except Drop as d:
        rec["outcome"], rec["detail"] = d.reason, d.detail
    except ApiError as e:
        rec["outcome"], rec["detail"] = "error", str(e)[:300]
    return rec


# ------------------------------------------------------------------------------------------------ loop

def jl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def run(req: dict) -> None:
    global RES
    if req.get("debug_repos"):  # debug run on named repositories: rows kept apart, never candidates or pairs
        RES = HERE / "results" / "debug"
        cands = [{"idx": i, "repo": r} for i, r in enumerate(req["debug_repos"])]
    else:
        cands = jl(HERE / "discovery" / "candidates.jsonl.gz")
    RES.mkdir(parents=True, exist_ok=True)
    frame = {x["repo"] for x in cands}
    rows = jl(RES / "agents.jsonl")
    done = {r["idx"] for r in rows}
    pairs = [r for r in rows if r.get("status") == "pair"]
    used = {r["control"]["repo"] for r in pairs}
    c = ghapi.from_env(code_per_min=4)
    t_start, maxm = time.time(), float(req.get("max_minutes", 280))
    deadline = M.ts(req["deadline"]) if req.get("deadline") else None
    n_read, stopped = 0, "frame end"
    for cand in cands:
        if cand["idx"] in done:
            continue
        if len(pairs) >= MAX_PAIRS:
            stopped = "200 pairs"
            break
        if (time.time() - t_start) / 60 > maxm:
            stopped = f"time limit {maxm} min"
            break
        if deadline and now() > deadline:
            stopped = "reading deadline"
            break
        r0, t0c = c.n_requests, time.time()
        read_time = now()
        row = {"idx": cand["idx"], "repo": cand["repo"], "read_at": M.iso(read_time), "chunk": req.get("n")}
        try:
            a = read_agent(c, cand, read_time)
            row["agent"] = a
            row.update(control_pair(c, a, frame, used, read_time))
        except Drop as d:
            row.update(status="dropped", reason=d.reason, detail=d.detail)
        except ApiError as e:
            row.update(status="dropped", reason="error", detail=str(e)[:300])
        except Exception as e:
            row.update(status="dropped", reason="error", detail=f"{type(e).__name__}: {str(e)[:200]}",
                       trace=traceback.format_exc()[-600:])
        row["calls"] = c.n_requests - r0
        row["seconds"] = round(time.time() - t0c, 1)
        append(RES / "agents.jsonl", row)
        n_read += 1
        if row.get("status") == "pair":
            pairs.append(row)
            used.add(row["control"]["repo"])
        print(f"{cand['idx']} {cand['repo']}: {row.get('status')} {row.get('reason', '')} ({row['calls']} calls, "
              f"{len(pairs)} pairs)", flush=True)
    append(RES / "chunks.jsonl", {"n": req.get("n"), "read": n_read, "pairs_total": len(pairs), "stopped": stopped,
                                  "requests": c.n_requests, "rate_limit": c.limit, "remaining": c.remaining,
                                  "minutes": round((time.time() - t_start) / 60, 1), "at": M.iso(now())})


def control_pair(c: ghapi.Client, a: dict, frame: set, used: set, read_time: dt.datetime) -> dict:
    t0 = M.ts(a["T0"])
    q = M.control_query(a["language"], a["stars"], LAUNCH)
    pages, items = [], []
    for page in range(1, 11):
        st, data, _ = c.get(f"search/repositories?q={ghapi.q(q)}&sort=updated&per_page=100&page={page}", "repo")
        if st != 200:
            st, data, _ = c.get(f"search/repositories?q={ghapi.q(q)}&sort=updated&per_page=100&page={page}", "repo")
            if st != 200:
                raise ApiError(f"repository search {st}")
        pages.append(data)
        items += data.get("items") or []
        if len(data.get("items") or []) < 100:
            break
    (RES / "control_search").mkdir(parents=True, exist_ok=True)
    with gzip.open(RES / "control_search" / f"{a['id']}.json.gz", "wt") as f:
        json.dump({"agent": a["repo"], "query": q, "pages": pages}, f)
    order = M.control_order(items, frame, a["repo"], a["id"])
    tested = 0
    for it in order:
        rec = read_control(c, it, t0, read_time, used)
        rec.update(agent=a["repo"], agent_id=a["id"], rank=tested, T0=a["T0"], query=q)
        append(RES / "control_checks.jsonl", rec)
        tested += 1
        if rec["outcome"] == "eligible":
            src_a, src_c = Source(c, a["repo"]), Source(c, rec["repo"])
            when = t0 + dt.timedelta(days=182)
            try:
                ea = eval_setup_at(src_a, a["default_branch"], when)
                ec = eval_setup_at(src_c, rec["default_branch"], when)
            except ApiError as e:
                ea = ec = {"eval_setup": None, "why": [str(e)[:200]]}
            return {"status": "pair", "control": rec, "controls_tested": tested, "eval_agent": ea, "eval_control": ec,
                    "control_candidates": len(order)}
    raise Drop("no_control", f"{tested} tested of {len(order)}")
