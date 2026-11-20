"""Block 2 re-measured with the product command: `fenvix repro <target>` per Block 1 flaky target.

    python harness/block2_fenvix_report.py harness/results/block2-fenvix-cli [harness/results/block2-final]

Reads <repo>.fenvix.block2.json (harness/detpy_harness.py --mode block2 --tool fenvix) and writes REPORT.md and
summary.json in the same directory. With a second directory, compares with its standalone results
(<repo>.standalone.block2.json: `detpy repro`, Block 2 final).

Definitions (every number MEASURED from the JSON files)
  reproduced          `fenvix repro` ended with status `reproduced` (exit 0): the bundle's --confirm replays all
                      failed with one fingerprint.
  cause named         a reproduced target whose printed `cause:` line names a cause (polluter, state setter, seed or
                      first divergent event), i.e. not `unknown`.
  replay N/N, one fp  replay.fails == replay.runs == --confirm and identical_fingerprint.
  replay command      the printed output holds a `replay: fenvix replay <bundle>` line.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path


def load(d: Path, tool: str) -> dict:
    out = {}
    for p in sorted(d.glob(f"*.{tool}.block2.json")):
        data = json.loads(p.read_text())
        out[data["name"]] = data
    return out


def summarise(runs: dict) -> dict:
    s = collections.Counter()
    statuses = collections.Counter()
    kinds = collections.Counter()
    causes = collections.Counter()
    per_repo = {}
    for name, data in sorted(runs.items()):
        r = collections.Counter()
        targets = data.get("targets", [])
        r["targets"] = len(targets)
        for b in data.get("bundles", []):
            st = b.get("status")
            statuses[st] += 1
            if st != "reproduced":
                continue
            r["reproduced"] += 1
            kinds[b.get("kind")] += 1
            cl = b.get("cause_line")
            if cl and cl != "unknown":
                r["cause"] += 1
                causes[cl.split(":", 1)[0]] += 1
            rp = b.get("replay") or {}
            if rp.get("runs") and rp.get("fails") == rp.get("runs") and rp.get("identical_fingerprint"):
                r["replay_one_fp"] += 1
            if (b.get("replay_line") or "").startswith("replay:  fenvix replay") or (b.get("replay_line") or "").startswith("replay: fenvix replay"):
                r["replay_cmd"] += 1
        per_repo[name] = dict(r)
        s.update(r)
    return {"totals": dict(s), "statuses": dict(statuses), "kinds": dict(kinds), "causes": dict(causes),
            "per_repo": per_repo}


def pct(a, b) -> str:
    return f"{a}/{b} ({100.0 * a / b:.1f}%)" if b else f"{a}/0"


def main(argv: list) -> int:
    d = Path(argv[1])
    runs = load(d, "fenvix")
    s = summarise(runs)
    t = s["totals"]
    lines = ["# Block 2 re-measured with `fenvix repro` (the product command)", ""]
    meta = d / "meta.json"
    if meta.exists():
        lines.append(f"Run: {json.loads(meta.read_text()).get('run')}. ")
    lines += [f"Repositories: {len(runs)}. Targets: {t.get('targets', 0)}. Every number MEASURED from "
              f"`*.fenvix.block2.json` in this directory.", "",
              "| measure | value |", "|---|---|",
              f"| reproduced (status reproduced, exit 0) | {pct(t.get('reproduced', 0), t.get('targets', 0))} |",
              f"| cause named (of reproduced) | {pct(t.get('cause', 0), t.get('reproduced', 0))} |",
              f"| replay N/N with one fingerprint (of reproduced) | {pct(t.get('replay_one_fp', 0), t.get('reproduced', 0))} |",
              f"| replay command printed (of reproduced) | {pct(t.get('replay_cmd', 0), t.get('reproduced', 0))} |",
              "", f"Statuses: {s['statuses']}", "", f"Kinds: {s['kinds']}", "", f"Causes: {s['causes']}", ""]
    if len(argv) > 2:
        base = load(Path(argv[2]), "standalone")
        bt = collections.Counter()
        for data in base.values():
            for b in data.get("bundles", []):
                bt[b.get("status")] += 1
        lines += [f"Baseline ({argv[2]}, `detpy repro`, standalone): statuses {dict(bt)}", ""]
    lines += ["| repo | targets | reproduced | cause named | replay N/N one fp |", "|---|---:|---:|---:|---:|"]
    for name, r in s["per_repo"].items():
        lines.append(f"| {name} | {r.get('targets', 0)} | {r.get('reproduced', 0)} | {r.get('cause', 0)} | "
                     f"{r.get('replay_one_fp', 0)} |")
    (d / "REPORT.md").write_text("\n".join(lines) + "\n")
    (d / "summary.json").write_text(json.dumps(s, indent=1))
    print("\n".join(lines[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
