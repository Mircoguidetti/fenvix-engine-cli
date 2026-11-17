#!/usr/bin/env python3
"""Skip-with-proof study 2: walk a sequence of commits of a large repository and simulate a test
result cache keyed on what every test unit actually read.

Unit = one test file (pytest, vitest) run in its own process, or one Go package. At every commit:

1. check out, reinstall when a dependency spec changed, run the build step;
2. for every unit, compare its dependency record (taken at its last real run) with the tree now:
   * ``closure`` (proof, file level): a file it read changed or vanished (read-write opens of existing files
     included), a path it found missing now exists, a path it stat'ed vanished, a directory it listed
     (outside discovery) changed entries, a module name it looked up is now provided by an added file, a new
     pytest plugin entry point, an environment variable it read changed, the runtime identity changed
     (interpreter / Node binary / standard library / tzdata / system libraries); never when the unit
     connected to a non-loopback address or to a loopback HTTP(S) proxy (R-002b), and never when its cached
     outcome is a failure (R-002 fixes);
   * ``func+guard`` (Python, proof at the Python level): ``closure``, except that a changed repository
     ``.py`` file whose module-level skeleton is unchanged only forces a rerun when a function whose
     definition changed was executed by the unit;
   * ``func`` (Python, coverage-only, NOT a proof): only executed functions and the unit's own file;
   * ``strict`` (closure plus the first study's rule: any config/CI/lock file change reruns all);
   * ``go-cache`` (Go): the go command's own test cache, persisted across commits (remote cache from
     cold CI). NOT a proof: reported as "go test cache (no proof)". Go ``closure`` = go-cache hit (its key
     covers the Go files, the files opened through package os inside the module and the environment
     variables read through os.Getenv / os.LookupEnv, from go's test log) AND no runtime read changed
     (strace) AND no non-loopback connect() and no connect() to a loopback HTTP(S) proxy AND the same
     runtime identity.
3. run every unit ``closure`` cannot skip, under strace (plus the Python / Node hooks), and a random sample of
   the skippable ones (verification: the cached outcome must equal the fresh one); a unit that ``closure``
   reruns but another rule would have skipped is compared with its cached outcome too (``xverify``);
4. write per-transition decisions, costs and verification results.

    python harness/skip_study2/walk.py --spec spec.json --work /tmp/w --out results/x.json
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from strace_deps import external, traced  # noqa: E402
from pyskel import changed_functions, top_qualname  # noqa: E402

PYHOOKS = HERE / "pyhooks"
NODEHOOK = HERE / "nodehooks" / "envrec.cjs"
# variables read below the hooks (C runtime, interpreter start-up): always part of the key. A trailing "*" is a
# prefix. Values are hashed, never stored.
ALWAYS_ENV = {"pytest": ("PATH", "TZ", "LANG", "LANGUAGE", "LC_*", "PYTHON*"),
              "vitest": ("PATH", "TZ", "LANG", "LANGUAGE", "LC_*", "NODE_*", "UV_*"),
              "go": ("PATH", "TZ", "LANG", "LANGUAGE", "LC_*")}
HARNESS_ENV = ("S2_",)  # the harness's own per-run variables


def env_value(name, env):
    """Hash of what the environment gives for ``name``: a variable, a prefix pattern (``LC_*``), the whole
    environment (``*``) or the proxy variables (``~proxy``). None when unset."""
    if name == "*":
        items = sorted((k, v) for k, v in env.items() if not k.startswith(HARNESS_ENV))
    elif name == "~proxy":
        items = sorted((k, v) for k, v in env.items() if k.lower().endswith("_proxy"))
    elif name.endswith("*"):
        items = sorted((k, v) for k, v in env.items() if k.startswith(name[:-1]) and not k.startswith(HARNESS_ENV))
    else:
        v = env.get(name)
        return None if v is None else hashlib.sha1(v.encode("utf-8", "surrogateescape")).hexdigest()[:12]
    return hashlib.sha1(repr(items).encode("utf-8", "surrogateescape")).hexdigest()[:12]


def _sha_file(p, h=None):
    h = h or hashlib.sha1()
    try:
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
    except OSError:
        h.update(b"<unreadable>")
    return h


def _tree_hash(root, skip_dirs=("site-packages", "dist-packages", "__pycache__", "test", "tests", "idlelib",
                                "tkinter", "turtledemo", "ensurepip")):
    """Content hash of a directory tree (relative path + bytes of every file)."""
    h = hashlib.sha1()
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in skip_dirs)
        for f in sorted(files):
            if f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            h.update(os.path.relpath(p, root).encode() + b"\0")
            _sha_file(p, h)
    return h.hexdigest()[:16]


def _linked_libs(binary):
    try:
        out = subprocess.run(["ldd", binary], capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return []
    libs = []
    for line in out.splitlines():
        m = re.search(r"=>\s*(/\S+)", line) or re.match(r"\s*(/\S+)", line)
        if m:
            libs.append(os.path.realpath(m.group(1)))
    return sorted(set(libs))


def runtime_identity(lang, env, venv=None):
    """{component: hash} of what runs the tests besides the repository and its installed packages (R-002 fix 5):
    interpreter path + version + binary, standard library content, Node binary, Go toolchain, tzdata, and the
    shared libraries the interpreter links (libc, libssl, ...). Changes on the runner image invalidate."""
    ident = {}
    bins = []
    if lang == "pytest":
        py = str(Path(venv) / "bin" / "python")
        code, out, _ = sh([py, "-c", "import os,sys,sysconfig;print(os.path.realpath(sys.executable));"
                           "print(sys.version);print(sysconfig.get_paths()['stdlib']);"
                           "print(sysconfig.get_config_var('LIBDIR') or '');print(sysconfig.get_config_var('LDLIBRARY') or '')"],
                          env=env, timeout=120)
        lines = out.splitlines()
        if code == 0 and len(lines) >= 3:
            exe, ver, stdlib = lines[0], lines[1], lines[2]
            ident["python"] = hashlib.sha1((exe + "\0" + ver).encode() + _sha_file(exe).digest()).hexdigest()[:16]
            ident["stdlib"] = _tree_hash(stdlib)
            bins.append(exe)
            if len(lines) >= 5 and lines[4]:
                lib = os.path.join(lines[3], lines[4])
                if os.path.exists(lib):
                    ident["libpython"] = _sha_file(lib).hexdigest()[:16]
        else:
            ident["python"] = "unknown:" + out[-200:]
    elif lang in ("vitest", "jest"):
        node = shutil.which("node", path=env.get("PATH"))
        if node:
            node = os.path.realpath(node)
            _, ver, _ = sh([node, "--version"], env=env, timeout=60)
            ident["node"] = hashlib.sha1((node + "\0" + ver.strip()).encode() + _sha_file(node).digest()).hexdigest()[:16]
            bins.append(node)
        else:
            ident["node"] = "missing"
    elif lang == "go":
        _, out, _ = sh(["go", "env", "GOVERSION", "GOROOT"], env=env, timeout=120)
        ident["go"] = hashlib.sha1(out.encode()).hexdigest()[:16]
    tz = [p for p in ("/usr/share/zoneinfo/tzdata.zi", "/etc/localtime") if os.path.exists(p)]
    h = hashlib.sha1()
    for p in tz:
        h.update(os.path.realpath(p).encode())
        _sha_file(p, h)
    ident["tzdata"] = h.hexdigest()[:16]
    libs = set()
    for b in bins:
        libs.update(_linked_libs(b))
    for name in ("libssl.so.3", "libcrypto.so.3"):
        for d in ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib"):
            if os.path.exists(os.path.join(d, name)):
                libs.add(os.path.realpath(os.path.join(d, name)))
                break
    h = hashlib.sha1()
    for p in sorted(libs):
        h.update(p.encode() + b"\0")
        _sha_file(p, h)
    ident["syslibs"] = h.hexdigest()[:16]
    return ident
T_START = time.time()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None, shell=False):
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, errors="replace",
                           timeout=timeout, shell=shell, stdin=subprocess.DEVNULL,
                           executable="/bin/bash" if shell else None)
        return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out + "\nTIMEOUT", time.perf_counter() - t0


def git(src, *args, check=True):
    p = subprocess.run(["git", *args], cwd=src, capture_output=True, text=True, errors="replace")
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr[-500:]}")
    return p.stdout


# ---------------------------------------------------------------------------
STRICT_CONFIG = ("uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock", "pyproject.toml", "setup.py", "setup.cfg",
                 "tox.ini", "pytest.ini", "conftest.py", "noxfile.py", "package.json", "pnpm-lock.yaml",
                 "yarn.lock", "package-lock.json", "pnpm-workspace.yaml", "go.mod", "go.sum", "go.work",
                 "go.work.sum", "Makefile", "vitest.config.ts", "vitest.config.mts", "vitest.config.js",
                 "vitest.workspace.ts", "jest.config.js", "jest.config.ts", "tsconfig.json", "babel.config.js",
                 ".nvmrc", ".python-version", "turbo.json", "nx.json", "lerna.json")


def strict_config_hit(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if base in STRICT_CONFIG or (base.startswith(("requirements", "constraints")) and base.endswith((".txt", ".in"))):
        return True
    if path.startswith((".github/workflows/", ".github/actions/", ".circleci/", ".gitlab-ci")):
        return True
    return base.startswith("tsconfig") and base.endswith(".json")


class Hasher:
    """Content hash per path, cached on (mtime_ns, size, ino)."""

    def __init__(self):
        self.cache = {}

    def file(self, p):
        try:
            st = os.stat(p)
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size, st.st_ino)
        c = self.cache.get(p)
        if c and c[0] == key:
            return c[1]
        if os.path.isdir(p):
            h = "dir"
        else:
            try:
                with open(p, "rb") as fh:
                    h = hashlib.sha1(fh.read()).hexdigest()[:16]
            except OSError:
                h = "unreadable"
        self.cache[p] = (key, h)
        return h

    @staticmethod
    def kind(p):
        try:
            return "d" if os.path.isdir(p) else "f"
        except OSError:
            return None

    @staticmethod
    def listing(d):
        try:
            names = sorted(n for n in os.listdir(d) if n != "__pycache__" and not n.endswith(".pyc"))
        except OSError:
            return None
        if d.endswith("site-packages"):
            # importable names + pytest plugin entry points; a plain version bump renames a dist-info dir
            # but changes neither (the bumped files themselves are compared as reads)
            imp = [n for n in names if not n.endswith((".dist-info", ".egg-info"))]
            eps = []
            for n in names:
                if n.endswith(".dist-info"):
                    try:
                        t = open(os.path.join(d, n, "entry_points.txt")).read()
                    except OSError:
                        continue
                    if "[pytest11]" in t:
                        sec = t.split("[pytest11]", 1)[1].split("\n[", 1)[0]
                        eps.append(sec.strip())
            names = imp + ["EP:" + e for e in sorted(eps)]
        return hashlib.sha1("\0".join(names).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
def pytest_section(text, rel):
    import configparser
    import tomllib
    try:
        if rel == "pyproject.toml":
            t = tomllib.loads(text).get("tool", {})
            return json.dumps({k: v for k, v in t.items() if k.startswith("pytest")}, sort_keys=True, default=str)
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_string(text)
        return json.dumps({s: dict(cp[s]) for s in cp.sections() if s in ("tool:pytest", "pytest")}, sort_keys=True)
    except Exception:
        return text


def outcome_summary(tests: dict) -> dict:
    """nodeid -> outcome class used to compare a cached result with a fresh one."""
    out = {}
    for k, v in tests.items():
        o = v[0] if isinstance(v, (list, tuple)) else v
        out[k] = "fail" if o in ("failed", "error", "fail") else ("pass" if o in ("passed", "pass", "xfailed") else o)
    return out


def parse_vitest(path):
    try:
        d = json.loads(Path(path).read_text())
    except Exception:
        return None
    tests = {}
    for f in d.get("testResults", []):
        for a in f.get("assertionResults", []):
            nid = " > ".join(a.get("ancestorTitles", []) + [a.get("title", "")])
            st = a.get("status")
            tests[nid] = ["passed" if st == "passed" else ("skipped" if st in ("pending", "skipped", "todo")
                                                         else "failed"), (a.get("duration") or 0) / 1000.0]
        if f.get("status") == "failed" and not f.get("assertionResults"):
            tests["<file>"] = ["error", 0.0]
        # vitest test durations exclude module loading and transforms; the file's own span includes them
        if f.get("startTime") and f.get("endTime"):
            tests["<file-span>"] = ["span", max(0.0, (f["endTime"] - f["startTime"]) / 1000.0)]
    return tests


class Walker:
    def __init__(self, spec, work, out, shard, nshards, budget_min, run_id):
        self.spec, self.work, self.out = spec, Path(work).resolve(), Path(out).resolve()
        self.shard, self.nshards, self.budget = shard, nshards, budget_min * 60
        self.run_id = run_id
        self.src = self.work / spec.get("src_dir", "src")  # market test: a layout path (Ansible collections)
        self.venv = self.work / "venv"
        self.rec_dir = self.work / "rec"
        self.rec_dir.mkdir(parents=True, exist_ok=True)
        self.hasher = Hasher()
        self.records = {}      # unit -> record of its last real run
        self.costs = {}        # unit -> plain cost (test seconds, wall seconds) from the baseline run
        self.lang = spec["lang"]
        self.workers = spec.get("workers", os.cpu_count() or 4)
        self.rng = random.Random(f"{spec['name']}-{shard}")
        self.result = {"spec": spec, "shard": shard, "nshards": nshards, "runner": os.environ.get("RUNNER_NAME", ""),
                       "cpus": os.cpu_count(), "commits": [], "transitions": [], "units": {}, "notes": []}
        self.dist_listing = {}  # commit idx -> site-packages names (python)
        self.added_cache = {}
        self._last_dep = None
        self.push = True
        self.cur_sha = None
        self._tracked = {}     # sha -> set of tracked paths (relative)
        self._runtime = None   # runtime identity, recomputed after every install

    # -- environment -------------------------------------------------------
    def env(self):
        e = dict(os.environ)
        for k in list(e):
            if k.startswith(("PYTEST_", "COV_", "VIRTUAL_ENV")):
                e.pop(k)
        e.update({k: self.fmt(v) for k, v in self.spec.get("env", {}).items()})
        if self.lang == "pytest":
            e["VIRTUAL_ENV"] = str(self.venv)
            e["PATH"] = f"{self.venv}/bin:" + e.get("PATH", "")
            e["PYTHONPATH"] = str(PYHOOKS) + (":" + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
            e["S2_ROOT"] = str(self.src)
            e["PYTHONHASHSEED"] = "0"
        elif self.lang in ("vitest", "jest"):
            req = f"--require {NODEHOOK}"
            if req not in e.get("NODE_OPTIONS", ""):
                e["NODE_OPTIONS"] = (e.get("NODE_OPTIONS", "") + " " + req).strip()
        e["CI"] = self.spec.get("ci_env", "true")  # market test: mlflow-dev measures the developer mode
        return e

    def runtime(self):
        if self._runtime is None:
            self._runtime = runtime_identity(self.lang, self.env(), self.venv)
        return self._runtime

    def tracked(self):
        """Paths tracked at the checked-out commit (relative to src)."""
        sha = self.cur_sha or "HEAD"
        if sha not in self._tracked:
            self._tracked = {sha: set(git(self.src, "ls-files", "-z", check=False).split("\0"))}
        return self._tracked[sha]

    def committed_hash(self, path):
        """Hash (Hasher format) of the committed content of a tracked file: its content before any test ran."""
        rel = os.path.relpath(path, self.src)
        p = subprocess.run(["git", "cat-file", "--filters", f"{self.cur_sha or 'HEAD'}:{rel}"], cwd=self.src,
                           capture_output=True)
        if p.returncode:
            return self.hasher.file(path)
        return hashlib.sha1(p.stdout).hexdigest()[:16]

    def fmt(self, s):
        return (s.replace("{src}", str(self.src)).replace("{venv}", str(self.venv)).replace("{work}", str(self.work))
                .replace("{py}", str(self.venv / "bin" / "python")).replace("{harness}", str(HERE)))

    def roots(self):
        r = [str(self.src)]
        if self.lang == "pytest":
            r.append(str(self.venv))
        for x in self.spec.get("roots", []):
            r.append(self.fmt(x))
        return r

    # -- commits -----------------------------------------------------------
    def commits(self):
        seq = self.spec["seq"]
        if not (self.src / ".git").exists():
            code, out, _ = sh(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", self.spec["url"],
                               str(self.src)], timeout=1800)
            if code:
                raise RuntimeError("clone failed: " + out[-500:])
        if seq["kind"] == "first-parent":
            head = seq.get("head") or git(self.src, "rev-parse", "origin/HEAD").strip()
            return git(self.src, "rev-list", "--first-parent", "-n", str(seq.get("n", 51)), head).split()[::-1]
        if seq["kind"] == "pr":
            n = seq["pr"]
            git(self.src, "fetch", "--quiet", "--filter=blob:none", "origin", f"pull/{n}/head:refs/s2/pr{n}")
            target = "origin/HEAD"
            if seq.get("base_sha"):  # the pull request's own base branch (not always the default branch)
                git(self.src, "fetch", "--quiet", "--filter=blob:none", "origin", seq["base_sha"], check=False)
                target = seq["base_sha"]
            base = seq.get("base") or git(self.src, "merge-base", target, f"refs/s2/pr{n}").strip()
            cs = git(self.src, "rev-list", "--reverse", "--first-parent", f"{base}..refs/s2/pr{n}").split()
            if seq.get("max") and len(cs) > seq["max"]:
                raise ValueError(f"PR {n}: {len(cs)} commits from the merge base (more than {seq['max']})")
            return [base] + cs
        if seq["kind"] == "list":
            return seq["commits"]
        raise ValueError(seq)

    def checkout(self, sha):
        git(self.src, "checkout", "--quiet", "--force", sha)
        self.cur_sha = sha
        git(self.src, "clean", "-qffd", "-e", ".s2rec", check=False)
        if self.lang == "go":
            time.sleep(2.1)  # go test refuses to cache results that read files modified in the last 2 s

    def dep_hash(self):
        h = hashlib.sha1()
        pats = self.spec.get("install_files", [])
        for f in sorted(git(self.src, "ls-files").splitlines()):
            if any(fnmatch.fnmatch(f, p) for p in pats):
                try:
                    h.update(f.encode() + b"\0" + (self.src / f).read_bytes())
                except OSError:
                    pass
        return h.hexdigest()

    def install(self):
        env = self.env()
        for cmd in self.spec.get("install", []):
            code, out, dt = sh(self.fmt(cmd), cwd=self.src, env=env, timeout=3600, shell=True)
            log(f"install: {cmd[:80]} -> {code} ({dt:.0f}s)")
            if code:
                return False, out[-3000:]
        self._runtime = None  # the interpreter may have changed
        return True, ""

    def build(self):
        env = self.env()
        for cmd in self.spec.get("build", []):
            code, out, dt = sh(self.fmt(cmd), cwd=self.src, env=env, timeout=3600, shell=True)
            if code:
                log(f"build failed: {cmd[:80]} -> {code}\n{out[-1500:]}")
                return False
        return True

    # -- units ---------------------------------------------------------------
    def discover(self):
        u = self.spec["units"]
        if self.lang == "go":
            code, out, _ = sh(["go", "list", "-f", "{{if or .TestGoFiles .XTestGoFiles}}{{.ImportPath}}{{end}}",
                               *u.get("patterns", ["./..."])], cwd=self.src, env=self.env(), timeout=1800)
            units = [x for x in out.splitlines() if x and not x.startswith(("go:", "warning"))]
        else:
            files = git(self.src, "ls-files").splitlines()
            units = [f for f in files if any(fnmatch.fnmatch(f, p) for p in u["include"])
                     and not any(fnmatch.fnmatch(f, p) for p in u.get("exclude", []))]
        frac = u.get("sample", 1.0)
        seed = u.get("seed", "s2")
        sel = []
        for x in units:
            h = int(hashlib.sha1(f"{seed}:{x}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
            if h < frac and int(hashlib.sha1(f"shard:{x}".encode()).hexdigest()[:8], 16) % self.nshards == self.shard:
                sel.append(x)
        return sorted(sel), len(units)

    # -- running ---------------------------------------------------------------
    def run_unit(self, unit, traced_run=True, tag="run"):
        key = hashlib.sha1(unit.encode()).hexdigest()[:12]
        rep = self.work / f"rep-{key}-{tag}.json"
        pyrec = self.src / ".s2rec" / f"{key}-{tag}"
        shutil.rmtree(pyrec, ignore_errors=True)
        rep.unlink(missing_ok=True)
        env = self.env()
        env["S2_REPORT"] = str(rep)
        envrec = self.work / f"envrec-{key}-{tag}"
        shutil.rmtree(envrec, ignore_errors=True)
        if traced_run and self.lang == "pytest":
            pyrec.mkdir(parents=True, exist_ok=True)
            env["S2_PYREC"] = str(pyrec)
        if traced_run and self.lang in ("vitest", "jest"):
            envrec.mkdir(parents=True, exist_ok=True)
            env["S2_ENVREC"] = str(envrec)
        cmd = [self.fmt(c).replace("{unit}", unit).replace("{out}", str(rep)) for c in self.spec["cmd"]]
        to = self.spec.get("unit_timeout", 900)
        if traced_run:
            code, out, wall, deps = traced(cmd, self.src, env, self.work / f"st-{key}-{tag}.log", self.roots(),
                                           timeout=to)
        else:
            code, out, wall = sh(cmd, cwd=self.src, env=env, timeout=to)
            deps = None
        tests = None
        if self.lang == "pytest":
            try:
                tests = json.loads(rep.read_text())["tests"]
            except Exception:
                tests = None
        elif self.lang == "vitest":
            tests = parse_vitest(rep)
        rep.unlink(missing_ok=True)
        r = {"code": code, "wall": wall, "tests": tests, "tail": out[-1200:] if (code not in (0, 5) or tests is None) else ""}
        if tests and "<file-span>" in tests:
            span = tests.pop("<file-span>")[1]
            r["test_time"] = max(span, sum(v[1] for v in tests.values()))
        else:
            r["test_time"] = sum(v[1] for v in (tests or {}).values())
        if deps is not None:
            r["deps"] = self.normalize(unit, deps, pyrec, envrec, env)
        shutil.rmtree(pyrec, ignore_errors=True)
        shutil.rmtree(envrec, ignore_errors=True)
        return r

    def normalize(self, unit, deps, pyrec, envrec=None, env=None):
        """Turn raw traces into a record that can be compared with a later tree."""
        if "error" in deps:
            return {"error": deps["error"]}
        src = str(self.src) + "/"
        rw = set(deps.get("rw", []))
        reads = {}
        n_rw = 0
        for p in deps["reads"]:
            if p in rw:
                # opened read-write (or read, then written) by the run: the dependency is the content before the run
                rel = p[len(src):] if p.startswith(src) else None
                if rel is not None and "/node_modules/" not in "/" + rel:
                    if rel in self.tracked():
                        reads[p] = self.committed_hash(p)
                        n_rw += 1
                    elif self.ignored(rel):
                        reads[p] = self.hasher.file(p)  # build output or cache: kept (conservative)
                        n_rw += 1
                    # untracked and not ignored: created after the checkout by a test, not an input
                    continue
                reads[p] = self.hasher.file(p)
                n_rw += 1
                continue
            reads[p] = self.hasher.file(p)
        reads = {p: h for p, h in reads.items() if h is not None}
        exists = {p: Hasher.kind(p) for p in deps["exists"]}
        exists = {p: k for p, k in exists.items() if k}
        lists = {}
        py = None
        env_names = set(ALWAYS_ENV.get(self.lang, ()))
        if self.lang == "pytest":
            funcs, tried, mods, plists = set(), set(), set(), set()
            for f in pyrec.glob("*.json") if pyrec.exists() else []:
                try:
                    d = json.loads(f.read_text())
                except Exception:
                    continue
                funcs.update(tuple(x) for x in d["funcs"])
                tried.update(d["tried"])
                mods.update(d["modules"])
                plists.update(d["lists"])
                env_names.update(d.get("env", []))
            for rel in plists:
                p = os.path.join(str(self.src), rel) if rel != "." else str(self.src)
                lists[p] = Hasher.listing(p)
            # site-packages listing (plugin discovery) is always a dependency of a pytest process
            for sp in self.site_packages():
                lists[sp] = Hasher.listing(sp)
            py = {"funcs": sorted({(f[0], top_qualname(f[1])) for f in funcs}), "tried": sorted(tried),
                  "modules": sorted(mods), "nproc": len(list(pyrec.glob('*.json'))) if pyrec.exists() else 0}
        else:
            for f in envrec.glob("*.txt") if envrec is not None and envrec.exists() else []:
                try:
                    env_names.update(x for x in f.read_text(errors="replace").splitlines() if x and not x.startswith("#"))
                except OSError:
                    pass
            first = deps["reads"].get(os.path.join(str(self.src), unit)) if self.lang != "go" else 0
            for d, n in deps["lists"].items():
                if first is None or n > first:
                    lists[d] = Hasher.listing(d)
        if (deps["net"] or self.spec.get("db_inputs_always")) and self.spec.get("db_inputs"):
            # a service database built from migration files at the start of the commit: those files are inputs
            for pat in self.spec["db_inputs"]:
                for f in self.src.glob(pat):
                    h = self.hasher.file(str(f))
                    if h:
                        reads[str(f)] = h
        env = env if env is not None else self.env()
        nonloop = external(deps["net"], env)   # a connect to a loopback HTTP(S) proxy is external (R-002b)
        envk = {n: env_value(n, env) for n in sorted(env_names) if not n.startswith(HARNESS_ENV)}
        return {"reads": reads, "exists": exists, "missing": deps["missing"], "lists": lists, "py": py,
                "net": len(deps["net"]), "net_ext": len(nonloop), "net_ext_addr": sorted({x[0] for x in nonloop})[:5],
                "execs": len(deps["execs"]), "nread_src": sum(1 for p in reads if p.startswith(src)), "n_rw": n_rw,
                "env": envk, "runtime": self.runtime()}

    def ignored(self, rel):
        return subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=self.src).returncode == 0

    def site_packages(self):
        if self.lang != "pytest":
            return []
        return [str(p) for p in (self.venv / "lib").glob("python*/site-packages")]

    # -- decisions ------------------------------------------------------------
    def added_since(self, j_sha, i_sha):
        key = (j_sha, i_sha)
        if key not in self.added_cache:
            out = git(self.src, "diff", "--no-renames", "--name-only", "--diff-filter=AD", j_sha, i_sha, check=False)
            self.added_cache[key] = out.splitlines()
        return self.added_cache[key]

    def decide(self, unit, rec, i_sha, shas):
        """{rule: reason or None}. ``rec`` is the record of the unit's last real run."""
        if rec is None or "deps" not in rec or "error" in rec.get("deps", {}):
            r = "new" if rec is None else "no-record"
            return {k: r for k in self.rules()}, {}
        d = rec["deps"]
        if rec.get("tests") is None and self.lang != "go":
            return {k: "no-result" for k in self.rules()}, {}
        if d["net_ext"]:
            return {k: "network" for k in self.rules()}, {}
        if rec.get("code") not in (0, 5):
            # a cached failure is never reused (Bazel does the same): flaky failures do not stick
            return {k: "cached-failure" for k in self.rules()}, {}
        reasons = []
        if d.get("runtime") is not None:
            now = self.runtime()
            for k in sorted(set(d["runtime"]) | set(now)):
                if d["runtime"].get(k) != now.get(k):
                    reasons.append(("runtime", k))
                    break
        if d.get("env"):
            cur = self.env()
            for n, h in d["env"].items():
                if env_value(n, cur) != h:
                    reasons.append(("env-var", n))
                    break
        changed_py = []
        src = str(self.src) + "/"
        for p, h in d["reads"].items():
            now = self.hasher.file(p)
            if now != h:
                if p.startswith(src) and p.endswith(".py") and now is not None:
                    changed_py.append(p)
                else:
                    reasons.append(("read", p))
        for p, k in d["exists"].items():
            if Hasher.kind(p) != k:
                reasons.append(("exists", p))
        for p in d["missing"]:
            if os.path.lexists(p):
                reasons.append(("appeared", p))
        for p, h in d["lists"].items():
            if Hasher.listing(p) != h:
                reasons.append(("listing", p))
        if d.get("py") and self.lang == "pytest":
            tried = set(d["py"]["tried"])
            for f in self.added_since(rec["sha"], i_sha):
                if not f.endswith((".py", ".so", ".pyi")) and "/" not in f:
                    continue
                parts = f.rsplit(".", 1)[0].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                names = {".".join(parts[k:]) for k in range(len(parts))}
                if names & tried:
                    reasons.append(("import-resolution", f))
                    break
        base = reasons[0] if reasons else None
        out = {}
        # closure: any change at all
        out["closure"] = self.reason_label(base) if base else (
            ("py-source:" + self.kind_of(changed_py[0])) if changed_py else None)
        if self.lang == "pytest":
            if base:
                out["func+guard"] = out["func"] = out["closure"]
            elif not changed_py:
                out["func+guard"] = out["func"] = None
            else:
                fg, fo = None, None
                funcs = {}
                for f, q in d["py"]["funcs"]:
                    funcs.setdefault(f, set()).add(q)
                for p in changed_py:
                    rel = p[len(src):]
                    old = self.blob(rec["sha"], rel)
                    new = self.blob(i_sha, rel)
                    if old is None or new is None:
                        fg = fg or "py-unreadable"
                        fo = fo or "py-unreadable"
                        continue
                    same_skel, ch, ok = changed_functions(old, new)
                    hit = bool(ch & funcs.get(rel, set()))
                    if not ok:
                        fg = fg or "py-syntax"
                        fo = fo or "py-syntax"
                        continue
                    if not same_skel:
                        fg = fg or "py-module-level"
                    elif hit:
                        fg = fg or "py-executed-function"
                    if hit or rel == unit:
                        fo = fo or "py-executed-function"
                out["func+guard"] = fg
                out["func"] = fo
            # ~cfg: a root config file whose pytest section is unchanged does not count (near-proof: assumes
            # nothing else in the test process interprets the rest of that file)
            cfg_only = reasons and all(k == "read" and self.pytest_section_same(p, rec["sha"], i_sha)
                                       for k, p in reasons)
            if cfg_only:
                out["closure~cfg"] = ("py-source:" + self.kind_of(changed_py[0])) if changed_py else None
                if changed_py:
                    sub = dict(rec)
                    sub["deps"] = dict(d, reads={p: h for p, h in d["reads"].items()
                                                 if not (p.startswith(src) and strict_config_hit(p[len(src):])
                                                         and "/" not in p[len(src):])})
                    o2, _ = self.decide(unit, sub, i_sha, shas)
                    out["func+guard~cfg"] = o2["func+guard"]
                else:
                    out["func+guard~cfg"] = None
            else:
                out["closure~cfg"] = out["closure"]
                out["func+guard~cfg"] = out["func+guard"]
        why = base[1] if base else (changed_py[0] if changed_py else None)
        if why and why.startswith(src):
            why = why[len(src):]
        elif why and why.startswith(str(self.venv) + "/"):
            why = "<venv>/" + why[len(str(self.venv)) + 1:]
        return out, {"n_changed_py": len(changed_py), "n_reasons": len(reasons), "why": why}

    def pytest_section_same(self, path, j_sha, i_sha):
        src = str(self.src) + "/"
        if not path.startswith(src):
            return False
        rel = path[len(src):]
        if "/" in rel or rel not in ("pyproject.toml", "setup.cfg", "tox.ini"):
            return False
        key = (rel, j_sha, i_sha)
        if key not in self.added_cache:
            a, b = self.blob(j_sha, rel), self.blob(i_sha, rel)
            self.added_cache[key] = a is not None and b is not None and pytest_section(a, rel) == pytest_section(b, rel)
        return self.added_cache[key]

    def reason_label(self, r):
        kind, what = r
        if kind in ("runtime", "env-var"):
            return f"{kind}:{what}"
        return kind + ":" + self.kind_of(what)

    def kind_of(self, p):
        """Class of a path. ``installed`` = third-party packages (virtualenv, node_modules); ``system`` = any other
        path outside the repository. (Version 2 labelled both ``env``, which read as "environment variable".)"""
        src = str(self.src) + "/"
        if not p.startswith(src):
            return "installed" if p.startswith(str(self.venv) + "/") else "system"
        rel = p[len(src):]
        if strict_config_hit(rel):
            return "config"
        if "/node_modules/" in "/" + rel:
            return "installed"
        if rel.endswith((".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".vue", ".go", ".jsx", ".mts")):
            return "source"
        return "data"

    def blob(self, sha, rel):
        p = subprocess.run(["git", "show", f"{sha}:{rel}"], cwd=self.src, capture_output=True)
        if p.returncode:
            return None
        return p.stdout.decode("utf-8", "replace")

    def rules(self):
        if self.lang == "pytest":
            return ["closure", "closure~cfg", "func+guard", "func+guard~cfg", "func"]
        return ["closure"]

    # -- main loop -------------------------------------------------------------
    def walk(self):
        commits = self.commits()
        log(f"{self.spec['name']} shard {self.shard}/{self.nshards}: {len(commits)} commits "
            f"{commits[0][:10]}..{commits[-1][:10]}")
        if self.lang == "go":
            return self.walk_go(commits)
        verify = self.spec.get("verify", 0.1)
        for i, sha in enumerate(commits):
            if time.time() - T_START > self.budget:
                self.result["notes"].append(f"budget reached before commit {i}")
                log("time budget reached")
                break
            t_commit = time.time()
            prev = commits[i - 1] if i else None
            self.checkout(sha)
            row = {"i": i, "sha": sha, "date": git(self.src, "show", "-s", "--format=%cI", sha).strip()}
            dh = self.dep_hash()
            if dh != self._last_dep:
                ok, why = self.install()
                row["installed"] = True
                if not ok:
                    row["status"] = "install-failed"
                    row["detail"] = why[-800:]
                    self.result["commits"].append(row)
                    self._last_dep = None
                    self.flush()
                    continue
                self._last_dep = dh
            if not self.build():
                row["status"] = "build-failed"
                self.result["commits"].append(row)
                self.flush()
                continue
            units, total_units = self.discover()
            row["units"], row["units_total"] = len(units), total_units
            changed = git(self.src, "diff", "--no-renames", "--name-only", prev, sha).splitlines() if prev else []
            row["changed_files"] = len(changed)
            row["strict_config"] = sorted({c for c in changed if strict_config_hit(c)})[:20]
            # decisions
            dec = {}
            for u in units:
                rec = self.records.get(u)
                dec[u] = self.decide(u, rec, sha, commits)
            must = [u for u in units if dec[u][0]["closure"]]
            skip = [u for u in units if not dec[u][0]["closure"]]
            ver = [u for u in skip if self.rng.random() < verify] if i else []
            plain = i == 0 and self.spec.get("plain_baseline", True)
            log(f"[{i}] {sha[:10]} units {len(units)} must {len(must)} skip {len(skip)} verify {len(ver)} "
                f"changed {len(changed)}")
            runs = {}

            def job(u):
                return u, self.run_unit(u, traced_run=True)
            with ThreadPoolExecutor(self.workers) as ex:
                for u, r in ex.map(job, must + ver):
                    runs[u] = r
            if plain:
                def pjob(u):
                    return u, self.run_unit(u, traced_run=False, tag="plain")
                with ThreadPoolExecutor(self.workers) as ex:
                    for u, r in ex.map(pjob, units):
                        self.costs[u] = {"test": r["test_time"], "wall": r["wall"], "code": r["code"],
                                         "n": len(r["tests"] or {})}
                ovh = [runs[u]["wall"] / self.costs[u]["wall"] for u in units
                       if u in runs and self.costs.get(u, {}).get("wall")]
                self.result["capture_overhead"] = {"median_ratio": statistics.median(ovh) if ovh else None,
                                                   "n": len(ovh),
                                                   "sum_traced": sum(runs[u]["wall"] for u in units if u in runs),
                                                   "sum_plain": sum(self.costs[u]["wall"] for u in units)}
            # verification of skipped units
            def compare(u, extra=None):
                old = self.records.get(u)
                new = runs[u]
                a = outcome_summary(old.get("tests") or {})
                b = outcome_summary(new.get("tests") or {})
                same = a == b and (old["code"] == 0) == (new["code"] == 0)
                item = {"unit": u, "same": same, **(extra or {})}
                if not same:
                    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))[:10]
                    item["diff"] = diff
                    # flaky? two more plain runs at this commit
                    again = [outcome_summary((self.run_unit(u, traced_run=False, tag=f"re{k}")["tests"]) or {})
                             for k in range(2)]
                    item["rerun_matches_cache"] = sum(1 for x in again if x == a)
                    item["rerun_matches_fresh"] = sum(1 for x in again if x == b)
                return item
            vres = [compare(u) for u in ver]
            # extra skips of the other rules (func+guard, func, ~cfg): units closure reran but that rule would
            # have reused; every one of them ran fresh here, so every one is compared (R-002 fix 6)
            xres = []
            for u in must:
                rs = [r for r, v in dec[u][0].items() if r != "closure" and v is None]
                if rs and self.records.get(u) and u in runs:
                    xres.append(compare(u, {"rules": rs}))
            # unit costs (plain baseline when known, else measured traced test time / overhead)
            for u in units:
                if u not in self.costs and u in runs:
                    r = runs[u]
                    ratio = (self.result.get("capture_overhead") or {}).get("median_ratio") or 1.0
                    self.costs[u] = {"test": r["test_time"] / ratio, "wall": r["wall"] / ratio, "code": r["code"],
                                     "n": len(r["tests"] or {}), "est": True}
            # record refresh
            for u, r in runs.items():
                r["sha"] = sha
                r["i"] = i
                self.records[u] = r
            if i:
                tr = {"i": i, "sha": sha, "units": len(units), "changed_files": len(changed),
                      "strict_config": bool(row["strict_config"]), "verify": vres, "xverify": xres,
                      "cached_fail": sorted(u for u in units if dec[u][0]["closure"] == "cached-failure"),
                      "runtime": self.runtime(),
                      "decisions": {u: dec[u][0] for u in units if any(dec[u][0].values())},
                      "tests": {u: self.costs.get(u, {}).get("n", 0) for u in units},
                      "new_units": [u for u in units if dec[u][0]["closure"] == "new"],
                      # market test: the path behind each closure rerun (first reason), top 25 by count
                      "why_paths": dict(Counter(f'{dec[u][0]["closure"].split(":", 1)[0]}|{dec[u][1].get("why")}'
                                                for u in must if dec[u][1].get("why")).most_common(25))}
                self.result["transitions"].append(tr)
            row["status"] = "ok"
            row["ran"] = len(runs)
            row["fails"] = sum(1 for u in units if (runs.get(u) or self.records.get(u) or {}).get("code") not in (0, 5))
            row["seconds"] = time.time() - t_commit
            self.result["commits"].append(row)
            self.result["units"] = {u: self.costs.get(u) for u in sorted(self.costs)}
            self.result["unit_info"] = {u: {"nread": len(r.get("deps", {}).get("reads", {})),
                                            "nread_src": r.get("deps", {}).get("nread_src"),
                                            "execs": r.get("deps", {}).get("execs"),
                                            "net": r.get("deps", {}).get("net"),
                                            "net_ext": r.get("deps", {}).get("net_ext"),
                                            "n_rw": r.get("deps", {}).get("n_rw"),
                                            "env": sorted((r.get("deps", {}).get("env") or {}))[:60],
                                            "code": r.get("code"),
                                            "tail": r.get("tail", "")[-300:]}
                                        for u, r in self.records.items()}
            if i % 10 == 0 or i == len(commits) - 1:
                self.flush()
        self.flush()

    # -- Go -------------------------------------------------------------------------
    def walk_go(self, commits):
        """go test ./... at every commit with GOCACHE kept across commits; strace attributes runtime reads
        (including subprocesses) to each package's test binary."""
        env = self.env()
        env["GOCACHE"] = str(self.work / "gocache")
        if self.spec.get("goflags"):
            env["GOFLAGS"] = self.spec["goflags"]
        verify = self.spec.get("verify", 0.1)
        pkgrec = {}
        for i, sha in enumerate(commits):
            if time.time() - T_START > self.budget:
                self.result["notes"].append(f"budget reached before commit {i}")
                break
            t_commit = time.time()
            prev = commits[i - 1] if i else None
            self.checkout(sha)
            row = {"i": i, "sha": sha, "date": git(self.src, "show", "-s", "--format=%cI", sha).strip()}
            dh = self.dep_hash()
            if dh != self._last_dep:
                sh(["go", "mod", "download"], cwd=self.src, env=env, timeout=1800)
                self._last_dep = dh
            if not self.build():
                row["status"] = "build-failed"
                self.result["commits"].append(row)
                continue
            units, total = self.discover()
            changed = git(self.src, "diff", "--no-renames", "--name-only", prev, sha).splitlines() if prev else []
            row["units"], row["units_total"], row["changed_files"] = len(units), total, len(changed)
            row["strict_config"] = sorted({c for c in changed if strict_config_hit(c)})[:20]
            # our runtime check, before running: which packages' recorded runtime reads changed
            rt_changed = {}
            for u in units:
                rec = pkgrec.get(u)
                if rec:
                    for p, h in rec["reads"].items():
                        if self.hasher.file(p) != h:
                            rt_changed[u] = p
                            break
                    else:
                        for p in rec["missing"]:
                            if os.path.lexists(p):
                                rt_changed[u] = p
                                break
            cmd = ["go", "test", "-json", *self.spec.get("go_args", []), *units]
            log_path = self.work / "go.strace"
            code, out, wall, deps = traced(cmd, self.src, env, log_path, self.roots(), timeout=5400,
                                           group_suffix=".test")
            res = self.parse_go_json(out)
            row["wall"] = wall
            row["go_exit"] = code
            if not res:
                row["go_tail"] = out[-2500:]
                log(f"go test produced no results (exit {code}):\n{out[-2500:]}")
            # map strace groups (cwd of the test binary) to packages
            modpath = self.go_module_dirs(env)
            groups = deps.get("groups", {}) if isinstance(deps, dict) else {}
            for g, gd in groups.items():
                pkg = modpath.get(g)
                if pkg:
                    reads = {p: self.hasher.file(p) for p in gd.get("reads", [])}
                    net = gd.get("net", [])
                    net = net if isinstance(net, list) else []
                    pkgrec[pkg] = {"reads": {p: h for p, h in reads.items() if h}, "missing": gd.get("missing", []),
                                   "execs": len([x for x in gd.get("execs", []) if not x.endswith(".test")]),
                                   "net": len(net), "net_ext": len(external(net, env)),
                                   "net_ext_addr": sorted({str(x[0]) for x in external(net, env)})[:5],
                                   "runtime": self.runtime(),
                                   "env": {n: env_value(n, env) for n in ALWAYS_ENV["go"]}, "i": i}
            dec = {}
            for u in units:
                r = res.get(u)
                if r is None:
                    dec[u] = {"go-cache": "no-result", "closure": "no-result"}
                    continue
                cached = r["cached"]
                d = {"go-cache": None if cached else ("new" if i == 0 else "go-miss")}
                prec = pkgrec.get(u)
                if not cached:
                    d["closure"] = d["go-cache"]
                elif prec is None:
                    d["closure"] = "no-record"     # no runtime record of this package: nothing to prove with
                elif prec.get("net_ext"):
                    d["closure"] = "network"       # connected to a non-loopback address: never skipped (R-002 3)
                elif prec.get("runtime") != self.runtime():
                    d["closure"] = "runtime"
                elif any(env_value(n, env) != h for n, h in (prec.get("env") or {}).items()):
                    # variables read below os.Getenv (TZ by package time, ...) are not in go's test log
                    d["closure"] = "env-var"
                elif u in rt_changed:
                    d["closure"] = "runtime-read-changed"   # Go's own key did not see it: potential wrong hit
                    d["path"] = os.path.relpath(rt_changed[u], self.src)
                else:
                    d["closure"] = None
                if r.get("execs_seen") or (pkgrec.get(u, {}).get("execs")):
                    d["spawns"] = True
                dec[u] = d
                if not cached and r.get("elapsed") is not None:
                    self.costs[u] = {"test": r["elapsed"], "wall": r["elapsed"], "code": 0 if r["ok"] else 1,
                                     "n": r.get("n", 0)}
            # verification: run a sample of Go-cached packages with -count=1, and every potential wrong hit
            cached_pkgs = [u for u in units if dec[u].get("go-cache") is None]
            ver = sorted(set([u for u in cached_pkgs if self.rng.random() < verify] +
                             [u for u in cached_pkgs if dec[u].get("closure") == "runtime-read-changed"])) if i else []
            # rec_i of every go-cache hit: which run's outcome the cache served
            for u in cached_pkgs:
                if pkgrec.get(u):
                    dec[u]["rec_i"] = pkgrec[u]["i"]
            vres = []
            if ver:
                c2, o2, _ = sh(["go", "test", "-json", "-count=1", *self.spec.get("go_args", []), *ver], cwd=self.src,
                               env=env, timeout=5400)
                fresh = self.parse_go_json(o2)
                for u in ver:
                    a, b = res.get(u), fresh.get(u)
                    same = a is not None and b is not None and a["ok"] == b["ok"] and a["fails"] == b["fails"]
                    item = {"unit": u, "same": same, "potential": dec[u].get("closure") == "runtime-read-changed",
                            "closure_skip": dec[u].get("closure") is None, "closure": dec[u].get("closure")}
                    if not same and b is not None:
                        c3, o3, _ = sh(["go", "test", "-json", "-count=1", *self.spec.get("go_args", []), u],
                                       cwd=self.src, env=env, timeout=3600)
                        again = self.parse_go_json(o3).get(u)
                        item["fails_fresh"] = b["fails"][:10]
                        item["rerun_matches_cache"] = int(again is not None and again["ok"] == a["ok"])
                    vres.append(item)
            if i:
                self.result["transitions"].append({
                    "i": i, "sha": sha, "units": len(units), "changed_files": len(changed),
                    "strict_config": bool(row["strict_config"]), "verify": vres, "runtime": self.runtime(),
                    "decisions": {u: d for u, d in dec.items() if any(v for k, v in d.items()
                                                                       if k not in ("spawns", "rec_i"))},
                    "spawns": sorted(u for u, d in dec.items() if d.get("spawns")),
                    "tests": {u: self.costs.get(u, {}).get("n", 0) for u in units}})
            row["status"] = "ok"
            row["cached"] = sum(1 for u in units if res.get(u, {}).get("cached"))
            row["fails"] = sum(1 for u in units if res.get(u) and not res[u]["ok"])
            row["seconds"] = time.time() - t_commit
            log(f"[{i}] {sha[:10]} pkgs {len(units)} go-cached {row['cached']} runtime-changed-but-cached "
                f"{sum(1 for u in units if dec.get(u, {}).get('closure') == 'runtime-read-changed')} "
                f"verify {len(ver)} wall {wall:.0f}s")
            self.result["commits"].append(row)
            self.result["units"] = {u: self.costs.get(u) for u in sorted(self.costs)}
            self.result["unit_info"] = {u: {"nread": len(r["reads"]), "execs": r["execs"], "net": r["net"],
                                            "net_ext": r.get("net_ext", 0), "net_ext_addr": r.get("net_ext_addr", [])}
                                        for u, r in pkgrec.items()}
            if i % 10 == 0 or i == len(commits) - 1:
                self.flush()
        self.flush()

    def go_module_dirs(self, env):
        code, out, _ = sh(["go", "list", "-f", "{{.Dir}}\t{{.ImportPath}}", *self.spec["units"].get("patterns", ["./..."])],
                          cwd=self.src, env=env, timeout=1800)
        m = {}
        for line in out.splitlines():
            if "\t" in line:
                d, p = line.split("\t", 1)
                m[d] = p
                m[os.path.realpath(d)] = p
        return m

    @staticmethod
    def parse_go_json(out):
        res = {}
        for line in out.splitlines():
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            pkg = ev.get("Package")
            if not pkg:
                continue
            r = res.setdefault(pkg, {"cached": False, "ok": None, "fails": [], "elapsed": None, "n": 0})
            act = ev.get("Action")
            if act == "output" and "(cached)" in (ev.get("Output") or "") and not ev.get("Test"):
                r["cached"] = True
            if ev.get("Test"):
                if act == "fail":
                    r["fails"].append(ev["Test"])
                if act in ("pass", "fail", "skip"):
                    r["n"] += 1
            elif act in ("pass", "fail", "skip"):
                r["ok"] = act != "fail"
                r["elapsed"] = ev.get("Elapsed")
        for r in res.values():
            r["fails"] = sorted(set(r["fails"]))
        return {k: v for k, v in res.items() if v["ok"] is not None}

    # -- output -----------------------------------------------------------------------
    def flush(self, push=True):
        import gzip
        self.result["elapsed_s"] = time.time() - T_START
        self.out.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.out.with_suffix(".tmp")
        data = json.dumps(self.result, separators=(",", ":")).encode()
        if self.out.suffix == ".gz":
            data = gzip.compress(data, 9)
        tmp.write_bytes(data)
        tmp.replace(self.out)
        if push and self.push and os.environ.get("S2_COMMIT"):
            commit_results([self.out], f"Skip study 2: {self.spec['name']} shard {self.shard} "
                                       f"({len(self.result['commits'])} commits)")


