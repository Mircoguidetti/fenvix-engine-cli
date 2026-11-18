#!/usr/bin/env python3
"""Level 2 browser study for one repository (called by run_repo.sh after setup).

Phases, each started only while the time budget allows (results are written after every run):
  baseline  B runs of the suite as the project configures it (Playwright workers as configured, retries 0)
  stress    S runs as baseline with one CPU hog per core beside them (CI machines are often loaded)
  serial    2 runs with --workers=1 (separates the cost of serialising from the cost of the controls)
  det       D runs of `detjs playwright --det` (same seed): per-test fingerprints, outcomes, wall time
  targets   for every flaky test (passed and failed across baseline + stress runs): R replays under --det,
            seeds 1..K until both outcomes are seen, and 3 replays of the first failing seed
Every Playwright run goes through `detjs playwright` (without --det it runs the project's CLI unchanged).
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

NAME = sys.argv[1]
H = Path(__file__).resolve().parent
OUT = Path(os.environ["L2_OUT"])
WORK = Path(os.environ["L2_WORK"])
RESULT = Path(os.environ["L2_RESULT"])
DETJS = os.environ["DETJS_BIN"]
T0 = time.time()
RUN = json.loads((H.parent / "RUN").read_text())
CFG = json.loads((H / "repos.json").read_text())[NAME]
P = {"baseline": 6, "stress": 4, "serial": 2, "det": 3, "replays": 10, "seeds": 8, "max_targets": 8,
     "budget_min": 300, "run_timeout_min": 45, "target_timeout_min": 8, "target_plain": 5, "ablation_tests": 3}
P.update(CFG.get("params", {}))
P.update(RUN.get("params", {}))
DEADLINE = T0 + P["budget_min"] * 60
# Virtual epoch of every --det run of this job: the job's start minute. Databases, the Playwright
# worker's own clock and other uncontrolled parts run on real time; a 2025 epoch put the app's
# timestamps a year behind theirs. Fixed for the whole job, so replays stay comparable.
EPOCH = time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(T0))
os.environ["L2_EPOCH"] = EPOCH
LOG = open(OUT / "study.log", "a")
FAIL = {"failed", "timedOut"}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def bash(script, *args, timeout=900):
    """Run bash with lib.sh and the repository script sourced (cwd: the clone)."""
    pre = (f"source '{H}/lib.sh'; source '{H}/repos/{NAME}.sh'; "
           f"[ -s '{OUT}/env.sh' ] && source '{OUT}/env.sh'; ")
    env = {**os.environ, "L2_H": str(H)}
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

R = {"name": NAME, "repo": CFG["repo"], "ref": CFG["ref"], "status": "running", "run_id": os.environ.get("GITHUB_RUN_ID"),
     "setup_s": int(os.environ.get("L2_SETUP_S") or 0), "params": P, "pw_dir": PW_DIR, "pw_args": PW_ARGS,
     "server_outside_runner": HAS_SERVER, "runs": [], "epoch": EPOCH, "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
try:
    R["machine"] = f"{os.cpu_count()} vCPU, " + open("/etc/os-release").read().split('PRETTY_NAME="')[1].split('"')[0]
except Exception:
    R["machine"] = f"{os.cpu_count()} vCPU"


def save():
    RESULT.write_text(json.dumps(R, indent=1, sort_keys=False) + "\n")


def norm(file, titles, project):
    return f"{Path(file).name}::{'::'.join(titles)}{f' [{project}]' if project else ''}"


def parse_json(path):
    """Playwright JSON report -> {key: (status, file, line)}."""
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
                if t.get("status") == "skipped" and not res:
                    status = "skipped"
                key = norm(spec.get("file") or file, titles + [spec.get("title", "")], t.get("projectName", ""))
                err = ""
                if res and status in FAIL:
                    e = res[-1].get("error") or (res[-1].get("errors") or [{}])[0]
                    err = re.sub(r"\x1b\[[0-9;]*m", "", e.get("message") or "")[:400] if isinstance(e, dict) else ""
                out[key] = (status, spec.get("file") or file, spec.get("line"), err)

    for s in d.get("suites", []) or []:
        walk(s, [], s.get("file") or s.get("title"))
    return out


def trace_key(nodeid):
    parts = nodeid.split("::")
    return "::".join([Path(parts[0]).name] + parts[1:])


def remaining():
    return DEADLINE - time.time()


def kill_group(p):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            return
        try:
            p.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            pass


def run_pw(label, mode, seed=None, filters=(), extra=(), timeout_s=None, server_mode=None, pw_args=None, det_flags=(),
           env_extra=None, keep_parts=None, raw_args=None):
    """One Playwright run (fresh app state and server). Returns the run record."""
    rec = {"label": label, "mode": mode, "seed": seed, "filters": list(filters), "extra": list(extra),
           "server_mode": server_mode, "det_flags": list(det_flags)}
    fn("reset")
    if STATE_SPEC and (STATE_WHERE == "outside" or mode != "det" or raw_args is not None):
        # The start state of every run (plain or --det) is the snapshot saved after setup (round 2).
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
    args = ["node", DETJS, "playwright"]
    if raw_args is not None:
        # A printed replay command, as the developer would run it (only the trace path and the JSON report added).
        args += [*raw_args, f"--det-trace={trace}", "--reporter=dot,json"]
    else:
        if mode == "det":
            args += ["--det", f"--det-trace={trace}", f"--det-epoch={EPOCH}", *det_flags] + ([f"--det-seed={seed}"] if seed is not None else [])
            if STATE_SPEC and STATE_WHERE == "runner":
                args.append(f"--det-state={STATE_SPEC}")
        # --max-failures=0: configs that stop at the first failure on CI (documenso) would hide the rest.
        args += ["test", *(PW_ARGS if pw_args is None else pw_args), *filters, "--retries=0", "--max-failures=0", "--reporter=dot,json", *extra]
    timeout_s = timeout_s or P["run_timeout_min"] * 60
    timeout_s = max(60, min(timeout_s, remaining() - 120))
    logf = OUT / "logs" / f"{label}.log"
    t = time.time()
    with open(logf, "w") as lf:
        p = subprocess.Popen(args, cwd=PW_CWD, env=env, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rec["rc"] = p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_group(p)
            rec["rc"] = "timeout"
    rec["wall_s"] = round(time.time() - t, 1)
    if HAS_SERVER:
        fn("server_stop")
    if mode == "det" and (label in ("det-1", "det-2") or keep_parts):
        for src in (OUT / "traces" / "server-parts", WORK / ".detjs" / "serve" / "parts"):
            if src.is_dir():
                dst = Path(keep_parts) if keep_parts else OUT / "server-parts" / label
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
    oc = parse_json(jsonf)
    rec["outcomes"] = {k: v[0] for k, v in oc.items()}
    rec["locations"] = {k: [v[1], v[2]] for k, v in oc.items()}
    rec["errors"] = dict(list({k: v[3] for k, v in oc.items() if v[3]}.items())[:25])
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


def store(rec):
    slim = {k: v for k, v in rec.items() if k not in ("locations",)}
    R["runs"].append(slim)
    save()


def verify(traces):
    traces = [t for t in traces if t]
    if len(traces) < 2:
        return None
    r = subprocess.run(["node", DETJS, "verify", *traces, "--json"], capture_output=True, text=True, timeout=600)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"error": (r.stdout + r.stderr)[-2000:]}


class Hogs:
    def __enter__(self):
        self.ps = [subprocess.Popen(["python3", "-c", "while True: pass"]) for _ in range(os.cpu_count() or 2)]
        return self

    def __exit__(self, *a):
        for p in self.ps:
            p.kill()


def budget_for(n_runs, per_run):
    return remaining() > n_runs * per_run + 300


# ------------------------------------------------------------------ helpers
def history(runs):
    h = {}
    for r in runs:
        for k, st in (r.get("outcomes") or {}).items():
            h.setdefault(k, []).append(st)
    return h


def letters(lst):
    return "".join("P" if x == "passed" else "F" if x in FAIL else "S" if x == "skipped" else "?" for x in lst)


def js_escape(text):
    return "".join("\\" + c if c in ".*+?^${}()|[]\\/" else c for c in text)


def flaky_of(runs):
    out = []
    for k, v in history(runs).items():
        if "passed" in v and any(x in FAIL for x in v):
            out.append(k)
    return sorted(out)


def spec_of_key(k):
    """Target spec for a test seen in a JSON report: exact key."""
    loc = LOC.get(k) or [k.split("::")[0], None]
    title = k.rsplit(" [", 1)[0].split("::")[-1] if k.endswith("]") else k.split("::")[-1]
    project = k.rsplit(" [", 1)[1][:-1] if k.endswith("]") else None
    return {"key": k, "file": Path(loc[0]).name, "grep": title, "project": project, "known": False}


def matches(spec, key):
    if spec.get("key"):
        return key == spec["key"]
    if Path(key.split("::")[0]).name != spec["file"] or spec["grep"] not in key:
        return False
    return spec.get("project") is None or key.endswith(f" [{spec['project']}]")


def outcome_for(spec, run):
    for k, o in (run.get("outcomes") or {}).items():
        if matches(spec, k):
            return k, o
    return None, "missing"


def target_args(spec):
    filt = [js_escape(spec["file"]), "--grep", js_escape(spec["grep"])]
    # A shard of a one-test selection may be empty: no --shard for targeted runs.
    args = [a for a in PW_ARGS if not a.startswith("--shard")]
    if spec.get("project"):
        args = [a for a in args if not a.startswith("--project")] + [f"--project={spec['project']}"]
    return filt, args


def verify_for(spec, traces):
    v = verify(traces)
    if not v or "tests" not in v:
        return None
    for t in v["tests"]:
        if matches(spec, trace_key(t["nodeid"])):
            return {"status": t["status"], "distinct_fingerprints": t["distinct_fingerprints"], "runs": len(t["fingerprints"]),
                    "divergence": t.get("divergence")}
    return None


def run_target(spec):
    """R replays under --det (default seed), seeds 1..K until both outcomes, 3 replays of the first failing seed."""
    filt, args = target_args(spec)
    T = {**spec, "replays": [], "seeds": {}, "failing_seed_replays": []}
    R["targets"].append(T)
    slug = f"t{len(R['targets'])}"
    est, reps = None, []
    for i in range(P["replays"]):
        if est and not budget_for(1, est * 1.2):
            break
        r = run_pw(f"{slug}-replay-{i + 1}", "det", filters=filt, pw_args=args, timeout_s=TT)
        est = r.get("wall_s", 60)
        reps.append(r)
        k, o = outcome_for(spec, r)
        T["replays"].append(o)
        T["matched_key"] = T.get("matched_key") or k
        T["replay_wall_s"] = statistics.median(x["wall_s"] for x in reps)
        if o == "missing" and i == 0:
            T["error"] = "test not found by its filter: " + (r.get("log_tail") or "")[-800:]
            save()
            return
        save()
    T["replay_verify"] = verify_for(spec, [r.get("trace") for r in reps])
    seen, fail_seed = set(), None
    for sd in range(1, P["seeds"] + 1):
        if not budget_for(1, (est or 60) * 1.2):
            break
        r = run_pw(f"{slug}-seed-{sd}", "det", seed=sd, filters=filt, pw_args=args, timeout_s=TT)
        _, o = outcome_for(spec, r)
        T["seeds"][str(sd)] = o
        seen.add("P" if o == "passed" else "F" if o in FAIL else "?")
        if o in FAIL and fail_seed is None:
            fail_seed = (sd, r.get("trace"))
        save()
        if {"P", "F"} <= seen and sd >= 3:
            break
    if fail_seed:
        fr = []
        for i in range(P.get("fail_replays", 3)):
            if not budget_for(1, (est or 60) * 1.2):
                break
            r = run_pw(f"{slug}-failseed-{fail_seed[0]}-{i + 1}", "det", seed=fail_seed[0], filters=filt, pw_args=args, timeout_s=TT)
            T["failing_seed_replays"].append(outcome_for(spec, r)[1])
            fr.append(r.get("trace"))
            if not T.get("replay_cmd") and r.get("replay_cmds"):
                T["replay_cmd"] = r["replay_cmds"][0]
        T["failing_seed"] = fail_seed[0]
        T["failing_seed_verify"] = verify_for(spec, [fail_seed[1]] + fr)
        # The printed replay command, run as printed after removing every run artefact (.detjs except the
        # state snapshot, test-results): same outcome and fingerprint as the failing seed's replays?
        if T.get("replay_cmd") and budget_for(1, (est or 60) * 1.2):
            subprocess.run(["bash", "-c", "find . -name .detjs -type d -prune -not -path './node_modules/*' | while read d; do "
                            "find \"$d\" -mindepth 1 -maxdepth 1 -not -name state -exec rm -rf {} +; done; "
                            "find . -name test-results -type d -prune -not -path '*/node_modules/*' -exec rm -rf {} +"], cwd=WORK)
            cmd = T["replay_cmd"].split()[3:]  # after "npx detjs playwright"
            r = run_pw(f"{slug}-replaycmd", "det", raw_args=cmd, timeout_s=TT)
            T["replay_cmd_outcome"] = outcome_for(spec, r)[1]
            T["replay_cmd_verify"] = verify_for(spec, [fail_seed[1]] + fr + [r.get("trace")])
    # Without the controls, same filter: how often does it fail on its own (the baseline for this selection)?
    plain = []
    for i in range(P["target_plain"]):
        if not budget_for(1, (est or 60) * 1.2):
            break
        r = run_pw(f"{slug}-plain-{i + 1}", "plain", filters=filt, pw_args=args, timeout_s=TT)
        plain.append(outcome_for(spec, r)[1])
    T["plain_runs"] = letters(plain)
    save()


if STATE_SPEC:
    rs = subprocess.run(["node", DETJS, "state", "save", f"--det-state={STATE_SPEC}"], cwd=WORK, capture_output=True, text=True)
    R["state"] = {"spec": STATE_SPEC, "where": STATE_WHERE, "save_rc": rs.returncode, "save_log": (rs.stdout + rs.stderr)[-600:]}
    log(f"state snapshot: rc={rs.returncode} {(rs.stdout + rs.stderr).strip()[-200:]}")

# ------------------------------------------------------------------ diagnosis
def diagnose(spec, idx):
    """Two --det replays of one target with full traces, server parts and the texts behind the digests;
    first divergence of the browser trace and of every server part, for this test."""
    filt, args = target_args(spec)
    slug = f"d{idx}"
    D = {**spec, "replays": [], "walls": []}
    R["diagnosis"].append(D)
    traces, parts = [], []
    for i in (1, 2):
        ddir = OUT / "diag" / slug / f"r{i}"
        shutil.rmtree(ddir, ignore_errors=True)
        ddir.mkdir(parents=True, exist_ok=True)
        r = run_pw(f"{slug}-r{i}", "det", filters=filt, pw_args=args, timeout_s=TT,
                   det_flags=(f"--det-max-events={P.get('diag_max_events', 300000)}",),
                   env_extra={"DETJS_PW_DIAG_DIR": str(ddir / "pages"), "DETJS_MAX_EVENTS": str(P.get("diag_max_events", 300000))},
                   keep_parts=str(ddir / "server-parts"))
        k, o = outcome_for(spec, r)
        D["replays"].append(o)
        D["walls"].append(r.get("wall_s"))
        D["matched_key"] = D.get("matched_key") or k
        if r.get("error"):
            D["error"] = r["error"][-800:]
        if r.get("log_tail"):
            D["log_tail"] = r["log_tail"][-1500:]
        if r.get("errors"):
            D.setdefault("errors", []).append(next(iter(r["errors"].values()), "")[:600])
        traces.append(r.get("trace"))
        parts.append(ddir / "server-parts")
        if r.get("trace") and Path(r["trace"]).exists():
            shutil.copy(r["trace"], ddir / "trace.jsonl")
        lf = OUT / "logs" / f"{slug}-r{i}.log"
        if lf.exists():
            (ddir / "run.log.tail").write_text(lf.read_text(errors="replace")[-60000:])
        save()
    D["browser"] = verify_for(spec, traces)
    D["server"] = []
    if parts[0].is_dir() and parts[1].is_dir():
        for f in sorted(parts[0].glob("*.jsonl")):
            g = parts[1] / f.name
            if not g.exists():
                D["server"].append({"part": f.name, "status": "missing in r2"})
                continue
            v = verify([str(f), str(g)])
            if not v or "tests" not in v:
                D["server"].append({"part": f.name, "error": str(v)[:500]})
                continue
            mine = [t for t in v["tests"] if matches(spec, trace_key(t["nodeid"]))]
            D["server"].append({"part": f.name, "summary": v.get("summary"),
                                "tests": [{"nodeid": t["nodeid"], "status": t["status"], "divergence": t.get("divergence")}
                                          for t in (mine or v["tests"])[:6]]})
    save()
    # Keep the evidence next to the result (size-capped).
    dst = RESULT.parent / NAME / "diag" / slug
    shutil.rmtree(dst, ignore_errors=True)
    total = 0
    for f in sorted((OUT / "diag" / slug).rglob("*")):
        if f.is_file() and total + f.stat().st_size < P.get("diag_keep_bytes", 12_000_000):
            out = dst / f.relative_to(OUT / "diag" / slug)
            out.parent.mkdir(parents=True, exist_ok=True)
            if f.stat().st_size > 4_000_000:
                continue
            shutil.copy(f, out)
            total += f.stat().st_size


TT = P["target_timeout_min"] * 60
if P.get("mode") == "diagnose":
    R["diagnosis"] = []
    for i, spec in enumerate(CFG.get("targets", []), 1):
        if remaining() < 300:
            break
        diagnose(spec, i)
    R["status"] = "ok"
    R["elapsed_min"] = round((time.time() - T0) / 60, 1)
    save()
    log(f"diagnosis done in {R['elapsed_min']} min")
    sys.exit(0)

# ------------------------------------------------------------------ phases
LOC = {}
R["targets"] = []
BASE = []
for i in range(P["baseline"]):
    if i and not budget_for(1, BASE[0]["wall_s"] * 1.2):
        break
    r = run_pw(f"baseline-{i + 1}", "plain")
    LOC.update(r.get("locations", {}))
    BASE.append(r)
    store(r)
if not any(r.get("outcomes") for r in BASE):
    R["status"] = "baseline_broken"
    save()
    sys.exit(0)
base_wall = statistics.median(r["wall_s"] for r in BASE if r.get("outcomes"))

# Known flaky tests (repos.json known_flaky: idle study, GitHub issues) first, then tests flaky in this
# job's baseline runs: the targets get their budget before the long full-suite phases.
known = [{**k, "known": True} for k in (CFG.get("targets") or CFG.get("known_flaky", []))]
detected = [spec_of_key(k) for k in flaky_of(BASE)]
detected = [d for d in detected if not any(matches(kn, d["key"]) for kn in known)]
R["known_flaky"] = known
for spec in (known + detected)[: P["max_targets"]]:
    if remaining() < 900:
        break
    run_target(spec)

STRESS = []
for i in range(P["stress"]):
    if not budget_for(1, base_wall * 2.5 + 60):
        break
    with Hogs():
        r = run_pw(f"stress-{i + 1}", "plain")
    LOC.update(r.get("locations", {}))
    STRESS.append(r)
    store(r)

SERIAL = []
for i in range(P["serial"]):
    if not budget_for(1, base_wall * 4 + 60):
        break
    r = run_pw(f"serial-{i + 1}", "plain", extra=("--workers=1",))
    SERIAL.append(r)
    store(r)

DET = []
for i in range(P["det"]):
    per = (DET[0]["wall_s"] if DET else base_wall * 6) * 1.1
    if not budget_for(1, per):
        break
    r = run_pw(f"det-{i + 1}", "det")
    LOC.update(r.get("locations", {}))
    DET.append(r)
    store(r)

hb, hs, hd = history(BASE), history(STRESS), history(DET)
flaky = flaky_of(BASE + STRESS)
R["tests_baseline"] = len(hb)
R["baseline_wall_median_s"] = base_wall
R["stress_wall_median_s"] = statistics.median(r["wall_s"] for r in STRESS) if STRESS else None
R["serial_wall_median_s"] = statistics.median(r["wall_s"] for r in SERIAL) if SERIAL else None
R["det_wall_median_s"] = statistics.median(r["wall_s"] for r in DET) if DET else None
R["always_failing_baseline"] = sorted(k for k, v in hb.items() if v and all(x in FAIL for x in v))
R["flaky"] = [{"key": k, "baseline": letters(hb.get(k, [])), "stress": letters(hs.get(k, [])), "det": letters(hd.get(k, [])),
               "location": LOC.get(k)} for k in flaky]
broken = []
for k, v in hd.items():
    b = hb.get(k, [])
    if b and all(x == "passed" for x in b) and any(x in FAIL for x in v):
        broken.append({"key": k, "det": letters(v), "always": all(x in FAIL for x in v),
                       "error": next((r.get("errors", {}).get(k) for r in DET if r.get("errors", {}).get(k)), None)})
R["broken_by_controls"] = broken
R["det_tests"] = len(hd)
vd = verify([r.get("trace") for r in DET])
if vd and "summary" in vd:
    R["det_verify"] = vd["summary"]
    R["det_diverged_examples"] = [{"key": trace_key(t["nodeid"]), "divergence": t.get("divergence")}
                                  for t in vd["tests"] if t["status"] != "stable"][:15]
    R["det_fingerprints"] = {trace_key(t["nodeid"]): [t["status"], t["distinct_fingerprints"], letters(t["outcomes"])]
                             for t in vd["tests"]}
elif vd:
    R["det_verify"] = vd
save()

# Stress-detected flaky tests not targeted yet.
done_keys = [t.get("matched_key") or t.get("key") for t in R["targets"]]
for k in flaky:
    if len(R["targets"]) >= P["max_targets"] or remaining() < 900:
        break
    if k in done_keys or any(matches(t, k) for t in R["targets"]):
        continue
    run_target(spec_of_key(k))

# Ablation: which control breaks a test that fails only under --det (one run per control switched off).
R["ablation"] = []
ABL = [("server-off", {"det_flags": ("--det-server=off",), "server_mode": "plain"}),
       ("net-off", {"det_flags": ("--det-net=off",)}), ("vtime-off", {"det_flags": ("--det-vtime=off",)}),
       ("seeds-off", {"det_flags": ("--det-browser-seeds=off",)})]
for b in [x for x in broken if x["always"]][: P["ablation_tests"]]:
    spec = spec_of_key(b["key"])
    filt, args = target_args(spec)
    A = {"key": b["key"]}
    R["ablation"].append(A)
    r = run_pw(f"abl{len(R['ablation'])}-all-on", "det", filters=filt, pw_args=args, timeout_s=TT)
    A["all-on"] = outcome_for(spec, r)[1]
    est = r.get("wall_s", 60)
    for name, kw in ABL:
        if not budget_for(1, est * 1.2):
            break
        r = run_pw(f"abl{len(R['ablation'])}-{name}", "det", filters=filt, pw_args=args, timeout_s=TT, **kw)
        A[name] = outcome_for(spec, r)[1]
    save()

R["status"] = "ok"
R["elapsed_min"] = round((time.time() - T0) / 60, 1)
save()
# Small diagnostic files next to the result: the first det trace's server parts and the det logs' tails.
diag = RESULT.parent / NAME
shutil.rmtree(diag, ignore_errors=True)
diag.mkdir(parents=True, exist_ok=True)
for r, cap in [(x, 300000) for x in DET[:1]] + [(x, 60000) for x in BASE[:1]]:
    lf = OUT / "logs" / f"{r['label']}.log"
    if lf.exists():
        (diag / f"{r['label']}.log.tail").write_text(lf.read_text(errors="replace")[-cap:])
# Where the app servers' own events differ between det-1 and det-2 (verifier text, per server process).
sp = OUT / "server-parts"
if (sp / "det-1").is_dir() and (sp / "det-2").is_dir():
    texts = []
    for f in sorted((sp / "det-1").glob("*.jsonl")):
        g = sp / "det-2" / f.name
        if g.exists():
            rr = subprocess.run(["node", DETJS, "verify", str(f), str(g)], capture_output=True, text=True, timeout=600)
            texts.append(f"===== {f.name}\n" + "\n".join((rr.stdout + rr.stderr).splitlines()[:120]))
    (diag / "server-parts-verify.txt").write_text("\n".join(texts))
total = 0
for f in sorted((OUT / "server-parts").glob("*/*.jsonl")) if (OUT / "server-parts").is_dir() else []:
    if f.stat().st_size < 1_500_000 and total + f.stat().st_size < 6_000_000:
        (diag / "server-parts" / f.parent.name).mkdir(parents=True, exist_ok=True)
        shutil.copy(f, diag / "server-parts" / f.parent.name / f.name)
        total += f.stat().st_size
if DET and DET[0].get("trace"):
    t = Path(DET[0]["trace"])
    if t.stat().st_size < 3_000_000:
        shutil.copy(t, diag / "det-1.trace.jsonl")
log(f"done in {R['elapsed_min']} min")
