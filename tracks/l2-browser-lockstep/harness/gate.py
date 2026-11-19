#!/usr/bin/env python3
"""Level 2 browser, round 4 (lockstep): gate and measurement jobs for one repository (called by run_gate.sh).

(helpers copied from tracks/l2-browser-r3/harness/exp.py)

  exp.py JOB NAME     JOB = e1 | e5     (RUN params per job; results/<JOB>-<NAME>.json)

Phases of an `e1` job (each only while the time budget allows; the result is written after every run):
  plain    N runs of the selection as the project configures it (Playwright workers as configured, retries 0)
  stress   M runs as `plain` with one CPU hog per core beside them (round 1's stress)
  extra    the same two phases for extra selections (targets outside the main selection, e.g. documenso's ui test)
  base     B plain runs of the round-2 suite selection when the e1 selection differs from it (actual)
  det      D full-suite `--det` runs on this commit's engine (round 2 run 4 predates fix 697c9729)
  freeze   E2: R `--det --det-freeze=on` replays and R0 `--det` replays of each listed target
  replay   H3: one `--det --det-seed=S` run of a target, then its printed replay command as printed
An `e5` job: database clock under libfaketime (see repos/<name>.sh e5_* functions).
"""
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

JOB, NAME = sys.argv[1], sys.argv[2]
H3 = Path(__file__).resolve().parent.parent.parent / "l2-browser-r3" / "harness"
H4 = Path(__file__).resolve().parent
H2 = H3.parent.parent / "l2-browser-r2" / "harness"       # round 2: lib.sh, repos/*.sh
OUT = Path(os.environ["L2_OUT"])
WORK = Path(os.environ["L2_WORK"])
RESULT = Path(os.environ["L2_RESULT"])
DETJS = os.environ["DETJS_BIN"]
T0 = time.time()
RUN = json.loads((H4.parent / "RUN").read_text())
REPOS = json.loads((H2 / "repos.json").read_text())
for _f in (H3 / "repos.json", H4 / "repos.json"):
    for _n, _c in json.loads(_f.read_text()).items():
        REPOS[_n] = {**REPOS.get(_n, {}), **_c}
CFG = REPOS[NAME]
SCRIPT = H4 / "repos" / f"{NAME}.sh"
if not SCRIPT.exists():
    SCRIPT = H3 / "repos" / f"{NAME}.sh"
if not SCRIPT.exists():
    SCRIPT = H2 / "repos" / f"{NAME}.sh"
P = {"plain": 20, "stress": 10, "base": 0, "det": 0, "freeze": 0, "freeze_control": 0, "budget_min": 320,
     "run_timeout_min": 45, "target_timeout_min": 8}
