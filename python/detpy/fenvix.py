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
    fenvix detect [DIR]                     languages and runners of DIR (one per line)
    fenvix version | --version | -V         versions of the installed components

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

from . import __version__

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

        runner = _repro.Runner(cwd=Path.cwd(), workdir=Path(ns.out) / ".work", python=ns.python,
                               pytest_args=ns.runner_args, timeout=ns.timeout)
        b = _repro.reproduce(runner, ns.test, seeds=ns.seeds, confirm=ns.confirm, max_runs=ns.max_runs,
                             out_dir=Path(ns.out), known_fail=ns.seed)
        b["runner"] = self.name
        if b.get("status") in ("reproduced", "replay-unstable"):
            _write_runner(Path(ns.out) / _repro._slug(ns.test), self.name)
        return b

    def explore(self, ns) -> dict:
        from . import repro as _repro

        runner = _repro.Runner(cwd=Path.cwd(), workdir=Path(ns.out) / ".work", python=ns.python,
                               pytest_args=ns.runner_args, timeout=ns.timeout)
        targets = None
        if ns.targets:
            targets = {line.strip() for line in open(ns.targets) if line.strip()}
        s = _repro.explore(runner, budget_s=ns.budget * 60, max_seeds=ns.max_seeds, out_dir=Path(ns.out),
                           confirm=ns.confirm, targets=targets, repro=not ns.no_repro, max_runs=ns.max_runs)
        s["runner"] = self.name
        return s

    def replay(self, bundle: Path, runs: int, python: str) -> dict:
        from . import repro as _repro

        return _repro.replay(bundle, runs, python)


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
    "vitest": PlannedAdapter("vitest", (".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.mts", ".test.tsx"),
                             ("vitest.config.ts", "vitest.config.js", "vitest.config.mts", "vitest.config.mjs")),
    "jest": PlannedAdapter("jest", (".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.tsx", ".test.jsx"),
                           ("jest.config.js", "jest.config.ts", "jest.config.cjs", "jest.config.mjs")),
    "playwright": PlannedAdapter("playwright", (".spec.ts", ".e2e.ts"),
                                 ("playwright.config.ts", "playwright.config.js")),
}


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
        lines.append(f"  not collected: no test has this id. Use an id as the runner prints it, e.g. "
                     f"`{PROG} pytest --collect-only -q`.")
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
    _search_options(p)
    ns = p.parse_args(argv)
    ns.runner_args = extra
    a = pick_adapter(ns.runner, test=ns.test)
    why = a.available()
    if why:
        print(f"{PROG}: {why}", file=sys.stderr)
        return 2
    b = a.repro(ns)
    print(render_repro(b, Path(ns.out)))
    if ns.json:
        print(json.dumps(b, indent=2))
    return 0 if b.get("status") == "reproduced" else 1


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
    _search_options(p)
    ns = p.parse_args(argv)
    ns.runner_args = extra
    a = pick_adapter(ns.runner)
    why = a.available()
    if why:
        print(f"{PROG}: {why}", file=sys.stderr)
        return 2
    s = a.explore(ns)
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
    return lines


USAGE = __doc__


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    cmd, rest = argv[0], argv[1:]
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
    print(f"{PROG}: unknown command {cmd!r} (`{PROG} --help` lists them)", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
