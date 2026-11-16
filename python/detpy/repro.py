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
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import _core

FIXED = "fixed"


def is_fail(outcome) -> bool:
    return isinstance(outcome, str) and ("failed" in outcome or "error" in outcome)


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
        return self.outcomes.get(nid, "missing")


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

    def collect(self) -> list:
        out = self.workdir / "collect.json"
        self.workdir.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        cmd = self._cmd(FIXED, ["--collect-only", f"--det-outcomes={out}",
                                f"--det-trace={self.workdir / 'collect.jsonl'}"])
        t0 = time.monotonic()
        p = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True, timeout=self.timeout, env=self.env)
        self.seconds += time.monotonic() - t0
        if not out.exists():
            raise RuntimeError("collection failed:\n" + (p.stdout + p.stderr)[-2000:])
        return json.loads(out.read_text())["order"]


def order_for(collected: list, config: str) -> list:
    """The order a full ``pytest --det [--det-seed=S]`` run uses."""
    if config == FIXED:
        return list(collected)
    perm = _core.shuffle_order(list(collected), int(config))
    return [collected[i] for i in perm]


def prefix_through(order: list, target: str) -> list:
    """Tests up to the target, plus the next one (its teardown matches the full run)."""
    i = order.index(target)
    return order[: i + 2]


