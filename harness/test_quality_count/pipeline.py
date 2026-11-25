"""Per-candidate §2-§4.3 pipeline over a request source (live REST in the workflow, or replay of committed raw JSON).

``run_candidate(src, cand, opts)`` makes every request through ``src.get(path[, search])`` and returns one row. The live
source records each (trimmed) response under its path; the replay source serves them back, so ``verify.py`` re-derives
every row from the committed raw responses (``Missing`` if a response is absent).
"""
from __future__ import annotations

import base64
import json
import posixpath
import re
import urllib.parse

import history
import rules as R

OWNERS_EXCLUDED = {"mircoguidetti", "stryker-mutator", "boxed", "sixty-north", "hcoles", "pitest", "arcmutate", "szpak",
                   "sourcefrog", "infection", "mbj", "mull-project", "muter-mutation-testing", "go-gremlins", "zimmski"}
RUNS_CAP = 50
VALUES = 10
PAIN_MIN = 30.0
TREE_KEEP = re.compile(
    r"(^|/)(package\.json|GNUmakefile|makefile|Makefile|composer\.json|justfile|Justfile|\.justfile|JUSTFILE|"
    r"[Tt]askfile(\.dist)?\.ya?ml|Rakefile|rakefile|Rakefile\.rb|Gemfile|tox\.ini|noxfile\.py|pom\.xml|"
    r"build\.gradle(\.kts)?|setup\.cfg|pyproject\.toml|cosmic-ray\.toml|mutants\.toml|\.mutant\.yml|mutant\.yml|"
    r"stryker-config\.json|stryker\.conf[^/]*|stryker\.config[^/]*|infection\.json[^/]*|action\.ya?ml)$"
    r"|\.(sh|rake|gemspec)$|^\.github/workflows/[^/]+$")
TOOL_FILE_RE = re.compile(r"(^|/)(stryker\.conf[^/]*|stryker\.config[^/]*|stryker-config\.json|infection\.json[^/]*|"
                          r"\.cargo/mutants\.toml|cosmic-ray\.toml|\.mutant\.yml|config/mutant\.yml|setup\.cfg|"
                          r"pyproject\.toml|pom\.xml|build\.gradle(\.kts)?|composer\.json|package\.json)$")
QUERY_TERM = {"stryker": "stryker", "mutmut": "mutmut", "cosmic-ray": "cosmic-ray", "pitest": "pitest",
              "cargo-mutants": "cargo-mutants", "infection": "infection", "mutant": "mutant",
              "go-mutesting": "go-mutesting", "gremlins": "gremlins", "mull": "mull", "muter": "muter",
              "mutatest": "mutatest"}


class Missing(Exception):
    pass


class ApiError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- trimming

def _b64(d: dict):
    if d.get("encoding") == "base64" and d.get("content") is not None:
        return base64.b64decode(d["content"]).decode("utf-8", errors="replace")
    return None


def _patch_kept(name: str, patch: str | None = None) -> bool:
    if name.startswith(".github/workflows/") or TREE_KEEP.search(name) or R.is_config_path(name):
        return True
    return bool(patch) and R.patch_touches(patch, False)


