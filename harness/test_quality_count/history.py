"""§4 history pain: narrowing changes in commits since HISTORY_START (§4.1), the recall filter (§4.2) and the issues
search (§4.3). Every request goes through ``pipeline.Counting`` with the 300-request cap per repository."""
from __future__ import annotations

import urllib.parse

import rules as R

SINCE = f"{R.HISTORY_START}T00:00:00Z"
ISSUE_OR = "(slow OR timeout OR minutes OR hours OR expensive)"


def watched_paths(row: dict) -> tuple[list[str], list[str]]:
    import pipeline
    configs = sorted(p for p in (row.get("tool_files") or []) + (row.get("hit_files") or []) if R.is_config_path(p))
    scripts = pipeline.script_paths(row)
    return sorted(set(configs)), scripts


def run_history(src, repo: str, row: dict, cap: int = 300) -> dict:
    import pipeline
    B = pipeline.Counting(src, cap)
    configs, scripts = watched_paths(row)
    out = {"paths": [".github/workflows"] + configs + scripts, "changes": [], "candidates": [], "errors": [],
           "commits": 0, "done": False, "capped": False}
    try:
        commits = {}
        for p in out["paths"]:
            page = 1
            while True:
                q = urllib.parse.urlencode({"path": p, "since": SINCE, "per_page": 100, "page": page})
                st, d = B.get(f"repos/{repo}/commits?{q}")
                if st != 200 or not isinstance(d, list):
                    if st not in (404, 409):
                        out["errors"].append(f"commits {p}: HTTP {st}")
                    break
                for c in d:
                    commits.setdefault(c["sha"], {"sha": c["sha"], "date": c.get("date"), "paths": set()})["paths"].add(p)
                if len(d) < 100:
                    break
                if page >= 10:
                    out["errors"].append(f"commits {p}: more than 1,000 commits (listing stopped)")
                    break
                page += 1
        out["commits"] = len(commits)
        order = sorted(commits.values(), key=lambda c: (c["date"] or "", c["sha"]), reverse=True)
        per = []
        for c in order:
            per.append(_commit(B, repo, c["sha"], set(scripts), out["errors"]))
        _cross(B, repo, [x for x in per if x], out["errors"])
        for x in per:
            if not x or not x["kinds"]:
                continue
            pr = (x.get("prs") or [None])[0]
            reasons = R.reason_match(x["message"], pr and pr.get("title"), pr and pr.get("body"))
            ch = {"id": f"commit:{x['sha']}", "sha": x["sha"], "date": x["date"], "kinds": sorted(x["kinds"]),
                  "files": x["files"], "message": x["message"], "pr": pr, "url": x["url"], "reasons": reasons,
                  "kind": "commit"}
            out["changes"].append(ch)
            if reasons:
                out["candidates"].append(ch)
        out["done"] = True
    except pipeline.Counting.Capped:
        out["capped"] = True
    out["requests"] = B.n
    return out


def _fetch(B, repo, path, ref, errors):
    st, d = B.get(f"repos/{repo}/contents/{urllib.parse.quote(path)}?ref={ref}")
    if st == 404:
        return None, True
    if st != 200 or not isinstance(d, dict):
        errors.append(f"contents {path}@{ref[:7]}: HTTP {st}")
        return None, False
    return d.get("text"), True


