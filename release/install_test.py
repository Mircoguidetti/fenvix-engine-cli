#!/usr/bin/env python3
"""Install test of the engine artifact, in a clean container, without a checkout of the engine
(.github/workflows/release-1.yml, job `install`).

    python3 install_test.py --artifact fenvix-engine-<v>-<b>-linux-x86_64.tar.gz --python PY --work DIR --out result.json
    python3 install_test.py --artifact ... --refuse --python PY311 --work DIR --out result.json

Default mode: checks the artifact against its .sha256, unpacks it, runs its install.sh into a fresh virtual
environment of PY and a fresh prefix, checks `fenvix --version` (Python command and Node shell) `fenvix doctor --install` (and records the full `fenvix doctor`),
then on small real projects pinned to a tag:
  * Python: `pytest --det` twice (traces verified identical by `fenvix verify`) and `--det-cache` twice (the second
    run reuses tests with proof and no outcome differs);
  * Vitest: `fenvix node vitest run --det` twice (traces verified) and `--det-cache` twice (the second run reuses).
--refuse (CPython 3.11): install.sh exits 4 with one sentence; a copy of the wheel forced into that interpreter
refuses `pytest --det` and `python -m detpy` at start (exit 4, one sentence, no traceback).
Exit code 0 only when every check passed; every command and its output go to --work/logs.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import zipfile

# Small real projects, pinned (DECLARED choice).
PY_PROJECT = {"url": "https://github.com/pallets/itsdangerous", "ref": "2.2.0", "tests": "tests", "extra": ["freezegun"]}
VITEST_PROJECT = {"url": "https://github.com/unjs/ufo", "ref": "v1.6.1"}


class Run:
    def __init__(self, work):
        self.work = os.path.abspath(work)
        self.logs = os.path.join(self.work, "logs")
        os.makedirs(self.logs, exist_ok=True)
        self.steps, self.checks, self.doctor = [], {}, None

    def sh(self, name, cmd, cwd=None, env=None, timeout=1800):
        t = time.time()
        e = dict(os.environ, **(env or {}))
        e.pop("PYTHONPATH", None)
        try:
            p = subprocess.run(cmd, cwd=cwd or self.work, env=e, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout, shell=isinstance(cmd, str))
            rc, out = p.returncode, p.stdout
        except subprocess.TimeoutExpired as x:
            rc, out = "timeout", str(x.stdout or "")
        open(os.path.join(self.logs, f"{name}.log"), "w").write(out)
        self.steps.append({"name": name, "cmd": cmd, "rc": rc, "seconds": round(time.time() - t, 1)})
        print(f"== {name}: rc={rc} ({time.time() - t:.1f}s)\n" + "\n".join(out.splitlines()[-12:]), flush=True)
        return rc, out

    def check(self, name, ok, detail=""):
        self.checks[name] = {"ok": bool(ok), "detail": str(detail)[:500]}
        print(f"-- check {name}: {'OK' if ok else 'FAILED'} {str(detail)[:300]}", flush=True)


def last(out):
    return out.strip().splitlines()[-1:] if out and out.strip() else ""


def unpack(r, a) -> str:
    """Verify the checksum, unpack, return the artifact directory."""
    data = open(a.artifact, "rb").read()
    want = open(a.artifact + ".sha256").read().split()[0]
    got = hashlib.sha256(data).hexdigest()
    r.check("artifact_sha256", got == want, f"{got} vs {want}")
    dest = os.path.join(r.work, "artifact")
    with tarfile.open(a.artifact) as t:
        t.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(dest)
    (d,) = glob.glob(os.path.join(dest, "fenvix-engine-*"))
    meta = json.load(open(os.path.join(d, "VERSION.json")))
    r.check("artifact_layout", all(os.path.exists(os.path.join(d, p)) for p in
                                   ("install.sh", "bin/fenvix", "node/bin/fenvix.js", "node/detjs.linux-x64.node"))
            and len(glob.glob(os.path.join(d, "wheels", "fenvix-*-manylinux_2_28_x86_64.whl"))) == 1, d)
    bad = [p for p, h in meta["files"].items()
           if hashlib.sha256(open(os.path.join(d, p), "rb").read()).hexdigest() != h]
    r.check("artifact_files_match_manifest", not bad, bad[:5])
    a.version = meta["version"]
    return d


def install(r, a, d):
    venv = os.path.join(r.work, "venv")
    r.sh("venv", [a.python, "-m", "venv", venv])
    py = os.path.join(venv, "bin", "python")
    if a.pytest:  # a pinned pytest before the engine: install.sh keeps it when it satisfies pytest>=8.1
        rc, _ = r.sh("pytest-pin", [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", a.pytest])
        r.check("pytest_pinned", rc == 0, a.pytest)
    home = os.path.join(r.work, "fenvix-home")
    rc, out = r.sh("install-sh", ["bash", os.path.join(d, "install.sh"), home], env={"PYTHON": py})
    r.check("install_sh", rc == 0, last(out))
    fx = os.path.join(venv, "bin", "fenvix")
    rc, out = r.sh("fenvix-version", [fx, "--version"])
    first = out.strip().splitlines()[0] if out.strip() else ""
    r.check("fenvix_version_python", rc == 0 and first.startswith(f"fenvix {a.version} "), first)
    rc, out = r.sh("fenvix-doctor-install", [fx, "doctor", "--install"])
    r.check("fenvix_doctor_install", rc == 0, out.strip())
    # every control of a deterministic run on this machine (ASLR switch, locale, strace, ...): what a container of
    # this image gives, recorded in the report; the installation itself is the check above
    rc, out = r.sh("fenvix-doctor", [fx, "doctor", "--json"])
    try:
        r.doctor = json.loads(out)
    except ValueError:
        r.doctor = out.strip()[-500:]
    rc, out = r.sh("pytest-version", [py, "-m", "pytest", "--version"])
    r.check("pytest_version", rc == 0 and (not a.pytest or out.split()[-1].startswith(a.pytest.split("==")[1].rstrip("*"))),
            out.strip())
    return py, fx, home


def python_part(r, py, fx):
    proj = os.path.join(r.work, "pyproj")
    r.sh("py-clone", ["git", "clone", "-q", "--depth", "1", "--branch", PY_PROJECT["ref"], PY_PROJECT["url"], proj])
    rc, _ = r.sh("py-project-install", [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", ".",
                                        *PY_PROJECT["extra"]], cwd=proj)
    r.check("py_project_installed", rc == 0)
    traces = []
    for i in (1, 2):
        t = os.path.join(r.work, f"py-det{i}.jsonl")
        rc, out = r.sh(f"py-det{i}", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det", f"--det-trace={t}",
                                      PY_PROJECT["tests"]], cwd=proj)
        r.check(f"py_det_run{i}", rc == 0 and " passed" in out, last(out))
        traces.append(t)
    rc, out = r.sh("py-verify", [fx, "verify", *traces])
    r.check("py_det_traces_identical", rc == 0, last(out))
    cache = os.path.join(r.work, "py-cache")
    outs, reused = [], 0
    for i in (1, 2):
        o = os.path.join(r.work, f"py-outcomes{i}.json")
        rc, out = r.sh(f"py-cache{i}", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det",
                                        f"--det-cache={cache}", f"--det-outcomes={o}", PY_PROJECT["tests"]], cwd=proj)
        outs.append((json.load(open(o)).get("outcomes") or {}) if os.path.exists(o) else {})
        m = re.search(r"reused (\d+) result", out)
        reused = int(m.group(1)) if m else 0
    diff = sorted(k for k in set(outs[0]) & set(outs[1]) if outs[0][k] != outs[1][k])
    r.check("py_cache_reused", reused > 0, f"{reused} reused in the second run")
    r.check("py_cache_same_outcomes", not diff and len(outs[1]) >= len(outs[0]) > 0, f"{len(outs[0])} outcomes; differing {diff[:5]}")


def node_part(r, a, fx, home):
    env = {"FENVIX_HOME": home}
    rc, out = r.sh("fenvix-node-version", [fx, "node", "--version"], env=env)
    r.check("fenvix_version_node", rc == 0 and out.strip() == f"fenvix {a.version}", out.strip())
    proj = os.path.join(r.work, "vitestproj")
    r.sh("vitest-clone", ["git", "clone", "-q", "--depth", "1", "--branch", VITEST_PROJECT["ref"], VITEST_PROJECT["url"], proj])
    rc, _ = r.sh("vitest-project-install", "npm install --no-audit --no-fund --ignore-scripts --no-package-lock", cwd=proj)
    r.check("vitest_project_installed", rc == 0)
    traces = []
    for i in (1, 2):
        t = os.path.join(r.work, f"vitest-det{i}.jsonl")
        rc, out = r.sh(f"vitest-det{i}", [fx, "node", "vitest", "run", "--det", f"--det-trace={t}"], cwd=proj, env=env)
        r.check(f"vitest_det_run{i}", rc == 0 and os.path.exists(t), last(out))
        traces.append(t)
    rc, out = r.sh("vitest-verify", [fx, "verify", *traces])
    r.check("vitest_det_traces_identical", rc == 0, last(out))
    cache = os.path.join(r.work, "vitest-cache")
    for i in (1, 2):
        rc, out = r.sh(f"vitest-cache{i}", [fx, "node", "vitest", "run", "--det", f"--det-cache={cache}"], cwd=proj, env=env)
    m = re.search(r"reused with proof (\d+) tests", out)  # detjs: "reused with proof N tests in M files"
    r.check("vitest_cache_reused", rc == 0 and bool(m) and int(m.group(1)) > 0, m.group(0) if m else out.strip()[-300:])


def refuse_part(r, a, d):
    venv = os.path.join(r.work, "venv-old")
    r.sh("venv-old", [a.python, "-m", "venv", venv])
    py = os.path.join(venv, "bin", "python")
    rc, out = r.sh("install-sh-old", ["bash", os.path.join(d, "install.sh"), os.path.join(r.work, "home-old")],
                   env={"PYTHON": py})
    r.check("install_refuses_old_python", rc == 4 and "needs CPython 3.12" in out and "Traceback" not in out, out.strip())
    # a copy forced past the installer (copied site-packages): refused at start, never a crash
    r.sh("pip-pytest-old", [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "pytest"])
    site = subprocess.check_output([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
    zipfile.ZipFile(glob.glob(os.path.join(d, "wheels", "fenvix-*.whl"))[0]).extractall(site)
    proj = os.path.join(r.work, "p-old")
    os.makedirs(proj, exist_ok=True)
    open(os.path.join(proj, "test_a.py"), "w").write("def test_a():\n    assert 1\n")
    rc, out = r.sh("old-pytest-det", [py, "-m", "pytest", "-q", "--det", "test_a.py"], cwd=proj)
    r.check("old_pytest_det_refused", rc == 4 and "needs CPython 3.12" in out and "Traceback" not in out, out.strip()[-300:])
    rc, out = r.sh("old-plain-pytest", [py, "-m", "pytest", "-q", "test_a.py"], cwd=proj)
    r.check("old_plain_pytest_unchanged", rc == 0 and "1 passed" in out, last(out))
    rc, out = r.sh("old-python-m-detpy", [py, "-m", "detpy", "unittest", "--det"], cwd=proj)
    r.check("old_python_m_detpy_refused", rc == 4 and "needs CPython 3.12" in out and "Traceback" not in out, out.strip()[-300:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--work", required=True)
    ap.add_argument("--refuse", action="store_true", help="the interpreter is unsupported: check the refusals only")
    ap.add_argument("--pytest", default=None, help="a pytest requirement installed first (e.g. pytest==8.1.*)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    a.artifact = os.path.abspath(a.artifact)
    r = Run(a.work)
    d = unpack(r, a)
    if a.refuse:
        refuse_part(r, a, d)
    else:
        py, fx, home = install(r, a, d)
        python_part(r, py, fx)
        node_part(r, a, fx, home)
    ok = all(c["ok"] for c in r.checks.values()) and bool(r.checks)
    json.dump({"ok": ok, "python": a.python, "artifact": os.path.basename(a.artifact),
               "projects": {"python": PY_PROJECT, "vitest": VITEST_PROJECT},
               "checks": r.checks, "doctor": r.doctor, "steps": r.steps}, open(a.out, "w"), indent=2)
    print("install test:", "PASSED" if ok else "FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
