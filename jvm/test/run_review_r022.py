#!/usr/bin/env python3
"""Review R-022: inputs the JVM skip-with-proof key misses (each scenario is a wrong reuse on claude/jvm-l0).

Fixture jvm/fixtures/review-r022 (Gradle, JUnit 5). One base capture run (A, every test passes);
then, per scenario: apply one change, capture run (B: every test runs, so every decision is checked
against the fresh outcome), decide with jvm/skip/fenvix_skip.py, revert.

A scenario holds when
  * no test is decided REUSE whose fresh outcome in B is not "passed" (no wrong reuse), and
  * every expected test is decided RUN, and
  * for a local change, PlainTest::unchanged() (reads none of the changed inputs) is still REUSE
    (so "rerun everything" is not a fix).

  python3 jvm/test/run_review_r022.py [--only NAME ...] [--out results/review-r022.json]
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
FIX = os.path.join(JVM, "fixtures", "review-r022")
sys.path.insert(0, os.path.join(JVM, "skip"))
import fenvix_skip  # noqa: E402

PLAIN = "rv.PlainTest::unchanged()"


def edit(rel, old, new):
    p = os.path.join(FIX, rel)
    s = open(p).read()
    assert old in s, (rel, old)
    open(p, "w").write(s.replace(old, new))
    return lambda: open(p, "w").write(s)


def write(rel, content):
    p = os.path.join(FIX, rel)
    existed = os.path.exists(p)
    old = open(p).read() if existed else None
    made = []
    d = os.path.dirname(p)
    while not os.path.isdir(d):
        made.append(d)
        d = os.path.dirname(d)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(content)

    def revert():
        if existed:
            open(p, "w").write(old)
        else:
            os.remove(p)
            for m in made:
                os.rmdir(m)
    return revert


def both(*fs):
    def apply():
        rs = [f() for f in fs]
        return lambda: [r() for r in reversed(rs)]
    return apply


HELLO = """package rv;

public class HelloGreeter implements Greeter {
    @Override
    public String greet() {
        return "hello";
    }
}
"""
PLUGIN = """package rv.ext;

public class Plugin {
}
"""
STATE_B = """package rv;

import org.junit.jupiter.api.Test;

