#!/usr/bin/env python3
"""Skip-key tests: a change to each input of the key makes the tests that read it run again.

Fixture jvm/fixtures/skipkeys (Gradle, JUnit 5). One base capture run (A);
then, per scenario: apply one change, capture run (B), decide with
jvm/skip/fenvix_skip.py, revert. A scenario holds when every expected test is
decided RUN with the expected reason, and KeysTest.unchanged() (which reads
none of the changed inputs) is decided REUSE unless the change is global
(runtime, config). A control scenario with no change must reuse every test.

  python3 jvm/test/run_skipkeys.py [--out results/skipkeys.json]
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
FIX = os.path.join(JVM, "fixtures", "skipkeys")
sys.path.insert(0, os.path.join(JVM, "skip"))
import fenvix_skip  # noqa: E402

ALL = ["sk.KeysTest::code()", "sk.KeysTest::fileRead()", "sk.KeysTest::fileProbe()", "sk.KeysTest::dirList()",
       "sk.KeysTest::resource()", "sk.KeysTest::env()", "sk.KeysTest::prop()", "sk.KeysTest::unchanged()",
       "sk.StaticATest::writer()", "sk.StaticBTest::reader()", "sk.DepTest::library()",
       "sk.NeverTest::network()", "sk.NeverTest::writesItsInput()"]
# never reused, whatever changes
NEVER = {"sk.NeverTest::network()": "network", "sk.NeverTest::writesItsInput()": "writes"}


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
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(content)
    return (lambda: open(p, "w").write(old)) if existed else (lambda: os.remove(p))


# name -> (apply() -> revert, extra env, extra gradle args, expected {test: reason}, global?)
SCENARIOS = [
    ("none", lambda: (lambda: None), {}, [], {}, False),
    ("code", lambda: edit("src/main/java/sk/Calc.java", "return a + b;", "return b + a;"), {}, [],
     {"sk.KeysTest::code()": "code"}, False),
    ("file-content", lambda: write("data/input.txt", "input two\n"), {}, [], {"sk.KeysTest::fileRead()": "file"}, False),
    ("file-created", lambda: write("data/flag", "x"), {}, [], {"sk.KeysTest::fileProbe()": "file"}, False),
    ("dir-listing", lambda: write("data/dir/b.txt", "b"), {}, [], {"sk.KeysTest::dirList()": "file"}, False),
    ("resource", lambda: write("src/test/resources/res.txt", "resource two\n"), {}, [], {"sk.KeysTest::resource()": ("resource", "file")}, False),
    ("env-var", lambda: (lambda: None), {"SK_MODE": "fast"}, [], {"sk.KeysTest::env()": "env"}, False),
    ("system-property", lambda: (lambda: None), {}, ["-Dsk.prop=two"], {"sk.KeysTest::prop()": "prop"}, False),
    ("static-writer", lambda: edit("src/test/java/sk/StaticATest.java", '"written by A"', '"written by A, v2"'), {}, [],
     {"sk.StaticATest::writer()": "code", "sk.StaticBTest::reader()": "after"}, False),
    ("runtime-jvm-flag", lambda: (lambda: None), {}, ["-Dsk.jvmarg=-XX:+UseSerialGC"], {t: "runtime" for t in ALL if t not in NEVER}, True),
    ("dependency-version", lambda: (lambda: None), {}, ["-Dsk.lang3=3.15.0"], {t: "config" for t in ALL if t not in NEVER}, True),
    ("config-junit-properties", lambda: write("src/test/resources/junit-platform.properties", "junit.jupiter.displayname.generator.default=org.junit.jupiter.api.DisplayNameGenerator$Standard\n"),
     {}, [], {t: "config" for t in ALL if t not in NEVER}, True),
]


def capture(out, env_extra, args):
    shutil.rmtree(out, ignore_errors=True)
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false", **env_extra)
    env.pop("SK_MODE", None) if "SK_MODE" not in env_extra else None
    cmd = ["java", "-jar", AGENT, "run", "--det", "--deps", f"--out={out}", "--", "gradle", "test", "-q", "--continue"] + args
    r = subprocess.run(cmd, cwd=FIX, env=env, capture_output=True, text=True, timeout=900)
    if not os.path.isdir(os.path.join(out, "deps")):
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("no capture")
    return os.path.join(out, "deps")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "results", "skipkeys.json"))
    ap.add_argument("--work", default="/tmp/fenvix-skipkeys")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    base = capture(os.path.join(a.work, "A"), {}, [])
    mods_a = fenvix_skip.load(base)
    results, ok_all = [], True
    for name, apply, env_extra, args, expected, global_change in SCENARIOS:
        revert = apply()
        try:
            b = capture(os.path.join(a.work, "B-" + name), env_extra, args)
            d = fenvix_skip.decide(mods_a, fenvix_skip.State(fenvix_skip.load(b), FIX))
        finally:
            revert()
        got = {tid: (r[0] if r else None) for (_, tid), r in d.items()}
        ok = True
        expected = dict(expected)
        if not global_change:
            expected.update(NEVER)
        for t, reason in expected.items():
            ok &= got.get(t) in (reason if isinstance(reason, tuple) else (reason,))
        if not global_change:
            for t in ALL:
                if t not in expected:
                    ok &= got.get(t) is None  # everything else reused
        ok_all &= ok
        results.append({"scenario": name, "ok": ok, "expected_rerun": {k: list(v) if isinstance(v, tuple) else v for k, v in expected.items()}, "decisions": got})
        rerun = sorted(t for t, r in got.items() if r)
        print(f"{'ok ' if ok else 'BAD'} {name:24} rerun={len(rerun)}/{len(got)} " +
              ", ".join(f"{t.split('::')[-1]}[{got[t]}]" for t in rerun[:6]) + (" ..." if len(rerun) > 6 else ""))
    json.dump(results, open(a.out, "w"), indent=1)
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
