"""One request file -> GET reads for the named repositories (or the desk-survey pages), raw files, checkpoint.

Runs only inside the db-copies-read workflow with its GITHUB_TOKEN. Every GitHub call is a GET through
``ghapi.Client`` (search refused, pacing, 600 s cap, 20% rate floor). Outputs go under ``--results``:
``raw/<owner>__<repo>/<stage>.json.gz``, ``docs/``, ``requests.log``, ``chunks.jsonl``, ``checkpoint.json``.
The job never commits; the workflow uploads ``--results`` as an artifact and the session commits it.

Request file: ``{"repos": ["owner/name", ...]}`` (optional ``"bound": 2280`` once the coordinator allows reading
past the 1,500 checkpoint) or ``{"docs": true}``.

Exit codes: 0 done or paused (checkpoint written); 1 refused (stale checkpoint, bad request); 2 stop (access 403).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghapi  # noqa: E402
import rules as R  # noqa: E402

SINCE = R.WINDOW_START
CHECKPOINT_AT = 1500
HARD_BOUND = 2280
CAP = {"files": 15, "issues": 10, "commits": 10, "pathcommits": 6, "diffs": 40, "comments": 15, "pullfiles": 15}
PASS1_FILES = 12  # §2a: the first pass leaves 3 of the 15 content slots for the test-dir conftest and Django files
STAGES = ["meta", "contributors", "tree", "files", "issues", "commits", "pathcommits", "diffs", "comments",
          "pullfiles"]
WORKFLOW = "db-copies-read.yml"
BRANCH = "claude/db-copies-read"
KEEP_HEADERS = ("link", "date", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-resource")

CONFIG_NAMES = ["pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "conftest.py"]
CONFIG_PREFIXES = ["jest.config.", ".mocharc", "vitest.config."]
DEP_NAMES = ["pyproject.toml", "Pipfile", "package.json", "go.mod"]


class Incomplete(Exception):
    pass


def slug(repo: str) -> str:
    return repo.replace("/", "__")


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, sort_keys=True)


def jload(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def keep(h: dict) -> dict:
    return {k.lower(): v for k, v in (h or {}).items() if k.lower() in KEEP_HEADERS}


def has_next(h: dict) -> bool:
    return 'rel="next"' in (keep(h).get("link") or "")


def content_text(entry: dict) -> str | None:
    d = entry.get("data")
    if entry.get("status") != 200 or not isinstance(d, dict) or d.get("encoding") != "base64":
        return None
    import base64
    try:
        return base64.b64decode(d.get("content") or "").decode("utf-8", errors="replace")
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------- file selection §2a
def _join(d: str, n: str) -> str:
    return f"{d.strip('/')}/{n}" if d.strip("/") else n


def config_candidates(paths: set[str], dirs: list[str]) -> list[str]:
    out = []
    for d in dirs:
        for n in CONFIG_NAMES:
            p = _join(d, n)
            if p in paths:
                out.append(p)
        pre = (d.strip("/") + "/") if d.strip("/") else ""
        for p in sorted(paths):
            if p.startswith(pre) and "/" not in p[len(pre):]:
                base = p[len(pre):]
                if any(base.startswith(x) for x in CONFIG_PREFIXES):
                    out.append(p)
    return out


def dep_candidates(paths: set[str], dirs: list[str]) -> list[str]:
    out = []
    for d in dirs:
        pre = (d.strip("/") + "/") if d.strip("/") else ""
        for n in DEP_NAMES:
            p = _join(d, n)
            if p in paths:
                out.append(p)
        for p in sorted(paths):
            if p.startswith(pre) and "/" not in p[len(pre):] and re.fullmatch(r"requirements[^/]*\.txt", p[len(pre):]):
                out.append(p)
    return out


def _uniq(xs):
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def pass1_files(row: dict, paths: set[str]) -> list[str]:
    dirs = _uniq(["", row.get("wd") or ""])
    return _uniq([row["file"], row["runner_src"]] + config_candidates(paths, dirs) + dep_candidates(paths, dirs))


def first_test_dir(row: dict, texts: dict[str, str], dirs_in_tree: set[str]) -> str | None:
    wd = (row.get("wd") or "").strip("/")
    _, rest = R.command_word(row["runner_line"])
    for tok in rest.split():
        if tok.startswith("-") or "$" in tok:
            continue
        t = re.split(r"[*?\[]", tok.strip("'\""))[0].rstrip("/")
        if not t:
            continue
        for cand in (_join(wd, t), t):
            if cand in dirs_in_tree:
                return cand
            parent = cand.rsplit("/", 1)[0] if "/" in cand else ""
            if parent and parent in dirs_in_tree and re.search(r"\.\w+$", cand):
                return parent
    for p, t in texts.items():
        m = re.search(r"testpaths\s*=\s*\[?\s*[\"']?([\w./-]+)", t or "")
        if m:
            base = p.rsplit("/", 1)[0] if "/" in p else ""
            cand = _join(base, m.group(1).rstrip("/"))
            if cand in dirs_in_tree:
                return cand
    return None


def pass2_files(row: dict, paths: set[str], dirs_in_tree: set[str], texts: dict[str, str]) -> tuple[list[str], dict]:
    info = {}
    out = []
    td = first_test_dir(row, texts, dirs_in_tree)
    info["test_dir"] = td
    if td and _join(td, "conftest.py") in paths:
        out.append(_join(td, "conftest.py"))
    dep_texts = [t for p, t in texts.items() if R.DEP_FILE.search(p)]
    dsm_texts = [t for p, t in texts.items() if p == row["file"] or re.search(r"(pytest\.ini|pyproject\.toml|setup\.cfg)$", p)]
    is_dj, why = R.django_project(dep_texts, dsm_texts, sorted(paths))
    info["django"] = is_dj
    info["django_why"] = why
    if is_dj:
        wd = (row.get("wd") or "").strip("/")
        mp = [p for p in (_join(wd, "manage.py"), "manage.py") if p in paths]
        if not mp:
            mp = sorted((p for p in paths if p.endswith("/manage.py")), key=lambda p: (p.count("/"), p))[:1]
        out += mp[:1]
        for t in dsm_texts:
            m = R.DSM.search(t or "")
            if m:
                mod = m.group(1).replace(".", "/")
                bases = _uniq([wd, ""] + ([mp[0].rsplit("/", 1)[0]] if mp and "/" in mp[0] else []))
                for b in bases:
                    for c in (_join(b, mod + ".py"), _join(b, mod + "/__init__.py")):
                        if c in paths:
                            out.append(c)
                            info["settings_module"] = c
                            break
                    if "settings_module" in info:
                        break
                break
    return _uniq(out), info


def pathcommit_files(row: dict, texts: dict[str, str], settings: str | None) -> list[str]:
    out = [row["file"]]
    names = list(texts)
    for n in ("pytest.ini", "setup.cfg", "tox.ini"):
        out += [p for p in names if p.rsplit("/", 1)[-1] == n]
    if "conftest.py" in texts:
        out.append("conftest.py")
    for pre in ("jest.config.", ".mocharc", "vitest.config."):
        out += [p for p in names if p.rsplit("/", 1)[-1].startswith(pre)]
    if settings:
        out.append(settings)
    out += [p for p in names if p.rsplit("/", 1)[-1] == "pyproject.toml" and "[tool.pytest.ini_options]" in (texts[p] or "")]
    return _uniq(out)[:CAP["pathcommits"]]


# ---------------------------------------------------------------------------------------------- reader
class Reader:
    def __init__(self, client: ghapi.Client, results: Path):
        self.c, self.results = client, results

    def get(self, path: str) -> dict:
        st, data, hd = self.c.get(path)
        return {"path": ghapi.normalise(path), "status": st, "headers": keep(hd), "data": data}

    def ok(self, e: dict, allow=(200,)) -> dict:
        if e["status"] == 0 or e["status"] >= 500:
            raise Incomplete(f"{e['path']}: {e['status']}")
        return e

    def stage_path(self, repo: str, stage: str) -> Path:
        return self.results / "raw" / slug(repo) / f"{stage}.json.gz"

    def load(self, repo: str, stage: str):
        p = self.stage_path(repo, stage)
        return jload(p) if p.exists() else None

    # each stage returns the object stored for it
    def s_meta(self, repo, row):
        return {"responses": [self.ok(self.get(f"repos/{repo}"))]}

    def s_contributors(self, repo, row):
        try:
            e = self.get(f"repos/{repo}/contributors?per_page=1&anon=1")
        except ghapi.AccessDenied as ex:
            if "too large" in str(ex).lower():
                return {"responses": [], "count": "unknown", "note": str(ex)[:300]}
            raise
        self.ok(e)
        return {"responses": [e]}

    def s_tree(self, repo, row, meta):
        br = meta["default_branch"]
        e = self.ok(self.get(f"repos/{repo}/git/trees/{urllib.parse.quote(br, safe='')}?recursive=1"))
        out = {"responses": [e]}
        d = e.get("data") or {}
        if d.get("truncated"):
            out["listings"] = []
            for dd in _uniq(["", row.get("wd") or ""]):
                q = urllib.parse.quote(dd.strip("/"))
                out["listings"].append(self.ok(self.get(f"repos/{repo}/contents/{q}?ref={urllib.parse.quote(br)}")))
        return out

    def tree_paths(self, tree: dict) -> tuple[set[str], set[str]]:
        files, dirs = set(), set()
        d = tree["responses"][0].get("data") or {}
        for t in d.get("tree") or []:
            (dirs if t.get("type") == "tree" else files).add(t.get("path"))
        for li in tree.get("listings") or []:
            for t in li.get("data") or []:
                if isinstance(t, dict):
                    (dirs if t.get("type") == "dir" else files).add(t.get("path"))
        return files, dirs

    def s_files(self, repo, row, meta, tree):
        br = urllib.parse.quote(meta["default_branch"])
        files, dirs = self.tree_paths(tree)
        budget = CAP["files"] - len(tree.get("listings") or [])
        p1 = [p for p in pass1_files(row, files) if p in files or tree.get("listings")]
        fetched, entries, not_fetched, got = {}, [], [], []
        for p in p1:
            if len(entries) >= min(PASS1_FILES, budget):
                not_fetched.append(p)
                continue
            e = self.ok(self.get(f"repos/{repo}/contents/{urllib.parse.quote(p)}?ref={br}"))
            entries.append(e)
            got.append(p)
            fetched[p] = content_text(e)
        p2, info = pass2_files(row, files, dirs, fetched)
        for p in p2:
            if p in fetched:
                continue
            if len(entries) >= budget:
                not_fetched.append(p)
                continue
            e = self.ok(self.get(f"repos/{repo}/contents/{urllib.parse.quote(p)}?ref={br}"))
            entries.append(e)
            got.append(p)
            fetched[p] = content_text(e)
        return {"responses": entries, "not_fetched": not_fetched, "info": info, "paths": got}

    def s_issues(self, repo, row, meta):
        out = {"responses": [], "mode": "issues", "truncated": False}
        use_pulls = not meta.get("has_issues", True)
        if not use_pulls:
            for page in range(1, CAP["issues"] + 1):
                e = self.ok(self.get(f"repos/{repo}/issues?state=all&since={SINCE}&per_page=100&page={page}"))
                if e["status"] == 410:
                    use_pulls = True
                    out["responses"] = []
                    out["issues_410"] = e
                    break
                out["responses"].append(e)
                if not has_next(e["headers"]) or len(e.get("data") or []) < 100:
                    break
            else:
                out["truncated"] = has_next(out["responses"][-1]["headers"])
        if use_pulls:
            out["mode"] = "pulls"
            out["issues"] = "disabled"
            for page in range(1, CAP["issues"] + 1):
                e = self.ok(self.get(f"repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page=100&page={page}"))
                out["responses"].append(e)
                data = e.get("data") or []
                if not has_next(e["headers"]) or len(data) < 100 or (data and (data[-1].get("created_at") or "") < SINCE):
                    break
            else:
                out["truncated"] = has_next(out["responses"][-1]["headers"])
        return out

    def s_commits(self, repo, row, meta):
        out = {"responses": [], "truncated": False}
        for page in range(1, CAP["commits"] + 1):
            e = self.ok(self.get(f"repos/{repo}/commits?since={SINCE}&per_page=100&page={page}"))
            out["responses"].append(e)
            if e["status"] != 200 or not has_next(e["headers"]) or len(e.get("data") or []) < 100:
                break
        else:
            out["truncated"] = has_next(out["responses"][-1]["headers"])
        return out

    def s_pathcommits(self, repo, row, files_stage):
        texts = file_texts(files_stage)
        settings = (files_stage.get("info") or {}).get("settings_module")
        out = {"responses": [], "files": pathcommit_files(row, texts, settings)}
        for f in out["files"]:
            out["responses"].append(self.ok(self.get(
                f"repos/{repo}/commits?path={urllib.parse.quote(f)}&since={SINCE}&per_page=100")))
        return out

    def s_diffs(self, repo, row, commits_stage, path_stage):
        msg_matched, path_listed = diff_queue(commits_stage, path_stage)
        queue = _uniq(msg_matched + path_listed)
        take = queue[:CAP["diffs"]]
        left_msg = len([s for s in msg_matched if s not in take])
        left_path = len([s for s in _uniq(path_listed) if s not in take and s not in msg_matched])
        out = {"responses": [], "truncated": len(queue) > CAP["diffs"], "left_out_message_matched": left_msg,
               "left_out_path_listed": left_path, "queued": len(queue)}
        for sha in take:
            out["responses"].append(self.ok(self.get(f"repos/{repo}/commits/{sha}")))
        return out

    def s_comments(self, repo, row, issues_stage):
        nums = matched_items(issues_stage)
        take = [n for n, _ in nums][:CAP["comments"]]
        out = {"responses": [], "truncated": len(nums) > CAP["comments"], "matched": len(nums)}
        for n in take:
            out["responses"].append(self.ok(self.get(f"repos/{repo}/issues/{n}/comments?per_page=100")))
        return out

    def s_pullfiles(self, repo, row, issues_stage):
        q = pullfile_queue(issues_stage)
        take = q[:CAP["pullfiles"]]
        out = {"responses": [], "truncated": len(q) > CAP["pullfiles"], "queued": len(q)}
        for n in take:
            out["responses"].append(self.ok(self.get(f"repos/{repo}/pulls/{n}/files?per_page=100")))
        return out


# ---------------------------------------------------------------------------------------------- shared with build.py
def file_texts(files_stage: dict) -> dict[str, str]:
    out = {}
    for p, e in zip(files_stage.get("paths") or [], files_stage.get("responses") or []):
        t = content_text(e)
        if t is not None:
            out[p] = t
    return out


def issue_items(issues_stage: dict) -> list[dict]:
    """Issues and pulls, newest first by created_at, each with kind and merged_at."""
    items = []
    for e in issues_stage.get("responses") or []:
        for it in e.get("data") or []:
            if not isinstance(it, dict):
                continue
            pr = it.get("pull_request") if issues_stage.get("mode") == "issues" else {"merged_at": it.get("merged_at")}
            items.append({"number": it.get("number"), "kind": "pull" if pr else "issue", "title": it.get("title") or "",
                          "body": it.get("body") or "", "state": it.get("state"), "created_at": it.get("created_at"),
                          "merged_at": (pr or {}).get("merged_at"), "user": it.get("user") or {},
                          "html_url": it.get("html_url")})
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return items


def commit_items(stage: dict) -> list[dict]:
    out = []
    for e in stage.get("responses") or []:
        for c in e.get("data") or []:
            if isinstance(c, dict) and c.get("sha"):
                out.append({"sha": c["sha"], "message": (c.get("commit") or {}).get("message") or "",
                            "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
                            "user": c.get("author") or {}, "html_url": c.get("html_url"),
                            "author_name": ((c.get("commit") or {}).get("author") or {}).get("name") or ""})
    return out


def _commit_user(c: dict) -> dict:
    u = dict(c.get("user") or {})
    if not u.get("login") and c.get("author_name"):
        u["login"] = c["author_name"]
    return u


def diff_queue(commits_stage: dict, path_stage: dict) -> tuple[list[str], list[str]]:
    msg = []
    for c in sorted(commit_items(commits_stage), key=lambda c: c["date"] or "", reverse=True):
        title = c["message"].splitlines()[0] if c["message"] else ""
        rules = R.text_rules("commit", c["message"])
        if R.matched_by_text("commit", c["message"]) and not R.exclusion("commit", _commit_user(c), title, c["message"],
                                                                         c["date"], rules):
            msg.append(c["sha"])
    path = []
    for c in sorted(commit_items(path_stage), key=lambda c: c["date"] or "", reverse=True):
        path.append(c["sha"])
    return msg, _uniq(path)


def matched_items(issues_stage: dict) -> list[tuple[int, dict]]:
    out = []
    for it in issue_items(issues_stage):
        text = it["title"] + "\n" + it["body"]
        rules = R.text_rules(it["kind"], text)
        if R.matched_by_text(it["kind"], text) and not R.exclusion(it["kind"], it["user"], it["title"], text,
                                                                   it["created_at"], rules):
            out.append((it["number"], it))
    return out


def pullfile_queue(issues_stage: dict) -> list[int]:
    first, rest = [], []
    for n, it in matched_items(issues_stage):
        if it["kind"] != "pull":
            continue
        rules = R.text_rules("pull", it["title"] + "\n" + it["body"])
        if "P2-text" in rules and it["state"] == "closed" and not it["merged_at"]:
            first.append(n)
        else:
            rest.append(n)
    return first + rest


# ---------------------------------------------------------------------------------------------- checkpoint
def reference_run(client: ghapi.Client, self_repo: str, current: str) -> str | None:
    """Last run of the workflow with conclusion success that uploaded an artifact (gate M1)."""
    e = client.get(f"repos/{self_repo}/actions/workflows/{WORKFLOW}/runs?branch={urllib.parse.quote(BRANCH)}"
                   f"&status=success&per_page=30")
    runs = (e[1] or {}).get("workflow_runs") or []
    runs.sort(key=lambda r: r.get("run_number") or 0, reverse=True)
    for r in runs:
        if str(r.get("id")) == str(current) or r.get("conclusion") != "success":
            continue
        a = client.get(f"repos/{self_repo}/actions/runs/{r['id']}/artifacts")
        if ((a[1] or {}).get("total_count") or 0) > 0:
            return str(r["id"])
    return None


def load_checkpoint(results: Path) -> dict | None:
    p = results / "checkpoint.json"
    return json.loads(p.read_text()) if p.exists() else None


def new_checkpoint() -> dict:
    return {"run_id": None, "attempts_total": 0, "repos": {}, "docs": None, "runs": []}


# ---------------------------------------------------------------------------------------------- docs (§6)
def fetch_docs(results: Path, urls: list[dict]) -> list[dict]:
    out = []
    for u in urls:
        rec = {"tool": u["tool"], "url": u["url"], "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            req = urllib.request.Request(u["url"], method="GET", headers={"User-Agent": "fenvix-research"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                rec.update(status=r.status, final_url=r.geturl(), bytes=len(body))
        except urllib.error.HTTPError as e:
            body = b""
            rec.update(status=e.code, error=str(e)[:200])
        except Exception as e:
            body = b""
            rec.update(status=0, error=repr(e)[:200])
        name = re.sub(r"[^A-Za-z0-9]+", "_", u["url"].split("://", 1)[-1]).strip("_")[:120] + ".html.gz"
        rec["file"] = name
        p = results / "docs" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wb") as fh:
            fh.write(body)
        out.append(rec)
        time.sleep(1)
    (results / "docs" / "index.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


# ---------------------------------------------------------------------------------------------- main
def run_repo(rd: Reader, repo: str, row: dict, cp: dict) -> str:
    st = cp["repos"].setdefault(repo, {"stages": {}, "state": "pending"})
    done = st["stages"]
    try:
        for stage in STAGES:
            if done.get(stage) == "done":
                continue
            if stage == "meta":
                obj = rd.s_meta(repo, row)
                m = obj["responses"][0]
                if m["status"] in (404, 451) or (m["status"] == 200 and (m["data"] or {}).get("archived")):
                    jdump(rd.stage_path(repo, stage), obj)
                    st["state"] = "unavailable"
                    done[stage] = "done"
                    return "unavailable"
                if m["status"] != 200:
                    raise Incomplete(f"meta status {m['status']}")
            else:
                meta = rd.load(repo, "meta")["responses"][0]["data"]
                if stage == "contributors":
                    obj = rd.s_contributors(repo, row)
                elif stage == "tree":
                    obj = rd.s_tree(repo, row, meta)
                elif stage == "files":
                    obj = rd.s_files(repo, row, meta, rd.load(repo, "tree"))
                elif stage == "issues":
                    obj = rd.s_issues(repo, row, meta)
                elif stage == "commits":
                    obj = rd.s_commits(repo, row, meta)
                elif stage == "pathcommits":
                    obj = rd.s_pathcommits(repo, row, rd.load(repo, "files"))
                elif stage == "diffs":
                    obj = rd.s_diffs(repo, row, rd.load(repo, "commits"), rd.load(repo, "pathcommits"))
                elif stage == "comments":
                    obj = rd.s_comments(repo, row, rd.load(repo, "issues"))
                else:
                    obj = rd.s_pullfiles(repo, row, rd.load(repo, "issues"))
            jdump(rd.stage_path(repo, stage), obj)
            done[stage] = "done"
    except Incomplete as e:
        done[stage] = "incomplete"
        st["state"] = "incomplete"
        st["note"] = str(e)[:200]
        return "incomplete"
    st["state"] = "done"
    st.pop("note", None)
    return "done"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    ap.add_argument("--results", default=str(HERE / "results"))
    ap.add_argument("--repos", default=str(HERE / "repos.json"))
    ap.add_argument("--docs-urls", default=str(HERE / "docs_urls.json"))
    a = ap.parse_args()
    results = Path(a.results)
    results.mkdir(parents=True, exist_ok=True)
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    self_repo = os.environ.get("GITHUB_REPOSITORY", "")
    req = json.loads(Path(a.request).read_text())
    log_fh = open(results / "requests.log", "a")

    def log(d):
        d = dict(d, run=run_id, t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        log_fh.write(json.dumps(d, sort_keys=True) + "\n")
        log_fh.flush()

    def chunk(d):
        with open(results / "chunks.jsonl", "a") as fh:
            fh.write(json.dumps(dict(d, run=run_id, request=Path(a.request).name), sort_keys=True) + "\n")

    client = ghapi.from_env(log=log)
    cp = load_checkpoint(results)
    ref = reference_run(client, self_repo, run_id)
    if (ref is None and cp is not None) or (ref is not None and (cp is None or str(cp.get("run_id")) != ref)):
        msg = f"stale checkpoint: checkpoint run_id {cp and cp.get('run_id')} vs last successful run {ref}"
        print(msg)
        chunk({"status": "refused", "note": msg, "attempts": client.n_requests})
        return 1
    cp = cp or new_checkpoint()
    base_total = cp["attempts_total"]
    status, note = "done", ""
    rows = {r["repo"]: r for r in json.loads(Path(a.repos).read_text())["repos"]}

    def total():
        return base_total + client.n_requests

    try:
        if req.get("docs"):
            recs = fetch_docs(results, json.loads(Path(a.docs_urls).read_text()))
            cp["docs"] = {"run": run_id, "pages": len(recs), "ok": sum(1 for r in recs if r.get("status") == 200)}
        else:
            bound = int(req.get("bound") or CHECKPOINT_AT)
            if bound > HARD_BOUND:
                raise SystemExit("bound above 2,280")
            for repo in req.get("repos") or []:
                if repo not in rows:
                    print(f"unknown repository in request: {repo}")
                    chunk({"status": "refused", "note": f"unknown repo {repo}"})
                    return 1
                if cp["repos"].get(repo, {}).get("state") in ("done", "unavailable"):
                    continue
                if total() >= bound:
                    status, note = "checkpoint-1500" if bound == CHECKPOINT_AT else "bound", f"attempts {total()}"
                    break
                r = run_repo(Reader(client, results), repo, rows[repo], cp)
                print(f"{repo}: {r} (attempts so far {total()})")
                if total() >= HARD_BOUND:
                    status, note = "bound", f"attempts {total()}"
                    break
    except ghapi.Pause as e:
        status, note = "paused", str(e)
    except ghapi.AccessDenied as e:
        cp["attempts_total"] = total()
        chunk({"status": "stop", "note": str(e)[:400], "attempts": client.n_requests, "attempts_total": total(),
               "limit": client.limit, "remaining": client.remaining})
        print(f"STOP access 403: {e}")
        return 2
    cp["attempts_total"] = total()
    cp["run_id"] = run_id
    cp["runs"].append({"run": run_id, "request": Path(a.request).name, "status": status, "attempts": client.n_requests,
                       "limit": client.limit, "remaining": client.remaining, "reset": client.reset})
    (results / "checkpoint.json").write_text(json.dumps(cp, indent=1, sort_keys=True) + "\n")
    chunk({"status": status, "note": note, "attempts": client.n_requests, "attempts_total": total(),
           "limit": client.limit, "remaining": client.remaining, "reset": client.reset,
           "repos": {k: v["state"] for k, v in cp["repos"].items()}})
    print(f"status {status} {note}; attempts this run {client.n_requests}, total {total()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
