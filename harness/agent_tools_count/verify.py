#!/usr/bin/env python3
"""Re-derive the agent tools count from committed files; exit 1 on any mismatch.

Checks: (1) frame.jsonl md5 and the Count B order (seeded_order, seed 2); (2) every Count A row re-derives from its
committed raw JSON (replay through pipeline.count_a); (3) every Count B row re-derives (replay through
pipeline.count_b); (4) hand reads: every automatic ``wasted`` row has codes for each wasted commit, the Count A
sample is random.Random(3) over the sorted not-wasted urls, the Count B samples are random.Random(4) / (5), every
sampled link is marked; (5) every <n><!--key--> in REPORT.md equals the re-computed value and REPORT carries the
two decision lines the rules give.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import pipeline as P  # noqa: E402
import rules as R  # noqa: E402
import stats  # noqa: E402

FRAME_MD5 = "c134bf6bd9e7ba83fd010b8d193b8d11"
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print("MISMATCH", msg)


def strip(x):
    """Rows as JSON (tuples -> lists) without the per-row bookkeeping fields."""
    return json.loads(json.dumps(x, sort_keys=True, default=str))


def replay_a(rows: list[dict]) -> None:
    fr = J.frame()
    by = {r["item"]: r for r in rows}
    seen = set()
    for raw in J.raw_records("a"):
        it = raw["item"]
        seen.add(it)
        row = by.get(it)
        if row is None:
            err(f"A item {it}: raw without row")
            continue
        try:
            out = P.count_a(P.ReplaySource(raw["responses"]), fr[it])
        except P.Missing as e:
            err(f"A item {it}: replay needs {e}")
            continue
        want = {k: v for k, v in row.items() if k not in
                ("item", "url", "repo", "number", "family", "c2_verdict", "chunk", "requests", "seconds")}
        if strip(out) != strip(want):
            diff = sorted(k for k in set(out) | set(want) if strip(out.get(k)) != strip(want.get(k)))
            err(f"A item {it} {row['url']}: replay differs in {diff}")
    for it in by:
        if it not in seen:
            err(f"A item {it}: row without raw")
    if len(by) != len(rows):
        err("A rows: duplicate items")


def replay_b(rows: list[dict]) -> None:
    by = {r["item"]: r for r in rows}
    seen = set()
    for raw in J.raw_records("b"):
        it = raw["item"]
        seen.add(it)
        row = by.get(it)
        if row is None:
            err(f"B {it}: raw without row")
            continue
        n_read = row.get("n_issues_read") or 0
        cnt = {"n": 0}

        def stop():
            if row["status"] != "partial-budget":
                return None
            cnt["n"] += 1
            return "budget" if cnt["n"] > n_read else None
        try:
            out = P.count_b(P.ReplaySource(raw["responses"]), it, J.RACE_FROM, stop)
        except P.Missing as e:
            err(f"B {it}: replay needs {e}")
            continue
        want = {k: v for k, v in row.items() if k not in ("item", "repo", "chunk", "requests", "seconds")}
        if strip(out) != strip(want):
            diff = sorted(k for k in set(out) | set(want) if strip(out.get(k)) != strip(want.get(k)))
            err(f"B {it}: replay differs in {diff}")
    for it in by:
        if it not in seen:
            err(f"B {it}: row without raw")
    order = J.b_order()
    pos = {r: i for i, r in enumerate(order)}
    got = sorted(by, key=lambda r: pos.get(r, 10 ** 9))
    if any(r not in pos for r in by):
        err("B rows: repository not in the frame")
    if got != order[:len(got)]:
        err("B rows: repositories read are not a prefix of the seeded order")


def sample_rows(arows: list[dict]) -> list[dict]:
    """Rows the §1.9 sample is drawn from: the pre-change rows when change 2 re-ran Count A, else the rows."""
    p = HERE / "results" / "a_rows_rule1.jsonl"
    return J.read_jsonl(p) if p.exists() else arows


def check_rule1(arows: list[dict]) -> None:
    """Change 2 re-ran every row offline: the pre-change rows must be the same items, and every row the change
    turned into ``wasted`` must have been ``not-wasted`` (the change only adds rules)."""
    p = HERE / "results" / "a_rows_rule1.jsonl"
    if not p.exists():
        return
    old = J.read_jsonl(p)
    if [r["item"] for r in old] != [r["item"] for r in arows]:
        err("a_rows_rule1: items differ from a_rows")
    for o, r in zip(old, arows):
        if o["result"] != r["result"] and not (o["result"] == R.NOT_WASTED and r["result"] == R.WASTED):
            err(f"a_rows_rule1 {o['url']}: {o['result']} -> {r['result']} is not an added rule hit")


def load_hand():
    ha = {h["url"]: h for h in J.read_jsonl(HERE / "handread_a.jsonl")}
    hs = J.read_jsonl(HERE / "handread_a_sample.jsonl")
    hb = J.read_jsonl(HERE / "handread_b.jsonl")
    return ha, hs, hb


def check_hand(arows, brows, ha, hs, hb) -> None:
    wasted = {r["url"]: r for r in arows if r.get("result") == R.WASTED}
    if set(ha) != set(wasted):
        err(f"hand A: read set != automatic wasted set ({len(ha)} vs {len(wasted)})")
    for u, h in ha.items():
        r = wasted.get(u)
        if not r:
            continue
        need = sorted({p for x in r["xs"] for p in x["wasted_commits"]})
        got = sorted(c["pos"] for c in h.get("commits", []))
        if need != got:
            err(f"hand A {u}: commits read {got} != wasted commits {need}")
        for c in h.get("commits", []):
            if not c.get("codes") or any(x not in R.W_CODES | R.R_CODES for x in c["codes"]):
                err(f"hand A {u} commit {c.get('pos')}: bad codes {c.get('codes')}")
    want = stats.sample_a(sample_rows(arows))
    # the sample is drawn from the automatic not-wasted rows (rows the hand read turns into not-wasted are excluded),
    # of the rows before change 2 when that change was made (results/a_rows_rule1.jsonl)
    if [s["url"] for s in hs] != want:
        err("hand A sample: not random.Random(3).sample(sorted(not-wasted urls), 30)")
    for s in hs:
        if s.get("miss") not in (True, False) or not s.get("note"):
            err(f"hand A sample {s.get('url')}: miss/note missing")
    comp, rest = stats.samples_b(brows)
    gotc = [h["key"] for h in hb if h["sample"] == "competing"]
    gotr = [h["key"] for h in hb if h["sample"] == "addressed"]
    if gotc != comp:
        err("hand B: competing sample differs from the seeded draw")
    if gotr != rest:
        err("hand B: agent-addressed sample differs from the seeded draw")
    iss = {i["key"]: i for i in stats.b_issues(brows)}
    for h in hb:
        i = iss.get(h["key"])
        if not i:
            err(f"hand B {h['key']}: not an agent-addressed issue")
            continue
        if sorted(lk["number"] for lk in h["links"]) != sorted(p["number"] for p in i["agent_prs"]):
            err(f"hand B {h['key']}: links marked differ from the linked agent pull requests")
        if any(lk.get("mark") not in ("same-issue", "not-attempt") for lk in h["links"]):
            err(f"hand B {h['key']}: bad mark")


def values(arows, brows, ha, hs, hb) -> dict[str, str]:
    v = stats.compute_a(arows, ha, hs) if arows else {}
    if brows:
        v.update(stats.compute_b(brows, hb))
    v.update(extra(arows, brows))
    return v


def extra(arows, brows) -> dict[str, str]:
    chunks = J.read_jsonl(HERE / "results" / "chunks.jsonl")
    data = [c for c in chunks if c.get("part") in ("A", "B")]
    a = [c for c in data if c["part"] == "A"]
    b = [c for c in data if c["part"] == "B"]
    reqa = sum(r.get("requests") or 0 for r in arows)
    reqb = sum(r.get("requests") or 0 for r in brows)
    nis = sum(r.get("n_issues_read") or 0 for r in brows)
    return {"chunks": str(len(data)), "chunks_a": str(len(a)), "chunks_b": str(len(b)),
            "requests": str(sum(c["requests"] for c in chunks)), "requests_a": str(reqa), "requests_b": str(reqb),
            "req_per_pr": f"{reqa / len(arows):.1f}" if arows else "n/a",
            "req_per_issue": f"{reqb / nis:.2f}" if nis else "n/a",
            "a_hours": f"{sum(c['seconds'] for c in a) / 3600:.1f}", "b_hours": f"{sum(c['seconds'] for c in b) / 3600:.1f}"}


def decision_lines(v: dict[str, str]) -> list[str]:
    return [f"(a) where it breaks: {v['_decision_a']} (Rate A {v['a_rate']} vs 20%, files evidence "
            f"{v['a_files_share']})",
            f"(b) the race: {v['_decision_b']} (Rate B {v['b_rate']} vs 5%, agent-addressed {v['b_addressed']})"]


def check_report(v) -> None:
    rep = HERE / "REPORT.md"
    if not rep.exists():
        err("REPORT.md missing")
        return
    txt = rep.read_text()
    keys = re.findall(r"(\d[\d.]*%?|n/a|yes|no)<!--([a-z0-9_]+)-->", txt)
    if not keys:
        err("REPORT.md has no marked numbers")
    for val, k in keys:
        if k not in v:
            err(f"REPORT.md key {k} unknown")
        elif val != v[k]:
            err(f"REPORT.md {k}: {val} != re-computed {v[k]}")
    plain = re.sub(r"<!--[a-z0-9_]+-->", "", txt)
    if "_decision_a" in v and "_decision_b" in v:
        for line in decision_lines(v):
            if line not in plain:
                err(f"REPORT.md lacks the decision line {line!r}")


def main() -> int:
    if hashlib.md5((HERE / "frame.jsonl").read_bytes()).hexdigest() != FRAME_MD5:
        err("frame.jsonl md5 differs")
    res = HERE / "results"
    arows = J.read_jsonl(res / "a_rows.jsonl")
    brows = J.read_jsonl(res / "b_rows.jsonl")
    replay_a(arows)
    check_rule1(arows)
    replay_b(brows)
    ha, hs, hb = load_hand()
    check_hand(arows, brows, ha, hs, hb)
    check_report(values(arows, brows, ha, hs, hb))
    print(f"verify: {len(arows)} Count A rows, {len(brows)} Count B rows, {len(errors)} mismatches")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
