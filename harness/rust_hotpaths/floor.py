#!/usr/bin/env python3
"""What is a fully warm ``--det --det-cache`` run made of? (rust-hotpaths round 2: the fixed floor)

A run in which every cacheable test is reused still costs a fraction of plain pytest. For one spec at its HEAD
commit (set up as ``profile.py`` / the cache-proof walk do), per engine wheel:

* walls, interleaved, ``--reps`` rounds: ``P0`` plain pytest, ``K0`` plain ``pytest --collect-only`` (what any pytest
  run pays before the first test), ``W`` the warm run (a cold run fills the cache first), ``X`` the pre-exec stage of
  the warm run alone (the first interpreter: pytest's start-up up to detpy's re-exec, the bytecode precompile; the
  re-exec is captured by ``execcap`` and not performed);
* one py-spy profile of the exec'd warm process (``--pyspy``), its samples split into floor buckets (``BUCKETS``).

    python3 harness/rust_hotpaths/floor.py --spec harness/cache_proof/specs/click.json --work /tmp/w \\
        --wheel r2=dist/detpy.whl --out /tmp/floor-click.json
"""

from __future__ import annotations

import collections
import importlib.util
import json
import re
import shutil
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("rh_profile", HERE / "profile.py")  # not the stdlib's profile
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

W = P.W

# innermost-first: the first rule matching any frame, scanning from the innermost frame outwards
BUCKETS = [
    ("check", r"ProofCachePlugin\._decide|pytest_collection_finish \(detpy/proofcache"),
    ("reuse", r"ProofCachePlugin\._reuse|_ProtocolWrapper"),
    ("finish", r"ProofCachePlugin\.finish|_write_receipts|terminal_summary|pytest_sessionfinish|pytest_unconfigure"),
    ("identity", r"runtime_identity|config_identity|_dist_infos"),
    ("collection", r"perform_collect|pytest_collection \(|pytest_collectstart|pytest_make_collect_report|"
                   r"_collectfile|genitems|pytest_pycollect"),
    ("tests", r"pytest_runtest_protocol|runtestprotocol|pytest_runtestloop"),
    ("configure", r"pytest_configure|_configure_det|ProofCachePlugin\.configure|Capture\.start|"
                  r"pytest_load_initial_conftests|_preparse|pytest_cmdline_parse|_prepareconfig|import_plugin|"
                  r"consider_|register"),
    ("imports", r"_find_and_load|_call_with_frames_removed|exec_module|<module>"),
]
_RX = [(b, re.compile(r)) for b, r in BUCKETS]


def classify(raw_path: str) -> dict:
    c: collections.Counter = collections.Counter()
    tot = 0
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
            for name, rx in _RX:
                if any(rx.search(f) for f in frames):
                    b = name
                    break
            c[b or "other"] += n
    return {"samples": tot, "buckets": dict(c.most_common())}


class Floor(P.Prof):
    def cmd(self, variant: str, cache, units) -> list:
        if variant == "K0":
            c = super().cmd("P0", None, units)
            return [*c, "--collect-only", "-q"]
        return super().cmd(variant, cache, units)

    def pre_exec(self, units, cache) -> float:
        """Wall of the first interpreter of a warm run (its re-exec captured, not performed)."""
        w = self.w
        cap = w.work / "exec.json"
        cap.unlink(missing_ok=True)
        env = self.env()
        env["DETPY_EXEC_CAPTURE"] = str(cap)
        W.git(w.src, "clean", "-qfd", check=False)
        _code, _out, wall = W.sh(self.cmd("C", cache, units), cwd=w.src, env=env, timeout=3000)
        return wall if cap.exists() else float("nan")

    def spy_warm(self, units, cache, tag: str) -> dict:
        w = self.w
        cap = w.work / "exec.json"
        cap.unlink(missing_ok=True)
        env = self.env()
        env["DETPY_EXEC_CAPTURE"] = str(cap)
        W.git(w.src, "clean", "-qfd", check=False)
        W.sh(self.cmd("C", cache, units), cwd=w.src, env=env, timeout=3000)
        if not cap.exists():
            return {"error": "no exec captured"}
        ex = json.loads(cap.read_text())
        env2 = ex["env"]
        env2.pop("DETPY_EXEC_CAPTURE", None)
        prefix = ["setarch", "-R"] if shutil.which("setarch") else []
        raw = w.work / f"floor-{tag}.txt"
        spy = [shutil.which("py-spy") or "py-spy", "record", "-r", "250", "-f", "raw", "-o", str(raw), "--"]
        W.git(w.src, "clean", "-qfd", check=False)
        code, out, wall = W.sh([*spy, *prefix, *ex["argv"]], cwd=w.src, env=env2, timeout=6000)
        r = {"wall": wall, "exit": code}
        if raw.exists():
            r.update(classify(str(raw)))
            shutil.copy(raw, self.out.parent / f"{self.out.stem}-{tag}.raw")
        else:
            r["tail"] = out[-1500:]
        return r

    def main(self):
        w = self.w
        commits = w.clone()
        W.git(w.src, "checkout", "-q", "--force", commits[-1])
        W.git(w.src, "clean", "-qfd", check=False)
        ok, how = w.install()
        if not ok:
            self.res["error"] = how
            self.save()
            return
        self.cur = None
        w.args = w.pytest_args()
        units = w.units()
        self.res.update(sha=commits[-1], units=len(units))
        caches = {}
        for eng in self.engines:  # warm-up (precompile, page cache) and the cold run that fills each cache
            self.use(eng)
            self.run("B", units, None)
            caches[eng] = w.work / f"floor-cache-{eng}"
            shutil.rmtree(caches[eng], ignore_errors=True)
            self.res["cache"].setdefault(f"C:{eng}", []).append(self.run("C", units, caches[eng]))
        for r in range(self.a.reps):
            W.log(f"round {r}")
            for v in ("P0", "K0"):
                x = self.run(v, units, None)
                self.res["walls"][v].append(x["wall"])
            for eng in self.engines:
                self.use(eng)
                x = self.run("C", units, caches[eng])
                self.res["walls"][f"W:{eng}"].append(x["wall"])
                self.res["cache"].setdefault(f"W:{eng}", []).append(x)
                self.res["walls"][f"X:{eng}"].append(self.pre_exec(units, caches[eng]))
            self.save()
        med = {k: statistics.median(v) for k, v in self.res["walls"].items()}
        self.res["median"] = med
        self.res["floor"] = {e: med[f"W:{e}"] / med["P0"] for e in self.engines}
        if self.a.pyspy:
            for eng in self.engines:
                self.use(eng)
                self.res["profiles"][f"W:{eng}"] = self.spy_warm(units, caches[eng], f"W-{eng}")
                self.save()
        self.res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.save()


def main(argv=None):
    ap = P.argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wheel", action="append", required=True, help="NAME=PATH")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--pyspy", action="store_true")
    ap.add_argument("--engine-env", action="append")
    ap.add_argument("--no-probe", action="store_true")
    Floor(ap.parse_args(argv)).main()


if __name__ == "__main__":
    main()
