"""Per-candidate §2-§3 pipeline over a request source (live REST in the workflow, or replay of committed raw JSON).

``run_candidate(src, cand)`` makes every request through ``src.get(path)`` and returns one row. The live source
records each response (trimmed) under its path; the replay source serves them back, so a row can be re-derived from
the committed raw JSON (``Missing`` if a response is absent).
"""
from __future__ import annotations

import base64
import posixpath
import urllib.parse

import rules as R

WINDOW_START = "2026-08-26"
OWNERS_EXCLUDED = {"github", "microsoft", "anthropics", "openai", "mircoguidetti"}
MAX_RUN_PAGES = 30

STAGES = ["no_db_job", "no_test_step", "not_serial", "too_few_runs", "below_10", "ge_10"]
UNCERTAIN = {"unresolved", "unsupported", "error"}


class Missing(Exception):
    pass


class ApiError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- trimming

def trim(path: str, d):
    p = path.split("?", 1)[0]
    if isinstance(d, dict) and p.count("/") == 2 and p.startswith("repos/"):
        return {k: d.get(k) for k in ("full_name", "fork", "archived", "pushed_at", "default_branch", "private",
                                      "stargazers_count", "language", "html_url")} | \
            {"owner": (d.get("owner") or {}).get("login")}
    if "/contents/" in p:
        if isinstance(d, list):
            return [{"name": x.get("name"), "path": x.get("path"), "type": x.get("type")} for x in d]
        if isinstance(d, dict):
            txt = None
            if d.get("encoding") == "base64" and d.get("content") is not None:
                txt = base64.b64decode(d["content"]).decode("utf-8", errors="replace")
            return {"type": d.get("type"), "path": d.get("path"), "size": d.get("size"), "text": txt}
    if p.endswith("/runs") and isinstance(d, dict):
        return {"total_count": d.get("total_count"), "workflow_runs": [
            {"id": r["id"], "event": r.get("event"), "created_at": r.get("created_at"),
             "head_branch": r.get("head_branch"), "conclusion": r.get("conclusion"), "html_url": r.get("html_url"),
             "path": r.get("path")} for r in d.get("workflow_runs", [])]}
    if p.endswith("/jobs") and isinstance(d, dict):
        return {"total_count": d.get("total_count"), "jobs": [
            {"id": j["id"], "name": j.get("name"), "conclusion": j.get("conclusion"), "html_url": j.get("html_url"),
             "steps": [{"name": s.get("name"), "number": s.get("number"), "conclusion": s.get("conclusion"),
                        "started_at": s.get("started_at"), "completed_at": s.get("completed_at")}
                       for s in j.get("steps") or []]} for j in d.get("jobs", [])]}
    return d


class LiveSource:
    def __init__(self, client):
        self.c = client
        self.responses: dict[str, dict] = {}

    def get(self, path: str):
        if path in self.responses:
            r = self.responses[path]
            return r["status"], r.get("data")
        st, data, _ = self.c.get(path)
        if st not in (200, 404) :
            st, data, _ = self.c.get(path)  # one retry
        rec = {"status": st, "data": trim(path, data) if st == 200 else
               {"message": (data or {}).get("message") if isinstance(data, dict) else str(data)[:200]}}
        self.responses[path] = rec
        return rec["status"], rec["data"]


class ReplaySource:
    def __init__(self, responses: dict):
        self.responses = responses

    def get(self, path: str):
        if path not in self.responses:
            raise Missing(path)
        r = self.responses[path]
        return r["status"], r.get("data")


# ---------------------------------------------------------------------------------------------- repository files

