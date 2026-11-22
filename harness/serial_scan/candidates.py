#!/usr/bin/env python3
"""Step 4: try candidates. Shallow-clone each selected repository at its pinned commit,
install, and collect its suite (list tests without running them). Every attempt goes to
raw/candidate_trials.jsonl; the ones that install AND collect (exit 0, >0 tests listed)
go to candidates.json, newest pinned commit first.

Selection (from scan.jsonl): running serially, runner in jest/vitest/mocha/pytest/go,
test_count_estimate >= 10, readable, not archived; ordered multi_core_runner first, then
reason_kind stated > implied > none, then stars.

Installs run with a scrubbed environment (env -i, own HOME) in the scratch directory.
Usage: python3 harness/serial_scan/candidates.py <workdir> [max_trials] [target_passes]
"""
import json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
PLAN_ONLY = os.environ.get("SERIAL_SCAN_PLAN_ONLY") == "1"
RUNNERS = {"jest", "vitest", "mocha", "pytest", "go"}
INSTALL_TIMEOUT, COLLECT_TIMEOUT = 1200, 900


def env_for(home):
    keep = {k: os.environ[k] for k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy",
                                       "no_proxy", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE",
                                       "PIP_CERT", "GIT_SSL_CAINFO") if k in os.environ}
    keep.update({"PATH": "/opt/node22/bin:/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin", "HOME": home,
                 "CI": "true", "GOPATH": os.path.join(home, "go"), "GOFLAGS": "-mod=mod",
                 "npm_config_cache": os.path.join(home, ".npm"), "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
                 "PUPPETEER_SKIP_DOWNLOAD": "1", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                 "CYPRESS_INSTALL_BINARY": "0", "LANG": "C.UTF-8"})
    return keep


def sh(cmd, cwd, env, timeout):
    t = time.time()
    try:
        p = subprocess.run(["bash", "-lc" if False else "-c", cmd], cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr), round(time.time() - t, 1)
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s", round(time.time() - t, 1)


def node_plan(root, sub, exists, read):
    try:
        pkg = json.loads(read("package.json") or "{}")
    except Exception:
        pkg = {}
    pm = pkg.get("packageManager", "")
    if exists("pnpm-lock.yaml"):
        ver = pm.split("@")[1].split("+")[0] if pm.startswith("pnpm@") else "9"
        install = f"npx -y pnpm@{ver} install --frozen-lockfile"
        exe = f"npx -y pnpm@{ver} exec"
    elif exists("yarn.lock"):
        if exists(".yarnrc.yml"):
            ver = pm.split("@")[1].split("+")[0] if pm.startswith("yarn@") else "4.5.0"
            install = f"npx -y @yarnpkg/cli-dist@{ver} install --immutable" if False else f"corepack yarn@{ver} install --immutable"
            exe = f"corepack yarn@{ver} exec"
        else:
            install = "npx -y yarn@1.22.22 install --frozen-lockfile --ignore-engines"
            exe = "npx --no-install"
    elif exists("package-lock.json"):
        install, exe = "npm ci --no-audit --no-fund", "npx --no-install"
    else:
        install, exe = "npm install --no-audit --no-fund", "npx --no-install"
    return install, exe


def plan(row, root, exists=None, read=None):
    exists = exists or (lambda p: os.path.exists(os.path.join(root, p)))
    read = read or (lambda p: open(os.path.join(root, p)).read() if os.path.exists(os.path.join(root, p)) else None)
    runner = row["runner"]
    sub = os.path.dirname(row["file"]) if os.path.basename(row["file"]) in ("package.json", "pyproject.toml", "pytest.ini",
                                                                            "setup.cfg", "tox.ini", "go.mod") or re.search(r"(jest|vitest|vite)\.config", row["file"]) else ""
    if sub.startswith(".github"):
        sub = ""
    if runner in ("jest", "vitest", "mocha"):
        install, exe = node_plan(root, sub, exists, read)
        cd = f"cd {sub} && " if sub else ""
        collect = {"jest": f"{cd}{exe} jest --listTests",
                   "vitest": f"{cd}{exe} vitest list --passWithNoTests",
                   "mocha": f"{cd}{exe} mocha --dry-run"}[runner]
        return install, collect
    if runner == "pytest":
        cands = []
        for extra in ("test", "tests", "testing", "dev"):
            cands.append(f".venv/bin/pip install -q -e '.[{extra}]'")
        reqs = [p for p in ("requirements-dev.txt", "requirements-test.txt", "requirements/test.txt", "requirements/dev.txt",
                            "test-requirements.txt", "dev-requirements.txt", "requirements_dev.txt", "requirements.txt")
                if exists(p)]
        req = " && ".join(f".venv/bin/pip install -q -r {r}" for r in reqs[:2])
        base = "python3 -m venv .venv && .venv/bin/pip install -q -U pip"
        if exists("pyproject.toml") or exists("setup.py"):
            ext = " || ".join(cands) + " || .venv/bin/pip install -q -e ."
            install = f"{base} && ({ext})" + (f" && {req}" if req else "") + " && .venv/bin/pip install -q pytest"
        else:
            install = f"{base}" + (f" && {req}" if req else "") + " && .venv/bin/pip install -q pytest"
        return install, ".venv/bin/python -m pytest --collect-only -q -p no:cacheprovider"
    if runner == "go":
        modroot = sub if sub and exists(sub + "/go.mod") else ""
        cd = f"cd {modroot} && " if modroot else ""
        return f"{cd}go mod download", f"{cd}go test -count=1 -list '.*' ./..."
    return None, None


