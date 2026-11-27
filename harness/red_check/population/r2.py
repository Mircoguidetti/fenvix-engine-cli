#!/usr/bin/env python3
"""C5.3 revision 2 (PREREG_R2.md): screen repositories first, then read their agent PRs. Runs in the workflow.

Request files:
  {"kind": "screen_r2", "chunk": "<name>", "max_minutes": int}    R2.2, resumable
  {"kind": "collect_r2", "chunk": "<name>", "max_minutes": int}   R2.3 + rev 1's 2.4 with runner rules v2
  {"kind": "oracle_r2", "chunk": "<name>"}                         2.8 for selected_r2.json's PRs
Writes under results_r2/: screen.jsonl, prs.jsonl.gz, excerpts/, checkpoint.json, chunks.jsonl, oracle.jsonl.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect as C  # noqa: E402
import ghrest  # noqa: E402
import rules as R  # noqa: E402

D = dt.date(2026, 11, 27)
WINDOW_START = D - dt.timedelta(days=60)
MIN_AGE_DAYS = 365
BATCH = 20
MAX_PULL_PAGES = 3
RES = HERE / "results_r2"
NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# ---------------------------------------------------------------- R2.2 screening rules

DIRECT = re.compile(r"\b(vitest|jest|pytest)\b|\bnode\s+(?:--[\w-]+(?:=\S+)?\s+)*--test\b")
WRAPPER = re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|\bnpm\s+t\b")
PKG_TEST = re.compile(r"\b(vitest|jest)\b|\bnode\s+(?:--[\w-]+(?:=\S+)?\s+)*--test\b")


def _code_lines(text: str):
    for line in text.splitlines():
        yield line.split("#", 1)[0]


def workflow_match(text: str, pkg_test: str | None) -> str | None:
    """'direct' | 'wrapper' | None for one workflow file (R2.2 rule 3); requires a pull_request trigger."""
    if "pull_request" not in text:
        return None
    lines = list(_code_lines(text))
    if any(DIRECT.search(x) for x in lines):
        return "direct"
    if pkg_test and PKG_TEST.search(pkg_test) and any(WRAPPER.search(x) for x in lines):
        return "wrapper"
    return None


def package_test_script(pkg_text: str | None) -> str | None:
    if not pkg_text:
        return None
    try:
        v = (json.loads(pkg_text).get("scripts") or {}).get("test")
    except (ValueError, AttributeError):
        return None
    return v if isinstance(v, str) else None


def screen_repo(full_name: str, node: dict | None) -> dict:
    """The R2.2 verdict of one repository from its GraphQL node (None: not found)."""
    out = {"repo": full_name}
    if not node:
        return {**out, "verdict": "repo_unreadable"}
    out.update(created_at=node.get("createdAt"), fork=node.get("isFork"), archived=node.get("isArchived"),
               private=node.get("isPrivate"))
    for k in ("fork", "archived", "private"):
        if out[k]:
            return {**out, "verdict": k}
    if R.ts(out["created_at"]).date() >= D - dt.timedelta(days=MIN_AGE_DAYS):  # created before 2025-11-27
        return {**out, "verdict": "repo_too_young_r2"}
    pkg = package_test_script(((node.get("pkg") or {}).get("text")))
    out["package_test"] = pkg
    hits = []
    for e in ((node.get("wf") or {}).get("entries") or []):
        name, text = e.get("name") or "", ((e.get("object") or {}).get("text"))
        if not name.endswith((".yml", ".yaml")) or not isinstance(text, str):
            continue
        how = workflow_match(text, pkg)
        if how:
            hits.append({"file": name, "rule": how})
    out["workflows"] = hits
    return {**out, "verdict": "eligible" if hits else "no_test_ci"}


def graphql_batch(names: list[str]) -> str:
    parts = []
    for i, n in enumerate(names):
        o, r = n.split("/", 1)
        parts.append(
            f'r{i}: repository(owner: {json.dumps(o)}, name: {json.dumps(r)}) {{ nameWithOwner createdAt isFork '
            f'isArchived isPrivate wf: object(expression: "HEAD:.github/workflows") {{ ... on Tree {{ entries {{ '
            f'name object {{ ... on Blob {{ text }} }} }} }} }} pkg: object(expression: "HEAD:package.json") {{ '
            f'... on Blob {{ text }} }} }}')
    return "query { " + " ".join(parts) + " }"


def candidates(pool: list[dict]) -> list[tuple[str, int]]:
    return R.repo_order(pool)


def screen(gql, pool: list[dict], state: dict, emit, deadline: float | None) -> str:
    order = [n for n, _ in candidates(pool)]
    while state["screen_next"] < len(order):
        if gql.low():
            return f"graphql rate limit low ({gql.remaining} of {gql.limit})"
        if deadline is not None and time.time() > deadline:
            return "max_minutes"
        batch = order[state["screen_next"]: state["screen_next"] + BATCH]
        ok = [n for n in batch if NAME.match(n)]
        st, d = gql.query(graphql_batch(ok)) if ok else (200, {"data": {}})
        if st != 200 or not isinstance(d, dict) or not isinstance(d.get("data"), dict):
            return f"graphql HTTP {st}: {str(d)[:200]}"  # nothing emitted; the next chunk retries the batch
        # Per-alias errors: only NOT_FOUND makes a repository unreadable; any other error stops the chunk (retry).
        not_found = set()
        for e in d.get("errors") or []:
            alias = (e.get("path") or [None])[0]
            if e.get("type") == "NOT_FOUND" and isinstance(alias, str):
                not_found.add(alias)
            else:
                return f"graphql error: {str(e)[:200]}"
        data = d["data"]
        rows = [{"repo": n, "verdict": "repo_unreadable", "reason": "name not queryable"} for n in batch if n not in ok]
        for i, n in enumerate(ok):
            row = screen_repo(n, data.get(f"r{i}"))
            if row["verdict"] == "repo_unreadable":
                row["reason"] = "NOT_FOUND" if f"r{i}" in not_found else "null without error"
            rows.append(row)
        for row in rows:
            emit(row)
        state["screen_next"] += len(batch)
    state["screen_done"] = True
    return "screening done"


# ---------------------------------------------------------------- R2.3 agent PRs of a repository

AUTHORS = {"copilot": "Copilot", "devin": "devin-ai-integration[bot]", "jules": "google-labs-jules[bot]"}


def families_of(p: dict) -> list[str]:
    login = (p.get("user") or {}).get("login")
    body = p.get("body") or ""
    fams = [f for f, a in AUTHORS.items() if login == a]
    if ((p.get("head") or {}).get("ref") or "").startswith("codex/") and R.CODEX_MARK.search(body):
        fams.append("codex")
    if R.CC_MARK.search(body):
        fams.append("claude_code")
    return fams


def agent_prs(src, repo: str) -> tuple[list[dict] | None, int]:
    """(agent PRs of the window newest first, or None when page 1 is unreadable; pages read). ``agent_prs.last_note``
    says why a listing stopped early: 'page_error' (a later page failed) or 'page_cap' (3 pages, still in the window)."""
    agent_prs.last_note = None
    out, pages = [], 0
    for page in range(1, MAX_PULL_PAGES + 1):
        st, d = src.get_json(f"repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page=100&page={page}")
        pages += 1
        if st != 200 or not isinstance(d, list):
            if page == 1:
                return None, pages
            agent_prs.last_note = "page_error"
            break
        for p in d:
            created = R.ts(p["created_at"]).date()
            fams = families_of(p)
            if WINDOW_START <= created < D and fams:
                out.append({"url": p["html_url"], "repo": repo, "number": p["number"], "family": fams[0],
                            "families": fams, "created_at": p["created_at"]})
        if len(d) < 100 or R.ts(d[-1]["created_at"]).date() < WINDOW_START:
            break
        if page == MAX_PULL_PAGES:
            agent_prs.last_note = "page_cap"
    out.sort(key=lambda r: (r["created_at"], r["url"]), reverse=True)
    return out, pages


SELECT_TARGET = 6


def selected_count(qual: dict) -> int:
    return sum(1 for urls in qual.values() if len(urls) >= 3)


def collect(src, state: dict, eligible: list[tuple[str, int]], emit, store_log=None,
            deadline: float | None = None, seen: set | None = None, qual: dict | None = None) -> str:
    """Like rev 1's collect, over the eligible repositories, with runner rules v2.
    ``state["rule"] == "all_eligible"`` (PREREG_R2 R2.6): no 30-repository stop; stop before a PR once
    ``SELECT_TARGET`` repositories have >= 3 qualifying PRs (``qual``: repo -> set of qualifying URLs)."""
    seen = seen or set()
    qual = qual if qual is not None else {}
    all_eligible = state.get("rule") == "all_eligible"
    base = src.n_requests
    used = lambda: state["requests"] + src.n_requests - base  # noqa: E731
    try:
        while True:
            if not all_eligible and state["repos_read"] >= C.MAX_REPOS:
                state["stopped"] = f"{C.MAX_REPOS} repositories read"
                return state["stopped"]
            if all_eligible and selected_count(qual) >= SELECT_TARGET:
                state["stopped"] = f"{SELECT_TARGET} repositories selected"
                return state["stopped"]
            if state["next"] >= len(eligible):
                state["stopped"] = "eligible repositories exhausted"
                return state["stopped"]
            name = eligible[state["next"]][0]
            rs = state["repos"].setdefault(name.lower(), {"name": name, "status": "reading", "read": 0,
                                                          "done_urls": []})
            if rs["status"] in ("excluded", "done"):
                state["next"] += 1
                continue
            for check in ("cap", "low", "time"):
                why = C._chunk_stop(check, used(), src, deadline, state)
                if why:
                    if check == "cap":
                        state["stopped"] = why
                    return why
            if "prs" not in rs:
                prs, pages = agent_prs(src, name)
                if prs is None:
                    rs.update(status="excluded", reason="pulls_unreadable")
                    state["next"] += 1
                    continue
                rs.update(prs=[p["url"] for p in prs][:C.MAX_PRS_PER_REPO], pull_pages=pages, n_agent_prs=len(prs),
                          pull_note=getattr(agent_prs, "last_note", None))
                rs["pr_rows"] = {p["url"]: p for p in prs[:C.MAX_PRS_PER_REPO]}
            for url in rs["prs"]:
                if url in rs["done_urls"] or url in seen:
                    continue
                if all_eligible and selected_count(qual) >= SELECT_TARGET:
                    state["stopped"] = f"{SELECT_TARGET} repositories selected"
                    return state["stopped"]
                for check in (("cap", "low", "time") if all_eligible else ("repos", "cap", "low", "time")):
                    why = C._chunk_stop(check, used(), src, deadline, state)
                    if why:
                        if check in ("repos", "cap"):
                            state["stopped"] = why
                        return why
                before = src.n_requests
                row = C.read_pr(src, rs["pr_rows"][url], store_log, version=2)
                row["requests"] = src.n_requests - before
                emit(row)
                if row.get("verdict") == "qualifying":
                    qual.setdefault(row["repo"].lower(), set()).add(row["url"])
                rs["done_urls"].append(url)
                if rs["read"] == 0:
                    state["repos_read"] += 1
                rs["read"] += 1
            rs["status"] = "done"
            state["next"] += 1
    finally:
        state["requests"] = used()


# ---------------------------------------------------------------- entry


def eligible_order(screened: list[dict], pool: list[dict]) -> list[tuple[str, int]]:
    ok = {r["repo"].lower() for r in screened if r["verdict"] == "eligible"}
    return [(n, c) for n, c in candidates(pool) if n.lower() in ok]


def main(argv: list[str]) -> int:
    req = json.loads(Path(argv[1]).read_text())
    RES.mkdir(exist_ok=True)
    src = ghrest.Client(ghrest.token())
    gql = ghrest.GraphQL(src)
    t0 = time.time()
    deadline = t0 + 60 * req["max_minutes"] if req.get("max_minutes") else None
    cp = RES / "checkpoint.json"
    state = json.loads(cp.read_text()) if cp.exists() else {
        "screen_next": 0, "screen_done": False, "graphql_requests": 0, "next": 0, "repos": {}, "repos_read": 0,
        "requests": 0, "stopped": None}
    pool = C.read_jsonl(HERE / "results" / "pool.jsonl.gz")
    rows: list[dict] = []
    try:
        if req["kind"] == "screen_r2":
            why = screen(gql, pool, state, rows.append, deadline)
        elif req["kind"] == "collect_r2":
            if (req.get("rule") == "all_eligible" and state.get("rule") != "all_eligible"
                    and state.get("stopped") == f"{C.MAX_REPOS} repositories read"):
                # PREREG_R2 R2.6: the 30-repository stop is replaced; reading resumes where it stopped.
                state.update(rule="all_eligible", stopped=None, rule_changed_at_next=state["next"],
                             rule_changed_at_requests=state["requests"])
            if not state["screen_done"]:
                why = "screening not done"
            elif state.get("stopped"):
                why = f"already stopped: {state['stopped']}"
            else:
                screened = C.read_jsonl(RES / "screen.jsonl")
                done_rows = C.read_jsonl(RES / "prs.jsonl.gz")
                seen = {r["url"] for r in done_rows}
                qual: dict = {}
                for r in done_rows:
                    if r.get("verdict") == "qualifying":
                        qual.setdefault(r["repo"].lower(), set()).add(r["url"])

                def emit(row):
                    row["chunk"] = req["chunk"]
                    rows.append(row)
                why = collect(src, state, eligible_order(screened, pool), emit,
                              C.Store(RES, HERE / "logs"), deadline, seen, qual)
        elif req["kind"] == "oracle_r2":
            sel = json.loads((HERE / "selected_r2.json").read_text())
            out = [C.oracle(src, p) for r in sel["repositories"] for p in r["prs"]]
            with open(RES / "oracle.jsonl", "w") as f:
                for o in out:
                    f.write(json.dumps(o, sort_keys=True) + "\n")
            state["oracle_requests"] = state.get("oracle_requests", 0) + src.n_requests
            why = f"oracle: {len(out)} PRs"
        else:
            why = f"unknown kind {req['kind']}"
    finally:
        # Rows and checkpoint together, at the chunk's end (see collect.py).
        if req["kind"] == "screen_r2":
            with open(RES / "screen.jsonl", "a") as f:
                for r in rows:
                    f.write(json.dumps(r, sort_keys=True) + "\n")
        elif rows:
            with gzip.open(RES / "prs.jsonl.gz", "at") as f:
                for r in rows:
                    f.write(json.dumps(r, sort_keys=True) + "\n")
        state["graphql_requests"] = state.get("graphql_requests", 0) + gql.n_requests
        cp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    with open(RES / "chunks.jsonl", "a") as f:
        f.write(json.dumps({"chunk": req["chunk"], "kind": req["kind"], "requests": src.n_requests,
                            "graphql": gql.n_requests, "remaining": src.remaining, "limit": src.limit,
                            "reset": src.reset, "graphql_remaining": gql.remaining, "graphql_limit": gql.limit,
                            "graphql_reset": gql.reset, "rows": len(rows), "seconds": round(time.time() - t0),
                            "stop": why, "at": dt.datetime.now(dt.timezone.utc).isoformat()}, sort_keys=True) + "\n")
    print(why, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