def ddmin(items: list, still_fails, max_tests: int | None = None) -> list:
    """Zeller's ddmin keeping the relative order: a 1-minimal sublist of ``items``
    for which ``still_fails`` holds (``still_fails(items)`` must hold)."""
    n = 2
    while len(items) >= 2:
        size = len(items)
        chunks = [items[i * size // n:(i + 1) * size // n] for i in range(n)]
        chunks = [c for c in chunks if c]
        reduced = False
        for c in chunks:
            if still_fails(c):
                items, n, reduced = c, 2, True
                break
        if not reduced:
            for i in range(len(chunks)):
                comp = [x for j, c in enumerate(chunks) if j != i for x in c]
                if still_fails(comp):
                    items, n, reduced = comp, max(n - 1, 2), True
                    break
        if not reduced:
            if n >= len(items):
                break
            n = min(len(items), 2 * n)
    if len(items) == 1 and still_fails([]):
        return []
    return items


def _version() -> str:
    from . import __version__

    return __version__


class OutOfRuns(Exception):
    pass


def _slug(nodeid: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid.split("::")[-1])[:60]
    return f"{base}-{hashlib.sha1(nodeid.encode()).hexdigest()[:8]}"


def _divergence(pass_run: Run | None, fail_run: Run, nodeid: str) -> dict | None:
    if pass_run is None or not os.path.exists(pass_run.trace) or not os.path.exists(fail_run.trace):
        return None
    try:
        rep = json.loads(_core.verify([pass_run.trace, fail_run.trace]))
    except Exception as exc:  # pragma: no cover - corrupt trace
        return {"error": repr(exc)}
    t = next((t for t in rep["tests"] if t["nodeid"] == nodeid), None)
    if not t:
        return None
    d = t.get("divergence") or {}
    keep = {k: d.get(k) for k in ("index", "reason", "description", "event_a", "event_b")}
    keep["fingerprints"] = t.get("fingerprints")
    return keep


def reproduce(runner: Runner, target: str, *, collected: list | None = None, seeds: int = 50,
              known_fail: str | None = None, known_pass: list | None = None, confirm: int = 10,
              max_runs: int = 400, out_dir: Path | None = None, command_args: list | None = None) -> dict:
    """Search, minimise, bundle and prove one failing test. Returns the bundle dict
    (``status`` = reproduced | not-found | not-minimised | replay-unstable)."""
    t_start = time.monotonic()
    runs_at_start = runner.runs
    collected = collected if collected is not None else runner.collect()
    if target not in collected:
        return {"test": target, "status": "not-collected"}
    budget = {"left": max_runs}
    cache: dict = {}

    def run_order(config, order, tag):
        key = (config, tuple(order))
        if key in cache:
            return cache[key]
        if budget["left"] <= 0:
            raise OutOfRuns()
        budget["left"] -= 1
        r = runner.run(config, order, tag)
        cache[key] = r
        return r

    # 1. search ----------------------------------------------------------------
    passing: list = list(known_pass or [])
    found = None
    configs = [FIXED] + [str(s) for s in range(1, seeds + 1)]
    if known_fail:
        # The configuration that failed in a full run first; if its prefix does not
        # fail (state from a later test, or a non-L0 source), keep searching.
        configs = [known_fail] + [c for c in configs if c != known_fail]
    searched = 0
    for config in configs:
        order = prefix_through(order_for(collected, config), target)
        r = run_order(config, order, f"search-{config}")
        searched += 1
        if is_fail(r.outcome(target)):
            found = (config, order, r)
            break
        if r.outcome(target) == "passed":
            passing.append(config)
    result = {"test": target, "configs_searched": searched}
    if found is None:
        result.update(status="not-found", runs=runner.runs - runs_at_start,
                      seconds=round(time.monotonic() - t_start, 2))
        return result
    config, order, first_fail = found
    before = order[: order.index(target)]

    # 2. minimise --------------------------------------------------------------
    tests_run = {"n": 0}

    def fails_with(sub):
        tests_run["n"] += 1
        r = run_order(config, list(sub) + [target], f"min-{config}-{tests_run['n']}")
        return is_fail(r.outcome(target))

    kind, polluters, setters, pass_run = "order", [], [], None
    try:
        alone = run_order(config, [target], f"alone-{config}")
        if is_fail(alone.outcome(target)):
            kind = "fails-alone"
            minimal = []
            # Brittle test: name what makes it pass, from a passing configuration.
            for pconf in passing or ([FIXED] if config != FIXED else []):
                porder = prefix_through(order_for(collected, pconf), target)
                pbefore = porder[: porder.index(target)]
                if not pbefore:
                    continue

                def passes_with(sub, pconf=pconf):
                    tests_run["n"] += 1
                    r = run_order(config, list(sub) + [target], f"set-{pconf}-{tests_run['n']}")
                    return r.outcome(target) == "passed"

                if passes_with(pbefore):
                    setters = ddmin(pbefore, passes_with)
                    if setters:
                        kind = "brittle"
                        pass_run = run_order(config, setters + [target], "setter-pass")
                    break
        else:
            pass_run = alone
            minimal = ddmin(before, fails_with)
            polluters = minimal
    except OutOfRuns:
        result.update(status="not-minimised", config=config, prefix_length=len(before) + 1,
                      runs=runner.runs - runs_at_start, seconds=round(time.monotonic() - t_start, 2))
        return result
    bundle_order = minimal + [target]

    # 3 + 4. replay and prove ----------------------------------------------------
    replays = [runner.run(config, bundle_order, f"replay-{i}") for i in range(confirm)]
    outcomes = [r.outcome(target) for r in replays]
    fps = [r.fingerprints.get(target) for r in replays]
    fails = sum(is_fail(o) for o in outcomes)
    identical = len(set(fps)) == 1 and fps[0] is not None
    div = _divergence(pass_run, replays[0], target)
    seed_args = [] if config == FIXED else [f"--det-seed={config}"]
    result.update(
        status="reproduced" if fails == confirm and identical else "replay-unstable",
        config=config, seed=None if config == FIXED else int(config), kind=kind,
        prefix_length=len(before) + 1, minimal_length=len(bundle_order),
        polluters=polluters, setters=setters,
        order=bundle_order, outcome=outcomes[0], exception=replays[0].exceptions.get(target),
        replay={"runs": confirm, "fails": fails, "fingerprints": sorted(set(f for f in fps if f)),
                "identical_fingerprint": identical},
        divergence=div, runs=runner.runs - runs_at_start, seconds=round(time.monotonic() - t_start, 2),
        controls=replays[0].meta.get("controls"), detpy=_version(),
        python=sys.version.split()[0] if runner.python == sys.executable else runner.python,
    )
    if out_dir is not None:
        b = Path(out_dir) / _slug(target)
        if b.exists():
            shutil.rmtree(b)
        b.mkdir(parents=True)
        (b / "order.txt").write_text("".join(n + "\n" for n in bundle_order))
        shutil.copy2(replays[0].trace, b / "fail.trace.jsonl")
        if pass_run is not None and os.path.exists(pass_run.trace):
            shutil.copy2(pass_run.trace, b / "pass.trace.jsonl")
        args = list(command_args if command_args is not None else runner.pytest_args)
        result["command"] = " ".join(shlex.quote(a) for a in
                                     ["pytest", "--det", *seed_args, f"--det-order={b / 'order.txt'}", *args])
        result["replay_command"] = f"detpy replay {shlex.quote(str(b))}"
        result["pytest_args"] = args
        result["bundle"] = str(b)
        (b / "bundle.json").write_text(json.dumps(result, indent=2))
    if not runner.keep_traces:
        runner.drop_traces()
    return result


def replay(bundle: Path, runs: int, python: str = sys.executable) -> dict:
    data = json.loads((bundle / "bundle.json").read_text())
    runner = Runner(cwd=Path.cwd(), workdir=bundle / "replay", python=python, pytest_args=data.get("pytest_args", []))
    rs = [runner.run(data["config"], data["order"], f"replay-{i}") for i in range(runs)]
    target = data["test"]
    fps = {r.fingerprints.get(target) for r in rs}
    fails = sum(is_fail(r.outcome(target)) for r in rs)
    return {"test": target, "runs": runs, "fails": fails, "identical_fingerprint": len(fps) == 1 and None not in fps,
            "matches_bundle": fps <= set(data.get("replay", {}).get("fingerprints", [])) and None not in fps}


def explore(runner: Runner, *, budget_s: float, max_seeds: int, out_dir: Path, confirm: int = 10,
            targets: set | None = None, repro: bool = True, max_runs: int = 400, fallback_seeds: int = 5) -> dict:
    """Seeds 1..N within the budget; one bundle per failing test (flaky only)."""
    t0 = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    collected = runner.collect()
    seeds_log, fail_cfg, pass_cfg = [], {}, {}
    for s in range(1, max_seeds + 1):
        if time.monotonic() - t0 > budget_s:
            break
        r = runner.run(str(s), None, f"seed-{s}")
        if not runner.keep_traces:
            Path(r.trace).unlink(missing_ok=True)
        failing = sorted(n for n, o in r.outcomes.items() if is_fail(o))
        seeds_log.append({"seed": s, "seconds": round(r.duration, 3), "tests": len(r.outcomes),
                          "failing": failing, "exit": r.exit_code, "timed_out": r.timed_out})
        for n, o in r.outcomes.items():
            if is_fail(o):
                fail_cfg.setdefault(n, str(s))
            elif o == "passed":
                pass_cfg.setdefault(n, []).append(str(s))
        (out_dir / "explore.json").write_text(json.dumps({"seeds": seeds_log}, indent=1))
    seeds_done = len(seeds_log)
    always = sorted(n for n in fail_cfg if not pass_cfg.get(n) and
                    all(n in x["failing"] for x in seeds_log if n in collected))
    flaky = sorted(n for n in fail_cfg if n not in always)
    bundles, skipped = [], []
    if repro:
        # With targets (measurement), a target that failed under every seed is
        # reproduced too: it was flaky in the baseline even if not here.
        todo = flaky if targets is None else [n for n in sorted(fail_cfg) if n in targets]
        for n in todo:
            if time.monotonic() - t0 > budget_s:
                skipped.append(n)
                continue
            b = reproduce(runner, n, collected=collected, known_fail=fail_cfg[n], known_pass=pass_cfg.get(n, []),
                          confirm=confirm, out_dir=out_dir / "bundles", max_runs=max_runs, seeds=fallback_seeds)
            b["first_failing_seed"] = int(fail_cfg[n])
            bundles.append(b)
            if not runner.keep_traces:
                runner.drop_traces()
    # Deduplication: by failing test (one bundle each), then families by first
    # diverging event and by polluter set.
    fam_div, fam_pol = {}, {}
    for b in bundles:
        if b.get("status") != "reproduced":
            continue
        d = b.get("divergence") or {}
        ev = d.get("event_b") or {}
        key = f"{d.get('reason')}|{ev.get('s')}|{ev.get('at')}"
        fam_div.setdefault(key, []).append(b["test"])
        fam_pol.setdefault(" + ".join(b.get("polluters") or b.get("setters") or ["<none>"]), []).append(b["test"])
    summary = {
        "seeds": seeds_done, "seconds": round(time.monotonic() - t0, 2), "runs": runner.runs,
        "collected": len(collected), "failing_tests": len(fail_cfg), "always_failing": always,
        "flaky_failing": flaky, "bundles": bundles, "not_reproduced_budget": skipped,
        "families_by_divergence": fam_div, "families_by_polluter": fam_pol, "seeds_log": seeds_log,
        "run_log": runner.log,
    }
    (out_dir / "explore.json").write_text(json.dumps(summary, indent=1))
    return summary


def _print_bundle(b: dict) -> None:
    print(f"detpy repro: {b['test']}: {b['status']}")
    if b.get("status") in ("reproduced", "replay-unstable"):
        where = "fixed order" if b["config"] == FIXED else f"--det-seed={b['config']}"
        print(f"  found with {where}; order minimised from {b['prefix_length']} to {b['minimal_length']} test(s)")
        if b.get("polluters"):
            print(f"  polluter(s): {', '.join(b['polluters'])}")
        if b.get("setters"):
            print(f"  fails without (state setter): {', '.join(b['setters'])}")
        if b.get("kind") == "fails-alone":
            print("  fails when run alone (no polluter)")
        rp = b["replay"]
        print(f"  replay: {rp['fails']}/{rp['runs']} failed, identical fingerprint: {rp['identical_fingerprint']}")
        d = b.get("divergence") or {}
        if d.get("description"):
            print(f"  first diverging event vs a passing run: {d.get('reason')}: {d.get('description')}")
        if b.get("command"):
            print(f"  replay: {b['command']}")
    print(f"  {b.get('runs')} pytest runs, {b.get('seconds')} s")


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
    rep = [b for b in s["bundles"] if b.get("status") == "reproduced"]
    print(f"detpy explore: {s['seeds']} seeds in {s['seconds']} s; {len(s['flaky_failing'])} flaky failing tests "
          f"({len(s['always_failing'])} always failing, not flaky); {len(rep)} replay bundles; "
          f"{len(s['families_by_divergence'])} distinct first diverging events, "
          f"{len(s['families_by_polluter'])} distinct polluter sets")
    for b in s["bundles"]:
        _print_bundle(b)
    return 0