def count_collected(runner, out):
    if runner == "jest":
        return sum(1 for l in out.splitlines() if re.search(r"\.(test|spec)\.[cm]?[jt]sx?$|__tests__/|/tests?/", l))
    if runner == "vitest":
        return sum(1 for l in out.splitlines() if re.search(r"\.[cm]?[jt]sx? > ", l))
    if runner == "mocha":
        m = re.findall(r"(\d+) passing", out)
        return int(m[-1]) if m else 0
    if runner == "pytest":
        m = re.findall(r"(\d+) tests? collected", out) or re.findall(r"^(\d+) tests? collected", out, re.M)
        if not m:
            m = re.findall(r"collected (\d+) items?", out)
        return int(m[-1]) if m else 0
    if runner == "go":
        return sum(1 for l in out.splitlines() if re.match(r"^(Test|Example|Benchmark|Fuzz)\w*$", l))
    return 0


def trial(row, workdir):
    repo = row["repo"]
    d = os.path.join(workdir, repo.replace("/", "__"))
    home = os.path.join(workdir, "_home_" + repo.replace("/", "__"))
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(home, exist_ok=True)
    rec = {"repo": repo, "commit": row["commit"], "runner": row["runner"], "flag": row["flag"],
           "file": row["file"], "line": row["line"], "reason_kind": row["reason_kind"],
           "multi_core_runner": row["multi_core_runner"], "stars": row["stars"]}
    p = subprocess.run(["git", "clone", "-q", "--depth", "1", f"https://github.com/{repo}", d],
                       capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        rec.update(status="clone_failed", log=p.stderr[-800:])
        return rec
    head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != row["commit"]:
        subprocess.run(["git", "-C", d, "fetch", "-q", "--depth", "1", "origin", row["commit"]], capture_output=True)
        c = subprocess.run(["git", "-C", d, "checkout", "-q", row["commit"]], capture_output=True, text=True)
        if c.returncode != 0:
            rec.update(status="pin_failed", log=c.stderr[-800:])
            shutil.rmtree(d, ignore_errors=True)
            return rec
    rec["commit_date"] = subprocess.run(["git", "-C", d, "log", "-1", "--format=%cI"], capture_output=True, text=True).stdout.strip()
    install, collect = plan(row, d)
    rec["install_cmd"], rec["collect_cmd"] = install, collect
    env = env_for(home)
    code, out, secs = sh(install, d, env, INSTALL_TIMEOUT)
    rec.update(install_exit=code, install_seconds=secs)
    if code != 0:
        rec.update(status="install_failed", log=out[-1500:])
        shutil.rmtree(d, ignore_errors=True)
        return rec
    code, out, secs = sh(collect, d, env, COLLECT_TIMEOUT)
    n = count_collected(row["runner"], out)
    rec.update(collect_exit=code, collect_seconds=secs, collected=n)
    rec["status"] = "ok" if code == 0 and n > 0 else "collect_failed"
    if rec["status"] != "ok":
        rec["log"] = out[-1500:]
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
    return rec


def plan_only(row, workdir):
    """No install, no collection, nothing from the repository executed: a blobless depth-1
    fetch to see which lockfiles exist, then the commands a measurement session would run."""
    repo = row["repo"]
    d = os.path.join(workdir, "plan_" + repo.replace("/", "__"))
    shutil.rmtree(d, ignore_errors=True)
    rec = {"repo": repo, "commit": row["commit"], "runner": row["runner"], "flag": row["flag"],
           "file": row["file"], "line": row["line"], "reason_kind": row["reason_kind"],
           "multi_core_runner": row["multi_core_runner"], "stars": row["stars"]}
    try:
        p = subprocess.run(["git", "clone", "-q", "--bare", "--filter=blob:none", "--depth", "1",
                            f"https://github.com/{repo}", d], capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            rec.update(status="fetch_failed")
            return rec
        if subprocess.run(["git", "-C", d, "cat-file", "-e", row["commit"]], capture_output=True).returncode != 0:
            subprocess.run(["git", "-C", d, "fetch", "-q", "--filter=blob:none", "--depth", "1", "origin", row["commit"]],
                           capture_output=True, timeout=600)
        files = set(subprocess.run(["git", "-C", d, "ls-tree", "-r", "--name-only", row["commit"]],
                                   capture_output=True, text=True).stdout.splitlines())
        if not files:
            rec.update(status="pin_failed")
            return rec
        rec["commit_date"] = subprocess.run(["git", "-C", d, "log", "-1", "--format=%cI", row["commit"]],
                                            capture_output=True, text=True).stdout.strip()

        def read(pth):
            q = subprocess.run(["git", "-C", d, "show", f"{row['commit']}:{pth}"], capture_output=True, timeout=120)
            return q.stdout.decode("utf-8", "replace") if q.returncode == 0 else None
        install, collect = plan(row, d, exists=lambda pth: pth in files, read=read)
        rec.update(install_cmd=install, collect_cmd=collect, status="planned_not_verified",
                   install_seconds=None, collect_seconds=None, collected=None)
        return rec
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_cmd(rec):
    if rec["runner"] == "jest":
        return rec["collect_cmd"].replace(" --listTests", "")
    if rec["runner"] == "vitest":
        return rec["collect_cmd"].replace(" list --passWithNoTests", " run")
    if rec["runner"] == "mocha":
        return rec["collect_cmd"].replace(" --dry-run", "")
    if rec["runner"] == "pytest":
        return ".venv/bin/python -m pytest -q -p no:cacheprovider"
    if rec["runner"] == "go":
        return rec["collect_cmd"].replace(" -list '.*'", "")
    return None


def main():
    workdir = sys.argv[1]
    max_trials = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    os.makedirs(workdir, exist_ok=True)
    rows = [json.loads(l) for l in open(os.environ.get("SERIAL_SCAN_ROWS", os.path.join(HERE, "scan.jsonl")))]
    pool = [r for r in rows if r["running_serially"] and r["runner"] in RUNNERS and r["readable"]
            and not r.get("archived") and (r["test_count_estimate"] or 0) >= 10]
    rank = {"stated": 0, "implied": 1, "none": 2}
    pool.sort(key=lambda r: (not r["multi_core_runner"], rank[r["reason_kind"]], -(r["stars"] or 0)))
    tpath = os.path.join(RAW, "candidate_plans.jsonl" if PLAN_ONLY else "candidate_trials.jsonl")
    done = {json.loads(l)["repo"]: json.loads(l) for l in open(tpath)} if os.path.exists(tpath) else {}
    todo = [r for r in pool if r["repo"] not in done][:max(0, max_trials - len(done))]
    passes = sum(1 for t in done.values() if t["status"] == "ok")
    print(f"pool {len(pool)}, already tried {len(done)} ({passes} ok), trying {len(todo)}", flush=True)
    with open(tpath, "a") as f, ThreadPoolExecutor(3) as ex:
        futs = []
        for r in todo:
            futs.append(ex.submit(plan_only if PLAN_ONLY else trial, r, workdir))
        for fu in futs:
            rec = fu.result()
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[rec["repo"]] = rec
            print(rec["repo"], rec["runner"], rec["status"], rec.get("collected"), flush=True)
    cur = {r["repo"]: r for r in rows}
    for t in done.values():  # refresh labels from the current scan.jsonl
        if t["repo"] in cur:
            t["reason_kind"] = cur[t["repo"]]["reason_kind"]
            t["multi_core_runner"] = cur[t["repo"]]["multi_core_runner"]
    want = ("planned_not_verified",) if PLAN_ONLY else ("ok",)
    ok = [t for t in done.values() if t["status"] in want and t["repo"] in cur
          and cur[t["repo"]]["running_serially"] and cur[t["repo"]]["commit"] == t["commit"]]
    ok.sort(key=lambda t: t.get("commit_date", ""), reverse=True)
    cands = []
    for t in ok:
        cands.append({
            "repo": t["repo"], "commit": t["commit"], "commit_date": t["commit_date"],
            "clone": f"git clone https://github.com/{t['repo']} && cd {t['repo'].split('/')[1]} && git checkout {t['commit']}",
            "install": t["install_cmd"], "collect": t["collect_cmd"], "run": run_cmd(t),
            "runner": t["runner"], "serial_flag": t["flag"], "flag_at": f"{t['file']}:{t['line']}",
            "reason_kind": t["reason_kind"], "multi_core_runner": t["multi_core_runner"], "stars": t["stars"],
            "install_and_collect": "UNKNOWN: not run in this session (executing third-party install/collect code was denied by the session's permission classifier)" if PLAN_ONLY else "MEASURED ok",
            "collected": t["collected"], "install_seconds": t["install_seconds"],
            "collect_seconds": t["collect_seconds"], "test_files_ESTIMATED": cur[t["repo"]]["test_count_estimate"],
            "env_note": "measured with CI=true and a scrubbed environment (env -i + proxy/CA vars); run inside the repo root"})
    comment = ("NOT VERIFIED: commands planned from the pinned tree (lockfiles detected by a blobless fetch); nothing was installed or collected because running third-party install/collect code was denied in this session. Newest pinned commit first." if PLAN_ONLY else
               "Candidates that installed AND collected in this container (exit 0, >0 tests listed), newest pinned commit first. Generated by candidates.py from raw/candidate_trials.jsonl; failures with reasons are in that file.")
    json.dump({"_comment": comment, "verified": not PLAN_ONLY,
               "candidates": cands}, open(os.path.join(HERE, "candidates.json"), "w"), indent=1)
    print(f"{len(cands)} candidates ok")


if __name__ == "__main__":
    main()
