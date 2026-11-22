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


CONTINUE_ON_COLLECTION_ERRORS = "--continue-on-collection-errors"


def with_collection_errors(args: list) -> list:
    """pytest arguments of a search, minimisation or replay run: a module that fails to import must not stop the
    collected tests from running (pytest interrupts the whole session otherwise, so the target never runs and every
    configuration would say nothing about it)."""
    args = list(args)
    return args if CONTINUE_ON_COLLECTION_ERRORS in args else [CONTINUE_ON_COLLECTION_ERRORS, *args]


def _crashed_run(trace: Path, order, code: int) -> dict | None:
    """A run whose process died (``os._exit``, a signal, a fatal error) wrote no outcomes file: the tests its trace
    finished keep their outcomes, and the first test of its order that did not finish crashed it, a failure
    (R-055 D3: a crash was no failure, so repro never found it and explore called the suite clean)."""
    if not order or code in (2, 3, 4, 5):  # pytest's own: interrupted, internal or usage error, no tests (no crash)
        return None
    done, fps = {}, {}
    try:
        with open(trace, encoding="utf-8") as fh:
            for line in fh:
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if j.get("type") == "test" and j.get("nodeid"):
                    done[j["nodeid"]] = j.get("outcome", "unknown")
                    if j.get("fingerprint"):
                        fps[j["nodeid"]] = j["fingerprint"]
    except OSError:
        return None
    crashed = next((n for n in order if n not in done), None)
    if crashed is None:
        return None
    outcomes = {n: done[n] for n in order if n in done}
    outcomes[crashed] = "error"
    fps[crashed] = _core.digest(f"crash: exit status {code}".encode())[:32]  # the same crash, the same fingerprint
    return {"order": list(order), "outcomes": outcomes, "fingerprints": fps,
            "exceptions": {crashed: ["crash", "", f"the process exited with status {code} during this test", ""]}}


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
    problem: str = ""  # the runner's output when a run ran no test and failed: why the suite cannot run
    log: list = field(default_factory=list)

    def _cmd(self, config: str, extra: list) -> list:
        cmd = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det",
               *with_collection_errors(self.pytest_args), *extra]
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
            code, timed_out, p = -9, True, None
        dur = time.monotonic() - t0
        self.runs += 1
        self.seconds += dur
        data = {}
        if out.exists():
            try:
                data = json.loads(out.read_text())
            except ValueError:
                data = {}
        if not data.get("outcomes") and code not in (0, None) and not timed_out and order is not None:
            # (a run with a given order: repro's; a whole-suite run that crashed stays a run with no result)
            data = _crashed_run(trace, order, code) or data
        r = Run(config, data.get("order", order or []), data.get("outcomes", {}), data.get("fingerprints", {}),
                data.get("exceptions", {}), dur, code, str(trace), timed_out,
                {k: data.get(k) for k in ("controls", "seed", "order_missing")})
        self.log.append({"tag": tag, "config": config, "tests": len(r.order), "seconds": round(dur, 3),
                         "exit": code})
        if p is not None and code != 0 and not r.outcomes:  # (r.order falls back to the order asked for)
            self.note_problem(p, code)
        return r

    def note_problem(self, p, code: int) -> None:
        """Keep why the suite cannot run (collection errors, a missing plugin, a bad argument): the end of the
        runner's output, shown by repro and explore instead of "not collected" or an empty exploration."""
        lines = [ln.rstrip() for ln in ((p.stdout or "") + (p.stderr or "")).splitlines() if ln.strip()]
        # pytest: the error lines (`E ...`), the short summary (`ERROR path`) and the last line; else the tail
        key = [ln for ln in lines if ln.startswith(("E ", "ERROR ", "error:", "usage:")) or "Error" in ln[:40]]
        self.problem = f"runner exit {code}\n" + "\n".join((key[-20:] + lines[-1:]) if key else lines[-25:])

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
        if p.returncode != 0:
            self.note_problem(p, p.returncode)
        if not out.exists():
            raise RuntimeError("collection failed:\n" + (p.stdout + p.stderr)[-2000:])
        order = json.loads(out.read_text())["order"]
        self.orders.setdefault(config, order)
        return order



