#!/usr/bin/env python3
"""Head-to-head walk: three skip rules on the same commits, each with its own cache, every extra skip verified.

Rules (a unit = one test file run in its own process; every rule reruns new units and never reuses a cached
failure, so the rules differ only in what they treat as a dependency):

* ``A`` (Datadog Test Impact Analysis / Codecov ATS shape, file level): the unit reruns only when a repository
  source-code file it loaded changed or vanished. "Loaded" = a repository file with a code extension that the unit's
  process opened (Python modules via their .pyc, conftest.py included; JS/TS modules; never node_modules, never
  build/test configuration such as vitest.config.ts / tsconfig.json / pyproject.toml). Not seen, as the vendors'
  docs admit: installed packages, data files, configuration, environment variables, runtime, network.
  The loaded set is a superset of the covered set, so A here skips at most what a coverage tool would skip.
* ``Ae`` (Python only; per-test coverage shape, file level): A, except that a changed repository ``.py`` file
  counts only when it is the unit's own file or the unit *executed a function defined in it* (sys.monitoring
  PY_START; code that only ran at import time, module bodies and class bodies, does not count, as in per-test
  coverage contexts).
* ``Af`` (Python only; Codecov ATS shape, function level): reruns only when the unit's own file changed or the
  definition of a function it executed changed (``pyskel.changed_functions``); module-level changes are not seen.
* ``B`` (Nx Ultracache shape, literal: "files read"): reruns only when a file the unit opened read-only (repository,
  virtualenv / node_modules) changed or vanished. Not seen: environment variables, files opened read-write, network,
  runtime identity, paths stat'ed / found missing, directory listings.
* ``B+`` (Nx shape, generous): B plus paths stat'ed, paths found missing (now exist?), directory listings and
  Python import resolution, i.e. the study's v2 capture without its network guard. Sensitivity column for B.
* ``C`` (fenvix proof rule, closure v3): ``walk.Walker.decide`` unchanged.

Each rule keeps its own cache: the record of the unit's last run *that this rule asked for*. A rule decides by
comparing that record with the tree now, and when it skips, the outcome it reuses is that record's outcome. The walker
really runs the union of what the rules rerun plus a random verification sample of the rest, so every skip of A, B
or B+ that C does not make is compared with a fresh run at the same commit.

A mismatch (cached outcome != fresh outcome) is re-run twice plainly at the head commit; one that reproduces is
re-checked at the end of the walk at the cached commit (twice, plainly, same environment profile as the cached run).
Classification per rule:

* ``wrong`` (verdict flip): the fresh run fails while the reused outcome is a pass, both head re-runs fail, and both
  re-runs at the cached commit pass;
* ``flaky``: any of those re-runs disagrees;
* ``set``: no failure, but the test set or a non-failure outcome (pass / skip) differs (e.g. new parametrized cases).

``--arm env`` / ``--arm runtime`` walk the first ``--max-commits`` commits with the environment alternating between
two profiles at every commit (commit 0 in profile 0):

* ``env``: profile 1 sets HOME to another (existing, writable) home, TZ=America/Los_Angeles, LANG=en_US.UTF-8;
* ``home-root``: profile 1 sets only HOME=/root, as on a root container runner (added after the ``env`` arm: it targets
  the one environment dependency the R-002 reviewer had documented, docusaurus snapshots that render ``/root/...``);
* ``runtime``: profile 1 uses another patch release of the same interpreter (Python: a second virtualenv at the same
  path, created with an older patch release; Node: an older release of the same major first on PATH).

Installs and builds always run in profile 0's environment.

``--arm ci-dep`` / ``ci-data`` / ``ci-env`` (realistic CI changes, ``changes.json``): the first ``--max-commits`` commits
of the window, profile 0 until commit ``--land`` and profile 1 from there on (the change lands and stays, as a merged
change does). The change lands as a commit of its own: the landing transition repeats commit ``--land - 1``'s code with
only the change applied (a lockfile bump or a fixture edit merged alone), then the window continues with the change. Profile 1 is the project's scenario of that kind:

* ``ci-dep``: the resolved version of a dependency changes (a lockfile bump; for these libraries, which install
  unpinned, also what a new release does to the next CI run). Each profile has its own virtualenv at the same path:
  the normal install, then ``uv pip install`` of the profile's pins (``pins0`` / ``pins1``);
* ``ci-data``: a data / fixture file read by the tests is edited (no test or source file changes with it);
* ``ci-env``: the CI job exports one more variable that the tests read (``env``).

In these arms every unit runs fresh at every commit (verification sample 100%), so every skip of every rule is checked.

    python3 headtohead/h2h_walk.py --spec headtohead/specs/toolz.json --work /tmp/w --out x.json.gz [--arm env]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
S2 = HERE.parent
sys.path.insert(0, str(S2))
import walk as W  # noqa: E402
from walk import Hasher, Walker, git, log, outcome_summary, sh, strict_config_hit  # noqa: E402
from pyskel import changed_functions, defs  # noqa: E402

RULES_ALL = ("C", "A", "Ae", "Af", "B", "B+")
PY_ONLY = ("Ae", "Af")
CODE_EXT = (".py", ".pyw", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue")
ALT_TZ = "America/Los_Angeles"
ALT_LANG = "en_US.UTF-8"


def good(code):
    return code in (0, 5)


class H2H(Walker):
    def __init__(self, spec, work, out, shard, nshards, budget_min, run_id, arm="", max_commits=0, max_rechecks=80,
                 land=3):
        super().__init__(spec, work, out, shard, nshards, budget_min, run_id)
        self.arm = arm or ""
        self.land = land
        self.change = None
        self.edit_log = []
        self.max_commits = max_commits
        self.max_rechecks = max_rechecks
        self.profile = 0
        self.base_env = False
        self.rules_h = tuple(r for r in RULES_ALL if self.lang == "pytest" or r not in PY_ONLY)
        self.own = tuple(r for r in self.rules_h if r != "C")
        self.rrec = {r: {} for r in self.own}
        self._pycache = {}
        self.last_dep = {0: None, 1: None}
        self.candidates = {}   # (unit, rec_sha, rec_profile) -> {"rules": set, "i": [...], "cached": summary}
        self.alt = {}
        self.result.update({"h2h": 3, "arm": self.arm, "rules": list(self.rules_h), "profiles": {}, "rechecks": []})
        if self.arm:
            self.prepare_arm()

    # -- environment profiles ----------------------------------------------------------------------------------------
    def prepare_arm(self):
        if self.arm == "env":
            home = self.work / "home-alt"
            home.mkdir(parents=True, exist_ok=True)
            for f in (".gitconfig",):
                src = Path(os.path.expanduser("~")) / f
                if src.exists():
                    shutil.copy(src, home / f)
            locs = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.lower()
            alt = {"HOME": str(home), "TZ": ALT_TZ}
            if "en_us.utf8" in locs or "en_us.utf-8" in locs:
                alt["LANG"] = ALT_LANG
            self.alt = alt
            self.result["profiles"] = {"0": {"HOME": os.path.expanduser("~"), "TZ": os.environ.get("TZ"),
                                             "LANG": os.environ.get("LANG")}, "1": alt}
        elif self.arm == "home-root":
            # a root container runner (docker images run as root with HOME=/root); /root made writable by the
            # workflow so that no test fails for lack of permissions
            home = Path("/root")
            src = Path(os.path.expanduser("~")) / ".gitconfig"
            try:
                if src.exists() and not (home / ".gitconfig").exists():
                    shutil.copy(src, home / ".gitconfig")
            except OSError as e:
                log(f"/root not writable: {e}")
            self.alt = {"HOME": str(home)}
            self.result["profiles"] = {"0": {"HOME": os.path.expanduser("~")}, "1": self.alt}
        elif self.arm.startswith("ci-"):
            kind = self.arm[3:]
            sc = json.loads((HERE / "changes.json").read_text()).get(self.spec["name"], {}).get(kind)
            if not sc:
                raise SystemExit(f"no {kind} scenario for {self.spec['name']} in changes.json")
            if kind == "dep" and self.lang != "pytest":
                raise SystemExit("ci-dep: Python projects only")
            self.change = sc
            self.result["change"] = dict(sc, land=self.land)
            self.result["profiles"] = {"0": {"before": True}, "1": {"change": sc.get("what")}}
        elif self.arm == "runtime":
            if self.lang == "pytest":
                minor = self.spec.get("py_minor") or "3.13"
                vers = self.python_patches(minor)
                cur = vers[-1] if vers else None
                alt = vers[-3] if len(vers) >= 3 else (vers[0] if vers else None)
                self.alt = {"python": alt}
                self.result["profiles"] = {"0": {"python": cur or minor + " (latest)"}, "1": {"python": alt}}
            else:
                node_dir, ver, cur = self.alt_node()
                self.alt = {"node_bin": str(node_dir / "bin") if node_dir else None}
                self.result["profiles"] = {"0": {"node": cur}, "1": {"node": ver}}
        log(f"arm {self.arm}: profiles {self.result['profiles']}")

    @staticmethod
    def python_patches(minor):
        _, out, _ = sh(["uv", "python", "list", "--all-versions", "--only-downloads", "--output-format", "json"],
                       timeout=300)
        vs = set()
        try:
            for x in json.loads(out[out.index("["):]):
                v = x.get("version", "")
                if v.startswith(minor + ".") and x.get("implementation", "cpython") == "cpython" \
                        and re.fullmatch(r"\d+\.\d+\.\d+", v) and x.get("variant", "default") == "default" \
                        and x.get("os", "linux") == "linux" and x.get("arch", "x86_64") == "x86_64":
                    vs.add(v)
        except Exception:
            for m in re.finditer(r"cpython-(%s\.\d+)-linux" % re.escape(minor), out):
                vs.add(m.group(1))
        return sorted(vs, key=lambda v: tuple(int(p) for p in v.split(".")))

    def alt_node(self):
        _, cur, _ = sh(["node", "--version"], timeout=60)
        cur = cur.strip()
        try:
            major = cur.lstrip("v").split(".")[0]
            idx = json.loads(urllib.request.urlopen("https://nodejs.org/dist/index.json", timeout=60).read())
            same = [x["version"] for x in idx if x["version"].lstrip("v").split(".")[0] == major]
            same.sort(key=lambda v: tuple(int(p) for p in v.lstrip("v").split(".")))
            older = [v for v in same if tuple(int(p) for p in v.lstrip("v").split(".")) <
                     tuple(int(p) for p in cur.lstrip("v").split("."))]
            ver = older[-1] if older else same[0]
            url = f"https://nodejs.org/dist/{ver}/node-{ver}-linux-x64.tar.xz"
            dst = self.work / "node-alt"
            tgz = self.work / "node-alt.tar.xz"
            urllib.request.urlretrieve(url, tgz)
            with tarfile.open(tgz) as t:
                t.extractall(self.work)
            shutil.rmtree(dst, ignore_errors=True)
            (self.work / f"node-{ver}-linux-x64").rename(dst)
            return dst, ver, cur
        except Exception as e:
            log(f"alternate node unavailable: {e}")
            return None, None, cur

    def separate_venvs(self):
        return self.lang == "pytest" and self.arm in ("runtime", "ci-dep")

    def dep_key(self):
        """Profiles have separate installs only in the Python runtime arm (one virtualenv per interpreter) and in the
        dependency-change arm (one virtualenv per resolved dependency set)."""
        return self.profile if self.separate_venvs() else 0

    def profile_at(self, i):
        if self.arm.startswith("ci-"):
            return 0 if i < self.land else 1
        return i % 2 if self.arm else 0

    def set_profile(self, k):
        if k == self.profile:
            return
        if self.separate_venvs():
            park = self.work / f"venv-p{self.profile}"
            nxt = self.work / f"venv-p{k}"
            if self.venv.exists():
                self.venv.rename(park)
            if nxt.exists():
                nxt.rename(self.venv)
        self.profile = k
        self._runtime = None

    def env(self):
        e = super().env()
        if self.profile == 1 and not self.base_env:
            if self.arm in ("env", "home-root"):
                e.update(self.alt)
            elif self.arm == "ci-env":
                e.update(self.change["env"])
            elif self.arm == "runtime" and self.lang != "pytest" and self.alt.get("node_bin"):
                e["PATH"] = self.alt["node_bin"] + ":" + e.get("PATH", "")
        return e

    def install(self):
        self.base_env = True
        try:
            if self.arm == "runtime" and self.lang == "pytest" and self.profile == 1 and self.alt.get("python") \
                    and not (self.venv / "bin" / "python").exists():
                code, out, _ = sh(["uv", "venv", "-q", "--python", self.alt["python"], str(self.venv)], timeout=900)
                log(f"alt venv {self.alt['python']} -> {code} {out[-300:]}")
            ok, why = super().install()
            if ok and self.arm == "ci-dep":
                pins = self.change.get(f"pins{self.profile}") or []
                if pins:
                    code, out, _ = sh(["uv", "pip", "install", "-q", "--python", str(self.venv / "bin" / "python"),
                                       *pins], cwd=self.src, env=self.env(), timeout=1500)
                    log(f"pins p{self.profile} {pins} -> {code} {out[-300:]}")
                    if code:
                        return False, out[-3000:]
                _, fr, _ = sh(["uv", "pip", "freeze", "--python", str(self.venv / "bin" / "python")], timeout=300)
                self.result.setdefault("freeze", {})[str(self.profile)] = fr.splitlines()[:400]
            return ok, why
        finally:
            self.base_env = False
            self._runtime = None

    def checkout(self, sha):
        super().checkout(sha)
        if self.arm == "ci-data" and self.profile == 1:
            st = []
            for ed in self.change["edits"]:
                f = self.src / ed["path"]
                try:
                    t = f.read_bytes()   # bytes: keep line endings (CRLF in recorded HTTP fixtures) as they are
                except OSError:
                    st.append([ed["path"], "missing"])
                    continue
                old, new = (x.encode() for x in ed["replace"])
                if old not in t:
                    st.append([ed["path"], "old-text-not-found"])
                    continue
                f.write_bytes(t.replace(old, new, ed.get("count", 1)))
                st.append([ed["path"], "applied"])
            self.edit_log.append([sha[:12], st])
            self.result["edits"] = self.edit_log

    def build(self):
        self.base_env = True
        try:
            return super().build()
        finally:
            self.base_env = False

    def prewarm(self):
        """First use of the package manager in a new HOME (corepack downloads pnpm): once, before the parallel runs."""
        if self.lang in ("vitest", "jest") and self.arm and self.profile == 1:
            sh(["pnpm", "--version"], cwd=self.src, env=self.env(), timeout=600)

    # -- recording ---------------------------------------------------------------------------------------------------
    def normalize(self, unit, deps, pyrec, envrec=None, env=None):
        out = super().normalize(unit, deps, pyrec, envrec, env)
        if "error" not in out:
            rw = set(deps.get("rw", []))
            out["rw"] = sorted(p for p in out["reads"] if p in rw)
        return out

    # -- rules ------------------------------------------------------------------------------------------------------
    def covered(self, p):
        src = str(self.src) + "/"
        if not p.startswith(src):
            return False
        rel = p[len(src):]
        if "/node_modules/" in "/" + rel or rel.startswith(".s2rec/") or rel.endswith(".d.ts"):
            return False
        if not rel.endswith(CODE_EXT):
            return False
        return rel.endswith((".py", ".pyw")) or not strict_config_hit(rel)

    def rule_decide(self, unit, rec, i_sha, rule):
        """Reason string when ``rule`` reruns the unit, None when it reuses ``rec``."""
        if rec is None:
            return "new"
        d = rec.get("deps")
        if not d or "error" in d:
            return "no-record"
        if rec.get("tests") is None:
            return "no-result"
        if not good(rec.get("code")):
            return "cached-failure"
        if rule in PY_ONLY:
            return self.py_cov_decide(unit, rec, i_sha, rule)
        rw = set(d.get("rw", []))
        for p, h in d["reads"].items():
            if rule == "A":
                if not self.covered(p):
                    continue
            elif p in rw:
                continue
            if self.hasher.file(p) != h:
                return "read:" + self.kind_of(p)
        if rule == "B+":
            for p, k in d["exists"].items():
                if Hasher.kind(p) != k:
                    return "exists:" + self.kind_of(p)
            for p in d["missing"]:
                if os.path.lexists(p):
                    return "appeared:" + self.kind_of(p)
            for p, h in d["lists"].items():
                if Hasher.listing(p) != h:
                    return "listing:" + self.kind_of(p)
            if d.get("py") and self.lang == "pytest":
                tried = set(d["py"]["tried"])
                for f in self.added_since(rec["sha"], i_sha):
                    if not f.endswith((".py", ".so", ".pyi")) and "/" not in f:
                        continue
                    parts = f.rsplit(".", 1)[0].split("/")
                    if parts[-1] == "__init__":
                        parts = parts[:-1]
                    if {".".join(parts[k:]) for k in range(len(parts))} & tried:
                        return "import-resolution"
        return None

    def _py_pair(self, j_sha, i_sha, rel):
        key = (j_sha, i_sha, rel)
        if key not in self._pycache:
            old, new = self.blob(j_sha, rel), self.blob(i_sha, rel)
            if old is None or new is None:
                self._pycache[key] = (None, None, None)
            else:
                same, ch, ok = changed_functions(old, new)
                self._pycache[key] = (set(defs(old) or {}), ch, ok)
        return self._pycache[key]

    def py_cov_decide(self, unit, rec, i_sha, rule):
        d = rec["deps"]
        src = str(self.src) + "/"
        execd = {}
        for f, q in (d.get("py") or {}).get("funcs", []):
            execd.setdefault(f, set()).add(q)
        for p, h in d["reads"].items():
            if not (p.startswith(src) and p.endswith((".py", ".pyw"))) or "/node_modules/" in p:
                continue
            if self.hasher.file(p) == h:
                continue
            rel = p[len(src):]
            if rel == unit:
                return "own-file"
            ran = execd.get(rel)
            if not ran:
                continue
            fdefs, ch, ok = self._py_pair(rec["sha"], i_sha, rel)
            if fdefs is None:
                return "py-unreadable"
            if not ok:
                return "py-syntax"
            ran_funcs = ran & fdefs   # executed functions (not module or class bodies)
            if rule == "Ae" and ran_funcs:
                return "py-executed-file"
            if rule == "Af" and (ch & ran_funcs):
                return "py-executed-function"
        return None

    def discover(self):
        units, total = super().discover()
        extra = [x for x in self.spec.get("dir_units", []) if (self.src / x).is_dir()]
        return sorted(set(units) | set(extra)), total + len(extra)

    def all_changes(self, rec):
        """Every class of change between ``rec`` and now (for attributing a mismatch), not only the first."""
        out = set()
        d = rec.get("deps") or {}
        if not d or "error" in d:
            return ["no-record"]
        rw = set(d.get("rw", []))
        for p, h in d.get("reads", {}).items():
            if self.hasher.file(p) != h:
                out.add(("rw-read:" if p in rw else "read:") + self.kind_of(p))
        for p, k in d.get("exists", {}).items():
            if Hasher.kind(p) != k:
                out.add("exists:" + self.kind_of(p))
        for p in d.get("missing", []):
            if os.path.lexists(p):
                out.add("appeared:" + self.kind_of(p))
        for p, h in d.get("lists", {}).items():
            if Hasher.listing(p) != h:
                out.add("listing:" + self.kind_of(p))
        cur = self.env()
        for n, h in (d.get("env") or {}).items():
            if W.env_value(n, cur) != h:
                out.add("env-var:" + n)
        now = self.runtime()
        for k in sorted(set(d.get("runtime") or {}) | set(now)):
            if (d.get("runtime") or {}).get(k) != now.get(k):
                out.add("runtime:" + k)
        if d.get("net_ext"):
            out.add("network")
        return sorted(out)

    # -- comparison --------------------------------------------------------------------------------------------------
    @staticmethod
    def kind(old, new):
        a = outcome_summary(old.get("tests") or {})
        b = outcome_summary(new.get("tests") or {})
        if a == b and good(old["code"]) == good(new["code"]) and (old["code"] == 0) == (new["code"] == 0):
            return "same", a, b
        bad = (not good(new["code"])) or any(v == "fail" for v in b.values())
        return ("verdict" if bad else "set"), a, b

    # -- main loop ---------------------------------------------------------------------------------------------------
    def walk(self):
        commits = self.commits()
        if self.arm.startswith("ci-"):
            # the change lands as a commit of its own (as a lockfile bump or a fixture edit does): the landing
            # transition repeats the previous commit's code with only the change applied
            n = self.max_commits or len(commits) + 1
            commits = commits[:self.land] + [commits[self.land - 1]] + commits[self.land:n - 1]
            self.result["change"]["land"] = self.land   # index of the landing commit (profile 1 from here on)
        elif self.max_commits:
            commits = commits[:self.max_commits]
        log(f"{self.spec['name']} shard {self.shard}/{self.nshards} arm '{self.arm}': {len(commits)} commits")
        verify = 1.0 if self.arm.startswith("ci-") else self.spec.get("verify", 0.1)
        for i, sha in enumerate(commits):
            if time.time() - W.T_START > self.budget:
                self.result["notes"].append(f"budget reached before commit {i}")
                log("time budget reached")
                break
            t_commit = time.time()
            prev = commits[i - 1] if i else None
            self.set_profile(self.profile_at(i))
            self.checkout(sha)
            row = {"i": i, "sha": sha, "profile": self.profile,
                   "date": git(self.src, "show", "-s", "--format=%cI", sha).strip()}
            dh = self.dep_hash()
            if dh != self.last_dep[self.dep_key()]:
                ok, why = self.install()
                row["installed"] = True
                if not ok:
                    row.update(status="install-failed", detail=why[-800:])
                    self.result["commits"].append(row)
                    self.last_dep[self.dep_key()] = None
                    self.flush()
                    continue
                self.last_dep[self.dep_key()] = dh
            if not self.build():
                row["status"] = "build-failed"
                self.result["commits"].append(row)
                self.flush()
                continue
            self.prewarm()
            units, total_units = self.discover()
            row["units"], row["units_total"] = len(units), total_units
            changed = git(self.src, "diff", "--no-renames", "--name-only", prev, sha).splitlines() if prev else []
            row["changed_files"] = len(changed)
            row["runtime"] = self.runtime()
            if self.lang == "pytest":
                row["interp"] = sh([str(self.venv / "bin" / "python"), "--version"], env=self.env(), timeout=60)[1].strip()
            else:
                row["interp"] = sh(["node", "--version"], env=self.env(), timeout=60)[1].strip()
            dec = {}
            for u in units:
                c = self.decide(u, self.records.get(u), sha, commits)[0]["closure"]
                dec[u] = {"C": c, **{r: self.rule_decide(u, self.rrec[r].get(u), sha, r) for r in self.own}}
            must_c = [u for u in units if dec[u]["C"]]
            must_any = [u for u in units if any(dec[u].values())]
            skip_c = [u for u in units if not dec[u]["C"]]
            ver = [u for u in skip_c if self.rng.random() < verify] if i else []
            torun = sorted(set(must_any) | set(ver))
            log(f"[{i}] {sha[:10]} p{self.profile} units {len(units)} " +
                " ".join(f"{r}:{sum(1 for u in units if dec[u][r])}" for r in self.rules_h) +
                f" verify {len(ver)} run {len(torun)} changed {len(changed)}")
            runs = {}

            def job(u):
                return u, self.run_unit(u, traced_run=True)
            with ThreadPoolExecutor(self.workers) as ex:
                for u, r in ex.map(job, torun):
                    runs[u] = r
            if i == 0 and self.spec.get("plain_baseline", True):
                def pjob(u):
                    return u, self.run_unit(u, traced_run=False, tag="plain")
                with ThreadPoolExecutor(self.workers) as ex:
                    for u, r in ex.map(pjob, units):
                        self.costs[u] = {"test": r["test_time"], "wall": r["wall"], "code": r["code"],
                                         "n": len(r["tests"] or {})}
                ovh = [runs[u]["wall"] / self.costs[u]["wall"] for u in units
                       if u in runs and self.costs.get(u, {}).get("wall")]
                self.result["capture_overhead"] = {"median_ratio": statistics.median(ovh) if ovh else None,
                                                   "n": len(ovh)}
            for u, r in runs.items():
                r.update(sha=sha, i=i, profile=self.profile)
            # comparisons: every rule's skip of a unit that ran fresh here
            checks = {r: {"n": 0, "extra": 0, "sample": 0} for r in self.rules_h}
            mism = []
            reruns = {}
            if i:
                for u in torun:
                    new = runs[u]
                    for r in self.rules_h:
                        if dec[u][r] is not None:
                            continue
                        old = (self.records if r == "C" else self.rrec[r]).get(u)
                        if old is None:
                            continue
                        checks[r]["n"] += 1
                        checks[r]["extra" if dec[u]["C"] else "sample"] += 1
                        checks[r].setdefault("keys", []).append([u, old.get("i")])
                        k, a, b = self.kind(old, new)
                        if k == "same":
                            continue
                        if u not in reruns:
                            reruns[u] = [self.run_unit(u, traced_run=False, tag=f"re{x}") for x in range(2)]
                        rr = reruns[u]
                        item = {"unit": u, "rule": r, "kind": k, "c": dec[u]["C"], "rec_i": old.get("i"),
                                "rec_sha": old.get("sha"), "rec_profile": old.get("profile", 0),
                                "fresh_code": new["code"],
                                "diff": sorted(x for x in set(a) | set(b) if a.get(x) != b.get(x))[:10],
                                "fails": sorted(x for x, v in b.items() if v == "fail")[:10],
                                "changes": self.all_changes(old),
                                "rerun_bad": sum(1 for x in rr if not good(x["code"]) or
                                                 any(v == "fail" for v in outcome_summary(x["tests"] or {}).values())),
                                "rerun_eq_fresh": sum(1 for x in rr if outcome_summary(x["tests"] or {}) == b),
                                "rerun_eq_cache": sum(1 for x in rr if outcome_summary(x["tests"] or {}) == a)}
                        if new.get("tail"):
                            item["tail"] = new["tail"][-400:]
                        if k == "verdict" and item["rerun_bad"] == 2:
                            key = (u, old.get("sha"), old.get("profile", 0))
                            c = self.candidates.setdefault(key, {"rules": [], "at": [], "cached": a,
                                                                 "rec_i": old.get("i")})
                            c["rules"].append(r)
                            c["at"].append(i)
                        mism.append(item)
            # unit costs for units first seen after the baseline
            for u in units:
                if u not in self.costs and u in runs:
                    r = runs[u]
                    ratio = (self.result.get("capture_overhead") or {}).get("median_ratio") or 1.0
                    self.costs[u] = {"test": r["test_time"] / ratio, "wall": r["wall"] / ratio, "code": r["code"],
                                     "n": len(r["tests"] or {}), "est": True}
            # cache refresh: C as in study 2 (every unit it reran or verified); A / B / B+ only what they reran
            for u in must_c + ver:
                if u in runs:
                    self.records[u] = runs[u]
            for r in self.own:
                for u in units:
                    if dec[u][r] is not None and u in runs:
                        self.rrec[r][u] = runs[u]
            if i:
                self.result["transitions"].append({
                    "i": i, "sha": sha, "profile": self.profile, "units": len(units), "changed_files": len(changed),
                    "decisions": {u: {r: dec[u][r] for r in self.rules_h if dec[u][r]} for u in units
                                  if any(dec[u].values())},
                    "checks": checks, "mismatch": mism, "verify_sample": len(ver),
                    "fresh_bad": sorted(u for u, r in runs.items() if not good(r["code"]) or
                                        any(v == "fail" for v in outcome_summary(r["tests"] or {}).values())),
                    "ran": len(runs),
                    "tests": {u: self.costs.get(u, {}).get("n", 0) for u in units}})
            row.update(status="ok", ran=len(runs), seconds=time.time() - t_commit,
                       fails=sum(1 for u in units if not good((runs.get(u) or self.records.get(u) or {}).get("code"))))
            self.result["commits"].append(row)
            self.result["units"] = {u: self.costs.get(u) for u in sorted(self.costs)}
            self.result["unit_info"] = {u: {"nread": len(r.get("deps", {}).get("reads", {})),
                                            "n_rw": r.get("deps", {}).get("n_rw"),
                                            "net_ext": r.get("deps", {}).get("net_ext"),
                                            "env": sorted((r.get("deps", {}).get("env") or {}))[:40],
                                            "code": r.get("code")}
                                        for u, r in self.records.items()}
            if i % 10 == 0 or i == len(commits) - 1:
                self.flush()
        self.recheck()
        self.flush()

    def recheck(self):
        """Re-run each reproducible verdict mismatch at its cached commit (plainly, twice, in the cached profile)."""
        cands = sorted(self.candidates.items(), key=lambda kv: (kv[1]["rec_i"] or 0, kv[0][0]))
        done = 0
        for (u, rec_sha, prof), c in cands:
            item = {"unit": u, "rec_sha": rec_sha, "rec_i": c["rec_i"], "profile": prof, "rules": sorted(set(c["rules"])),
                    "at": sorted(set(c["at"]))}
            if done >= self.max_rechecks or time.time() - W.T_START > self.budget + 900:
                item["status"] = "not-rechecked (budget)"
                self.result["rechecks"].append(item)
                continue
            try:
                self.set_profile(prof)
                self.checkout(rec_sha)
                dh = self.dep_hash()
                if dh != self.last_dep[self.dep_key()]:
                    ok, _ = self.install()
                    self.last_dep[self.dep_key()] = dh if ok else None
                    if not ok:
                        item["status"] = "install-failed"
                        self.result["rechecks"].append(item)
                        continue
                self.build()
                self.prewarm()
                rr = [self.run_unit(u, traced_run=False, tag=f"rb{x}") for x in range(2)]
                item["base_good"] = sum(1 for x in rr if good(x["code"]) and not any(
                    v == "fail" for v in outcome_summary(x["tests"] or {}).values()))
                item["base_eq_cache"] = sum(1 for x in rr if outcome_summary(x["tests"] or {}) == c["cached"])
                item["status"] = "wrong" if item["base_good"] == 2 else "flaky (cached pass not reproducible)"
            except Exception as e:  # keep the walk's data even if one re-check breaks
                item["status"] = f"error: {e}"[:300]
            done += 1
            self.result["rechecks"].append(item)
            log(f"recheck {u} @ {rec_sha[:10]} p{prof}: {item['status']}")
            if done % 5 == 0:
                self.flush()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--budget-min", type=float, default=330)
    ap.add_argument("--run-id", default="local")
    ap.add_argument("--arm", default="", choices=("", "env", "runtime", "home-root", "ci-dep", "ci-data", "ci-env"))
    ap.add_argument("--land", type=int, default=3, help="ci-* arms: index of the commit where the change lands")
    ap.add_argument("--max-commits", type=int, default=0)
    ap.add_argument("--max-rechecks", type=int, default=80)
    a = ap.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text())
    s, n = (int(x) for x in a.shard.split("/"))
    w = H2H(spec, a.work, a.out, s, n, a.budget_min, a.run_id, a.arm, a.max_commits, a.max_rechecks, a.land)
    w.walk()
    return 0


if __name__ == "__main__":
    sys.exit(main())