P.update(CFG.get("r4", {}).get(JOB, {}))
P.update((RUN.get("params") or {}).get(JOB, {}))
P.update((RUN.get("params") or {}).get(f"{JOB}:{NAME}", {}))
DEADLINE = T0 + P["budget_min"] * 60
os.environ.update({k: str(v) for k, v in (P.get("env") or {}).items()})  # A/B switches of the engine (e.g. "ab" jobs)
EPOCH = time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(T0))
os.environ["L2_EPOCH"] = EPOCH
LOG = open(OUT / "exp.log", "a")
FAIL = {"failed", "timedOut"}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def bash(script, *args, timeout=900):
    pre = (f"source '{H2}/lib.sh'; source '{SCRIPT}'; "
           f"[ -s '{OUT}/env.sh' ] && source '{OUT}/env.sh'; ")
    env = {**os.environ, "L2_H": str(H2), "L2_H3": str(H3)}
    try:
        r = subprocess.run(["bash", "-c", pre + script, "_", *args], cwd=WORK, env=env, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        return 124, str(e)


def fn(name, *args, timeout=900):
    return bash(f'if [ "$(type -t {name})" = function ]; then {name} "$@"; fi', *args, timeout=timeout)


_, v = bash('printf "%s\\0%s\\0%s\\0%s\\0%s\\0%s" "${PW_DIR:-}" "${PW_ARGS:-}" "${PW_ENV:-}" "$(type -t server_start)" "${STATE_SPEC:-}" "${STATE_WHERE:-runner}"')
PW_DIR, PW_ARGS, PW_ENV, HAS_SERVER, STATE_SPEC, STATE_WHERE = (v.split("\0") + ["", "", "", "", "", ""])[:6]
PW_CWD = WORK / (PW_DIR or ".")
PW_ARGS = PW_ARGS.split()
PW_ENV = dict(kv.split("=", 1) for kv in PW_ENV.split() if "=" in kv)
HAS_SERVER = HAS_SERVER.strip() == "function"
STATE_SPEC = str(WORK / STATE_SPEC) if STATE_SPEC.strip() else None
STATE_WHERE = STATE_WHERE.strip() or "runner"
for d in ("json", "traces", "logs"):
    (OUT / d).mkdir(parents=True, exist_ok=True)

R = {"name": NAME, "job": JOB, "repo": CFG["repo"], "ref": CFG["ref"], "status": "running", "run_id": os.environ.get("GITHUB_RUN_ID"),
     "engine_commit": os.environ.get("ENGINE_SHA"), "setup_s": int(os.environ.get("L2_SETUP_S") or 0), "params": P,
     "pw_dir": PW_DIR, "pw_args": PW_ARGS, "runs": [], "epoch": EPOCH, "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
try:
    R["machine"] = f"{os.cpu_count()} vCPU, " + open("/etc/os-release").read().split('PRETTY_NAME="')[1].split('"')[0]
except Exception:
    R["machine"] = f"{os.cpu_count()} vCPU"


def save():
    RESULT.write_text(json.dumps(R, indent=1) + "\n")


def norm(file, titles, project):
    return f"{Path(file).name}::{'::'.join(titles)}{f' [{project}]' if project else ''}"


def parse_json(path):
    """Playwright JSON report -> {key: (status, file, line, error)}."""
    try:
        d = json.loads(Path(path).read_text())
    except Exception:
        return {}
    out = {}

    def walk(suite, titles, file):
        file = suite.get("file") or file
        for s in suite.get("suites", []) or []:
            walk(s, titles + [s.get("title", "")], s.get("file") or file)
        for spec in suite.get("specs", []) or []:
            for t in spec.get("tests", []) or []:
                res = t.get("results") or []
                status = res[-1].get("status", "skipped") if res else "skipped"
                key = norm(spec.get("file") or file, titles + [spec.get("title", "")], t.get("projectName", ""))
                err = ""
                if res and status in FAIL:
                    e = res[-1].get("error") or (res[-1].get("errors") or [{}])[0]
                    err = re.sub(r"\x1b\[[0-9;]*m", "", e.get("message") or "")[:500] if isinstance(e, dict) else ""
                out[key] = (status, spec.get("file") or file, spec.get("line"), err)

    for s in d.get("suites", []) or []:
        walk(s, [], s.get("file") or s.get("title"))
    return out


def remaining():
    return DEADLINE - time.time()


def kill_group(p):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            break
        try:
            p.wait(timeout=15)
            break
        except subprocess.TimeoutExpired:
            pass
    kill_stragglers()


def kill_stragglers():
    """Processes a timed-out run leaves behind (web servers, browsers re-parented out of its group) would hold the
    project's port and fail every later run in 1 s (gate run 4, actual: runs 4-10 'missing' after run 3 timed out).
    Kills every process whose working directory is inside the checkout, except this one and its parents."""
    me = {os.getpid(), os.getppid()}
    root = os.path.realpath(str(WORK))
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in me:
            continue
        try:
            cwd = os.path.realpath(os.readlink(f"/proc/{d}/cwd"))
        except OSError:
            continue
        if cwd == root or cwd.startswith(root + os.sep):
            try:
                os.kill(int(d), signal.SIGKILL)
            except OSError:
                pass
    time.sleep(1)


class Hogs:
    """Round 1's CPU stress: one busy process per core beside the run."""
    def __enter__(self):
        self.ps = [subprocess.Popen(["python3", "-c", "while True: pass"]) for _ in range(os.cpu_count() or 2)]
        return self

    def __exit__(self, *a):
        for p in self.ps:
            p.kill()


def run_pw(label, mode, seed=None, args=None, det_flags=(), timeout_s=None, env_extra=None, raw_args=None, server_mode=None):
    rec = {"label": label, "mode": mode, "seed": seed, "args": list(args or []), "det_flags": list(det_flags)}
    fn("reset")
    if STATE_SPEC and (STATE_WHERE == "outside" or mode != "det" or raw_args is not None):
        rs = subprocess.run(["node", DETJS, "state", "restore", f"--det-state={STATE_SPEC}"], cwd=WORK, capture_output=True, text=True)
        if rs.returncode != 0:
            rec["state_error"] = (rs.stdout + rs.stderr)[-800:]
    if HAS_SERVER:
        rc, out = fn("server_start", server_mode or mode, "none" if seed is None else str(seed), timeout=600)
        if rc != 0:
            rec["error"] = "server_start failed: " + out[-1500:]
            fn("server_stop")
            return rec
    jsonf = OUT / "json" / f"{label}.json"
    trace = OUT / "traces" / f"{label}.jsonl"
    jsonf.unlink(missing_ok=True)
    trace.unlink(missing_ok=True)
    env = {**os.environ, **PW_ENV, "PLAYWRIGHT_JSON_OUTPUT_NAME": str(jsonf), "DETJS_ROOT": str(PW_CWD), **(env_extra or {})}
    cmd = ["node", DETJS, "playwright"]
    if raw_args is not None:
        cmd += [*raw_args, f"--det-trace={trace}", "--reporter=dot,json"]
    else:
        if mode == "det":
            cmd += ["--det", f"--det-trace={trace}", f"--det-epoch={EPOCH}", *det_flags] + ([f"--det-seed={seed}"] if seed is not None else [])
            if STATE_SPEC and STATE_WHERE == "runner":
                cmd.append(f"--det-state={STATE_SPEC}")
        cmd += ["test", *(PW_ARGS if args is None else args), "--retries=0", "--max-failures=0", "--reporter=dot,json"]
    timeout_s = max(60, min(timeout_s or P["run_timeout_min"] * 60, remaining() - 120))
    logf = OUT / "logs" / f"{label}.log"
    t = time.time()
    with open(logf, "w") as lf:
        p = subprocess.Popen(cmd, cwd=PW_CWD, env=env, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rec["rc"] = p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_group(p)
            rec["rc"] = "timeout"
    rec["wall_s"] = round(time.time() - t, 1)
    if rec["rc"] not in (0,):
        try:
            rec["log_tail"] = logf.read_text(errors="replace")[-3000:]
        except OSError:
            pass
    if HAS_SERVER:
        fn("server_stop")
    oc = parse_json(jsonf)
    rec["outcomes"] = {k: v[0] for k, v in oc.items()}
    rec["errors"] = {k: v[3] for k, v in oc.items() if v[3]}
    if len(rec["errors"]) > 80:
        rec["errors"] = dict(list(rec["errors"].items())[:80])
    rec["trace"] = str(trace) if trace.exists() else None
    counts = {}
    for s in rec["outcomes"].values():
        counts[s] = counts.get(s, 0) + 1
    rec["counts"] = counts
    if not oc:
        rec["log_tail"] = logf.read_text(errors="replace")[-3000:]
    if mode == "det":
        txt = logf.read_text(errors="replace")
        rec["replay_cmds"] = re.findall(r"detjs: replay [^\n]*:\n  (npx detjs playwright [^\n]*)", txt)[:20]
    log(f"{label}: rc={rec['rc']} wall={rec['wall_s']}s {counts}")
    return rec


def store(rec, phase):
    rec["phase"] = phase
    R["runs"].append({k: v for k, v in rec.items()})
    save()


def verify(traces):
    traces = [t for t in traces if t]
    if len(traces) < 2:
        return None
    r = subprocess.run(["node", DETJS, "verify", *traces, "--json"], capture_output=True, text=True, timeout=900)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"error": (r.stdout + r.stderr)[-2000:]}


def trace_key(nodeid):
    parts = nodeid.split("::")
    return "::".join([Path(parts[0]).name] + parts[1:])


def js_escape(text):
    return "".join("\\" + c if c in ".*+?^${}()|[]\\/" else c for c in text)


def matches(spec, key):
    if spec.get("key"):
        return key == spec["key"]
    if Path(key.split("::")[0]).name != spec["file"] or spec["grep"] not in key:
        return False
    return spec.get("project") is None or key.endswith(f" [{spec['project']}]")


def target_args(spec):
    filt = [js_escape(spec["file"]), "--grep", js_escape(spec["grep"])]
    args = [a for a in PW_ARGS if not a.startswith("--shard")]
    if spec.get("project"):
        args = [a for a in args if not a.startswith("--project")] + [f"--project={spec['project']}"]
    return filt + args


def outcome_for(spec, run):
    for k, o in (run.get("outcomes") or {}).items():
        if matches(spec, k):
            return k, o
    return None, "missing"


def budget_for(per_run):
    return remaining() > per_run + 300


def phase_runs(phase, n, args, stress=False, mode="plain", det_flags=(), est=None):
    done = []
    for i in range(n):
        if done and not budget_for(statistics.median(x["wall_s"] for x in done) * 1.2):
            log(f"{phase}: budget exhausted after {i} runs")
            break
        if not done and est and not budget_for(est):
            break
        if stress:
            with Hogs():
                r = run_pw(f"{phase}-{i + 1}", mode, args=args, det_flags=det_flags)
        else:
            r = run_pw(f"{phase}-{i + 1}", mode, args=args, det_flags=det_flags)
        store(r, phase)
        done.append(r)
    return done


# ------------------------------------------------------------------ jobs (round 4)
import gzip


def ls_stats(label):
    """The lockstep coordinator's per-test lines (DETJS_LS_STATS=1) of one run's log."""
    out = []
    try:
        for line in (OUT / "logs" / f"{label}.log").read_text(errors="replace").splitlines():
            if line.startswith("detjs lockstep {"):
                try:
                    out.append(json.loads(line[len("detjs lockstep "):]))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def keep_trace(path, dst_name):
    if not path or not Path(path).exists():
        return None
    dst = RESULT.parent / f"{JOB}-{NAME}" / f"{dst_name}.jsonl.gz"
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = Path(path).read_bytes()
    if len(data) > 3_000_000:
        return None
    dst.write_bytes(gzip.compress(data))
    return str(dst.relative_to(RESULT.parent))


if JOB == "gate":
    # Gate (round 4): R --det runs (lockstep on) of each listed target with the same epoch and seed; identical
    # traces are what the gate asks for. A few plain runs of each target are kept for comparison of outcomes.
    os.environ["DETJS_LS_STATS"] = "1"
    R["gate"] = []
    for spec in CFG["r4"]["targets"]:
        T = {**spec, "plain": [], "runs": [], "errors": [], "walls": [], "stats": [], "traces": []}
        R["gate"].append(T)
        args = target_args(spec)
        for i in range(P.get("plain_runs", 2)):
            if not budget_for(300):
                break
            r = run_pw(f"g{len(R['gate'])}-plain-{i + 1}", "plain", args=args, timeout_s=P["target_timeout_min"] * 60)
            T["plain"].append(outcome_for(spec, r)[1])
            save()
        traces = []
        for i in range(P.get("runs", 10)):
            if not budget_for(P.get("per_run_s", 300)):
                T["budget_stop"] = i
                break
            label = f"g{len(R['gate'])}-det-{i + 1}"
            dd = None
            if i < P.get("diag_runs", 2):
                dd = OUT / "diag" / label
                shutil.rmtree(dd, ignore_errors=True)
                os.environ["DETJS_PW_DIAG_DIR"] = str(dd / "server")  # the app server (server_start) inherits it
            r = run_pw(label, "det", args=args, timeout_s=P["target_timeout_min"] * 60,
                       env_extra={"DETJS_PW_DIAG_DIR": str(dd / "pages")} if dd else None)
            os.environ.pop("DETJS_PW_DIAG_DIR", None)
            if dd and dd.exists():
                # keep the diagnosis texts of the target test (bodies, frames, DOM) for the divergence analysis
                needle = re.sub(r"[^A-Za-z0-9._-]+", "_", spec["grep"])[:40]
                total = 0
                for f in sorted(dd.rglob("*")):
                    if f.is_file() and needle in f.name and f.stat().st_size < 4_000_000 and total < 10_000_000:
                        dst = RESULT.parent / f"{JOB}-{NAME}" / "diag" / label / f.relative_to(dd)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(gzip.compress(f.read_bytes()))
                        total += f.stat().st_size
            k, o = outcome_for(spec, r)
            T["runs"].append(o)
            if r.get("error"):
                T.setdefault("run_errors", {})[str(i + 1)] = r["error"][-800:]
            if r.get("log_tail") and o not in ("passed",):
                T.setdefault("run_logs", {})[str(i + 1)] = r["log_tail"][-2500:]
            T["errors"].append((r.get("errors") or {}).get(k, "")[:400])
            T["walls"].append(r.get("wall_s"))
            st = [x for x in ls_stats(label) if spec["grep"] in x.get("test", "")]
            T["stats"].append(st[-1] if st else None)
            traces.append(r.get("trace"))
            T["traces"].append(keep_trace(r.get("trace"), label))
            save()
        vv = verify(traces)
        T["verify_all"] = []
        for t in (vv or {}).get("tests", []) if isinstance(vv, dict) else []:
            row = {"key": trace_key(t["nodeid"]), "status": t["status"], "distinct_fingerprints": t["distinct_fingerprints"],
                   "runs": len(t["fingerprints"]), "divergence": t.get("divergence")}
            T["verify_all"].append(row)
            if matches(spec, row["key"]):
                T["verify"] = row
        if isinstance(vv, dict) and "error" in vv:
            T["verify_error"] = vv["error"]
        save()

for x in R["runs"]:
    x.pop("trace", None)
R["status"] = "ok"
R["elapsed_min"] = round((time.time() - T0) / 60, 1)
save()
log(f"done in {R['elapsed_min']} min")
