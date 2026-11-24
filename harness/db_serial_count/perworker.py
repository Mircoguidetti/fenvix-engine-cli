#!/usr/bin/env python3
"""§4 per-worker database check, for rows with a pair of median >= 10.0 minutes.

Two halves (the work session cannot read third-party contents; the workflow token cannot use code search):
  search (work session):  perworker.py search            -> results/perworker_search.jsonl (9 code searches per repo)
  fetch  (workflow):      request {"chunk": n, "perworker": true} -> results/perworker_eval.jsonl
A repository is `per_worker` when any fetched hit file counts (``counts``).
"""
from __future__ import annotations

import datetime as dt
import json
import posixpath
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

RES = HERE / "results"
TERMS = ["JEST_WORKER_ID", "VITEST_POOL_ID", "VITEST_WORKER_ID", "PYTEST_XDIST_WORKER", "TEST_ENV_NUMBER",
         "testcontainers", "pglite", "parallelize", '"CREATE DATABASE" TEMPLATE']
ENV_TERMS = TERMS[:5]
ENV_DB = re.compile(r"\b(database|db|connection|schema|DATABASE_URL)\b")
IMPORT_RE = re.compile(r"from testcontainers|import .*testcontainers|require\(['\"](@testcontainers|testcontainers)|"
                       r"from ['\"]@electric-sql/pglite|gem ['\"]testcontainers")
TEMPLATE_RE = re.compile(r"CREATE DATABASE \S+ (WITH )?TEMPLATE")


def counts(term: str, text: str) -> bool:
    if term in ENV_TERMS:
        return term in text and bool(ENV_DB.search(text))
    if term in ("testcontainers", "pglite"):
        return bool(IMPORT_RE.search(text))
    if term == "parallelize":
        for ln in text.splitlines():
            s = ln.strip()
            if s.startswith("#") or "parallelize(" not in s:
                continue
            m = re.search(r"workers:\s*([^,)\s]+)", s)
            if m and m.group(1) != "1":
                return True
        return False
    if term.startswith('"CREATE DATABASE"'):
        return bool(TEMPLATE_RE.search(text))
    return False


def path_ok(path: str, wd: str) -> bool:
    wd = (wd or "").strip("/")
    if wd and not (path == wd or path.startswith(wd + "/")):
        return False
    rel = path[len(wd) + 1:] if wd else path
    return bool(re.search(r"test|spec|conftest|setup", rel))


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def ge10_pairs(row: dict) -> list[dict]:
    return [p for p in row.get("pairs") or [] if p.get("stage") == "ge_10"]


def search(repos: list[dict]) -> int:
    """repos: [{repo, wds}] -> one code search per term per repository (first page, 100 hits)."""
    import ghapi
    c = ghapi.Client(use_gh=True)
    done = {x["repo"].lower() for x in read_jsonl(RES / "perworker_search.jsonl")}
    for r in repos:
        if r["repo"].lower() in done:
            continue
        hits, errors = [], []
        for t in TERMS:
            path = "search/code?" + urllib.parse.urlencode({"q": f"repo:{r['repo']} {t}", "per_page": 100})
            st, d, _ = c.get(path, search=True)
            if st != 200:
                errors.append({"term": t, "status": st})
                continue
            for it in d.get("items", []):
                hits.append({"term": t, "path": it["path"]})
        keep = [h for h in hits if any(path_ok(h["path"], wd) for wd in r["wds"])]
        rec = {"repo": r["repo"], "wds": r["wds"], "hits": hits, "fetch": keep, "errors": errors,
               "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        with open(RES / "perworker_search.jsonl", "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        print(f"{r['repo']}: {len(hits)} hits, {len(keep)} to fetch, errors {errors}", flush=True)
    return 0


def fetch_eval() -> int:
    """Workflow half: fetch every `fetch` file not yet evaluated and record whether it counts."""
    import ghapi
    import pipeline
    c = ghapi.from_env()
    rows = {r["repo"].lower(): r for r in read_jsonl(RES / "rows.jsonl")}
    done = {(x["repo"].lower(), x["path"], x["term"]) for x in read_jsonl(RES / "perworker_eval.jsonl")}
    for s in read_jsonl(RES / "perworker_search.jsonl"):
        meta = (rows.get(s["repo"].lower()) or {}).get("meta") or {}
        ref = meta.get("default_branch") or "HEAD"
        for h in s["fetch"]:
            k = (s["repo"].lower(), h["path"], h["term"])
            if k in done:
                continue
            done.add(k)
            st, d, _ = c.get(f"repos/{s['repo']}/contents/{urllib.parse.quote(h['path'])}?ref={urllib.parse.quote(ref)}")
            if st not in (200, 404):
                st, d, _ = c.get(f"repos/{s['repo']}/contents/{urllib.parse.quote(h['path'])}?ref={urllib.parse.quote(ref)}")
            text = (pipeline.trim(f"repos/x/y/contents/{h['path']}", d) or {}).get("text") if st == 200 else None
            rec = {"repo": s["repo"], "path": h["path"], "term": h["term"], "status": st,
                   "counts": counts(h["term"], text) if text is not None else None,
                   "excerpt": _excerpt(h["term"], text)}
            with open(RES / "perworker_eval.jsonl", "a") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
            print(f"{s['repo']} {h['path']} [{h['term']}]: HTTP {st} counts={rec['counts']}", flush=True)
    return 0


def _excerpt(term: str, text: str | None) -> str | None:
    if not text:
        return None
    key = {"\"CREATE DATABASE\" TEMPLATE": "CREATE DATABASE"}.get(term, term)
    for i, ln in enumerate(text.splitlines()):
        if key.lower() in ln.lower():
            return ln.strip()[:200]
    return None


def verdicts() -> dict[str, dict]:
    """repo -> {per_worker, searched, fetched_all, evidence}."""
    out = {}
    evals = read_jsonl(RES / "perworker_eval.jsonl")
    for s in read_jsonl(RES / "perworker_search.jsonl"):
        ev = [e for e in evals if e["repo"].lower() == s["repo"].lower()]
        fetched = {(e["path"], e["term"]) for e in ev}
        need = {(h["path"], h["term"]) for h in s["fetch"]}
        hits = [e for e in ev if e.get("counts")]
        out[s["repo"].lower()] = {"per_worker": bool(hits), "complete": need <= fetched and not s["errors"],
                                  "evidence": [f"{e['path']} [{e['term']}]: {e.get('excerpt')}" for e in hits]}
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["search"]:
        pend = []
        pw = {x["repo"].lower() for x in read_jsonl(RES / "perworker_search.jsonl")}
        for r in read_jsonl(RES / "rows.jsonl"):
            if r.get("cls") == "candidate_ge10" and r["repo"].lower() not in pw:
                wds = sorted({(p.get("timing") or {}).get("wd") or "" for p in ge10_pairs(r)})
                pend.append({"repo": (r.get("meta") or {}).get("full_name") or r["repo"], "wds": wds})
        sys.exit(search(pend))
    if sys.argv[1:] == ["fetch"]:
        sys.exit(fetch_eval())
    print(__doc__)
