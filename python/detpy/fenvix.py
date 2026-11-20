"""``fenvix``: the one command of the product (installed as a console script with the Python package).

    fenvix pytest [pytest args]             run pytest deterministically (--det is added when absent)
    fenvix unittest|django|nose2|ward|zope-testrunner|doctest [args]
                                            the other Python runners, deterministically
    fenvix vitest|jest|mocha|node-test|ava|tap|uvu|jasmine|bun|deno|playwright [args]
                                            the JavaScript runners (detjs), deterministically
    fenvix repro TEST [options] [-- runner args]
                                            turn a flaky test into a reproducible defect: cause, seed, order,
                                            replay command, proof (the failure replayed N/N with one fingerprint)
    fenvix explore --budget MINUTES [options] [-- runner args]
                                            nightly exploration: seeds within a budget, one defect per flaky test
    fenvix replay BUNDLE [--runs N]         replay a defect and check it fails every time with one fingerprint
    fenvix verify TRACE TRACE... [--json] [--show-stable] [--ignore-env NAME]
                                            compare runs: identical only when the inputs and every event match
    fenvix cassette list|rename OLD NEW|drop TEST...
                                            the network recordings, per test
    fenvix doctor [--install]               what this machine can give: every control, checked (--install: only what
                                            an installation needs: interpreter, native core, no foreign `detpy`)
    fenvix detect [DIR]                     languages and runners of DIR (one per line)
    fenvix version | --version | -V         versions of the installed components
    fenvix go test [args]                   fenvix-go test ...  (runner image only: $FENVIX_HOME/bin)
    fenvix jvm run|decide ...               the JVM agent / fenvix-skip (runner image only: $FENVIX_HOME/jvm, /bin)

Every subcommand takes --help. The interface of repro / explore / replay / verify does not depend on the runner:
a runner adapter (``ADAPTERS`` below) does the runner-specific work; see docs/CLI.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, _support

PROG = "fenvix"
PY_RUNNERS = ("unittest", "django", "nose2", "ward", "zope-testrunner", "doctest")
JS_RUNNERS = ("vitest", "jest", "mocha", "node-test", "ava", "tap", "uvu", "jasmine", "bun", "deno", "playwright")
HOME = os.environ.get("FENVIX_HOME", "/opt/fenvix")


# ---------------------------------------------------------------------------------------------------------------
# runner adapters: what repro / explore / replay need from a runner. The commands, their options, their output and
# the bundle layout are the same for every runner; an adapter only runs its runner.
class Adapter:
    """Interface of a runner adapter (docs/CLI.md, "Runner adapters").

    name           the runner's name (``--runner NAME``; stored in every bundle as ``runner``)
    available      None when the adapter can run here, else the reason it cannot (shown to the user)
    owns(test)     whether a test id has this runner's shape (used when --runner is not given)
    detect(dir)    whether the project in ``dir`` uses this runner
    repro(ns)      search, minimise, bundle and prove one failing test: returns the bundle dict
    explore(ns)    seeds within a budget, one bundle per flaky failing test: returns the summary dict
    replay(b, n)   replay bundle directory ``b`` n times: returns {runs, fails, identical_fingerprint, ...}
    """

    name = "?"

    def available(self) -> str | None:
        return None

    def owns(self, test: str) -> bool:
        return False

    def detect(self, d: Path) -> bool:
        return False

    def repro(self, ns) -> dict:
        raise NotImplementedError

    def explore(self, ns) -> dict:
        raise NotImplementedError

    def replay(self, bundle: Path, runs: int, python: str) -> dict:
        raise NotImplementedError


class PytestAdapter(Adapter):
    """pytest (and unittest suites run through pytest): ``detpy.repro`` over ``pytest --det`` subprocesses."""

    name = "pytest"

    def owns(self, test: str) -> bool:
        return "::" in test or test.endswith(".py")

    def detect(self, d: Path) -> bool:
        names = {p.name for p in d.iterdir()} if d.is_dir() else set()
        return bool(names & {"pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini", "setup.py"}) or (
            (d / "tests").is_dir() and any((d / "tests").glob("test_*.py")))

    def repro(self, ns) -> dict:
        from . import repro as _repro

        known = ns.seed
        if getattr(ns, "plan", None):
            # a failure seen under -n: the worker's own list, serially (audit G-1557)
            wid, ids, config = _repro.plan_worker(ns.plan, ns.test)
            runner = _repro.PlanRunner(cwd=Path.cwd(), workdir=Path(ns.out) / ".work", python=ns.python,
                                       pytest_args=ns.runner_args, timeout=ns.timeout, plan_list=ids)
            known = known or config
            print(f"{PROG} repro: {ns.test} ran in worker {wid} ({len(ids)} tests, configuration {config}); "
                  f"searching its list", file=sys.stderr)
        else:
            runner = _repro.Runner(cwd=Path.cwd(), workdir=Path(ns.out) / ".work", python=ns.python,
                                   pytest_args=ns.runner_args, timeout=ns.timeout)
        b = _repro.reproduce(runner, ns.test, seeds=ns.seeds, confirm=ns.confirm, max_runs=ns.max_runs,
                             out_dir=Path(ns.out), known_fail=known)
        return _repro.finish_bundle(b, Path(ns.out), Path.cwd(), ns.python, self.name)

    def explore(self, ns) -> dict:
        from . import repro as _repro

        runner = _repro.Runner(cwd=Path.cwd(), workdir=Path(ns.out) / ".work", python=ns.python,
                               pytest_args=ns.runner_args, timeout=ns.timeout)
        targets = None
        if ns.targets:
            targets = {line.strip() for line in open(ns.targets) if line.strip()}
        s = _repro.explore(runner, budget_s=ns.budget * 60, max_seeds=ns.max_seeds, out_dir=Path(ns.out),
                           confirm=ns.confirm, targets=targets, repro=not ns.no_repro, max_runs=ns.max_runs,
                           first_seed=ns.first_seed)
        s["runner"] = self.name
        _finish_explore(s, ns, self.name)
        return s

    def replay(self, bundle: Path, runs: int, python: str) -> dict:
        from . import repro as _repro

        return _repro.replay(bundle, runs, python)


class ShellAdapter(PytestAdapter):
    """The other Python runners (unittest, Django, nose2, ward, zope.testrunner, doctest) through their shells
    (``python -m detpy <runner> --det``): the same search, minimisation and replay (audit G-0532, G-0540). Test ids
    are the shell's (``fenvix <runner> --det`` prints them in its trace); pick the adapter with ``--runner``."""

    def __init__(self, name: str, markers: tuple = ()):
        self.name, self.markers = name, markers

    def owns(self, test: str) -> bool:
        return False  # ids of the shells look like other runners' ids: --runner chooses

    def detect(self, d: Path) -> bool:
        return any((d / m).exists() for m in self.markers)

    def _runner(self, ns):
        from . import repro as _repro

        return _repro.ShellRunner(cwd=Path.cwd(), workdir=Path(ns.out) / ".work", python=ns.python,
                                  pytest_args=ns.runner_args, timeout=ns.timeout, runner_name=self.name)

    def repro(self, ns) -> dict:
        from . import repro as _repro

        runner = self._runner(ns)
        b = _repro.reproduce(runner, ns.test, seeds=ns.seeds, confirm=ns.confirm, max_runs=ns.max_runs,
                             out_dir=Path(ns.out), known_fail=ns.seed, command_args=ns.runner_args)
        bdir = Path(ns.out) / _repro._slug(ns.test)
        if (bdir / "bundle.json").exists():
            b["command"] = _repro.shell_command(self.name, b["config"], str(bdir / "order.txt"), ns.runner_args)
            data = json.loads((bdir / "bundle.json").read_text())
            data.update(command=b["command"], pytest_args=list(ns.runner_args))
            (bdir / "bundle.json").write_text(json.dumps(data, indent=2))
        return _repro.finish_bundle(b, Path(ns.out), Path.cwd(), ns.python, self.name)

    def explore(self, ns) -> dict:
        from . import repro as _repro

        runner = self._runner(ns)
        targets = None
        if ns.targets:
            targets = {line.strip() for line in open(ns.targets) if line.strip()}
        s = _repro.explore(runner, budget_s=ns.budget * 60, max_seeds=ns.max_seeds, out_dir=Path(ns.out),
                           confirm=ns.confirm, targets=targets, repro=not ns.no_repro, max_runs=ns.max_runs,
                           first_seed=ns.first_seed)
        s["runner"] = self.name
        _finish_explore(s, ns, self.name)
        return s


