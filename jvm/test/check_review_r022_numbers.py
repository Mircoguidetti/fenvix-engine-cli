#!/usr/bin/env python3
"""Review R-022: re-derive the headline numbers of the P-022 report from the committed results.

Claims (P-022 REPORT.md, sessions/2026-11-18-jvm-l0) are embedded below; each is recomputed from
jvm/harness/results/ (present on claude/jvm-l0). Exit 1 when a claim does not match the committed data.

  python3 jvm/test/check_review_r022_numbers.py
"""
import glob, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(os.path.dirname(HERE), "harness", "results")
GHA_RUN_44385794604 = ["Java-WebSocket", "Mapper-base", "avro-ipc-jetty", "biojava-biojava-structure", "fastjson", "http-request-lib",
                       "java", "junit-quickcheck-core", "openhtmltopdf-openhtmltopdf-examples", "ormlite-core"]
KEYS = ("tests", "documented_present", "documented_reproduced", "unstable_baseline", "unstable_reproduced", "broken_by_det",
        "fingerprint_covered", "fingerprinted")


def summaries(d, names=None, exclude=()):
    out = []
    for p in sorted(glob.glob(os.path.join(RES, d, "*", "summary.json"))):
        n = os.path.basename(os.path.dirname(p))
        if (names is None or n in names) and n not in exclude:
            out.append((n, json.load(open(p))))
    return out


def main():
    checks = []

    def check(name, claimed, got):
        checks.append(claimed == got)
        print(f"{'ok ' if claimed == got else 'BAD'} {name:58} claimed {claimed}  committed {got}")

    gha = summaries("idoft", GHA_RUN_44385794604)
    t = {k: sum(s[k] for _, s in gha) for k in KEYS}
    check("GHA run 44385794604: projects", 10, len(gha))
    check("GHA: documented reproduced / present", (94, 469), (t["documented_reproduced"], t["documented_present"]))
    check("GHA: baseline-unstable reproduced / unstable", (59, 94), (t["unstable_reproduced"], t["unstable_baseline"]))
    check("GHA: broken by --det", 22, t["broken_by_det"])
    check("GHA: fingerprint coverage", (7777, 7914), (t["fingerprint_covered"], t["fingerprinted"]))

    loc = summaries("idoft-local", exclude=("mercury-platform-core",))
    t = {k: sum(s[k] for _, s in loc) for k in KEYS}
    check("container: projects", 28, len(loc))
    check("container: tests", 12226, t["tests"])
    check("container: documented reproduced / present", (171, 542), (t["documented_reproduced"], t["documented_present"]))
    check("container: baseline-unstable reproduced / unstable", (63, 105), (t["unstable_reproduced"], t["unstable_baseline"]))
    check("container: broken by --det before the last fixes", 35, t["broken_by_det"])
    # "after the last fixes": the committed rechecks (10 new --det runs on the final agent) replace a project's count
    after = 0
    for n, s in loc:
        rp = os.path.join(RES, "idoft-local", n, "recheck.json")
        after += json.load(open(rp))["after"] if os.path.exists(rp) else s["broken_by_det"]
    check("container: broken by --det after the last fixes (rechecks)", 29, after)
    sl = [s["slowdown"] for _, s in loc if s.get("slowdown") is not None]
    check("container: slowdown median (projects with timing)", (23, -0.032), (len(sl), round(statistics.median(sl), 3)))

    # tests that ran in the baseline but never ran under --det (seed 0) are in no column of the report
    dropped = []
    for d, names in (("idoft", GHA_RUN_44385794604), ("idoft-local", None)):
        for n, _ in summaries(d, names, ("mercury-platform-core",)):
            for r in json.load(open(os.path.join(RES, d, n, "tests.json"))):
                if r["det"] == "0F/0P" and r["baseline"] != "0F/0P":
                    dropped.append(f"{d}/{n}:{r['test']}")
    check("tests silently not run under --det (reported: none)", 0, len(dropped))

    walk = json.load(open(os.path.join(RES, "skip", "summary.json")))["repos"]
    six = ["commons-lang", "commons-io", "jackson-databind", "gson", "mockito", "moshi"]
    check("skip walk GHA: verified reuses (6 repositories)", 5731740, sum(walk[r]["verified"] for r in six))
    check("skip walk GHA: wrong", 0, sum(walk[r]["wrong"] for r in six))
    check("skip walk GHA: flaky / not verifiable", (37, 22), (sum(walk[r]["flaky"] for r in six), sum(walk[r]["not_verifiable"] for r in six)))
    sys.exit(0 if all(checks) else 1)


if __name__ == "__main__":
    main()
