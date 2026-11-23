#!/usr/bin/env python3
"""Append hand-check verdicts: handcheck_add.py <verdicts.json>  (list of {url, verdict, reason[, borderline]}).
Tier and family are copied from count1_rows.jsonl; set "sample" for the unflagged-reading set."""
import json, sys
from common import HERE, read_jsonl, append_jsonl
rows = {r["url"]: r for r in read_jsonl(HERE / "count1_rows.jsonl")}
have = {r["url"] for r in read_jsonl(HERE / "handcheck.jsonl")}
for v in json.load(open(sys.argv[1])):
    assert v["verdict"] in ("weakens", "does not weaken"), v
    if v["url"] in have:
        print("already checked", v["url"]); continue
    r = rows[v["url"]]
    append_jsonl(HERE / "handcheck.jsonl", {"url": v["url"], "family": r["family"], "tier": r["tier"],
                 "set": v.get("set", "flagged"), "verdict": v["verdict"], "reason": v["reason"],
                 "borderline": bool(v.get("borderline"))})
print(len(read_jsonl(HERE / "handcheck.jsonl")), "verdicts")