def trim(path: str, d):
    p = path.split("?", 1)[0]
    if p.startswith("search/issues") and isinstance(d, dict):
        return {"total_count": d.get("total_count"), "incomplete_results": d.get("incomplete_results"), "items": [
            {"number": x.get("number"), "title": x.get("title"), "body": (x.get("body") or "")[:6000],
             "html_url": x.get("html_url"), "created_at": x.get("created_at"), "state": x.get("state"),
             "pull_request": bool(x.get("pull_request"))} for x in d.get("items", [])]}
    if isinstance(d, dict) and p.count("/") == 2 and p.startswith("repos/"):
        return {k: d.get(k) for k in ("full_name", "fork", "archived", "pushed_at", "default_branch", "private",
                                      "stargazers_count", "language", "html_url")} | \
            {"owner": d["owner"].get("login") if isinstance(d.get("owner"), dict) else d.get("owner")}
    if "/git/trees/" in p and isinstance(d, dict):
        return {"truncated": d.get("truncated"), "n_entries": len(d.get("tree") or []),
                "paths": sorted(x["path"] for x in d.get("tree") or [] if x.get("type") == "blob"
                                and TREE_KEEP.search(x.get("path") or ""))}
    if "/contents/" in p:
        if isinstance(d, list):
            return [{"name": x.get("name"), "path": x.get("path"), "type": x.get("type")} for x in d]
        if isinstance(d, dict):
            return {"type": d.get("type"), "path": d.get("path"), "size": d.get("size"), "text": _b64(d)}
    if p.endswith("/runs") and isinstance(d, dict):
        return {"total_count": d.get("total_count"), "workflow_runs": [
            {"id": r["id"], "event": r.get("event"), "created_at": r.get("created_at"), "status": r.get("status"),
             "head_branch": r.get("head_branch"), "conclusion": r.get("conclusion"), "html_url": r.get("html_url"),
             "path": r.get("path"), "run_attempt": r.get("run_attempt")} for r in d.get("workflow_runs", [])]}
    if p.endswith("/jobs") and isinstance(d, dict):
        # gate note 1: job-level started_at / completed_at / status kept
        return {"total_count": d.get("total_count"), "jobs": [
            {"id": j["id"], "name": j.get("name"), "status": j.get("status"), "conclusion": j.get("conclusion"),
             "started_at": j.get("started_at"), "completed_at": j.get("completed_at"), "html_url": j.get("html_url"),
             "steps": [{"name": s.get("name"), "number": s.get("number"), "conclusion": s.get("conclusion"),
                        "started_at": s.get("started_at"), "completed_at": s.get("completed_at")}
                       for s in j.get("steps") or []]} for j in d.get("jobs", [])]}
    if p.endswith("/pulls") and "/commits/" in p and isinstance(d, list):
        return [{"number": x.get("number"), "title": x.get("title"), "body": (x.get("body") or "")[:6000],
                 "html_url": x.get("html_url"), "merged_at": x.get("merged_at"), "created_at": x.get("created_at")}
                for x in d]
    if re.search(r"/commits/[0-9a-f]{7,40}$", p) and isinstance(d, dict):
        c = d.get("commit") or {}
        return {"sha": d.get("sha"), "message": (c.get("message") or "")[:6000],
                "date": ((c.get("committer") or {}).get("date") or (c.get("author") or {}).get("date")),
                "parents": [x.get("sha") for x in d.get("parents") or []], "html_url": d.get("html_url"),
                "files": [{"filename": f.get("filename"), "status": f.get("status"),
                           "previous_filename": f.get("previous_filename"),
                           "patch": (f.get("patch")[:30000] if f.get("patch") is not None else None)
                           if _patch_kept(f.get("filename") or "", f.get("patch")) else None,
                           "has_patch": f.get("patch") is not None}
                          for f in d.get("files") or []]}
    if p.endswith("/commits") and isinstance(d, list):
        return [{"sha": x.get("sha"), "date": ((x.get("commit") or {}).get("committer") or {}).get("date"),
                 "message": ((x.get("commit") or {}).get("message") or "")[:2000]} for x in d]
    return d


class LiveSource:
    def __init__(self, client):
        self.c = client
        self.responses: dict[str, dict] = {}

    def get(self, path: str, search: str | None = None):
        if path in self.responses:
            r = self.responses[path]
            return r["status"], r.get("data")
        st, data, _ = self.c.get(path, search=search)
        if st not in (200, 404, 409, 422):
            st, data, _ = self.c.get(path, search=search)  # one retry
        rec = {"status": st, "data": trim(path, data) if st == 200 else
               {"message": (data or {}).get("message") if isinstance(data, dict) else str(data)[:200]}}
        if search:
            rec["search"] = search
        self.responses[path] = rec
        return rec["status"], rec["data"]


