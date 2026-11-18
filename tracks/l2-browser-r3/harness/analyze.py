#!/usr/bin/env python3
"""Round 3 tables from tracks/l2-browser-r3/results/*.json (stdout, Markdown).

  python3 tracks/l2-browser-r3/harness/analyze.py [results_dir]

E1   per project: tests that failed at least once in the plain (configured workers) or stressed runs, with their
     failure counts and first error line; the round-1/2 targets marked; condition = plain (fails without load) or
     load (fails only under CPU stress).
S3   step 3: broken by the controls on this engine (passes in every plain run, fails in some --det run) vs round 2
     run 4, and hidden by the controls (fails in every plain run, passes in every --det run).
E2   freeze-before-observe: fingerprints in the frozen replays vs control replays.
E5   database clock: fingerprints and outcomes per variant.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "results"
R2 = HERE.parent.parent / "l2-browser-r2"
FAIL = ("failed", "timedOut")
REPOS = json.loads((R2 / "harness" / "repos.json").read_text())


def L(o):
    return "P" if o == "passed" else "F" if o in FAIL else "S" if o == "skipped" else "-" if o is None else "?"


def first_line(e):
    e = re.sub(r"\s+", " ", (e or "").strip())
    return e[:110].replace("|", "/")


def targets_of(name):
    return REPOS.get(name, {}).get("targets") or []


def is_target(name, key):
    for t in targets_of(name):
        if t.get("key") == key or (t["grep"] in key and Path(key.split("::")[0]).name == t["file"]):
            return True
    return False


def hist(runs):
    h, errs = {}, {}
    for r in runs:
        for k, o in (r.get("outcomes") or {}).items():
            h.setdefault(k, []).append(o)
        for k, e in (r.get("errors") or {}).items():
            errs.setdefault(k, e)
    return h, errs


def main():
    summary = {}
    for f in sorted(RES.glob("e1-*.json")):
        r = json.loads(f.read_text())
        name = r["name"]
        if r.get("status") not in ("ok", "running"):
            print(f"### E1 {name}: {r.get('status')}\n")
            continue
        runs = r.get("runs") or []
        groups = {}
        for x in runs:
            ph = x["phase"]
            sel = ph.split("-")[0] if ph.startswith("extra") else "main"
            kind = "stress" if ph.endswith("stress") else "plain" if ph.endswith("plain") else ph
            groups.setdefault((sel, kind), []).append(x)
        print(f"### E1 {name} (run {r.get('run_id')}, {r.get('machine')}, selection `{' '.join(r.get('e1_args') or [])}`)\n")
        n_tests = 0
        rows, flaky_plain, flaky_load, targets_seen = [], [], [], {}
        for sel in sorted({s for s, _ in groups}):
            hp, ep = hist(groups.get((sel, "plain"), []))
            hs, es = hist(groups.get((sel, "stress"), []))
            np_, ns_ = len(groups.get((sel, "plain"), [])), len(groups.get((sel, "stress"), []))
            walls = [x["wall_s"] for x in groups.get((sel, "plain"), []) if x.get("outcomes")]
            print(f"- selection {sel}: {np_} plain runs, {ns_} stressed runs; tests {len(hp)}; median wall plain "
                  f"{sorted(walls)[len(walls)//2] if walls else '-'} s")
            n_tests += len(hp)
            for k in sorted(set(hp) | set(hs)):
                p, s = hp.get(k, []), hs.get(k, [])
                fp, fs = sum(o in FAIL for o in p), sum(o in FAIL for o in s)
                tgt = is_target(name, k)
                if tgt:
                    targets_seen[k] = (fp, len(p), fs, len(s))
                if not fp and not fs:
                    continue
                pp = sum(o == "passed" for o in p) + sum(o == "passed" for o in s)
                always = pp == 0
                cond = "always fails" if always else "plain" if fp else "load"
                if not always:
                    (flaky_plain if fp else flaky_load).append(k)
                rows.append(f"| `{k[:90]}`{' **(target)**' if tgt else ''} | {fp}/{len(p)} | {fs}/{len(s)} | {cond} | "
                            f"{first_line(ep.get(k) or es.get(k))} |")
        print()
        print("| Test | Failed plain | Failed stressed | Condition | First error |")
        print("|---|---|---|---|---|")
        print("\n".join(rows) or "| (none) | | | | |")
        print()
        tl = targets_of(name)
        print(f"Round-1/2 targets ({len(tl)}): " + "; ".join(
            f"`{t['grep'][:50]}` " + (lambda v: f"plain {v[0]}/{v[1]}, stress {v[2]}/{v[3]}" if v else "not in selection")(
                next((v for k, v in targets_seen.items() if t['grep'] in k and Path(k.split('::')[0]).name == t['file']), None))
            for t in tl))
        print()
        summary[name] = {"tests": n_tests, "flaky_plain": len(flaky_plain), "flaky_load_only": len(flaky_load),
                         "targets": len(tl), "targets_failing": sum(1 for v in targets_seen.values() if v[0] or v[2]),
                         "targets_failing_plain": sum(1 for v in targets_seen.values() if v[0])}
        # Step 3: broken / hidden on this engine
        dets = [x for x in runs if x["phase"] == "det"]
        base = [x for x in runs if x["phase"] == "base"] or groups.get(("main", "plain"), [])
        if dets:
            hb, _ = hist(base)
            hd, ed = hist(dets)
            broken = sorted(k for k, v in hd.items() if hb.get(k) and all(o == "passed" for o in hb[k]) and any(o in FAIL for o in v))
            hidden = sorted(k for k, v in hd.items() if hb.get(k) and all(o in FAIL for o in hb[k]) and all(o == "passed" for o in v))
            r2 = json.loads((R2 / "results" / f"{name}.json").read_text()) if (R2 / "results" / f"{name}.json").exists() else {}
            b2 = sorted(b["key"] for b in r2.get("broken_by_controls") or [])
            dv = r.get("det_verify") or {}
            fps = r.get("det_fingerprints") or {}
            stable_pass = sum(1 for k, v in fps.items() if v[0] == "stable" and hd.get(k) and all(o == "passed" for o in hd[k]))
            walls = sorted(x["wall_s"] for x in dets)
            bw = sorted(x["wall_s"] for x in base if x.get("outcomes"))
            print(f"Step 3 ({name}): {len(dets)} --det runs vs {len(base)} plain runs of the suite selection; broken by the "
                  f"controls {len(broken)} of {len(hd)} ({100 * len(broken) / max(1, len(hd)):.1f}%; round 2 run 4: {len(b2)}); "
                  f"hidden by the controls {len(hidden)}; identical fingerprints {dv.get('stable', '-')}/{dv.get('tests', '-')} "
                  f"({stable_pass} passing in every run); reasons {dv.get('reasons')}; slowdown "
                  f"x{(walls[len(walls)//2] / bw[len(bw)//2]) if walls and bw else 0:.1f}\n")
            print(f"- broken now, not in round 2: {[k[:80] for k in broken if k not in b2]}")
            print(f"- broken in round 2, not now: {[k[:80] for k in b2 if k not in broken]}")
            print(f"- broken in both: {len([k for k in broken if k in b2])}")
            print(f"- hidden: {[k[:80] for k in hidden]}")
            print(f"- errors of the broken: " + "; ".join(f"`{k[:60]}`: {first_line(ed.get(k))[:90]}" for k in broken[:12]))
            print()
            summary[name].update({"broken": len(broken), "broken_r2": len(b2), "hidden": len(hidden), "det_tests": len(hd)})
        for F in r.get("freeze") or []:
            fv, cv = F.get("frozen_verify") or {}, F.get("control_verify") or {}
            print(f"E2 `{F['grep'][:60]}`: frozen {''.join(L(o) for o in F['frozen'])} -> {fv.get('distinct_fingerprints')} fp "
                  f"(divergence {(fv.get('divergence') or {}).get('description', '-')[:120]}); control "
                  f"{''.join(L(o) for o in F['control'])} -> {cv.get('distinct_fingerprints')} fp")
        for X in r.get("replay") or []:
            print(f"\nH3 `{X['grep'][:60]}`: seed {X.get('seed')} -> {X.get('seed_outcome')}; printed `{X.get('printed')}` -> "
                  f"{X.get('printed_outcome')}")
        print()
    for f in sorted(RES.glob("e5-*.json")):
        r = json.loads(f.read_text())
        print(f"### E5 {r['name']} (run {r.get('run_id')}): prepare rc {(r.get('e5_prepare') or {}).get('rc')}\n")
        print("| Variant | DB now() | Target | Replays | Distinct fp | First divergence |")
        print("|---|---|---|---|---|---|")
        for V in r.get("e5") or []:
            for T in V["targets"]:
                v = T.get("verify") or {}
                print(f"| {V['variant']} | {V.get('db_now', '')[-40:]} | `{T['grep'][:50]}` | {''.join(L(o) for o in T['replays'])} | "
                      f"{v.get('distinct_fingerprints', '-')} | {((v.get('divergence') or {}).get('description') or '-')[:110]} |")
        print()
    print("summary:", json.dumps(summary))


if __name__ == "__main__":
    main()
