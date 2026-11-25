#!/usr/bin/env python3
"""§0.2 probes (after the coordinator's "search budget free" message only; ghapi refuses search before it).

Usage: probe.py session      (gh api route; writes results/probe_session.json, plus the §0.2d registry pages)
       probe.py workflow     (GITHUB_TOKEN route, from the workflow request {"chunk": "probe", "probe": true})
       probe.py decide       (results/probe_decisions.json from the committed probe files; printed and saved)

Every response is committed raw (trimmed to total_count, incomplete_results, the first item paths/URLs, status and
the error message).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

RES = HERE / "results"
KNOWN = "langchain-ai/langchain"
RECORDING_PKGS_PYPI = ["pytest-agentcontract", "coding-agent-vcr", "cendor-cassette", "evalcraft", "pytest-recording",
                       "vcrpy", "pytest-vcr"]
RECORDING_PKGS_NPM = ["pytest-agentcontract", "coding-agent-vcr", "cendor-cassette", "evalcraft", "@pollyjs/core",
                      "nock"]
GENERAL_TOOLS = {"vcrpy", "pytest-recording", "pytest-vcr", "@pollyjs/core", "nock"}


def probe_queries() -> list[dict]:
    I, C = R.ISSUES_PREFIX, R.COMMITS_PREFIX
    k = KNOWN
    qs = [
        # (a) route choice and (b) nested path check
        {"id": "a1", "kind": "code", "q": "api.openai.com path:cassettes"},
        {"id": "a2", "kind": "code", "q": "api.openai.com path:tests/cassettes"},
        # (b) one query of each §1 shape
        {"id": "b-code-cassette", "kind": "code", "q": "api.openai.com path:cassette"},
        {"id": "b-code-recordings", "kind": "code", "q": "api.openai.com path:recordings"},
        {"id": "b-code-vcr", "kind": "code", "q": "api.openai.com path:vcr"},
        {"id": "b-code-pyproject", "kind": "code", "q": "vcrpy filename:pyproject.toml"},
        {"id": "b-code-requirements", "kind": "code", "q": "vcrpy filename:requirements.txt"},
        {"id": "b-code-packagejson", "kind": "code", "q": "nock filename:package.json"},
        {"id": "b-issues-pm", "kind": "issues", "q": f"{I} flaky llm test"},
        {"id": "b-issues-quoted", "kind": "issues", "q": f'{I} "non-deterministic" "model output" test'},
        {"id": "b-issues-cost", "kind": "issues", "q": f'{I} "skip llm" (llm OR openai OR agent)'},
        {"id": "b-commits-pm", "kind": "commits", "q": f"{C} flaky llm test"},
        {"id": "b-commits-quoted", "kind": "commits", "q": f'{C} "non-deterministic" "model output" test'},
        {"id": "b-commits-cost", "kind": "commits", "q": f'{C} "tests are expensive" llm'},
        {"id": "b-commits-cost-model", "kind": "commits", "q": f'{C} "skip llm" test'},
        # (b) §3.2 shapes on a known repository
        {"id": "b-r-issues-pain", "kind": "issues", "q": R.repo_text_queries(k, "issues")[0]},
        {"id": "b-r-issues-model", "kind": "issues", "q": R.repo_text_queries(k, "issues")[1]},
        {"id": "b-r-commits-pain", "kind": "commits", "q": R.repo_text_queries(k, "commits")[0]},
        {"id": "b-r-commits-model", "kind": "commits", "q": R.repo_text_queries(k, "commits")[1]},
        # (b) OR check
        {"id": "or-issues-A", "kind": "issues", "q": f"repo:{k} flaky"},
        {"id": "or-issues-B", "kind": "issues", "q": f"repo:{k} nondeterministic"},
        {"id": "or-issues-AB", "kind": "issues", "q": f"repo:{k} flaky OR nondeterministic"},
        {"id": "or-commits-A", "kind": "commits", "q": f"repo:{k} flaky"},
        {"id": "or-commits-B", "kind": "commits", "q": f"repo:{k} nondeterministic"},
        {"id": "or-commits-AB", "kind": "commits", "q": f"repo:{k} flaky OR nondeterministic"},
        # (b) is:issue / is:pr and parentheses
        {"id": "type-plain", "kind": "issues", "q": f"repo:{k} flaky llm"},
        {"id": "type-issue", "kind": "issues", "q": f"repo:{k} flaky llm is:issue"},
        {"id": "type-pr", "kind": "issues", "q": f"repo:{k} flaky llm is:pr"},
        {"id": "paren", "kind": "issues", "q": f"repo:{k} (flaky OR nondeterministic) llm"},
        # (c) one §1.B issues query and one §1.C commits query
        {"id": "c-issues", "kind": "issues", "q": f"{I} flaky openai test"},
        {"id": "c-commits", "kind": "commits", "q": f"{C} flaky openai test"},
    ]
    return qs


def run_github(route: str) -> list[dict]:
    import ghapi
    c = ghapi.Client(use_gh=True) if route == "session" else ghapi.from_env()
    out = []
    for p in probe_queries():
        path = f"search/{p['kind']}?" + urllib.parse.urlencode({"q": p["q"], "per_page": 100})
        st, d, hd = c.get(path, search="code" if p["kind"] == "code" else "issues")
        rec = {**p, "route": route, "status": st, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "rate_limited": any(k.lower() == "retry-after" for k in hd)}
        if st == 200 and isinstance(d, dict):
            items = d.get("items") or []
            rec.update(total_count=d.get("total_count"), incomplete_results=d.get("incomplete_results"),
                       paths=[x.get("path") for x in items if x.get("path")][:100],
                       urls=[x.get("html_url") for x in items][:20])
        else:
            rec["message"] = (d or {}).get("message") if isinstance(d, dict) else str(d)[:300]
        out.append(rec)
        print(f"{route} {p['id']}: {st} tc={rec.get('total_count')}", flush=True)
    return out


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "fenvix-research", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, {"exception": repr(e)[:200]}


def run_registries() -> list[dict]:
    out = []
    for n in RECORDING_PKGS_PYPI:
        st, d = _get_json(f"https://pypi.org/pypi/{urllib.parse.quote(n)}/json")
        info = (d or {}).get("info") or {}
        urls = info.get("project_urls") or {}
        out.append({"registry": "pypi", "name": n, "status": st, "summary": info.get("summary"),
                    "repository": urls.get("Source") or urls.get("Repository") or urls.get("Homepage")
                    or info.get("home_page")})
    for n in RECORDING_PKGS_NPM:
        st, d = _get_json(f"https://registry.npmjs.org/{urllib.parse.quote(n, safe='@')}")
        repo = (d or {}).get("repository")
        out.append({"registry": "npm", "name": n, "status": st, "summary": (d or {}).get("description"),
                    "repository": repo.get("url") if isinstance(repo, dict) else repo})
    return out


def _gh_repo(url) -> str | None:
    import re
    m = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(\.git)?(/|$)", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def decide(session: list[dict], workflow: list[dict], registries: list[dict]) -> dict:
    """The §0.2 decisions, computed from the probe records."""
    S = {r["id"]: r for r in session}
    W = {r["id"]: r for r in workflow}

    def ok(r):
        return bool(r) and r.get("status") == 200 and not r.get("rate_limited")

    def tc(r):
        return (r or {}).get("total_count") or 0
    code_ok = {rt: any(ok(x.get(i)) for i in ("a1", "a2")) for rt, x in (("session", S), ("workflow", W))}
    if not any(code_ok.values()):
        return {"blocked": True, "why": "no code-search route answers 200"}
    cs = max(tc(S.get("a1")), tc(S.get("a2"))) if code_ok["session"] else -1
    cw = max(tc(W.get("a1")), tc(W.get("a2"))) if code_ok["workflow"] else -1
    code_route = "session" if cs >= cw else "workflow"
    C = S if code_route == "session" else W
    text_ok = {rt: ok(x.get("c-issues")) and ok(x.get("c-commits")) for rt, x in (("session", S), ("workflow", W))}
    text_route = "session" if text_ok["session"] else ("workflow" if text_ok["workflow"] else None)
    T = S if text_route == "session" else W
    nested = any(p.count("/") >= 2 and "/cassettes/" in f"/{p}" for p in (C.get("a1") or {}).get("paths") or [])
    def or_ok(k):  # a probe that errored never counts as "OR works": the queries are split instead
        rs = [T.get(f"or-{k}-{x}") for x in ("A", "B", "AB")]
        return all(ok(r) for r in rs) and tc(rs[2]) >= max(tc(rs[0]), tc(rs[1]))
    issues_or_ok, commits_or_ok = or_ok("issues"), or_ok("commits")
    plain = T.get("type-plain") or {}
    type_split = plain.get("status") == 422 and ok(T.get("type-issue")) and ok(T.get("type-pr"))
    dropped, fixes = [], []
    shape_ids = {"b-code-cassette": "path:cassette", "b-code-recordings": "path:recordings",
                 "b-code-vcr": "path:vcr", "a1": "path:cassettes"}
    for i, shape in shape_ids.items():
        r = C.get(i)
        if not ok(r) or tc(r) == 0:
            dropped += [f"{h} {shape}" for h in R.HOST_TERMS]
            fixes.append(f"code shape {shape}: status {(r or {}).get('status')} total {tc(r)} -> dropped")
    recording = []
    excluded_repos = []
    for x in registries:
        if x["status"] == 200 and x["name"] not in GENERAL_TOOLS and R.MODEL_RE.search(x.get("summary") or ""):
            recording.append(x["name"])
            r = _gh_repo(x.get("repository"))
            if r:
                excluded_repos.append(r)
    for i, fn in (("b-code-pyproject", "filename:pyproject.toml"), ("b-code-requirements", "filename:requirements.txt"),
                  ("b-code-packagejson", "filename:package.json")):
        r = C.get(i)
        if not ok(r) or tc(r) == 0:
            dropped += [f"{p} {fn}" for p in recording]
            fixes.append(f"code shape {fn}: status {(r or {}).get('status')} -> dropped")
    text_shapes = {}
    for i in ("b-issues-pm", "b-issues-quoted", "b-issues-cost", "b-commits-pm", "b-commits-quoted",
              "b-commits-cost", "b-commits-cost-model", "b-r-issues-pain", "b-r-issues-model", "b-r-commits-pain",
              "b-r-commits-model"):
        r = T.get(i) or {}
        text_shapes[i] = {"status": r.get("status"), "total_count": r.get("total_count")}
        if not ok(r) or tc(r) == 0:
            fixes.append(f"text shape {i}: status {r.get('status')} total {tc(r)} -> needs a fix (coordinator)")
    repo_shapes_ok = all(ok(T.get(i)) and tc(T.get(i)) > 0 for i in ("b-r-issues-pain", "b-r-issues-model",
                                                                     "b-r-commits-pain", "b-r-commits-model"))
    return {"blocked": False, "code_route": code_route, "code_totals": {"session": cs, "workflow": cw},
            "text_route": text_route, "nested_path_ok": nested, "issues_or_ok": issues_or_ok,
            "commits_or_ok": commits_or_ok, "issues_type_split": type_split, "dropped": sorted(set(dropped)),
            "recording_packages": sorted(recording), "excluded_repos": sorted(set(excluded_repos)),
            "text_shapes": text_shapes, "repo_text_shapes_ok": repo_shapes_ok, "fixes": fixes}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    RES.mkdir(exist_ok=True)
    mode = argv[0] if argv else "session"
    if mode in ("session", "workflow"):
        recs = run_github(mode)
        doc = {"route": mode, "results": recs}
        if mode == "session":
            doc["registries"] = run_registries()
        (RES / f"probe_{mode}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        return 0
    s = json.loads((RES / "probe_session.json").read_text()) if (RES / "probe_session.json").exists() else {}
    w = json.loads((RES / "probe_workflow.json").read_text()) if (RES / "probe_workflow.json").exists() else {}
    d = decide(s.get("results") or [], w.get("results") or [], s.get("registries") or [])
    (RES / "probe_decisions.json").write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    print(json.dumps(d, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