class ReplaySource:
    def __init__(self, responses: dict):
        self.responses = responses

    def get(self, path: str, search: str | None = None):
        if path not in self.responses:
            raise Missing(path)
        r = self.responses[path]
        return r["status"], r.get("data")


class Counting:
    """Counts first-time paths (a cached path is not a request); raises Capped at the cap."""

    class Capped(Exception):
        pass

    def __init__(self, src, cap: int):
        self.src, self.cap, self.n, self.seen = src, cap, 0, set()

    def get(self, path: str, search: str | None = None):
        if path not in self.seen:
            if self.n >= self.cap:
                raise Counting.Capped(path)
            self.seen.add(path)
            self.n += 1
        return self.src.get(path, search) if search else self.src.get(path)


# ---------------------------------------------------------------------------------------------- repository files

class Repo:
    def __init__(self, src, repo: str, ref: str, tree_paths: set | None):
        self.src, self.repo, self.ref, self.tree = src, repo, ref, tree_paths
        self.listings: dict[str, list | None] = {}

    def _contents(self, path: str, ref: str | None = None):
        q = urllib.parse.quote(path) if path else ""
        st, d = self.src.get(f"repos/{self.repo}/contents/{q}?ref={urllib.parse.quote(ref or self.ref)}")
        if st == 404:
            return None
        if st != 200:
            raise ApiError(f"contents {path}: HTTP {st}")
        return d

    def listdir(self, d: str):
        d = d or ""
        if self.tree is not None:
            pre = d + "/" if d else ""
            names = {p[len(pre):].split("/", 1)[0] for p in self.tree if p.startswith(pre)}
            return sorted(names) if names or d == "" else None
        if d not in self.listings:
            x = self._contents(d)
            self.listings[d] = [e["name"] for e in x] if isinstance(x, list) else None
        return self.listings[d]

    def read(self, path: str):
        if not path:
            return None
        path = posixpath.normpath(path)
        if path.startswith("..") or path.startswith("/"):
            return None
        if self.tree is not None:
            if path not in self.tree and TREE_KEEP.search(path):
                return None
            # a path the trimmed tree does not keep (e.g. an extensionless script) is fetched directly: 404 = absent
        else:
            names = self.listdir(posixpath.dirname(path))
            if names is None or posixpath.basename(path) not in names:
                return None
        x = self._contents(path)
        if not isinstance(x, dict) or x.get("type") != "file":
            return None
        if x.get("text") is None:
            raise ApiError(f"contents {path}: no text (size {x.get('size')})")
        return x["text"]


# ---------------------------------------------------------------------------------------------- §2.8 / §3 runs

