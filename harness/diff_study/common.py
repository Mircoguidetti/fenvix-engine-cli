"""Shared helpers of the execution-diff study: install, run, trace reading,
alternative site identities, run-equivalence patterns."""

from __future__ import annotations

import ast
import bisect
import hashlib
import json
import os
import re
import subprocess
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE_DIR = HERE / "probe"
TEST_WORDS = ("test", "tests", "testing")
REQ_FILES = (
    "requirements/tests.txt", "requirements/test.txt", "requirements/testing.txt",
    "requirements-test.txt", "requirements-tests.txt", "requirements_test.txt", "test-requirements.txt",
    "test_requirements.txt", "tests/requirements.txt", "requirements/dev.txt", "requirements-dev.txt",
    "dev-requirements.txt", "requirements_dev.txt", "requirements.txt",
)
MAX_EVENTS = 200_000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None):
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                           errors="replace", stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out, time.perf_counter() - t0, True


def git(src, *args, timeout=600) -> tuple[int, str]:
    code, out, _, _ = sh(["git", *args], cwd=src, timeout=timeout)
    return code, out


# ---------------------------------------------------------------------------
# Install (same logic as harness/detpy_harness.py)
def detect_install(src: Path) -> tuple[list, list, list]:
    data = {}
    pyproject = src / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
        except Exception:
            data = {}
    extras = [k for k in (data.get("project", {}).get("optional-dependencies") or {})
              if any(w in k.lower() for w in TEST_WORDS)]
    if not extras and (src / "setup.py").exists():
        text = (src / "setup.py").read_text(errors="replace")
        extras = re.findall(r"['\"](tests?|testing)['\"]\s*:", text)[:1]
    args = ["-e", f".[{','.join(extras)}]" if extras else "."]
    groups = []
    all_groups = list(data.get("dependency-groups", {}) or {})
    test_groups = [g for g in all_groups if any(w in g.lower() for w in TEST_WORDS)]
    for g in test_groups or [g for g in all_groups if g.lower() == "dev"]:
        groups += ["--group", g]
    reqs = []
    for f in REQ_FILES:
        if (src / f).exists():
            reqs += ["-r", f]
    return args, groups, reqs


def install(src: Path, py: str, wheel: str, extra: list, log_path: Path) -> tuple[bool, str]:
    base = ["uv", "pip", "install", "--quiet", "--python", py]
    tools = [wheel, "pytest>=7"]
    args, groups, reqs = detect_install(src)
    attempts = [args + groups + reqs + extra, args + groups + extra, args + reqs + extra, args + extra,
                ["-e", "."] + extra]
    out = ""
    for attempt in attempts:
        code, out, _, _ = sh(base + attempt + tools, cwd=src, timeout=1500)
        with open(log_path, "a") as f:
            f.write(" ".join(attempt) + "\n" + out + "\n")
        if code == 0:
            return True, " ".join(attempt)
    return False, out[-400:]