class PlannedAdapter(Adapter):
    """A runner whose shell exists (``fenvix <runner> --det`` runs it deterministically) but whose repro / explore /
    replay adapter is not built yet: the commands say so instead of failing obscurely."""

    def __init__(self, name: str, shapes: tuple, markers: tuple):
        self.name, self.shapes, self.markers = name, shapes, markers

    def available(self) -> str | None:
        return (f"repro / explore / replay are not available for {self.name} in this version: the interface is "
                f"fixed (docs/CLI.md), the {self.name} adapter is not built yet. `fenvix {self.name} --det` runs the "
                f"suite deterministically and `fenvix verify` compares its runs.")

    def owns(self, test: str) -> bool:
        return any(s in test for s in self.shapes)

    def detect(self, d: Path) -> bool:
        return any((d / m).exists() for m in self.markers)


ADAPTERS: dict[str, Adapter] = {
    "pytest": PytestAdapter(),
    "unittest": ShellAdapter("unittest"),
    "django": ShellAdapter("django", ("manage.py",)),
    "nose2": ShellAdapter("nose2", ("nose2.cfg", "unittest.cfg")),
    "ward": ShellAdapter("ward"),
    "zope-testrunner": ShellAdapter("zope-testrunner"),
    "doctest": ShellAdapter("doctest"),
    "vitest": PlannedAdapter("vitest", (".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.mts", ".test.tsx"),
                             ("vitest.config.ts", "vitest.config.js", "vitest.config.mts", "vitest.config.mjs")),
    "jest": PlannedAdapter("jest", (".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.tsx", ".test.jsx"),
                           ("jest.config.js", "jest.config.ts", "jest.config.cjs", "jest.config.mjs")),
    "playwright": PlannedAdapter("playwright", (".spec.ts", ".e2e.ts"),
                                 ("playwright.config.ts", "playwright.config.js")),
}


