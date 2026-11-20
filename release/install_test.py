#!/usr/bin/env python3
"""Install test: only the built packages, no checkout of the engine (.github/workflows/packages.yml, job install).

    python3 install_test.py --wheels DIR --npm DIR --version X.Y.Z --work DIR [--py311 PATH] --out result.json

DIR (--wheels) holds the wheels (and the sdist) built by CI; DIR (--npm) the `npm pack` tarballs of `fenvix` and
the `@fenvix/<platform>` packages. In a fresh virtual environment and a fresh Node project it:

  1. installs `fenvix` from a local package index (PEP 503, with data-requires-python as PyPI serves it) and the
     npm tarballs, checks `fenvix --version` (both commands) and `fenvix doctor`;
  2. runs `pytest --det` twice on a small real Python project (traces verified identical) and `--det-cache` twice
     (the second run reuses tests, no outcome differs);
  3. runs `fenvix vitest run --det` twice on a small real Vitest project (traces verified) and `--det-cache`
     twice (the second run reuses);
  4. with --py311: on CPython 3.11, pip refuses the package with the Requires-Python message, and a copy forced
     into that interpreter refuses `pytest --det` and `python -m detpy` at start (exit 4, one sentence).

Exit code 0 only when every check passed; every command and its output go to --work/logs.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Small real projects, pinned (DECLARED choice).
PY_PROJECT = {"url": "https://github.com/pallets/itsdangerous", "ref": "2.2.0", "tests": "tests",
              "extra": ["freezegun"]}
VITEST_PROJECT = {"url": "https://github.com/unjs/ufo", "ref": "v1.6.1"}

BIN = "Scripts" if os.name == "nt" else "bin"


class Run:
    def __init__(self, work):
        self.work = os.path.abspath(work)
        self.logs = os.path.join(self.work, "logs")
        os.makedirs(self.logs, exist_ok=True)
        self.steps, self.checks = [], {}

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


def serve_index(wheels: str, root: str) -> tuple[str, ThreadingHTTPServer]:
    """A PEP 503 index of the local files, with data-requires-python from each file's metadata (as PyPI)."""
    d = os.path.join(root, "simple", "fenvix")
    os.makedirs(d, exist_ok=True)
    links = []
    for f in sorted(os.listdir(wheels)):
        if not (f.endswith(".whl") or f.endswith(".tar.gz")):
            continue
        shutil.copy(os.path.join(wheels, f), d)
        rp = ""
        if f.endswith(".whl"):
            with zipfile.ZipFile(os.path.join(wheels, f)) as z:
                meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
                m = re.search(r"^Requires-Python: (.+)$", z.read(meta).decode(), re.M)
                rp = m.group(1).strip() if m else ""
        else:
            rp = ">=3.12"  # same metadata as the wheels (pyproject.toml)
        links.append(f'<a href="{f}" data-requires-python="{html.escape(rp)}">{f}</a>')
    open(os.path.join(d, "index.html"), "w").write("<html><body>\n" + "\n".join(links) + "\n</body></html>\n")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/simple", srv


def pip_install(r, name, py, index, extra):
    return r.sh(name, [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--index-url", index,
                       "--extra-index-url", "https://pypi.org/simple", "--only-binary", "fenvix", "fenvix", *extra])


def python_part(r, a, index):
    venv = os.path.join(r.work, "venv")
    r.sh("venv", [sys.executable, "-m", "venv", venv])
    py = os.path.join(venv, BIN, "python")
    fx = os.path.join(venv, BIN, "fenvix")
    rc, _ = pip_install(r, "pip-install-fenvix", py, index, ["pytest-xdist"])
    r.check("pip_install", rc == 0)
    rc, out = r.sh("fenvix-version", [fx, "--version"])
    r.check("fenvix_version_python", rc == 0 and out.strip() == f"fenvix {a.version}", out.strip())
    rc, out = r.sh("fenvix-doctor", [fx, "doctor"])
    r.check("fenvix_doctor", rc == 0, out.strip())

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
        r.check(f"py_det_run{i}", rc == 0 and " passed" in out, out.strip().splitlines()[-1:] if out else "")
        traces.append(t)
    rc, out = r.sh("py-verify", [fx, "verify", *traces])
    r.check("py_det_traces_identical", rc == 0, out.strip().splitlines()[-1:] if out else "")
    cache = os.path.join(r.work, "py-cache")
    outs = []
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


