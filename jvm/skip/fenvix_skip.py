#!/usr/bin/env python3
"""Skip with proof for the JVM: which tests recorded in a base run can be reused now.

A base run (A) is a test run with the skip-with-proof capture on
(`fenvix-jvm run --deps` or `-Dfenvix.deps=1`): every test JVM writes
`<out>/deps/<module>-<pid>.jsonl` with one record per test, per class
container, per JVM session scope, and one `jvm` record (class table with
digests, runtime identity, configuration, every environment variable and
system property digest, class path).

A test of A is REUSABLE in the current state (B) when all of these hold:

* it passed in A (failures are never reused) and wrote no file it could read
  back, and made no external network attempt;
* every class whose code it executed or whose static fields it accessed (its
  own scope, its class container scope and the JVM session scope) has the same
  class-file digest now: taken from B's class table when B loaded the class,
  otherwise looked up on B's class path (missing = changed);
* every file it read has the same content digest, every path it probed the
  same existence state, every directory it listed the same names, every
  classpath resource it looked up the same location and content;
* every environment variable and system property it read has the same value
  digest (in B's JVM); a read of the whole environment or of all properties
  compares all of them;
* the same runtime identity (JDK vendor, version, bytes of lib/modules and
  libjvm, JVM flags, native libraries outside the JDK, build tool and plugins)
  and the same configuration (junit-platform.properties, class path order,
  test-task settings) as its module's JVM in B;
* every test it depends on through static fields written earlier in A is
  reusable too.

B is described by its own capture (the measurement runs every test anyway, so
every reuse is checked against the fresh outcome) or, for a pure decision, by
the `jvm` records of a run that executed no test (not implemented here).

  python3 fenvix_skip.py decide A_DEPS_DIR B_DEPS_DIR --root-a DIR --root-b DIR [--json out.json]
"""
import argparse, glob, json, os, sys, zipfile

try:
    import blake3
except ImportError:  # pragma: no cover
    blake3 = None


def short(data: bytes) -> str:
    return blake3.blake3(data).hexdigest()[:32]


def digest_file(path):
    try:
        h = blake3.blake3()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()[:32]
    except OSError:
        return None


def load(deps_dir):
    """module -> {"jvm": record, "tests": {id: rec}, "scopes": {id: rec}}"""
    mods = {}
    for f in sorted(glob.glob(os.path.join(deps_dir, "*.jsonl"))):
        recs = [json.loads(l) for l in open(f) if l.strip()]
        jvm = next((r for r in recs if r["type"] == "jvm"), None)
        for r in recs:
            m = mods.setdefault(r.get("module", ""), {"jvm": None, "tests": {}, "scopes": {}})
            if r["type"] == "jvm":
                m["jvm"] = r
            elif r["type"] == "test":
                r["_jvm"] = jvm
                m["tests"][r["id"]] = r
            else:
                m["scopes"][r["id"]] = r
    return mods


class State:
    """The current state B: its capture plus the file system at root_b."""

    def __init__(self, mods_b, root_b):
        self.mods = mods_b
        self.root = os.path.abspath(root_b)
        self._file = {}
        self._classes = {}
        self._jars = {}

    def jvm(self, module):
        m = self.mods.get(module)
        return m["jvm"] if m else None

    def path(self, key):
        if key.startswith("root:"):
            return os.path.join(self.root, key[5:])
        if key.startswith("abs:") or key.startswith("sys:"):
            return key[4:]
        return None

    def file_state(self, abs_path):
        if abs_path in self._file:
            return self._file[abs_path]
        if not os.path.exists(abs_path):
            s = "absent"
        elif os.path.isdir(abs_path):
            s = "dir"
        else:
            d = digest_file(abs_path)
            s = "file:" + (d or "unreadable")
        self._file[abs_path] = s
        return s

    def entry(self, key, value):
        """Current value of a files[] entry, in the recorded vocabulary."""
        if key.endswith("/") and value.startswith("list:"):
            p = self.path(key[:-1])
            try:
                names = sorted(os.listdir(p))
            except OSError:
                return "list:absent"
            return "list:" + short("".join(n + "\n" for n in names).encode())
        p = self.path(key)
        if p is None:
            return None
        st = self.file_state(p)
        if value.startswith("probe:"):
            return "probe:" + ("absent" if st == "absent" else "dir" if st == "dir" else "file")
        if value.startswith("read:"):
            return "read:" + st
        return value

    def class_digest(self, module, name):
        jvm = self.jvm(module)
        if jvm and name in jvm["classes"]:
            return jvm["classes"][name].split(" ")[0]
        key = (module, name)
        if key in self._classes:
            return self._classes[key]
        d = None
        for entry in (jvm or {}).get("classpath", []):
            if entry.endswith(".jar"):
                z = self._jar(entry)
                if z is not None:
                    try:
                        d = short(z.read(name + ".class"))
                        break
                    except KeyError:
                        continue
            else:
                p = os.path.join(entry, name + ".class")
                if os.path.isfile(p):
                    d = digest_file(p)
                    break
        self._classes[key] = d
        return d

    def _jar(self, path):
        if path not in self._jars:
            try:
                self._jars[path] = zipfile.ZipFile(path)
            except (OSError, zipfile.BadZipFile):
                self._jars[path] = None
        return self._jars[path]