def _finish_explore(s: dict, ns, runner: str) -> None:
    from . import repro as _repro

    for b in s.get("bundles", []) if isinstance(s.get("bundles"), list) else []:
        if isinstance(b, dict) and b.get("test"):
            _repro.finish_bundle(b, Path(ns.out) / "bundles", Path.cwd(), ns.python, runner)


def _write_runner(bundle: Path, runner: str) -> None:
    f = bundle / "bundle.json"
    if f.exists():
        data = json.loads(f.read_text())
        data["runner"] = runner
        f.write_text(json.dumps(data, indent=2))


def pick_adapter(explicit: str | None, test: str | None = None, bundle: Path | None = None) -> Adapter:
    if explicit:
        if explicit not in ADAPTERS:
            raise SystemExit(f"{PROG}: unknown runner {explicit!r} (known: {', '.join(ADAPTERS)})")
        return ADAPTERS[explicit]
    if bundle is not None:
        try:
            r = json.loads((bundle / "bundle.json").read_text()).get("runner", "pytest")
            return ADAPTERS.get(r, ADAPTERS["pytest"])
        except (OSError, ValueError):
            pass
    cwd = Path.cwd()
    if test:
        owners = [a for a in ADAPTERS.values() if a.owns(test)]
        if len(owners) == 1:
            return owners[0]
        if owners:
            local = [a for a in owners if a.detect(cwd)]
            if len(local) == 1:
                return local[0]
            raise SystemExit(f"{PROG}: {test!r} could be a test of {', '.join(a.name for a in owners)}: "
                             f"say which with --runner")
    local = [a for a in ADAPTERS.values() if a.detect(cwd)]
    return local[0] if local else ADAPTERS["pytest"]


# ---------------------------------------------------------------------------------------------------------------
# product output
def _q(s: str) -> str:
    import shlex

    return shlex.quote(str(s))


def _uncontrolled_of(bundle_dir: Path, test: str) -> list:
    t = bundle_dir / "fail.trace.jsonl"
    if not t.exists():
        return []
    try:
        for line in t.read_text().splitlines():
            r = json.loads(line)
            if r.get("type") == "test" and r.get("nodeid") == test:
                return r.get("uncontrolled", [])
    except (OSError, ValueError):
        pass
    return []


def cause_of(b: dict) -> str:
    """One sentence: why the test fails (from the bundle)."""
    kind = b.get("kind")
    cfg = b.get("config")
    where = "the fixed order" if cfg == "fixed" else f"--det-seed={cfg}"
    if kind == "order" and b.get("polluters"):
        return (f"test order: it fails when run after {', '.join(b['polluters'])} "
                f"(state left behind by {'that test' if len(b['polluters']) == 1 else 'those tests'})")
    if kind == "brittle" and b.get("setters"):
        return (f"test order: it passes only when run after {', '.join(b['setters'])} "
                f"(it depends on state {'that test sets' if len(b['setters']) == 1 else 'those tests set'} up)")
    d = b.get("divergence") or {}
    if d.get("reason") and d.get("description"):
        return f"{d['reason']}: it fails alone under {where}; first divergent event vs a passing run: {d['description']}"
    if kind == "fails-alone":
        return (f"seed: it fails alone under {where} and passes under another seed (a seeded generator, the hash "
                f"seed or the clock decide it)")
    return "unknown"


def render_repro(b: dict, out: Path) -> str:
    test = b.get("test", "?")
    status = b.get("status", "?")
    lines = [f"{PROG} repro: {test}"]
    if status == "not-collected":
        lines.append(f"  not collected: no test has this id. Use an id as the runner prints it (`{PROG} pytest "
                     f"--collect-only -q`, or the nodeid lines of .detpy/trace.jsonl); for unittest, Django, nose2, "
                     f"ward, zope or doctest suites add --runner NAME.")
        return "\n".join(lines)
    if status == "not-found":
        lines.append(f"  not reproduced: it passed in the fixed order and under {b.get('configs_searched', '?')} "
                     f"configuration(s) searched (raise --seeds, or run `{PROG} explore`)")
        return "\n".join(lines)
    if status == "not-minimised":
        lines.append(f"  failure found under {b.get('config')} but the run budget ran out while minimising "
                     f"(raise --max-runs)")
        return "\n".join(lines)
    rp = b.get("replay") or {}
    bundle_dir = out / _slug(test)
    unc = _uncontrolled_of(bundle_dir, test)
    if status == "reproduced":
        fps = b.get("fingerprints") or rp.get("fingerprints") or []
        lines.append(f"  status:  REPRODUCED: failed {rp.get('fails')}/{rp.get('runs')} replays with one fingerprint"
                     f"{' ' + fps[0] if fps else ''}")
    else:
        lines.append(f"  status:  NOT REPRODUCIBLE under fenvix: failed {rp.get('fails')}/{rp.get('runs')} replays, "
                     f"identical fingerprint: {rp.get('identical_fingerprint')}"
                     + (f"; the test uses a source this release does not control: {', '.join(unc)}" if unc else ""))
    lines.append(f"  cause:   {cause_of(b)}")
    cfg = b.get("config")
    lines.append(f"  seed:    {'none (fixed order)' if cfg == 'fixed' else cfg}")
    lines.append(f"  order:   {' -> '.join(b.get('order') or [])}")
    exc = b.get("exception")
    if exc:
        if isinstance(exc, (list, tuple)) and len(exc) >= 3:
            exc = f"{exc[2]}" + (f" ({exc[3]})" if len(exc) > 3 and exc[3] else "")
        lines.append(f"  error:   {str(exc).splitlines()[0][:300]}")
    lines.append(f"  replay:  {PROG} replay {_q(bundle_dir)}")
    if b.get("command"):
        lines.append(f"  rerun:   {b['command']}")
    lines.append(f"  bundle:  {bundle_dir} ({b.get('runs')} runs, {b.get('seconds')} s)")
    return "\n".join(lines)


