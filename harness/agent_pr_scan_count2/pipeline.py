"""Count 2 per-PR pipeline over a request source (live GitHub REST in Actions, or replay of committed raw JSON).

``run_pr(src, pr)`` makes every request through ``src.get(path)`` and decides every verdict with ``rules``. The live
source records each response (trimmed to the fields listed in ``trim``) under its exact path; the replay source
serves those records back. Replaying a PR therefore re-derives its verdict from the committed raw JSON, and a
request the replay cannot serve is a verification failure (``Missing``).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import rules as R

API = "https://api.github.com"
UA = "fenvix-research"
MAX_RUN_PAGES = 3
MAX_JOB_READS = 20
MAX_SECONDARY_JOB_READS = 10
MAX_BASE_COMMITS = 30
ACTIONS_APP = "github-actions"


class Missing(Exception):
    """Replay asked for a response that is not in the committed raw JSON."""


# ---------------------------------------------------------------- trimming (fields kept from each API response)

def _run(r: dict) -> dict:
    return {"id": r["id"], "name": r.get("name"), "workflow_id": r.get("workflow_id"),
            "check_suite_id": r.get("check_suite_id"), "event": r.get("event"), "head_sha": r.get("head_sha"),
            "head_branch": r.get("head_branch"), "head_repo": ((r.get("head_repository") or {}).get("full_name")),
            "status": r.get("status"), "conclusion": r.get("conclusion"), "created_at": r.get("created_at"),
            "run_started_at": r.get("run_started_at"), "run_attempt": r.get("run_attempt")}


def trim(path: str, d):
    p = path.split("?", 1)[0]
    if re.search(r"/pulls/\d+$", p):
        return {"number": d.get("number"), "state": d.get("state"), "head_sha": d["head"]["sha"],
                "head_ref": d["head"].get("ref"), "head_repo": (d["head"].get("repo") or {}).get("full_name"),
                "base_ref": d["base"]["ref"], "base_repo": (d["base"].get("repo") or {}).get("full_name"),
                "created_at": d.get("created_at"), "merged_at": d.get("merged_at"), "closed_at": d.get("closed_at")}
    if p.endswith("/check-runs"):
        return {"total_count": d.get("total_count"), "check_runs": [
            {"id": r["id"], "name": r["name"], "status": r.get("status"), "conclusion": r.get("conclusion"),
             "started_at": r.get("started_at"), "completed_at": r.get("completed_at"),
             "app": (r.get("app") or {}).get("slug"), "check_suite_id": (r.get("check_suite") or {}).get("id"),
             "head_sha": r.get("head_sha")} for r in d.get("check_runs", [])]}
    if p.endswith("/status"):
        return {"state": d.get("state"), "statuses": [
            {"context": s.get("context"), "state": s.get("state"), "created_at": s.get("created_at"),
             "updated_at": s.get("updated_at")} for s in d.get("statuses") or []]}
    if p.endswith("/jobs"):
        return {"total_count": d.get("total_count"), "jobs": [
            {"id": j["id"], "name": j.get("name"), "run_id": j.get("run_id"), "status": j.get("status"),
             "conclusion": j.get("conclusion"), "started_at": j.get("started_at"),
             "completed_at": j.get("completed_at"), "head_sha": j.get("head_sha")} for j in d.get("jobs", [])]}
    if p.endswith("/actions/runs"):
        return {"total_count": d.get("total_count"), "workflow_runs": [_run(r) for r in d.get("workflow_runs", [])]}
    if p.endswith("/commits"):
        return [{"sha": c["sha"], "date": ((c.get("commit") or {}).get("committer") or {}).get("date")} for c in d]
    return d


# ---------------------------------------------------------------- sources

class LiveSource:
    """GitHub REST with the workflow token: at most 1 request per second, rate headers tracked, responses recorded."""

    def __init__(self, token: str, pace: float = 1.0):
        self.token, self.pace = token, pace
        self.responses: dict[str, dict] = {}
        self.remaining, self.limit, self.reset = None, None, None
        self.n_requests = 0
        self._last = 0.0

    def low(self, frac: float = 0.2) -> bool:
        return self.remaining is not None and self.limit and self.remaining < frac * self.limit

    def has(self, path: str) -> bool:
        return path in self.responses

    def _http(self, path: str):
        req = urllib.request.Request(f"{API}/{path}", headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA})
        for attempt in range(4):
            wait = self.pace - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.n_requests += 1
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    self._rate(r.headers)
                    return 200, json.loads(r.read())
            except urllib.error.HTTPError as e:
                self._rate(e.headers)
                body = e.read().decode(errors="replace")
                if e.code in (403, 429) and "rate limit" in body.lower() and attempt < 3:
                    reset = int(e.headers.get("X-RateLimit-Reset") or 0)
                    time.sleep(min(max(reset - time.time(), 0) + 5, 3700) if self.remaining == 0 else 60)
                    continue
                if e.code >= 500 and attempt < 3:
                    time.sleep(10)
                    continue
                return e.code, body[:300]
            except Exception as e:  # network
                if attempt == 3:
                    return "network", str(e)[:300]
                time.sleep(5)
        return "retries", "retries exhausted"

    def _rate(self, h) -> None:
        if h and h.get("X-RateLimit-Remaining") is not None:
            self.remaining, self.limit = int(h["X-RateLimit-Remaining"]), int(h["X-RateLimit-Limit"])
            self.reset = int(h.get("X-RateLimit-Reset") or 0)

    def get(self, path: str):
        if path not in self.responses:
            st, d = self._http(path)
            self.responses[path] = {"status": st, "data": trim(path, d)} if st == 200 else \
                {"status": st, "error": d}
        rec = self.responses[path]
        return rec["status"], rec.get("data", rec.get("error"))


class ReplaySource:
    def __init__(self, responses: dict[str, dict]):
        self.responses = responses

    def has(self, path: str) -> bool:
        return path in self.responses

    def get(self, path: str):
        if path not in self.responses:
            raise Missing(path)
        rec = self.responses[path]
        return rec["status"], rec.get("data", rec.get("error"))


# ---------------------------------------------------------------- reads

def checks(src, repo: str, sha: str) -> dict:
    """Copied from harness/dep_verdict/ci_status.py ``checks()``; keeps started_at/completed_at/check_suite_id and the
    statuses' created_at; returns the HTTP status of a failed read as ``error``."""
    runs = []
    for page in (1, 2, 3):
        st, d = src.get(f"repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}")
        if st != 200:
            return {"error": f"check-runs HTTP {st}: {str(d)[:200]}", "runs": runs}
        runs += d["check_runs"]
        if len(d["check_runs"]) < 100:
            break
    st, d = src.get(f"repos/{repo}/commits/{sha}/status")
    if st != 200:
        return {"error": f"status HTTP {st}: {str(d)[:200]}", "runs": runs, "statuses": []}
    return {"runs": runs, "statuses": d["statuses"], "state": d["state"]}


