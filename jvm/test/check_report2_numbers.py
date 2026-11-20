#!/usr/bin/env python3
"""Numbers of sessions/2026-11-18-jvm-l0/REPORT-2.md, recomputed from the committed results.

Same computations as the reviewer's jvm/test/check_review_r022_numbers.py (which embeds the
P-022 claims, 29 and 0, and therefore reports those two as BAD by construction), checked against
the corrected claims of REPORT-2, plus the rechecks made after the R-022 fixes
(<project>/recheck-r022.json, written by jvm/harness/recheck_all.py).

  python3 jvm/test/check_report2_numbers.py
"""
import glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_review_r022_numbers import GHA_RUN_44385794604, RES, summaries  # noqa: E402

# REPORT-2 claims (section "Numbers")
CLAIM_AFTER_P022 = 25          # broken by --det after the P-022 fixes (committed rechecks, P-022 agent)
CLAIM_NOT_RUN_P022 = (13, 13)  # tests that ran in the baseline and never under --det (GHA run, container), P-022 rounds
CLAIM_R022 = json.load(open(os.path.join(HERE, "results", "report2-claims.json"))) if os.path.exists(
    os.path.join(HERE, "results", "report2-claims.json")) else None


def main():
    checks = []

    def check(name, claimed, got):
        checks.append(claimed == got)
        print(f"{'ok ' if claimed == got else 'BAD'} {name:64} claimed {claimed}  committed {got}")

    loc = summaries("idoft-local", exclude=("mercury-platform-core",))
    after = 0
    for n, s in loc:
        rp = os.path.join(RES, "idoft-local", n, "recheck.json")
        after += json.load(open(rp))["after"] if os.path.exists(rp) else s["broken_by_det"]
    check("container: broken by --det after the P-022 fixes (rechecks)", CLAIM_AFTER_P022, after)
    dropped = {}
    for d, names in (("idoft", GHA_RUN_44385794604), ("idoft-local", None)):
        dropped[d] = 0
        for n, _ in summaries(d, names, ("mercury-platform-core",)):
            for r in json.load(open(os.path.join(RES, d, n, "tests.json"))):
                if r["det"] == "0F/0P" and r["baseline"] != "0F/0P":
                    dropped[d] += 1
    check("ran in the baseline, never under --det (GHA, container), P-022", CLAIM_NOT_RUN_P022, (dropped["idoft"], dropped["idoft-local"]))
    if CLAIM_R022:
        rows = {}
        for n, s in loc:
            rp = os.path.join(RES, "idoft-local", n, "recheck-r022.json")
            if os.path.exists(rp):
                rows[n] = json.load(open(rp))
        ok = {n: r for n, r in rows.items() if "after" in r}
        check("container rechecks after R-022: projects", CLAIM_R022["projects"], len(ok))
        check("container rechecks after R-022: broken by --det", CLAIM_R022["broken"], sum(r["after"] for r in ok.values()))
        check("container rechecks after R-022: not run under --det", CLAIM_R022["not_run"], sum(r.get("not_run_under_det", 0) for r in ok.values()))
    sys.exit(0 if all(checks) else 1)


if __name__ == "__main__":
    main()