def commit_results(paths, msg):
    """Commit result files to the current branch with rebase-retry (used inside GitHub Actions)."""
    repo = Path(__file__).resolve().parents[2]
    branch = os.environ.get("S2_BRANCH", "claude/market-test")
    for attempt in range(12):
        sh(["git", "fetch", "-q", "origin", branch], cwd=repo)
        sh(["git", "reset", "-q", "--soft", f"origin/{branch}"], cwd=repo)
        sh(["git", "reset", "-q"], cwd=repo)
        for p in paths:
            sh(["git", "add", "-f", str(p)], cwd=repo)
        code, out, _ = sh(["git", "commit", "-q", "-m", msg], cwd=repo)
        if code and "nothing to commit" in out:
            return True
        code, out, _ = sh(["git", "push", "-q", "origin", f"HEAD:{branch}"], cwd=repo)
        if code == 0:
            return True
        time.sleep(5 + random.random() * 20)
    log("could not push results")
    return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--budget-min", type=float, default=330)
    ap.add_argument("--run-id", default="local")
    a = ap.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text())
    s, n = (int(x) for x in a.shard.split("/"))
    w = Walker(spec, a.work, a.out, s, n, a.budget_min, a.run_id)
    w.walk()
    return 0


if __name__ == "__main__":
    sys.exit(main())