def _err(st, d) -> str:
    return f"HTTP {st}: {str(d)[:200]}"


def run_start(r: dict):
    return R.ts(r.get("run_started_at") or r.get("created_at"))


def run_pr(src, pr: dict, probe: bool = False) -> dict:
    """pr: {repo, number}. Returns the PR's outcome with per-check detail."""
    repo, n = pr["repo"], pr["number"]
    st, pull = src.get(f"repos/{repo}/pulls/{n}")
    if st != 200:
        return {"verdict": R.PR_UNREADABLE, "reason": f"pulls/{n} {_err(st, pull)}"}
    out = {"head_sha": pull["head_sha"], "base_ref": pull["base_ref"], "created_at": pull["created_at"],
           "merged_at": pull["merged_at"], "closed_at": pull["closed_at"]}
    sha, base_ref, created = pull["head_sha"], pull["base_ref"], R.ts(pull["created_at"])
    if probe:
        q = urllib.parse.urlencode({"branch": base_ref, "per_page": 20})
        st, d = src.get(f"repos/{repo}/actions/runs?{q}")
        out["probe_base_runs"] = {"status": st, "n": len(d["workflow_runs"]) if st == 200 else None}
    head = checks(src, repo, sha)
    if head.get("error"):
        return {**out, "verdict": R.HEAD_UNREADABLE, "reason": head["error"]}
    out["n_head_runs"], out["n_head_statuses"] = len(head["runs"]), len(head["statuses"])
    failed = [{"kind": "actions" if r["app"] == ACTIONS_APP else "check", "name": r["name"], "id": r["id"],
               "check_suite_id": r["check_suite_id"], "conclusion": r["conclusion"], "S": r["started_at"]}
              for r in head["runs"] if R.run_failed(r["conclusion"])]
    failed += [{"kind": "status", "name": s["context"], "conclusion": s["state"], "S": s["created_at"]}
               for s in head["statuses"] if R.status_failed(s["state"])]
    if not failed:
        return {**out, "verdict": R.NO_FAILED_CHECK}

    # identities of failed Actions checks
    if any(f["kind"] == "actions" for f in failed):
        st, hr = src.get(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100")
        suites = {r["check_suite_id"]: r for r in hr["workflow_runs"]} if st == 200 else {}
        for f in failed:
            if f["kind"] != "actions":
                continue
            if st != 200:
                f["unreadable"] = f"head actions/runs {_err(st, hr)}"
                continue
            run = suites.get(f["check_suite_id"])
            if not run:
                f["unreadable"] = "workflow run not found for the check suite"
                continue
            f["workflow"], f["run_id"] = run["name"], run["id"]
            jst, jd = src.get(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
            f["job_confirmed"] = jst == 200 and any(j["id"] == f["id"] for j in jd["jobs"])
    for f in failed:
        f["identity"] = R.actions_identity(f["workflow"], f["name"]) if f["kind"] == "actions" and "workflow" in f \
            else (f["name"] if f["kind"] != "actions" else None)

    times = [R.ts(f["S"]) for f in failed if f["S"]]
    if not times:  # no start time on any failed check: no window can be built
        for f in failed:
            f.setdefault("unreadable", "failed head check without started_at")
        times = [created]
    w_from = min([created] + times) - R.WINDOW
    w_to = max(times)
    out["window"] = [R.iso(w_from), R.iso(w_to)]

    # base listings (shared by every identity of the PR)
    base_runs, base_runs_err = None, None
    if any(f["kind"] == "actions" and f.get("identity") and not f.get("unreadable") for f in failed):
        base_runs = []
        for page in range(1, MAX_RUN_PAGES + 1):
            q = urllib.parse.urlencode({"branch": base_ref, "created": f"{w_from.date()}..{w_to.date()}",
                                        "per_page": 100, "page": page})
            st, d = src.get(f"repos/{repo}/actions/runs?{q}")
            if st != 200:
                base_runs_err = f"base actions/runs {_err(st, d)}"
                break
            base_runs += d["workflow_runs"]
            if len(d["workflow_runs"]) < 100:
                break
    commits, commits_err = None, None
    if any(f["kind"] != "actions" and not f.get("unreadable") for f in failed):
        q = urllib.parse.urlencode({"sha": base_ref, "since": R.iso(w_from), "until": R.iso(w_to),
                                    "per_page": MAX_BASE_COMMITS})
        st, d = src.get(f"repos/{repo}/commits?{q}")
        if st != 200:
            commits_err = f"base commits {_err(st, d)}"
        else:
            commits = d[:MAX_BASE_COMMITS]
            # Change after the pre-registration (hand check): the base branch history read now can contain the
            # PR's own commits (merge commit or fast-forward after S); they are not base-side evidence. When the
            # head commit is in the listing, the PR's commits are read and dropped from the walk.
            if any(c["sha"] == sha for c in commits):
                pst, pc = src.get(f"repos/{repo}/pulls/{n}/commits?per_page=100")
                if pst != 200:
                    commits_err = f"PR commits {_err(pst, pc)}"
                else:
                    own = {c["sha"] for c in pc}
                    out["base_commits_own_excluded"] = sum(1 for c in commits if c["sha"] in own)
                    commits = [c for c in commits if c["sha"] not in own]

    for f in failed:
        S = R.ts(f["S"]) if f["S"] else None
        if f.get("unreadable"):
            f["verdict"], f["reason"] = R.UNREADABLE, f["unreadable"]
        elif f["kind"] == "actions":
            _walk_actions(src, repo, f, S, base_runs, base_runs_err)
        else:
            _walk_commits(src, repo, f, S, commits, commits_err)
    # secondary rule (after every primary walk, so the set of base commits already read is fixed)
    for f in failed:
        f["secondary"] = _secondary(src, repo, f, created, base_runs, commits)
    out["failed_checks"] = failed
    out["verdict"] = R.pr_verdict([f["verdict"] for f in failed])
    out["secondary_already_red"] = any(f["secondary"] for f in failed)
    return out


def _base_actions_candidates(repo: str, f: dict, base_runs: list[dict]) -> list[dict]:
    c = [r for r in base_runs if r["name"] == f["workflow"] and (r.get("head_repo") or "").lower() == repo.lower()]
    return sorted(c, key=lambda r: (run_start(r), r["id"]), reverse=True)


def _job_result(job: dict) -> dict:
    return {"started": R.ts(job.get("started_at")), "completed": job.get("status") == "completed",
            "signal": R.result_of_run(job.get("conclusion")) if job.get("status") == "completed" else None}


def _walk_actions(src, repo, f, S, base_runs, err) -> None:
    if err:
        f["verdict"], f["reason"] = R.UNREADABLE, err
        return
    reads = 0
    for r in _base_actions_candidates(repo, f, base_runs):
        rs = run_start(r)
        if not (S - R.WINDOW <= rs < S):
            continue
        if reads >= MAX_JOB_READS:
            f["verdict"], f["reason"] = R.NO_BASE_SIGNAL, "jobs cap"
            return
        reads += 1
        st, jd = src.get(f"repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100")
        if st != 200:
            f["verdict"], f["reason"] = R.UNREADABLE, f"base jobs {_err(st, jd)}"
            return
        cands = [dict(_job_result(j), job_id=j["id"], conclusion=j.get("conclusion"))
                 for j in jd["jobs"] if j.get("name") == f["name"]]
        best = R.pick_primary(cands, S)
        if best:
            f["verdict"] = best["signal"]
            f["base"] = {"run_id": r["id"], "job_id": best["job_id"], "conclusion": best["conclusion"],
                         "started": R.iso(best["started"]), "event": r.get("event"), "head_sha": r.get("head_sha")}
            f["jobs_reads"] = reads
            return
    f["verdict"], f["reason"], f["jobs_reads"] = R.NO_BASE_SIGNAL, "no base run of this identity in the window", reads


def _commit_results(ch: dict, f: dict) -> list[dict]:
    if f["kind"] == "status":
        return [{"started": R.ts(s["created_at"]), "completed": s["state"] != "pending",
                 "signal": R.result_of_status(s["state"]), "conclusion": s["state"]}
                for s in ch["statuses"] if s["context"] == f["name"]]
    return [{"started": R.ts(r["started_at"]), "completed": r["status"] == "completed",
             "signal": R.result_of_run(r["conclusion"]) if r["status"] == "completed" else None,
             "conclusion": r["conclusion"], "check_id": r["id"]}
            for r in ch["runs"] if r["name"] == f["name"] and r["app"] != ACTIONS_APP]


def _walk_commits(src, repo, f, S, commits, err) -> None:
    if err:
        f["verdict"], f["reason"] = R.UNREADABLE, err
        return
    for i, c in enumerate(commits):
        ch = checks(src, repo, c["sha"])
        if ch.get("error"):
            f["verdict"], f["reason"] = R.UNREADABLE, f"base commit {c['sha'][:12]} {ch['error']}"
            return
        best = R.pick_primary(_commit_results(ch, f), S)
        if best:
            f["verdict"] = best["signal"]
            f["base"] = {"commit": c["sha"], "conclusion": best["conclusion"], "started": R.iso(best["started"]),
                         "commits_read": i + 1}
            return
    f["verdict"], f["reason"] = R.NO_BASE_SIGNAL, "no base result of this identity in the window"


def _secondary(src, repo, f, created, base_runs, commits) -> bool:
    if f.get("unreadable") or not f.get("identity"):
        return False
    if f["kind"] == "actions":
        if not base_runs:
            return False
        reads = 0
        for r in _base_actions_candidates(repo, f, base_runs):
            rs = run_start(r)
            if not (created - R.WINDOW <= rs < created) or not R.run_failed(r.get("conclusion")):
                continue
            if reads >= MAX_SECONDARY_JOB_READS:
                break
            reads += 1
            st, jd = src.get(f"repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100")
            if st == 200 and R.secondary_hit([_job_result(j) for j in jd["jobs"] if j.get("name") == f["name"]],
                                             created):
                return True
        return False
    for c in commits or []:
        sp = f"repos/{repo}/commits/{c['sha']}/check-runs?per_page=100&page=1"
        if not src.has(sp):
            continue
        ch = checks(src, repo, c["sha"])
        if not ch.get("error") and R.secondary_hit(_commit_results(ch, f), created):
            return True
    return False


def token() -> str:
    return os.environ["GITHUB_TOKEN"]
