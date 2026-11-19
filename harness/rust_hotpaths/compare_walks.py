#!/usr/bin/env python3
"""Two cache-proof walks of the same commits (base engine, new engine), commit by commit.

    compare_walks.py BASE_DIR NEW_DIR [--md OUT]

Per project (shards summed per commit): reused results and reused test time at every commit both walks ran,
the commits where they differ, verification (checked reuses, wrong, flaky) and the walls of the cache run (A),
the full --det run (B) and, at every 10th commit, the cold run and plain pytest.
"""

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import os
import statistics


def load_dir(d):
    out = collections.defaultdict(dict)  # project -> sha -> aggregated step
    for f in sorted(glob.glob(os.path.join(d, "*.json*"))):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rb") as fh:
            r = json.loads(fh.read())
        name = r["spec"]["name"]
        for st in r.get("steps", []):
            if st.get("status") != "ok":
                continue
            a = out[name].setdefault(st["sha"], {"i": st["i"], "shards": 0, "n_tests": 0, "n_reused": 0,
                                                 "time_reused": 0.0, "time_total": 0.0, "checked": 0, "wrong": 0,
                                                 "flaky": 0, "A": 0.0, "B": 0.0, "cold": 0.0, "plain": 0.0,
                                                 "has_overhead": True})
            a["shards"] += 1
            for k in ("n_tests", "n_reused", "time_reused", "time_total"):
                a[k] += st.get(k) or 0
            v = st.get("verify") or {}
            a["checked"] += v.get("checked", 0)
            for m in v.get("mismatches", []):
                a["wrong" if m.get("verdict") == "wrong" else "flaky"] += 1
            a["A"] += (st.get("A") or {}).get("wall", 0.0)
            a["B"] += (st.get("B") or {}).get("wall", 0.0)
            o = st.get("overhead")
            if o:
                a["cold"] += o["cold_wall"]
                a["plain"] += statistics.median(o["pytest_walls"])
            else:
                a["has_overhead"] = False
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("new")
    ap.add_argument("--md")
    a = ap.parse_args()
    base, new = load_dir(a.base), load_dir(a.new)
    lines = ["| project | commits compared | reused results base / new | reused test time base / new | commits with a "
             "different reuse count | verified reuses new (wrong, flaky) | cache run A, median base / new | full "
             "--det run B, median base / new | cold / plain pytest, median base / new |",
             "|---|---|---|---|---|---|---|---|---|"]
    details = []
    for p in sorted(set(base) & set(new)):
        nsh = max(s["shards"] for s in new[p].values())
        common = [s for s in new[p] if s in base[p] and new[p][s]["shards"] == nsh and base[p][s]["shards"] == nsh]
        common.sort(key=lambda s: new[p][s]["i"])
        # the first commit of each walk runs with an empty cache
        trans = [s for s in common if new[p][s]["i"] > 0 and base[p][s]["i"] > 0]
        rb = sum(base[p][s]["n_reused"] for s in trans)
        rn = sum(new[p][s]["n_reused"] for s in trans)
        tb = sum(base[p][s]["time_reused"] for s in trans) / max(1e-9, sum(base[p][s]["time_total"] for s in trans))
        tn = sum(new[p][s]["time_reused"] for s in trans) / max(1e-9, sum(new[p][s]["time_total"] for s in trans))
        diff = [s for s in trans if base[p][s]["n_reused"] != new[p][s]["n_reused"]]
        chk = sum(new[p][s]["checked"] for s in new[p])
        wr = sum(new[p][s]["wrong"] for s in new[p])
        fl = sum(new[p][s]["flaky"] for s in new[p])

        def med(w, k):
            xs = [w[p][s][k] for s in trans if w[p][s][k]]
            return statistics.median(xs) if xs else float("nan")

        def ratio(w):
            xs = [w[p][s]["cold"] / w[p][s]["plain"] for s in common if w[p][s]["has_overhead"] and w[p][s]["plain"]]
            return statistics.median(xs) if xs else float("nan")

        lines.append(f"| {p} | {len(trans)} | {rb} / {rn} | {100 * tb:.1f}% / {100 * tn:.1f}% | {len(diff)} | "
                     f"{chk} ({wr}, {fl}) | {med(base, 'A'):.1f}s / {med(new, 'A'):.1f}s | {med(base, 'B'):.1f}s / "
                     f"{med(new, 'B'):.1f}s | {ratio(base):.2f}x / {ratio(new):.2f}x |")
        for s in diff[:15]:
            details.append(f"- {p} {s[:10]} (commit {new[p][s]['i']}): reused {base[p][s]['n_reused']} (base) vs "
                           f"{new[p][s]['n_reused']} (new) of {new[p][s]['n_tests']}")
    text = "\n".join(lines) + ("\n\nCommits with a different reuse count:\n\n" + "\n".join(details) if details else "")
    print(text)
    if a.md:
        with open(a.md, "w") as fh:
            fh.write(text + "\n")


if __name__ == "__main__":
    main()
