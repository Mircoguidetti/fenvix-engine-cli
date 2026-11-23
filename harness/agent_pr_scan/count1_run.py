#!/usr/bin/env python3
"""Count 1: draw agent pull requests, read them with git, classify. Usage: count1_run.py [--claude-code]

Draw rule (spec): per family, an equal number per month at random (random.Random(1)), drawn in seeded order until
the family's share of 300 autonomous pull requests is in the primary denominator (repository has at least one test
file at base). Autonomous families are interleaved one pull request at a time so the 3-per-repository cap is
applied in a single global order. Claude Code is drawn afterwards (up to 100), counting the repositories already
used.

Writes: count1_rows.jsonl (every pull request read), count1_excluded.jsonl (dropped before reading, with reason),
unreadable.jsonl (read failed, exact error), count1_diffs.jsonl.gz (name-status + test diff, for the hand check).
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import classify
import gitpr
from common import HERE, Meta, append_jsonl, read_jsonl, seeded_order

AUTONOMOUS = ["copilot", "devin", "jules", "codex"]
TARGET_AUTONOMOUS = 300
TARGET_CC = 100
CAP_PER_REPO = 3
BASE_EXCLUDED_OWNERS = {"mircoguidetti", "github", "anthropics", "openai"}
WORK = Path(os.environ.get("WORK_DIR", "/tmp/agent_pr_scan_work")) / "count1"

ROWS = HERE / "count1_rows.jsonl"
EXCL = HERE / "count1_excluded.jsonl"
UNREAD = HERE / "unreadable.jsonl"
DIFFS = HERE / "count1_diffs.jsonl.gz"


def family_rule(r: dict) -> bool:
    if r["family"] == "codex":
        return r["codex_marker"]
    if r["family"] == "claude_code":
        return r["cc_marker"]
    return True


def load_pool(fam: str) -> list[dict]:
    seen, out = set(), []
    for r in read_jsonl(HERE / "search_rows" / f"count1_{fam}.jsonl.gz"):
        if r["url"] in seen or not family_rule(r):
            continue
        seen.add(r["url"])
        out.append(r)
    return out


def config() -> dict:
    rc = read_jsonl(HERE / "rules_check.jsonl")
    wrong = Counter(r["family"] for r in rc if not r["agent_made"])
    checked = Counter(r["family"] for r in rc)
    passing = [f for f in AUTONOMOUS if checked[f] >= 20 and wrong[f] <= 2]
    vendors = {o.lower() for r in rc for o in r.get("vendor_owner", [])}
    return {"passing": passing, "cc_pass": checked["claude_code"] >= 20 and wrong["claude_code"] <= 2,
            "excluded_owners": BASE_EXCLUDED_OWNERS | vendors}


def static_exclusion(r: dict, meta: Meta, owners: set[str]) -> str | None:
    owner = r["repo"].split("/")[0].lower()
    if owner in owners:
        return f"excluded owner {owner}"
    m = meta.get(r["repo"])
    if not m["found"]:
        return m["note"]
    if m["fork"]:
        return "fork"
    if m["archived"]:
        return "archived"
    created = gitpr.parse_ts(m["created_at"])
    if gitpr.parse_ts(r["merged_at"]) - created < dt.timedelta(days=30):
        return "repository created less than 30 days before merge"
    return None


def read_one(r: dict) -> dict:
    root = WORK / r["url"].split("github.com/")[1].replace("/", "__")
    try:
        info = gitpr.read_pr(root, r["repo"], r["number"], r["merged_at"])
        d = info["dir"]
        ns = gitpr.name_status(d, info["base"], info["landing"])
        base_tests = [p for p in gitpr.tree_paths(d, info["base"]) if classify.is_test(p)]
        sel = sorted({e["path"] for e in ns if classify.is_test(e["path"]) or classify.is_test(e["old"])
                      or classify.is_test_config(e["path"])} |
                     {e["old"] for e in ns if classify.is_test(e["old"]) or classify.is_test_config(e["old"])})
        text = gitpr.patch(d, info["base"], info["landing"], sel)
        c = classify.classify(ns, text)
        return {"ok": True, "info": {k: v for k, v in info.items() if k != "dir"}, "ns": ns, "patch": text,
                "n_base_test_files": len(base_tests), "cls": c}
    except gitpr.Unreadable as e:
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run(families: list[str], targets: dict[str, int], phase: str, owners: set[str]) -> None:
    meta = Meta()
    done_urls = {r["url"] for r in read_jsonl(ROWS)} | {r["url"] for r in read_jsonl(EXCL)} | \
                {r["url"] for r in read_jsonl(UNREAD)}
    per_repo = Counter(r["repo"].lower() for r in read_jsonl(ROWS)) + \
        Counter(r["repo"].lower() for r in read_jsonl(UNREAD) if r.get("count") == "count1")
    in_denom = Counter(r["family"] for r in read_jsonl(ROWS) if r["n_base_test_files"] > 0)
    orders = {}
    for fam in families:
        pools = defaultdict(list)
        for r in load_pool(fam):
            pools[r["month"]].append(r)
        orders[fam] = seeded_order(pools)
    # global interleaved order: one per family in turn
    seq, i = [], 0
    while any(i < len(orders[f]) for f in families):
        for f in families:
            if i < len(orders[f]):
                seq.append(orders[f][i])
        i += 1
    exhausted: set[str] = set()
    pos = Counter()
    pool = ThreadPoolExecutor(max_workers=6)
    futures: dict[str, object] = {}

    def share(f: str) -> int:
        return targets[f]

    def need(f: str) -> bool:
        return in_denom[f] < share(f)

    idx = 0
    while idx < len(seq) and any(need(f) for f in families):
        r = seq[idx]
        # prefetch metadata and speculative reads for the next window of candidates
        window = [x for x in seq[idx:idx + 40] if x["url"] not in done_urls]
        meta.ensure([x["repo"] for x in window])
        for x in window[:12]:
            if x["url"] not in futures and need(x["family"]) and \
                    static_exclusion(x, meta, owners) is None and per_repo[x["repo"].lower()] < CAP_PER_REPO:
                futures[x["url"]] = pool.submit(read_one, x)
        idx += 1
        fam = r["family"]
        if r["url"] in done_urls or not need(fam):
            continue
        base = {"url": r["url"], "family": fam, "repo": r["repo"], "number": r["number"], "month": r["month"],
                "window": r["window"], "merged_at": r["merged_at"], "title": r["title"], "author": r["author"],
                "phase": phase}
        why = static_exclusion(r, meta, owners)
        if why is None and per_repo[r["repo"].lower()] >= CAP_PER_REPO:
            why = "repository cap (3 per repository) reached"
        if why:
            append_jsonl(EXCL, {**base, "reason": why})
            done_urls.add(r["url"])
            continue
        fut = futures.pop(r["url"], None) or pool.submit(read_one, r)
        res = fut.result()
        done_urls.add(r["url"])
        per_repo[r["repo"].lower()] += 1
        if not res["ok"]:
            append_jsonl(UNREAD, {**base, "count": "count1", "error": res["error"]})
            print(f"UNREADABLE {r['url']}: {res['error']}", flush=True)
            continue
        c = res["cls"]
        row = {**base, **res["info"], "n_base_test_files": res["n_base_test_files"], "tier": c["tier"],
               "signals": c["signals"], "strong_signals_test_only_pr": c["strong_signals_test_only_pr"],
               "n_files": c["n_files"], "n_test_files_changed": c["n_test_files_changed"],
               "nontest_code_changed": c["nontest_code_changed"],
               "snapshot_files_changed": c["snapshot_files_changed"], "body_head": r["body_head"]}
        append_jsonl(ROWS, row)
        append_jsonl(DIFFS, {"url": r["url"], "ns": res["ns"], "patch": res["patch"][:400000]})
        if res["n_base_test_files"] > 0:
            in_denom[fam] += 1
        print(f"{fam} {in_denom[fam]}/{share(fam)} {r['url']} tests={res['n_base_test_files']} {c['tier']}",
              flush=True)
    for f in families:
        if need(f):
            exhausted.add(f)
    pool.shutdown(wait=False, cancel_futures=True)
    print("in_denominator", dict(in_denom), "exhausted", sorted(exhausted), flush=True)


def main() -> None:
    cfg = config()
    if "--claude-code" in sys.argv:
        if cfg["cc_pass"]:
            run(["claude_code"], {"claude_code": TARGET_CC}, "claude_code", cfg["excluded_owners"])
        return
    fams = cfg["passing"]
    base = TARGET_AUTONOMOUS // len(fams)
    targets = {f: base for f in fams}
    for f in fams[: TARGET_AUTONOMOUS - base * len(fams)]:
        targets[f] += 1
    run(fams, targets, "autonomous", cfg["excluded_owners"])


if __name__ == "__main__":
    main()
