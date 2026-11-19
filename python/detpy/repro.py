"""``detpy repro`` and ``detpy explore``: turn a flaky test into a replay bundle.

repro TEST_ID
    1. search: the fixed order, then ``--det-seed=1..N``; each configuration runs
       only the tests up to the target (and the one after it, so the target's
       teardown is the one of the full run). Under --det one run per
       configuration is enough: the outcome is a function of the order.
    2. minimise: delta debugging (ddmin) over the tests that ran before the
       target, keeping their order, until no single test can be removed. The
       tests left are the polluters. If the target fails alone, it is brittle:
       the passing configuration is minimised the same way to name the test
       that *sets up* the state it needs.
    3. bundle: seed, minimal order, controls, outcome, exception, first
       diverging event against a passing run, traces.
    4. proof: the bundle is replayed ``--confirm`` times; it must fail every
       time with one fingerprint.

explore --budget MINUTES
    Runs the whole suite with seeds 1, 2, ... while the budget lasts, keeps the
    tests that fail under some seed and pass under another (always-failing tests
    are not flaky), writes one bundle per failing test and groups the bundles by
    first diverging event and by polluter.

Both use only pytest subprocesses with the plugin (``--det``, ``--det-order``,
``--det-outcomes``), so they work wherever ``pytest --det`` works.

The decisions are in Rust (``crates/detpy-core/src/repro.rs``, bound in ``crates/detpy-py/src/repro.rs``): the
search, ddmin, the replay verdicts, the first diverging event, the bundle (in its key order), the texts printed and
``explore``'s seed/budget bookkeeping. This module keeps the process orchestration: the ``Runner`` (pytest command
lines, subprocesses, outcome files), the bundle files, argument handling and printing. The Python original is kept
verbatim in ``tests/rust_hotpaths_ref/_ref_repro.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import _core

FIXED = "fixed"


def is_fail(outcome) -> bool:
    return _core.repro_is_fail(outcome)


@dataclass
class Run:
    config: str
    order: list
    outcomes: dict
    fingerprints: dict
    exceptions: dict
    duration: float
    exit_code: int
    trace: str
    timed_out: bool = False
    meta: dict = field(default_factory=dict)

    def outcome(self, nid):
        return _core.repro_outcome(self.outcomes, nid)


@dataclass
class Runner:
    """Runs pytest --det in a project directory and reads its outcomes file."""

    cwd: Path
    workdir: Path
    python: str = sys.executable
    pytest_args: list = field(default_factory=list)
    timeout: float = 1800
    env: dict | None = None
    keep_traces: bool = True
    orders: dict = field(default_factory=dict)
    runs: int = 0
    seconds: float = 0.0
    log: list = field(default_factory=list)

    def _cmd(self, config: str, extra: list) -> list:
        cmd = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det", *self.pytest_args, *extra]
        if config != FIXED:
            cmd.append(f"--det-seed={int(config)}")
        return cmd

    def run(self, config: str, order: list | None, tag: str) -> Run:
        self.workdir.mkdir(parents=True, exist_ok=True)
        out = self.workdir / f"{tag}.json"
        trace = self.workdir / f"{tag}.jsonl"
        extra = [f"--det-outcomes={out}", f"--det-trace={trace}"]
        if order is not None:
            of = self.workdir / f"{tag}.order.txt"
            of.write_text("".join(n + "\n" for n in order))
            extra.append(f"--det-order={of}")
        for f in (out, trace):
            f.unlink(missing_ok=True)
        t0 = time.monotonic()
        timed_out = False
        try:
            p = subprocess.run(self._cmd(config, extra), cwd=self.cwd, capture_output=True, text=True,
                               timeout=self.timeout, env=self.env)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code, timed_out = -9, True
        dur = time.monotonic() - t0
        self.runs += 1
        self.seconds += dur
        data = {}
        if out.exists():
            try:
                data = json.loads(out.read_text())
            except ValueError:
                data = {}
        r = Run(config, data.get("order", order or []), data.get("outcomes", {}), data.get("fingerprints", {}),
                data.get("exceptions", {}), dur, code, str(trace), timed_out,
                {k: data.get(k) for k in ("controls", "seed", "order_missing")})
        self.log.append({"tag": tag, "config": config, "tests": len(r.order), "seconds": round(dur, 3),
                         "exit": code})
        return r

    def drop_traces(self) -> None:
        """Delete the traces of finished runs (large suites: one trace per run adds up)."""
        for f in self.workdir.glob("*.jsonl"):
            f.unlink(missing_ok=True)

    def order_of(self, config: str) -> list:
        """The order a whole-suite run with this configuration uses, as the plugin
        computes it (shuffle, then pytest-django's groups, ...): read from a
        collect-only run, or from a whole-suite run already made."""
        if config not in self.orders:
            self.orders[config] = self.collect(config)
        return self.orders[config]

    def collect(self, config: str = FIXED) -> list:
        out = self.workdir / f"collect-{config}.json"
        self.workdir.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        cmd = self._cmd(config, ["--collect-only", f"--det-outcomes={out}",
                                 f"--det-trace={self.workdir / 'collect.jsonl'}"])
        t0 = time.monotonic()
        p = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True, timeout=self.timeout, env=self.env)
        self.seconds += time.monotonic() - t0
        if not out.exists():
            raise RuntimeError("collection failed:\n" + (p.stdout + p.stderr)[-2000:])
        order = json.loads(out.read_text())["order"]
        self.orders.setdefault(config, order)
        return order



def order_for(collected: list, config: str) -> list:
    """The shuffle alone (no plugin adjustments such as pytest-django's groups);
    ``Runner.order_of`` gives the order a run really uses."""
    return _core.repro_order_for(list(collected), config)


def prefix_through(order: list, target: str) -> list:
    """Tests up to the target, plus the next one (its teardown matches the full run)."""
    return _core.repro_prefix_through(order, target)


def ddmin(items: list, still_fails, max_tests: int | None = None) -> list:
    """Zeller's ddmin keeping the relative order: a 1-minimal sublist of ``items``
    for which ``still_fails`` holds (``still_fails(items)`` must hold)."""
    return _core.repro_ddmin(list(items), still_fails)


OutOfRuns = _core.ReproOutOfRuns


def _slug(nodeid: str) -> str:
    return _core.repro_slug(nodeid)


def _divergence(pass_run: Run | None, fail_run: Run, nodeid: str) -> dict | None:
    return _core.repro_divergence(pass_run.trace if pass_run is not None else None, fail_run.trace, nodeid)


def reproduce(runner: Runner, target: str, *, collected: list | None = None, seeds: int = 50,
              known_fail: str | None = None, known_pass: list | None = None, confirm: int = 10,
              max_runs: int = 400, out_dir: Path | None = None, command_args: list | None = None) -> dict:
    """Search, minimise, bundle and prove one failing test. Returns the bundle dict
    (``status`` = reproduced | not-found | not-minimised | replay-unstable)."""
    result, fail_trace, pass_trace = _core.repro_reproduce(runner, target, collected, seeds, known_fail, known_pass,
                                                           confirm, max_runs)
    if fail_trace is None:  # not collected, not found or not minimised: no bundle
        return result
    if out_dir is not None:
        b = Path(out_dir) / _slug(target)
        if b.exists():
            shutil.rmtree(b)
        b.mkdir(parents=True)
        (b / "order.txt").write_text("".join(n + "\n" for n in result["order"]))
        shutil.copy2(fail_trace, b / "fail.trace.jsonl")
        if pass_trace is not None and os.path.exists(pass_trace):
            shutil.copy2(pass_trace, b / "pass.trace.jsonl")
        args = list(command_args if command_args is not None else runner.pytest_args)
        result.update(_core.repro_bundle_commands(result["config"], str(b), args))
        (b / "bundle.json").write_text(json.dumps(result, indent=2))
    if not runner.keep_traces:
        runner.drop_traces()
    return result


def replay(bundle: Path, runs: int, python: str = sys.executable) -> dict:
    data = json.loads((bundle / "bundle.json").read_text())
    runner = Runner(cwd=Path.cwd(), workdir=bundle / "replay", python=python, pytest_args=data.get("pytest_args", []))
    rs = [runner.run(data["config"], data["order"], f"replay-{i}") for i in range(runs)]
    return _core.repro_replay_verdict(data, rs, runs)


def explore(runner: Runner, *, budget_s: float, max_seeds: int, out_dir: Path, confirm: int = 10,
            targets: set | None = None, repro: bool = True, max_runs: int = 400, fallback_seeds: int = 5) -> dict:
    """Seeds 1..N within the budget; one bundle per failing test (flaky only)."""
    book = _core.ExploreBook(budget_s, max_seeds)
    out_dir.mkdir(parents=True, exist_ok=True)
    collected = runner.order_of(FIXED)
    while (s := book.next_seed()) is not None:
        r = runner.run(str(s), None, f"seed-{s}")
        if r.order:
            runner.orders.setdefault(str(s), list(r.order))
        if not runner.keep_traces:
            Path(r.trace).unlink(missing_ok=True)
        book.add_seed(s, r)
        (out_dir / "explore.json").write_text(json.dumps({"seeds": book.seeds_log}, indent=1))
    book.classify(collected)
    # With targets (measurement), a target that failed under every seed is
    # reproduced too: it was flaky in the baseline even if not here.
    for n in book.todo(targets, repro):
        if book.over_budget():
            book.skip(n)
            continue
        known_fail, known_pass = book.known(n)
        b = reproduce(runner, n, collected=collected, known_fail=known_fail, known_pass=known_pass,
                      confirm=confirm, out_dir=out_dir / "bundles", max_runs=max_runs, seeds=fallback_seeds)
        book.add_bundle(n, b)
        if not runner.keep_traces:
            runner.drop_traces()
    summary = book.summary(runner.runs, len(collected), runner.log)
    (out_dir / "explore.json").write_text(json.dumps(summary, indent=1))
    return summary


def _print_bundle(b: dict) -> None:
    print(_core.repro_render_bundle(b))


def main_repro(args) -> int:
    runner = Runner(cwd=Path.cwd(), workdir=Path(args.out) / ".work", python=args.python,
                    pytest_args=args.pytest_args, timeout=args.timeout)
    b = reproduce(runner, args.test, seeds=args.seeds, confirm=args.confirm, max_runs=args.max_runs,
                  out_dir=Path(args.out), known_fail=args.seed)
    _print_bundle(b)
    if args.json:
        print(json.dumps(b, indent=2))
    return 0 if b["status"] == "reproduced" else 1


def main_explore(args) -> int:
    runner = Runner(cwd=Path.cwd(), workdir=Path(args.out) / ".work", python=args.python,
                    pytest_args=args.pytest_args, timeout=args.timeout)
    targets = None
    if args.targets:
        targets = {line.strip() for line in open(args.targets) if line.strip()}
    s = explore(runner, budget_s=args.budget * 60, max_seeds=args.max_seeds, out_dir=Path(args.out),
                confirm=args.confirm, targets=targets, repro=not args.no_repro, max_runs=args.max_runs)
    print(_core.repro_render_explore(s))
    return 0
