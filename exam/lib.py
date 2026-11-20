"""Exam library: commands, checkouts, environments, outcome maps and check records.

Every engine call goes through the customer's single entry `fenvix` on PATH. Nothing here decides anything the engine
should decide: the library runs the customer's commands and compares what they print and write with a plain run.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

EXAM = Path(__file__).resolve().parent
PLUGINS = EXAM / "plugins"


def leg_from_env() -> dict:
    return {
        "platform": os.environ.get("EXAM_PLATFORM", "local"),
        "python": os.environ.get("EXAM_PYTHON", f"{sys.version_info.major}.{sys.version_info.minor}"),
        "node": os.environ.get("EXAM_NODE", ""),
        "variant": os.environ.get("EXAM_VARIANT", ""),
    }


class Skip(Exception):
    """A check that cannot start because an earlier step of the same leg failed (recorded as FAIL with the reason)."""


class Ctx:
    def __init__(self, work: str, rows: list[str]):
        self.work = Path(work).resolve()
        self.logs = self.work / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.rows = rows
        self.leg = leg_from_env()
        self.results: list[dict] = []
        self.install = self._install_info()
        self._n = 0
        self._venvs: dict[str, Path] = {}
        self._clones: dict[str, Path] = {}

    # -- install ------------------------------------------------------------------------------------------------------
    def _install_info(self) -> dict:
        p = os.environ.get("EXAM_INSTALL_INFO")
        if p and os.path.exists(p):
            try:
                return json.load(open(p))
            except ValueError:
                pass
        return {"ok": shutil.which("fenvix") is not None, "source": os.environ.get("EXAM_INSTALL", "ci-artifact"),
                "reason": "" if shutil.which("fenvix") else "fenvix not on PATH"}

    def need_install(self):
        if not self.install.get("ok"):
            raise Skip(f"install failed: {self.install.get('reason', 'unknown')}")

    # -- commands -----------------------------------------------------------------------------------------------------
    def sh(self, name: str, cmd, cwd=None, env=None, timeout=1800, input=None) -> tuple:
        self._n += 1
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:90]
        logf = self.logs / f"{self._n:04d}-{safe}.log"
        e = dict(os.environ)
        e.update({k: str(v) for k, v in (env or {}).items() if v is not None})
        for k, v in (env or {}).items():
            if v is None:
                e.pop(k, None)
        t = time.time()
        try:
            p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=e, shell=isinstance(cmd, str), text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, input=input,
                               errors="replace")
            rc, out = p.returncode, p.stdout
        except subprocess.TimeoutExpired as x:
            rc = "timeout"
            out = x.stdout.decode(errors="replace") if isinstance(x.stdout, bytes) else (x.stdout or "")
        except FileNotFoundError as x:
            rc, out = 127, f"{x}"
        dt = time.time() - t
        with open(logf, "w") as fh:
            fh.write(f"$ {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))}\n# cwd={cwd} rc={rc} {dt:.1f}s\n")
            fh.write(out)
        print(f"  [{name}] rc={rc} {dt:.1f}s", flush=True)
        return rc, out

    # -- checks -------------------------------------------------------------------------------------------------------
    def record(self, cid: str, ok, expected: str, observed: str, evidence=None, gaps=None):
        row = cid.split(".")[0]
        r = {"id": cid, "row": row, "leg": self.leg, "ok": bool(ok), "expected": expected,
             "observed": str(observed)[:2000], "evidence": evidence or {}, "gaps": gaps or []}
        self.results.append(r)
        print(f"{'PASS' if ok else 'FAIL'} {cid}: {str(observed)[:300]}", flush=True)
        return ok

    def run_check(self, cid: str, expected: str, fn, gaps=None):
        """Run fn() -> (ok, observed[, evidence]); any exception is a FAIL with its reason."""
        print(f"== {cid}", flush=True)
        try:
            res = fn()
            ok, observed = res[0], res[1]
            ev = res[2] if len(res) > 2 else None
        except Skip as s:
            ok, observed, ev = False, f"not run: {s}", None
        except Exception as x:  # recorded, never hidden
            ok, observed, ev = False, f"exam error: {type(x).__name__}: {x}", {"traceback": traceback.format_exc()[-1500:]}
        return self.record(cid, ok, expected, observed, ev, gaps)

    # -- checkouts ----------------------------------------------------------------------------------------------------
    def clone(self, proj: dict, name: str | None = None, fresh=False) -> Path:
        key = name or proj["name"]
        d = self.work / "src" / key
        if key in self._clones and not fresh:
            return d
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for cmd in (["git", "init", "-q"], ["git", "fetch", "-q", "--depth", "1", proj["url"], proj["sha"]],
                    ["git", "checkout", "-q", "FETCH_HEAD"]):
            rc, out = self.sh(f"clone-{key}", cmd, cwd=d, timeout=900)
            if rc != 0:
                raise Skip(f"clone {proj['url']}@{proj['sha']} failed: {out[-300:]}")
        if proj.get("submodules"):
            self.sh(f"submodules-{key}", ["git", "submodule", "update", "--init", "--depth", "1"], cwd=d)
        self._clones[key] = d
        return d

    def reset(self, d: Path):
        """Back to the pinned commit: tracked files restored, untracked files removed (keeps .venv, node_modules)."""
        self.sh("reset", ["git", "checkout", "-q", "--", "."], cwd=d)
        self.sh("clean", ["git", "clean", "-qfdx", "-e", ".venv", "-e", "node_modules", "-e", ".yarn",
                          "-e", ".pnp.*", "-e", ".exam-*"], cwd=d)


# ---------------------------------------------------------------------------------------------------------------------
# Python environments
# ---------------------------------------------------------------------------------------------------------------------

def py_exe() -> str:
    return os.environ.get("EXAM_PY_EXE") or shutil.which("python3") or sys.executable


def venv(ctx: Ctx, d: Path, install: list[str], engine=True, key=None) -> dict:
    """A virtual environment in the checkout with the project's test dependencies and (by the install switch) the
    engine. Returns the env dict that puts it first on PATH."""
    v = d / ".venv"
    k = key or str(d)
    if k not in ctx._venvs:
        if v.exists():
            shutil.rmtree(v)
        rc, out = ctx.sh("venv", [py_exe(), "-m", "venv", str(v)], cwd=d)
        if rc != 0:
            raise Skip(f"venv failed: {out[-300:]}")
        pip = [str(v / "bin" / "python"), "-m", "pip", "install", "-q", "--disable-pip-version-check"]
        ctx.sh("pip-upgrade", pip + ["-U", "pip"], cwd=d)
        if install:
            rc, out = ctx.sh("pip-project", pip + install, cwd=d, timeout=1800)
            if rc != 0:
                raise Skip(f"project install failed: {out[-500:]}")
        if engine:
            ctx.need_install()
            # the artifact's own wheel into the project's venv: what a runner image must do for a job that makes its
            # own environment (install-image.sh alone does not: check F-09.job-venv, gap G-0413)
            whl = os.environ.get("EXAM_WHEEL", "")
            rc, out = ctx.sh("pip-engine", pip + ["--no-deps", whl], cwd=d) if whl else (1, "EXAM_WHEEL unset")
            if rc != 0:
                raise Skip(f"engine install into the venv failed: {out[-300:]}")
        ctx._venvs[k] = v
    return {"PATH": f"{v / 'bin'}:{os.environ.get('PATH', '')}", "VIRTUAL_ENV": str(v),
            "PYTHONPATH": str(PLUGINS), "PYTHONDONTWRITEBYTECODE": None}


def pip(ctx: Ctx, d: Path, env: dict, pkgs: list[str]):
    rc, out = ctx.sh("pip-extra", ["python", "-m", "pip", "install", "-q", "--disable-pip-version-check"] + pkgs,
                     cwd=d, env=env, timeout=1800)
    if rc != 0:
        raise Skip(f"pip install {pkgs} failed: {out[-300:]}")


def load_json(p) -> dict:
    try:
        with open(p) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def pytest_plain(ctx: Ctx, d: Path, env: dict, args: list[str], tag: str, extra_env=None) -> tuple:
    """Plain pytest (engine plugin off): outcome map through the exam's own plugin."""
    out_p = ctx.work / f"plain-{tag}-{ctx._n + 1}.json"
    e = dict(env, EXAM_OUTCOMES=str(out_p), **(extra_env or {}))
    rc, out = ctx.sh(f"plain-{tag}", ["python", "-m", "pytest", "-p", "no:detpy", "-p", "exam_outcomes",
                                      "-p", "no:cacheprovider", "-q"] + args, cwd=d, env=e)
    return rc, out, load_json(out_p).get("outcomes", {})


