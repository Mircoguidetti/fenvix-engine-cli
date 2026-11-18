#!/usr/bin/env python3
"""Where does the overhead of ``pytest --det --det-cache`` go? (rust-hotpaths session)

For one spec (and shard) at its HEAD commit, set up as the cache-proof walk does, then run interleaved:

* ``P0``  plain pytest (no ``--det``);
* ``B``   ``pytest --det`` (no cache);
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
        code, out, _ = W.sh(["uv", "pip", "install", "-q", "--python", self.w.py, "--reinstall-package", "detpy",
                             "--no-deps", os.path.abspath(self.engines[eng])], timeout=600)
        if code:
            raise RuntimeError(f"install {eng}: {out[-400:]}")
        self.cur = eng

    def env(self) -> dict:
        env = self.w.env()
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "harness" / "cache_proof"), str(HERE / "execcap")])
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
        cache = w.work / "prof-cache"
        # warm-up: precompile under the fixed seed, imports in the page cache
        self.run("B", units, None)
        for r in range(self.a.reps):
            W.log(f"round {r}")
            for v in ("P0", "B"):
                x = self.run(v, units, None)
                self.res["walls"][v].append(x["wall"])
                self.res["cache"].setdefault(v, []).append(x)
            for eng in self.engines:
                self.use(eng)
                shutil.rmtree(cache, ignore_errors=True)
                c = self.run("C", units, cache)
                self.res["walls"][f"C:{eng}"].append(c["wall"])
                self.res["cache"].setdefault(f"C:{eng}", []).append(c)
                wm = self.run("C", units, cache)
                self.res["walls"][f"W:{eng}"].append(wm["wall"])
                self.res["cache"].setdefault(f"W:{eng}", []).append(wm)
            self.save()
        if self.a.pyspy:
            self.profile("P0", units, None, "P0")
            self.profile("B", units, None, "B")
            for eng in self.engines:
                self.use(eng)
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
    Prof(ap.parse_args(argv)).main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
