#!/usr/bin/env python3
"""Where does the overhead of ``pytest --det --det-cache`` go? (rust-hotpaths session)

For one spec (and shard) at its HEAD commit, set up as the cache-proof walk does, then run interleaved:

* ``P0``  plain pytest (no ``--det``);
* ``B:<engine>``   ``pytest --det`` (no cache);
* ``C:<engine>``  cold run ``--det --det-cache=<empty dir>`` for every engine wheel given (``--wheel NAME=PATH``,
  swapped in place with ``uv pip install --reinstall-package detpy``);
* ``W:<engine>``  warm run: the same cache again (every result reusable unless not cacheable).

Wall times come from unprofiled runs (``--reps`` rounds, engines interleaved). Then one py-spy profile per variant
(``--native``, 250 Hz) of the single process detpy would exec (the re-exec is captured by ``execcap``, then launched
directly), classified into overhead buckets (``classify``).

    python3 harness/rust_hotpaths/profile.py --spec harness/cache_proof/specs/click.json --work /tmp/w \\
        --wheel base=dist-base/detpy.whl --wheel new=dist/detpy.whl --out /tmp/click.json
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "harness" / "cache_proof"))
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(HERE))
import walk as W  # noqa: E402

# ---------------------------------------------------------------------------
# sample classification: phase buckets (session start, decision, end-of-session recording) dominate: the innermost
# phase frame anywhere in the stack; otherwise the innermost hook/control frame; otherwise the test itself.
RULES = [
    ("record.facts", r"_prefetch_facts|_facts_index|read_many \(detpy|read_facts \(detpy"),
    ("record.children", r"collect_children"),
    ("record.save", r"save_merged|ProofCache.*save"),
    ("record.loop", r"_record_all|record_session"),
    ("record.other", r"ProofCachePlugin\.finish|_write_receipts"),
    ("check", r"ProofCachePlugin\._decide|pytest_collection_finish \(detpy/proofcache"),
    ("startup.identity", r"runtime_identity|config_identity|_dist_infos"),
    ("startup.capture", r"Capture\.start|ProofCachePlugin\.configure|ProofCache.*new"),
    ("switch.sockets", r"_scan_sockets|scan_sockets"),
    ("switch", r"Capture\.switch|scan_modules|_conftests|LineRecorder.*switch"),
    ("audit", r"audit_hook|Capture\._audit"),
    ("env", r"_Recorded\.__|_note_env|_env_caller_is_user"),
    ("lines", r"LineRecorder|_core.*sysmon"),
    ("follow", r"detpy/follow\.py|Follower"),
    ("det.seeds", r"detpy/seeds\.py"),
    ("det.clock", r"detpy/clock\.py"),
    ("det.network", r"detpy/network\.py"),
    ("det.fsorder", r"detpy/fsorder\.py"),
    ("det.plugin", r"detpy/plugin\.py|detpy/_state\.py|detpy/reexec\.py|detpy/repro\.py|detpy/_sites"),
    ("compile", r"source_to_code|_rewrite_test|rewrite_asserts|_PyAST_Compile|_PyParser|PyParser_|builtins.compile"),
]
_COMP = [(b, re.compile(r)) for b, r in RULES]
_PHASES = ("record", "check", "startup")


def classify(raw_path: str) -> dict:
    tot = 0
    c: collections.Counter = collections.Counter()
    with open(raw_path, errors="replace") as fh:
        for line in fh:
            stack, _, n = line.rstrip().rpartition(" ")
            try:
                n = int(n)
            except ValueError:
                continue
            tot += n
            frames = stack.split(";")
            b = None
            for f in reversed(frames):
                for name, rx in _COMP:
                    if name.split(".")[0] in _PHASES and rx.search(f):
                        b = name
                        break
                if b:
                    break
            if b is None:
                for f in reversed(frames):
                    for name, rx in _COMP:
                        if rx.search(f):
                            b = name
                            break
                    if b:
                        break
            c[b or "test+pytest"] += n
    return {"samples": tot, "buckets": dict(c.most_common())}


# ---------------------------------------------------------------------------
class Prof:
    def __init__(self, a):
        spec = json.loads(Path(a.spec).read_text())
        s, n = (int(x) for x in a.shard.split("/"))
        self.engines = dict(x.split("=", 1) for x in a.wheel)
        # per-engine environment (--engine-env NAME:VAR=VALUE): the same wheel under another setting is another engine
        self.engine_env: dict = collections.defaultdict(dict)
        for x in a.engine_env or ():
            name, _, kv = x.partition(":")
            k, _, v = kv.partition("=")
            self.engine_env[name][k] = v
        first = next(iter(self.engines.values()))
        self.w = W.Walk(spec, a.work, a.out, s, n, 9999, first, 1, 1)
        self.a = a
        self.out = Path(a.out)
        self.res = {"spec": spec["name"], "shard": a.shard, "engines": list(self.engines), "cpus": os.cpu_count(),
                    "runner": os.environ.get("RUNNER_NAME", ""), "engine_sha": os.environ.get("GITHUB_SHA", ""),
                    "walls": collections.defaultdict(list), "cache": {}, "profiles": {}}
        self.cur = None

    def use(self, eng: str) -> None:
        if self.cur == eng:
            return
        prev, self.cur = self.cur, eng
        if prev is not None and self.engines[prev] == self.engines[eng]:
            return  # same wheel, other environment (--engine-env): same install, same bytecode cache
        code, out, _ = W.sh(["uv", "pip", "install", "-q", "--python", self.w.py, "--reinstall-package", "detpy",
                             "--no-deps", os.path.abspath(self.engines[eng])], timeout=600)
        if code:
            raise RuntimeError(f"install {eng}: {out[-400:]}")
        # one bytecode cache per wheel behind one path (the path is in the environment the tests see): an
        # engine's precompile stamps must not decide what another compiles
        tag = lambda e: hashlib.sha1(os.path.abspath(self.engines[e]).encode()).hexdigest()[:10]  # noqa: E731
        fixed = self.w.work / "pyc"
        if prev is not None and fixed.exists():
            fixed.rename(self.w.work / f"pyc-{tag(prev)}")
        mine = self.w.work / f"pyc-{tag(eng)}"
        if mine.exists():
            mine.rename(fixed)

    def env(self) -> dict:
        env = self.w.env()
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "harness" / "cache_proof"), str(HERE / "execcap")])
        env["DETPY_PYC_CACHE"] = str(self.w.work / "pyc")
        env.update(self.engine_env.get(self.cur, {}))
        return env

    def cmd(self, variant: str, cache: Path | None, units) -> list[str]:
        w = self.w
        c = [w.py, *w.spec.get("python_flags", []), "-m", "pytest"]
        if variant != "P0":
            c += ["--det", "--det-urandom"]
        c.append(f"--det-outcomes={w.work / 'o-prof.json'}")
        if cache is not None:
            c.append(f"--det-cache={cache}")
        return c + [*w.args, *units]

    def run(self, variant: str, units, cache: Path | None) -> dict:
        w = self.w
        W.git(w.src, "clean", "-qfd", check=False)
        o = w.work / "o-prof.json"
        o.unlink(missing_ok=True)
        code, out, wall = W.sh(self.cmd(variant, cache, units), cwd=w.src, env=self.env(),
                               timeout=w.spec.get("timeout", 3000))
        r = {"exit": code, "wall": wall}
        try:
            d = json.loads(o.read_text())
            r["n"] = len(d.get("outcomes", {}))
            c = d.get("cache") or {}
            r["cache"] = {k: c.get(k) for k in ("reused", "ran", "recorded", "check_seconds", "record_seconds",
                                                "not_cached", "phase_seconds")}
        except (OSError, ValueError):
            r["tail"] = out[-1500:]
        return r

    def profile(self, variant: str, units, cache: Path | None, tag: str) -> None:
        """py-spy of the process detpy execs (captured, then launched directly)."""
        w = self.w
        cap = w.work / "exec.json"
        cap.unlink(missing_ok=True)
        env = self.env()
        env["DETPY_EXEC_CAPTURE"] = str(cap)
        W.git(w.src, "clean", "-qfd", check=False)
        cmd = self.cmd(variant, cache, units)
        if variant != "P0":
            W.sh(cmd, cwd=w.src, env=env, timeout=w.spec.get("timeout", 3000))
            if not cap.exists():
                self.res["profiles"][tag] = {"error": "no exec captured"}
                return
            ex = json.loads(cap.read_text())
            argv, env2 = ex["argv"], ex["env"]
            env2.pop("DETPY_EXEC_CAPTURE", None)
            prefix = ["setarch", "-R"] if shutil.which("setarch") else []
        else:
            argv, env2, prefix = cmd, self.env(), []
        if cache is not None and tag.startswith("C"):
            shutil.rmtree(cache, ignore_errors=True)
        raw = w.work / f"prof-{tag.replace(':', '-')}.txt"
        spy = [shutil.which("py-spy") or "py-spy", "record", "-r", "250", "--native", "-f", "raw", "-o", str(raw),
               "--"]
        W.git(w.src, "clean", "-qfd", check=False)
        code, out, wall = W.sh([*spy, *prefix, *argv], cwd=w.src, env=env2, timeout=w.spec.get("timeout", 3000) * 2)
        p = {"wall": wall, "exit": code}
        if raw.exists():
            p.update(classify(str(raw)))
            dst = self.out.parent / f"{self.out.name.split('.json')[0]}-{tag.replace(':', '-')}.raw.gz"
            with open(raw, "rb") as fi, gzip.open(dst, "wb") as fo:
                fo.write(fi.read())
        else:
            p["tail"] = out[-1500:]
        self.res["profiles"][tag] = p

    @staticmethod
    def receipts(cache: Path) -> dict:
        """Warm-run decisions: {nodeid: [reused, why, receipt sizes]}."""
        out = {}
        try:
            for line in (cache / "receipts.jsonl").read_text().splitlines():
                x = json.loads(line)
                out[x["nodeid"]] = [x["reused"], x.get("why"), x.get("n_units"), x.get("n_skeleton"),
                                    x.get("n_hooks"), x.get("n_content"), x.get("n_data"), x.get("n_env")]
        except (OSError, ValueError):
            pass
        return out

    def compare(self) -> None:
        """Cold-run stores and warm-run decisions of the engines, against the first one. Tests whose entry or
        decision differs between two rounds of the same engine (randomised inputs, threads) are run-to-run noise:
        counted apart."""
        import canon

        engs = list(self.engines)
        work = self.w.work
        rounds = 2 if (work / f"store-{engs[0]}-1.json").exists() else 1

        def store(e, r):
            return canon.canon(str(work / f"store-{e}-{r}.json"))

        def differing(a, b):
            ta, tb = a["tests"], b["tests"]
            return {n for n in set(ta) | set(tb)
                    if {k: v for k, v in ta.get(n, {}).items() if k != "fingerprint"}
                    != {k: v for k, v in tb.get(n, {}).items() if k != "fingerprint"}}

        def rdiff(ra, rb):
            return {n for n in set(ra) | set(rb) if ra.get(n) != rb.get(n)}

        rec = self.res.get("receipts", {})
        noise_s, noise_r = set(), set()
        if rounds == 2:
            for e in engs:
                noise_s |= differing(store(e, 0), store(e, 1))
                noise_r |= rdiff(rec.get(f"{e}-0", {}), rec.get(f"{e}-1", {}))
        a = store(engs[0], 0)
        out = {}
        for e in engs[1:]:
            b = store(e, 0)
            d = sorted(differing(a, b) - noise_s)
            fp = [n for n in a["tests"] if n in b["tests"] and a["tests"][n]["fingerprint"] != b["tests"][n]["fingerprint"]]
            ra, rb = rec.get(f"{engs[0]}-0", {}), rec.get(e + "-0", {})
            rd = sorted(rdiff(ra, rb) - noise_r)
            out[e] = {"entries": [len(a["tests"]), len(b["tests"])], "store_diffs": d[:50], "n_store_diffs": len(d),
                      "fingerprint_only": fp[:50], "n_fingerprint_only": len(fp), "receipt_diffs": rd[:50],
                      "n_receipt_diffs": len(rd), "n_receipts": [len(ra), len(rb)],
                      "written_equal": a["written"] == b["written"],
                      "noise": {"store": len(noise_s), "receipts": len(noise_r), "examples": sorted(noise_s)[:10]},
                      "details": [self.detail(n, a["tests"].get(n, {}), b["tests"].get(n, {})) for n in d[:5]]}
        self.res["equivalence"] = out

    @staticmethod
    def detail(nid: str, x: dict, y: dict) -> dict:
        """What differs in one entry: per field, the items only in the first engine's and only in the second's."""
        out = {"nodeid": nid}
        for k in sorted(set(x) | set(y)):
            if k == "fingerprint" or x.get(k) == y.get(k):
                continue
            vx, vy = x.get(k), y.get(k)
            if isinstance(vx, list) and isinstance(vy, list):
                sx = {json.dumps(v) for v in vx}
                sy = {json.dumps(v) for v in vy}
                out[k] = {"only_first": sorted(sx - sy)[:30], "only_second": sorted(sy - sx)[:30]}
            else:
                out[k] = {"first": vx, "second": vy}
        return out

    def save(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.out.write_text(json.dumps(self.res, indent=1))

    def main(self):
        w = self.w
        commits = w.clone()
        sha = commits[-1]
        W.git(w.src, "checkout", "-q", "--force", sha)
        W.git(w.src, "clean", "-qfd", check=False)
        ok, how = w.install()
        if not ok:
            self.res["error"] = how
            self.save()
            return
        self.cur = next(iter(self.engines))
        w.args = w.pytest_args()
        units = w.units()
        st: dict = {}
        if w.spec.get("precollect") and units:
            units = w.collectable(units, st)
        self.res.update(sha=sha, units=len(units), dropped=st.get("dropped_units", []))
        # old vs new pure functions on this environment (the last engine given is the one tested)
        self.use(list(self.engines)[-1])
        code, out, _ = W.sh([w.py, str(HERE / "equiv_probe.py"), "--root", str(w.src)], cwd=str(w.work),
                            env=self.env(), timeout=3600)
        try:
            self.res["probe"] = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            self.res["probe"] = {"error": out[-1500:]}
        self.save()
        cache = w.work / "prof-cache"
        # warm-up: precompile under the fixed seed (each engine its own cache), imports in the page cache
        for eng in self.engines:
            self.use(eng)
            self.run("B", units, None)
        for r in range(self.a.reps):
            W.log(f"round {r}")
            x = self.run("P0", units, None)
            self.res["walls"]["P0"].append(x["wall"])
            self.res["cache"].setdefault("P0", []).append(x)
            for eng in self.engines:
                self.use(eng)
                x = self.run("B", units, None)
                self.res["walls"][f"B:{eng}"].append(x["wall"])
                self.res["cache"].setdefault(f"B:{eng}", []).append(x)
                shutil.rmtree(cache, ignore_errors=True)
                c = self.run("C", units, cache)
                if r < 2:
                    shutil.copy(cache / "proof-cache.json", w.work / f"store-{eng}-{r}.json")
                self.res["walls"][f"C:{eng}"].append(c["wall"])
                self.res["cache"].setdefault(f"C:{eng}", []).append(c)
                wm = self.run("C", units, cache)
                if r < 2:
                    self.res.setdefault("receipts", {})[f"{eng}-{r}"] = self.receipts(cache)
                self.res["walls"][f"W:{eng}"].append(wm["wall"])
                self.res["cache"].setdefault(f"W:{eng}", []).append(wm)
            self.save()
        if len(self.engines) > 1:
            self.compare()
            self.save()
        if self.a.pyspy:
            self.profile("P0", units, None, "P0")
            for eng in self.engines:
                self.use(eng)
                self.profile("B", units, None, f"B:{eng}")
                self.profile("C", units, cache, f"C:{eng}")
                self.save()
        self.res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.save()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wheel", action="append", required=True, help="NAME=PATH (first: installed first)")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--pyspy", action="store_true")
    ap.add_argument("--engine-env", action="append", help="NAME:VAR=VALUE, environment of one engine's runs")
    Prof(ap.parse_args(argv)).main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
