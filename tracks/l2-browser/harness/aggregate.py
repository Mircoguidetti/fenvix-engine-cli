#!/usr/bin/env python3
"""Tables for tracks/l2-browser/REPORT.md from results/*.json (stdout, Markdown)."""
import json
import sys
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "results"
FAIL = set("F")


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def main():
    rows, flaky_rows = [], []
    tot = {"flaky": 0, "replay10": 0, "identical": 0, "pass_seed": 0, "fail_seed": 0, "fail_seed_repro": 0,
           "tests": 0, "det_tests": 0, "stable": 0, "broken": 0, "broken_always": 0}
    for f in sorted(RES.glob("*.json")):
        r = json.loads(f.read_text())
        if r.get("status") not in ("ok", "running"):
            rows.append(f"| {r['name']} | {r.get('status')} | | | | | | | | |")
            continue
        bw, sw, dw = r.get("baseline_wall_median_s"), r.get("serial_wall_median_s"), r.get("det_wall_median_s")
        vd = r.get("det_verify") or {}
        broken = r.get("broken_by_controls") or []
        nb = len(broken)
        nba = sum(1 for b in broken if b.get("always"))
        tot["tests"] += r.get("tests_baseline") or 0
        tot["det_tests"] += vd.get("tests") or 0
        tot["stable"] += vd.get("stable") or 0
        tot["broken"] += nb
        tot["broken_always"] += nba
        runs = r.get("runs") or []
        nb_runs = sum(1 for x in runs if x["label"].startswith("baseline"))
        ns_runs = sum(1 for x in runs if x["label"].startswith("stress"))
        nd_runs = sum(1 for x in runs if x["label"].startswith("det"))
        rows.append(
            f"| {r['name']} | {r.get('tests_baseline')} | {nb_runs}+{ns_runs} | {len(r.get('flaky') or [])} | "
            f"{bw:.0f} | {sw and f'{sw:.0f}' or '-'} | {dw and f'{dw:.0f}' or '-'} | "
            f"{f'x{dw / bw:.1f}' if dw and bw else '-'} / {f'x{dw / sw:.1f}' if dw and sw else '-'} | "
            f"{vd.get('stable', '-')}/{vd.get('tests', '-')} ({nd_runs} runs) | {nb} ({nba} always) |")
        targets = {t["key"]: t for t in r.get("targets") or []}
        for fl in r.get("flaky") or []:
            k = fl["key"]
            t = targets.get(k)
            tot["flaky"] += 1
            if not t:
                flaky_rows.append(f"| {r['name']} | `{k[:90]}` | {fl['baseline']} | {fl['stress']} | {fl['det']} | not targeted | | | |")
                continue
            reps = t.get("replays") or []
            rv = t.get("replay_verify") or {}
            identical = rv.get("status") == "stable" and rv.get("distinct_fingerprints") == 1 and len(reps) >= 10
            if len(reps) >= 10:
                tot["replay10"] += 1
            if identical:
                tot["identical"] += 1
            seeds = t.get("seeds") or {}
            outs = list(reps) + list(seeds.values())
            ps = any(o == "passed" for o in outs)
            fs = [s for s, o in seeds.items() if o in ("failed", "timedOut")]
            tot["pass_seed"] += ps
            tot["fail_seed"] += bool(fs or any(o in ("failed", "timedOut") for o in reps))
            fr = t.get("failing_seed_replays") or []
            fv = t.get("failing_seed_verify") or {}
            repro = bool(fr) and all(o in ("failed", "timedOut") for o in fr) and fv.get("distinct_fingerprints") == 1
            tot["fail_seed_repro"] += repro
            rl = "".join("P" if o == "passed" else "F" if o in ("failed", "timedOut") else "?" for o in reps)
            sl = " ".join(f"{s}:{'P' if o == 'passed' else 'F' if o in ('failed', 'timedOut') else '?'}" for s, o in seeds.items())
            flaky_rows.append(
                f"| {r['name']} | `{k[:90]}` | {fl['baseline']} | {fl['stress']} | {fl['det']} | {rl} | "
                f"{rv.get('distinct_fingerprints', '-')} | {sl} | "
                f"{t.get('failing_seed', '-')}: {''.join('F' if o in ('failed', 'timedOut') else 'P' for o in fr)} "
                f"({fv.get('distinct_fingerprints', '-')} fp) |")
    print("| Project | Tests | Baseline runs (normal+stress) | Flaky | Baseline wall s | Serial wall s | Det wall s | "
          "Slowdown vs configured / serial | Identical fingerprints, full suite | Broken by controls |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    print()
    print("| Project | Flaky test | Baseline | Stress | Det full runs | 10 replays (default seed) | Distinct fp | Seeds | Failing seed replays |")
    print("|---|---|---|---|---|---|---|---|---|")
    print("\n".join(flaky_rows))
    print()
    print("totals:", json.dumps(tot))
    print(f"- flaky tests: {tot['flaky']}; replayed 10 times: {tot['replay10']}; identical fingerprint 10/10: "
          f"{tot['identical']} ({pct(tot['identical'], tot['flaky'])}); pass in some seed: {tot['pass_seed']}; "
          f"fail in some seed: {tot['fail_seed']}; failing seed replays fail with one fingerprint: {tot['fail_seed_repro']}")
    print(f"- full suites under --det: {tot['stable']}/{tot['det_tests']} tests identical fingerprints "
          f"({pct(tot['stable'], tot['det_tests'])}); broken by controls {tot['broken']} ({tot['broken_always']} always) "
          f"of {tot['tests']} tests")


if __name__ == "__main__":
    sys.exit(main())
