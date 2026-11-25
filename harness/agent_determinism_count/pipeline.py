"""Per-candidate §2 membership and §3.1 recordings over a request source (live REST in the workflow, or replay of the
committed raw responses).

``run_candidate(src, cand, opts)`` makes every request through ``src.get(path, kind=...)`` and returns one row. The
live source records each trimmed response under its path; the replay source serves them back, so ``verify.py``
re-derives every row from the committed raw JSON (``Missing`` when a response is absent). The 300-request cap counts
distinct core paths requested for the candidate (membership, recordings and, later, comments), identically live and in
replay. LiveSource/ReplaySource and the trimming pattern are copied from test-quality-count 432d4b0 pipeline.py.
"""
from __future__ import annotations

import base64
import posixpath
import re
import urllib.parse

import rules as R

OWNERS_EXCLUDED = {"mircoguidetti", "langchain-ai", "crewaiinc", "run-llama", "ag2ai", "agno-agi", "mastra-ai",
                   "pydantic", "kevin1024", "ktosiek", "nock", "deepset-ai", "strands-agents"}
REPOS_EXCLUDED = {"netflix/pollyjs", "kiwicom/pytest-recording", "microsoft/autogen", "microsoft/semantic-kernel",
                  "openai/openai-agents-python", "openai/openai-agents-js", "vercel/ai", "huggingface/smolagents",
                  "google/adk-python", "phidatahq/phidata", "stanfordnlp/dspy"}
REPO_PATTERNS_EXCLUDED = [re.compile(r"^google/adk-"), re.compile(r"^anthropics/claude-agent-sdk-")]
GENERAL_TOOLS = ["vcrpy", "pytest-recording", "pytest-vcr", "@pollyjs/core", "nock"]
RESOLVE_FILES = {"Makefile", "makefile", "GNUmakefile", "package.json", "tox.ini", "noxfile.py"}


class Missing(Exception):
    pass


class ApiError(Exception):
    pass


class CapReached(Exception):
    pass


# ---------------------------------------------------------------------------------------------- trimming

def _b64(d: dict):
    if d.get("encoding") == "base64" and d.get("content") is not None:
        return base64.b64decode(d["content"]).decode("utf-8", errors="replace")
    return None


def tree_keep(path: str) -> bool:
    return bool(R.manifest_kind(path) or path.startswith(".github/workflows/") or R.recording_file(path)
                or posixpath.basename(path) in RESOLVE_FILES)


def trim_search_item(x: dict, kind: str) -> dict:
    if kind == "commits":
        c = x.get("commit") or {}
        return {"kind": "commit", "url": x.get("html_url"), "sha": x.get("sha"),
                "repo": (x.get("repository") or {}).get("full_name"), "message": (c.get("message") or "")[:8000],
                "created_at": ((c.get("committer") or {}).get("date") or (c.get("author") or {}).get("date"))}
    ru = x.get("repository_url") or ""
    return {"kind": "pr" if x.get("pull_request") else "issue", "url": x.get("html_url"), "number": x.get("number"),
            "repo": ru.split("/repos/", 1)[1] if "/repos/" in ru else None, "title": x.get("title") or "",
            "body": (x.get("body") or "")[:8000], "created_at": x.get("created_at")}


