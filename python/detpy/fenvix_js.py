"""``fenvix repro | explore | replay`` for the JavaScript runners: Vitest and Jest through detjs (Playwright: see
``PlaywrightAdapter.available``).

The search, the minimisation, the replays, the verdicts and the bundle are the runner-neutral ones of
``detpy.repro`` (Rust ``crates/detpy-core/src/repro.rs``); this module only runs detjs:

    detjs vitest run --det [--det-seed=N] [--det-order=FILE] --det-outcomes=PATH --det-trace=PATH [runner args]
    detjs jest       --det [--det-seed=N] [--det-order=FILE] --det-outcomes=PATH --det-trace=PATH [runner args]
    detjs <runner> --det --det-collect --det-outcomes=PATH [--det-seed=N]      (the order of a configuration)

A Vitest or Jest run executes one test file at a time; an order is honoured as files in the order of their first
listed test, then the tests of each file in the listed order (docs/NODE.md, "Repro"). Every order the search and the
minimisation produce is of that shape, so a bundle replays exactly the order it lists.

detjs is found through ``FENVIX_DETJS`` (a command, e.g. ``node /opt/fenvix/node/bin/detjs.js``), then
``$FENVIX_HOME/node/bin/detjs.js`` (default ``/opt/fenvix``), then the repository this package was installed from
(``<repo>/node/bin/detjs.js``), then ``detjs`` on the PATH.

Use:

* with the ``fenvix`` command (branch verifier-cli, ``python/detpy/fenvix.py``): ``fenvix_js.register(ADAPTERS)``
  replaces the planned vitest / jest / playwright adapters by these;
* standalone, with the same options and output (docs/CLI.md):
  ``python -m detpy.fenvix_js repro TEST [--runner vitest|jest] [options] [-- runner args]``,
  ``python -m detpy.fenvix_js explore --budget MIN [options] [-- runner args]``,
  ``python -m detpy.fenvix_js replay BUNDLE [--runs N]``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import _core
from . import repro as _repro

# The adapters implement fenvix.py's ``Adapter`` interface by duck typing: fenvix.py imports this module while it is
# being initialised (``register``), so this module never imports it at import time.
_AdapterBase = object
PROG = "fenvix" if importlib.util.find_spec("detpy.fenvix") is not None else "python -m detpy.fenvix_js"

SUBCOMMAND = {"vitest": ["run"], "playwright": ["test"]}  # detjs <runner> <subcommand> --det ...
JS_EXT = (".js", ".ts", ".mjs", ".cjs", ".mts", ".cts", ".jsx", ".tsx")


# ---------------------------------------------------------------------------------------------------------------
# detjs
def detjs_command() -> list | None:
    """The command that starts detjs, or None."""
    env = os.environ.get("FENVIX_DETJS")
    if env:
        return shlex.split(env)
    home = os.environ.get("FENVIX_HOME", "/opt/fenvix")
    for cand in (Path(home) / "node" / "bin" / "detjs.js", Path(__file__).resolve().parents[2] / "node" / "bin" / "detjs.js"):
        if cand.is_file():
            return ["node", str(cand)]
    w = shutil.which("detjs")
    return [w] if w else None


def _detjs_problem(cmd: list | None) -> str | None:
    """Why detjs cannot drive a repro here (None when it can)."""
    if cmd is None:
        return ("detjs (the JavaScript shell) is not installed: set FENVIX_DETJS to its command, or FENVIX_HOME to the "
                "directory holding node/bin/detjs.js, or put detjs on the PATH")
    if cmd[0] == "node" and shutil.which("node") is None:
        return "node is not on the PATH (detjs runs on Node.js >= 18)"
    try:
        p = subprocess.run([*cmd, "--det-help"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"detjs could not start ({' '.join(cmd)}): {e}"
    if p.returncode != 0:
        return f"detjs could not start ({' '.join(cmd)}): {(p.stderr or p.stdout).strip()[-300:]}"
    if "--det-order" not in p.stdout or "--det-collect" not in p.stdout:
        return (f"this detjs ({' '.join(cmd)}) has no --det-order / --det-outcomes / --det-collect: it predates the "
                f"repro driver; install a newer detjs")
    return None


@dataclass
class DetjsRunner(_repro.Runner):
    """``repro.Runner`` for detjs: the same outcome / order / trace files, a detjs command line.

    ``pytest_args`` holds the runner arguments (the name ``repro.Runner`` gives them)."""

    runner: str = "vitest"
    detjs: list | None = None

    def __post_init__(self):
        if self.detjs is None:
            self.detjs = detjs_command() or ["detjs"]

    @property
    def runner_args(self) -> list:
        return self.pytest_args

    def _cmd(self, config: str, extra: list) -> list:
        extra = ["--det-collect" if a == "--collect-only" else a for a in extra]
        cmd = [*self.detjs, self.runner, *SUBCOMMAND.get(self.runner, []), "--det", *extra]
        if config != _repro.FIXED:
            cmd.append(f"--det-seed={int(config)}")
        return [*cmd, *self.pytest_args]

    def _exec(self, cmd: list) -> tuple[int, bool, str]:
        """Run detjs in its own process group, killed afterwards: the runners start worker processes (Vitest forks,
        servers a suite leaves behind) that must not outlive a run or a timeout. (exit code, timed out, output)."""
        proc = subprocess.Popen(cmd, cwd=self.cwd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        timed_out = False
        try:
            out, _ = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _killpg(proc.pid)
            try:
                out, _ = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                out = b""
        _killpg(proc.pid)
        return (-9 if timed_out else proc.returncode), timed_out, (out or b"").decode(errors="replace")

    def run(self, config: str, order: list | None, tag: str) -> _repro.Run:
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
        code, timed_out, text = self._exec(self._cmd(config, extra))
        dur = time.monotonic() - t0
        self.runs += 1
        self.seconds += dur
        data = {}
        if out.exists():
            try:
                data = json.loads(out.read_text())
            except ValueError:
                data = {}
        else:
            (self.workdir / f"{tag}.log").write_text(text[-20000:])
        r = _repro.Run(config, data.get("order", order or []), data.get("outcomes", {}), data.get("fingerprints", {}),
                       data.get("exceptions", {}), dur, code, str(trace), timed_out,
                       {k: data.get(k) for k in ("controls", "seed", "order_missing", "order_regrouped")})
        self.log.append({"tag": tag, "config": config, "tests": len(r.order), "seconds": round(dur, 3), "exit": code,
                         **({"timed_out": True} if timed_out else {})})
        return r

    def collect(self, config: str = _repro.FIXED) -> list:
        out = self.workdir / f"collect-{config}.json"
        self.workdir.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        t0 = time.monotonic()
        code, timed_out, text = self._exec(self._cmd(config, ["--det-collect", f"--det-outcomes={out}",
                                                              f"--det-trace={self.workdir / 'collect.jsonl'}"]))
        self.seconds += time.monotonic() - t0
        if not out.exists():
            raise RuntimeError(f"collection failed (exit {code}{', timed out' if timed_out else ''}):\n" + text[-2000:])
        order = json.loads(out.read_text())["order"]
        self.orders.setdefault(config, order)
        return order


def _killpg(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


def runner_command(runner: str, config: str, order_file: str, args: list) -> str:
    words = ["detjs", runner, *SUBCOMMAND.get(runner, []), "--det"]
    if config != _repro.FIXED:
        words.append(f"--det-seed={config}")
    words.append(f"--det-order={order_file}")
    return " ".join(shlex.quote(w) for w in [*words, *args])


def uncontrolled_of(trace: Path, test: str) -> list:
    """Sources the test used that Level 0 does not control in this run: ``child`` / ``thread`` (``uncontrolled.*``
    events), ``entropy`` (crypto.randomBytes & co. observed, not controlled without --det-urandom)."""
    out: list = []
    try:
        text = Path(trace).read_text()
    except OSError:
        return out
    header = {}
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "header":
            header = r.get("meta") or {}
        if r.get("type") != "test" or r.get("nodeid") != test:
            continue
        kinds = lambda: {x.split(" ")[0] for x in out}  # noqa: E731
        for e in r.get("events") or []:  # the events carry what was used (the program, the worker)
            op = str(e.get("o", ""))
            if op.startswith("uncontrolled.") and op.split(".", 1)[1] not in kinds():
                out.append(f"{op.split('.', 1)[1]} ({str(e.get('v'))[:80]})")
            elif e.get("s") == "entropy" and not header.get("urandom_controlled") and "entropy" not in kinds():
                out.append(f"entropy ({op}; controlled only with --det-urandom)")
        for k in r.get("uncontrolled") or []:  # verifier-cli's recorder: kinds kept even when events are truncated
            if k not in kinds():
                out.append(k)
        if r.get("truncated") and not out:
            out.append("unknown (events truncated)")
        break
    return out


def finish_bundle(b: dict, out_dir: Path, runner: DetjsRunner) -> dict:
    """The bundle of a detjs repro: runner, runner arguments, the detjs and replay commands, Node and detjs versions,
    the uncontrolled sources of the failing run (bundle.json rewritten in place)."""
    b["runner"] = runner.runner
    if b.get("status") not in ("reproduced", "replay-unstable"):
        return b
    bdir = Path(out_dir) / _repro._slug(b["test"])
    b.pop("pytest_args", None)
    b.pop("python", None)
    b["runner_args"] = list(runner.pytest_args)
    b["bundle"] = str(bdir)
    b["command"] = runner_command(runner.runner, b["config"], str(bdir / "order.txt"), runner.pytest_args)
    b["replay_command"] = f"{PROG} replay {shlex.quote(str(bdir))}"
    b["root"] = str(runner.cwd)
    try:
        b["node"] = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    except OSError:
        b["node"] = None
    b["uncontrolled"] = uncontrolled_of(bdir / "fail.trace.jsonl", b["test"])
    if b["status"] == "replay-unstable" and b["uncontrolled"]:
        # the minimisation ran on outcomes an uncontrolled source decides: its polluters / setters are not a cause
        b["minimised"] = {k: b.get(k) for k in ("kind", "polluters", "setters", "divergence")}
        b["kind"], b["polluters"], b["setters"] = "uncontrolled", [], []
        b["divergence"] = {
            "reason": "uncontrolled",
            "description": (f"the test used {', '.join(b['uncontrolled'])}, which Level 0 does not control: its outcome "
                            f"varies between replays of one order and seed"),
            "fingerprints": (b.get("replay") or {}).get("fingerprints", []),
        }
    if (bdir / "bundle.json").exists():
        (bdir / "bundle.json").write_text(json.dumps(b, indent=2))
    return b


# ---------------------------------------------------------------------------------------------------------------
# adapters (interface: docs/CLI.md "Runner adapters", fenvix.py ``Adapter``)
class DetjsAdapter(_AdapterBase):
    """Vitest or Jest through detjs."""

    name = "?"
    shapes: tuple = ()
    markers: tuple = ()
    package = "?"
    packages: tuple = ()

    def available(self) -> str | None:
        why = _detjs_problem(detjs_command())
        if why:
            return f"repro / explore / replay for {self.name} need detjs: {why}"
        cwd = Path.cwd()
        found = False
        for pkg in self.packages or (self.package,):
            try:
                p = subprocess.run(["node", "-e", f"require('module').createRequire(process.cwd() + '/x.js')"
                                    f".resolve('{pkg}/package.json')"], cwd=cwd, capture_output=True, timeout=120)
                found = found or p.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not found:
            return (f"{self.name} is not installed in {cwd}: detjs runs the project's own {self.name} (install the "
                    f"project's dependencies, and run fenvix from the directory the tests run from)")
        return None

    def owns(self, test: str) -> bool:
        f = test.split("::", 1)[0]
        return any(s in f for s in self.shapes) and f.endswith(JS_EXT)

    def detect(self, d: Path) -> bool:
        d = Path(d)
        if any((d / m).exists() for m in self.markers):
            return True
        try:
            pkg = json.loads((d / "package.json").read_text())
        except (OSError, ValueError):
            return False
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        return self.package in deps

    def _runner(self, ns, workdir: Path) -> DetjsRunner:
        return DetjsRunner(cwd=Path.cwd(), workdir=workdir, pytest_args=list(getattr(ns, "runner_args", []) or []),
                           timeout=getattr(ns, "timeout", 1800), runner=self.name)

    def repro(self, ns) -> dict:
        runner = self._runner(ns, Path(ns.out) / ".work")
        try:
            b = _repro.reproduce(runner, ns.test, seeds=ns.seeds, confirm=ns.confirm, max_runs=ns.max_runs,
                                 out_dir=Path(ns.out), known_fail=ns.seed)
        except RuntimeError as e:  # the suite could not be collected: say so, no traceback
            raise SystemExit(f"fenvix repro: {self.name}: {e}") from None
        return finish_bundle(b, Path(ns.out), runner)

    def explore(self, ns) -> dict:
        runner = self._runner(ns, Path(ns.out) / ".work")
        targets = None
        if getattr(ns, "targets", None):
            targets = {line.strip() for line in open(ns.targets) if line.strip()}
        s = _repro.explore(runner, budget_s=ns.budget * 60, max_seeds=ns.max_seeds, out_dir=Path(ns.out),
                           confirm=ns.confirm, targets=targets, repro=not ns.no_repro, max_runs=ns.max_runs)
        s["runner"] = self.name
        for b in s.get("bundles", []) if isinstance(s.get("bundles"), list) else []:
            if isinstance(b, dict) and b.get("test"):
                finish_bundle(b, Path(ns.out) / "bundles", runner)
        (Path(ns.out) / "explore.json").write_text(json.dumps(s, indent=1))
        return s

    def replay(self, bundle: Path, runs: int, python: str = sys.executable) -> dict:
        bundle = Path(bundle)
        data = json.loads((bundle / "bundle.json").read_text())
        runner = DetjsRunner(cwd=Path.cwd(), workdir=bundle / "replay", runner=data.get("runner", self.name),
                             pytest_args=list(data.get("runner_args", [])))
        rs = [runner.run(data["config"], data["order"], f"replay-{i}") for i in range(runs)]
        return _core.repro_replay_verdict(data, rs, runs)


class VitestAdapter(DetjsAdapter):
    name = "vitest"
    package = "vitest"
    shapes = (".test.", ".spec.")
    markers = ("vitest.config.ts", "vitest.config.js", "vitest.config.mts", "vitest.config.mjs", "vitest.config.cts",
               "vitest.config.cjs", "vitest.workspace.ts", "vitest.workspace.js")


class JestAdapter(DetjsAdapter):
    name = "jest"
    package = "jest"
    shapes = (".test.", ".spec.", "__tests__/")
    markers = ("jest.config.js", "jest.config.ts", "jest.config.cjs", "jest.config.mjs", "jest.config.json")


class PlaywrightAdapter(DetjsAdapter):
    """Playwright Test through `detjs playwright test --det` (node/src/playwright/): the test process is controlled
    and traced per test; the browser and the web servers are separate processes (not controlled, the L2 lane)."""

    name = "playwright"
    package = "@playwright/test"
    packages = ("@playwright/test", "playwright")
    shapes = (".spec.", ".e2e.", ".test.")
    markers = ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs", "playwright.config.cjs",
               "playwright.config.mts", "playwright.config.cts")

    def detect(self, d: Path) -> bool:
        return any((Path(d) / m).exists() for m in self.markers)


ADAPTERS = {"vitest": VitestAdapter(), "jest": JestAdapter(), "playwright": PlaywrightAdapter()}


def register(adapters: dict) -> dict:
    """Replace the planned vitest / jest / playwright adapters of ``fenvix.ADAPTERS`` by these (in place)."""
    adapters.update(ADAPTERS)
    return adapters


# ---------------------------------------------------------------------------------------------------------------
# output (docs/CLI.md; the same as fenvix.py's, plus the uncontrolled sources a detjs bundle carries)
def cause_of(b: dict) -> str:
    if b.get("kind") == "uncontrolled":
        return f"uncontrolled source: {(b.get('divergence') or {}).get('description', '')}"
    try:
        from .fenvix import cause_of as _cause  # type: ignore

        return _cause(b)
    except ImportError:  # pragma: no cover - before verifier-cli merges
        pass
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
    lines = [f"fenvix repro: {test}"]
    if status == "not-collected":
        lines.append(f"  not collected: no test has this id. Use an id as detjs writes it (<file>::<describe>::<name>, "
                     f"e.g. from `detjs {b.get('runner', 'vitest')} --det --det-collect --det-outcomes=ids.json`).")
        return "\n".join(lines)
    if status == "not-found":
        lines.append(f"  not reproduced: it passed in the fixed order and under {b.get('configs_searched', '?')} "
                     f"configuration(s) searched (raise --seeds, or run `fenvix explore`)")
        return "\n".join(lines)
    if status == "not-minimised":
        lines.append(f"  failure found under {b.get('config')} but the run budget ran out while minimising "
                     f"(raise --max-runs)")
        return "\n".join(lines)
    rp = b.get("replay") or {}
    bundle_dir = Path(out) / _repro._slug(test)
    unc = b.get("uncontrolled") or []
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
    lines.append(f"  replay:  {b.get('replay_command') or PROG + ' replay ' + shlex.quote(str(bundle_dir))}")
    if b.get("command"):
        lines.append(f"  rerun:   {b['command']}")
    lines.append(f"  bundle:  {bundle_dir} ({b.get('runs')} runs, {b.get('seconds')} s)")
    return "\n".join(lines)


def render_replay(res: dict) -> str:
    ok = res.get("fails") == res.get("runs") and res.get("identical_fingerprint")
    head = "REPRODUCED" if ok else "NOT REPRODUCED"
    lines = [f"fenvix replay: {res.get('test')}: {head}: failed {res.get('fails')}/{res.get('runs')} runs, "
             f"identical fingerprint: {res.get('identical_fingerprint')}, same fingerprint as the bundle: "
             f"{res.get('matches_bundle')}"]
    if not ok:
        lines.append("  the defect no longer fails the same way: fixed, or it depends on something the bundle "
                     "does not hold (code, dependencies, environment changed since it was written)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------
# standalone command line: python -m detpy.fenvix_js repro|explore|replay (docs/CLI.md options)
def pick(explicit: str | None, test: str | None = None, bundle: Path | None = None) -> DetjsAdapter:
    if explicit:
        if explicit not in ADAPTERS:
            raise SystemExit(f"fenvix: unknown runner {explicit!r} (known here: {', '.join(ADAPTERS)})")
        return ADAPTERS[explicit]
    if bundle is not None:
        r = json.loads((bundle / "bundle.json").read_text()).get("runner")
        if r in ADAPTERS:
            return ADAPTERS[r]
    cwd = Path.cwd()
    cands = [a for a in ADAPTERS.values() if (test is None or a.owns(test))]
    local = [a for a in cands if a.detect(cwd)]
    if len(local) == 1:
        return local[0]
    raise SystemExit(f"fenvix: cannot tell the runner of this project ({', '.join(a.name for a in local or cands)}): "
                     f"say which with --runner")


def _split(argv: list) -> tuple[list, list]:
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def _common(p) -> None:
    p.add_argument("--runner", default=None, help="vitest or jest (default: from the project files)")
    p.add_argument("--out", default=".detpy/repro", help="directory of the bundles (default .detpy/repro)")
    p.add_argument("--confirm", type=int, default=10, help="replays that must all fail with one fingerprint (default 10)")
    p.add_argument("--max-runs", type=int, default=400, help="runner runs allowed per test (default 400)")
    p.add_argument("--timeout", type=float, default=1800, help="seconds per runner run (default 1800)")
    p.add_argument("--python", default=sys.executable, help="(accepted for fenvix compatibility; unused)")
    p.add_argument("--json", action="store_true", help="also print the bundle / summary as JSON")


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "repro":
        rest, extra = _split(rest)
        p = argparse.ArgumentParser(prog="fenvix repro", description="Turn a flaky Vitest / Jest test into a "
                                    "reproducible defect (docs/CLI.md). Runner arguments go after `--`.")
        p.add_argument("test")
        p.add_argument("--seeds", type=int, default=50)
        p.add_argument("--seed", default=None)
        _common(p)
        ns = p.parse_args(rest)
        ns.runner_args = extra
        a = pick(ns.runner, test=ns.test)
        why = a.available()
        if why:
            print(f"fenvix: {why}", file=sys.stderr)
            return 2
        b = a.repro(ns)
        print(render_repro(b, Path(ns.out)))
        if ns.json:
            print(json.dumps(b, indent=2))
        return 0 if b.get("status") == "reproduced" else 1
    if cmd == "explore":
        rest, extra = _split(rest)
        p = argparse.ArgumentParser(prog="fenvix explore")
        p.add_argument("--budget", type=float, required=True)
        p.add_argument("--max-seeds", type=int, default=1000)
        p.add_argument("--targets", default=None)
        p.add_argument("--no-repro", action="store_true")
        _common(p)
        ns = p.parse_args(rest)
        ns.runner_args = extra
        a = pick(ns.runner)
        why = a.available()
        if why:
            print(f"fenvix: {why}", file=sys.stderr)
            return 2
        s = a.explore(ns)
        print(_core.repro_render_explore(s).replace("detpy explore", "fenvix explore", 1))
        for b in s.get("bundles", []) if isinstance(s.get("bundles"), list) else []:
            if isinstance(b, dict) and b.get("status") == "reproduced":
                print(f"  defect: {b.get('test')}: {cause_of(b)}; replay: {b.get('replay_command')}")
        if ns.json:
            print(json.dumps(s, indent=2))
        return 0
    if cmd == "replay":
        p = argparse.ArgumentParser(prog="fenvix replay")
        p.add_argument("bundle")
        p.add_argument("--runs", type=int, default=10)
        p.add_argument("--runner", default=None)
        p.add_argument("--python", default=sys.executable)
        p.add_argument("--json", action="store_true")
        ns = p.parse_args(rest)
        bundle = Path(ns.bundle)
        if not (bundle / "bundle.json").is_file():
            print(f"fenvix replay: not a replay bundle: {bundle} (no bundle.json)", file=sys.stderr)
            return 2
        a = pick(ns.runner, bundle=bundle)
        why = a.available()
        if why:
            print(f"fenvix: {why}", file=sys.stderr)
            return 2
        res = a.replay(bundle, ns.runs, ns.python)
        print(json.dumps(res, indent=2) if ns.json else render_replay(res))
        return 0 if res["fails"] == res["runs"] and res["identical_fingerprint"] else 1
    print(f"fenvix_js: unknown command {cmd!r} (repro, explore, replay)", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