def scope_chain(mod_a, rec):
    out = [rec]
    for sid in rec.get("scopes", []):
        s = mod_a["scopes"].get(sid)
        if s:
            out.append(s)
    return out


def why_not(mod_name, mod_a, rec, b: State):
    """None if reusable, else the first reason (a short code and detail)."""
    if rec.get("outcome") != "passed":
        return ("not-passed", rec.get("outcome"))
    jvm_a = rec["_jvm"]
    jvm_b = b.jvm(mod_name)
    if jvm_a is None or jvm_b is None:
        return ("no-jvm-record", mod_name)
    if jvm_a["runtime"] != jvm_b["runtime"]:
        diff = sorted(k for k in set(jvm_a["runtime"]) | set(jvm_b["runtime"]) if jvm_a["runtime"].get(k) != jvm_b["runtime"].get(k))
        return ("runtime", ",".join(diff[:3]))
    if jvm_a["config"] != jvm_b["config"]:
        diff = sorted(k for k in set(jvm_a["config"]) | set(jvm_b["config"]) if jvm_a["config"].get(k) != jvm_b["config"].get(k))
        return ("config", ",".join(diff[:3]))
    for s in scope_chain(mod_a, rec):
        if s.get("written"):
            return ("writes", s["id"])
        if s.get("net"):
            return ("network", s["net"][0])
        for name in s.get("classes", []):
            da = jvm_a["classes"].get(name)
            if da is None:
                continue  # generated at run time (no code source)
            if b.class_digest(mod_name, name) != da.split(" ")[0]:
                return ("code", name)
        for k, v in s.get("files", {}).items():
            if v == "write":
                return ("writes", k)
            now = b.entry(k, v)
            if now is not None and now != v:
                return ("file", k)
        for r in s.get("resources", []):
            name, _, loc = r.partition("=")
            if loc == "absent" or "@" not in loc:
                continue
            path_key, _, st = loc.rpartition("@")
            if path_key.startswith("jar:"):
                jar = path_key[4:].split("!")[0]
                p = b.path(jar)
            else:
                p = b.path(path_key)
            if p is not None and b.file_state(p) != st:
                return ("resource", name)
        for k, v in s.get("env", {}).items():
            if k == "*":
                if jvm_a["env_all"] != jvm_b["env_all"]:
                    return ("env", "*")
                continue
            if jvm_b["env_all"].get(k, "unset") != v:
                return ("env", k)
        for k, v in s.get("props", {}).items():
            if k == "*":
                if {x: y for x, y in jvm_a["props_all"].items() if not x.startswith("fenvix.")} != \
                        {x: y for x, y in jvm_b["props_all"].items() if not x.startswith("fenvix.")}:
                    return ("prop", "*")
                continue
            if jvm_b["props_all"].get(k, "unset") != v:
                return ("prop", k)
    return None


def decide(mods_a, b: State):
    """{(module, id): (reusable, reason)} with the static-write dependencies resolved."""
    first = {}
    for mn, m in mods_a.items():
        for tid, rec in m["tests"].items():
            first[(mn, tid)] = why_not(mn, m, rec, b)
    # dependencies through static fields written by earlier tests (transitive)
    final = dict(first)
    changed = True
    while changed:
        changed = False
        for mn, m in mods_a.items():
            for tid, rec in m["tests"].items():
                if final[(mn, tid)] is not None:
                    continue
                for dep in rec.get("after", []):
                    if final.get((mn, dep), ("missing", dep)) is not None:
                        final[(mn, tid)] = ("after", dep)
                        changed = True
                        break
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["decide"])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--root-b", required=True)
    ap.add_argument("--json")
    a = ap.parse_args()
    mods_a, mods_b = load(a.a), load(a.b)
    d = decide(mods_a, State(mods_b, a.root_b))
    out = []
    for (mn, tid), r in sorted(d.items()):
        rec_b = mods_b.get(mn, {}).get("tests", {}).get(tid)
        out.append({"module": mn, "id": tid, "reusable": r is None, "reason": None if r is None else list(r),
                    "outcome_a": mods_a[mn]["tests"][tid].get("outcome"),
                    "outcome_b": rec_b.get("outcome") if rec_b else None, "ms_b": rec_b.get("ms") if rec_b else None})
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
    for o in out:
        print(("REUSE " if o["reusable"] else "RUN   ") + f"{o['module']}::{o['id']}" + ("" if o["reusable"] else f"  [{o['reason'][0]}: {o['reason'][1]}]"))


if __name__ == "__main__":
    main()