def pytest_engine(ctx: Ctx, d: Path, env: dict, args: list[str], tag: str, extra_env=None) -> tuple:
    """`fenvix python ...` with the engine's own outcome map (--det-outcomes)."""
    out_p = ctx.work / f"eng-{tag}-{ctx._n + 1}.json"
    e = dict(env, **(extra_env or {}))
    rc, out = ctx.sh(f"fenvix-{tag}", ["fenvix", "python", "-q", "-p", "no:cacheprovider",
                                       f"--det-outcomes={out_p}"] + args, cwd=d, env=e)
    return rc, out, load_json(out_p).get("outcomes", {})


def reused_count(out: str) -> int:
    m = re.findall(r"reused (\d+) result", out)
    if m:
        return sum(int(x) for x in m)
    m = re.findall(r"reused[:= ]+(\d+)", out)
    return sum(int(x) for x in m) if m else 0


def cmp_outcomes(eng: dict, plain: dict) -> tuple:
    if not plain:
        return False, "plain run produced no outcomes"
    if not eng:
        return False, "engine run produced no outcome map"
    missing = sorted(set(plain) - set(eng))
    extra = sorted(set(eng) - set(plain))
    diff = sorted(k for k in set(eng) & set(plain) if norm(eng[k]) != norm(plain[k]))
    ok = not missing and not diff
    desc = (f"{len(eng)} engine / {len(plain)} plain outcomes; differing {len(diff)} {diff[:5]}; "
            f"missing in engine {len(missing)} {missing[:3]}; extra {len(extra)}")
    return ok, desc


