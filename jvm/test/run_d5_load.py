#!/usr/bin/env python3
"""R-022 D5: --det fingerprints of the control suite under machine load.

Runs the control fixture (jvm/fixtures/controls, Gradle, JUnit 5) as N pairs of --det runs while the
machine is loaded the way a shared CI runner is: 2 x CPUs busy loops plus another Gradle build of a
fixture running in a loop next to it. Each pair is verified (`fenvix-jvm verify`); the result lists,
per pair, the tests whose fingerprints differ between the two runs.

  python3 jvm/test/run_d5_load.py [--pairs 5] [--agent jvm/dist/fenvix-agent.jar] [--out results/d5-load.json]

Exit 0 when every pair verifies with identical fingerprints for every test.
"""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
CTL = os.path.join(JVM, "fixtures", "controls")
NEIGHBOUR = os.path.join(JVM, "fixtures", "review-r022-det")


def det_run(agent, work, tag):
    for d in ("build/test-results", ".fenvix"):
        shutil.rmtree(os.path.join(CTL, d), ignore_errors=True)
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false")
    with open(os.path.join(work, tag + ".log"), "w") as f:
        subprocess.run(["java", "-jar", agent, "run", "--det", "--", "gradle", "test", "--continue", "-q"], cwd=CTL, stdout=f,
                       stderr=subprocess.STDOUT, env=env, timeout=1800)
    t = os.path.join(work, tag + ".jsonl")
    shutil.copy(os.path.join(CTL, ".fenvix", "trace.jsonl"), t)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=5)
    ap.add_argument("--agent", default=os.path.join(JVM, "dist", "fenvix-agent.jar"))
    ap.add_argument("--work", default="/tmp/fenvix-d5-load")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "d5-load.json"))
    a = ap.parse_args()
    a.agent = os.path.abspath(a.agent)
    shutil.rmtree(a.work, ignore_errors=True)
    os.makedirs(a.work)
    burners = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(2 * (os.cpu_count() or 2))]
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false")
    neighbour = subprocess.Popen(["bash", "-c", "while true; do gradle test --rerun-tasks -q --continue >/dev/null 2>&1; done"], cwd=NEIGHBOUR,
                                 env=env, start_new_session=True)
    pairs = []
    try:
        for p in range(a.pairs):
            t1 = det_run(a.agent, a.work, f"p{p}-1")
            t2 = det_run(a.agent, a.work, f"p{p}-2")
            v = subprocess.run(["java", "-jar", a.agent, "verify", t1, t2], capture_output=True, text=True).stdout
            summary = next((l.strip() for l in v.splitlines() if "not covered:" in l), "")
            differ = [l.split()[1] for l in v.splitlines() if l.startswith("NOT-COVERED")]
            detail = [l.strip()[:240] for l in v.splitlines() if l.startswith("    runs")]
            pairs.append({"pair": p, "summary": summary, "differ": differ, "detail": detail})
            print(f"pair {p}: {summary} {differ}", flush=True)
    finally:
        for b in burners:
            b.kill()
        os.killpg(neighbour.pid, 9)
    ok = all(not x["differ"] and "missing: 0" in x["summary"] for x in pairs)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"agent": a.agent, "cpus": os.cpu_count(), "pairs": pairs, "ok": ok, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
              open(a.out, "w"), indent=1)
    print(f"{'ok ' if ok else 'BAD'} fingerprints under load: {sum(1 for x in pairs if not x['differ'])}/{len(pairs)} pairs identical")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