def node_part(r, a):
    proj = os.path.join(r.work, "vitestproj")
    r.sh("vitest-clone", ["git", "clone", "-q", "--depth", "1", "--branch", VITEST_PROJECT["ref"], VITEST_PROJECT["url"], proj])
    rc, _ = r.sh("vitest-project-install", "npm install --no-audit --no-fund --ignore-scripts --no-package-lock", cwd=proj)
    r.check("vitest_project_installed", rc == 0)
    tarballs = sorted(glob.glob(os.path.join(os.path.abspath(a.npm), "*.tgz")))
    rc, out = r.sh("npm-install-fenvix", ["npm", "install", "--no-audit", "--no-fund", "--no-save", "--no-package-lock",
                                          *tarballs], cwd=proj)
    r.check("npm_install", rc == 0, out.strip().splitlines()[-1:] if out else "")
    rc, out = r.sh("npx-fenvix-version", ["npx", "--no-install", "fenvix", "--version"], cwd=proj)
    r.check("fenvix_version_node", rc == 0 and out.strip() == f"fenvix {a.version}", out.strip())
    traces = []
    for i in (1, 2):
        t = os.path.join(r.work, f"vitest-det{i}.jsonl")
        rc, out = r.sh(f"vitest-det{i}", ["npx", "--no-install", "fenvix", "vitest", "run", "--det", f"--det-trace={t}"], cwd=proj)
        r.check(f"vitest_det_run{i}", rc == 0 and os.path.exists(t), out.strip().splitlines()[-1:] if out else "")
        traces.append(t)
    rc, out = r.sh("vitest-verify", ["npx", "--no-install", "fenvix", "verify", *traces], cwd=proj)
    r.check("vitest_det_traces_identical", rc == 0, out.strip().splitlines()[-1:] if out else "")
    cache = os.path.join(r.work, "vitest-cache")
    for i in (1, 2):
        rc, out = r.sh(f"vitest-cache{i}", ["npx", "--no-install", "fenvix", "vitest", "run", "--det", f"--det-cache={cache}"], cwd=proj)
    m = re.search(r"reused (\d+)", out)
    r.check("vitest_cache_reused", rc == 0 and m and int(m.group(1)) > 0, m.group(0) if m else out.strip()[-300:])


def old_python_part(r, a, index, py311):
    venv = os.path.join(r.work, "venv311")
    r.sh("venv311", [py311, "-m", "venv", venv])
    py = os.path.join(venv, BIN, "python")
    rc, out = r.sh("pip311-install-fenvix", [py, "-m", "pip", "install", "--disable-pip-version-check", "--index-url",
                                             index, "fenvix"])
    r.check("py311_pip_refuses", rc != 0 and "Requires-Python >=3.12" in out, out.strip().splitlines()[:2])
    # a copy forced past pip (copied site-packages): refused at start, never a crash
    r.sh("pip311-pytest", [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "pytest"])
    site = subprocess.check_output([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
    whl = sorted(glob.glob(os.path.join(a.wheels, "fenvix-*.whl")))[0]
    zipfile.ZipFile(whl).extractall(site)
    proj = os.path.join(r.work, "p311")
    os.makedirs(proj, exist_ok=True)
    open(os.path.join(proj, "test_a.py"), "w").write("def test_a():\n    assert 1\n")
    rc, out = r.sh("py311-pytest-det", [py, "-m", "pytest", "-q", "--det", "test_a.py"], cwd=proj)
    r.check("py311_pytest_det_refused", rc == 4 and "needs CPython 3.12" in out and "Traceback" not in out, out.strip()[-300:])
    rc, out = r.sh("py311-python-m-detpy", [py, "-m", "detpy", "unittest", "--det"], cwd=proj)
    r.check("py311_python_m_detpy_refused", rc == 4 and "needs CPython 3.12" in out and "Traceback" not in out, out.strip()[-300:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheels", required=True)
    ap.add_argument("--npm", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--py311", default=None)
    ap.add_argument("--skip-node", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    a.wheels = os.path.abspath(a.wheels)
    r = Run(a.work)
    index, srv = serve_index(a.wheels, os.path.join(r.work, "index"))
    try:
        python_part(r, a, index)
        if not a.skip_node:
            node_part(r, a)
        if a.py311:
            old_python_part(r, a, index, a.py311)
    finally:
        srv.shutdown()
    ok = all(c["ok"] for c in r.checks.values()) and bool(r.checks)
    json.dump({"ok": ok, "platform": sys.platform, "python": sys.version.split()[0],
               "projects": {"python": PY_PROJECT, "vitest": VITEST_PROJECT},
               "checks": r.checks, "steps": r.steps}, open(a.out, "w"), indent=2)
    print("install test:", "PASSED" if ok else "FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
