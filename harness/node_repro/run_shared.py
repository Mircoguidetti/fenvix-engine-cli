"""`fenvix repro` on the Node Block 1 flaky set, every test, with the full-suite runs shared per repository.

    python harness/node_repro/run_shared.py --work DIR --repos valibot,mobx [--shard K --nshards N] --out OUT

The verdict of each test is `fenvix repro TEST` (detpy.fenvix_js: search the fixed order and seeds 1..20, minimise,
10 confirming replays, bundle), run in-process. What differs from run_repro.py (one `repro` process per test): the
search runs a configuration's order up to the target; here each configuration's whole order is run once per
repository shard and every target's search verdict is read from it (its prefix is an initial segment of that run:
the target ran after exactly the same tests). The collections are shared too. The minimisation and the 10
confirming replays run fresh for every test, so a shared verdict can lose a reproduction but never make one. The
tree is cleaned before each test as in run_repro.py.

Run-dependent ids (a date or a random number in the test name: a different id in every plain run) are matched to
their stable id under --det (`fenvix_js.stable_id`); the row keeps both.

Then each REPRODUCED bundle is replayed 10 times by `python -m detpy.fenvix_js replay` in a fresh process from a
cleaned tree (as replay_bundles.py). Output: OUT/<repo>.jsonl and OUT/<repo>.replay.jsonl, the rows of run_repro.py
and replay_bundles.py, so report.py aggregates them (`--results OUT`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_repro as RR  # noqa: E402

from detpy import fenvix_js  # noqa: E402
from detpy import repro as _repro  # noqa: E402

NH = RR.NH


class SharedRunner(fenvix_js.DetjsRunner):
    """A DetjsRunner whose full-suite runs and collections are run once per configuration."""

    def __post_init__(self):
        super().__post_init__()
        self.memo_runs: dict = {}
        self.memo_collect: dict = {}
        self.shared_hits = 0
        self.keep_traces = True  # the shared runs' traces outlive one test's search

    def run(self, config, order, tag):
        # the search runs the configuration's order up to the target: the target's verdict is read from one run of
        # the whole order (the prefix is its initial segment: the target ran after exactly the same tests)
        full = self.orders.get(config)
        if tag.startswith("search-") and (order is None or (full and list(order) == full[:len(order)])):
            if config not in self.memo_runs:
                self.memo_runs[config] = super().run(config, full, f"shared-{config}")
            else:
                self.shared_hits += 1
            return self.memo_runs[config]
        return super().run(config, order, tag)

    def collect(self, config=_repro.FIXED):
        if config not in self.memo_collect:
            self.memo_collect[config] = super().collect(config)
        return list(self.memo_collect[config])


def shard_targets(targets: list, shard: int, nshards: int) -> list:
    return [t for i, t in enumerate(sorted(targets)) if i % nshards == shard]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--repos", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--confirm", type=int, default=10)
    ap.add_argument("--max-runs", type=int, default=150)
    ap.add_argument("--timeout", type=float, default=900, help="seconds per runner run")
    ap.add_argument("--budget", type=float, default=0, help="stop starting tests after S seconds (0: none)")
    ap.add_argument("--replay", type=int, default=10)
    ap.add_argument("--engine", default=None)
    args = ap.parse_args(argv)
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sets = {r["name"]: r for r in RR.flaky_set.repos()}
    t_start = time.monotonic()
    for name in args.repos.split(","):
        targets = shard_targets([t["id"] for t in sets[name]["targets"]], args.shard, args.nshards)
        if not targets:
            continue
        res_file = out / f"{name}.jsonl"
        p = RR.prepare(name, work)
        if p is None:
            with res_file.open("a") as f:
                f.write(json.dumps({"repo": name, "test": None, "status": "not-prepared", "shard": args.shard}) + "\n")
            continue
        print(f"{name}: {p.runner} {p.runner_version} in {p.src}; {len(targets)} tests in shard {args.shard}/{args.nshards}",
              flush=True)
        # node-final's first baseline run (node_harness.first_run): when the plain run is unusable, the flags and
        # variables of the project's own test script, then its build (apollo-client: `--config
        # ./config/jest.config.js`, without which every suite fails to parse); run_repro.py skipped this stage
        from types import SimpleNamespace
        first_dir = work / "first" / name
        shutil.rmtree(first_dir, ignore_errors=True)
        first_dir.mkdir(parents=True)
        fr = NH.first_run(p, SimpleNamespace(min_tests=10, run_timeout=args.timeout), first_dir)
        print(f"{name}: first baseline run: {len(fr.outcomes)} outcomes; runner args {p.pytest_args}; "
              f"script env {sorted(p.env)}", flush=True)
        NH.snapshot_tree(p)
        cwd = Path(RR.test_dir(p))
        prefix = os.path.relpath(cwd, p.src).replace(os.sep, "/")
        env = NH.node_env(p, RR.engine_env(None, None))
        bundles = out / "bundles" / name
        runner = SharedRunner(cwd=cwd, workdir=work / "runs" / name, pytest_args=list(p.pytest_args),
                              timeout=args.timeout, runner=p.runner, env=env,
                              detjs=["node", str(RR.DETJS)])
        NH.clean_tree(p)
        try:
            collected = runner.collect()
        except RuntimeError as e:
            with res_file.open("a") as f:
                for test in targets:
                    f.write(json.dumps({"repo": name, "test": test, "status": "not-collected-suite", "error": str(e)[-1500:],
                                        "engine": args.engine, "wall_s": 0}) + "\n")
            continue
        print(f"{name}: collected {len(collected)} tests, e.g. {collected[:3]}", flush=True)
        for test in targets:
            if args.budget and time.monotonic() - t_start > args.budget:
                with res_file.open("a") as f:
                    f.write(json.dumps({"repo": name, "test": test, "status": "not-attempted-budget", "engine": args.engine,
                                        "wall_s": 0}) + "\n")
                continue
            NH.clean_tree(p)
            run_id = test[len(prefix) + 1:] if prefix != "." and test.startswith(prefix + "/") else test
            t0 = time.monotonic()
            hits0, n0 = runner.shared_hits, len(runner.log)
            stable, note = fenvix_js.stable_id(run_id, collected)
            try:
                if stable is None:
                    b = {"test": run_id, "status": "not-collected", "runner": p.runner, "id": note}
                else:
                    b = _repro.reproduce(runner, stable, collected=collected, seeds=args.seeds, confirm=args.confirm,
                                         max_runs=args.max_runs, out_dir=bundles)
                    if note:
                        b["requested_test"], b["id"] = run_id, note
                    b = fenvix_js.finish_bundle(b, bundles, runner)
                status = b.get("status", "crashed")
                err = None
            except Exception as e:  # one test's failure never stops the others
                b, status, err = None, "crashed", repr(e)[-1500:]
            dur = time.monotonic() - t0
            if status == "not-collected":  # what was collected from the same file: the evidence for the verdict
                f0 = run_id.split("::", 1)[0]
                b = {**(b or {}), "collected_total": len(collected),
                     "collected_same_file": [c for c in collected if c.split("::", 1)[0] == f0][:20]}
            row = {"repo": name, "test": test, "test_run": run_id, "stable_id": stable if note else None,
                   "engine": args.engine, "runner": p.runner, "runner_version": p.runner_version, "commit": p.commit,
                   "wall_s": round(dur, 1), "runs_fresh": len(runner.log) - n0, "runs_shared": runner.shared_hits - hits0,
                   "status": status, "bundle": b, "error": err, "shard": args.shard,
                   "method": "repro in-process; full-suite runs and collection shared per repository (run_shared.py)"}
            with res_file.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"{name}: {test}: {status} ({dur:.0f} s)", flush=True)
        # the full-suite runs once per repository: their cost, for the time per test
        with (out / f"{name}.shared.jsonl").open("a") as f:
            f.write(json.dumps({"repo": name, "shard": args.shard, "shared_runs": len(runner.memo_runs),
                                "shared_seconds": round(sum(r.duration for r in runner.memo_runs.values()), 1),
                                "log": runner.log[:200]}) + "\n")
        if args.replay:
            rows = [json.loads(line) for line in res_file.read_text().splitlines() if line.strip()]
            for r in rows:
                if r.get("status") != "reproduced" or r.get("shard") != args.shard:
                    continue
                NH.clean_tree(p)
                b = r["bundle"]
                t0 = time.monotonic()
                pr = subprocess.run([sys.executable, "-m", "detpy.fenvix_js", "replay", b["bundle"], "--runs",
                                     str(args.replay), "--json"], cwd=b["root"], env=env, capture_output=True, text=True)
                try:
                    v = json.loads(pr.stdout)
                except ValueError:
                    v = {"error": (pr.stdout + pr.stderr)[-2000:]}
                with (out / f"{name}.replay.jsonl").open("a") as fh:
                    fh.write(json.dumps({"repo": name, "test": r["test"], "exit": pr.returncode,
                                         "wall_s": round(time.monotonic() - t0, 1), **v}) + "\n")
        NH.clean_tree(p)
        shutil.rmtree(work / "runs" / name, ignore_errors=True)
        shutil.rmtree(work / "src" / name, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
