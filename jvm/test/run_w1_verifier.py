#!/usr/bin/env python3
"""R-022 W1: the skip walk's verifier counts an order-dependent wrong reuse as WRONG, not FLAKY.

The reviewer's test (run_review_r022_walk.py) needs a wrong reuse to exist: on claude/jvm-l0 the
decider reused rv.VictimTest::flagIsOff() after a new PolluterTest (finding S2). With S2 fixed the
decider runs VictimTest, so that test has nothing to classify. This test checks both halves:

  1. classify(): the verifier's rule, case by case (no build);
  2. the walk on the reviewer's two-commit repository with an ADVERSARIAL decider that reuses
     every test (it stands in for any wrong reuse): VictimTest must be labelled wrong, with the
     suite rerun recorded as failed, and not flaky;
  3. the same walk with the real decider: VictimTest is not reused (S2), so nothing is wrong.

  python3 jvm/test/run_w1_verifier.py [--work DIR]
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
FIX = os.path.join(JVM, "fixtures", "review-r022")
sys.path.insert(0, os.path.join(JVM, "harness"))
sys.path.insert(0, HERE)

import skip_walk  # noqa: E402
from run_review_r022_walk import POLLUTER, git  # noqa: E402

TID = "rv.VictimTest::flagIsOff()"


def unit():
    ok = True
    cases = [
        # (fresh, alone, suite outcome, expected verdict)
        ("failed", ["passed", "failed"], None, "flaky"),
        ("failed", ["failed", "failed"], None, "wrong"),
        ("failed", [None, None], None, "wrong"),
        ("failed", ["passed", "passed"], "failed", "wrong"),   # order-dependent: polluter
        ("failed", ["passed", "passed"], "passed", "flaky"),   # suite-level non-determinism
    ]
    for fresh, alone, suite, want in cases:
        asked = []

        def s(v=suite):
            asked.append(1)
            return v
        got, _ = skip_walk.classify(fresh, alone, s)
        good = got == want and (bool(asked) == (alone == ["passed", "passed"]))
        ok &= good
        print(f"{'ok ' if good else 'BAD'} classify fresh={fresh} alone={alone} suite={suite} -> {got} (want {want})")
    return ok


def repo(work):
    shutil.rmtree(work, ignore_errors=True)
    src = os.path.join(work, "src")
    shutil.copytree(FIX, src, ignore=shutil.ignore_patterns("build", ".gradle", ".fenvix"))
    with open(os.path.join(src, "gradlew"), "w") as f:
        f.write('#!/bin/sh\nexec gradle "$@"\n')
    os.chmod(os.path.join(src, "gradlew"), 0o755)
    git(src, "init", "-q")
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "add", "-A")
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "commit", "-qm", "base")
    c1 = git(src, "rev-parse", "HEAD")
    with open(os.path.join(src, "src/test/java/rv/PolluterTest.java"), "w") as f:
        f.write(POLLUTER)
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "add", "-A")
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "commit", "-qm", "add PolluterTest")
    c2 = git(src, "rev-parse", "HEAD")
    return src, [c1, c2]


def walk(work, name, src, shas):
    skip_walk.REPOS[name] = {"url": src, "tool": "gradle", "shas": shas}
    out = os.path.join(work, "out")
    sys.argv = ["skip_walk.py", "--repo", name, "--work", os.path.join(work, "walk-" + name), "--out", out]
    skip_walk.main()
    return json.load(open(os.path.join(out, name, "shard0.json")))["rows"][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/fenvix-w1-verifier")
    a = ap.parse_args()
    ok = unit()
    src, shas = repo(a.work)

    real = skip_walk.fenvix_skip.decide
    # 2. adversarial decider: reuse everything the base run had (stands in for a wrong reuse)
    skip_walk.fenvix_skip.decide = lambda mods_a, b: {(mn, t): None for mn, m in mods_a.items() for t in m["tests"]}
    try:
        row = walk(a.work, "w1-adversarial", src, shas)
    finally:
        skip_walk.fenvix_skip.decide = real
    wrong = [w for w in row.get("wrong", []) if w["test"] == TID]
    flaky = [w for w in row.get("flaky", []) if w["test"] == TID]
    good = bool(wrong) and not flaky and wrong[0].get("suite_rerun") == "failed" and wrong[0].get("reruns") == ["passed", "passed"]
    ok &= good
    print(f"{'ok ' if good else 'BAD'} adversarial walk: VictimTest wrong={wrong} flaky={flaky}")

    # 3. the real decider does not reuse VictimTest (S2), so the walk has no wrong reuse
    row = walk(a.work, "w1-real", src, shas)
    good = not row.get("wrong") and not any(w["test"] == TID for w in row.get("flaky", []))
    ok &= good
    print(f"{'ok ' if good else 'BAD'} real decider walk: reused={row.get('reused')} wrong={row.get('wrong')} flaky={row.get('flaky')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
