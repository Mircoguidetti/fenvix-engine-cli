#!/usr/bin/env python3
"""Review R-022b (second round): wrong reuses through channels the R-022 fixes do not key.

Fixture jvm/fixtures/review-r022b (Gradle, JUnit 5). Same protocol as run_review_r022.py: one base
capture run A (every test passes), then per scenario: apply one change, capture run B (every test
runs, so every decision is checked against the fresh outcome), decide with jvm/skip/fenvix_skip.py
(the Rust decider), revert.

Every scenario has a writer (rv.<X>ATest, runs first) whose own code changes, so it is rerun, and a
reader (rv.<X>BTest) that is unchanged. The scenario holds when no test is decided REUSE whose fresh
outcome in B is not "passed", the reader is decided RUN, and PlainTest::unchanged() is still REUSE.

  python3 jvm/test/run_review_r022b.py [--only NAME ...] [--out results/review-r022b.json]
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
FIX = os.path.join(JVM, "fixtures", "review-r022b")
sys.path.insert(0, os.path.join(JVM, "skip"))
import fenvix_skip  # noqa: E402

PLAIN = "rv.PlainTest::unchanged()"


def edit(rel, old, new):
    p = os.path.join(FIX, rel)
    s = open(p).read()
    assert old in s, (rel, old)
    open(p, "w").write(s.replace(old, new))
    return lambda: open(p, "w").write(s)


def effect(cls, code):
    return lambda: edit(f"src/test/java/rv/{cls}.java", "/*EFFECT*/", code)


# name -> (apply() -> revert, reader that must be RUN, documented in REPORT-2 §6 as a known residual risk)
SCENARIOS = [
    ("none", lambda: (lambda: None), None, False),
    # JDK global state behind static methods (no GETSTATIC in code under test): java.util.logging
    ("jul-root-level", effect("JulATest", 'java.util.logging.Logger.getLogger("").setLevel(java.util.logging.Level.OFF);'),
     "rv.JulBTest::read()", False),
    # JDK global default (REPORT-2 §6 lists Locale.setDefault as not keyed). The jvm record's runtime has the
    # end-of-JVM locale, so a leak that lasts to the end of the JVM reruns every test; LocaleCTest restores the
    # default after the reader, so the end state is the same and only the reader is affected
    ("locale-default", effect("LocaleATest", 'java.util.Locale.setDefault(new java.util.Locale("de", "DE"));'),
     "rv.LocaleBTest::read()", True),
    # per-thread JDK state: the runner thread's context class loader (used by ServiceLoader, frameworks)
    ("context-class-loader", effect("TcclATest", "Thread.currentThread().setContextClassLoader(new java.net.URLClassLoader(new java.net.URL[0], null));"),
     "rv.TcclBTest::read()", False),
    # class initialisation order: the GETSTATIC in Reg.size() first executes inside Reg.<clinit>, sees null and
    # is classified "constant" for the rest of the JVM, so later reads of the (mutable) list are not `mut`
    ("clinit-null-read", effect("RegATest", 'Reg.ITEMS.add("x");'), "rv.RegBTest::read()", False),
    # JDK-internal cache: ResourceBundle.getBundle caches per (name, loader); the reader hits the cache and reads no resource
    ("resource-bundle-cache", lambda: edit("src/test/resources/rvmsg.properties", "greeting=hello", "greeting=hi"),
     "rv.MsgBTest::read()", False),
    # reflection-driven JDK cache: java.beans.Introspector caches BeanInfo; the reader reflects nothing itself
    ("introspector-cache", lambda: edit("src/main/java/rv/Bean.java", "public int getB() { return b; }",
                                        "public int getB() { return b; }\n    public int getC() { return 0; }"),
     "rv.BeanBTest::read()", False),
    # control: a system property written by a test and read through JDK code (Boolean.getBoolean)
    ("property-via-jdk", effect("PropATest", 'System.setProperty("rv.flag", "true");'), "rv.PropBTest::read()", False),
]


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
    ap.add_argument("--out", default=os.path.join(HERE, "results", "review-r022b.json"))
    ap.add_argument("--work", default="/tmp/fenvix-review-r022b")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    base = capture(os.path.join(a.work, "A"), [])
    mods_a = fenvix_skip.load(base)
    bad_a = sorted(t for m in mods_a.values() for t, r in m["tests"].items() if r.get("outcome") != "passed")
    if bad_a:
        raise SystemExit(f"base run A must pass every test, failed: {bad_a}")
    results, ok_all = [], True
    for name, apply, reader, documented in SCENARIOS:
        if a.only and name not in a.only:
            continue
        revert = apply()
        try:
            b = capture(os.path.join(a.work, "B-" + name), [])
            mods_b = fenvix_skip.load(b)
            d = fenvix_skip.decide(mods_a, fenvix_skip.State(mods_b, FIX))
        finally:
            revert()
        got = {tid: (r[0] if r else None) for (_, tid), r in d.items()}
        fresh = {tid: rec.get("outcome") for m in mods_b.values() for tid, rec in m["tests"].items()}
        wrong = sorted(t for t, r in got.items() if r is None and fresh.get(t) != "passed")
        missing = [reader] if reader and got.get(reader, "absent") is None else []
        plain_ok = got.get(PLAIN, "absent") is None
        ok = not wrong and not missing and plain_ok
        ok_all &= ok
        reader_rec = next((m["tests"][reader] for m in mods_a.values() if reader in m["tests"]), {}) if reader else {}
        results.append({"scenario": name, "ok": ok, "documented_residual": documented, "wrong_reuse": {t: fresh.get(t) for t in wrong},
                        "expected_run_but_reused": missing, "plain_reused": plain_ok, "decisions": got, "fresh_outcomes": fresh,
                        "reader_capture_a": {k: reader_rec.get(k) for k in ("classes", "mut", "swrite", "resources", "props", "after")}})
        print(f"{'ok ' if ok else 'BAD'} {name:24} wrong reuses={len(wrong)} " +
              (f"[{', '.join(t + '=' + str(fresh.get(t)) for t in wrong[:4])}]" if wrong else "") +
              (f" expected RUN but reused: {missing}" if missing else "") + ("" if plain_ok else " PlainTest not reused") +
              (" (documented residual, REPORT-2 §6)" if documented and not ok else ""))
    json.dump(results, open(a.out, "w"), indent=1)
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
