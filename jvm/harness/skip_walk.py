#!/usr/bin/env python3
"""Skip with proof over consecutive commits of a Java/Kotlin repository (Gradle or Maven).

For each commit of a shard (oldest first), the whole test suite runs with the
capture on (`fenvix-jvm run --det --deps`), so every test has a fresh outcome.
For each transition (previous commit -> this commit) the proof rule
(jvm/skip/fenvix_skip.py) decides, from the previous capture and the state of
this commit, which tests could have been reused; each reuse is then checked
against the fresh outcome of this commit: a reused test that does not pass now
is WRONG (a rerun of its class twice tells a flaky test from a wrong skip).

Also computed per transition, as a comparison: a per-module cache in the style
of Gradle's build cache for test tasks (ESTIMATED model: a module's tests are
reused when every class and resource file of the module's build output and
the module's dependency jars are byte-identical; per task, not per test).

  python3 skip_walk.py --repo NAME --shard K --shards N [--commits 50]
"""
import argparse, glob, hashlib, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
JVM = os.path.dirname(HERE)
AGENT = os.path.join(JVM, "dist", "fenvix-agent.jar")
sys.path.insert(0, os.path.join(JVM, "skip"))
import fenvix_skip  # noqa: E402

REPOS = json.load(open(os.path.join(HERE, "skip_repos.json")))
MVN_SKIPS = ["-Dmaven.javadoc.skip=true", "-Drat.skip=true", "-Dcheckstyle.skip=true", "-Denforcer.skip=true",
             "-Dspotbugs.skip=true", "-Dlicense.skip=true", "-Dgpg.skip=true", "-Djacoco.skip=true", "-Danimal.sniffer.skip=true",
             "-Dmaven.source.skip=true", "-Dpmd.skip=true", "-Dspotless.check.skip=true", "-Djapicmp.skip=true",
             "-Drevapi.skip=true", "-Dmoditect.skip=true", "-Dbnd.skip=true", "-Dmaven.site.skip=true", "-Dinvoker.skip=true"]


def sh(cmd, cwd=None, env=None, timeout=None, log=None):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           errors="replace")
        out, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = str(e.stdout)[-5000:], -9
    if log:
        with open(log, "a") as f:
            f.write(f"$ {' '.join(cmd)}\n{out[-8000:]}\n[rc={rc} {time.time() - t0:.1f}s]\n")
    return rc, out, time.time() - t0


def env_for(spec):
    env = dict(os.environ)
    home = os.environ.get(f"JAVA_HOME_{spec.get('jdk', '17')}_X64")
    if home:
        env["JAVA_HOME"] = home
        env["PATH"] = home + "/bin:" + env["PATH"]
    env["GRADLE_OPTS"] = "-Dorg.gradle.daemon=false -Dorg.gradle.jvmargs=-Xmx3g"
    env["MAVEN_OPTS"] = "-Xmx3g"
    return env


def commits(repo, spec, n):
    before = [f"--before={spec['before']}"] if spec.get("before") else []
    rc, out, _ = sh(["git", "rev-list", "--first-parent", f"-n{n + 1}", *before, spec.get("ref", "HEAD")], cwd=repo)
    return list(reversed(out.split()))


def test_cmd(spec, out):
    if spec["tool"] == "maven":
        cmd = ["mvn", "-B", "-q", "test", "-Dmaven.test.failure.ignore=true", "-DfailIfNoTests=false",
               "-Dsurefire.failIfNoSpecifiedTests=false", *MVN_SKIPS, *spec.get("args", [])]
    else:
        cmd = ["./gradlew", "--no-daemon", "-q", "--continue", *spec.get("tasks", ["test"]), *spec.get("args", [])]
    return ["java", "-jar", AGENT, "run", "--det", "--deps", f"--out={out}", "--"] + cmd


def module_cache_keys(repo, spec, deps_dir):
    """ESTIMATED model of a per-module test-task cache: digest of the build output files plus the jar list (Gradle) or poms (Maven; the whole reactor, one key)."""
    mods = fenvix_skip.load(deps_dir)
    keys = {}
    for mn, m in mods.items():
        jvm = m["jvm"]
        if not jvm:
            continue
        h = hashlib.sha256()
        entries = list(jvm.get("classpath", []))
        if spec["tool"] == "maven":
            # Surefire's class path is a manifest-only booter jar: use the reactor's build output
            # directories and the poms (dependency versions) instead
            for root, dirs, files in sorted(os.walk(repo)):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                if os.path.basename(root) == "target":
                    entries += [os.path.join(root, d) for d in ("classes", "test-classes") if d in dirs]
                    dirs[:] = []
                if "pom.xml" in files:
                    with open(os.path.join(root, "pom.xml"), "rb") as fh:
                        h.update(hashlib.sha256(fh.read()).digest())
        for entry in entries:
            if entry.endswith(".jar"):
                h.update(("jar:" + entry.split("/.m2/")[-1].split("/files-2.1/")[-1] + "\n").encode())
            elif os.path.isdir(entry):
                for root, _, files in sorted(os.walk(entry)):
                    for f in sorted(files):
                        p = os.path.join(root, f)
                        h.update(os.path.relpath(p, repo).encode())
                        with open(p, "rb") as fh:
                            h.update(hashlib.sha256(fh.read()).digest())
        h.update(json.dumps(jvm.get("runtime", {}), sort_keys=True).encode())
        keys[mn] = h.hexdigest()
    return keys