@dataclass
class ShellRunner(Runner):
    """``Runner`` for the runner shells (``python -m detpy unittest|django|nose2|ward|zope-testrunner|doctest``):
    the same search, minimisation and replay as for pytest (audit G-0532, G-0540). ``runner_name`` is the shell;
    ``pytest_args`` hold the runner's own arguments. Collection is a whole run (the shells have no collect-only):
    its outcomes file holds the order."""

    runner_name: str = "unittest"

    def _cmd(self, config: str, extra: list) -> list:
        cmd = [self.python, "-m", "detpy", self.runner_name, "--det", *extra, *self.pytest_args]
        if config != FIXED:
            cmd.insert(5, f"--det-seed={int(config)}")
        return cmd

    def collect(self, config: str = FIXED) -> list:
        r = self.run(config, None, f"collect-{config}")
        if not r.order:
            raise RuntimeError(f"collection failed: no test ran under `python -m detpy {self.runner_name}`")
        self.orders.setdefault(config, list(r.order))
        return list(r.order)


@dataclass
class PlanRunner(Runner):
    """``fenvix repro TEST --plan PLAN`` (audit G-1557): a failure seen under pytest-xdist, searched in the list of
    the worker that ran the test (``plan.json`` of the -n run), serially: every configuration's order is that list."""

    plan_list: list = field(default_factory=list)

    def order_of(self, config: str) -> list:
        return list(self.plan_list)

    def collect(self, config: str = FIXED) -> list:
        return list(self.plan_list)


def plan_worker(plan_path: str, test: str) -> tuple[str, list, str]:
    """(worker, its list, the run's configuration: 'fixed' or the seed) of the worker that ran ``test``."""
    with open(plan_path) as f:
        plan = json.load(f)
    if plan.get("format") != "detpy-plan":
        raise ValueError(f"{plan_path} is not a plan written by a `--det -n N` run")
    for wid, ids in sorted((plan.get("lists") or {}).items()):
        if test in ids:
            config = FIXED
            trace = os.path.join(os.path.dirname(plan_path), "trace.jsonl")
            try:
                with open(trace) as t:
                    meta = json.loads(t.readline()).get("meta") or {}
                if meta.get("shuffle"):
                    config = str(meta.get("seed"))
            except (OSError, ValueError):
                pass
            return wid, list(ids), config
    raise ValueError(f"{test} is in no worker list of {plan_path}")


def shell_command(runner_name: str, config: str, order_path: str, args: list) -> str:
    import shlex

    words = ["python", "-m", "detpy", runner_name, "--det"]
    if config != FIXED:
        words.append(f"--det-seed={config}")
    words.append(f"--det-order={order_path}")
    return " ".join(shlex.quote(w) for w in [*words, *args])


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
    if fail_trace is None:  # not collected, not run, not found or not minimised: no bundle
        problem = getattr(runner, "problem", "")  # (any Driver: simulated runners in tests have none)
        if result.get("status") in ("not-collected", "not-run") and problem:
            result["suite_error"] = problem
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
        if isinstance(runner, Runner) and not isinstance(runner, ShellRunner):  # the replay runs as the search did
            args = with_collection_errors(args)
        result.update(_core.repro_bundle_commands(result["config"], str(b), args))
        (b / "bundle.json").write_text(json.dumps(result, indent=2))
    if not runner.keep_traces:
        runner.drop_traces()
    return result


def provenance(cwd: Path, fail_trace: Path, python: str) -> dict:
    """What a bundle needs to be replayed elsewhere (audit G-1556): the commit (and whether the checkout had local
    changes), the interpreter, the installed distributions, the run inputs of the failing run (time zone, locale,
    environment digests, seed, ...)."""
    def git(*args):
        try:
            p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
            return p.stdout.strip() if p.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    out: dict = {"commit": git("rev-parse", "HEAD"), "dirty": None, "python": None, "platform": sys.platform,
                 "distributions": [], "inputs": {}}
    status = git("status", "--porcelain", "--untracked-files=no")
    out["dirty"] = None if status is None else bool(status)
    try:
        code = ("import sys, json, importlib.metadata as m; print(json.dumps([sys.version.split()[0], sorted("
                "f\"{d.metadata['Name']}=={d.version}\" for d in m.distributions() if d.metadata['Name'])]))")
        p = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=60)
        out["python"], out["distributions"] = json.loads(p.stdout)
    except Exception:
        pass
    try:
        with open(fail_trace) as f:
            out["inputs"] = (json.loads(f.readline()).get("meta") or {}).get("inputs") or {}
    except (OSError, ValueError):
        pass
    return out


