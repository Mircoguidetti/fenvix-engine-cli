#!/usr/bin/env python3
"""Review R-022: the skip walk's verifier must count a wrong reuse as WRONG, not FLAKY.

jvm/harness/skip_walk.py checks every reuse against the fresh outcome; a reused test that does not pass is
rerun alone (its class, twice) and labelled FLAKY as soon as one rerun passes. A wrong reuse caused by state
left by another test (here: a new test, StateBTest, assigns the static field StateCTest reads) fails in the
full suite and passes alone, deterministically: it is a wrong reuse, but the rule labels it flaky, so the
walk's "0 wrong" cannot see this class of error (36 of the 37 commons-lang "flaky" have the same shape:
failed fresh, passed twice alone).

The test builds a two-commit git repository from jvm/fixtures/review-r022 (commit 2 adds StateBTest),
runs skip_walk.main() on it and expects the reuse of rv.StateCTest::read() in "wrong".

  python3 jvm/test/run_review_r022_walk.py [--work DIR]
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
FIX = os.path.join(JVM, "fixtures", "review-r022")
sys.path.insert(0, os.path.join(JVM, "harness"))

STATE_B = """package rv;

import org.junit.jupiter.api.Test;

class StateBTest {
    @Test
    void write() {
        Shared.value = 2;
    }
}
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/fenvix-review-r022-walk")
    a = ap.parse_args()
    shutil.rmtree(a.work, ignore_errors=True)
    src = os.path.join(a.work, "src")
    shutil.copytree(FIX, src, ignore=shutil.ignore_patterns("build", ".gradle", ".fenvix"))
    with open(os.path.join(src, "gradlew"), "w") as f:
        f.write('#!/bin/sh\nexec gradle "$@"\n')
    os.chmod(os.path.join(src, "gradlew"), 0o755)
    git(src, "init", "-q")
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "add", "-A")
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "commit", "-qm", "base")
    c1 = git(src, "rev-parse", "HEAD")
    with open(os.path.join(src, "src/test/java/rv/StateBTest.java"), "w") as f:
        f.write(STATE_B)
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "add", "-A")
    git(src, "-c", "user.name=r", "-c", "user.email=r@invalid", "commit", "-qm", "add StateBTest")
    c2 = git(src, "rev-parse", "HEAD")

    import skip_walk  # noqa: E402
    skip_walk.REPOS["review-r022-walk"] = {"url": src, "tool": "gradle", "shas": [c1, c2]}
    out = os.path.join(a.work, "out")
    sys.argv = ["skip_walk.py", "--repo", "review-r022-walk", "--work", os.path.join(a.work, "walk"), "--out", out]
    skip_walk.main()
    res = json.load(open(os.path.join(out, "review-r022-walk", "shard0.json")))
    row = res["rows"][1]
    tid = "rv.StateCTest::read()"
    wrong = [w for w in row.get("wrong", []) if w["test"] == tid]
    flaky = [w for w in row.get("flaky", []) if w["test"] == tid]
    ok = bool(wrong) and not flaky
    print(f"{'ok ' if ok else 'BAD'} walk-verifier  reused={row.get('reused')} wrong={row.get('wrong')} flaky={row.get('flaky')}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