/** New test, runs between StateATest and StateCTest (name order) and assigns another value. */
class StateBTest {
    @Test
    void write() {
        Shared.value = 2;
    }
}
"""

# name -> (apply() -> revert, extra gradle args, tests that must be RUN (id prefixes), global?)
SCENARIOS = [
    ("none", lambda: (lambda: None), [], [], False),
    # F1: heap state reached through a static field (GETSTATIC only) and PER_CLASS instance state
    ("heap-state", lambda: edit("src/main/java/rv/Filler.java", 'l.add("a");', 'l.add("a");\n        l.add("b");'), [],
     ["rv.HeapATest::fill()", "rv.HeapBTest::count()", "rv.PerClassTest::a_fill()", "rv.PerClassTest::b_count()"], False),
    # F2: a test added in B writes state that a reused test of A reads
    ("new-writer-test", lambda: write("src/test/java/rv/StateBTest.java", STATE_B), [], ["rv.StateCTest::read()"], False),
    # F3: static initialiser runs once per JVM; later tests read the constant through an inherited reference
    ("inherited-static", lambda: edit("src/main/java/rv/Limits.java", "Integer.valueOf(3)", "Integer.valueOf(4)"), [],
     ["rv.LimitsTest::a_first()", "rv.LimitsTest::b_second()"], False),
    # F4: class metadata read reflectively (annotation default), no code of the class runs
    ("annotation-default", lambda: edit("src/main/java/rv/Cfg.java", "default 3", "default 5"), [], ["rv.AnnoTest::retries()"], False),
    # F5: lookups that found nothing in A
    ("resource-appears", lambda: write("src/test/resources/rv-optional.properties", "mode=custom\n"), [],
     ["rv.LookupTest::resourceAbsent()"], False),
    ("class-appears", lambda: write("src/main/java/rv/ext/Plugin.java", PLUGIN), [], ["rv.LookupTest::classAbsent()"], False),
    ("provider-appears", both(lambda: write("src/test/java/rv/HelloGreeter.java", HELLO),
                              lambda: write("src/test/resources/META-INF/services/rv.Greeter", "rv.HelloGreeter\n")), [],
     ["rv.LookupTest::noProvider()"], False),
    # F6: test arguments read by JUnit (infrastructure) from a classpath file
    ("csv-source-data", lambda: write("src/test/resources/sums.csv", "1,2,4\n"), [], ["rv.CsvTest::sum("], False),
    # F7: a child process reads a repository file
    ("child-process-input", lambda: write("data/proc.txt", "two\n"), [], ["rv.ProcTest::childReadsFile()"], False),
    # F7b: native code (JNI) reads a repository file
    ("native-code-input", lambda: write("data/native.txt", "two\n"), [], ["rv.NativeTest::nativeReadsFile()"], False),
    # F8: a JUnit configuration parameter set by the build (system property read by JUnit itself)
    ("junit-config-parameter", lambda: (lambda: None), ["-Drv.junit.timeout=1ns"], [], True),
]


def build_native():
    """Compile src/native/rvnative.c into build/native/librvnative.so (JNI headers of the JDK running javac)."""
    javac = os.path.realpath(shutil.which("javac"))
    inc = os.path.join(os.path.dirname(os.path.dirname(javac)), "include")
    os.makedirs(os.path.join(FIX, "build", "native"), exist_ok=True)
    subprocess.run(["gcc", "-shared", "-fPIC", "-O2", f"-I{inc}", f"-I{os.path.join(inc, 'linux')}", "-o",
                    os.path.join(FIX, "build", "native", "librvnative.so"), os.path.join(FIX, "src", "native", "rvnative.c")],
                   check=True)


def capture(out, args):
    shutil.rmtree(out, ignore_errors=True)
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false")
    cmd = ["java", "-jar", AGENT, "run", "--det", "--deps", f"--out={out}", "--", "gradle", "test", "-q", "--continue"] + args
    r = subprocess.run(cmd, cwd=FIX, env=env, capture_output=True, text=True, timeout=900)
    if not os.path.isdir(os.path.join(out, "deps")):
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("no capture")
    return os.path.join(out, "deps")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "results", "review-r022.json"))
    ap.add_argument("--work", default="/tmp/fenvix-review-r022")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    build_native()
    base = capture(os.path.join(a.work, "A"), [])
    mods_a = fenvix_skip.load(base)
    bad_a = sorted(t for m in mods_a.values() for t, r in m["tests"].items() if r.get("outcome") != "passed")
    if bad_a:
        raise SystemExit(f"base run A must pass every test, failed: {bad_a}")
    results, ok_all = [], True
    for name, apply, args, must_run, global_change in SCENARIOS:
        if a.only and name not in a.only:
            continue
        revert = apply()
        try:
            b = capture(os.path.join(a.work, "B-" + name), args)
            mods_b = fenvix_skip.load(b)
            d = fenvix_skip.decide(mods_a, fenvix_skip.State(mods_b, FIX))
        finally:
            revert()
        got = {tid: (r[0] if r else None) for (_, tid), r in d.items()}
        fresh = {tid: rec.get("outcome") for m in mods_b.values() for tid, rec in m["tests"].items()}
        wrong = sorted(t for t, r in got.items() if r is None and fresh.get(t) != "passed")
        missing = sorted(p for p in must_run if not any(t.startswith(p) and got[t] is not None for t in got))
        plain_ok = global_change or got.get(PLAIN, "absent") is None
        ok = not wrong and not missing and plain_ok
        ok_all &= ok
        results.append({"scenario": name, "ok": ok, "wrong_reuse": {t: fresh.get(t) for t in wrong},
                        "expected_run_but_reused": missing, "plain_reused": plain_ok, "decisions": got,
                        "fresh_outcomes": fresh})
        print(f"{'ok ' if ok else 'BAD'} {name:24} wrong reuses={len(wrong)} " +
              (f"[{', '.join(t.split('::', 1)[0].split('.')[-1] + '::' + t.split('::', 1)[1] + '=' + str(fresh.get(t)) for t in wrong[:4])}]" if wrong else "") +
              (f" expected RUN but reused: {missing}" if missing else "") + ("" if plain_ok else " PlainTest not reused"))
    json.dump(results, open(a.out, "w"), indent=1)
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