class Repo:
    def __init__(self, src, repo: str, ref: str):
        self.src, self.repo, self.ref = src, repo, ref
        self.listings: dict[str, list | None] = {}

    def _contents(self, path: str):
        q = urllib.parse.quote(path) if path else ""
        st, d = self.src.get(f"repos/{self.repo}/contents/{q}?ref={urllib.parse.quote(self.ref)}")
        if st == 404:
            return None
        if st != 200:
            raise ApiError(f"contents {path}: HTTP {st}")
        return d

    def listdir(self, d: str):
        d = d or ""
        if d not in self.listings:
            x = self._contents(d)
            self.listings[d] = [e["name"] for e in x] if isinstance(x, list) else None
        return self.listings[d]

    def read(self, path: str):
        if path is None or path == "":
            return None
        path = posixpath.normpath(path)
        if path.startswith("..") or path.startswith("/"):
            return None
        names = self.listdir(posixpath.dirname(path))
        if names is None or posixpath.basename(path) not in names:
            return None
        x = self._contents(path)
        if not isinstance(x, dict) or x.get("type") != "file":
            return None
        if x.get("text") is None:
            raise ApiError(f"contents {path}: no text (size {x.get('size')})")
        return x["text"]


# ---------------------------------------------------------------------------------------------- §2

def test_steps(job: dict, wf: dict, repo: Repo, wf_path: str, wf_text: str) -> list[dict]:
    """Candidate test steps of a job with their serial evaluation."""
    out = []
    steps = job.get("steps") or []
    for i, st in enumerate(steps):
        if not isinstance(st, dict) or st.get("run") is None:
            continue
        cmds = [c for c in R.kept_commands(str(st["run"])) if R.is_runner_command(c)]
        if not cmds:
            continue
        wd = R.working_dir(st, job, wf)
        rec = {"index": i, "key": list(R.step_key(st)), "wd": wd, "commands": cmds}
        env = R.merged_env(wf, job, st)
        if wd is None:
            rec["status"] = "unresolved"
            rec["why"] = "working-directory is an expression"
            out.append(rec)
            continue
        try:
            lines = []
            for c in cmds:
                lines += R.resolve_command(c, wd, repo.read, wf_path, wf_text)
        except R.Unresolved as e:
            rec.update(status="unresolved", why=str(e))
            out.append(rec)
            continue
        if not lines:
            continue  # resolves to no runner command: not a test step (gate note 7)
        checks = [R.serial_check(ln, env, repo.read, repo.listdir, wf_path, wf_text) for ln in lines]
        rec["checks"] = checks
        ser = [c for c in checks if c["serial"]]
        rec["status"] = "serial" if ser else "not_serial"
        if ser:
            order = {R.DECLARED: 0, R.EXPLICIT: 1, R.DEFAULT: 2}
            best = sorted(ser, key=lambda c: order[c["reason"]])[0]
            rec.update(reason=best["reason"], kind=best["kind"], evidence=best["evidence"])
        else:
            rec["kind"] = checks[0]["kind"]
        rec["wrapped"] = any(any(v.split(":")[0] in ("tox", "nox", "make") for v in c["via"]) for c in checks) or \
            _pre_post(repo, wd, checks)
        out.append(rec)
    return out


def _pre_post(repo: Repo, wd: str, checks: list[dict]) -> bool:
    names = {v.split(":", 1)[1] for c in checks for v in c["via"] if v.split(":")[0] in ("npm", "yarn", "pnpm")}
    if not names:
        return False
    import json
    pj = repo.read(R.jpath(wd, "package.json"))
    try:
        scripts = json.loads(pj or "{}").get("scripts") or {}
    except Exception:
        return False
    return any(f"pre{n}" in scripts or f"post{n}" in scripts for n in names)


def sharded(job: dict, steps: list[dict]) -> bool:
    m = ((job.get("strategy") or {}).get("matrix")) or {}
    if isinstance(m, dict) and any(k in ("shard", "group", "split") for k in m):
        return True
    return any("--shard" in c or "--splits" in c for s in steps for c in s.get("commands", []))


# ---------------------------------------------------------------------------------------------- §3

