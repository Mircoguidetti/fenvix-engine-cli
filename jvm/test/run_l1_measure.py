#!/usr/bin/env python3
"""Level 1 (threads, Kotlin coroutines) under Level 0: measured, not solved.

Runs jvm/fixtures/l1-measure N times without and N times with --det and
reports, per test, how many runs failed in each mode, and, under --det, how
many distinct fingerprints the test produced (1 = reproducible).

  python3 jvm/test/run_l1_measure.py [--runs 10] [--out results/l1-measure.json]
"""
import argparse, glob, json, os, shutil, subprocess, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
FIX = os.path.join(JVM, "fixtures", "l1-measure")


def outcomes():
    out = {}
    for f in glob.glob(os.path.join(FIX, "build/test-results/test/*.xml")):
        for tc in ET.parse(f).getroot().iter("testcase"):
            bad = tc.find("failure") is not None or tc.find("error") is not None
            out[f"{tc.get('classname')}::{tc.get('name')}"] = "failed" if bad else "passed"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(HERE, "results", "l1-measure.json"))
    a = ap.parse_args()
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false")
    res = {"nodet": [], "det": [], "fingerprints": {}, "seconds": {"nodet": [], "det": []}}
    import time
    for mode in ("nodet", "det"):
        for i in range(a.runs):
            shutil.rmtree(os.path.join(FIX, "build/test-results"), ignore_errors=True)
            shutil.rmtree(os.path.join(FIX, ".fenvix"), ignore_errors=True)
            cmd = ["gradle", "test", "-q", "--continue"]
            if mode == "det":
                cmd = ["java", "-jar", AGENT, "run", "--det", "--"] + cmd
            t0 = time.time()
            subprocess.run(cmd, cwd=FIX, env=env, capture_output=True, timeout=900)
            res["seconds"][mode].append(round(time.time() - t0, 2))
            res[mode].append(outcomes())
            if mode == "det":
                for line in open(os.path.join(FIX, ".fenvix", "trace.jsonl")):
                    o = json.loads(line)
                    if o.get("type") == "test":
                        res["fingerprints"].setdefault(o["nodeid"], set()).add(o["fingerprint"])
    tests = sorted(set().union(*[set(r) for r in res["nodet"] + res["det"]]))
    table = []
    for t in tests:
        nd = sum(r.get(t) == "failed" for r in res["nodet"])
        dd = sum(r.get(t) == "failed" for r in res["det"])
        fp = len(res["fingerprints"].get(t.replace("::", "::", 1) + "()", set()) or res["fingerprints"].get(t, set()))
        table.append({"test": t, "failed_without_det": f"{nd}/{a.runs}", "failed_with_det": f"{dd}/{a.runs}", "distinct_fingerprints_det": fp})
        print(f"{t:60} without --det failed {nd}/{a.runs}   with --det failed {dd}/{a.runs}   fingerprints under --det: {fp}")
    print("build+test seconds (NOISY): without", res["seconds"]["nodet"], "with", res["seconds"]["det"])
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"runs": a.runs, "table": table, "seconds": res["seconds"]}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