def run_env(py: str, src: Path, probe_out: Path | None, extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHASHSEED", "DETPY_REEXEC", "VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS",
                        "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "DETPY_PRECOMPILE_S")}
    env["PATH"] = str(Path(py).parent) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(Path(py).parent.parent)
    env["COLUMNS"] = "160"
    if probe_out is not None:
        env["PYTHONPATH"] = str(PROBE_DIR)
        env["DIFFPROBE_OUT"] = str(probe_out)
        env["DIFFPROBE_ROOT"] = str(src)
    env.update(extra or {})
    return env


def collect_args(py: str, src: Path, base_args: list) -> tuple[list | None, int, str]:
    has_xdist = sh([py, "-c", "import xdist"])[0] == 0
    xd = ["-n", "0"] if has_xdist else []
    out = ""
    for extra in ([], ["-o", "addopts="]):
        args = base_args + extra + xd
        code, out, _, _ = sh([py, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                              "-p", "no:randomly", *args], cwd=src, env=run_env(py, src, None), timeout=900)
        n = sum(1 for line in out.splitlines() if "::" in line and not line.startswith(("ERROR", "FAILED")))
        if code == 0 and n > 0:
            return args, n, out
    return None, 0, out


def run_det(py: str, src: Path, rundir: Path, tag: str, args: list, timeout: float,
            extra_pytest: list | None = None) -> dict:
    trace = rundir / f"{tag}.jsonl"
    outj = rundir / f"{tag}.outcomes.json"
    probe = rundir / f"{tag}.probe.json"
    for p in (trace, outj, probe):
        p.unlink(missing_ok=True)
    cmd = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det", f"--det-trace={trace}",
           f"--det-outcomes={outj}", f"--det-max-events={MAX_EVENTS}", "-p", "diffprobe", *args,
           *(extra_pytest or [])]
    code, out, dur, to = sh(cmd, cwd=src, env=run_env(py, src, probe), timeout=timeout)
    (rundir / f"{tag}.log").write_text(out[-30000:])
    return {"tag": tag, "exit": code, "duration_s": round(dur, 2), "timed_out": to, "trace": str(trace),
            "probe": str(probe), "outcomes": str(outj)}


# ---------------------------------------------------------------------------
# Traces
def read_trace(path) -> tuple[dict, dict]:
    """(header meta, {nodeid: test record}); empty if missing."""
    meta, tests = {}, {}
    try:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                t = d.get("type")
                if t == "header":
                    meta = d.get("meta", {})
                elif t == "test":
                    tests[d["nodeid"]] = d
    except FileNotFoundError:
        pass
    return meta, tests


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def is_informative(ev: dict) -> bool:
    """Events beyond the outcome and the end-of-test random state digest."""
    return not (ev["s"] == "outcome" or (ev["o"] == "random.state" and ev["at"] == "<end>"))


# ---------------------------------------------------------------------------
# Alternative call-site identities
def _call_lines(node) -> tuple[list, list]:
    """Lines starting a call (and the attribute line of method calls) and
    statement lines inside ``node``'s own scope (nested defs excluded)."""
    calls, stmts = set(), set()
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in n.decorator_list:
                stack.append(d)
            continue
        if isinstance(n, ast.Call):
            calls.add(n.lineno)
            if isinstance(n.func, ast.Attribute) and n.func.end_lineno:
                calls.add(n.func.end_lineno)
        if isinstance(n, ast.stmt):
            stmts.add(n.lineno)
        stack.extend(ast.iter_child_nodes(n))
    return sorted(calls), sorted(stmts)


class SourceIndex:
    """Maps ``path:line`` sites of one commit to (function qualname, ordinal)."""

    def __init__(self, src: Path, commit: str):
        self.src, self.commit = src, commit
        self.files: dict = {}
        self.cache: dict = {}

    def _load(self, path: str):
        if path in self.files:
            return self.files[path]
        info = None
        code, text = git(self.src, "show", f"{self.commit}:{path}", timeout=60)
        if code == 0:
            try:
                tree = ast.parse(text)
                scopes = []  # (start, end, qualname, calls, stmts)

                def visit(node, prefix):
                    for ch in ast.iter_child_nodes(node):
                        if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            q = f"{prefix}.{ch.name}" if prefix else ch.name
                            c, s = _call_lines(ch)
                            start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                            scopes.append((start, ch.end_lineno or ch.lineno, q, c, s))
                            visit(ch, q)
                        else:
                            visit(ch, prefix)

                visit(tree, "")
                c, s = _call_lines(tree)
                scopes.append((1, 10 ** 9, "<module>", c, s))
                info = scopes
            except (SyntaxError, ValueError):
                info = None
        self.files[path] = info
        return info

    def map(self, site: str) -> tuple[str, str]:
        """(function+ordinal id, function id) of a site."""
        hit = self.cache.get(site)
        if hit is not None:
            return hit
        path, _, line = site.rpartition(":")
        res = (site, site)
        if path and line.isdigit() and not path.startswith(("<", "~", "/")):
            scopes = self._load(path)
            if scopes:
                ln = int(line)
                best = None
                for sc in scopes:
                    if sc[0] <= ln <= sc[1] and (best is None or sc[1] - sc[0] < best[1] - best[0]):
                        best = sc
                _, _, q, calls, stmts = best
                i = bisect.bisect_left(calls, ln)
                if i < len(calls) and calls[i] == ln:
                    k = f"c{i}"
                else:
                    k = f"s{bisect.bisect_right(stmts, ln)}"
                res = (f"{path}::{q}#{k}", f"{path}::{q}")
        self.cache[site] = res
        return res


