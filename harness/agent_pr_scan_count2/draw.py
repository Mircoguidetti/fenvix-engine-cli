#!/usr/bin/env python3
"""Count 2 draw (session side): pools -> seeded order per family -> family interleave -> static exclusions.

Usage: draw.py [--eligible N]   (prepare the draw until N eligible PRs; default 4000)

Pools: first-scan merged rows (harness/agent_pr_scan/search_rows/count1_<f>.jsonl.gz) plus closed-unmerged rows
(search_rows/closed_<f>.jsonl.gz), one pool per (family, month), de-duplicated by URL. Order: common.seeded_order
(seed 1) per family, then one PR per family in turn. Static exclusions as count1_run.py (owners, fork, archived,
not found, repository younger than 30 days at merge / close). The 3-per-repository cap and the quota are applied by
the Actions job (they depend on which PRs are read). Writes draw.jsonl.gz (one row per sequence position up to the
prepared point, with ``excluded`` = reason or null) and draw_meta.json. Repository metadata cache: repo_meta.jsonl
here, on top of the first scan's repo_meta.jsonl (read-only).
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCAN = HERE.parent / "agent_pr_scan"
sys.path.insert(0, str(SCAN))
import common  # noqa: E402

FAMILIES = ["copilot", "devin", "jules", "codex", "claude_code"]
BASE_EXCLUDED_OWNERS = {"mircoguidetti", "github", "anthropics", "openai"}
META_MINE = HERE / "repo_meta.jsonl"


def family_rule(r: dict) -> bool:
    if r["family"] == "codex":
        return r["codex_marker"]
    if r["family"] == "claude_code":
        return r["cc_marker"]
    return True


def excluded_owners() -> set[str]:
    rc = common.read_jsonl(SCAN / "rules_check.jsonl")
    return BASE_EXCLUDED_OWNERS | {o.lower() for r in rc for o in r.get("vendor_owner", [])}


def load_pools(fam: str) -> dict[str, list[dict]]:
    pools, seen = defaultdict(list), set()
    for path, state in ((SCAN / "search_rows" / f"count1_{fam}.jsonl.gz", "merged"),
                        (HERE / "search_rows" / f"closed_{fam}.jsonl.gz", "closed_unmerged")):
        for r in common.read_jsonl(path):
            if r["url"] in seen or not family_rule(r):
                continue
            seen.add(r["url"])
            r = dict(r, state=state)
            pools[r["month"]].append(r)
    return pools


def sequence() -> list[dict]:
    orders = {f: common.seeded_order(load_pools(f)) for f in FAMILIES}
    seq, i = [], 0
    while any(i < len(orders[f]) for f in FAMILIES):
        for f in FAMILIES:
            if i < len(orders[f]):
                seq.append(orders[f][i])
        i += 1
    return seq


def load_meta() -> dict[str, dict]:
    cache = {r["repo"].lower(): r for r in common.read_jsonl(SCAN / "repo_meta.jsonl")}
    cache.update({r["repo"].lower(): r for r in common.read_jsonl(META_MINE)})
    return cache


def static_exclusion(r: dict, m: dict, owners: set[str]) -> str | None:
    owner = r["repo"].split("/")[0].lower()
    if owner in owners:
        return f"excluded owner {owner}"
    if not m["found"]:
        return m["note"]
    if m["fork"]:
        return "fork"
    if m["archived"]:
        return "archived"
    end = r["merged_at"] if r["state"] == "merged" else r["closed_at"]
    if common_ts(end) - common_ts(m["created_at"]) < dt.timedelta(days=30):
        return "repository created less than 30 days before " + ("merge" if r["state"] == "merged" else "close")
    return None


def common_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def slim(i: int, r: dict, why: str | None) -> dict:
    return {"idx": i, "url": r["url"], "family": r["family"], "repo": r["repo"], "number": r["number"],
            "month": r["month"], "state": r["state"], "created_at": r["created_at"], "merged_at": r.get("merged_at"),
            "closed_at": r.get("closed_at"), "excluded": why}


def main() -> None:
    target = int(sys.argv[sys.argv.index("--eligible") + 1]) if "--eligible" in sys.argv else 4000
    common.META = META_MINE  # Meta.ensure appends new metadata here, never to the first scan's file
    meta = common.Meta()
    meta.cache = {**load_meta(), **meta.cache}
    owners = excluded_owners()
    seq = sequence()
    out, eligible, i = [], 0, 0
    while i < len(seq) and eligible < target:
        window = seq[i:i + 60]
        meta.ensure([r["repo"] for r in window if r["repo"].split("/")[0].lower() not in owners])
        for r in window:
            if eligible >= target:
                break
            m = meta.cache.get(r["repo"].lower())
            if m is None and r["repo"].split("/")[0].lower() not in owners:
                raise SystemExit(f"no metadata for {r['repo']}")
            why = static_exclusion(r, m, owners)
            out.append(slim(i, r, why))
            eligible += why is None
            i += 1
        print(f"prepared {i}/{len(seq)} eligible {eligible}", flush=True)
    with gzip.open(HERE / "draw.jsonl.gz", "wt") as f:
        for r in out:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    (HERE / "draw_meta.json").write_text(json.dumps(
        {"prepared": len(out), "eligible": eligible, "sequence_length": len(seq),
         "complete": len(out) == len(seq)}, indent=1) + "\n")


if __name__ == "__main__":
    main()
