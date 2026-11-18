#!/usr/bin/env python3
"""JVM measurement round on projects with documented flaky tests (IDoFT), Maven.

One project per invocation (one GitHub Actions job per project):

  prepare  clone at the pinned commit, build the module (JDK 11, then 17),
           one baseline run: keep the project if it builds, its suite ends
           within --max-first-run seconds and runs at least one documented test.
  round    the protocol below; writes <out>/<name>/summary.json and tests.json.

Protocol (the Python and Node rounds, adapted):

  baseline   B runs of the module's suite as the project configures it, with a
             realistic random order: Surefire runOrder=random (classes) and,
             for JUnit 5, MethodOrderer$Random (methods), a new seed per run.
  det        D runs with --det (seed 0, fixed order); traces verified together
             (fingerprint coverage = tests with one fingerprint in all D runs).
  seeds      one run per seed 1..S with --det-seed=N (reproducible shuffle).
  confirm    for every target test (baseline-unstable or documented) that
             failed under some --det configuration and passed under another:
             C runs of the first failing configuration; reproduced = fails C/C
             with one fingerprint.
  timing     quiet serial pass: T runs without --det (project order, no
             randomisation) and T runs with --det, sum of the suite's test
             times from the Surefire reports (NOISY on shared runners).

Metrics: documented tests reproduced; baseline-unstable tests reproduced
(strict); broken by --det (fail in >= 1 --det seed-0 run, in <= 1 baseline
run, and more often under --det than in the baseline); fingerprint coverage;
slowdown.
"""
import argparse, glob, json, os, re, shutil, statistics, subprocess, sys, time, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
SKIPS = ["-Dmaven.javadoc.skip=true", "-Drat.skip=true", "-Dcheckstyle.skip=true", "-Denforcer.skip=true",
         "-Dspotbugs.skip=true", "-Dfindbugs.skip=true", "-Dlicense.skip=true", "-Dgpg.skip=true", "-Djacoco.skip=true",
         "-Danimal.sniffer.skip=true", "-Dmaven.source.skip=true", "-Dpmd.skip=true", "-Dcpd.skip=true",
         "-Dspotless.check.skip=true", "-Dspotless.apply.skip=true", "-Dformatter.skip=true", "-Dmdep.analyze.skip=true",
         "-Dbasepom.check.skip-all=true", "-Dmaven.site.skip=true", "-Dsortpom.skip=true", "-Dimpsort.skip=true",
         "-Djapicmp.skip=true", "-Drevapi.skip=true", "-Dmaven.gitcommitid.skip=true", "-Dbuildnumber.skip=true",
         "-Dlombok.delombok.skip=true", "-Dinvoker.skip=true", "-Dcobertura.skip=true", "-Dfmt.skip=true",
         "-Dmaven.antrun.skip=true", "-Dxml-format.skip=true", "-Dspring-javaformat.skip=true", "-Dmodernizer.skip=true"]


def name_of(c):
    return c["url"].rstrip("/").split("/")[-1] + ("" if c["module"] in (".", "") else "-" + c["module"].split("/")[-1])


def sh(cmd, cwd=None, env=None, timeout=None, log=None):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           errors="replace")
        out, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), -9
    if log:
        with open(log, "a") as f:
            f.write(f"$ {' '.join(cmd)}\n{out[-20000:]}\n[rc={rc} {time.time() - t0:.1f}s]\n")
    return rc, out, time.time() - t0


def java_env(jdk):
    env = dict(os.environ)
    home = os.environ.get(f"JAVA_HOME_{jdk}_X64")
    if home:
        env["JAVA_HOME"] = home
        env["PATH"] = home + "/bin:" + env["PATH"]
    env["MAVEN_OPTS"] = "-Xmx2g"
    return env


def module_dir(repo, c):
    return repo if c["module"] in (".", "") else os.path.join(repo, c["module"])


def pl(c):
    return [] if c["module"] in (".", "") else ["-pl", c["module"]]


# ------------------------------------------------------------------ results
def norm(cls, name):
    """class::method, parameters and invocation indexes dropped (one row per test method)."""
    m = re.split(r"[(\[]", name, 1)[0].strip()
    return f"{cls}::{m}"


