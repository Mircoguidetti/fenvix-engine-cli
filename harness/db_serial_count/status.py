#!/usr/bin/env python3
"""§5 state after each chunk: final class per row (with §4 and hand checks), counts, DROP check, next request.

Usage: status.py               print the state
       status.py --next N      write requests/<N>.json with the next 150 unread candidates (in §1 order)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import perworker  # noqa: E402
import rules as R  # noqa: E402

RES = HERE / "results"
CHUNK = 150


def final_class(row: dict) -> str:
    c = row.get("cls")
    if c != "candidate_ge10":
        return c
    pw = row.get("perworker")
    if pw is None:
        return "pending_perworker"
    if pw.get("per_worker"):
        return "per_worker"
    if row.get("handcheck") is False:
        return "handcheck_failed"
    return "qualifying"


def counts(rows: list[dict]) -> dict:
    out = {"read": 0, "excluded": 0, "qualifying": 0, "uncertain": 0, "not_qualifying": 0, "per_worker": 0,
           "pending_perworker": 0, "handcheck_failed": 0}
    for r in rows:
        fc = final_class(r)
        if fc == "excluded":
            out["excluded"] += 1
            continue
        out["read"] += 1
        if fc in ("per_worker", "handcheck_failed"):
            out[fc] += 1
            out["not_qualifying"] += 1
        else:
            out[fc] = out.get(fc, 0) + 1
    return out


def load_rows() -> list[dict]:
    rows = perworker.read_jsonl(RES / "rows.jsonl")
    pw = perworker.verdicts()
    hc = {x["repo"].lower(): x for x in perworker.read_jsonl(HERE / "handcheck.jsonl")}
    for r in rows:
        name = ((r.get("meta") or {}).get("full_name") or r["repo"]).lower()
        if r.get("cls") == "candidate_ge10":
            v = pw.get(name)
            r["perworker"] = v if v and v["complete"] else None
            h = hc.get(name)
            r["handcheck"] = None if h is None else bool(h.get("pass"))
    return rows


def state() -> dict:
    rows = load_rows()
    c = counts(rows)
    leaves = discover.read_leaves()
    nup = R.n_upper(leaves)
    inc = any(lf.get("incomplete") for lf in leaves)
    d = R.drop_check(c["qualifying"], c["uncertain"] + c["pending_perworker"], c["read"], nup, inc)
    c.update(N_upper=nup, any_incomplete=inc, U=round(d["U"], 6), estimate=round(d["estimate"], 2),
             drop=d["drop"], drop_reachable=R.drop_reachable(nup),
             continue_=c["qualifying"] >= 20)
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", type=int)
    ap.add_argument("--size", type=int, default=CHUNK)
    a = ap.parse_args(argv)
    st = state()
    print(json.dumps(st, sort_keys=True))
    if a.next is not None:
        done = {r["idx"] for r in perworker.read_jsonl(RES / "rows.jsonl")}
        asked = set()
        for p in sorted((HERE / "requests").glob("*.json")):
            q = json.loads(p.read_text())
            asked |= set(q.get("candidates") or [])
        cands = [c["idx"] for c in perworker.read_jsonl(RES / "candidates.jsonl")]
        # unread candidates in §1 order; ones asked before but not read (time limit) come first by order anyway
        nxt = [i for i in cands if i not in done][: a.size]
        req = {"chunk": a.next, "candidates": nxt, "max_minutes": 300}
        (HERE / "requests" / f"{a.next}.json").write_text(json.dumps(req) + "\n")
        print(f"requests/{a.next}.json: {len(nxt)} candidates ({nxt[0] if nxt else '-'}..{nxt[-1] if nxt else '-'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