def _slug(test: str) -> str:
    from . import _core

    return _core.repro_slug(test)


def render_replay(res: dict, bundle: Path) -> str:
    ok = res.get("fails") == res.get("runs") and res.get("identical_fingerprint")
    head = "REPRODUCED" if ok else "NOT REPRODUCED"
    lines = [f"{PROG} replay: {res.get('test')}: {head}: failed {res.get('fails')}/{res.get('runs')} runs, "
             f"identical fingerprint: {res.get('identical_fingerprint')}, same fingerprint as the bundle: "
             f"{res.get('matches_bundle')}"]
    if not ok:
        lines.append("  the defect no longer fails the same way: fixed, or it depends on something the bundle "
                     "does not hold (code, dependencies, environment changed since it was written)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------
# commands
def _split_dashdash(argv: list) -> tuple[list, list]:
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def _search_options(sp) -> None:
    sp.add_argument("--runner", default=None, help=f"runner of the test ({', '.join(ADAPTERS)}); default: from the "
                    "test id and the project files")
    sp.add_argument("--out", default=".detpy/repro", help="directory of the bundles (default .detpy/repro)")
    sp.add_argument("--confirm", type=int, default=10,
                    help="replays that must all fail with one fingerprint for the defect to count as reproduced "
                         "(default 10)")
    sp.add_argument("--max-runs", type=int, default=400, help="runner runs allowed per test (default 400)")
    sp.add_argument("--timeout", type=float, default=1800, help="seconds per runner run (default 1800)")
    sp.add_argument("--python", default=sys.executable, help="interpreter that runs pytest")
    sp.add_argument("--json", action="store_true", help="also print the bundle as JSON")


def cmd_repro(argv: list) -> int:
    argv, extra = _split_dashdash(argv)
    p = argparse.ArgumentParser(
        prog=f"{PROG} repro", description="Turn a flaky test into a reproducible defect: search the fixed order and "
        "seeds 1..N for a failing run, minimise the tests before it (the polluters), write a bundle and replay it "
        "--confirm times. Prints the cause, the seed and order, and the replay command. Runner arguments go after "
        "`--`.", epilog=f"example: {PROG} repro 'tests/test_cache.py::test_hit' --seeds 100 -- -x tests/")
    p.add_argument("test", help="test id as the runner prints it (pytest: path::name)")
    p.add_argument("--seeds", type=int, default=50, help="seeds searched after the fixed order (default 50)")
    p.add_argument("--seed", default=None, help="skip the search: the configuration known to fail ('fixed' or N)")
    p.add_argument("--plan", default=None, metavar="PLAN",
                   help="the test failed under pytest-xdist (-n): search the list of the worker that ran it, from the "
                        "run's plan (.detpy/plan.json)")
    p.add_argument("--keep-work", action="store_true", help="keep the runs' work files (<out>/.work)")
    _search_options(p)
    ns = p.parse_args(argv)
    ns.runner_args = extra
    a = pick_adapter(ns.runner, test=ns.test)
    why = a.available()
    if why:
        print(f"{PROG}: {why}", file=sys.stderr)
        return 2
    try:
        b = a.repro(ns)
    except ValueError as e:  # an unusable --plan
        print(f"{PROG} repro: {e}", file=sys.stderr)
        return 2
    if not ns.keep_work:  # audit G-2021: the runs' work files (outcomes, traces, orders) are not left behind
        shutil.rmtree(Path(ns.out) / ".work", ignore_errors=True)
    print(render_repro(b, Path(ns.out)))
    if ns.json:
        print(json.dumps(b, indent=2))
    return 0 if b.get("status") == "reproduced" else 1


STATE_FILE = "explore-state.json"  # the seeds explored so far: --resume starts after them (audit G-1529)


def cmd_explore(argv: list) -> int:
    argv, extra = _split_dashdash(argv)
    p = argparse.ArgumentParser(
        prog=f"{PROG} explore", description="Nightly exploration: run the whole suite under seeds 1, 2, ... until the "
        "budget is spent, keep the tests that fail under one seed and pass under another, and turn each into a "
        "reproducible defect (as `fenvix repro`). Runner arguments go after `--`.")
    p.add_argument("--budget", type=float, required=True, help="time budget in minutes")
    p.add_argument("--max-seeds", type=int, default=1000, help="stop after this many seeds (default 1000)")
    p.add_argument("--targets", default=None, help="file of test ids: write bundles only for these")
    p.add_argument("--no-repro", action="store_true", help="explore only: no minimisation, no bundles")
    p.add_argument("--keep-work", action="store_true", help="keep the runs' work files (<out>/.work)")
    p.add_argument("--resume", action="store_true",
                   help="continue after the last seed of the previous exploration in --out (explore.json): every "
                        "night explores new seeds")
    p.add_argument("--first-seed", type=int, default=1, help="first seed to explore (default 1, or --resume)")
    p.add_argument("--changed-since", default=None, metavar="REF",
                   help="explore only the test files changed since the git revision REF")
    p.add_argument("--only-unstable", action="store_true",
                   help="explore only the test files of the tests found flaky by the previous exploration in --out")
    _search_options(p)
    ns = p.parse_args(argv)
    ns.runner_args = extra
    previous, state = {}, {}
    for name, into in (("explore.json", previous), (STATE_FILE, state)):
        f = Path(ns.out) / name
        if f.exists():
            try:
                into.update(json.loads(f.read_text()))
            except ValueError:
                pass
    if ns.resume and state.get("last_seed"):
        ns.first_seed = int(state["last_seed"]) + 1
    selected = []
    if ns.changed_since:
        r = subprocess.run(["git", "diff", "--name-only", ns.changed_since, "--"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"{PROG} explore: git diff {ns.changed_since} failed: {r.stderr.strip()}", file=sys.stderr)
            return 2
        selected += [f for f in r.stdout.split() if os.path.basename(f).startswith("test") and f.endswith(".py")
                     or f.endswith("_test.py")]
    if ns.only_unstable:
        selected += sorted({n.split("::", 1)[0] for n in previous.get("flaky_failing", [])})
    if ns.changed_since or ns.only_unstable:
        selected = [f for f in dict.fromkeys(selected) if os.path.exists(f)]
        if not selected:
            print(f"{PROG} explore: nothing selected (no changed or previously unstable test file)")
            return 0
        ns.runner_args = [*ns.runner_args, *selected]
        print(f"{PROG} explore: {len(selected)} test file(s) selected: {', '.join(selected[:10])}", file=sys.stderr)
    a = pick_adapter(ns.runner)
    why = a.available()
    if why:
        print(f"{PROG}: {why}", file=sys.stderr)
        return 2
    s = a.explore(ns)
    ran = [x.get("seed") for x in s.get("seeds_log", []) if isinstance(x, dict) and x.get("seed") is not None]
    st = {"first_seed": ns.first_seed, "last_seed": max(ran) if ran else ns.first_seed - 1,
          "previous_last_seed": state.get("last_seed")}
    (Path(ns.out) / STATE_FILE).write_text(json.dumps(st, indent=1))
    if not getattr(ns, "keep_work", False):
        shutil.rmtree(Path(ns.out) / ".work", ignore_errors=True)
    from . import _core

    print(_core.repro_render_explore(s).replace("detpy explore", f"{PROG} explore", 1))
    for bdl in s.get("bundles", []) if isinstance(s.get("bundles"), list) else []:
        if isinstance(bdl, dict) and bdl.get("status") == "reproduced":
            print(f"  defect: {bdl.get('test')}: {cause_of(bdl)}; replay: {PROG} replay "
                  f"{_q(Path(ns.out) / 'bundles' / _slug(bdl.get('test', '')))}")
    if ns.json:
        print(json.dumps(s, indent=2))
    return 0


def cmd_replay(argv: list) -> int:
    p = argparse.ArgumentParser(prog=f"{PROG} replay", description="Replay a defect bundle written by `fenvix repro` "
                                "or `fenvix explore`, and check that it fails every time with one fingerprint, the "
                                "bundle's. Exit 0 when it does.")
    p.add_argument("bundle", help="bundle directory (it holds bundle.json and order.txt)")
    p.add_argument("--runs", type=int, default=10, help="replays (default 10)")
    p.add_argument("--runner", default=None, help="override the bundle's runner")
    p.add_argument("--python", default=sys.executable, help="interpreter that runs pytest")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    ns = p.parse_args(argv)
    bundle = Path(ns.bundle)
    if not (bundle / "bundle.json").is_file():
        print(f"{PROG} replay: not a replay bundle: {bundle} (no bundle.json; bundles are written under "
              f".detpy/repro/ by `{PROG} repro`)", file=sys.stderr)
        return 2
    a = pick_adapter(ns.runner, bundle=bundle)
    why = a.available()
    if why:
        print(f"{PROG}: {why}", file=sys.stderr)
        return 2
    res = a.replay(bundle, ns.runs, ns.python)
    print(json.dumps(res, indent=2) if ns.json else render_replay(res, bundle))
    return 0 if res["fails"] == res["runs"] and res["identical_fingerprint"] else 1


def cmd_verify(argv: list) -> int:
    from . import _core

    p = argparse.ArgumentParser(
        prog=f"{PROG} verify", description="Compare two or more runs of the same suite (their traces). A test is "
        "IDENTICAL only when every run had the same inputs (time zone, locale, environment, seed, hash seed, clock, "
        "network, ...), ran it after the same tests, it used no source this release does not control (threads, "
        "child processes, I/O readiness) and it observed the same events with the same outcome. Otherwise the "
        "first divergent event is named. Exit 0 when every test is identical.")
    p.add_argument("traces", nargs="+", help="trace files (.detpy/trace.jsonl, --det-trace=PATH)")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.add_argument("--show-stable", action="store_true", help="also list the identical tests")
    p.add_argument("--ignore-env", action="append", default=[], metavar="NAME",
                   help="environment variable whose difference between the runs you declare irrelevant (NAME or "
                        "PREFIX*; repeatable). The report lists what was ignored.")
    ns = p.parse_args(argv)
    if len(ns.traces) < 2:
        p.error("verify needs at least two traces")
    missing = [t for t in ns.traces if not os.path.isfile(t)]
    if missing:
        print(f"{PROG} verify: trace not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        report_json, text = _core.verify_with(ns.traces, ns.ignore_env, ns.show_stable)
    except Exception as e:  # unreadable or incompatible traces: one line, no traceback
        print(f"{PROG} verify: {e}", file=sys.stderr)
        return 2
    report = json.loads(report_json)
    print(report_json if ns.json else text.replace("detpy verify", f"{PROG} verify", 1), end="" if not ns.json else "\n")
    s = report["summary"]
    return 0 if s["tests"] > 0 and s["diverged"] == 0 and s["missing"] == 0 else 1


def foreign_detpy_owners() -> list:
    """Installed distributions other than ``fenvix`` that also write the import package ``detpy/``.

    The PyPI project ``detpy`` (an unrelated toolbox) installs a top-level ``detpy/`` too; installing it after
    fenvix replaces the engine's files (audit G-0170, G-0737). pip cannot declare the conflict, so it is checked
    here and by ``fenvix doctor``."""
    from importlib import metadata

    out = []
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").lower()
        if name == "fenvix":
            continue
        top = (dist.read_text("top_level.txt") or "").split()
        files = dist.files or ()
        if "detpy" in top or any(str(f).startswith("detpy/") for f in files):
            out.append(f"{dist.metadata.get('Name')} {dist.version}")
    return sorted(set(out))


def install_checks() -> list:
    """(name, ok, detail, what it affects) of the installation itself: the interpreter is supported, the native
    core loads, no other distribution writes ``detpy/``. ``release/engine/install.sh`` refuses on any failure."""
    out = []
    prob = _support.PROBLEM
    out.append(("interpreter", prob is None, prob or f"CPython {sys.version.split()[0]} ({sys.executable})",
                "everything: fenvix supports CPython 3.12-3.14 on Linux x86_64 (glibc 2.28+)"))
    if prob is None:
        try:
            from . import _core

            out.append(("native core", True, os.path.basename(_core.__file__), "everything"))
        except Exception as e:  # reported, not hidden
            out.append(("native core", False, f"{type(e).__name__}: {e}", "everything"))
    foreign = foreign_detpy_owners()
    out.append(("import package detpy", not foreign,
                "owned by fenvix only" if not foreign else
                "also written by " + ", ".join(foreign) + " (an unrelated project with the same import name: "
                "uninstall it and reinstall fenvix)", "everything: its files replace the engine's"))
    return out


def doctor_checks() -> list:
    """(name, ok, detail, what it affects) for every control this machine must give (audit G-0700), after the
    checks of the installation itself."""
    import platform

    first = install_checks()
    if not all(ok for _, ok, _, _ in first):
        return first  # the controls cannot be asked of an interpreter or a core that does not work

    from . import _level0, reexec

    out = list(first)

    def run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    v = sys.version_info
    out.append(("python", platform.python_implementation() == "CPython" and v >= (3, 12),
                f"{platform.python_implementation()} {platform.python_version()}",
                "go-live scope is CPython 3.12-3.14; the cache with proof needs 3.12+"))
    ok, why = reexec.can_reexec()
    out.append(("hash seed re-exec", ok, why or "the interpreter can re-execute itself under a fixed PYTHONHASHSEED",
                "hash seed and bytecode controls"))
    setarch = shutil.which("setarch")
    aslr = bool(setarch) and run([setarch, platform.machine(), "-R", "true"])
    out.append(("ASLR switch", aslr or sys.platform == "darwin",
                "setarch -R allowed" if aslr else ("macOS: not needed" if sys.platform == "darwin"
                                                   else "personality(ADDR_NO_RANDOMIZE) refused or setarch missing"),
                "address-dependent order (sets of objects, id())"))
    loc = next((c for c in _level0.LOCALE_FALLBACKS if _level0._locale_exists(c)), None)
    out.append(("locale", loc is not None, loc or "none of " + ", ".join(_level0.LOCALE_FALLBACKS),
                "the locale control (--det-locale)"))
    tz = os.path.exists("/usr/share/zoneinfo/UTC") or os.path.exists("/usr/share/zoneinfo/Etc/UTC")
    out.append(("time zone database", tz or sys.platform == "darwin", "/usr/share/zoneinfo",
                "time zones other than UTC under --det-tz"))
    strace = shutil.which("strace")
    st_ok = bool(strace) and run([strace, "-f", "-qq", "-o", os.devnull, "true"])
    out.append(("strace", st_ok, strace or "not installed",
                "the cache with proof follows child processes (otherwise a test that starts one is never reused)"))
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    out.append(("C compiler", bool(cc), cc or "none",
                "the clock shim of followed child processes (the cache with proof)"))
    libc = " ".join(platform.libc_ver()) or "unknown"
    out.append(("C library", sys.platform == "darwin" or platform.libc_ver()[0] == "glibc", libc,
                "the engine is built for glibc (Linux) and macOS"))
    js = _detjs()
    out.append(("detjs (JavaScript runners)", bool(js), " ".join(js) if js else "not installed",
                "fenvix vitest|jest|... (optional)"))
    return out


def cmd_doctor(argv: list) -> int:
    p = argparse.ArgumentParser(prog=f"{PROG} doctor", description="Check what this machine can give: every control "
                                "of a deterministic run and of the cache with proof. Exit 1 when a required check "
                                "fails.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--install", action="store_true", help="only the checks of the installation itself (interpreter, "
                   "native core, no foreign detpy): what release/engine/install.sh requires")
    ns = p.parse_args(argv)
    checks = install_checks() if ns.install else doctor_checks()
    optional = {"detjs (JavaScript runners)", "strace", "C compiler", "time zone database"}
    if "--json" in argv:
        print(json.dumps([{"check": n, "ok": ok, "detail": d, "affects": a} for n, ok, d, a in checks], indent=2))
    else:
        for n, ok, d, a in checks:
            print(f"{'OK     ' if ok else ('MISSING' if n in optional else 'FAILED ')} {n}: {d}"
                  + ("" if ok else f"  (affects: {a})"))
    return 0 if all(ok for n, ok, _, _ in checks if n not in optional) else 1


def cmd_cassette(argv: list) -> int:
    """``fenvix cassette list|rename|drop``: the recordings of the closed network, per test (audit G-2200)."""
    from . import _core

    p = argparse.ArgumentParser(prog=f"{PROG} cassette", description="Inspect and maintain the network cassette "
                                "(recordings of external connections, per test; docs/NETWORK.md).")
    p.add_argument("--cassette", default=".detpy/cassette.json", help="cassette file (default .detpy/cassette.json)")
    sub = p.add_subparsers(dest="op", required=True)
    sub.add_parser("list", help="every test with recordings: connections, hosts, recording date")
    r = sub.add_parser("rename", help="move a test's recordings to its new id (a renamed or moved test)")
    r.add_argument("old")
    r.add_argument("new")
    d = sub.add_parser("drop", help="remove the recordings of tests (they are blocked until recorded again)")
    d.add_argument("tests", nargs="+")
    ns = p.parse_args(argv)
    if not os.path.isfile(ns.cassette):
        print(f"{PROG} cassette: no cassette at {ns.cassette} (record one with `{PROG} pytest --det-record`)",
              file=sys.stderr)
        return 2
    c = _core.Cassette.load(ns.cassette)
    if ns.op == "list":
        for t in c.tests():
            hosts, i = [], 0
            while True:
                try:
                    h, port, tls, nseg = c.info(t, i)
                except KeyError:
                    break
                hosts.append(f"{'https' if tls else 'tcp'}://{h}:{port}")
                i += 1
            print(f"{t}\t{i} connection(s)\trecorded {c.recorded(t) or 'unknown'}\t{', '.join(sorted(set(hosts)))}")
        return 0
    if ns.op == "rename":
        if not c.rename_test(ns.old, ns.new):
            print(f"{PROG} cassette: no recordings for {ns.old}", file=sys.stderr)
            return 1
        c.save(ns.cassette)
        print(f"renamed {ns.old} -> {ns.new}")
        return 0
    missing = [t for t in ns.tests if t not in set(c.tests())]
    for t in ns.tests:
        c.clear_test(t)
    c.save(ns.cassette)
    print(f"dropped {len(ns.tests) - len(missing)} test(s)" + (f"; no recordings for {', '.join(missing)}" if missing
                                                                 else ""))
    return 0


# ---------------------------------------------------------------------------------------------------------------
# runner entries
def _with_det(args: list) -> list:
    if any(a == "--det" or a.startswith("--det=") for a in args) or "--no-det" in args:
        return [a for a in args if a != "--no-det"]
    return ["--det", *args]


def _exec(argv: list) -> int:
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        print(f"{PROG}: {argv[0]} not found (FENVIX_HOME={HOME})", file=sys.stderr)
        return 127
    return 0  # pragma: no cover


def _detjs() -> list | None:
    cand = os.path.join(HOME, "node", "bin", "detjs.js")
    if os.path.exists(cand):
        return ["node", cand]
    w = shutil.which("detjs")
    return [w] if w else None


def detect(d: str) -> list:
    """Languages and runners of a project directory (and of its first-level subdirectories: monorepos)."""
    out = []
    root = Path(d)
    if not root.is_dir():
        raise SystemExit(f"{PROG} detect: not a directory: {d}")
    dirs = [root] + sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "node_modules")))
    for p in dirs:
        names = {x.name for x in p.iterdir()} if p.is_dir() else set()
        rel = "." if p == root else p.name
        if names & {"pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini", "requirements.txt",
                    "Pipfile", "conftest.py", "manage.py", "noxfile.py"}:
            runner = "django" if "manage.py" in names else "pytest"
            out.append(f"{rel}\tpython\t{runner}")
        if names & {"package.json", "deno.json", "bun.lockb"}:
            js = "deno" if "deno.json" in names else "bun" if "bun.lockb" in names else None
            pkg = p / "package.json"
            if js is None and pkg.exists():
                try:
                    data = json.loads(pkg.read_text())
                except ValueError:
                    data = {}
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                for name, r in (("vitest", "vitest"), ("jest", "jest"), ("@playwright/test", "playwright"),
                                ("mocha", "mocha"), ("ava", "ava"), ("tap", "tap"), ("uvu", "uvu"),
                                ("jasmine", "jasmine")):
                    if name in deps:
                        js = r
                        break
            out.append(f"{rel}\tnode\t{js or 'node-test'}")
        if "go.mod" in names:
            out.append(f"{rel}\tgo\tgo-test")
        if names & {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
            out.append(f"{rel}\tjvm\t{'maven' if 'pom.xml' in names else 'gradle'}")
    return out


def version_lines() -> list:
    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return (r.stdout.strip().splitlines() or ["unavailable"])[0]
        except Exception as e:
            return f"unavailable ({type(e).__name__})"

    if _support.PROBLEM is not None:
        return [f"fenvix {__version__} (unsupported here: {_support.PROBLEM})"]
    from . import _core

    lines = [f"fenvix {__version__} (engine: detpy {__version__}, trace encoding {_core.ENCODING_VERSION}; "
             f"Python {sys.version.split()[0]})"]
    js = _detjs()
    if js:
        pkg = os.path.join(HOME, "node", "package.json")
        lines.append("detjs " + (run(["node", "-p", f"require({pkg!r}).version"]) if os.path.exists(pkg) else "present"))
    for b in ("fenvix-go", "fenvix-skip"):
        path = os.path.join(HOME, "bin", b)
        lines.append(f"{b} {'present' if os.path.exists(path) else 'absent'}")
    jar = os.path.join(HOME, "jvm", "fenvix-agent.jar")
    lines.append(f"fenvix-agent.jar {'present' if os.path.exists(jar) else 'absent'}")
    return lines


def _image_tool(name: str) -> str:
    p = os.path.join(HOME, "bin", name)
    return p if os.path.exists(p) else (shutil.which(name) or p)


# commands that run the engine: refused with one sentence (exit 4) on an interpreter outside the supported set,
# before anything imports the native core (G-0547, G-0549)
_ENGINE_COMMANDS = {"repro", "explore", "replay", "verify", "cassette", "pytest", "python", "python-runner", "zope",
                    *PY_RUNNERS}


USAGE = __doc__


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in _ENGINE_COMMANDS and _support.PROBLEM is not None:
        _support.refuse()
    if cmd in ("--version", "-V", "version"):
        print("\n".join(version_lines()))
        return 0
    if cmd == "repro":
        return cmd_repro(rest)
    if cmd == "explore":
        return cmd_explore(rest)
    if cmd == "replay":
        return cmd_replay(rest)
    if cmd == "verify":
        return cmd_verify(rest)
    if cmd == "cassette":
        return cmd_cassette(rest)
    if cmd == "doctor":
        return cmd_doctor(rest)
    if cmd in ("pytest", "python"):  # `python`: the release-1 name of the same entry
        return _exec([sys.executable, "-m", "pytest", *_with_det(rest)])
    if cmd in PY_RUNNERS or cmd == "zope":
        name = "zope-testrunner" if cmd == "zope" else cmd
        return _exec([sys.executable, "-m", "detpy", name, *_with_det(rest)])
    if cmd == "python-runner":  # release-1 name: fenvix python-runner RUNNER [args]
        if not rest:
            print(f"{PROG} python-runner: name a runner ({', '.join(PY_RUNNERS)})", file=sys.stderr)
            return 2
        return main([rest[0], *rest[1:]])
    if cmd in JS_RUNNERS or cmd == "node":
        js = _detjs()
        if js is None:
            print(f"{PROG}: detjs (the JavaScript shell) is not installed (FENVIX_HOME={HOME}, PATH)", file=sys.stderr)
            return 127
        args = rest if cmd == "node" else [cmd, *_with_det(rest)]
        return _exec([*js, *args])
    if cmd == "detect":
        for line in detect(rest[0] if rest else "."):
            print(line)
        return 0
    if cmd == "go":
        return _exec([_image_tool("fenvix-go"), *rest])
    if cmd == "jvm":
        if rest and rest[0] == "decide":
            return _exec([_image_tool("fenvix-skip"), *rest])
        return _exec(["java", "-jar", os.path.join(HOME, "jvm", "fenvix-agent.jar"), *rest])
    print(f"{PROG}: unknown command {cmd!r} (`{PROG} --help` lists them)", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
