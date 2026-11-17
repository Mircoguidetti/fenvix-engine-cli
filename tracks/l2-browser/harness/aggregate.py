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
    rows, flaky_rows, abl_rows = [], [], []
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
            f"{bw and f'{bw:.0f}' or '-'} | {sw and f'{sw:.0f}' or '-'} | {dw and f'{dw:.0f}' or '-'} | "
            f"{f'x{dw / bw:.1f}' if dw and bw else '-'} / {f'x{dw / sw:.1f}' if dw and sw else '-'} | "
            f"{vd.get('stable', '-')}/{vd.get('tests', '-')} ({nd_runs} runs) | {nb} ({nba} always) |")
        base_runs = [x for x in runs if x["label"].startswith("baseline")]
        stress_runs = [x for x in runs if x["label"].startswith("stress")]
        L = lambda o: "P" if o == "passed" else "F" if o in ("failed", "timedOut") else "S" if o == "skipped" else "?"
        for t in r.get("targets") or []:
            k = t.get("matched_key") or t.get("key") or t.get("grep")
            bl = "".join(L((x.get("outcomes") or {}).get(k)) if k in (x.get("outcomes") or {}) else "-" for x in base_runs)
            sl = "".join(L((x.get("outcomes") or {}).get(k)) if k in (x.get("outcomes") or {}) else "-" for x in stress_runs)
            tot["flaky"] += 1
            reps = t.get("replays") or []
            rv = t.get("replay_verify") or {}
            identical = rv.get("status") == "stable" and rv.get("distinct_fingerprints") == 1 and len(reps) >= 10
            tot["replay10"] += len(reps) >= 10
            tot["identical"] += identical
            seeds = t.get("seeds") or {}
            outs = list(reps) + list(seeds.values())
            tot["pass_seed"] += any(o == "passed" for o in outs)
            tot["fail_seed"] += any(o in ("failed", "timedOut") for o in outs)
            fr = t.get("failing_seed_replays") or []
            fv = t.get("failing_seed_verify") or {}
            repro = bool(fr) and all(o in ("failed", "timedOut") for o in fr) and fv.get("distinct_fingerprints") == 1
            tot["fail_seed_repro"] += repro
            rl = "".join(L(o) for o in reps)
            sdl = " ".join(f"{sd}:{L(o)}" for sd, o in seeds.items())
            flaky_rows.append(
                f"| {r['name']} | `{str(k)[:80]}` | {'known' if t.get('known') else 'this job'} | {bl} | {sl} | {t.get('plain_runs', '-')} | {rl} | "
                f"{rv.get('distinct_fingerprints', '-')} | {sdl} | "
                f"{t.get('failing_seed', '-')}: {''.join(L(o) for o in fr)} ({fv.get('distinct_fingerprints', '-')} fp) |"
                + (f" {t['error'][:80]}" if t.get("error") else ""))
        for a in r.get("ablation") or []:
            abl_rows.append(f"| {r['name']} | `{a['key'][:80]}` | {a.get('all-on')} | {a.get('server-off')} | {a.get('net-off')} | {a.get('vtime-off')} | {a.get('seeds-off')} |")
    print("| Project | Tests | Baseline runs (normal+stress) | Flaky | Baseline wall s | Serial wall s | Det wall s | "
          "Slowdown vs configured / serial | Identical fingerprints, full suite | Broken by controls |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    print()
    print("| Project | Flaky test | Source | Baseline (suite) | Stress (suite) | Plain runs (same filter) | Replays --det | Distinct fp | Seeds | Failing seed replays |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(flaky_rows))
    print()
    print("| Project | Broken test | All controls | Server off | Net off | Vtime off | Seeds off |")
    print("|---|---|---|---|---|---|---|")
    print("\n".join(abl_rows))
    print()
    print("| Project | Flaky test | p (baseline, retries 0) | CI retries r | P(failure reported) = p^(r+1) | P(hidden by retries) = p(1-p^r) | CI trace setting | P(a failing attempt traced) |")
    print("|---|---|---|---|---|---|---|---|")
    repos = json.loads((Path(__file__).resolve().parent / "repos.json").read_text())
    for f in sorted(RES.glob("*.json")):
        r = json.loads(f.read_text())
        cfg = repos.get(r.get("name"), {})
        rr, tr = cfg.get("ci_retries"), cfg.get("ci_trace", "-")
        for fl in r.get("flaky") or []:
            b = fl["baseline"]
            p = b.count("F") / len(b) if b else 0
            rep = f"{p ** (rr + 1):.3f}" if rr is not None else "-"
            hid = f"{p * (1 - p ** rr):.3f}" if rr is not None else "-"
            traced = {"on-first-retry": f"{p ** 2:.3f}", "retain-on-failure": f"{p:.3f}"}.get(tr, "-")
            print(f"| {r['name']} | `{fl['key'][:80]}` | {b.count('F')}/{len(b)} = {p:.2f} | {rr if rr is not None else '-'} | {rep} | {hid} | {tr} | {traced} |")
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