def norm(o) -> str:
    o = str(o).lower()
    return {"pass": "passed", "ok": "passed", "fail": "failed", "skip": "skipped", "error": "failed",
            "xfailed": "skipped", "xpassed": "passed", "todo": "skipped", "pending": "skipped"}.get(o, o)


def verify(ctx: Ctx, d: Path, env: dict, t1, t2, tag="verify") -> tuple:
    """`fenvix verify --json T1 T2` -> (identical?, summary, report)."""
    if not (os.path.exists(t1) and os.path.exists(t2)):
        return False, f"trace missing ({os.path.exists(t1)}, {os.path.exists(t2)})", {}
    rc, out = ctx.sh(tag, ["fenvix", "verify", "--json", str(t1), str(t2)], cwd=d, env=env)
    rep = {}
    for line in out.splitlines():
        if line.startswith("{"):
            try:
                rep = json.loads(line)
                break
            except ValueError:
                pass
    s = rep.get("summary", {})
    ok = rc == 0 and s.get("diverged", 1) == 0 and s.get("missing", 1) == 0 and s.get("tests", 0) > 0
    return ok, f"rc={rc} summary={json.dumps(s)[:400]}", rep


def first_divergence(rep: dict) -> list:
    out = []
    for t in rep.get("tests", []):
        if t.get("divergence"):
            out.append({"test": t.get("nodeid") or t.get("id"), "divergence": t["divergence"]})
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Node environments
# ---------------------------------------------------------------------------------------------------------------------

