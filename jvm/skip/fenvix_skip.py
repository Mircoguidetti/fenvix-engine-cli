#!/usr/bin/env python3
"""Skip with proof for the JVM: which tests recorded in a base run can be reused now.

The decision rule is engine logic and lives in Rust (crates/fenvix-skip, binary
`fenvix-skip`, built by jvm/build.sh); this module is the Python interface to it
(used by the measurement harnesses) plus a loader of the capture files.

A base run (A) is a test run with the skip-with-proof capture on
(`fenvix-jvm run --deps` or `-Dfenvix.deps=1`): every test JVM writes
`<out>/deps/<module>-<pid>.jsonl` with one record per test (in execution order),
per class container, per JVM session scope, and one `jvm` record.

A test of A is REUSABLE in the current state (B) when (details: crates/fenvix-skip/src/lib.rs)

* it passed in A, wrote no file it could read back, made no external network attempt,
  started no child process and ran no native code of the project;
* every class whose code it executed, whose static fields it accessed (declaring class
  included), whose static initialiser it depended on or whose reflective metadata it read
  has the same class-file digest now;
* every class looked up by name is still found / still not found; every file read, path
  probed, directory listed, classpath resource looked up (found or not, every location
  of getResources) is unchanged;
* every environment variable and system property it read has the same value; same runtime
  identity and configuration (JUnit configuration parameters included);
* if it read static state another test could change, every test before it in its JVM in B
  is reused and was there, in the same order of state-touching tests, in A; the tests of its
  own class before it are reused and in the same order; the writers of the static fields it
  read are reused.

B is described by its own capture (the measurement runs every test anyway, so every
reuse is checked against the fresh outcome).

  python3 fenvix_skip.py decide A_DEPS_DIR B_DEPS_DIR --root-b DIR [--json out.json]
"""
import argparse, glob, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def binary():
    b = os.environ.get("FENVIX_SKIP_BIN") or os.path.join(REPO, "target", "release", "fenvix-skip")
    if not os.path.exists(b):
        raise SystemExit(f"fenvix-skip binary not found at {b} (run jvm/build.sh)")
    return b


class Mods(dict):
    """module -> {"jvm": record, "tests": {id: rec}, "scopes": {id: rec}}, remembering its deps directory."""
    deps_dir = None


def pid_of(path):
    try:
        return int(os.path.basename(path).rsplit("-", 1)[1].split(".")[0])
    except (IndexError, ValueError):
        return 0


def load(deps_dir):
    """Read a capture (for reporting: outcomes, times). A test run by several JVMs of one module
    gets the suffix "#n" for its n-th JVM after the first (same rule as the Rust decider)."""
    mods = Mods()
    mods.deps_dir = os.path.abspath(deps_dir)
    seen = {}
    for f in sorted(glob.glob(os.path.join(deps_dir, "*.jsonl")), key=lambda p: (os.path.basename(p).rsplit("-", 1)[0], pid_of(p))):
        recs = [json.loads(l) for l in open(f) if l.strip()]
        jvm = next((r for r in recs if r["type"] == "jvm"), None)
        for r in recs:
            m = mods.setdefault(r.get("module", ""), {"jvm": None, "tests": {}, "scopes": {}})
            if r["type"] == "jvm":
                m["jvm"] = r
            elif r["type"] == "test":
                r["_jvm"] = jvm
                key = (r.get("module", ""), r["id"])
                n = seen.get(key, 0)
                seen[key] = n + 1
                if n:
                    r["id"] = f'{r["id"]}#{n + 1}'
                    r["after"] = [f"{a}#{n + 1}" for a in r.get("after", [])]
                m["tests"][r["id"]] = r
            else:
                m["scopes"][r["id"]] = r
    return mods


class State:
    """The current state B: its capture plus the file system at root_b."""

    def __init__(self, mods_b, root_b):
        self.mods = mods_b
        self.root = os.path.abspath(root_b)


def _dir_of(mods):
    d = getattr(mods, "deps_dir", None)
    if d is None or not os.path.isdir(d):
        raise ValueError("decide() needs captures returned by load()")
    return d


def decide_rows(a_dir, b_dir, root_b):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    try:
        r = subprocess.run([binary(), "decide", a_dir, b_dir, "--root-b", root_b, "--json", out], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"fenvix-skip failed: {r.stderr[-2000:]}")
        return json.load(open(out))
    finally:
        os.unlink(out)


def decide(mods_a, b: State):
    """{(module, id): None if reusable, else (reason, detail)} -- decided by the Rust decider."""
    rows = decide_rows(_dir_of(mods_a), _dir_of(b.mods), b.root)
    return {(o["module"], o["id"]): (None if o["reusable"] else tuple(o["reason"])) for o in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["decide"])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--root-b", required=True)
    ap.add_argument("--json")
    a = ap.parse_args()
    cmd = [binary(), "decide", a.a, a.b, "--root-b", a.root_b] + (["--json", a.json] if a.json else [])
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
