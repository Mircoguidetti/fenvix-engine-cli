#!/usr/bin/env python3
"""§1 discovery: coarse code search with size bisection, resumable from results/discovery_state.json.

Copied from db-serial-count 8150aa1 discover.py; queries are the PREREG §1 families A (workflow files) and B (tool
files); candidates keep their hit terms and files; the pool line adds each query's contribution to N.

Usage: discover.py --route session|workflow [--max-minutes N]      (run)
       discover.py --build                                          (candidates.json + pool line from the leaves)

Each split is searched with per_page=100 page=1; a split with total_count > 1,000 and more than one size value is
bisected (parent, not a leaf). A leaf reads every page up to 1,000 results. A leaf whose responses report
incomplete_results is retried up to 3 times (largest total_count kept); still incomplete -> `incomplete`.
Leaves (with their trimmed items) go to results/discovery/leaves.jsonl.gz, every split to results/discovery/splits.jsonl.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import random
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghapi  # noqa: E402

RES = HERE / "results"
DISC = RES / "discovery"
STATE = RES / "discovery_state.json"
FAMILY_A = ["stryker", "mutmut", "cosmic-ray", "pitest", "mutationCoverage", "cargo-mutants", '"cargo mutants"',
            "infection", "mutant", "go-mutesting", "gremlins", "mull-runner", "muter", "mutatest", "mutation"]
FAMILY_B = ["stryker filename:package.json", "stryker filename:stryker.conf", "stryker filename:stryker.config",
            "stryker filename:stryker-config.json", "infection filename:composer.json",
            "infection filename:infection.json", "infection filename:infection.json5",
            "infection filename:infection.json.dist", "mutants filename:mutants.toml path:.cargo",
            "mutmut filename:setup.cfg", "mutmut filename:pyproject.toml", "cosmic-ray filename:cosmic-ray.toml",
            "pitest filename:pom.xml", "pitest filename:build.gradle", "pitest filename:build.gradle.kts",
            "mutant filename:.mutant.yml", "mutant filename:mutant.yml path:config"]
SIZE_MAX = 400000
DROPPED: dict[str, str] = {}  # query key -> reason (a §0.2b shape fixed or dropped before discovery; CHANGES.md)


def queries() -> list[dict]:
    qa = [{"key": f"A {t}", "family": "A", "term": t.strip('"'), "q": f"{t} path:.github/workflows"} for t in FAMILY_A]
    qb = [{"key": f"B {t}", "family": "B", "term": t.split()[0], "q": t} for t in FAMILY_B]
    return [q for q in qa + qb if q["key"] not in DROPPED]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"started": now(), "finished": None, "queries": {}, "rate_limit": {}, "requests": 0}


def save_state(st: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True) + "\n")
    tmp.replace(STATE)


def trim_item(it: dict) -> dict:
    r = it.get("repository") or {}
    return {"repo": r.get("full_name"), "repo_url": r.get("html_url"), "path": it.get("path"), "sha": it.get("sha")}


def fetch(c: ghapi.Client, q: str, a: int, b: int, page: int) -> tuple[int, dict, dict]:
    path = "search/code?" + urllib.parse.urlencode({"q": f"{q} size:{a}..{b}", "per_page": 100, "page": page})
    for attempt in range(2):
        st, data, hd = c.get(path, search="code")
        if st == 200 and isinstance(data, dict):
            return st, data, hd
        sys.stderr.write(f"search HTTP {st} on {path}: {json.dumps(data)[:200]}\n")
        time.sleep(30)
    return st, data if isinstance(data, dict) else {"error": data}, hd


def run_node(c: ghapi.Client, qd: dict, a: int, b: int) -> dict:
    """Search one size split. Returns the split record (with items when it is a leaf)."""
    st, d, hd = fetch(c, qd["q"], a, b, 1)
    rec = {"query": qd["key"], "family": qd["family"], "term": qd["term"], "a": a, "b": b, "status": st,
           "total_count": d.get("total_count"), "incomplete_results": d.get("incomplete_results"),
           "at": now(), "retries": 0}
    if st != 200:
        rec.update(leaf=True, error=True, read=0, truncated=True, incomplete=True, items=[])
        return rec
    tc = d.get("total_count") or 0
    if tc > 1000 and a < b:
        rec["leaf"] = False
        return rec
    # leaf: retry page 1 while incomplete (up to 3 times), keep the largest total_count
    best, last, max_tc = d, d, d.get("total_count") or 0
    tries = 0
    while last.get("incomplete_results") and tries < 3:
        tries += 1
        st2, d2, _ = fetch(c, qd["q"], a, b, 1)
        if st2 != 200:
            continue
        last = d2
        max_tc = max(max_tc, d2.get("total_count") or 0)
        if len(d2.get("items", [])) >= len(best.get("items", [])) or not d2.get("incomplete_results"):
            best = d2
    best = {**best, "incomplete_results": bool(last.get("incomplete_results"))}
    rec["retries"] = tries
    tc = max_tc
    items = [trim_item(x) for x in best.get("items", [])]
    incomplete = bool(best.get("incomplete_results"))
    pages = math.ceil(min(tc, 1000) / 100)
    for p in range(2, pages + 1):
        stp, dp, _ = fetch(c, qd["q"], a, b, p)
        ptries = 0
        while stp == 200 and dp.get("incomplete_results") and ptries < 3:
            ptries += 1
            stp, dp, _ = fetch(c, qd["q"], a, b, p)
        if stp != 200:
            incomplete = True
            rec.setdefault("page_errors", []).append({"page": p, "status": stp})
            continue
        if dp.get("incomplete_results"):
            incomplete = True
        got = dp.get("items", [])
        items += [trim_item(x) for x in got]
        if not got:
            break
    rec.update(leaf=True, total_count=tc, incomplete_results=bool(best.get("incomplete_results")),
               read=len(items), truncated=tc > 1000 or incomplete, incomplete=incomplete, items=items)
    return rec


BUDGET_FREE = RES / "search_budget_free.json"


def require_budget_free() -> None:
    """AC1 / rule 9: no search request before the coordinator's "search budget free" message, recorded in
    results/search_budget_free.json (time and quote) by the work session when the message arrives."""
    if not BUDGET_FREE.exists():
        sys.exit("refusing to search: results/search_budget_free.json is missing (coordinator message not received)")


def run(route: str, max_minutes: float) -> int:
    require_budget_free()
    RES.mkdir(exist_ok=True)
    DISC.mkdir(exist_ok=True)
    st = load_state()
    st.setdefault("route", route)
    c = ghapi.Client(use_gh=True) if route == "session" else ghapi.from_env()
    t0 = time.time()
    for qd in queries():
        qs = st["queries"].setdefault(qd["key"], {"stack": [[0, SIZE_MAX]], "done": False, "root_total": None,
                                                  "nodes": 0, "leaves": 0})
        while qs["stack"]:
            if (time.time() - t0) / 60 > max_minutes:
                save_state(st)
                print(f"stopping after {max_minutes} min (resumable)")
                return 0
            a, b = qs["stack"][0]
            rec = run_node(c, qd, a, b)
            if qs["root_total"] is None and a == 0 and b == SIZE_MAX:
                qs["root_total"] = rec["total_count"]
                qs["root_incomplete"] = rec["incomplete_results"]
            qs["stack"].pop(0)
            if not rec["leaf"]:
                m = (a + b) // 2
                qs["stack"] = [[a, m], [m + 1, b]] + qs["stack"]
            else:
                with gzip.open(DISC / "leaves.jsonl.gz", "at") as f:
                    f.write(json.dumps(rec, sort_keys=True) + "\n")
                qs["leaves"] += 1
            split = {k: v for k, v in rec.items() if k != "items"}
            with open(DISC / "splits.jsonl", "a") as f:
                f.write(json.dumps(split, sort_keys=True) + "\n")
            qs["nodes"] += 1
            st["requests"] = st.get("requests", 0) + 0
            st["rate_limit"] = {k: c.limit.get(k) for k in c.limit}
            save_state(st)
            print(f"{now()} {qd['key']:<24} size:{a}..{b} tc={rec['total_count']} leaf={rec['leaf']} "
                  f"read={rec.get('read', '-')} inc={rec.get('incomplete', '-')} req={c.n_requests}", flush=True)
        qs["done"] = True
        save_state(st)
    st["finished"] = st["finished"] or now()
    save_state(st)
    print("discovery finished")
    return 0


# ---------------------------------------------------------------------------------------------- build / summary

def read_leaves() -> list[dict]:
    p = DISC / "leaves.jsonl.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt") as f:
        recs = [json.loads(x) for x in f if x.strip()]
    # a leaf re-run after an interruption: keep the last record per (query, a, b)
    by = {}
    for r in recs:
        by[(r["query"], r["a"], r["b"])] = r
    return list(by.values())


def candidate_order(repos: list[dict], seed: int = 1) -> list[dict]:
    """Sort by html_url, then one random.Random(seed).shuffle of the whole list."""
    lst = sorted(repos, key=lambda r: r["html_url"])
    random.Random(seed).shuffle(lst)
    return lst


def build(leaves: list[dict]) -> tuple[list[dict], dict]:
    """Candidates (distinct repositories, hit terms and files) in the shuffled order, and the pool summary:
    N = distinct candidates + sum of max(0, total_count - read) over truncated leaves."""
    cand: dict[str, dict] = {}
    by_query: dict[str, set] = {}
    for lf in leaves:
        by_query.setdefault(lf["query"], set())
        for it in lf.get("items") or []:
            if not it.get("repo"):
                continue
            k = it["repo"].lower()
            row = cand.setdefault(k, {"repo": it["repo"], "html_url": it.get("repo_url") or
                                      f"https://github.com/{it['repo']}", "terms": [], "files": []})
            if lf["query"] not in row["terms"]:
                row["terms"].append(lf["query"])
            if it.get("path") and it["path"] not in row["files"]:
                row["files"].append(it["path"])
            by_query[lf["query"]].add(k)
    for r in cand.values():
        r["terms"].sort()
        r["files"].sort()
    order = candidate_order(list(cand.values()))
    missing_q: dict[str, int] = {}
    for lf in leaves:
        if lf.get("truncated"):
            missing_q[lf["query"]] = missing_q.get(lf["query"], 0) + max(0, (lf.get("total_count") or 0) -
                                                                          (lf.get("read") or 0))
    missing = sum(missing_q.values())
    n = len(order) + missing
    per_query = {}
    for q in [x["key"] for x in queries()] + sorted(set(by_query) - {x["key"] for x in queries()}):
        repos = by_query.get(q, set())
        only = sum(1 for k in repos if len(cand[k]["terms"]) == 1)
        roots = [lf for lf in leaves if lf["query"] == q]
        per_query[q] = {"repos": len(repos), "only_this_query": only, "unread_hits": missing_q.get(q, 0),
                        "contribution": only + missing_q.get(q, 0), "leaves": len(roots),
                        "total_count": sum(lf.get("total_count") or 0 for lf in roots),
                        "truncated_leaves": sum(1 for lf in roots if lf.get("truncated")),
                        "incomplete_leaves": sum(1 for lf in roots if lf.get("incomplete"))}
    summ = {"candidates": len(order), "N": n, "truncated_missing": missing, "leaves": len(leaves),
            "truncated_leaves": sum(1 for lf in leaves if lf.get("truncated")),
            "incomplete_leaves": sum(1 for lf in leaves if lf.get("incomplete")),
            "drop_reachable_at": drop_reachable(n), "per_query": per_query}
    return order, summ


def drop_reachable(n: int) -> int:
    return max(300, math.floor(3.8416 * n / 20 - 3.8416) + 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="session")
    ap.add_argument("--max-minutes", type=float, default=48 * 60)
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args(argv)
    if a.build:
        order, summ = build(read_leaves())
        with open(RES / "candidates.jsonl", "w") as f:
            for i, r in enumerate(order):
                f.write(json.dumps({"idx": i, **r}, sort_keys=True) + "\n")
        (RES / "pool.json").write_text(json.dumps(summ, indent=1, sort_keys=True) + "\n")
        print(json.dumps(summ, sort_keys=True))
        return 0
    return run(a.route, a.max_minutes)


if __name__ == "__main__":
    sys.exit(main())
