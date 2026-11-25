"""Agent tools count pipeline over a request source (live GitHub REST in Actions, or replay of committed raw JSON).

``count_a(src, pr)`` (one pull request of the frame, commit by commit) and ``count_b(src, repo, ...)`` (one
repository's closed issues) make every request through ``src.get(path)`` and decide every class with ``rules``.
The live source records each response (trimmed to the fields listed in ``trim``) under its exact path; the replay
source serves those records back, so ``verify.py`` re-derives every row from the committed raw JSON.

The base-side rule (``judge_commit``, ``_walk_actions``, ``_walk_commits``) is Count 2's ``run_pr`` logic
(origin/claude/agent-pr-scan-count2 3aee9ba, pipeline.py), applied to every commit of the pull request instead of
the last head commit only, without the secondary rule, and keeping the base check run id for non-Actions checks
(gate rev 3 note 1).
"""
from __future__ import annotations

import base64
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
MAX_BASE_COMMITS = 30
ACTIONS_APP = "github-actions"
MAX_PR_COMMITS = 250
MAX_ISSUE_PAGES = 10
OUTPUT_TEXT_MAX = 30000
PATCH_LINES = 400


class Missing(Exception):
    """Replay asked for a response that is not in the committed raw JSON."""


class Interrupted(Exception):
    """The chunk's time limit was reached inside a repository (Count B); the repository is read again next chunk."""


# ---------------------------------------------------------------- trimming (fields kept from each API response)

SHA = r"[0-9a-f]{40}"


def _run(r: dict) -> dict:
    return {"id": r["id"], "name": r.get("name"), "path": r.get("path"), "workflow_id": r.get("workflow_id"),
            "check_suite_id": r.get("check_suite_id"), "event": r.get("event"), "head_sha": r.get("head_sha"),
            "head_branch": r.get("head_branch"), "head_repo": ((r.get("head_repository") or {}).get("full_name")),
            "status": r.get("status"), "conclusion": r.get("conclusion"), "created_at": r.get("created_at"),
            "run_started_at": r.get("run_started_at"), "run_attempt": r.get("run_attempt")}


def _check_run(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "status": r.get("status"), "conclusion": r.get("conclusion"),
            "started_at": r.get("started_at"), "completed_at": r.get("completed_at"),
            "app": (r.get("app") or {}).get("slug"), "check_suite_id": (r.get("check_suite") or {}).get("id"),
            "head_sha": r.get("head_sha")}


def _login(u) -> str | None:
    return (u or {}).get("login")


def _patch(p: str | None) -> str | None:
    if p is None:
        return None
    return "\n".join(p.splitlines()[:PATCH_LINES])


