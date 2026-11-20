#!/usr/bin/env python3
"""Recheck "broken by --det" for every project of a committed IDoFT round with the current agent.

For each project with a summary.json under --results (the round's output), runs
`jvm_harness.py --mode recheck` (prepare + D --det runs, compared with the recorded baseline) and
writes <project>/<--name> (default recheck-r022.json). Projects run one after another (--jobs N:
N at a time). Then prints the totals: broken by --det now, tests that ran in the baseline and never
under --det now.

  python3 recheck_all.py --results results/idoft-local [--only NAME ...] [--jobs 2] [--agent-rev SHA]
"""
import argparse, concurrent.futures, glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(HERE, "results", "idoft-local"))
    ap.add_argument("--exclude", nargs="*", default=["mercury-platform-core"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--name", default="recheck-r022.json")
    ap.add_argument("--agent-rev", default="")
    ap.add_argument("--work", default="/tmp/jvm-recheck")
    ap.add_argument("--jdks", default="8,11,17")
    ap.add_argument("--runs", type=int, default=10)
    a = ap.parse_args()
    names = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(a.results, "*", "summary.json")))
    names = [n for n in names if n not in a.exclude and (not a.only or n in a.only)]

    def one(n):
        if os.path.exists(os.path.join(a.results, n, a.name)):
            return n, "done before"
        cmd = [sys.executable, os.path.join(HERE, "jvm_harness.py"), "--name", n, "--mode", "recheck", "--out", a.results,
               "--work", os.path.join(a.work, n), "--jdks", a.jdks, "--runs", str(a.runs), "--recheck-name", a.name,
               "--agent-rev", a.agent_rev]
        with open(os.path.join(a.work, n + ".log"), "w") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
        return n, r.returncode

    os.makedirs(a.work, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        for n, rc in ex.map(one, names):
            print(n, rc, flush=True)
    tot = {"projects": 0, "before": 0, "after": 0, "not_run": 0}
    for n in names:
        p = os.path.join(a.results, n, a.name)
        if not os.path.exists(p):
            print(f"{n}: no recheck")
            continue
        s = json.load(open(p))
        if "after" not in s:
            print(f"{n}: {s.get('status')}")
            continue
        tot["projects"] += 1
        tot["before"] += s["before"]
        tot["after"] += s["after"]
        tot["not_run"] += s.get("not_run_under_det", 0)
        print(f"{n}: broken {s['before']} -> {s['after']}, not run under --det {s.get('not_run_under_det')}")
    print(json.dumps(tot))


if __name__ == "__main__":
    main()
