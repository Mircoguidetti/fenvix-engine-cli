#!/usr/bin/env python3
"""Control tests of the JVM shell, Gradle and Maven.

For each build tool: two runs without --det and two runs with --det on the
fixture jvm/fixtures/controls. A control test passes the check when it fails
in at least one run without --det and passes in both runs with --det; the two
--det traces must also verify with identical fingerprints for every test.
Tests named in UNCHANGED must pass in every run (--det does not change
deterministic outcomes). Exit code 0 only if every check holds.

  python3 jvm/test/run_controls.py [--tools gradle,maven] [--out results.json]
"""
import argparse, glob, json, os, shutil, subprocess, sys, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
FIXTURES = {"junit5": os.path.join(JVM, "fixtures", "controls"), "junit4": os.path.join(JVM, "fixtures", "controls-junit4")}
FIX = FIXTURES["junit5"]
# tests that are deterministic without --det too (they must pass everywhere)
UNCHANGED = {"fx.SchedControlTest::timersFireInDueOrder()", "fx.SchedControlTest::shorterTimeoutStillExpiresFirst()",
             "fx.NetControlTest::loopbackIsAllowed()", "fx.SleepControlTest::busyWaitOnTheClockEnds()",
             "fx.UnchangedTest::arithmetic()", "fx.UnchangedTest::sortedCollections()", "fx.UnchangedTest::stringFormat()",
             "fx.OrderControlTest::polluter()",
             "fx4.Junit4UnchangedTest::a()", "fx4.Junit4UnchangedTest::b()", "fx4.Junit4UnchangedTest::c()", "fx4.Junit4UnchangedTest::d()"}


def results(tool):
    pat = "build/test-results/test/*.xml" if tool == "gradle" else "target/surefire-reports/TEST-*.xml"
    out = {}
    for f in glob.glob(os.path.join(FIX, pat)):
        for tc in ET.parse(f).getroot().iter("testcase"):
            name = tc.get("name")
            if not name.endswith(")"):
                name += "()"
            tid = f"{tc.get('classname')}::{name}"
            bad = tc.find("failure") is not None or tc.find("error") is not None
            out[tid] = "skipped" if tc.find("skipped") is not None else ("failed" if bad else "passed")
    return out


def run(tool, det, i, log):
    for d in ["build/test-results", "target/surefire-reports", ".fenvix"]:
        shutil.rmtree(os.path.join(FIX, d), ignore_errors=True)
    cmd = ["gradle", "test", "--continue", "-q"] if tool == "gradle" else ["mvn", "-B", "-q", "test", "-Dmaven.test.failure.ignore=true"]
    if det:
        cmd = ["java", "-jar", AGENT, "run", "--det", "--"] + cmd
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false")
    with open(log, "w") as f:
        subprocess.run(cmd, cwd=FIX, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=1200)
    r = results(tool)
    trace = None
    if det:
        trace = os.path.join(os.path.dirname(log), f"{tool}-det-{i}.jsonl")
        shutil.copy(os.path.join(FIX, ".fenvix", "trace.jsonl"), trace)
    return r, trace


def order_of(trace):
    out = []
    for line in open(trace):
        o = json.loads(line)
        if o.get("type") == "test":
            out.append(o["nodeid"])
    return out


def seed_check(tool, logs, fxname):
    """--det-seed=N: the same order in two runs with N, a different order from seed 0."""
    orders = {}
    for seed, i in ((0, 1), (5, 1), (5, 2)):
        for d in ["build/test-results", "target/surefire-reports", ".fenvix"]:
            shutil.rmtree(os.path.join(FIX, d), ignore_errors=True)
        cmd = ["gradle", "test", "--continue", "-q"] if tool == "gradle" else ["mvn", "-B", "-q", "test", "-Dmaven.test.failure.ignore=true"]
        cmd = ["java", "-jar", AGENT, "run", f"--det-seed={seed}", "--"] + cmd
        with open(os.path.join(logs, f"{fxname}-{tool}-seed{seed}-{i}.log"), "w") as f:
            subprocess.run(cmd, cwd=FIX, stdout=f, stderr=subprocess.STDOUT, env=dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false"), timeout=1200)
        orders[(seed, i)] = order_of(os.path.join(FIX, ".fenvix", "trace.jsonl"))
    same = orders[(5, 1)] == orders[(5, 2)]
    differs = orders[(5, 1)] != orders[(0, 1)]
    complete = sorted(orders[(5, 1)]) == sorted(orders[(0, 1)]) and len(orders[(0, 1)]) > 0
    return {"same_order_same_seed": same, "seed5_differs_from_seed0": differs, "same_tests": complete,
            "ok": same and differs and complete}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", default="gradle,maven")
    ap.add_argument("--fixtures", default="junit5,junit4")
    ap.add_argument("--out", default=os.path.join(JVM, "test", "results", "controls.json"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    logs = os.path.join(os.path.dirname(a.out), "logs")
    os.makedirs(logs, exist_ok=True)
    ok_all = True
    report = {}
    global FIX
    combos = [(fx, tool) for fx in a.fixtures.split(",") for tool in a.tools.split(",")]
    for fxname, tool in combos:
        FIX = FIXTURES[fxname]
        state = os.path.join(FIX, "build" if tool == "gradle" else "target", "fx-state")
        runs = {}
        for det in (False, True):
            shutil.rmtree(state, ignore_errors=True)
            for i in (1, 2):
                runs[(det, i)] = run(tool, det, i, os.path.join(logs, f"{fxname}-{tool}-{'det' if det else 'nodet'}-{i}.log"))
        tests = sorted(set().union(*[set(r[0]) for r in runs.values()]))
        rows = []
        for t in tests:
            nd = [runs[(False, i)][0].get(t, "missing") for i in (1, 2)]
            dd = [runs[(True, i)][0].get(t, "missing") for i in (1, 2)]
            if t in UNCHANGED:
                ok = all(x == "passed" for x in nd + dd)
                kind = "unchanged"
            else:
                ok = any(x != "passed" for x in nd) and all(x == "passed" for x in dd)
                kind = "control"
            ok_all &= ok
            rows.append({"test": t, "kind": kind, "without_det": nd, "with_det": dd, "ok": ok})
        v = subprocess.run(["java", "-jar", AGENT, "verify", runs[(True, 1)][1], runs[(True, 2)][1]], capture_output=True, text=True)
        vtext = v.stdout
        identical = "not covered: 0" in vtext and "missing: 0" in vtext
        ok_all &= identical
        seeds = seed_check(tool, logs, fxname)
        ok_all &= seeds["ok"]
        report[f"{fxname}-{tool}"] = {"rows": rows, "verify": vtext, "fingerprints_identical": identical, "seed_exploration": seeds}
        print(f"== {fxname} {tool}: seed exploration {seeds}")
        print(f"== {fxname} {tool}: {sum(r['ok'] for r in rows)}/{len(rows)} checks hold; fingerprints identical across --det runs: {identical}")
        for r in rows:
            print(f"  {'ok ' if r['ok'] else 'BAD'} {r['kind']:9} {r['test']}  without={','.join(r['without_det'])}  det={','.join(r['with_det'])}")
    json.dump(report, open(a.out, "w"), indent=1)
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