def results(mdir):
    out, total = {}, 0.0
    for f in glob.glob(os.path.join(mdir, "target", "surefire-reports", "TEST-*.xml")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        try:
            total += float(root.get("time") or 0)
        except ValueError:
            pass
        for tc in root.iter("testcase"):
            tid = norm(tc.get("classname") or "", tc.get("name") or "")
            if tc.find("skipped") is not None:
                o = "skipped"
            elif tc.find("failure") is not None or tc.find("error") is not None:
                o = "failed"
            else:
                o = "passed"
            prev = out.get(tid)
            out[tid] = "failed" if "failed" in (prev, o) else (prev or o)
    return out, total


def trace_fps(trace):
    """normalised id -> list of fingerprints (one per invocation) from a merged trace."""
    fps = {}
    if not trace or not os.path.exists(trace):
        return fps
    for line in open(trace):
        o = json.loads(line)
        if o.get("type") != "test":
            continue
        parts = o["nodeid"].split("::")
        if len(parts) < 2:
            continue
        cls, name = parts[-2], parts[-1]
        # nested classes: a.B::Inner::m -> a.B$Inner::m
        if len(parts) > 2 and "." not in parts[-2] and "." in parts[-3]:
            cls = parts[-3] + "$" + parts[-2]
        fps.setdefault(norm(cls, name), []).append(o["fingerprint"])
    return fps


class Runner:
    def __init__(self, c, repo, out, jdk, run_timeout):
        self.c, self.repo, self.out, self.jdk, self.run_timeout = c, repo, out, jdk, run_timeout
        self.mdir = module_dir(repo, c)
        self.log = os.path.join(out, "runs.log")
        self.n = 0

    def test_cmd(self, extra=()):
        return ["mvn", "-B", "-q", "surefire:test", *pl(self.c), "-Dmaven.test.failure.ignore=true",
                "-DfailIfNoTests=false", "-Dsurefire.failIfNoSpecifiedTests=false", "-DtrimStackTrace=true",
                "-Djacoco.skip=true", *extra]

    def run(self, mode, seed=None, randomize=False):
        """mode: base | det. Returns (outcomes, test seconds, trace path or None, wall seconds)."""
        shutil.rmtree(os.path.join(self.mdir, "target", "surefire-reports"), ignore_errors=True)
        self.n += 1
        extra = []
        if randomize:
            extra += ["-Dsurefire.runOrder=random", f"-Dsurefire.runOrder.random.seed={int(time.time() * 1000) % 2**31}",
                      "-Djunit.jupiter.testmethod.order.default=org.junit.jupiter.api.MethodOrderer$Random",
                      f"-Djunit.jupiter.execution.order.random.seed={int(time.time() * 997) % 2**31}"]
        cmd = self.test_cmd(extra)
        trace = None
        if mode == "det":
            fdir = os.path.join(self.out, "fx", f"r{self.n}")
            cmd = ["java", "-jar", AGENT, "run", f"--det-seed={seed or 0}", f"--out={fdir}", "--"] + cmd
            trace = os.path.join(fdir, "trace.jsonl")
        rc, _, wall = sh(cmd, cwd=self.repo, env=java_env(self.jdk), timeout=self.run_timeout, log=self.log)
        o, t = results(self.mdir)
        if trace and not os.path.exists(trace):
            trace = None
        return {"outcomes": o, "test_seconds": t, "trace": trace, "wall": wall, "rc": rc}


def verify(traces):
    traces = [t for t in traces if t]
    if len(traces) < 2:
        return {}
    r = subprocess.run(["java", "-jar", AGENT, "verify", "--json", *traces], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


# ------------------------------------------------------------------ prepare
def prepare(c, work, out, max_first_run, jdks):
    name = name_of(c)
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "prepare.log")
    repo = os.path.join(work, name)
    res = {"name": name, **{k: c[k] for k in ("url", "sha", "module")}, "status": "?"}
    if not os.path.isdir(os.path.join(repo, ".git")):
        rc, _, _ = sh(["git", "clone", "-q", "--filter=blob:none", c["url"], repo], log=log, timeout=1200)
        if rc != 0:
            res["status"] = "clone-failed"
            return res, None
    sh(["git", "fetch", "-q", "origin", c["sha"]], cwd=repo, log=log, timeout=600)
    rc, _, _ = sh(["git", "checkout", "-q", "-f", c["sha"]], cwd=repo, log=log)
    if rc != 0:
        res["status"] = "checkout-failed"
        return res, None
    if not os.path.exists(os.path.join(repo, "pom.xml")):
        res["status"] = "not-maven"
        return res, None
    ok = False
    for jdk in jdks:
        for compat in ([], ["-Dmaven.compiler.source=1.8", "-Dmaven.compiler.target=1.8", "-Dmaven.compiler.release="]):
            rc, outp, secs = sh(["mvn", "-B", "-q", "-DskipTests", *SKIPS, *compat, "install", *pl(c), *(["-am"] if pl(c) else [])],
                                cwd=repo, env=java_env(jdk), timeout=2400, log=log)
            res[f"build_jdk{jdk}{'_compat' if compat else ''}"] = {"rc": rc, "seconds": round(secs, 1)}
            if rc == 0:
                ok = True
                break
        if ok:
            break
    if not ok:
        res["status"] = "build-failed"
        return res, None
    res["jdk"] = jdk
    r = Runner(c, repo, out, jdk, max_first_run * 3)
    first = r.run("base", randomize=True)
    res["first_run"] = {"wall": round(first["wall"], 1), "test_seconds": round(first["test_seconds"], 1), "tests": len(first["outcomes"]),
                        "failed": sum(v == "failed" for v in first["outcomes"].values())}
    documented = [t for t in c["tests"] if any(k.endswith("::" + t.split(".")[-1]) and k.startswith(".".join(t.split(".")[:-1]) + "::")
                                               for k in first["outcomes"])]
    res["documented_present"] = len(documented)
    if not first["outcomes"]:
        res["status"] = "no-tests-ran"
    elif first["wall"] > max_first_run:
        res["status"] = "too-slow"
    elif not documented:
        res["status"] = "documented-tests-absent"
    else:
        res["status"] = "ok"
    return res, r


def doc_ids(c):
    out = {}
    for t, cat in c["tests"].items():
        cls, _, m = t.rpartition(".")
        out[f"{cls}::{m}"] = cat
    return out


# ------------------------------------------------------------------ round
def round_(c, r: Runner, out, a):
    t_start = time.time()
    budget = a.budget
    over = lambda: time.time() - t_start > budget  # noqa: E731
    base = [r.run("base", randomize=True) for _ in range(a.runs)]
    det = [r.run("det", seed=0) for _ in range(a.runs)]
    ids = sorted(set().union(*[set(x["outcomes"]) for x in base + det]))
    doc = doc_ids(c)

    def fails(runs, t):
        return sum(x["outcomes"].get(t) == "failed" for x in runs)

    def passes(runs, t):
        return sum(x["outcomes"].get(t) == "passed" for x in runs)

    unstable = [t for t in ids if fails(base, t) and passes(base, t)]
    targets = sorted(set(unstable) | (set(doc) & set(ids)))
    seed_runs = {0: det}
    explored = 0
    for s in range(1, a.seeds + 1):
        if over():
            break
        seed_runs[s] = [r.run("det", seed=s)]
        explored = s
    det_all = [x for runs in seed_runs.values() for x in runs]
    state = {}
    confirm_cache = {}
    for t in targets:
        fail_cfg = next((s for s, runs in seed_runs.items() if fails(runs, t)), None)
        pass_any = any(passes(runs, t) for runs in seed_runs.values())
        st = {"fail_seed": fail_cfg, "passes_somewhere": pass_any, "reproduced": False, "confirm": ""}
        if fail_cfg is not None and pass_any and not over():
            if fail_cfg not in confirm_cache:
                runs = list(seed_runs[fail_cfg][:a.confirm]) if fail_cfg == 0 else list(seed_runs[fail_cfg])
                while len(runs) < a.confirm and not over():
                    runs.append(r.run("det", seed=fail_cfg))
                confirm_cache[fail_cfg] = (runs, verify([x["trace"] for x in runs]))
            runs, v = confirm_cache[fail_cfg]
            nf = fails(runs, t)
            fps = set()
            for x in runs:
                fp = trace_fps(x["trace"]).get(t)
                if fp:
                    fps.add(tuple(fp))
            st["confirm"] = f"{nf}/{len(runs)}"
            st["fingerprints"] = len(fps)
            st["reproduced"] = len(runs) >= a.confirm and nf == len(runs) and len(fps) == 1
        state[t] = st
    # fingerprint coverage over the D seed-0 runs
    fp_by_test = {}
    for x in det:
        for t, f in trace_fps(x["trace"]).items():
            fp_by_test.setdefault(t, set()).add(tuple(f))
    covered = [t for t, f in fp_by_test.items() if len(f) == 1 and all(t in trace_fps_cache(x) for x in det if x["trace"])]
    broken = [t for t in ids if fails(det, t) >= 1 and fails(base, t) <= 1 and fails(det, t) > fails(base, t)]
    # timing pass (serial, quiet as the runner allows)
    timing = {"base": [], "det": []}
    if not over():
        for _ in range(a.timing):
            timing["base"].append(r.run("base")["test_seconds"])
            timing["det"].append(r.run("det", seed=0)["test_seconds"])
    tb = statistics.median(timing["base"]) if timing["base"] else None
    td = statistics.median(timing["det"]) if timing["det"] else None
    rows = []
    for t in ids:
        st = state.get(t, {})
        rows.append({"test": t, "documented": doc.get(t, ""), "baseline": f"{fails(base, t)}F/{passes(base, t)}P",
                     "det": f"{fails(det, t)}F/{passes(det, t)}P", "baseline_unstable": t in unstable,
                     "seeds_failing": [s for s, runs in seed_runs.items() if fails(runs, t)],
                     "reproduced": st.get("reproduced", False), "confirm": st.get("confirm", ""),
                     "fingerprint_covered": t in covered, "broken_by_det": t in broken})
    doc_present = [t for t in doc if t in ids]
    summary = {
        "name": name_of(c), "url": c["url"], "sha": c["sha"], "module": c["module"], "jdk": r.jdk,
        "runs": a.runs, "seeds_explored": explored, "seed_budget_hit": explored < a.seeds, "confirm": a.confirm,
        "tests": len(ids), "documented": len(doc), "documented_present": len(doc_present),
        "documented_categories": dict(sorted({cat: sum(1 for t in doc_present if doc[t] == cat) for cat in set(doc.values())}.items())),
        "documented_reproduced": sum(1 for t in doc_present if state.get(t, {}).get("reproduced")),
        "documented_unstable_in_baseline": sum(1 for t in doc_present if t in unstable),
        "unstable_baseline": len(unstable),
        "unstable_reproduced": sum(1 for t in unstable if state.get(t, {}).get("reproduced")),
        "unstable_under_det_seed0": sum(1 for t in ids if fails(det, t) and passes(det, t)),
        "broken_by_det": len(broken), "broken_tests": broken[:50],
        "fingerprint_coverage": f"{len(covered)}/{len(fp_by_test)}",
        "fingerprint_covered": len(covered), "fingerprinted": len(fp_by_test),
        "timing_base_s": timing["base"], "timing_det_s": timing["det"],
        "slowdown": None if not tb or not td else round((td - tb) / tb, 4),
        "seconds": round(time.time() - t_start, 1),
    }
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
    json.dump(rows, open(os.path.join(out, "tests.json"), "w"), indent=1)
    return summary


_FPC = {}


def trace_fps_cache(x):
    k = x["trace"]
    if k not in _FPC:
        _FPC[k] = trace_fps(k)
    return _FPC[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=os.path.join(HERE, "idoft_candidates.json"))
    ap.add_argument("--name", required=True)
    ap.add_argument("--mode", choices=["prepare", "round"], required=True)
    ap.add_argument("--work", default="/tmp/jvm-work")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "idoft"))
    ap.add_argument("--max-first-run", type=float, default=300)
    ap.add_argument("--jdks", default="11,17")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--confirm", type=int, default=10)
    ap.add_argument("--timing", type=int, default=3)
    ap.add_argument("--budget", type=float, default=4 * 3600)
    a = ap.parse_args()
    cands = json.load(open(a.candidates))
    c = next(x for x in cands if name_of(x) == a.name)
    out = os.path.join(a.out, a.name)
    os.makedirs(out, exist_ok=True)
    res, r = prepare(c, a.work, out, a.max_first_run, a.jdks.split(","))
    json.dump(res, open(os.path.join(out, "prepare.json"), "w"), indent=1)
    print(json.dumps(res))
    if a.mode == "round" and res["status"] == "ok":
        s = round_(c, r, out, a)
        print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