def trim(path: str, d, kind: str | None = None):
    p = path.split("?", 1)[0]
    if p in ("search/issues", "search/commits") and isinstance(d, dict):
        k = "commits" if p == "search/commits" else "issues"
        return {"total_count": d.get("total_count"), "incomplete_results": d.get("incomplete_results"),
                "items": [trim_search_item(x, k) for x in d.get("items", [])]}
    if p == "search/code" and isinstance(d, dict):
        return {"total_count": d.get("total_count"), "incomplete_results": d.get("incomplete_results"),
                "items": [{"repo": (x.get("repository") or {}).get("full_name"), "path": x.get("path"),
                           "url": x.get("html_url")} for x in d.get("items", [])]}
    if isinstance(d, dict) and p.count("/") == 2 and p.startswith("repos/"):
        return {k: d.get(k) for k in ("full_name", "fork", "archived", "pushed_at", "default_branch", "private",
                                      "html_url")} | \
            {"owner": d["owner"].get("login") if isinstance(d.get("owner"), dict) else d.get("owner")}
    if "/git/trees/" in p and isinstance(d, dict):
        tree = d.get("tree") or []
        return {"truncated": bool(d.get("truncated")), "n_entries": len(tree),
                "files": sorted([x["path"], x.get("sha"), x.get("size")] for x in tree
                                if x.get("type") == "blob" and tree_keep(x.get("path") or ""))}
    if "/git/blobs/" in p and isinstance(d, dict):
        text = _b64(d)
        if kind == "rec":
            return R.recording_facts(None, text, d.get("size"))
        return {"size": d.get("size"), "text": text}
    if "/contents/" in p or p.endswith("/contents"):
        if isinstance(d, list):
            return [{"name": x.get("name"), "path": x.get("path"), "type": x.get("type"), "sha": x.get("sha"),
                     "size": x.get("size")} for x in d]
        return d
    if p.endswith("/runs") and isinstance(d, dict):
        return {"total_count": d.get("total_count"), "workflow_runs": [
            {"id": r["id"], "event": r.get("event"), "created_at": r.get("created_at"), "status": r.get("status"),
             "conclusion": r.get("conclusion"), "html_url": r.get("html_url"), "path": r.get("path")}
            for r in d.get("workflow_runs", [])]}
    if p.endswith("/jobs") and isinstance(d, dict):
        return {"total_count": d.get("total_count"), "jobs": [
            {"id": j["id"], "name": j.get("name"), "status": j.get("status"), "conclusion": j.get("conclusion"),
             "html_url": j.get("html_url"),
             "steps": [{"name": s.get("name"), "number": s.get("number"), "conclusion": s.get("conclusion")}
                       for s in j.get("steps") or []]} for j in d.get("jobs", [])]}
    if p.endswith("/commits") and isinstance(d, list):
        return [{"sha": x.get("sha"), "date": ((x.get("commit") or {}).get("committer") or {}).get("date"),
                 "html_url": x.get("html_url")} for x in d[:1]]
    if p.endswith("/comments") and isinstance(d, list):
        return [{"created_at": x.get("created_at"), "body": (x.get("body") or "")[:4000]} for x in d]
    return d


def _is_search(path: str) -> bool:
    return path.startswith("search/")


class LiveSource:
    """Every request of one candidate (or one text pass). ``cap``: distinct core paths allowed (``used`` already
    spent by earlier passes)."""

    def __init__(self, client, cap: int = R.REQUEST_CAP, used: int = 0):
        self.c = client
        self.responses: dict[str, dict] = {}
        self.cap, self.core = cap, used

    def get(self, path: str, kind: str | None = None):
        key = path + ("#rec" if kind == "rec" else "")
        if key in self.responses:
            r = self.responses[key]
            return r["status"], r.get("data")
        search = _is_search(path)
        if not search:
            if self.core >= self.cap:
                raise CapReached(path)
            self.core += 1
        st, data, _ = self.c.get(path, search=("code" if path.startswith("search/code") else "issues")
                                  if search else None)
        if st not in (200, 404, 409, 422):
            st, data, _ = self.c.get(path, search=("code" if path.startswith("search/code") else "issues")
                                     if search else None)  # one retry
        rec = {"status": st, "data": trim(path, data, kind) if st == 200 else
               {"message": (data or {}).get("message") if isinstance(data, dict) else str(data)[:200]}}
        self.responses[key] = rec
        return rec["status"], rec["data"]


class ReplaySource:
    def __init__(self, responses: dict, cap: int = R.REQUEST_CAP, used: int = 0):
        self.responses = responses
        self.cap, self.core = cap, used
        self._seen: set = set()

    def get(self, path: str, kind: str | None = None):
        key = path + ("#rec" if kind == "rec" else "")
        if key not in self._seen:
            if not _is_search(path):
                if self.core >= self.cap:
                    raise CapReached(path)
                self.core += 1
            self._seen.add(key)
        if key not in self.responses:
            raise Missing(key)
        r = self.responses[key]
        return r["status"], r.get("data")


# ---------------------------------------------------------------------------------------------- repository files

