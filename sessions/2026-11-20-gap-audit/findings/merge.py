#!/usr/bin/env python3
"""Merge the per-agent gap files into one normalized list (all.jsonl) and print statistics.
Usage: merge.py [--check]"""
import glob
import json
import os
import re
import sys

F = "/home/user/audit/findings"
SEV = ["WRONG-RESULT", "BLOCKS-USE", "DEGRADES", "MINOR"]
CLS = ["BUILD-MVP", "BUILD-LATER", "DECIDE"]
SEES = ["wrong result", "cannot use", "slower", "missing feature", "misleading claim"]


def norm(rec, agent, n):
    r = dict(rec)
    r["agent"] = agent
    r.setdefault("id", f"{agent}-{n:03d}")
    s = str(r.get("severity", "")).upper().replace("_", "-").strip()
    if s not in SEV:
        s = {"WRONG RESULT": "WRONG-RESULT", "BLOCKS USE": "BLOCKS-USE", "BLOCKER": "BLOCKS-USE", "DEGRADE": "DEGRADES",
             "LOW": "MINOR"}.get(s, "?" + s)
    r["severity"] = s
    c = str(r.get("class", "")).upper().replace("_", "-").strip()
    if c not in CLS:
        c = "?" + c
    r["class"] = c
    u = str(r.get("user_sees", "")).lower().strip()
    r["user_sees"] = u if u in SEES else "?" + u
    for k in ("area", "missing", "evidence", "how"):
        r[k] = re.sub(r"\s+", " ", str(r.get(k, ""))).strip()
    return r


def main():
    allr, bad = [], []
    for path in sorted(glob.glob(os.path.join(F, "*.gaps.jsonl"))):
        agent = os.path.basename(path).split(".")[0]
        for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as e:  # noqa: BLE001
                bad.append((path, n, str(e)[:80]))
                continue
            if not isinstance(rec, dict):
                bad.append((path, n, "not an object"))
                continue
            allr.append(norm(rec, agent, n))
    with open("/home/user/audit/all.jsonl", "w") as fh:
        for r in allr:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {}
    for r in allr:
        by.setdefault(r["agent"], []).append(r)
    print(f"total {len(allr)} gaps from {len(by)} agents; bad lines {len(bad)}")
    for a, rs in sorted(by.items()):
        sev = {s: sum(1 for r in rs if r["severity"] == s) for s in SEV}
        odd = sum(1 for r in rs if r["severity"].startswith("?") or r["class"].startswith("?") or r["user_sees"].startswith("?"))
        print(f"  {a:8s} {len(rs):4d}  " + " ".join(f"{k}={v}" for k, v in sev.items()) + (f"  odd={odd}" if odd else ""))
    for b in bad[:30]:
        print("BAD", b)


if __name__ == "__main__":
    main()
