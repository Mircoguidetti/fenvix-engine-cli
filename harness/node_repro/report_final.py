"""Aggregate the rows of run_shared.py (one CI run of .github/workflows/node-repro.yml) into REPORT.md and summary.json.

    python harness/node_repro/report_final.py DIR [--run-id N] [--engine SHA]

DIR holds `<repo>[.<kind>].<shard>.jsonl` (kind: replay, shared; none: one row per test). Definitions (the same as
report.py):
  set            the baseline-unstable tests of node-final (flaky_set.py), Vitest and Jest; matrix-js-sdk-flaky
                 reported apart (node-final had no trace for it)
  attempted      a `fenvix repro` verdict was produced for the test (not: repository not prepared, budget exhausted)
  REPRODUCED     status `reproduced`: a failing configuration found, minimised, and the bundle failed 10/10 replays
                 with one fingerprint
  cause named    a reproduced bundle whose cause names something (polluter, setter, a divergent event, a seed)
  replay         `fenvix replay --runs 10` of each REPRODUCED bundle in a fresh process from a cleaned tree: 10/10
                 failed with one fingerprint, the bundle's
  stable id      the test's Block 1 id carried run-dependent values; repro used its stable id under --det
  time per test  the test's own wall time plus its share of the repository shard's shared full-suite runs
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flaky_set  # noqa: E402
import report as R  # noqa: E402  (cause_class)

APART = {"matrix-js-sdk-flaky"}


def load(d: Path):
    rows, replays, shared = [], {}, []
    for f in sorted(d.glob("*.jsonl")):
        parts = f.name.split(".")
        kind = parts[1] if len(parts) == 4 else ""
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if kind == "replay":
                replays[(r["repo"], r["test"])] = r
            elif kind == "shared":
                shared.append(r)
            else:
                rows.append(r)
    return rows, replays, shared


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--run-id", default="?")
    ap.add_argument("--engine", default="?")
    args = ap.parse_args(argv)
    d = Path(args.dir)
    rows, replays, shared = load(d)
    sets = {r["name"]: r for r in flaky_set.repos() if r["runner"] in ("vitest", "jest") and r["unstable"]}
    share = {}  # (repo, shard) -> shared seconds per attempted test
    for s in shared:
        n = sum(1 for r in rows if r["repo"] == s["repo"] and r.get("shard") == s["shard"] and r.get("bundle"))
        share[(s["repo"], s["shard"])] = s["shared_seconds"] / n if n else 0
    groups = {"set": [n for n in sets if n not in APART], "apart": [n for n in sets if n in APART]}
    out = {}
    lines = [f"# `fenvix repro` on the Node Block 1 flaky set, every test (MEASURED, CI run {args.run_id})", "",
             f"Engine {args.engine}. Rows: `run_shared.py` (in-process `fenvix repro` per test; full-suite search runs "
             "shared per repository shard), aggregated by `report_final.py` (definitions in its docstring). "
             "GitHub-hosted ubuntu-latest runners, Node 22.", "",
             "| repo | runner | tests in set | attempted | REPRODUCED | cause named | separate replay 10/10 | stable id used "
             "| not collected | not-found | other | median s/test | causes |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    detail = []
    for gname, names in groups.items():
        t = {"set": 0, "attempted": 0, "reproduced": 0, "named": 0, "replay_ok": 0, "replay_n": 0, "stable": 0,
             "stable_distinct": set(), "not_collected": 0, "not_found": 0, "other": 0, "not_attempted": 0,
             "times": [], "statuses": {}}
        for name in sorted(names):
            st = sets[name]
            rs = [r for r in rows if r["repo"] == name and r.get("test")]
            att = [r for r in rs if r["status"] not in ("not-attempted-budget",)]
            prepared = any(r for r in rows if r["repo"] == name and r.get("status") != "not-prepared")
            rep = [r for r in att if r["status"] == "reproduced"]
            named = [r for r in rep if R.cause_class(r["bundle"]) not in ("not-named", "-")]
            ind = [replays[(name, r["test"])] for r in rep if (name, r["test"]) in replays]
            ind_ok = [x for x in ind if x.get("fails") == x.get("runs") == 10 and x.get("identical_fingerprint")
                      and x.get("matches_bundle")]
            stab = [r for r in att if r.get("stable_id")]
            nc = [r for r in att if r["status"] in ("not-collected", "not-collected-suite")]
            nf = [r for r in att if r["status"] == "not-found"]
            oth = [r for r in att if r["status"] not in ("reproduced", "not-collected", "not-collected-suite", "not-found")]
            times = [r["wall_s"] + share.get((name, r.get("shard")), 0) for r in att if r.get("bundle")]
            causes: dict = {}
            for r in att:
                c = R.cause_class(r.get("bundle")) if r["status"] in ("reproduced", "replay-unstable") else r["status"]
                causes[c] = causes.get(c, 0) + 1
            for k, v in (("set", len(st["targets"])), ("attempted", len(att)), ("reproduced", len(rep)),
                         ("named", len(named)), ("replay_ok", len(ind_ok)), ("replay_n", len(ind)),
                         ("stable", len(stab)), ("not_collected", len(nc)), ("not_found", len(nf)), ("other", len(oth)),
                         ("not_attempted", len(st["targets"]) - len(att))):
                t[k] += v
            t["stable_distinct"] |= {(name, r["stable_id"]) for r in stab}
            t["times"] += times
            for r in att:
                t["statuses"][r["status"]] = t["statuses"].get(r["status"], 0) + 1
            lines.append(f"| {name}{' (apart)' if gname == 'apart' else ''} | {st['runner']} {st['runner_version']} | "
                         f"{len(st['targets'])} | {len(att)}{'' if prepared else ' (not prepared)'} | {len(rep)} | "
                         f"{len(named)} | {len(ind_ok)}/{len(ind)} | {len(stab)} | {len(nc)} | {len(nf)} | {len(oth)} | "
                         f"{round(statistics.median(times), 1) if times else '-'} | "
                         f"{', '.join(f'{k} {v}' for k, v in sorted(causes.items()))} |")
            for r in rs:
                b = r.get("bundle") or {}
                rp = b.get("replay") or {}
                x = replays.get((name, r["test"])) or {}
                detail.append(f"| {name} | `{r['test'][:140]}` | {r['status']} | {R.cause_class(b)} | "
                              f"{rp.get('fails', '-')}/{rp.get('runs', '-')} | {x.get('fails', '-')}/{x.get('runs', '-')} | "
                              f"{'`' + r['stable_id'][:80] + '`' if r.get('stable_id') else ''} | {r['wall_s']} |")
        t["stable_distinct"] = len(t["stable_distinct"])
        t["median_s"] = round(statistics.median(t["times"]), 1) if t["times"] else None
        t["mean_s"] = round(statistics.mean(t["times"]), 1) if t["times"] else None
        del t["times"]
        out[gname] = t
    s = out["set"]
    a = s["attempted"]
    pct = lambda n, m: f"{n}/{m} = {100 * n / m:.1f} %" if m else f"{n}/0"  # noqa: E731
    lines += ["", f"**Totals, set (Vitest/Jest, without matrix-js-sdk-flaky): {s['set']} tests.** Attempted "
              f"{pct(a, s['set'])}; REPRODUCED {pct(s['reproduced'], a)} of attempted; cause named "
              f"{pct(s['named'], a)}; separate replay 10/10 with the bundle's fingerprint {s['replay_ok']}/{s['replay_n']}"
              f"; reproduced through a stable id {s['stable']} (ids with run-dependent values; {s['stable_distinct']} "
              f"distinct tests); not collected {s['not_collected']}; not reproduced under the fixed order and seeds "
              f"1..20 (`not-found`) {s['not_found']}; other verdicts {s['other']}; not attempted {s['not_attempted']}; "
              f"time per test median {s['median_s']} s, mean {s['mean_s']} s. Verdicts: "
              f"{', '.join(f'{k} {v}' for k, v in sorted(s['statuses'].items()))}.", ""]
    m = out["apart"]
    lines += [f"**matrix-js-sdk-flaky (apart):** {m['set']} tests, attempted {m['attempted']}, REPRODUCED "
              f"{m['reproduced']}, not-found {m['not_found']}, other {m['other']}; verdicts "
              f"{', '.join(f'{k} {v}' for k, v in sorted(m['statuses'].items()))}.", "",
              "## Per test", "",
              "| repo | test | status | cause | bundle replays failed | separate replay failed | stable id | wall s |",
              "|---|---|---|---|---|---|---|---:|", *detail]
    (d / "REPORT.md").write_text("\n".join(lines) + "\n")
    (d / "summary.json").write_text(json.dumps({"run_id": args.run_id, "engine": args.engine, **out}, indent=1))
    print("\n".join(lines[:8 + len(sets) + 4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