def rerun_class(repo, spec, tid, log):
    """Run one test class twice without the cache; outcomes of the test (flaky evidence)."""
    cls = tid.split("::")[-2] if "::" in tid else tid
    outs = []
    for i in range(2):
        out = f"/tmp/rerun-{i}"
        shutil.rmtree(out, ignore_errors=True)
        if spec["tool"] == "maven":
            cmd = ["mvn", "-B", "-q", "surefire:test", f"-Dtest={cls}", "-DfailIfNoTests=false", "-Dsurefire.failIfNoSpecifiedTests=false",
                   "-Dmaven.test.failure.ignore=true"]
        else:
            cmd = ["./gradlew", "--no-daemon", "-q", "--continue", "test", "--tests", cls]
        sh(["java", "-jar", AGENT, "run", "--det", "--deps", f"--out={out}", "--"] + cmd, cwd=repo, env=env_for(spec), timeout=1800, log=log)
        found = None
        for f in glob.glob(os.path.join(out, "deps", "*.jsonl")):
            for line in open(f):
                o = json.loads(line)
                if o.get("type") == "test" and o["id"] == tid:
                    found = o.get("outcome")
        outs.append(found)
    return outs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--commits", type=int, default=50)
    ap.add_argument("--work", default="/tmp/walk")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "skip"))
    ap.add_argument("--budget", type=float, default=5.3 * 3600)
    a = ap.parse_args()
    spec = REPOS[a.repo]
    t_start = time.time()
    a.work = os.path.abspath(a.work)
    out = os.path.abspath(os.path.join(a.out, a.repo))
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, f"shard{a.shard}.log")
    repo = os.path.join(a.work, a.repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        sh(["git", "clone", "-q", spec["url"], repo], log=log, timeout=1800)
    if spec.get("pin"):
        sh(["git", "checkout", "-q", spec["pin"]], cwd=repo, log=log)
    all_c = spec.get("shas") or commits(repo, spec, a.commits)
    # shard k walks transitions [k*per, (k+1)*per): commits [k*per, (k+1)*per]
    per = -(-(len(all_c) - 1) // a.shards)
    mine = all_c[a.shard * per: min(len(all_c), (a.shard + 1) * per + 1)]
    rows = []
    prev = None
    for i, sha in enumerate(mine):
        if time.time() - t_start > a.budget:
            break
        sh(["git", "checkout", "-q", "-f", sha], cwd=repo, log=log)
        sh(["git", "clean", "-qfdx", "-e", ".gradle"], cwd=repo, log=log)
        cap = os.path.join(a.work, "cap", sha)
        shutil.rmtree(cap, ignore_errors=True)
        rc, _, secs = sh(test_cmd(spec, cap), cwd=repo, env=env_for(spec), timeout=3 * 3600, log=log)
        deps = os.path.join(cap, "deps")
        if not glob.glob(os.path.join(deps, "*.jsonl")):
            rows.append({"sha": sha, "status": "no-capture", "rc": rc, "seconds": round(secs, 1)})
            prev = None
            continue
        mods_b = fenvix_skip.load(deps)
        keys_b = module_cache_keys(repo, spec, deps)
        tests_b = {(mn, t): r for mn, m in mods_b.items() for t, r in m["tests"].items()}
        total_ms = sum(r.get("ms") or 0 for r in tests_b.values())
        row = {"sha": sha, "status": "ok", "rc": rc, "seconds": round(secs, 1), "tests": len(tests_b), "test_ms": round(total_ms),
               "failed": sum(1 for r in tests_b.values() if r.get("outcome") == "failed")}
        if prev is not None:
            mods_a, keys_a = prev
            d = fenvix_skip.decide(mods_a, fenvix_skip.State(mods_b, repo))
            reused = [k for k, r in d.items() if r is None and k in tests_b]
            reasons, details = {}, {}
            for k, r in d.items():
                if r is not None:
                    reasons[r[0]] = reasons.get(r[0], 0) + 1
                    dk = f"{r[0]}: {r[1]}"
                    details[dk] = details.get(dk, 0) + 1
            wrong, flaky = [], []
            for k in reused:
                if tests_b[k].get("outcome") != "passed":
                    re_o = rerun_class(repo, spec, k[1], log)
                    (flaky if "passed" in re_o and "failed" in re_o + [tests_b[k].get("outcome")] else wrong).append(
                        {"test": k[1], "module": k[0], "fresh": tests_b[k].get("outcome"), "reruns": re_o})
            skipped_ms = sum(tests_b[k].get("ms") or 0 for k in reused)
            mod_hit = [mn for mn in keys_b if keys_a.get(mn) == keys_b[mn]]
            mod_ms = sum(r.get("ms") or 0 for (mn, _), r in tests_b.items() if mn in mod_hit)
            row.update({"prev": mine[i - 1], "reused": len(reused), "verified": len(reused), "wrong": wrong, "flaky": flaky,
                        "share_time_skipped": round(skipped_ms / total_ms, 4) if total_ms else None,
                        "share_tests_skipped": round(len(reused) / len(tests_b), 4) if tests_b else None,
                        "rerun_reasons": reasons,
                        "rerun_details": dict(sorted(details.items(), key=lambda x: -x[1])[:6]), "module_cache_hits": len(mod_hit), "modules": len(keys_b),
                        "module_cache_share_time": round(mod_ms / total_ms, 4) if total_ms else None})
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k not in ("wrong", "flaky")}), flush=True)
        json.dump({"repo": a.repo, "spec": spec, "shard": a.shard, "shards": a.shards, "rows": rows},
                  open(os.path.join(out, f"shard{a.shard}.json"), "w"), indent=1)
        prev = (mods_b, keys_b)
        # keep the previous capture only
        for old in glob.glob(os.path.join(a.work, "cap", "*")):
            if not old.endswith(sha):
                shutil.rmtree(old, ignore_errors=True)


if __name__ == "__main__":
    main()
