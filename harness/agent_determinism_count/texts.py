#!/usr/bin/env python3
"""§3.2 repository texts of members: the repository-scoped searches, the comment fetch, and the pure assembly of a
member's text candidates in §4.1 reading order.

Usage: texts.py search --route session|workflow --chunk N      (repository searches of chunk N's members)
       (the comment pass runs in the workflow: request {"chunk": "Nc", "comments": N})

Records: results/texts_search{,_wf}.jsonl ({repo, chunk, route, at, queries, hits}) with raw responses in
results/texts_raw{,_wf}/<chunk>.jsonl.gz; results/comments.jsonl ({repo, chunk, at, used, search_at, targets, fetched: {url: [comments]}, capped})
with raw responses in results/comments_raw/<chunk>.jsonl.gz. ``verify.py`` replays both.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

RES = HERE / "results"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------------- searches

def run_searches(src, repo: str, cfg: dict) -> dict:
    """The 12 §3.2 queries (or their single-term / is:issue-is:pr splits per the §0.2b probe), first 100 results."""
    out = {"queries": [], "hits": []}
    qs = []
    for q in R.repo_text_queries(repo, "issues", cfg.get("issues_or_ok", True)):
        if cfg.get("issues_type_split"):
            qs += [("issues", f"{q} is:issue"), ("issues", f"{q} is:pr")]
        else:
            qs.append(("issues", q))
    qs += [("commits", q) for q in R.repo_text_queries(repo, "commits", cfg.get("commits_or_ok", True))]
    for kind, q in qs:
        path = f"search/{kind}?" + urllib.parse.urlencode({"q": q, "per_page": 100})
        st, d = src.get(path)
        rec = {"q": q, "kind": kind, "status": st}
        if st != 200:
            rec["error"] = True
        else:
            rec.update(total_count=d.get("total_count"), read=len(d.get("items") or []),
                       incomplete=bool(d.get("incomplete_results")),
                       capped=(d.get("total_count") or 0) > R.TEXT_SEARCH_CAP)
            for it in d.get("items") or []:
                out["hits"].append({**it, "query": q})
        out["queries"].append(rec)
    return out


def search_flags(rec: dict | None) -> list[str]:
    if rec is None:
        return ["texts-missing"]
    f = []
    if any(q.get("error") for q in rec["queries"]):
        f.append("text-error")
    if any(q.get("capped") or q.get("incomplete") for q in rec["queries"]):
        f.append("text-capped")
    return f


# ---------------------------------------------------------------------------------------------- assembly (pure)

def text_of(t: dict, comments: dict | None = None) -> str:
    if t["kind"] == "commit":
        return t.get("message") or ""
    s = f"{t.get('title') or ''}\n\n{t.get('body') or ''}"
    cs = (comments or {}).get(t["url"])
    if cs:
        s += "\n\n" + "\n\n".join(c.get("body") or "" for c in cs)
    return s


def member_texts(repo: str, discovery_hits: list[dict], search_rec: dict | None) -> list[dict]:
    """Distinct texts (by URL) of the member: its S2/S3 discovery hits (``discovery`` True) and its repository-search
    hits, dated on or after HISTORY_START, in §4.1 order."""
    by: dict[str, dict] = {}
    for h in discovery_hits or []:
        if h.get("stratum") in ("S2", "S3") and h.get("url"):
            by.setdefault(h["url"], {**h, "discovery": True})
    for h in (search_rec or {}).get("hits") or []:
        # a hit of another repository (the §0.2b probe saw repo: scope leak around parentheses) is not this member's
        if (h.get("repo") or "").lower() != repo.lower():
            continue
        if h.get("url") and h["url"] not in by:
            by[h["url"]] = {**h, "discovery": False}
    texts = [t for t in by.values() if (t.get("created_at") or "") >= R.HISTORY_START]
    return R.text_order(texts)


def comment_targets(texts: list[dict], fetched: dict) -> list[dict]:
    """Issue/PR texts whose title + body do not match both regexes and whose comments are not fetched yet: the first
    COMMENT_CAP of them in reading order."""
    out = []
    for t in texts:
        if t["kind"] == "commit" or R.is_text_candidate(text_of(t)):
            continue
        out.append(t)
        if len(out) >= R.COMMENT_CAP:
            break
    return [t for t in out if t["url"] not in fetched]


def candidates_of(texts: list[dict], comments: dict) -> tuple[list[dict], list[dict]]:
    """(text candidates in reading order, filtered search hits)."""
    cands, filt = [], []
    for t in texts:
        (cands if R.is_text_candidate(text_of(t, comments)) else filt).append(t)
    return cands, filt


# ---------------------------------------------------------------------------------------------- comments

def fetch_comments(src, repo: str, targets: list[dict]) -> dict:
    """url -> comments (first page of 100). Stops at the request cap (``pipeline.CapReached`` propagates)."""
    out = {}
    for t in targets:
        n = t.get("number")
        if n is None:
            continue
        st, d = src.get(f"repos/{repo}/issues/{n}/comments?per_page=100")
        out[t["url"]] = d if st == 200 and isinstance(d, list) else {"error": st}
    return out


def comments_pass(src, repo: str, texts: list[dict]) -> dict:
    import pipeline as P
    tg = comment_targets(texts, {})
    rec = {"targets": [t["url"] for t in tg], "fetched": {}, "capped": False}
    try:
        rec["fetched"] = fetch_comments(src, repo, tg)
    except P.CapReached:
        rec["capped"] = True
    return rec


def comment_map(rec: dict | None) -> dict:
    return {u: v for u, v in ((rec or {}).get("fetched") or {}).items() if isinstance(v, list)}


def comment_flags(texts: list[dict], rec: dict | None) -> list[str]:
    """A comment fetch that is missing, errored or stopped at the cap leaves pain at most unknown."""
    need = comment_targets(texts, {})
    if not need:
        return []
    if rec is None:
        return ["comments-missing"]
    f = rec.get("fetched") or {}
    if rec.get("capped") or any(not isinstance(f.get(t["url"]), list) for t in need):
        return ["comments-incomplete"]
    return []


# ---------------------------------------------------------------------------------------------- session route CLI

def main(argv=None) -> int:
    import chunk as CH
    import ghapi
    import pipeline as P
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search"])
    ap.add_argument("--route", default="session")
    ap.add_argument("--chunk", required=True)
    a = ap.parse_args(argv)
    cfg = CH.probe_config()
    sfx = "_wf" if a.route == "workflow" else ""
    have = {r["repo"].lower() for f in ("texts_search.jsonl", "texts_search_wf.jsonl")
            for r in CH.read_jsonl(RES / f)}
    rows = [r for r in CH.read_jsonl(RES / "rows.jsonl") if str(r.get("chunk")) == str(a.chunk)
            and r.get("cls") == "member" and not (r.get("recordings") or {}).get("yes")]
    c = ghapi.Client(use_gh=True) if a.route == "session" else ghapi.from_env()
    (RES / f"texts_raw{sfx}").mkdir(parents=True, exist_ok=True)
    n = 0
    for r in rows:
        if r["repo"].lower() in have:
            continue
        src = P.LiveSource(c)
        repo = (r.get("meta") or {}).get("full_name") or r["repo"]
        out = run_searches(src, repo, cfg)
        rec = {"repo": r["repo"], "query_repo": repo, "chunk": r.get("chunk"), "route": a.route, "at": now(), **out}
        with gzip.open(RES / f"texts_raw{sfx}" / f"{a.chunk}.jsonl.gz", "at") as f:
            f.write(json.dumps({"repo": r["repo"], "at": rec["at"], "cfg": cfg, "responses": src.responses},
                               sort_keys=True) + "\n")
        with open(RES / f"texts_search{sfx}.jsonl", "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        n += 1
        print(f"{r['repo']}: {len(out['queries'])} queries, {len(out['hits'])} hits, flags {search_flags(rec)}",
              flush=True)
    print(f"texts chunk {a.chunk}: {n} members searched, search requests {c.n_search}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
