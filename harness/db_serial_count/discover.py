#!/usr/bin/env python3
"""§1 discovery: coarse code search with size bisection, resumable from results/discovery_state.json.

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
DB_TERMS = ["postgres", "mysql", "mariadb", "mongo"]
RUNNER_TERMS = ["jest", "vitest", "mocha", '"node --test"', "pytest", "tox", "nox", '"manage.py"', "rspec",
                '"rails test"', "rake", '"go test"', '"npm test"', '"yarn test"', '"pnpm test"', '"make test"']
SIZE_MAX = 400000


def queries() -> list[dict]:
    return [{"key": f"{d} {r}", "d": d, "r": r.strip('"'), "q": f"{d} {r} path:.github/workflows"}
            for d in DB_TERMS for r in RUNNER_TERMS]


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
        st, data, hd = c.get(path, search=True)
        if st == 200 and isinstance(data, dict):
            return st, data, hd
        sys.stderr.write(f"search HTTP {st} on {path}: {json.dumps(data)[:200]}\n")
        time.sleep(30)
    return st, data if isinstance(data, dict) else {"error": data}, hd


def run_node(c: ghapi.Client, qd: dict, a: int, b: int) -> dict:
    """Search one size split. Returns the split record (with items when it is a leaf)."""
    st, d, hd = fetch(c, qd["q"], a, b, 1)
    rec = {"query": qd["key"], "d": qd["d"], "r": qd["r"], "a": a, "b": b, "status": st,
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


def run(route: str, max_minutes: float) -> int:
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
    cand: dict[str, dict] = {}
    files: set = set()
    for lf in leaves:
        for it in lf["items"]:
            if not it.get("repo"):
                continue
            k = it["repo"].lower()
            row = cand.setdefault(k, {"repo": it["repo"], "html_url": it["repo_url"] or f"https://github.com/{it['repo']}",
                                      "pairs": [], "paths": []})
            pair = f"{lf['d']} x {lf['r']}"
            if pair not in row["pairs"]:
                row["pairs"].append(pair)
            if it["path"] not in row["paths"]:
                row["paths"].append(it["path"])
            files.add((k, it["path"]))
    for r in cand.values():
        r["pairs"].sort()
        r["paths"].sort()
    order = candidate_order(list(cand.values()))
    n_upper = sum(max(lf.get("total_count") or 0, lf.get("read") or 0) for lf in leaves)
    missing = sum(max(0, (lf.get("total_count") or 0) - (lf.get("read") or 0)) for lf in leaves if lf.get("truncated"))
    summ = {"candidates": len(order), "N_upper": n_upper, "N_files": len(files) + missing,
            "distinct_files": len(files), "truncated_missing": missing, "leaves": len(leaves),
            "truncated_leaves": sum(1 for lf in leaves if lf.get("truncated")),
            "incomplete_leaves": sum(1 for lf in leaves if lf.get("incomplete"))}
    return order, summ


def drop_reachable(n_upper: int) -> int:
    return max(300, math.floor(3.8416 * n_upper / 20 - 3.8416) + 1)


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