def time_file(src, repo: str, branch: str, run_file: str, targets: list[dict]) -> None:
    """Fill ``values`` for every target {job_name, caller, yaml_steps, idx} from the runs of ``run_file``."""
    for t in targets:
        t["values"], t["runs_seen"], t["run_ids"] = [], 0, []
    page = 1
    fname = posixpath.basename(run_file)
    while page <= MAX_RUN_PAGES and any(len(t["values"]) < 10 for t in targets):
        q = urllib.parse.urlencode({"branch": branch, "status": "success", "created": f">={WINDOW_START}",
                                    "per_page": 100, "page": page})
        st, d = src.get(f"repos/{repo}/actions/workflows/{urllib.parse.quote(fname)}/runs?{q}")
        if st != 200:
            raise ApiError(f"runs {fname}: HTTP {st}")
        runs = d.get("workflow_runs") or []
        for run in runs:
            if not any(len(t["values"]) < 10 for t in targets):
                break
            if str(run.get("event") or "").startswith("pull_request"):
                continue
            jobs = []
            jp = 1
            while True:
                stj, dj = src.get(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100&page={jp}")
                if stj != 200:
                    raise ApiError(f"jobs {run['id']}: HTTP {stj}")
                jobs += dj.get("jobs") or []
                if len(jobs) >= (dj.get("total_count") or 0) or not dj.get("jobs"):
                    break
                jp += 1
            for t in targets:
                if len(t["values"]) >= 10:
                    continue
                t["runs_seen"] += 1
                best = None
                for j in jobs:
                    if j.get("conclusion") != "success":
                        continue
                    if not R.job_matches(j.get("name") or "", t["job_name"], t.get("caller")):
                        continue
                    sec = R.step_seconds(R.pick_api_step(j.get("steps") or [], t["yaml_steps"], t["idx"]))
                    if sec is not None and (best is None or sec > best[0]):
                        best = (sec, j.get("html_url"))
                if best is not None:
                    t["values"].append(best[0])
                    t["run_ids"].append({"run": run["id"], "created_at": run.get("created_at"), "job": best[1]})
        if len(runs) < 100:
            break
        page += 1


# ---------------------------------------------------------------------------------------------- candidate

def _fetch_workflows(rp: Repo):
    names = rp.listdir(".github/workflows")
    files = []
    for n in sorted(names or []):
        if n.endswith((".yml", ".yaml")):
            p = f".github/workflows/{n}"
            files.append((p, rp.read(p)))
    return files


def run_candidate(src, cand: dict) -> dict:
    repo = cand["repo"]
    row = {"idx": cand["idx"], "repo": repo, "html_url": cand["html_url"], "pairs_found": cand.get("pairs")}
    st, meta = src.get(f"repos/{repo}")
    if st != 200:
        row.update(cls="uncertain", stage="error", error=f"repo HTTP {st}")
        return row
    owner = (meta.get("owner") or "").lower()
    row["meta"] = meta
    excl = []
    if meta.get("fork"):
        excl.append("fork")
    if meta.get("archived"):
        excl.append("archived")
    if owner in OWNERS_EXCLUDED:
        excl.append("owner")
    if (meta.get("pushed_at") or "") < WINDOW_START:
        excl.append("stale")
    if excl:
        row.update(cls="excluded", excluded=excl)
        return row
    branch = meta["default_branch"]
    rp = Repo(src, meta.get("full_name") or repo, branch)
    try:
        files = _fetch_workflows(rp)
    except ApiError as e:
        row.update(cls="uncertain", stage="error", error=str(e))
        return row
    parsed, errors = {}, []
    for p, text in files:
        if text is None:
            continue
        try:
            parsed[p] = (R.load_yaml(text), text)
        except Exception as e:  # YAML error
            if R.DB_TERM_RE.search(text) or R.COMPOSE_UP_RE.search(text):
                errors.append({"file": p, "error": f"yaml: {str(e)[:120]}"})
    # callers of local reusable workflows
    callers: dict[str, list] = {}
    for p, (wf, _) in parsed.items():
        for jk, job in (wf.get("jobs") or {}).items() if isinstance(wf.get("jobs"), dict) else []:
            if isinstance(job, dict) and isinstance(job.get("uses"), str):
                u = job["uses"].split("@")[0]
                if u.startswith("./.github/workflows/"):
                    callers.setdefault(u[2:], []).append((p, jk, job))
    pairs = list(errors and [{"file": e["file"], "stage": "error", "error": e["error"]} for e in errors] or [])
    for p, (wf, text) in sorted(parsed.items()):
        if not (R.DB_TERM_RE.search(text) or R.COMPOSE_UP_RE.search(text)):
            continue
        jobs = wf.get("jobs") if isinstance(wf.get("jobs"), dict) else {}
        trig = R.triggers(wf)
        for jk, job in jobs.items():
            if not isinstance(job, dict) or "steps" not in job:
                continue
            pair = {"file": p, "job": jk}
            try:
                ev = R.db_job_evidence(job, wf, rp.read)
                if not ev:
                    continue
                pair["db"] = ev
                steps = test_steps(job, wf, rp, p, text)
                pair["steps"] = steps
                pair["sharded"] = sharded(job, steps)
                if not steps:
                    pair["stage"] = "no_test_step"
                    pairs.append(pair)
                    continue
                ser = [s for s in steps if s["status"] == "serial"]
                if not ser:
                    pair["stage"] = "unresolved" if any(s["status"] == "unresolved" for s in steps) else "not_serial"
                    pairs.append(pair)
                    continue
                jname = str(job.get("name") if job.get("name") is not None else jk)
                runs_via = []
                if "workflow_call" in trig:
                    for cp, cjk, cjob in callers.get(p, []):
                        cname = str(cjob.get("name") if cjob.get("name") is not None else cjk)
                        runs_via.append((cp, cname))
                    own = trig - {"workflow_call"}
                    if own:
                        runs_via.append((p, None))
                    if not runs_via:
                        pair.update(stage="unsupported", why="workflow_call without a caller in this repository")
                        pairs.append(pair)
                        continue
                else:
                    runs_via.append((p, None))
                best = None
                for run_file, caller in runs_via:
                    targets = [{"job_name": jname, "caller": caller, "yaml_steps": job["steps"], "idx": s["index"],
                                "step": s} for s in ser]
                    time_file(src, rp.repo, branch, run_file, targets)
                    for t in targets:
                        med = R.median10(t["values"])
                        t["step"].setdefault("timing", []).append(
                            {"run_file": run_file, "caller": caller, "values": t["values"], "median_s": med,
                             "runs_seen": t["runs_seen"], "runs": t["run_ids"][:10]})
                        if med is not None and (best is None or med > best["median_s"]):
                            best = {"median_s": med, "run_file": run_file, "caller": caller,
                                    "step_index": t["idx"], "reason": t["step"]["reason"],
                                    "kind": t["step"]["kind"], "last_run": (t["run_ids"] or [{}])[0].get("created_at"),
                                    "job_url": (t["run_ids"] or [{}])[0].get("job"),
                                    "wd": t["step"]["wd"], "wrapped": t["step"].get("wrapped")}
                if best is None:
                    pair["stage"] = "too_few_runs"
                else:
                    pair["timing"] = best
                    pair["stage"] = "ge_10" if best["median_s"] >= 600.0 else "below_10"
            except ApiError as e:
                pair.update(stage="error", error=str(e))
            except Exception as e:  # unexpected parse issue -> uncertain, recorded
                pair.update(stage="error", error=f"{type(e).__name__}: {str(e)[:160]}")
            pairs.append(pair)
    row["pairs"] = pairs
    row["workflow_files"] = [p for p, _ in files]
    return classify(row)


def classify(row: dict) -> dict:
    pairs = row.get("pairs") or []
    stages = [p["stage"] for p in pairs]
    known = [s for s in stages if s in STAGES]
    row["furthest"] = max(known, key=STAGES.index) if known else ("no_db_job" if not stages else None)
    if "ge_10" in stages:
        row["cls"] = "candidate_ge10"  # becomes qualifying or per_worker after §4 (work session)
        row["stage"] = "ge_10"
    elif any(s in UNCERTAIN for s in stages):
        row["cls"] = "uncertain"
        row["stage"] = next(s for s in stages if s in UNCERTAIN)
    else:
        row["cls"] = "not_qualifying"
        row["stage"] = row["furthest"] or "no_db_job"
    return row