def npm_install(ctx: Ctx, d: Path, pm="npm", extra: list | None = None, env=None):
    key = f"node:{d}:{pm}"
    if key in ctx._venvs:
        return
    if pm.startswith("yarn"):
        drop_package_manager(d)
    if pm == "npm":
        cmd = "npm ci --no-audit --no-fund --ignore-scripts || npm install --no-audit --no-fund --ignore-scripts"
    elif pm == "pnpm":
        cmd = "pnpm install --ignore-scripts --no-frozen-lockfile"
    elif pm == "yarn-classic":
        cmd = "yarn install --ignore-scripts --non-interactive"
    elif pm == "yarn-berry":
        cmd = ("corepack enable && yarn set version stable && yarn config set nodeLinker node-modules && "
               "YARN_ENABLE_IMMUTABLE_INSTALLS=false yarn install")
    elif pm == "bun":
        cmd = "bun install"
    else:
        raise ValueError(pm)
    rc, out = ctx.sh(f"{pm}-install", cmd, cwd=d, env=env, timeout=1800)
    if rc != 0:
        raise Skip(f"{pm} install failed: {out[-500:]}")
    if extra:
        add = {"npm": "npm install --no-audit --no-fund --ignore-scripts -D", "pnpm": "pnpm add -D",
               "yarn-classic": "yarn add -D", "yarn-berry": "yarn add -D", "bun": "bun add -d"}[pm]
        rc, out = ctx.sh(f"{pm}-extra", f"{add} {' '.join(extra)}", cwd=d, env=env, timeout=1800)
        if rc != 0:
            raise Skip(f"{pm} add {extra} failed: {out[-500:]}")
    ctx._venvs[key] = d


def drop_package_manager(d: Path):
    """A project pinned to another manager (`packageManager` field) as a yarn user would have it: without the pin."""
    p = d / "package.json"
    try:
        j = json.loads(p.read_text())
    except (OSError, ValueError):
        return
    if j.pop("packageManager", None) is not None:
        p.write_text(json.dumps(j, indent=2))


def node_engine_env(ctx: Ctx) -> dict:
    ctx.need_install()
    return {}


def detjs_receipts(d: Path, reused_only=False) -> tuple:
    """Per-test outcomes and reuse count from the engine's receipts (.detjs/receipts.jsonl)."""
    rec = d / ".detjs" / "receipts.jsonl"
    o, n = {}, 0
    if rec.exists():
        for line in rec.read_text(errors="replace").splitlines():
            try:
                x = json.loads(line)
            except ValueError:
                continue
            nid = str(x.get("id") or x.get("nodeid") or x.get("test") or x.get("file") or "")
            if not nid or (reused_only and not x.get("reused")):
                continue
            o[nid] = x.get("outcome")
            n += bool(x.get("reused")) and x.get("kind") != "file"
    return o, n


def counts(out: str) -> dict:
    """Pass/fail counts from a runner's summary (Vitest, Jest, Mocha, node:test, AVA, tap, uvu, Jasmine, Bun, Deno)."""
    c = {}
    m = re.findall(r"# \{ total: (\d+), pass: (\d+)(?:, fail: (\d+))?", out)  # tap 18+
    if m:
        return {"passed": int(m[-1][1]), "failed": int(m[-1][2] or 0)}
    bp = re.findall(r"^\s*(\d+) pass$", out, re.M)  # bun: one summary per process
    if bp:
        bf = re.findall(r"^\s*(\d+) fail$", out, re.M)
        return {"passed": sum(map(int, bp)), "failed": sum(map(int, bf))}
    pats = {
        "passed": [r"Tests?\s+(\d+) passed", r"Tests:.*?(\d+) passed", r"(\d+) passing", r"# pass\s+(\d+)",
                   r"(\d+) tests? passed", r"Passed:\s+(\d+)", r"(\d+) pass\b", r"ok \| (\d+) passed",
                   r"(\d+) specs?, 0 failures"],
        "failed": [r"Tests?\s+.*?(\d+) failed", r"Tests:.*?(\d+) failed", r"(\d+) failing", r"# fail\s+(\d+)",
                   r"(\d+) tests? failed", r"Failed:\s+(\d+)", r"(\d+) fail\b", r"(\d+) failed \|",
                   r"\d+ specs?, (\d+) failures?"],
    }
    for k, ps in pats.items():
        for p in ps:
            m = re.findall(p, out)
            if m:
                c[k] = int(m[-1])
                break
    return c


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