VARIANTS = ("line", "func_ord", "func", "nosite")


def variant_fps(rec: dict, index: SourceIndex | None) -> dict:
    """Fingerprints of one test record under each site identity (None if truncated)."""
    if rec.get("truncated"):
        return {"line": rec["fingerprint"], "func_ord": None, "func": None, "nosite": None}
    hs = {v: hashlib.blake2b(digest_size=12) for v in VARIANTS}
    for e in rec["events"]:
        site = e["at"]
        fo, fn = index.map(site) if index is not None else (site, site)
        tail = f"\x1f{e['t']}\x1f{e['s']}\x1f{e['o']}\x1f{e['v']}\x1e"
        hs["line"].update((site + tail).encode("utf-8", "surrogateescape"))
        hs["func_ord"].update((fo + tail).encode("utf-8", "surrogateescape"))
        hs["func"].update((fn + tail).encode("utf-8", "surrogateescape"))
        hs["nosite"].update(tail.encode("utf-8", "surrogateescape"))
    return {v: h.hexdigest() for v, h in hs.items()}


def pattern(values: list) -> str:
    """Equivalence classes of runs: [x, x, y, None] -> 'AAB-'."""
    seen: dict = {}
    out = []
    for v in values:
        if v is None:
            out.append("-")
            continue
        if v not in seen:
            seen[v] = "ABCDEFGHIJ"[len(seen)]
        out.append(seen[v])
    return "".join(out)


def site_path(site: str) -> str:
    path, _, line = site.rpartition(":")
    return path if line.isdigit() else site


def first_divergence(ea: list, eb: list) -> tuple[int, dict | None, dict | None]:
    n = min(len(ea), len(eb))
    for i in range(n):
        if ea[i] != eb[i]:
            return i, ea[i], eb[i]
    if len(ea) == len(eb):
        return -1, None, None
    return n, (ea[n] if n < len(ea) else None), (eb[n] if n < len(eb) else None)


def is_test_path(p: str) -> bool:
    parts = p.split("/")
    base = parts[-1]
    return (base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"
            or any(x in ("tests", "test", "testing") for x in parts[:-1]))


def locate(ev_a: dict | None, ev_b: dict | None, changed: set) -> str:
    """Where the first diverging event happened."""
    evs = [e for e in (ev_a, ev_b) if e is not None]
    if any(e["s"] == "outcome" for e in evs) and all(e["s"] == "outcome" for e in evs):
        return "outcome-only"
    paths = [site_path(e["at"]) for e in evs if e["s"] != "outcome"]
    if any(p in changed for p in paths):
        return "changed-file"
    if any(p == "<end>" for p in paths):
        return "end-random-state"
    for p in paths:
        if p.startswith("<site>"):
            return "site-packages"
        if p.startswith("<stdlib>") or p.startswith("<frozen"):
            return "stdlib"
    for p in paths:
        if not p.startswith("<") and is_test_path(p):
            return "unchanged-test-file"
    for p in paths:
        if not p.startswith("<"):
            return "unchanged-source-file"
    return "other"


def short_event(e: dict | None) -> dict | None:
    if e is None:
        return None
    return {"t": e["t"], "s": e["s"], "o": e["o"], "at": e["at"], "v": str(e["v"])[:160]}