def trim(path: str, d):
    p = path.split("?", 1)[0]
    if "/git/trees/" in p:
        return {"truncated": bool(d.get("truncated")), "blobs": [t["path"] for t in d.get("tree") or []
                                                                 if t.get("type") == "blob"]}
    if "/contents/" in p:
        if isinstance(d, list):
            return {"type": "dir"}
        out = {"type": d.get("type"), "path": d.get("path")}
        if "/contents/.github/workflows/" in p and d.get("encoding") == "base64":
            out["text"] = base64.b64decode(d.get("content") or "").decode(errors="replace")
        return out
    if re.search(r"/pulls/\d+$", p):
        return {"number": d.get("number"), "state": d.get("state"), "title": d.get("title"), "body": d.get("body"),
                "user_login": _login(d.get("user")), "head_sha": d["head"]["sha"], "head_ref": d["head"].get("ref"),
                "head_repo": (d["head"].get("repo") or {}).get("full_name"), "base_ref": d["base"]["ref"],
                "base_repo": (d["base"].get("repo") or {}).get("full_name"), "created_at": d.get("created_at"),
                "merged_at": d.get("merged_at"), "closed_at": d.get("closed_at"), "commits": d.get("commits")}
    if re.search(r"/pulls/\d+/commits$", p):
        return [{"sha": c["sha"], "author_login": _login(c.get("author")),
                 "author_name": ((c.get("commit") or {}).get("author") or {}).get("name"),
                 "message": (c.get("commit") or {}).get("message"),
                 "date": ((c.get("commit") or {}).get("committer") or {}).get("date"),
                 "parents": [x["sha"] for x in c.get("parents") or []]} for c in d]
    if re.search(r"/pulls/\d+/files$", p):
        return [{"filename": f.get("filename"), "status": f.get("status")} for f in d]
    if re.search(r"/pulls/\d+/reviews$", p):
        return [{"user_login": _login(r.get("user")), "state": r.get("state"), "submitted_at": r.get("submitted_at")}
                for r in d]
    if re.search(r"/repos/[^/]+/[^/]+/pulls$", "/" + p):
        return [{"number": x.get("number"), "user_login": _login(x.get("user")),
                 "head_ref": (x.get("head") or {}).get("ref"), "created_at": x.get("created_at"),
                 "flags": R.body_flags(x.get("body"))} for x in d]
    if re.search(r"/check-runs/\d+/annotations$", p):
        return [{"path": a.get("path"), "annotation_level": a.get("annotation_level"), "title": a.get("title"),
                 "message": (a.get("message") or "")[:500], "start_line": a.get("start_line")} for a in d]
    if re.search(r"/check-runs/\d+$", p):
        o = d.get("output") or {}
        return {**_check_run(d), "output": {"title": o.get("title"), "summary": (o.get("summary") or "")[:OUTPUT_TEXT_MAX],
                                            "text": (o.get("text") or "")[:OUTPUT_TEXT_MAX]}}
    if p.endswith("/check-runs"):
        return {"total_count": d.get("total_count"), "check_runs": [_check_run(r) for r in d.get("check_runs", [])]}
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
    if re.search(r"/actions/runs/\d+$", p):
        return {"id": d.get("id"), "name": d.get("name"), "path": d.get("path"), "event": d.get("event")}
    if re.search(rf"/commits/{SHA}$", p):
        return {"sha": d.get("sha"), "parents": [x["sha"] for x in d.get("parents") or []],
                "files": [{"filename": f.get("filename"), "status": f.get("status"), "patch": _patch(f.get("patch"))}
                          for f in d.get("files") or []]}
    if p.endswith("/commits"):
        return [{"sha": c["sha"], "date": ((c.get("commit") or {}).get("committer") or {}).get("date")} for c in d]
    if re.search(r"/issues/\d+/timeline$", p):
        out = []
        for e in d:
            ev = {"event": e.get("event")}
            if e.get("event") == "cross-referenced":
                si = (e.get("source") or {}).get("issue") or {}
                ev.update({"is_pr": bool(si.get("pull_request")), "number": si.get("number"),
                           "repo": (si.get("repository") or {}).get("full_name"), "user_login": _login(si.get("user")),
                           "title": si.get("title"), "body": si.get("body"), "created_at": si.get("created_at"),
                           "closed_at": si.get("closed_at"),
                           "merged_at": (si.get("pull_request") or {}).get("merged_at")})
            out.append(ev)
        return out
    if re.search(r"/repos/[^/]+/[^/]+/issues$", "/" + p):
        return [{"number": i.get("number"), "is_pr": bool(i.get("pull_request")), "title": i.get("title"),
                 "body": (i.get("body") or "")[:2000], "created_at": i.get("created_at"),
                 "closed_at": i.get("closed_at")} for i in d]
    return d


# ---------------------------------------------------------------- sources