def finish_bundle(b: dict, out_dir: Path, cwd: Path, python: str, runner_name: str) -> dict:
    """The product's additions to a bundle written by ``reproduce`` (``fenvix repro``): the runner, the replay
    command of the product, the provenance and a failure location relative to the project (audit G-1556)."""
    b["runner"] = runner_name
    bdir = Path(out_dir) / _slug(b.get("test", ""))
    f = bdir / "bundle.json"
    if not f.exists():
        return b
    data = json.loads(f.read_text())
    data["runner"] = runner_name
    data["replay_command"] = f"fenvix replay {data.get('bundle', bdir)}"
    data["provenance"] = provenance(cwd, bdir / "fail.trace.jsonl", python)
    data["project"] = str(Path(cwd).resolve())  # where `fenvix replay` runs from (named when run elsewhere)
    _relative_exception(data, cwd)
    f.write_text(json.dumps(data, indent=2))
    b.update({k: data[k] for k in ("replay_command", "provenance", "exception") if k in data})
    if data.get("command"):
        b.setdefault("command", data["command"])  # the single failing run (printed as `fenvix pytest ...`)
    return b


def _relative_exception(result: dict, cwd: Path) -> None:
    """The failure's location relative to the project (an absolute local path does not travel)."""
    exc = result.get("exception")
    if isinstance(exc, list) and len(exc) > 3 and isinstance(exc[3], str) and os.path.isabs(exc[3]):
        try:
            exc[3] = os.path.relpath(exc[3], cwd)
        except ValueError:
            pass


def replay(bundle: Path, runs: int, python: str = sys.executable) -> dict:
    data = json.loads((bundle / "bundle.json").read_text())
    shell = data.get("runner") not in (None, "pytest")
    cls = ShellRunner if shell else Runner
    kw = {"runner_name": data["runner"]} if shell else {}
    cwd = Path.cwd()
    _check_project(data, cwd)
    runner = cls(cwd=cwd, workdir=bundle / "replay", python=python, pytest_args=data.get("pytest_args", []),
                 **kw)
    rs = []
    for i in range(runs):
        rs.append(runner.run(data["config"], data["order"], f"replay-{i}"))
        outcome = rs[-1].outcome(data.get("test"))
        if outcome == "missing":
            # reviewer #9: the test did not run at all (another directory, a renamed test, a suite that no longer
            # collects): that is not "no longer fails", and the remaining runs would say the same
            return {"test": data.get("test"), "runs": runs, "fails": 0, "identical_fingerprint": False,
                    "matches_bundle": False, "status": "not-collected",
                    "suite_error": getattr(runner, "problem", "") or f"runner exit {rs[-1].exit_code}: the test was not collected"}
        if isinstance(outcome, str) and (outcome.startswith("skip") or outcome.startswith("xfail")):
            # R-051 R3, R-054 N3: collected but skipped, or marked as an expected failure (xfail, run=False or not):
            # quarantined, its result is not a failure of the defect, so the replay says nothing either
            why = "its body did not run" if outcome.startswith("skip") else "it is marked as an expected failure"
            return {"test": data.get("test"), "runs": runs, "fails": 0, "identical_fingerprint": False,
                    "matches_bundle": False, "status": "not-run",
                    "suite_error": f"the test was {outcome}: {why}"}
    return _core.repro_replay_verdict(data, rs, runs)


def _check_project(data: dict, cwd: Path) -> None:
    """A bundle replays from its project's root (the directory `fenvix repro` ran in): its order names files
    relative to it. From anywhere else the runner would collect nothing, or a whole other tree (reviewer #9)."""
    path = str(data.get("test", "")).split("::", 1)[0]
    if not path.endswith(".py") or (cwd / path).exists():
        return  # not a file id (unittest dotted names, doctest), or found here
    proj = data.get("project")
    where = f" ({proj})" if proj else ""
    raise ValueError(f"{path} is not under {cwd}: run `fenvix replay` from the project root, the directory "
                     f"`fenvix repro` ran in{where}")


def explore(runner: Runner, *, budget_s: float, max_seeds: int, out_dir: Path, confirm: int = 10,
            targets: set | None = None, repro: bool = True, max_runs: int = 400, fallback_seeds: int = 5,
            first_seed: int = 1) -> dict:
    """Seeds first_seed.. within the budget; one bundle per failing test (flaky only)."""
    book = _core.ExploreBook(budget_s, max_seeds, first_seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    collected = runner.order_of(FIXED)
    # a module that does not import: the tests that collect are explored, and the suite is reported as not
    # collecting cleanly (plain pytest stops at collection there; R-050 V10)
    collection_errors = getattr(runner, "problem", "") if collected else ""
    crashed_seeds = []
    while (s := book.next_seed()) is not None:
        r = runner.run(str(s), None, f"seed-{s}")
        if not r.outcomes and r.exit_code not in (0, None) and not r.timed_out:
            crashed_seeds.append(s)
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
    if not collected and getattr(runner, "problem", ""):  # the suite cannot run: say why (reviewer #10)
        summary["suite_error"] = runner.problem
    if collection_errors:
        summary["collection_errors"] = collection_errors
    if crashed_seeds:
        summary["crashed_seeds"] = crashed_seeds
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
