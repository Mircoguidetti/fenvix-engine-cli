#!/usr/bin/env python3
"""§1.1 discovery (work session, legacy code search).

Phase 1 (bisection): for each F, the probe form, `size:a..b` bisected until total_count <= 1,000 or a single size.
Phase 2 (leaves): leaves sorted by (F, a), shuffled once with random.Random(1), fetched (all pages) in that order until
the discovery deadline (start + 24 h). Only hits with path == F are kept (note 6).
Phase 3 (frame): distinct repositories over fetched leaves, sorted by html_url, random.Random(1).shuffle once.

State is checkpointed in discovery/state.json, so a restart resumes. Logs every request in discovery/splits.jsonl
and discovery/pages.jsonl; hits in discovery/hits.jsonl.
Usage: discover.py [--code-per-min N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

import ghapi

HERE = Path(__file__).resolve().parent
D = HERE / "live" / "discovery"  # live files; checkpoint.sh copies them to discovery/
STATE = D / "state.json"
FORMS = {"a": "filename:{F} path:/", "b": "filename:{F}", "c": "{STEM} filename:{F}"}
STEM = {"AGENTS.md": "AGENTS", "CLAUDE.md": "CLAUDE"}
MAX_SIZE = 400000


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def append(name: str, rec: dict) -> None:
    with open(D / name, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def save(state: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True))
    tmp.replace(STATE)


def query(F: str, form: str, a: int, b: int) -> str:
    return FORMS[form].format(F=F, STEM=STEM[F]) + f" size:{a}..{b}"


def search(c: ghapi.Client, qs: str, page: int = 1):
    return c.get(f"search/code?q={ghapi.q(qs)}&per_page=100&page={page}", "code")


def split_count(c, F, form, a, b, leaf_retry: bool):
    """total_count of a split; a leaf with incomplete_results is retried up to 3 times (largest total kept)."""
    best, inc, tries = None, None, 0
    while True:
        st, data, _ = search(c, query(F, form, a, b))
        tries += 1
        if st != 200 or not isinstance(data, dict):
            if tries >= 4:
                return {"status": st, "total_count": best, "incomplete": True, "tries": tries}
            time.sleep(10)
            continue
        tc, inc = data.get("total_count") or 0, bool(data.get("incomplete_results"))
        best = tc if best is None else max(best, tc)
        is_leaf = best <= 1000 or a == b
        if not (inc and is_leaf and leaf_retry) or tries >= 4:
            return {"status": st, "total_count": best, "incomplete": inc, "tries": tries}


A3_HARD_STOP = dt.datetime(2026, 11, 26, 13, 48, 26, tzinfo=dt.timezone.utc).timestamp()


def truncation(state) -> dict:
    """Per query form: 'complete', or the size bound below which every size is in a leaf ('sizes 0..N')."""
    out = {}
    for F in state["forms"]:
        if F in state.get("bisected", []):
            out[F] = "complete"
        else:
            q = state.get("queue", {}).get(F)
            out[F] = "not started" if q is None or q == [[0, MAX_SIZE]] else f"sizes 0..{q[0][0] - 1}"
    return out


def bisect(c, state, deadline: float | None = None) -> bool:
    """Returns False if the deadline (amendment 2: 24 h bisection budget) stopped it before completion."""
    for F, form in state["forms"].items():
        q = state.setdefault("queue", {}).setdefault(F, [[0, MAX_SIZE]]) if F not in state.get("bisected", []) \
            else []
        while q:
            if deadline is not None and time.time() > deadline:
                state["bisection_truncated_by_budget"] = True
                save(state)
                print("bisection budget reached", flush=True)
                return False
            a, b = q[0]
            r = split_count(c, F, form, a, b, leaf_retry=True)
            leaf = (r["total_count"] or 0) <= 1000 or a == b
            rec = {"F": F, "a": a, "b": b, "leaf": leaf, **r, "at": now()}
            append("splits.jsonl", rec)
            print(f"{rec['at']} {F} size:{a}..{b} tc={r['total_count']} leaf={leaf} inc={r['incomplete']}",
                  flush=True)
            q.pop(0)
            if leaf:
                state.setdefault("leaves", []).append(
                    {"F": F, "a": a, "b": b, "total_count": r["total_count"], "incomplete": r["incomplete"],
                     "truncated": (r["total_count"] or 0) > 1000 or r["incomplete"]})
            else:
                m = (a + b) // 2
                q[:0] = [[a, m], [m + 1, b]]
            save(state)
        state.setdefault("bisected", []).append(F) if F not in state.get("bisected", []) else None
        save(state)
    return True


def fetch_leaves(c, state, deadline: float):
    if "order" not in state:
        leaves = sorted(state["leaves"], key=lambda x: (x["F"], x["a"]))
        random.Random(1).shuffle(leaves)
        state["order"] = leaves
        state["next_leaf"] = 0
        save(state)
    order = state["order"]
    while state["next_leaf"] < len(order):
        if time.time() > deadline:
            state["truncated_by_budget"] = True
            save(state)
            print("discovery budget reached", flush=True)
            return
        lf = order[state["next_leaf"]]
        F, form = lf["F"], state["forms"][lf["F"]]
        read = kept = 0
        pages = 1  # PREREG amendment 1: page 1 of each leaf only
        for p in range(1, pages + 1):
            st, data, _ = search(c, query(F, form, lf["a"], lf["b"]), p)
            items = data.get("items") or [] if isinstance(data, dict) else []
            append("pages.jsonl", {"F": F, "a": lf["a"], "b": lf["b"], "page": p, "status": st,
                                   "items": len(items), "at": now()})
            with open(D / "hits.jsonl", "a") as f:
                for it in items:
                    read += 1
                    if it.get("path") != F:
                        continue
                    kept += 1
                    r = it.get("repository") or {}
                    f.write(json.dumps({"F": F, "repo": r.get("full_name"), "id": r.get("id"),
                                        "html_url": r.get("html_url"), "fork": r.get("fork")}) + "\n")
            if st != 200 or len(items) < 100:
                break
        lf.update(read=read, kept=kept, fetched_at=now())
        print(f"{now()} leaf {state['next_leaf'] + 1}/{len(order)} {F} {lf['a']}..{lf['b']} tc={lf['total_count']} "
              f"read={read} kept={kept}", flush=True)
        state["next_leaf"] += 1
        save(state)
    state["leaves_done"] = True
    save(state)


def frame(state):
    seen = {}
    with open(D / "hits.jsonl") as f:
        for ln in f:
            h = json.loads(ln)
            if h["repo"] and h["repo"] not in seen:
                seen[h["repo"]] = {"repo": h["repo"], "id": h["id"], "html_url": h["html_url"], "files": set()}
            if h["repo"]:
                seen[h["repo"]]["files"].add(h["F"])
    cands = sorted(seen.values(), key=lambda x: x["html_url"])
    random.Random(1).shuffle(cands)
    with open(D / "candidates.jsonl", "w") as f:
        for i, c in enumerate(cands):
            f.write(json.dumps({"idx": i, **c, "files": sorted(c["files"])}, sort_keys=True) + "\n")
    state["frame"] = {"candidates": len(cands), "at": now()}
    save(state)
    print(f"frame: {len(cands)} candidates", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-per-min", type=float, default=4)
    ap.add_argument("--amendment3", action="store_true", help="PREREG amendment 3 hard stop (set once in state)")
    ap.add_argument("--amendment2", action="store_true", help="PREREG amendment 2 budgets (set once in state)")
    args = ap.parse_args()
    D.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not state:
        probe = json.loads((HERE / "probe" / "search.json").read_text())
        state = {"forms": {F: probe[F]["form"] for F in ("AGENTS.md", "CLAUDE.md") if probe[F]["form"]},
                 "started": now(), "deadline": time.time() + 24 * 3600}
        save(state)
    c = ghapi.Client(use_gh=True, code_per_min=args.code_per_min)
    a2 = state.get("amendment2")
    if a2 is None and args.amendment2:
        # PREREG amendment 2: fresh 24 h bisection budget from the first resumed search request
        a2 = state["amendment2"] = {"resumed": now(), "bisect_deadline": time.time() + 24 * 3600}
        save(state)
    if a2 is not None and args.amendment3 and "amendment3" not in state:
        # PREREG amendment 3: bisection hard stop 2026-11-26T13:48:26Z (amendment-2 deadline + 6 h)
        state["amendment3"] = {"set": now(), "old_bisect_deadline": a2["bisect_deadline"]}
        a2["bisect_deadline"] = A3_HARD_STOP
        save(state)
    if a2 is not None:
        if not bisect(c, state, a2["bisect_deadline"]):
            if "amendment3" not in state:
                return 3  # amendment 2: stop and ask the coordinator
            # amendment 3: read what was found; the frame is truncated at the size bound reached per form
            state["frame_truncated"] = truncation(state)
            save(state)
            print(f"bisection stopped at hard stop: {state['frame_truncated']}", flush=True)
        if "bisect_end" not in a2:
            a2["bisect_end"] = now()
            a2["leaf_deadline"] = time.time() + 24 * 3600
            save(state)
            print(f"bisection ended {a2['bisect_end']}: {len(state['leaves'])} leaves, "
                  f"{sum(x['total_count'] or 0 for x in state['leaves'])} files in leaves", flush=True)
        deadline = a2["leaf_deadline"]
    else:
        bisect(c, state)
        deadline = state["deadline"]
    if not state.get("leaves_done"):
        fetch_leaves(c, state, deadline)
    frame(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