def inspect_runs(src, repo: str, run_file: str, targets: list[dict], schedule_only: bool) -> None:
    """Fill each target {job_name, caller, yaml_steps, mut_idx, timeout} with runs evidence and values."""
    for t in targets:
        t.update(inspected=0, evidence=None, values=[], more=False, total_runs=None, jobs_truncated=False)
    q = {"created": f">={R.WINDOW_START}", "per_page": 100}
    if schedule_only:
        q["event"] = "schedule"
    fname = posixpath.basename(run_file)
    st, d = src.get(f"repos/{repo}/actions/workflows/{urllib.parse.quote(fname)}/runs?{urllib.parse.urlencode(q)}")
    if st != 200:
        raise ApiError(f"runs {fname}: HTTP {st}")
    runs = d.get("workflow_runs") or []
    total = d.get("total_count") or len(runs)
    n = 0
    for run in runs[:RUNS_CAP]:
        if all(t["evidence"] and len(t["values"]) >= VALUES for t in targets):
            break
        n += 1
        jobs, jp = [], 1
        while True:
            stj, dj = src.get(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100&page={jp}")
            if stj != 200:
                raise ApiError(f"jobs {run['id']}: HTTP {stj}")
            jobs += dj.get("jobs") or []
            if len(jobs) >= (dj.get("total_count") or 0) or not dj.get("jobs"):
                break
            if jp >= 5:
                for t in targets:
                    t["jobs_truncated"] = True
                break
            jp += 1
        for t in targets:
            if t["evidence"] and len(t["values"]) >= VALUES:
                continue
            t["inspected"] += 1
            legs = []
            for j in jobs:
                if not R.job_matches(j.get("name") or "", t["job_name"], t.get("caller")):
                    continue
                api_steps = [R.pick_api_step(j.get("steps") or [], t["yaml_steps"], i) for i in t["mut_idx"]]
                ev = R.leg_eval(j, api_steps, t["timeout"])
                ev["job_url"] = j.get("html_url")
                legs.append(ev)
            if any(x["evidence"] for x in legs) and t["evidence"] is None:
                t["evidence"] = {"run": run["id"], "created_at": run.get("created_at"),
                                 "job_url": next(x["job_url"] for x in legs if x["evidence"])}
            vals = [x for x in legs if x["value_s"] is not None]
            if vals and len(t["values"]) < VALUES:
                best = max(vals, key=lambda x: x["value_s"])
                t["values"].append({"run": run["id"], "created_at": run.get("created_at"),
                                    "value_s": best["value_s"], "lower_bound": best["lower_bound"],
                                    "legs": len(vals), "machine_s": sum(x["value_s"] for x in vals),
                                    "step_s": sum(x["step_s"] for x in vals), "job_url": best["job_url"]})
    for t in targets:
        t["total_runs"] = total
        t["more"] = total > t["inspected"]
        if t["evidence"]:
            t["status"] = "running"
        elif (t["inspected"] >= RUNS_CAP and t["more"]) or t.get("jobs_truncated"):
            t["status"] = "uncertain"
        else:
            t["status"] = "configured-not-running"


# ---------------------------------------------------------------------------------------------- candidate

def caller_chains(p: str, callers: dict, parsed: dict, depth: int = 0, seen: frozenset = frozenset()) -> list:
    """Every caller chain of a called workflow up to a workflow that is not only `workflow_call`:
    [(root file, [caller job names from the root down], events reaching it, if-complex flag)]; None = unsupported."""
    out = []
    if depth > 4:
        return [None]
    for cp, cjk, cjob in callers.get(p, []):
        if cp in seen:
            continue
        try:
            cev = R.events(parsed[cp])
        except R.OnError:
            out.append(None)
            continue
        own = cev - {"workflow_call"}
        fev, cx = R.if_filter(cjob.get("if"), own)
        if own:
            out.append((cp, [_named(cjob, cjk)], fev, cx))
        if "workflow_call" in cev:
            for up in caller_chains(cp, callers, parsed, depth + 1, seen | {p}):
                if up is None:
                    out.append(None)
                    continue
                root, names, uev, ux = up
                fev2, cx2 = R.if_filter(cjob.get("if"), uev)
                out.append((root, names + [_named(cjob, cjk)], fev2, ux or cx2))
    return out


def _named(job: dict, jk) -> str:
    return str(job.get("name") if job.get("name") is not None else jk)


def run_candidate(src, cand: dict, opts: dict | None = None) -> dict:
    opts = opts or {}
    repo = cand["repo"]
    row = {"idx": cand["idx"], "repo": repo, "html_url": cand.get("html_url"), "hit_terms": cand.get("terms"),
           "hit_files": cand.get("files")}
    st, meta = src.get(f"repos/{repo}")
    if st != 200:
        row.update(cls="uncertain", mclass="error", error=f"repo HTTP {st}")
        return row
    row["meta"] = meta
    owner = (meta.get("owner") or "").lower()
    excl = []
    if meta.get("fork"):
        excl.append("fork")
    if meta.get("archived"):
        excl.append("archived")
    if (meta.get("pushed_at") or "") < R.WINDOW_START:
        excl.append("stale")
    if owner in OWNERS_EXCLUDED:
        excl.append("maintainer")
    if excl and not opts.get("no_exclude"):
        row.update(cls="excluded", excluded=excl)
        if excl != ["maintainer"]:
            return row  # maintainer repositories are still read (information, not counted)
    full = meta.get("full_name") or repo
    branch = meta["default_branch"]
    try:
        analyze(src, full, branch, row, cand)
    except ApiError as e:
        row.update(mclass="error", error=str(e))
        row.setdefault("errors", []).append(str(e))
        _set_cls(row, "uncertain")
        return row
    if row.get("cls") == "running" and not (row.get("duration") or {}).get("pain") and not opts.get("no_history"):
        row["history"] = history.run_history(src, full, row, cap=300)
        if opts.get("issues_route") == "workflow":
            left = 300 - row["history"]["requests"]
            row["issues"] = history.run_issues(src, full, row_tools(row), left)
    return row


def _set_cls(row: dict, cls: str) -> None:
    if row.get("cls") == "excluded":
        row["cls_if_counted"] = cls
    else:
        row["cls"] = cls


def analyze(src, repo: str, branch: str, row: dict, cand: dict) -> None:
    st, tr = src.get(f"repos/{repo}/git/trees/{urllib.parse.quote(branch)}?recursive=1")
    tree = None
    if st == 200 and not tr.get("truncated"):
        tree = set(tr.get("paths") or [])
    elif st not in (200, 404, 409):
        raise ApiError(f"tree: HTTP {st}")
    row["tree_unavailable"] = None if tree is not None else ("truncated" if st == 200 else f"http-{st}")
    rp = Repo(src, repo, branch, tree)
    ctx = R.Ctx(rp.read, sorted(tree) if tree is not None else None, cand.get("files") or [])
    if tree is None:  # gate note 4: contents fallback for the root files
        names = rp.listdir("") or []
        ctx.paths = sorted(n for n in names if TREE_KEEP.search(n))
    resolver = R.Resolver(ctx)
    wf_names = [n for n in (rp.listdir(".github/workflows") or []) if n.endswith((".yml", ".yaml"))]
    wf_files = [f".github/workflows/{n}" for n in sorted(wf_names)]
    row["workflow_files"] = wf_files
    row["tool_files"] = sorted(p for p in (ctx.paths or []) if TOOL_FILE_RE.search(p))
    parsed, errors, term_hits = {}, [], []
    for p in wf_files:
        text = rp.read(p)
        if text is None:
            continue
        try:
            parsed[p] = R.load_yaml(text)
        except Exception as e:  # YAML error
            if R.YAML_ERROR_TERM_RE.search(text):
                errors.append(f"yaml {p}: {str(e)[:120]}")
            if R.has_term(text, ctx):
                term_hits.append({"file": p, "kind": "workflow-file", "name": p})
    callers: dict[str, list] = {}
    for p, wf in parsed.items():
        jobs = wf.get("jobs") if isinstance(wf.get("jobs"), dict) else {}
        for jk, job in jobs.items():
            if isinstance(job, dict) and isinstance(job.get("uses"), str):
                u = job["uses"].split("@")[0]
                if u.startswith("./.github/workflows/"):
                    callers.setdefault(u[2:], []).append((p, jk, job))
    jobs_out, unresolved, uses_actions, flags = [], [], [], []
    for p, wf in sorted(parsed.items()):
        try:
            evs = R.events(wf)
            on_ok = True
        except R.OnError as e:
            evs, on_ok = set(), False
            flags.append(f"on-unparsed {p}: {e}")
        jobs = wf.get("jobs") if isinstance(wf.get("jobs"), dict) else {}
        for jk, job in jobs.items():
            if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
                continue
            jname = _named(job, jk)
            a = R.analyze_job(job, wf, ctx, resolver)
            job_term = R.has_term(str(jk), ctx, name=True) or R.has_term(jname, ctx, name=True)
            if job_term:
                term_hits.append({"file": p, "job": str(jk), "kind": "job-name", "name": jname})
            for i, stp in enumerate(job["steps"]):
                if isinstance(stp, dict) and R.has_term(str(stp.get("name") or ""), ctx, name=True):
                    term_hits.append({"file": p, "job": str(jk), "kind": "step-name", "name": str(stp["name"]),
                                      "step": i})
            for h in a["term_hits"]:
                term_hits.append({"file": p, "job": str(jk), **h})
            for u in a["unresolved"]:
                counted = R.has_term(u["name"], ctx, name=True) or job_term or \
                    R.has_term(u.get("step_name"), ctx, name=True)
                unresolved.append({"file": p, "job": str(jk), **u, "counted": counted})
            uses_actions += [{"file": p, "job": str(jk), "uses": x} for x in a["uses_actions"]]
            if not a["mutation_steps"]:
                continue
            jr = {"file": p, "job": str(jk), "name": jname, "steps": a["mutation_steps"],
                  "tools": sorted({m["tool"] for s in a["mutation_steps"] for m in s["mutations"]}),
                  "wrapped": any(s.get("wrapped") for s in a["mutation_steps"]), "targets": [], "flags": []}
            routes = []
            if not on_ok:
                jr.update(status="unsupported", why="on: does not parse")
                jobs_out.append(jr)
                continue
            if "workflow_call" in evs:
                chains = caller_chains(p, callers, parsed)
                if any(ch is None for ch in chains):
                    jr.update(status="unsupported", why="reusable workflow chain deeper than 4 or a caller "
                                                        "whose on: does not parse")
                    jobs_out.append(jr)
                    continue
                for root, names, cev, cx in chains:
                    cev, jx = R.if_filter(job.get("if"), cev)
                    if cx or jx:
                        jr["flags"].append("if-complex")
                    routes.append((root, " / ".join(names), cev))
                own = evs - {"workflow_call"}
                if own:
                    oev, jx = R.if_filter(job.get("if"), own)
                    if jx:
                        jr["flags"].append("if-complex")
                    routes.append((p, None, oev))
                if not routes:
                    jr.update(status="unsupported", why="workflow_call without a caller in this repository")
                    jobs_out.append(jr)
                    continue
            else:
                jev, jx = R.if_filter(job.get("if"), evs)
                if jx:
                    jr["flags"].append("if-complex")
                routes.append((p, None, jev))
            allev = set().union(*[r[2] for r in routes]) if routes else set()
            jr["events"] = sorted(allev)
            jr["freq"] = R.frequency(allev)
            mut_idx = [s["index"] for s in a["mutation_steps"]]
            timeout = a["mutation_steps"][0]["timeout"]
            for run_file, caller, rev in routes:
                if not rev:
                    continue
                t = {"run_file": run_file, "caller": caller, "job_name": jname, "yaml_steps": job["steps"],
                     "mut_idx": mut_idx, "timeout": timeout, "freq": R.frequency(rev),
                     "schedule_only": rev == {"schedule"}}
                try:
                    inspect_runs(src, repo, run_file, [t], t["schedule_only"])
                except ApiError as e:
                    t.update(status="error", error=str(e))
                jr["targets"].append(t)
            sts = [t["status"] for t in jr["targets"]]
            jr["status"] = "running" if "running" in sts else ("uncertain" if any(s in ("uncertain", "error")
                                                                                 for s in sts)
                                                              else "configured-not-running")
            jobs_out.append(jr)
    for jr in jobs_out:
        for t in jr["targets"]:
            t.pop("yaml_steps", None)
    # tool terms linked to a mutation job are not `tool-present-unlinked` items (gate note 2): file-level terms are
    # checked on the workflow without its mutation jobs; job/step/script terms of a mutation job are dropped
    mut_jobs = {(j["file"], j["job"]) for j in jobs_out}
    term_hits = [h for h in term_hits if (h.get("file"), h.get("job")) not in mut_jobs]
    for p, wf in sorted(parsed.items()):
        rest = {k: v for k, v in wf.items() if k != "jobs"}
        jobs = wf.get("jobs") if isinstance(wf.get("jobs"), dict) else {}
        rest["jobs"] = {k: v for k, v in jobs.items() if (p, str(k)) not in mut_jobs}
        if R.has_term(json.dumps(rest, default=str), ctx):
            term_hits.append({"file": p, "kind": "workflow-file", "name": p})
    row.update(jobs=jobs_out, unresolved=unresolved, term_hits=term_hits, uses_actions=uses_actions,
               errors=errors, flags=flags)
    counted = [u for u in unresolved if u["counted"]]
    if jobs_out:
        row["mclass"] = "has-mutation-job"
        sts = [j["status"] for j in jobs_out]
        if "running" in sts:
            status = "running"
        elif any(s in ("uncertain", "unsupported") for s in sts) or errors or counted or term_hits:
            status = "uncertain"
        else:
            status = "configured-not-running"
    elif errors:
        row["mclass"], status = "error", "uncertain"
    elif counted:
        row["mclass"], status = "unresolved", "uncertain"
    elif term_hits:
        row["mclass"], status = "tool-present-unlinked", "uncertain"
    else:
        row["mclass"], status = "no-mutation", "not-running"
    row["status"] = status
    _set_cls(row, {"running": "running", "uncertain": "uncertain"}.get(status, "not-running"))
    if status == "running":
        row["duration"] = duration(jobs_out)


def duration(jobs: list[dict]) -> dict:
    meds, too_few, cap_few = [], False, False
    other_uncertain = any(j.get("status") in ("uncertain", "unsupported") or
                          any(t.get("status") in ("uncertain", "error") for t in j.get("targets") or [])
                          for j in jobs)
    for j in jobs:
        if j.get("status") != "running":
            continue
        for t in j["targets"]:
            if t.get("status") != "running":
                continue
            vals = [v["value_s"] / 60 for v in t["values"]]
            med = R.median_upto10(vals)
            t["median_min"] = med
            if med is None:
                too_few = True
                if t["inspected"] >= RUNS_CAP:
                    cap_few = True
            else:
                meds.append({"file": j["file"], "job": j["job"], "run_file": t["run_file"], "median_min": med,
                             "machine_min": R.median_upto10([v["machine_s"] / 60 for v in t["values"]]),
                             "step_min": R.median_upto10([v["step_s"] / 60 for v in t["values"]]),
                             "n": len(vals), "freq": t["freq"], "tools": j["tools"], "wrapped": j["wrapped"]})
    best = max(meds, key=lambda m: m["median_min"]) if meds else None
    return {"max_median_min": best["median_min"] if best else None, "best": best, "medians": meds,
            "pain": bool(best and best["median_min"] >= PAIN_MIN), "too_few_runs": too_few, "runs_cap_few": cap_few,
            "other_uncertain": other_uncertain}


def row_tools(row: dict) -> list[str]:
    tools = set()
    for j in row.get("jobs") or []:
        for s in j["steps"]:
            for m in s["mutations"]:
                if m["tool"] in QUERY_TERM:
                    tools.add(m["tool"])
                elif m["tool"] == "uses-action":
                    for k in ("stryker", "mutmut", "pitest", "cargo-mutants", "infection"):
                        if k in m["cmd"].lower():
                            tools.add(k)
    return sorted(tools)


def script_paths(row: dict) -> list[str]:
    out = set()
    for j in row.get("jobs") or []:
        for s in j["steps"]:
            for m in s["mutations"]:
                out |= set(R.via_paths(m.get("via") or []))
    return sorted(p for p in out if not p.startswith(".github/workflows/"))
