#!/usr/bin/env python3
"""R-022b item 4: the immutability refinements of the shared-state rule do not reuse wrongly.

Fixture jvm/fixtures/narrowing (Gradle, JUnit 5). Same protocol as run_review_r022b.py: one base capture
run A, then per scenario one change, capture run B (every test runs), decide with the Rust decider,
revert. Two kinds of checks:

* probes (nw.Probe*Test): each reads only state that cannot change after class initialisation, of a
  kind the refined rule calls immutable (R1 deep final fields of a non-final class, R1 a non-capturing
  lambda, R2 an enum's values(), R3 List.of / Optional.of of immutable elements). In A each must not be
  `mut` (that is the narrowing).
* twins (nw.<X>ATest writer, nw.<X>BTest reader): the same shapes made mutable (a final field holding a
  mutable list, a runtime subclass with a mutable field, an enum with a mutable instance field, List.of /
  Optional.of of mutable elements, a lambda capturing a counter, a ThreadLocal, a final static read as
  null inside its own <clinit>). The scenario makes the writer mutate the state; the reader must be
  decided RUN, no test may be reused whose fresh outcome is not "passed", PlainTest must stay reused.

  python3 jvm/test/run_r022b_narrowing.py [--agent JAR] [--only NAME ...] [--out results/r022b-narrowing.json]
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
FIX = os.path.join(JVM, "fixtures", "narrowing")
sys.path.insert(0, os.path.join(JVM, "skip"))
import fenvix_skip  # noqa: E402

PLAIN = "nw.PlainTest::unchanged()"
PROBES = ["nw.ProbeDeepFinalTest::read()", "nw.ProbeEnumValuesTest::read()", "nw.ProbeListOfTest::read()",
          "nw.ProbeOptionalTest::read()", "nw.ProbeLambdaTest::read()"]


def effect(cls, code):
    def apply():
        p = os.path.join(FIX, "src", "test", "java", "nw", cls + ".java")
        s = open(p).read()
        assert "/*EFFECT*/" in s, cls
        open(p, "w").write(s.replace("/*EFFECT*/", code))
        return lambda: open(p, "w").write(s)
    return apply


SCENARIOS = [
    ("none", lambda: (lambda: None), None),
    ("deep-final-mutable-list", effect("BoxATest", 'State.BOX.items().add("b");'), "nw.BoxBTest::read()"),
    ("runtime-subclass-mutable", effect("SubATest", "((State.Sub) State.SUB).bump();"), "nw.SubBTest::read()"),
    ("enum-values-mutable-constant", effect("CounterATest", "State.Counter.values()[0].bump();"), "nw.CounterBTest::read()"),
    ("list-of-mutable-element", effect("BuildersATest", 'State.BUILDERS.get(0).append("y");'), "nw.BuildersBTest::read()"),
    ("optional-of-mutable", effect("OptMutATest", "State.OPT_MUT.get().incrementAndGet();"), "nw.OptMutBTest::read()"),
    ("capturing-lambda", effect("BumpedATest", "State.BUMPED.getAsInt();"), "nw.BumpedBTest::read()"),
    ("thread-local", effect("TlATest", 'State.TL.set("x");'), "nw.TlBTest::read()"),
    ("clinit-null-single-site", effect("RegATest", 'Reg.ITEMS.add("x");'), "nw.RegBTest::read()"),
]


def capture(agent, out):
    shutil.rmtree(out, ignore_errors=True)
    env = dict(os.environ, GRADLE_OPTS="-Dorg.gradle.daemon=false")
    cmd = ["java", "-jar", agent, "run", "--det", "--deps", f"--out={out}", "--", "gradle", "test", "-q", "--continue"]
    r = subprocess.run(cmd, cwd=FIX, env=env, capture_output=True, text=True, timeout=900)
    if not os.path.isdir(os.path.join(out, "deps")):
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("no capture")
    return os.path.join(out, "deps")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default=os.path.join(JVM, "dist", "fenvix-agent.jar"))
    ap.add_argument("--out", default=os.path.join(HERE, "results", "r022b-narrowing.json"))
    ap.add_argument("--work", default="/tmp/fenvix-r022b-narrowing")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    mods_a = fenvix_skip.load(capture(a.agent, os.path.join(a.work, "A")))
    recs = {t: r for m in mods_a.values() for t, r in m["tests"].items()}
    bad_a = sorted(t for t, r in recs.items() if r.get("outcome") != "passed")
    if bad_a:
        raise SystemExit(f"base run A must pass every test, failed: {bad_a}")
    ok_all = True
    probes = {}
    for p in PROBES:
        r = recs.get(p, {})
        ok = p in recs and not r.get("mut")
        ok_all &= ok
        probes[p] = {"mut": r.get("mut"), "mut_classes": r.get("mut_classes")}
        print(f"{'ok ' if ok else 'BAD'} probe {p:40} mut={r.get('mut')} {r.get('mut_classes') or ''}")
    results = []
    for name, apply, reader in SCENARIOS:
        if a.only and name not in a.only:
            continue
        if reader:
            rr = recs.get(reader, {})
            print(f"    reader {reader} in A: mut={rr.get('mut')} {rr.get('mut_classes') or ''}")
        revert = apply()
        try:
            mods_b = fenvix_skip.load(capture(a.agent, os.path.join(a.work, "B-" + name)))
            d = fenvix_skip.decide(mods_a, fenvix_skip.State(mods_b, FIX))
        finally:
            revert()
        got = {tid: (r[0] if r else None) for (_, tid), r in d.items()}
        fresh = {tid: rec.get("outcome") for m in mods_b.values() for tid, rec in m["tests"].items()}
        wrong = sorted(t for t, r in got.items() if r is None and fresh.get(t) != "passed")
        missing = [reader] if reader and got.get(reader, "absent") is None else []
        plain_ok = got.get(PLAIN, "absent") is None
        probes_reused = all(got.get(p, "absent") is None for p in PROBES)
        ok = not wrong and not missing and plain_ok and probes_reused
        ok_all &= ok
        results.append({"scenario": name, "ok": ok, "wrong_reuse": {t: fresh.get(t) for t in wrong}, "expected_run_but_reused": missing,
                        "plain_reused": plain_ok, "probes_reused": probes_reused, "decisions": got, "fresh_outcomes": fresh})
        print(f"{'ok ' if ok else 'BAD'} {name:30} wrong reuses={len(wrong)} " +
              (f"[{', '.join(t + '=' + str(fresh.get(t)) for t in wrong[:4])}]" if wrong else "") +
              (f" expected RUN but reused: {missing}" if missing else "") + ("" if plain_ok else " PlainTest not reused") +
              ("" if probes_reused else " a probe was not reused"))
    json.dump({"agent": a.agent, "probes": probes, "scenarios": results}, open(a.out, "w"), indent=1)
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
