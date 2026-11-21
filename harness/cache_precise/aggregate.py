#!/usr/bin/env python3
"""Table of measure.py results: one row per (project, mode, scenario).

    python harness/cache_precise/aggregate.py results/*.json > table.md
"""
import json
import sys


def main(paths):
    print("| project | mode | scenario | change | passing | reused | share | ran | warm s | uncached s | wrong | flaky |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    bad = 0
    for p in sorted(paths):
        r = json.load(open(p))
        for name, s in r["scenarios"].items():
            share = s["reused_share_of_passing"]
            bad += len(s["wrong"])
            print(f"| {r['spec']['name']} | {r['mode']} | {name} | {s['change']} | {s['passing']} | {s['reused']} | "
                  f"{'' if share is None else f'{share:.1%}'} | {s['ran']} | {s['wall_s']['warm']} | "
                  f"{s['wall_s']['uncached']} | {len(s['wrong'])} | {len(s['flaky'])} |")
    print(f"\nwrong results in total: {bad}")


if __name__ == "__main__":
    main(sys.argv[1:])
