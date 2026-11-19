#!/usr/bin/env python3
"""Review R-022: --det defects (each check fails on claude/jvm-l0).

  iso-maven / iso-gradle   the project isolates each test class in a fresh JVM (Surefire reuseForks=false,
                           Gradle forkEvery=1); --det must keep that isolation (serial is enough for Level 0).
                           Found in the IDoFT round: json-iterator/java (10 "broken by --det", 13 tests never run).
  method-ref-clock         System::currentTimeMillis and Instant::now (method references, invokedynamic) must read
                           the virtual clock under --det.
  method-ref-random        Random::new must be seeded under --det (same value in two --det runs).
  junit4-surefire-2.17     Surefire 2.17's JUnit 4 provider fires testRunStarted(null): the fenvix listener must not
                           throw (found on tyrus: "Test mechanism" error, listener removed, no trace).

  python3 jvm/test/run_review_r022_det.py [--only NAME ...] [--out results/review-r022-det.json]
"""
import argparse, glob, json, os, shutil, subprocess, sys, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
FIX = os.path.join(JVM, "fixtures", "review-r022-det")
FIX4 = os.path.join(JVM, "fixtures", "review-r022-junit4")


def results(fix, tool):
    pat = "build/test-results/test/*.xml" if tool == "gradle" else "target/surefire-reports/TEST-*.xml"
    out = {}
    for f in glob.glob(os.path.join(fix, pat)):
        for tc in ET.parse(f).getroot().iter("testcase"):
            name = tc.get("name") or ""
            tid = f"{tc.get('classname')}::{name}"
            if tc.find("skipped") is not None:
                out[tid] = "skipped"
            else:
                out[tid] = "failed" if (tc.find("failure") is not None or tc.find("error") is not None) else "passed"
    return out


def run(fix, tool, det, log):
    for d in ["build", "target", ".fenvix"]:
        shutil.rmtree(os.path.join(fix, d), ignore_errors=True)
    cmd = ["gradle", "test", "--continue", "-q"] if tool == "gradle" else ["mvn", "-B", "-q", "test", "-Dmaven.test.failure.ignore=true"]
    if det:
        cmd = ["java", "-jar", AGENT, "run", "--det", "--"] + cmd
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false")
    with open(log, "w") as f:
        subprocess.run(cmd, cwd=fix, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=1200)
    rnd = os.path.join(fix, "build" if tool == "gradle" else "target", "rd-out", "random-method-ref.txt")
    trace = os.path.join(fix, ".fenvix", "trace.jsonl")
    return {"tests": results(fix, tool), "random": open(rnd).read() if os.path.exists(rnd) else None,
            "trace_tests": sum(1 for l in open(trace) if '"type":"test"' in l.replace(" ", "")) if os.path.exists(trace) else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "results", "review-r022-det.json"))
    ap.add_argument("--work", default="/tmp/fenvix-review-r022-det")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    want = lambda n: not a.only or n in a.only  # noqa: E731
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"{'ok ' if ok else 'BAD'} {name:24} {json.dumps(detail)[:300]}")

    iso = ["rd.IsoATest::strict()", "rd.IsoBTest::lenient()"]
    det_maven = []
    for tool in ("maven", "gradle"):
        name = f"iso-{tool}"
        if not (want(name) or (tool == "maven" and (want("method-ref-clock") or want("method-ref-random")))):
            continue
        plain = run(FIX, tool, False, os.path.join(a.work, f"{tool}-plain.log"))
        dets = [run(FIX, tool, True, os.path.join(a.work, f"{tool}-det-{i}.log")) for i in (1, 2)]
        if tool == "maven":
            det_maven = dets
        if want(name):
            got_plain = {t: plain["tests"].get(t) for t in iso}
            got_det = [{t: d["tests"].get(t) for t in iso} for d in dets]
            if any(v != "passed" for v in got_plain.values()):
                raise SystemExit(f"fixture broken without --det: {got_plain}")
            check(name, all(v == "passed" for g in got_det for v in g.values()), {"without_det": got_plain, "det": got_det})
    if det_maven:
        if want("method-ref-clock"):
            st = [d["tests"].get("rd.MethodRefTest::clockByMethodReference()") for d in det_maven]
            check("method-ref-clock", all(s == "passed" for s in st), {"det_outcomes": st})
        if want("method-ref-random"):
            vals = [d["random"] for d in det_maven]
            check("method-ref-random", vals[0] is not None and vals[0] == vals[1], {"values_in_two_det_runs": vals})
    if want("junit4-surefire-2.17"):
        r = run(FIX4, "maven", True, os.path.join(a.work, "junit4-det.log"))
        mech = {t: v for t, v in r["tests"].items() if "mechanism" in t.lower() or v != "passed"}
        check("junit4-surefire-2.17", not mech and r["trace_tests"] == 2,
              {"not_passed": mech, "tests_in_trace": r["trace_tests"], "expected_in_trace": 2})
    json.dump(checks, open(a.out, "w"), indent=1)
    sys.exit(0 if checks and all(c["ok"] for c in checks) else 1)


if __name__ == "__main__":
    main()