def q(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


class Repo:
    def __init__(self, src, repo: str, ref: str, files: dict):
        self.src, self.repo, self.ref, self.files = src, repo, ref, files  # path -> (sha, size)

    def read(self, path: str):
        if not path or path not in self.files:
            return None
        sha = self.files[path][0]
        st, d = self.src.get(f"repos/{self.repo}/git/blobs/{sha}", kind="text")
        if st != 200:
            raise ApiError(f"blob {path}: HTTP {st}")
        if d.get("text") is None:
            raise ApiError(f"blob {path}: no text")
        return d["text"]

    def last_commit_date(self, path: str):
        st, d = self.src.get(f"repos/{self.repo}/commits?" + urllib.parse.urlencode(
            {"path": path, "sha": self.ref, "per_page": 1}))
        if st != 200:
            raise ApiError(f"commits {path}: HTTP {st}")
        return (d[0].get("date"), d[0].get("html_url")) if d else (None, None)


def excluded(meta: dict, repo: str, extra: list[str] | None = None) -> list[str]:
    out = []
    full = (meta.get("full_name") or repo).lower()
    owner = (meta.get("owner") or full.split("/")[0]).lower()
    if meta.get("fork"):
        out.append("fork")
    if meta.get("archived"):
        out.append("archived")
    if (meta.get("pushed_at") or "") < R.WINDOW_START:
        out.append("stale")
    if owner in OWNERS_EXCLUDED or full in REPOS_EXCLUDED or any(p.match(full) for p in REPO_PATTERNS_EXCLUDED) \
            or full in {x.lower() for x in extra or []}:
        out.append("library-owner" if owner != "mircoguidetti" else "own")
    return out


def list_files(src, repo: str, ref: str) -> tuple[dict, bool]:
    """(path -> (sha, size), truncated). A truncated tree falls back to the contents API: .github/workflows and the
    root and first-level manifests."""
    st, d = src.get(f"repos/{repo}/git/trees/{q(ref)}?recursive=1")
    if st == 409:  # empty repository
        return {}, False
    if st != 200:
        raise ApiError(f"tree: HTTP {st}")
    files = {p: (sha, size) for p, sha, size in d["files"]}
    if not d["truncated"]:
        return files, False
    files = {}

    def listing(path: str):
        s2, x = src.get(f"repos/{repo}/contents/{q(path)}?ref={urllib.parse.quote(ref)}" if path else
                        f"repos/{repo}/contents?ref={urllib.parse.quote(ref)}")
        if s2 == 404:
            return []
        if s2 != 200 or not isinstance(x, list):
            raise ApiError(f"contents {path}: HTTP {s2}")
        return x

    root = listing("")
    for e in root:
        if e["type"] == "file" and tree_keep(e["path"]):
            files[e["path"]] = (e["sha"], e["size"])
    for e in root:
        if e["type"] == "dir" and e["name"] not in R.SKIP_DIRS and not e["name"].startswith("."):
            for x in listing(e["path"]):
                if x["type"] == "file" and R.manifest_kind(x["path"]):
                    files[x["path"]] = (x["sha"], x["size"])
    for x in listing(".github/workflows"):
        if x["type"] == "file":
            files[x["path"]] = (x["sha"], x["size"])
    return files, True


# ---------------------------------------------------------------------------------------------- §2.2 libraries

def check_libraries(rp: Repo, opts: dict) -> dict:
    mans = sorted((p for p in rp.files if R.manifest_kind(p)), key=lambda p: (p.count("/"), p))
    out = {"manifests": len(mans), "libraries": [], "errors": [], "recording_packages": [], "markers": [],
           "general_tools": []}
    for p in mans[:R.MANIFEST_CAP]:
        text = rp.read(p)
        try:
            deps = R.parse_manifest(p, text)
        except R.ManifestError as e:
            out["errors"].append({"file": p, "error": str(e)[:160]})
            continue
        for lib, k in R.libraries_of(p, deps):
            out["libraries"].append({"lib": lib, "kind": k, "file": p})
        pk = R.recording_packages_of(p, deps, opts.get("recording_packages") or [])
        if pk:
            out["recording_packages"].append({"file": p, "packages": pk})
        out["general_tools"] += R.recording_packages_of(p, deps, GENERAL_TOOLS)
        out["markers"] += [{"file": p, "marker": m.group(0)} for m in R.MARKER_RE.finditer(text)]
    out["capped"] = len(mans) > R.MANIFEST_CAP
    out["general_tools"] = sorted(set(out["general_tools"]))
    return out


# ---------------------------------------------------------------------------------------------- §2.3 CI tests

def workflow_targets(rp: Repo) -> tuple[dict, list[str]]:
    """{run_file: [target]} of jobs with a test step, and the reasons for `uncertain` met while parsing."""
    wfs = sorted(p for p in rp.files if posixpath.dirname(p) == ".github/workflows" and p.endswith((".yml", ".yaml")))
    parsed, flags = {}, []
    for p in wfs:
        text = rp.read(p)
        try:
            wf = R.load_yaml(text)
            parsed[p] = (wf, R.triggers(wf), text)
        except Exception as e:
            if re.search(r"(?i)test", text or ""):
                flags.append(f"workflow-parse:{p}:{type(e).__name__}")
    callers: dict[str, list] = {}
    for p, (wf, _, _) in parsed.items():
        jobs = wf.get("jobs") if isinstance(wf.get("jobs"), dict) else {}
        for jk, job in jobs.items():
            if isinstance(job, dict) and isinstance(job.get("uses"), str):
                u = job["uses"].split("@")[0]
                if u.startswith("./.github/workflows/"):
                    callers.setdefault(u[2:], []).append((p, str(job.get("name") if job.get("name") is not None
                                                                  else jk)))
    out: dict[str, list] = {}
    for p, (wf, trig, text) in sorted(parsed.items()):
        jobs = wf.get("jobs") if isinstance(wf.get("jobs"), dict) else {}
        for jk, job in jobs.items():
            if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
                continue
            steps = job["steps"]
            idxs = [i for i, s in enumerate(steps)
                    if isinstance(s, dict) and R.is_test_step(s, R.working_dir(s, job, wf), rp.read)]
            if not idxs:
                continue
            jname = str(job.get("name") if job.get("name") is not None else jk)
            via = []
            if "workflow_call" in trig:
                via += [(cp, cname) for cp, cname in callers.get(p, [])]
                if trig - {"workflow_call"}:
                    via.append((p, None))
                if not via:
                    flags.append(f"workflow_call-no-caller:{p}")
                    continue
            else:
                via.append((p, None))
            for run_file, caller in via:
                out.setdefault(run_file, []).append({"file": p, "job": jk, "job_name": jname, "caller": caller,
                                                     "yaml_steps": steps, "idxs": idxs})
    return out, flags


def check_ci(src, rp: Repo) -> dict:
    targets, flags = workflow_targets(rp)
    res = {"test_jobs": sum(len(v) for v in targets.values()), "flags": flags, "workflows": []}
    for run_file, tg in sorted(targets.items()):
        fname = posixpath.basename(run_file)
        qs = urllib.parse.urlencode({"created": f">={R.WINDOW_START}", "per_page": 100})
        st, d = src.get(f"repos/{rp.repo}/actions/workflows/{q(fname)}/runs?{qs}")
        w = {"file": run_file, "jobs": [t["job"] for t in tg], "inspected": 0, "result": "none"}
        res["workflows"].append(w)
        if st == 404:
            w["result"] = "no-runs"
            continue
        if st != 200:
            raise ApiError(f"runs {fname}: HTTP {st}")
        runs = (d.get("workflow_runs") or [])[:R.RUNS_CAP]
        w["total_runs"] = d.get("total_count") or 0
        unmatched = False
        for run in runs:
            jobs, page = [], 1
            while True:
                stj, dj = src.get(f"repos/{rp.repo}/actions/runs/{run['id']}/jobs?per_page=100&page={page}")
                if stj != 200:
                    raise ApiError(f"jobs {run['id']}: HTTP {stj}")
                jobs += dj.get("jobs") or []
                if len(jobs) >= (dj.get("total_count") or 0) or not dj.get("jobs"):
                    break
                page += 1
            w["inspected"] += 1
            ev = [R.run_evidence(jobs, t) for t in tg]
            if "yes" in ev:
                w.update(result="yes", run=run.get("html_url"), run_created=run.get("created_at"))
                res["ci"] = "yes"
                return res
            unmatched = unmatched or "unmatched" in ev
        if w["total_runs"] > w["inspected"]:
            w["result"] = "uncertain-more-runs"
        elif unmatched:
            w["result"] = "uncertain-step-unmatched"
    if any(w["result"].startswith("uncertain") for w in res["workflows"]) or flags:
        res["ci"] = "uncertain"
    else:
        res["ci"] = "no-ci-tests"
    return res


# ---------------------------------------------------------------------------------------------- §3.1 recordings

def check_recordings(rp: Repo, libs: dict) -> dict:
    cands = sorted(p for p in rp.files if R.recording_file(p))
    out = {"files": len(cands), "capped": len(cands) > R.RECORDING_FILE_CAP, "hits_before_history": [],
           "fetched": 0, "general_hosts": []}
    for p in cands[:R.RECORDING_FILE_CAP]:
        kind = R.recording_file(p)
        st, facts = rp.src.get(f"repos/{rp.repo}/git/blobs/{rp.files[p][0]}", kind="rec")
        if st != 200:
            raise ApiError(f"blob {p}: HTTP {st}")
        out["fetched"] += 1
        if not R.recording_hit(kind, facts):
            continue
        date, url = rp.last_commit_date(p)
        hit = {"path": p, "rule": kind, "hosts": facts["hosts"], "date": date, "commit_url": url,
               "snippet": facts.get("snippet"),
               "url": f"https://github.com/{rp.repo}/blob/{urllib.parse.quote(rp.ref)}/{q(p)}"}
        if date and date >= R.HISTORY_START:
            out["yes"] = hit
            return out
        out["hits_before_history"].append(hit)
    for rp_hit in libs.get("recording_packages") or []:
        date, url = rp.last_commit_date(rp_hit["file"])
        hit = {"path": rp_hit["file"], "rule": "package", "packages": rp_hit["packages"], "date": date,
               "commit_url": url,
               "url": f"https://github.com/{rp.repo}/blob/{urllib.parse.quote(rp.ref)}/{q(rp_hit['file'])}"}
        if date and date >= R.HISTORY_START:
            out["yes"] = hit
            return out
        out["hits_before_history"].append(hit)
    return out


# ---------------------------------------------------------------------------------------------- candidate

def run_candidate(src, cand: dict, opts: dict | None = None) -> dict:
    opts = opts or {}
    repo = cand["repo"]
    row = {"idx": cand["idx"], "repo": repo, "html_url": cand.get("html_url"), "stratum": cand.get("stratum")}
    stage = "membership"
    try:
        st, meta = src.get(f"repos/{repo}")
        if st != 200:
            row.update(cls="uncertain", stage="error", error=f"repo HTTP {st}")
            return row
        row["meta"] = meta
        ex = [] if opts.get("no_exclude") else excluded(meta, repo, opts.get("excluded_repos"))
        if ex:
            row.update(cls="excluded", excluded=ex)
            return row
        full, ref = meta.get("full_name") or repo, meta["default_branch"]
        files, truncated = list_files(src, full, ref)
        row["tree_truncated"] = truncated
        rp = Repo(src, full, ref, files)
        libs = check_libraries(rp, opts)
        row["libs"] = libs
        if not libs["libraries"]:
            if libs["errors"] or libs["capped"] or truncated:
                row.update(cls="uncertain", stage="agent-lib",
                           why=["manifest-error"] * bool(libs["errors"]) + ["manifests-capped"] * libs["capped"]
                           + ["tree-truncated"] * truncated)
            else:
                row.update(cls="non-member", stage="no-agent-lib")
            return row
        ci = check_ci(src, rp)
        row["ci"] = ci
        if ci["ci"] == "no-ci-tests":
            row.update(cls="non-member", stage="no-ci-tests")
            return row
        if ci["ci"] == "uncertain":
            row.update(cls="uncertain", stage="ci-tests", why=sorted({w["result"] for w in ci["workflows"]
                                                                      if w["result"].startswith("uncertain")})
                       + ci["flags"])
            return row
        row.update(cls="member", stage="member")
        stage = "pain"
        row["pain_flags"] = ["tree-truncated"] if truncated else []
        rec = check_recordings(rp, libs)
        row["recordings"] = rec
        if rec["capped"]:
            row["pain_flags"] = sorted(row["pain_flags"] + ["recording-capped"])
        return row
    except CapReached:
        if stage == "membership":
            row.update(cls="uncertain", stage="request-cap")
        else:
            row["pain_flags"] = sorted(set((row.get("pain_flags") or []) + ["request-cap"]))
        return row
    except ApiError as e:
        if stage == "membership":
            row.update(cls="uncertain", stage="error", error=str(e)[:200])
        else:
            row["pain_flags"] = sorted(set((row.get("pain_flags") or []) + ["api-error"]))
            row["pain_error"] = str(e)[:200]
        return row
    finally:
        row["core_requests"] = src.core
