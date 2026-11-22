#!/usr/bin/env python3
"""Print auto-`stated` candidates that have no decision yet in review_decisions.json, with
their evidence lines, for hand review."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
dec = json.load(open(os.path.join(HERE, "review_decisions.json"))) if os.path.exists(os.path.join(HERE, "review_decisions.json")) else {}
for l in open(os.path.join(HERE, "raw", "examined.jsonl")):
    r = json.loads(l)
    if r.get("running_serially") and r.get("auto_reason_kind") == "stated" and r["repo"] not in dec:
        print(f"== {r['repo']} [{r['runner']}] {r['file']}:{r['line']}: {r['verbatim_line'].strip()[:160]}")
        for i, e in enumerate(r["auto_reason_all"]):
            print(f"   [{i}] {e['source']} {e['file'][:48]}:{e['line']}: {e['text'].strip()[:260]}")