class LiveSource:
    """GitHub REST with the workflow token: at most 1 request per second; sleeps until the reset when
    X-RateLimit-Remaining < 500 (the budget is shared with other workflows of this repository)."""

    def __init__(self, token: str, pace: float = 1.0, floor: int = 500, raw: bool = False):
        self.token, self.pace, self.floor, self.raw = token, pace, floor, raw
        self.responses: dict[str, dict] = {}
        self.remaining, self.limit, self.reset = None, None, None
        self.n_requests = 0
        self.slept = 0.0
        self._last = 0.0

    def has(self, path: str) -> bool:
        return path in self.responses

    def _http(self, path: str):
        req = urllib.request.Request(f"{API}/{path}", headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA})
        for attempt in range(4):
            if self.remaining is not None and self.remaining < self.floor and self.reset:
                w = min(max(self.reset - time.time(), 0) + 5, 3700)
                print(f"rate floor: remaining {self.remaining} < {self.floor}, sleeping {w:.0f}s", flush=True)
                time.sleep(w)
                self.slept += w
                self.remaining = None
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
                    w = min(max(reset - time.time(), 0) + 5, 3700) if self.remaining == 0 else 60
                    time.sleep(w)
                    self.slept += w
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
            if st == 200:
                self.responses[path] = {"status": st, "data": d if self.raw else trim(path, d)}
            else:
                self.responses[path] = {"status": st, "error": d}
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


def _err(st, d) -> str:
    return f"HTTP {st}: {str(d)[:200]}"


def run_start(r: dict):
    return R.ts(r.get("run_started_at") or r.get("created_at"))


def page_path(base: str, page: int) -> str:
    return base if page == 1 else f"{base}&page={page}"


# ---------------------------------------------------------------- per-commit checks

def checks_all(src, repo: str, sha: str) -> dict:
    """Check runs (every page, gate rev 3 note 5) and the combined status of one commit."""
    runs = []
    page = 1
    while True:
        st, d = src.get(f"repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}")
        if st != 200:
            return {"error": f"check-runs HTTP {st}: {str(d)[:200]}", "runs": runs}
        runs += d["check_runs"]
        if len(d["check_runs"]) < 100:
            break
        page += 1
    st, d = src.get(f"repos/{repo}/commits/{sha}/status")
    if st != 200:
        return {"error": f"status HTTP {st}: {str(d)[:200]}", "runs": runs, "statuses": []}
    return {"runs": runs, "statuses": d["statuses"], "state": d["state"]}


