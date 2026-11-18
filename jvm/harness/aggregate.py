#!/usr/bin/env python3
"""Aggregate the JVM IDoFT round: results/idoft/<project>/summary.json -> REPORT.md + summary.json."""
import glob, json, os, statistics, sys


def pct(a, b):
    return f"{100.0 * a / b:.1f}%" if b else "n/a"


def fmt(x):
    return "" if x is None else f"{100 * x:+.1f}%"


def main():
    d = sys.argv[1]
    S = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(d, "*", "summary.json")))]
    prep = json.load(open(os.path.join(d, "prepare.json"))) if os.path.exists(os.path.join(d, "prepare.json")) else []
    tot = {k: sum(s[k] for s in S) for k in ("tests", "documented_present", "documented_reproduced", "documented_unstable_in_baseline",
                                              "unstable_baseline", "unstable_reproduced", "broken_by_det", "fingerprint_covered", "fingerprinted")}
    slows = [s["slowdown"] for s in S if s.get("slowdown") is not None]
    L = []
    A = L.append
    A("# JVM Level 0 round on IDoFT projects (Maven)\n")
    A(f"Projects measured: {len(S)} (prepared: {len(prep)}; statuses: " +
      ", ".join(f"{k} {sum(1 for p in prep if p['status'] == k)}" for k in sorted({p['status'] for p in prep})) + ").\n")
    A("All numbers MEASURED on GitHub-hosted runners; timings NOISY.\n")
    A(f"* Documented IDoFT tests present in the runs: {tot['documented_present']}; reproduced (fail 10/10 with one fingerprint "
      f"under a --det configuration, pass under another): **{tot['documented_reproduced']}/{tot['documented_present']} = "
      f"{pct(tot['documented_reproduced'], tot['documented_present'])}**.")
    A(f"* Documented tests unstable in our randomised baseline: {tot['documented_unstable_in_baseline']}.")
    A(f"* Tests unstable in the baseline (any test): {tot['unstable_baseline']}; reproduced: **{tot['unstable_reproduced']} = "
      f"{pct(tot['unstable_reproduced'], tot['unstable_baseline'])}**.")
    A(f"* Broken by --det: **{tot['broken_by_det']}** of {tot['tests']} tests.")
    A(f"* Fingerprint coverage (one fingerprint in all 10 seed-0 runs): {tot['fingerprint_covered']}/{tot['fingerprinted']} = "
      f"{pct(tot['fingerprint_covered'], tot['fingerprinted'])}.")
    if slows:
        A(f"* Slowdown of --det (median over projects of the median test-time ratio, quiet serial pass, NOISY): "
          f"**{100 * statistics.median(slows):+.1f}%** (min {100 * min(slows):+.1f}%, max {100 * max(slows):+.1f}%).")
    A("\n| project | jdk | tests | documented (categories) | doc. reproduced | baseline-unstable | reproduced | broken by --det | fingerprint coverage | slowdown | seeds |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in S:
        cats = ", ".join(f"{k} {v}" for k, v in s["documented_categories"].items() if v)
        A(f"| {s['name']} | {s['jdk']} | {s['tests']} | {s['documented_present']} ({cats}) | {s['documented_reproduced']} | "
          f"{s['unstable_baseline']} | {s['unstable_reproduced']} | {s['broken_by_det']} | {s['fingerprint_coverage']} | "
          f"{fmt(s.get('slowdown'))} | "
          f"{s['seeds_explored']}{' (budget)' if s['seed_budget_hit'] else ''} |")
    open(os.path.join(d, "REPORT.md"), "w").write("\n".join(L) + "\n")
    json.dump({"totals": tot, "projects": len(S), "slowdowns": slows}, open(os.path.join(d, "summary.json"), "w"), indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
