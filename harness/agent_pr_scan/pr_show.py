#!/usr/bin/env python3
"""Hand-check helper: show part of a sampled pull request's diff, read again with git.
Usage: pr_show.py <url> [path-substring ...] [--stat] [--max N]"""
import json, os, sys
from pathlib import Path
import gitpr
from common import HERE, read_jsonl

args = [a for a in sys.argv[1:] if not a.startswith("--")]
url, subs = args[0], args[1:]
mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 15000
subs = [s for s in subs if not s.isdigit()]
rows = {r["url"]: r for r in read_jsonl(HERE / "count1_rows.jsonl")}
r = rows[url]
root = Path(os.environ.get("WORK_DIR", "/tmp/agent_pr_scan_work")) / "show"
info = gitpr.read_pr(root, r["repo"], r["number"], r["merged_at"])
d = info["dir"]
ns = gitpr.name_status(d, info["base"], info["landing"])
if "--stat" in sys.argv:
    print(gitpr.git(d, "diff", "-M", "--stat=200", info["base"], info["landing"]))
paths = sorted({e["path"] for e in ns if any(s in e["path"] for s in subs)} |
               {e["old"] for e in ns if any(s in e["old"] for s in subs)})
txt = gitpr.patch(d, info["base"], info["landing"], paths) if paths else ""
print(txt[:mx] + ("\n[...truncated]" if len(txt) > mx else ""))
gitpr.cleanup(d)