def commit_view(src, repo: str, sha: str) -> dict:
    """Checks of one commit with an identity for every check run and status. The workflow runs of the commit
    (``actions/runs?head_sha=``, every page) are read when the commit has at least one Actions check run."""
    ch = checks_all(src, repo, sha)
    if ch.get("error"):
        return ch
    suites, runs_err = {}, None
    if any(r["app"] == ACTIONS_APP for r in ch["runs"]):
        page = 1
        while True:
            st, hr = src.get(page_path(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100", page))
            if st != 200:
                runs_err = f"head actions/runs {_err(st, hr)}"
                break
            for r in hr["workflow_runs"]:
                suites[r["check_suite_id"]] = r
            if len(hr["workflow_runs"]) < 100:
                break
            page += 1
    ids = []
    for r in ch["runs"]:
        if r["app"] == ACTIONS_APP:
            run = suites.get(r["check_suite_id"])
            ident = R.actions_identity(run["name"], r["name"]) if run else None
            ids.append({"kind": "actions", "identity": ident, "conclusion": r["conclusion"], "status": r["status"],
                        "id": r["id"]})
        else:
            ids.append({"kind": "check", "identity": r["name"], "conclusion": r["conclusion"], "status": r["status"],
                        "id": r["id"]})
    for s in ch["statuses"]:
        ids.append({"kind": "status", "identity": s["context"], "conclusion": s["state"], "status": "completed"})
    return {**ch, "suites": suites, "runs_err": runs_err, "ids": ids}


def xkey(kind: str, identity: str) -> str:
    return ("status:" if kind == "status" else "check:") + identity


def judge_commit(src, repo: str, n: int, sha: str, base_ref: str, created, view: dict) -> list[dict]:
    """Count 2's head-commit rule applied to commit ``sha``: per failed check, ALREADY_RED / NEW_RED /
    NO_BASE_SIGNAL / UNREADABLE with the base result that decided it."""
    failed = [{"kind": "actions" if r["app"] == ACTIONS_APP else "check", "name": r["name"], "id": r["id"],
               "check_suite_id": r["check_suite_id"], "conclusion": r["conclusion"], "S": r["started_at"],
               "completed_at": r["completed_at"]}
              for r in view["runs"] if R.run_failed(r["conclusion"])]
    failed += [{"kind": "status", "name": s["context"], "conclusion": s["state"], "S": s["created_at"],
                "completed_at": s["updated_at"]}
               for s in view["statuses"] if R.status_failed(s["state"])]
    if not failed:
        return []
    for f in failed:
        if f["kind"] != "actions":
            continue
        if view["runs_err"]:
            f["unreadable"] = view["runs_err"]
            continue
        run = view["suites"].get(f["check_suite_id"])
        if not run:
            f["unreadable"] = "workflow run not found for the check suite"
            continue
        f["workflow"], f["run_id"], f["workflow_path"] = run["name"], run["id"], run.get("path")
        jst, jd = src.get(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
        f["job_confirmed"] = jst == 200 and any(j["id"] == f["id"] for j in jd["jobs"])
    for f in failed:
        f["identity"] = R.actions_identity(f["workflow"], f["name"]) if f["kind"] == "actions" and "workflow" in f \
            else (f["name"] if f["kind"] != "actions" else None)

    times = [R.ts(f["S"]) for f in failed if f["S"]]
    if not times:
        for f in failed:
            f.setdefault("unreadable", "failed check without started_at")
        times = [created]
    w_from = min([created] + times) - R.WINDOW
    w_to = max(times)

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
            # Count 2 (change after its pre-registration): the PR's own commits are not base-side evidence.
            if any(c["sha"] == sha for c in commits):
                pst, pc = src.get(f"repos/{repo}/pulls/{n}/commits?per_page=100")
                if pst != 200:
                    commits_err = f"PR commits {_err(pst, pc)}"
                else:
                    own = {c["sha"] for c in pc}
                    commits = [c for c in commits if c["sha"] not in own]
    for f in failed:
        S = R.ts(f["S"]) if f["S"] else None
        if f.get("unreadable"):
            f["verdict"], f["reason"] = R.UNREADABLE, f["unreadable"]
        elif f["kind"] == "actions":
            _walk_actions(src, repo, f, S, base_runs, base_runs_err)
        else:
            _walk_commits(src, repo, f, S, commits, commits_err)
    return failed


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
            return
    f["verdict"], f["reason"] = R.NO_BASE_SIGNAL, "no base run of this identity in the window"


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
        ch = checks_all(src, repo, c["sha"])
        if ch.get("error"):
            f["verdict"], f["reason"] = R.UNREADABLE, f"base commit {c['sha'][:12]} {ch['error']}"
            return
        best = R.pick_primary(_commit_results(ch, f), S)
        if best:
            f["verdict"] = best["signal"]
            f["base"] = {"commit": c["sha"], "conclusion": best["conclusion"], "started": R.iso(best["started"]),
                         "check_id": best.get("check_id"), "commits_read": i + 1}
            return
    f["verdict"], f["reason"] = R.NO_BASE_SIGNAL, "no base result of this identity in the window"


# ---------------------------------------------------------------- evidence

class Tree:
    """Blob paths of a commit's tree; a truncated tree is completed path by path with the contents API."""

    def __init__(self, src, repo: str, sha: str):
        self.src, self.repo, self.sha = src, repo, sha
        st, d = src.get(f"repos/{repo}/git/trees/{sha}?recursive=1")
        self.error = None if st == 200 else _err(st, d)
        self.blobs = set(d["blobs"]) if st == 200 else set()
        self.truncated = st == 200 and d["truncated"]

    def exists(self, path: str) -> bool:
        if path in self.blobs:
            return True
        if not self.truncated:
            return False
        st, d = self.src.get(f"repos/{self.repo}/contents/{urllib.parse.quote(path)}?ref={self.sha}")
        return st == 200 and d.get("type") == "file"


def check_evidence(src, repo: str, check_id: int | None, sha: str | None) -> dict:
    """Failure files of one check run (``files`` / ``none``) with the annotations and output text kept for the
    hand read."""
    if not check_id or not sha:
        return {"class": "none", "files": [], "candidates": [], "annotations": [], "output": None}
    st, cr = src.get(f"repos/{repo}/check-runs/{check_id}")
    ast, ann = src.get(f"repos/{repo}/check-runs/{check_id}/annotations?per_page=100")
    out = cr["output"] if st == 200 else None
    anns = ann if ast == 200 else []
    cands = R.evidence_candidates(anns, out)
    files = []
    tree_err = None
    if cands:
        t = Tree(src, repo, sha)
        tree_err = t.error
        files = R.failure_files(cands, t.exists)
    return {"class": "files" if files else "none", "files": files, "candidates": cands, "tree_error": tree_err,
            "read_errors": [x for x in (None if st == 200 else f"check-run {_err(st, cr)}",
                                        None if ast == 200 else f"annotations {_err(ast, ann)}") if x],
            "annotations": [a for a in anns if a.get("annotation_level") == "failure"][:30],
            "output": None if out is None else {"title": out.get("title"), "summary": (out.get("summary") or "")[:3000],
                                                "text": (out.get("text") or "")[:3000]}}


USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?(\S+?)['\"]?\s*(?:#.*)?$", re.MULTILINE)


def callee_paths(text: str, repo: str) -> list[str]:
    """Reusable workflows called by a workflow file: ``./.github/workflows/x.yml`` or ``<repo>/.github/workflows/
    x.yml@ref`` (this repository only)."""
    out = []
    for m in USES_RE.finditer(text or ""):
        u = m.group(1)
        if u.startswith("./.github/workflows/"):
            out.append(u[2:])
        elif u.lower().startswith(repo.lower() + "/.github/workflows/"):
            out.append(u[len(repo) + 1:].split("@", 1)[0])
    return sorted(set(out))


# ---------------------------------------------------------------- Count A

def _commit_rec(i: int, c: dict, family: str, author: str | None, head_ref: str | None) -> dict:
    return {"pos": i, "sha": c["sha"], "author_login": c["author_login"], "message": c["message"] or "",
            "date": c["date"], "parents": len(c["parents"]),
            "agent": R.is_agent_commit(family, c, author, head_ref)}


def count_a(src, pr: dict) -> dict:
    """pr: {repo, number, family}. One frame pull request, commit by commit (§1)."""
    repo, n, family = pr["repo"], pr["number"], pr["family"]
    st, pull = src.get(f"repos/{repo}/pulls/{n}")
    if st != 200:
        return {"result": R.UNCERTAIN, "reason": f"pulls/{n} {_err(st, pull)}"}
    out = {"author": pull["user_login"], "head_ref": pull["head_ref"], "base_ref": pull["base_ref"],
           "created_at": pull["created_at"], "n_commits_pr": pull["commits"]}
    if (pull["commits"] or 0) > MAX_PR_COMMITS:
        return {**out, "result": R.UNCERTAIN, "reason": f"{pull['commits']} commits (> {MAX_PR_COMMITS})"}
    raw_commits = []
    for page in (1, 2, 3):
        st, d = src.get(page_path(f"repos/{repo}/pulls/{n}/commits?per_page=100", page))
        if st != 200:
            return {**out, "result": R.UNCERTAIN, "reason": f"pulls/{n}/commits {_err(st, d)}"}
        raw_commits += d
        if len(d) < 100:
            break
    force, page = 0, 1
    while True:
        st, d = src.get(f"repos/{repo}/issues/{n}/timeline?per_page=100&page={page}")
        if st != 200:
            force = None
            break
        force += sum(1 for e in d if e["event"] == "head_ref_force_pushed")
        if len(d) < 100:
            break
        page += 1
    out["force_pushes"] = force
    author, head_ref = pull["user_login"], pull["head_ref"]
    cs = [_commit_rec(i + 1, c, family, author, head_ref) for i, c in enumerate(raw_commits)]
    N = len(cs)
    out["n_commits"] = N
    created = R.ts(pull["created_at"])
    views, judged = {}, {}
    for c in cs:
        v = commit_view(src, repo, c["sha"])
        if v.get("error"):
            return {**out, "result": R.UNCERTAIN, "reason": f"commit {c['pos']} {v['error']}"}
        views[c["pos"]] = v
        judged[c["pos"]] = judge_commit(src, repo, n, c["sha"], pull["base_ref"], created, v)
        c["n_runs"], c["n_statuses"] = len(v["runs"]), len(v["statuses"])
        c["n_action_required"] = sum(1 for r in v["runs"] if r["conclusion"] == "action_required")
        c["new_red"] = any(f["verdict"] == R.NEW_RED for f in judged[c["pos"]])
        c["failed"] = [{"identity": f.get("identity"), "kind": f["kind"], "verdict": f["verdict"]}
                       for f in judged[c["pos"]]]

    # states of every identity per commit
    states: dict[str, dict[int, str]] = {}
    for c in cs:
        pos = c["pos"]
        fkeys = {}
        for f in judged[pos]:
            if f.get("identity") is None:
                continue
            k = xkey(f["kind"], f["identity"])
            s = {"ALREADY_RED": "already", "NEW_RED": "new_red"}.get(f["verdict"], "fail_other")
            if fkeys.get(k) != "already":
                fkeys[k] = s
        for k, s in fkeys.items():
            states.setdefault(k, {})[pos] = s
        for x in views[pos]["ids"]:
            if x["identity"] is None:
                continue
            k = xkey(x["kind"], x["identity"])
            if k in fkeys:
                continue
            if x["status"] == "completed" and x["conclusion"] == "success":
                states.setdefault(k, {})[pos] = "pass"

    # X set: first commit where each identity is already red
    xs = {}
    for c in cs:
        for f in judged[c["pos"]]:
            if f["verdict"] == R.ALREADY_RED and f.get("identity") is not None:
                k = xkey(f["kind"], f["identity"])
                if k not in xs:
                    xs[k] = {"key": k, "identity": f["identity"], "kind": f["kind"], "k": c["pos"], "f": f}

    commit_files: dict[int, dict] = {}

    def files_of(c):
        if c["pos"] not in commit_files:
            st, d = src.get(f"repos/{repo}/commits/{c['sha']}")
            commit_files[c["pos"]] = d if st == 200 else {"error": _err(st, d), "files": None}
        return commit_files[c["pos"]]

    def new_red_before(pos: int) -> bool:
        for j in range(pos - 1, 0, -1):
            cj = cs[j - 1]
            if cj["n_runs"] or cj["n_statuses"]:
                return cj["new_red"]
        return False

    any_wasted = any_after = any_files = False
    x_rows, errors = [], []
    for k_, x in xs.items():
        f, k = x["f"], x["k"]
        T = R.ts(f.get("completed_at"))
        end = R.x_window(k, states.get(k_, {}), N)
        sha_k = cs[k - 1]["sha"]
        base = f.get("base") or {}
        if f["kind"] == "status":
            ev_k = check_evidence(src, repo, None, None)
            ev_b = check_evidence(src, repo, None, None)
        else:
            ev_k = check_evidence(src, repo, f["id"], sha_k)
            bid = base.get("job_id") if f["kind"] == "actions" else base.get("check_id")
            bsha = base.get("head_sha") if f["kind"] == "actions" else base.get("commit")
            ev_b = check_evidence(src, repo, bid, bsha)
        any_files = any_files or ev_k["class"] == "files"
        marks = {p: R.in_base(p, ev_b["files"]) for p in ev_k["files"]}
        caller = f.get("workflow_path") if f["kind"] == "actions" else None
        wf = {"caller": caller, "callees": None}
        window, wasted = [], []
        for c in cs:
            if not c["agent"]:
                continue
            if R.after_k(c | {"date": R.ts(c["date"])}, k, T):
                any_after = True
            if not R.in_window(c | {"date": R.ts(c["date"])}, k, T, end):
                continue
            cf = files_of(c)
            if cf.get("error"):
                errors.append(f"commit {c['pos']} {cf['error']}")
            fnames = [x_["filename"] for x_ in cf.get("files") or []]
            if caller and wf["callees"] is None and any(
                    p.startswith(".github/workflows/") and p != caller for p in fnames):
                cst, cd = src.get(f"repos/{repo}/contents/{caller}?ref={sha_k}")
                wf["callees"] = callee_paths(cd.get("text") if cst == 200 else "", repo)
            wpaths = ([caller] if caller else []) + (wf["callees"] or [])
            reasons = R.wasted_reasons({"message": c["message"], "files": fnames},
                                       {"failure_files": ev_k["files"], "workflow_paths": wpaths},
                                       new_red_before(c["pos"]),
                                       c["pos"] == end and states.get(k_, {}).get(end) == "pass")
            rec = {"pos": c["pos"], "sha": c["sha"], "message": c["message"][:600], "reasons": reasons,
                   "files": [{"filename": x_["filename"], "status": x_["status"],
                              "patch_head": "\n".join((x_.get("patch") or "").splitlines()[:12])}
                             for x_ in (cf.get("files") or [])[:30]],
                   "n_files": len(fnames)}
            window.append(rec)
            if reasons:
                wasted.append(c["pos"])
                any_wasted = True
        x_rows.append({"identity": x["identity"], "kind": x["kind"], "k": k, "T": f.get("completed_at"),
                       "end": end, "states": {str(p): s for p, s in sorted(states.get(k_, {}).items())},
                       "check_id": f.get("id"), "base": base, "base_event": base.get("event"),
                       "workflow_path": caller, "callees": wf["callees"],
                       "evidence": ev_k, "base_evidence": ev_b, "in_base": marks,
                       "window": window, "wasted_commits": wasted})
    if errors:
        return {**out, "result": R.UNCERTAIN, "reason": "; ".join(errors)[:500], "xs": x_rows,
                "commits": _commit_summary(cs)}
    out["xs"] = x_rows
    out["commits"] = _commit_summary(cs)
    out["files_evidence"] = any_files
    out["result"] = R.pr_result(bool(xs), any_wasted, any_after)
    out["human_after"] = sum(1 for c in cs if not c["agent"] and c["parents"] < 2 and xs and
                             c["pos"] > min(x["k"] for x in xs.values()))
    return out


def _commit_summary(cs: list[dict]) -> list[dict]:
    return [{k: c.get(k) for k in ("pos", "sha", "author_login", "date", "parents", "agent", "n_runs", "n_statuses",
                                   "n_action_required", "new_red", "failed")} | {"message": c["message"][:200]}
            for c in cs]


# ---------------------------------------------------------------- Count B

def count_b(src, repo: str, race_from: str, should_stop=None) -> dict:
    """One repository's closed issues since RACE_FROM (§2). ``should_stop()`` returns None, ``"chunk"`` (raise
    Interrupted: the repository is read again in the next chunk) or ``"budget"`` (keep what was read, status
    ``partial-budget``)."""
    rf = R.ts(race_from)
    st, d = src.get(f"repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page=100")
    if st != 200:
        return {"status": "unreadable", "reason": f"pulls {_err(st, d)}"}
    if not any(R.pr_family(p["user_login"], p["head_ref"], p["flags"]) and R.ts(p["created_at"]) >= rf for p in d):
        return {"status": "skipped-no-agent"}
    issues, truncated = [], False
    for page in range(1, MAX_ISSUE_PAGES + 1):
        q = f"repos/{repo}/issues?state=closed&since={race_from}&sort=updated&direction=desc&per_page=100"
        st, d = src.get(page_path(q, page))
        if st != 200:
            return {"status": "unreadable", "reason": f"issues page {page} {_err(st, d)}"}
        issues += d
        if len(d) < 100:
            break
        if page == MAX_ISSUE_PAGES:
            truncated = True
    keep = [i for i in issues if not i["is_pr"] and i["closed_at"] and R.ts(i["closed_at"]) >= rf]
    seen = set()
    keep = [i for i in keep if not (i["number"] in seen or seen.add(i["number"]))]
    out_issues, status, n_read, errors = [], "read", 0, 0
    for iss in keep:
        if should_stop:
            s = should_stop()
            if s == "chunk":
                raise Interrupted(repo)
            if s == "budget":
                status = "partial-budget"
                break
        r = _issue(src, repo, iss)
        n_read += 1
        if r is None:
            errors += 1
            continue
        if r["class"]:
            out_issues.append(r)
    return {"status": status, "truncated": truncated, "n_issues": len(keep), "n_issues_read": n_read,
            "n_timeline_errors": errors, "issues": out_issues}


def _pull(src, repo, m):
    st, d = src.get(f"repos/{repo}/pulls/{m}")
    return d if st == 200 else None


def _issue(src, repo: str, iss: dict) -> dict | None:
    n = iss["number"]
    events, page = [], 1
    while True:
        st, d = src.get(f"repos/{repo}/issues/{n}/timeline?per_page=100&page={page}")
        if st != 200:
            return None
        events += d
        if len(d) < 100:
            break
        page += 1
    xrefs = {}
    for e in events:
        if e["event"] == "cross-referenced" and R.same_repo_pr_xref(e, repo):
            xrefs.setdefault(e["number"], e)
    agents = []
    for m, e in sorted(xrefs.items()):
        if not R.agent_candidate(e["user_login"], R.body_flags(e["body"])):
            continue
        flags = R.body_flags(e["body"])
        by_body = R.closes(e["body"], repo, n)
        pull = None
        if not by_body or (flags["codex"] and e["user_login"] not in
                           set().union(*R.PR_LOGINS.values())):
            pull = _pull(src, repo, m)
            if pull is None:
                continue
        head_ref = pull["head_ref"] if pull else None
        fam = R.pr_family(e["user_login"], head_ref, flags)
        if fam is None:
            continue
        link = "a" if by_body else ("b" if R.ref_names_issue(head_ref, n) else None)
        if link is None:
            continue
        fst, files = src.get(f"repos/{repo}/pulls/{m}/files?per_page=20")
        agents.append({"number": m, "family": fam, "link": link, "user_login": e["user_login"],
                       "created_at": e["created_at"], "closed_at": e["closed_at"], "merged_at": e["merged_at"],
                       "title": e["title"], "body": (e["body"] or "")[:2000], "head_ref": head_ref,
                       "files": [f["filename"] for f in files[:20]] if fst == 200 else None})
    cls = R.issue_class(agents)
    out = {"number": n, "title": iss["title"], "body": iss["body"], "closed_at": iss["closed_at"], "class": cls,
           "agent_prs": sorted(agents, key=lambda p: (R.ts(p["created_at"]), p["number"]))}
    if cls == R.COMPETING:
        for p in out["agent_prs"]:
            pull = _pull(src, repo, p["number"])
            p["head_sha"] = pull["head_sha"] if pull else None
            rst, rv = src.get(f"repos/{repo}/pulls/{p['number']}/reviews?per_page=100")
            p["approved"] = rst == 200 and any(r["state"] == "APPROVED" for r in rv)
            g = None
            if p["head_sha"]:
                ch = checks_all(src, repo, p["head_sha"])
                if not ch.get("error"):
                    g = R.green_time(ch["runs"])
            p["green"] = R.iso(g) if g else None
        out["labels"] = R.choice_labels(out["agent_prs"])
    return out


def token() -> str:
    return os.environ["GITHUB_TOKEN"]
