#!/usr/bin/env python3
"""Measurement harness for detjs Level 0 (Node / TypeScript, Vitest and Jest).

Mirrors harness/detpy_harness.py (same protocol, metrics and per-test CSV
columns; the protocol, seed exploration, ablation and per-test analysis are
the Python harness's own functions, with the test-runner invocation replaced):

* pools (harness/node/repos.json): ``flaky`` = projects with documented flaky
  tests (harness/node/flaky_candidates.json: the Hashemi et al. ICSME 2022
  dataset, then GitHub issues), pinned at the commit where the flakiness was
  documented; ``popular`` = popular projects with large Vitest/Jest suites at HEAD;
* baseline (realistic): Vitest ``--sequence.shuffle --sequence.seed=<per run>``,
  Jest ``--randomize --seed=<per run>`` (Jest >= 29.2; older Jest has no
  random order), two workers;
* ``--det`` runs (fixed order, serial), seed exploration ``--det-seed=1..K``
  with confirm/confirm confirmation, ablation of tests broken by ``--det``
  (reference: ``--det`` with every Level 0 control off but order and serial
  execution, then one ``--det-disable=<control>`` run per control), quiet
  timing pass, causes of non-reproduced baseline-flaky tests.

The verifier is the Rust one: through the Python binding when the detpy wheel
is installed (CI installs it: the same verifier reads Node and Python traces),
otherwise through the Node binding (``detjs verify --json``).

    python harness/node/node_harness.py --set zod --mode round --runs 10
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
import detpy_harness as H  # noqa: E402

DETJS = ROOT / "node" / "bin" / "detjs.js"
NODE_CONTROLS = ("seeds", "time", "timers", "fs", "net")
log = H.log
sh = H.sh


# ---------------------------------------------------------------------------
# Verifier: Python binding of the Rust core when available, else the Node one.
class _NodeCore:
    @staticmethod
    def verify(paths) -> str:
        r = subprocess.run([NODE_BIN or "node", str(DETJS), "verify", "--json", *map(str, paths)],
                           capture_output=True, text=True)
        if not r.stdout.strip():
            raise RuntimeError(r.stderr[-500:])
        return r.stdout


class _Shim:
    _core = _NodeCore
    __version__ = "node-binding"


VERIFIER = "unknown"


def _import_core():
    global VERIFIER
    try:
        import detpy._core  # noqa: F401
        import detpy
        VERIFIER = f"Rust verifier through the Python binding (detpy {detpy.__version__})"
        return detpy
    except ImportError:
        VERIFIER = "Rust verifier through the Node binding (detjs verify)"
        return _Shim


H._import_detpy = _import_core
H.ABLATE_CONTROLS = NODE_CONTROLS
NODE_BIN = None


# ---------------------------------------------------------------------------
# Node versions
NODE_DIST = "https://nodejs.org/dist"


def node_versions() -> list:
    cache = Path(os.environ.get("DETJS_HARNESS_CACHE", "/tmp/detjs-harness-cache"))
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / "node-index.json"
    if not f.exists():
        urllib.request.urlretrieve(f"{NODE_DIST}/index.json", f)
    return json.loads(f.read_text())


def ensure_node(major: int) -> str:
    """bin directory of the latest Node `major` (downloaded once)."""
    cache = Path(os.environ.get("DETJS_HARNESS_CACHE", "/tmp/detjs-harness-cache"))
    v = next(x["version"] for x in node_versions() if int(x["version"][1:].split(".")[0]) == major)
    d = cache / f"node-{v}-linux-x64"
    if not (d / "bin" / "node").exists():
        tar = cache / f"node-{v}.tar.xz"
        urllib.request.urlretrieve(f"{NODE_DIST}/{v}/node-{v}-linux-x64.tar.xz", tar)
        subprocess.run(["tar", "-xJf", str(tar), "-C", str(cache)], check=True)
        tar.unlink()
    return str(d / "bin")


def pick_node(src: Path, commit_date: str, forced) -> int:
    """Node major for a checkout: .nvmrc/.node-version, else engines.node, else the commit era.
    Never below 18 (detjs needs Node >= 18) nor above 22."""
    if forced:
        return int(forced)
    for f in (".nvmrc", ".node-version"):
        p = src / f
        if p.exists():
            m = re.search(r"(\d+)", p.read_text())
            if m:
                return min(22, max(18, int(m.group(1))))
    try:
        eng = json.loads((src / "package.json").read_text()).get("engines", {}).get("node", "")
        m = re.findall(r"(\d+)", eng)
        if m and ">" in eng:
            return min(22, max(18, int(m[0]) if int(m[0]) >= 18 else 18))
    except (OSError, ValueError):
        pass
    year = int(commit_date[:4]) if commit_date[:4].isdigit() else 2026
    return 18 if year <= 2022 else 20 if year <= 2024 else 22


# ---------------------------------------------------------------------------
# Preparation
@dataclass
class Prepared(H.Prepared):
    runner: str = ""  # vitest | jest
    runner_version: str = ""
    node_bin: str = ""
    runner_bin: str = ""
    random_order: bool = True
    documented: dict = field(default_factory=dict)  # file or test-name hint -> category
    source: str = ""


def git(args, cwd, timeout=900):
    return sh(["git", *args], cwd=cwd, timeout=timeout)


def checkout(p: Prepared, repo: dict, work: Path) -> bool:
    src = work / "src" / p.name
    shutil.rmtree(src, ignore_errors=True)
    code, out, _, _ = git(["clone", "-q", "--filter=blob:none", p.url, str(src)], cwd=work)
    if code != 0:
        p.status, p.detail = "clone-failed", out[-300:]
        return False
    target = "HEAD"
    if repo.get("pin") == "parent-of-fix":
        for c in repo.get("commits", []):
            if git(["cat-file", "-e", f"{c['fix_commit']}^"], cwd=src)[0] == 0:
                target = f"{c['fix_commit']}^"
                _, files, _, _ = git(["diff", "--name-only", f"{c['fix_commit']}^", c["fix_commit"]], cwd=src)
                for f in files.split():
                    if re.search(r"(test|spec|__tests__)", f):
                        p.documented[f] = f"hashemi:{c['cause']}"
                p.source = c["commit_url"]
                break
        else:
            p.status, p.detail = "commit-missing", "no fix commit of the dataset is reachable"
            return False
    elif repo.get("pin") == "before-issue":
        issue = repo["issues"][0]
        _, sha, _, _ = git(["rev-list", "-1", f"--before={issue['created_at']}", "HEAD"], cwd=src)
        target = sha.strip() or "HEAD"
        p.source = issue["url"]
        for tok in re.findall(r"[`'\"]([^`'\"]{4,120})[`'\"]|([\w./-]+\.(?:test|spec)\.[cm]?[jt]sx?)", issue["title"]):
            hint = tok[0] or tok[1]
            p.documented[hint] = "issue"
        if not p.documented:
            p.documented[issue["title"]] = "issue-title"
    elif repo.get("commit"):
        target = repo["commit"]
    if git(["checkout", "-q", target], cwd=src)[0] != 0:
        p.status, p.detail = "checkout-failed", target
        return False
    _, p.commit, _, _ = git(["rev-parse", "HEAD"], cwd=src)
    p.commit = p.commit.strip()
    _, p.commit_date, _, _ = git(["log", "-1", "--format=%cI"], cwd=src)
    p.commit_date = p.commit_date.strip()
    p.src = str(src)
    return True


def node_env(p: Prepared, extra=None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DETJS", "npm_", "NODE_OPTIONS"))}
    env.update({"PATH": f"{p.node_bin}:{env.get('PATH', '')}", "CI": "true", "HUSKY": "0", "FORCE_COLOR": "0",
                "PUPPETEER_SKIP_DOWNLOAD": "1", "PUPPETEER_SKIP_CHROMIUM_DOWNLOAD": "1",
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1", "CYPRESS_INSTALL_BINARY": "0",
                "ELECTRON_SKIP_BINARY_DOWNLOAD": "1", "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
                "COREPACK_ENABLE_STRICT": "0", "NODE_OPTIONS": "--max-old-space-size=6144"})
    env.update(p.env)
    env.update(extra or {})
    return env


def install(p: Prepared, repo: dict) -> bool:
    src = Path(p.src)
    env = node_env(p)
    sh(["corepack", "enable", "--install-directory", p.node_bin], cwd=src, env=env)
    pkg = json.loads((src / "package.json").read_text())
    pm_field = pkg.get("packageManager", "")
    if repo.get("install"):
        cmds = [repo["install"]]
    elif (src / "pnpm-lock.yaml").exists() or pm_field.startswith("pnpm"):
        cmds = [["pnpm", "install", "--frozen-lockfile"], ["pnpm", "install", "--no-frozen-lockfile"]]
    elif (src / "yarn.lock").exists() or pm_field.startswith("yarn"):
        if (src / ".yarnrc.yml").exists():
            cmds = [["yarn", "install", "--immutable"], ["yarn", "install"]]
        else:
            cmds = [["npx", "-y", "yarn@1", "install", "--frozen-lockfile", "--ignore-engines"],
                    ["npx", "-y", "yarn@1", "install", "--ignore-engines"]]
    elif (src / "bun.lockb").exists() or (src / "bun.lock").exists():
        p.status, p.detail = "unsupported", "bun project"
        return False
    else:
        cmds = [["npm", "ci", "--no-audit", "--no-fund"], ["npm", "install", "--no-audit", "--no-fund", "--legacy-peer-deps"]]
    out = ""
    for cmd in cmds:
        cmd = cmd if isinstance(cmd, list) else ["bash", "-lc", cmd]
        code, out, dur, to = sh(cmd, cwd=src, env=env, timeout=1500)
        log(f"{p.name}: install `{' '.join(cmd)}` exit={code} {dur:.0f}s")
        if code == 0:
            p.install_cmd = " ".join(cmd)
            break
    else:
        p.status, p.detail = "install-failed", out[-400:]
        return False
    for cmd in repo.get("build", []):
        code, out, dur, _ = sh(["bash", "-lc", cmd], cwd=src, env=env, timeout=1500)
        log(f"{p.name}: build `{cmd}` exit={code} {dur:.0f}s")
        if code != 0:
            p.status, p.detail = "build-failed", out[-400:]
            return False
    return True


def detect_runner(p: Prepared, repo: dict) -> bool:
    src = Path(p.src)
    req = f"require('module').createRequire(process.cwd() + '/x.js')"
    for runner in ([repo["runner"]] if repo.get("runner") else ["vitest", "jest"]):
        code, out, _, _ = sh([f"{p.node_bin}/node", "-e",
                              f"const r={req}; const f=r.resolve('{runner}/package.json'); const j=require(f);"
                              f"const b=typeof j.bin==='string'?j.bin:j.bin['{runner}'];"
                              f"console.log(JSON.stringify({{v:j.version, bin:require('path').join(require('path').dirname(f), b)}}))"],
                             cwd=src, env=node_env(p))
        if code == 0:
            info = json.loads(out.strip().splitlines()[-1])
            p.runner, p.runner_version, p.runner_bin = runner, info["v"], info["bin"]
            major, minor = (int(x) for x in info["v"].split(".")[:2])
            if runner == "jest":
                p.random_order = major > 29 or (major == 29 and minor >= 2)
            if runner == "vitest" and (major, minor) < (1, 4):
                p.status, p.detail = "unsupported", f"vitest {info['v']} (detjs needs >= 1.4)"
                return False
            return True
    p.status, p.detail = "no-runner", "neither vitest nor jest resolvable from the repository root"
    return False


def prepare(repo: dict, work: Path, _wheel, _default, max_first_run: float) -> Prepared:
    global NODE_BIN
    p = Prepared(name=repo["name"], url=repo["url"], kind=repo.get("kind", "popular"))
    p.max_run_seconds = max_first_run
    p.env = repo.get("env", {})
    p.pytest_args = list(repo.get("args", []))
    if not checkout(p, repo, work):
        return p
    major = pick_node(Path(p.src), p.commit_date, repo.get("node"))
    try:
        p.node_bin = ensure_node(major)
    except Exception as e:  # network
        p.status, p.detail = "node-download-failed", repr(e)
        return p
    NODE_BIN = f"{p.node_bin}/node"
    _, v, _, _ = sh([NODE_BIN, "--version"])
    p.python_version = f"node {v.strip()}"
    if not install(p, repo) or not detect_runner(p, repo):
        return p
    p.xdist = True  # two workers in the baseline
    p.has_xdist = True
    p.status = "ok"
    return p


# ---------------------------------------------------------------------------
# Runs
def parse_report(path: Path, root: str) -> tuple[dict, dict]:
    """Jest-format JSON report (Jest --json, Vitest --reporter=json) -> outcomes, exceptions."""
    outcomes, exceptions = {}, {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return outcomes, exceptions
    norm = {"passed": "passed", "failed": "failed", "pending": "skipped", "skipped": "skipped", "todo": "todo",
            "disabled": "skipped", "focused": "passed"}
    for f in data.get("testResults", []):
        fid = os.path.relpath(f.get("name", ""), root).replace(os.sep, "/")
        results = f.get("assertionResults") or []
        if not results and f.get("status") == "failed":
            nid = f"{fid}::<file>"
            outcomes[nid] = "error"
            msg = (f.get("message") or f.get("failureMessage") or "").strip()
            exceptions[nid] = _exc(msg, "collect")
        for a in results:
            nid = "::".join([fid, *a.get("ancestorTitles", []), a.get("title", "")])
            o = norm.get(a.get("status"), a.get("status") or "unknown")
            prev = outcomes.get(nid)
            if prev is None or (o == "failed" and prev != "failed"):
                outcomes[nid] = o
            if o == "failed" and nid not in exceptions:
                exceptions[nid] = _exc("\n".join(a.get("failureMessages") or []), "call")
    return outcomes, exceptions


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _exc(msg: str, phase: str) -> list:
    msg = _ANSI.sub("", msg or "").strip()
    first = msg.splitlines()[0] if msg else ""
    m = re.match(r"^\s*([A-Za-z_$][\w$.]*(?:Error|Exception|Error\b)?)(?: \[[A-Z_]+\])?: ", first)
    etype = m.group(1).rsplit(".", 1)[-1] if m else ("AssertionError" if re.search(r"expect\(|toBe|toEqual", first) else
                                                     "Timeout" if "timed out" in first.lower() or "timeout" in first.lower() else "unknown")
    where = ""
    for line in msg.splitlines()[1:]:
        mm = re.search(r"\(?([^\s()]+):(\d+):\d+\)?\s*$", line.strip())
        if mm and "node_modules" not in mm.group(1) and "node:" not in mm.group(1):
            where = f"{mm.group(1)}:{mm.group(2)}"
            break
    return [etype, phase, first[:200], where]


def command(p: Prepared, mode: str, index: int, seed, disable, report: Path, trace: Path | None) -> list:
    node = f"{p.node_bin}/node"
    if p.runner == "vitest":
        rep = ["--reporter=json", f"--outputFile={report}"]
        major = int(p.runner_version.split(".")[0])
        workers = ["--maxWorkers=2"] + (["--minWorkers=1"] if major < 4 else [])
        if mode == "normal":
            return [node, p.runner_bin, "run", *rep, "--sequence.shuffle", f"--sequence.seed={1000 + index}", *workers, *p.pytest_args]
        if mode == "timing-serial":
            return [node, p.runner_bin, "run", *rep, "--no-file-parallelism", "--maxWorkers=1",
                    *(["--minWorkers=1"] if major < 4 else []), *p.pytest_args]
        base = [node, str(DETJS), "vitest", "run", *rep]
    else:
        rep = ["--ci", "--json", f"--outputFile={report}"]
        if mode == "normal":
            rnd = ["--randomize", f"--seed={1000 + index}"] if p.random_order else []
            return [node, p.runner_bin, *rep, *rnd, "--maxWorkers=2", *p.pytest_args]
        if mode == "timing-serial":
            return [node, p.runner_bin, *rep, "--runInBand", *p.pytest_args]
        base = [node, str(DETJS), "jest", *rep]
    det = ["--det", f"--det-trace={trace}"]
    if mode in ("serial",):
        det.append("--det-disable=" + ",".join(NODE_CONTROLS))
    if seed is not None:
        det.append(f"--det-seed={seed}")
    if disable is not None:
        det.append(f"--det-disable={disable}")
    return [*base, *det, *p.pytest_args]


def run_node(p: Prepared, rundir: Path, mode: str, index: int, timeout: float, seed=None, disable=None):
    """Same contract as detpy_harness.run_pytest. Modes: normal (baseline), serial (reference for the
    ablation: --det with every Level 0 control off except order and serial execution), det, seed,
    ablate, timing-serial (quiet timing: serial runner without --det)."""
    tag = f"{mode}{'' if seed is None else seed}{'' if disable is None else '-' + disable}_{index}"
    report = rundir / f"{tag}.json"
    trace = rundir / f"{tag}.jsonl" if mode not in ("normal", "timing-serial") else None
    report.unlink(missing_ok=True)
    cmd = command(p, mode, index, seed, disable, report, trace)
    code, out, dur, to = sh(cmd, cwd=p.src, env=node_env(p), timeout=timeout)
    (rundir / f"{tag}.log").write_text(out[-20000:])
    outcomes, exceptions = parse_report(report, p.src)
    return H.RunResult(mode, index, seed, dur, code, to, outcomes,
                       str(trace) if trace and trace.exists() else None, None, exceptions)


H.run_pytest = run_node

_orig_analyze = H.analyze


def analyze(p: Prepared, results, explore, outdir: Path) -> dict:
    """Map the documented flaky files / names onto test ids, then the Python harness analysis."""
    ids = set().union(*(r.outcomes.keys() for r in results)) if results else set()
    known = {}
    for hint, cat in p.documented.items():
        for nid in ids:
            fid = nid.split("::", 1)[0]
            if fid == hint or fid.endswith("/" + hint) or (len(hint) > 6 and hint in nid):
                known[nid] = cat
    p.known_flaky = known
    s = _orig_analyze(p, results, explore, outdir)
    s.update({"runner": f"{p.runner} {p.runner_version}", "node": p.python_version, "documented_source": p.source,
              "documented_hints": list(p.documented)[:10], "random_order_baseline": p.random_order,
              "verifier": VERIFIER})
    csv_path = outdir / f"{p.name}.csv"
    if csv_path.exists():
        text = csv_path.read_text().replace("idoft_category", "documented_flaky", 1)
        csv_path.write_text(text)
    causes = classify_not_reproduced(p, outdir)
    s["not_reproduced_causes"] = causes
    (outdir / f"{p.name}.summary.json").write_text(json.dumps(s, indent=2))
    return s


H.analyze = analyze


# ---------------------------------------------------------------------------
# Causes of baseline-flaky tests that --det did not reproduce
A = re.compile(r"(setTimeout|setInterval|setImmediate|nextTick|Promise\.(?:all|race|any)|await |async |waitFor|"
               r"findBy|act\(|flushPromises|useFakeTimers|advanceTimers|runAllTimers|Date\.now|new Date|"
               r"performance\.now|requestAnimationFrame|debounce|throttle|timeout|Worker\(|worker_threads|"
               r"EventEmitter|\.on\(|\.once\(|race|concurren)", re.I)
B = re.compile(r"(fetch\(|https?://|http\.|https\.|axios|net\.|dns\.|child_process|spawn|exec\(|execa|"
               r"process\.env|os\.|puppeteer|playwright|chromium|browser|\.listen\(|createServer|redis|postgres|"
               r"mysql|mongo|sqlite|docker|fs\.|readFile|writeFile|tmp|mkdtemp|process\.platform|navigator)", re.I)
C = re.compile(r"(jest\.mock|vi\.mock|mockImplementation|mockReturnValue|spyOn|beforeAll|afterAll|global\.|"
               r"globalThis\.|window\.|document\.|localStorage|module-level|singleton|cache|Math\.random|"
               r"randomUUID|getRandomValues|readdir|resetModules|isolateModules)")
EXC_A = {"Timeout", "TimeoutError", "AbortError"}
EXC_B = {"NetworkBlockedError", "FetchError", "ECONNREFUSED", "ECONNRESET", "ENOTFOUND", "EADDRINUSE", "EACCES",
         "ENOENT", "EPERM", "SystemError"}


def test_source(src: Path, nodeid: str) -> str:
    parts = nodeid.split("::")
    f = src / parts[0]
    if not f.exists():
        return ""
    text = f.read_text(errors="replace")
    title = parts[-1]
    i = text.find(title[:60])
    if i < 0:
        return ""
    return text[max(0, i - 200): i + 2500]


def classify_row(row: dict, src: str) -> tuple[str, str]:
    reason = row.get("pass_fail_reason", "") or row.get("det_reason", "")
    exc = row.get("det_exception") or row.get("baseline_exception") or ""
    msg = row.get("det_exception_message", "")
    if reason == "net" or exc in EXC_B or B.search(msg or ""):
        return "external", f"exception {exc or '-'} / diverging event {reason or '-'}"
    if reason in ("random", "fs", "time"):
        return "l0-gap", f"diverging event `{reason}`: a controlled source still differs between runs"
    if exc in EXC_A or "timed out" in (msg or "").lower() or "timeout" in (msg or "").lower():
        return "concurrency/event-order", f"exception {exc or '-'}: {msg[:80]}"
    hits_b, hits_a, hits_c = (sorted(set(m.lower() for m in X.findall(src))) for X in (B, A, C))
    if hits_a:
        return "concurrency/event-order", f"test source uses {', '.join(hits_a[:4])}" + (
            f"; also {', '.join(hits_b[:3])}" if hits_b else "")
    if hits_b:
        return "external", f"test source uses {', '.join(hits_b[:4])}"
    if hits_c:
        return "l0-gap", f"shared state not reset by Level 0: {', '.join(hits_c[:4])}"
    return "unknown", "no marker in the source, exception or fingerprint" + ("" if src else " (source not found)")


def classify_not_reproduced(p: Prepared, outdir: Path) -> dict:
    rows = list(csv.DictReader(open(outdir / f"{p.name}.csv"))) if (outdir / f"{p.name}.csv").exists() else []
    out, counts = [], collections.Counter()
    for r in rows:
        if r.get("baseline_unstable") != "True" or r.get("reproduced") == "True":
            continue
        cls, why = classify_row(r, test_source(Path(p.src), r["nodeid"]))
        counts[cls] += 1
        never = all(not x.split("=")[0].startswith(("failed", "error")) for x in r["det_outcomes"].split(";"))
        out.append({"repo": p.name, "pool": p.kind, "nodeid": r["nodeid"], "class": cls, "evidence": why,
                    "documented": r.get("documented_flaky", ""), "under_det": "never fails" if never else "fails",
                    "baseline_outcomes": r["baseline_outcomes"], "det_exception": r.get("det_exception", ""),
                    "pass_fail_reason": r.get("pass_fail_reason", "")})
    (outdir / f"{p.name}.causes.json").write_text(json.dumps(out, indent=1))
    return dict(counts)


# ---------------------------------------------------------------------------
def timing_pass(p: Prepared, args, outdir: Path, work: Path) -> dict:
    rundir = work / "timing" / p.name
    shutil.rmtree(rundir, ignore_errors=True)
    rundir.mkdir(parents=True)
    normal, det = [], []
    for i in range(args.timing_runs):
        normal.append(run_node(p, rundir, "timing-serial", i, args.run_timeout))
        det.append(run_node(p, rundir, "det", i, args.run_timeout))
        log(f"{p.name}: timing #{i} serial {normal[-1].duration:.2f}s det {det[-1].duration:.2f}s")
    res = {"name": p.name, "kind": p.kind, "status": "ok", "node": p.python_version,
           "runner": f"{p.runner} {p.runner_version}", "serial_s": [r.duration for r in normal],
           "det_s": [r.duration for r in det], "tests": len(normal[0].outcomes) if normal else 0,
           "machine": H.runner_info()}
    m_n, m_d = statistics.median(res["serial_s"]), statistics.median(res["det_s"])
    res["slowdown_pct"] = (m_d / m_n - 1) * 100 if m_n > 0 else None
    (outdir / f"{p.name}.timing.json").write_text(json.dumps(res, indent=2))
    return res


def prepare_check(p: Prepared, args, outdir: Path, work: Path) -> dict:
    rundir = work / "runs" / p.name
    shutil.rmtree(rundir, ignore_errors=True)
    rundir.mkdir(parents=True)
    r = run_node(p, rundir, "normal", 0, args.run_timeout)
    res = {"name": p.name, "kind": p.kind, "status": "ok", "node": p.python_version, "runner": p.runner,
           "runner_version": p.runner_version, "tests": len(r.outcomes), "first_run_s": r.duration,
           "commit": p.commit, "detail": ""}
    failing = sum(H.is_fail(o) for o in r.outcomes.values())
    if r.timed_out or r.duration > p.max_run_seconds:
        res.update(status="too-slow", detail=f"first baseline run took {r.duration:.0f}s")
    elif len(r.outcomes) < args.min_tests:
        tail = (rundir / "normal_0.log").read_text()[-300:] if (rundir / "normal_0.log").exists() else ""
        res.update(status="baseline-broken" if not r.outcomes else "too-few-tests",
                   detail=f"{len(r.outcomes)} test outcomes (exit {r.exit_code}): {tail}")
    elif failing > 0.5 * len(r.outcomes):
        res.update(status="baseline-broken", detail=f"{failing}/{len(r.outcomes)} tests fail in the first baseline run")
    (outdir / f"{p.name}.prepare.json").write_text(json.dumps(res, indent=2))
    return res


def load_pools(cfg: dict) -> tuple[list, list]:
    popular = [dict(r, kind="popular") for r in cfg["popular"]]
    flaky = []
    cand = HERE / cfg.get("flaky_candidates", "flaky_candidates.json")
    if cand.exists():
        overrides = cfg.get("flaky_overrides", {})
        for c in json.loads(cand.read_text())["candidates"]:
            flaky.append(dict(c, kind="flaky", **overrides.get(c["name"], {})))
    return flaky, popular


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", default=str(HERE / "repos.json"))
    ap.add_argument("--set", required=True, help="comma separated repository names")
    ap.add_argument("--mode", choices=("round", "prepare", "timing"), default="round")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--confirm", type=int, default=10)
    ap.add_argument("--work", default=str(ROOT / ".harness-work" / "node"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-timeout", type=float, default=900)
    ap.add_argument("--max-first-run", type=float, default=150)
    ap.add_argument("--min-tests", type=int, default=50)
    ap.add_argument("--repo-budget", type=float, default=2700)
    ap.add_argument("--timing-runs", type=int, default=3)
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("--executor", default="local")
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.repos).read_text())
    flaky, popular = load_pools(cfg)
    by_name = {r["name"]: r for r in popular + flaky}
    outdir, work = Path(args.out), Path(args.work)
    outdir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    _import_core()
    rc = 0
    for name in [n.strip() for n in args.set.split(",") if n.strip()]:
        repo = by_name[name]
        try:
            p = prepare(repo, work, None, None, args.max_first_run)
            log(f"prepared {p.name} [{p.kind}]: {p.status} {p.python_version} {p.runner} {p.runner_version} "
                f"{p.commit[:10]} {p.detail[-120:]!r}")
            if p.status != "ok":
                r = {"name": p.name, "kind": p.kind, "status": p.status, "detail": p.detail}
            elif args.mode == "prepare":
                r = prepare_check(p, args, outdir, work)
            elif args.mode == "timing":
                r = timing_pass(p, args, outdir, work)
            else:
                r = H.measure(p, args, outdir, work)
                if r.get("status") != "ok":
                    r.setdefault("detail", "")
        except Exception as e:  # pragma: no cover
            import traceback
            r = {"name": name, "kind": repo.get("kind", ""), "status": "harness-error",
                 "detail": repr(e) + traceback.format_exc()[-600:]}
            rc = 1
        r.update({"executor": args.executor, "date": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        (outdir / f"{name}.{args.mode}.result.json").write_text(json.dumps(r, indent=2, default=str))
        log(f"done {name}: {r.get('status')} {str(r.get('detail', ''))[-200:]}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