def _commit(B, repo, sha, scripts: set, errors: list) -> dict | None:
    st, d = B.get(f"repos/{repo}/commits/{sha}")
    if st != 200 or not isinstance(d, dict):
        errors.append(f"commit {sha[:7]}: HTTP {st}")
        return None
    parent = (d.get("parents") or [None])[0]
    x = {"sha": sha, "date": d.get("date"), "message": d.get("message") or "", "url": d.get("html_url"),
         "kinds": set(), "files": [], "removed": [], "added": [], "prs": None}
    for f in d.get("files") or []:
        name, status = f.get("filename") or "", f.get("status")
        prev = f.get("previous_filename") or name
        patch = f.get("patch") if f.get("has_patch", f.get("patch") is not None) else None
        is_wf = name.startswith(".github/workflows/") and name.endswith((".yml", ".yaml")) or \
            prev.startswith(".github/workflows/") and prev.endswith((".yml", ".yaml"))
        is_cfg = R.is_config_path(name)
        is_script = name in scripts
        if not (is_wf or is_cfg or is_script):
            continue
        if is_script and not is_wf and not is_cfg:
            kinds = R.compare_patch(patch, name, script=True)
            if kinds:
                x["kinds"] |= set(kinds)
                x["files"].append({"file": name, "kinds": kinds})
            continue
        if not R.patch_touches(patch, is_wf):
            continue
        ptext, ctext, ok = None, None, True
        if status != "added" and parent:
            ptext, ok1 = _fetch(B, repo, prev, parent, errors)
            ok = ok and ok1
        if status != "removed":
            ctext, ok2 = _fetch(B, repo, name, sha, errors)
            ok = ok and ok2
        if not ok:
            x["files"].append({"file": name, "error": "history-error"})
            continue
        if is_wf:
            try:
                pw = R.load_yaml(ptext) if ptext else None
                cw = R.load_yaml(ctext) if ctext else None
            except Exception as e:
                errors.append(f"yaml {name}@{sha[:7]}: {str(e)[:100]}")
                x["files"].append({"file": name, "error": "history-error"})
                continue
            cmp = R.compare_workflow(pw, cw)
            x["kinds"] |= set(cmp["kinds"])
            x["removed"] += [{**r, "file": prev} for r in cmp["removed"]]
            x["added"] += [{**a, "file": name} for a in cmp["added"]]
            if cmp["kinds"] or cmp["removed"] or cmp["added"]:
                x["files"].append({"file": name, "kinds": cmp["kinds"], "removed": cmp["removed"],
                                   "added": cmp["added"]})
        else:
            kinds = R.compare_patch(patch, name, ptext, ctext)
            if kinds:
                x["kinds"] |= set(kinds)
                x["files"].append({"file": name, "kinds": kinds})
    return x


def _tools_overlap(a, b) -> bool:
    return bool(set(a["tools"]) & set(b["tools"])) or "uses-action" in a["tools"] + b["tools"] or \
        any(t.startswith("script:") for t in a["tools"] + b["tools"])


def _cross(B, repo, per: list[dict], errors: list) -> None:
    """Removed mutation jobs: moved-off-change when added to a scheduled/manual workflow in the same commit or pull
    request; disabled when not added anywhere in the same commit or pull request."""
    for x in per:
        if x["kinds"] or x["removed"] or x["added"]:
            st, d = B.get(f"repos/{repo}/commits/{x['sha']}/pulls")
            x["prs"] = d if st == 200 and isinstance(d, list) else []
            if st not in (200, 404, 409, 422):
                errors.append(f"pulls {x['sha'][:7]}: HTTP {st}")
    by_pr: dict[int, list] = {}
    for x in per:
        for pr in x.get("prs") or []:
            by_pr.setdefault(pr["number"], []).append(x)
    for x in per:
        for r in x["removed"]:
            group = [x] + [y for pr in x.get("prs") or [] for y in by_pr.get(pr["number"], []) if y is not x]
            adds = [a for y in group for a in y["added"] if _tools_overlap(r, a)]
            if not adds:
                x["kinds"].add("disabled")
            elif r["freq"] == "every-change" and any(a["freq"] in ("scheduled", "manual") for a in adds):
                x["kinds"].add("moved-off-change")


def issue_queries(repo: str, tools: list[str]) -> list[str]:
    import pipeline
    terms = [pipeline.QUERY_TERM[t] for t in tools if t in pipeline.QUERY_TERM] + ["mutation"]
    return [f"repo:{repo} {t} {ISSUE_OR} created:>={R.HISTORY_START}" for t in dict.fromkeys(terms)]


def run_issues(src, repo: str, tools: list[str], cap_left: int) -> dict:
    """§4.3 on any source whose ``get(path, search)`` reaches search/issues."""
    import pipeline
    B = pipeline.Counting(src, max(cap_left, 0))
    out = {"queries": [], "candidates": [], "errors": [], "done": False, "capped": False}
    seen = set()
    try:
        for q in issue_queries(repo, tools):
            path = "search/issues?" + urllib.parse.urlencode({"q": q, "per_page": 30, "page": 1})
            st, d = B.get(path, "issues")
            out["queries"].append({"q": q, "status": st, "total_count": (d or {}).get("total_count")
                                   if isinstance(d, dict) else None})
            if st != 200 or not isinstance(d, dict):
                out["errors"].append(f"issues query HTTP {st}: {q}")
                continue
            for it in (d.get("items") or [])[:30]:
                if it["number"] in seen:
                    continue
                seen.add(it["number"])
                out["candidates"].append({"id": f"issue:{it['number']}", "kind": "pr" if it.get("pull_request")
                                          else "issue", "number": it["number"], "title": it.get("title"),
                                          "body": it.get("body"), "url": it.get("html_url"),
                                          "date": it.get("created_at"), "query": q})
        out["done"] = True
    except pipeline.Counting.Capped:
        out["capped"] = True
    out["requests"] = B.n
    return out
