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
     "budget_min": 300, "run_timeout_min": 45, "target_timeout_min": 8}
P.update(CFG.get("params", {}))
P.update(RUN.get("params", {}))
DEADLINE = T0 + P["budget_min"] * 60
LOG = open(OUT / "study.log", "a")
FAIL = {"failed", "timedOut", "interrupted"}


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


_, v = bash('printf "%s\\0%s\\0%s\\0%s" "${PW_DIR:-}" "${PW_ARGS:-}" "${PW_ENV:-}" "$(type -t server_start)"')
PW_DIR, PW_ARGS, PW_ENV, HAS_SERVER = (v.split("\0") + ["", "", "", ""])[:4]
PW_CWD = WORK / (PW_DIR or ".")
PW_ARGS = PW_ARGS.split()
PW_ENV = dict(kv.split("=", 1) for kv in PW_ENV.split() if "=" in kv)
HAS_SERVER = HAS_SERVER.strip() == "function"
for d in ("json", "traces", "logs"):
    (OUT / d).mkdir(parents=True, exist_ok=True)

R = {"name": NAME, "repo": CFG["repo"], "ref": CFG["ref"], "status": "running", "run_id": os.environ.get("GITHUB_RUN_ID"),
     "setup_s": int(os.environ.get("L2_SETUP_S") or 0), "params": P, "pw_dir": PW_DIR, "pw_args": PW_ARGS,
     "server_outside_runner": HAS_SERVER, "runs": [], "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
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


def run_pw(label, mode, seed=None, filters=(), extra=(), timeout_s=None):
    """One Playwright run (fresh app state and server). Returns the run record."""
    rec = {"label": label, "mode": mode, "seed": seed, "filters": list(filters), "extra": list(extra)}
    fn("reset")
    if HAS_SERVER:
        rc, out = fn("server_start", mode, "none" if seed is None else str(seed), timeout=600)
        if rc != 0:
            rec["error"] = "server_start failed: " + out[-1500:]
            fn("server_stop")
            return rec
    jsonf = OUT / "json" / f"{label}.json"
    trace = OUT / "traces" / f"{label}.jsonl"
    jsonf.unlink(missing_ok=True)
    trace.unlink(missing_ok=True)
    env = {**os.environ, **PW_ENV, "PLAYWRIGHT_JSON_OUTPUT_NAME": str(jsonf), "DETJS_ROOT": str(PW_CWD)}
    args = ["node", DETJS, "playwright"]
    if mode == "det":
        args += ["--det", f"--det-trace={trace}"] + ([f"--det-seed={seed}"] if seed is not None else [])
    args += ["test", *PW_ARGS, *filters, "--retries=0", "--reporter=dot,json", *extra]
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
    if mode == "det" and label in ("det-1", "det-2"):
        for src in (OUT / "traces" / "server-parts", WORK / ".detjs" / "serve" / "parts"):
            if src.is_dir():
                dst = OUT / "server-parts" / label
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


# ------------------------------------------------------------------ phases
LOC = {}
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

STRESS = []
for i in range(P["stress"]):
    if not budget_for(1, base_wall * 2.5 + 60):
        break
    with Hogs():
        r = run_pw(f"stress-{i + 1}", "plain", extra=())
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


def history(runs):
    h = {}
    for r in runs:
        for k, s in (r.get("outcomes") or {}).items():
            h.setdefault(k, []).append(s)
    return h


def letters(lst):
    return "".join("P" if s == "passed" else "F" if s in FAIL else "S" if s == "skipped" else "?" for s in lst)


hb, hs, hd = history(BASE), history(STRESS), history(DET)
flaky = []
for k in sorted(set(hb) | set(hs)):
    allr = hb.get(k, []) + hs.get(k, [])
    if "passed" in allr and any(s in FAIL for s in allr):
        flaky.append(k)
R["tests_baseline"] = len(hb)
R["baseline_wall_median_s"] = base_wall
R["stress_wall_median_s"] = statistics.median(r["wall_s"] for r in STRESS) if STRESS else None
R["serial_wall_median_s"] = statistics.median(r["wall_s"] for r in SERIAL) if SERIAL else None
R["det_wall_median_s"] = statistics.median(r["wall_s"] for r in DET) if DET else None
R["always_failing_baseline"] = sorted(k for k, v in hb.items() if v and all(s in FAIL for s in v))
R["flaky"] = [{"key": k, "baseline": letters(hb.get(k, [])), "stress": letters(hs.get(k, [])), "det": letters(hd.get(k, [])),
               "location": LOC.get(k)} for k in flaky]
# Tests broken by the controls: passed in every baseline run, failed in a --det run.
broken = []
for k, v in hd.items():
    b = hb.get(k, [])
    if b and all(s == "passed" for s in b) and any(s in FAIL for s in v):
        broken.append({"key": k, "det": letters(v), "always": all(s in FAIL for s in v)})
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

# ------------------------------------------------------------------ targets
targets = sorted(flaky, key=lambda k: (-(letters(hb.get(k, [])).count("F") > 0), k))[: P["max_targets"]]
R["targets"] = []
tt = P["target_timeout_min"] * 60
for k in targets:
    loc = LOC.get(k)
    if not loc or not loc[0]:
        R["targets"].append({"key": k, "error": "no location"})
        continue
    filt = [f"{loc[0]}:{loc[1]}"] if loc[1] else [loc[0]]
    T = {"key": k, "filter": filt, "replays": [], "seeds": {}, "failing_seed_replays": []}
    R["targets"].append(T)
    slug = f"t{len(R['targets'])}"
    est = None
    reps = []
    for i in range(P["replays"]):
        if est and not budget_for(1, est * 1.2):
            break
        r = run_pw(f"{slug}-replay-{i + 1}", "det", filters=filt, timeout_s=tt)
        est = r.get("wall_s", 60)
        reps.append(r)
        T["replays"].append(r["outcomes"].get(k, "missing"))
        T["replay_wall_s"] = statistics.median(x["wall_s"] for x in reps)
        save()
    v = verify([r.get("trace") for r in reps])
    if v and "tests" in v:
        mine = [t for t in v["tests"] if trace_key(t["nodeid"]) == k]
        if mine:
            T["replay_verify"] = {"status": mine[0]["status"], "distinct_fingerprints": mine[0]["distinct_fingerprints"],
                                  "runs": len(mine[0]["fingerprints"]), "divergence": mine[0].get("divergence")}
        T["replay_summary"] = v["summary"]
    seen = set()
    fail_seed = None
    for s in range(1, P["seeds"] + 1):
        if not budget_for(1, (est or 60) * 1.2):
            break
        r = run_pw(f"{slug}-seed-{s}", "det", seed=s, filters=filt, timeout_s=tt)
        o = r["outcomes"].get(k, "missing")
        T["seeds"][str(s)] = o
        seen.add("P" if o == "passed" else "F" if o in FAIL else "?")
        if o in FAIL and fail_seed is None:
            fail_seed = (s, r.get("trace"))
        save()
        if {"P", "F"} <= seen and s >= 3:
            break
    if fail_seed:
        fr = []
        for i in range(3):
            if not budget_for(1, (est or 60) * 1.2):
                break
            r = run_pw(f"{slug}-failseed-{fail_seed[0]}-{i + 1}", "det", seed=fail_seed[0], filters=filt, timeout_s=tt)
            T["failing_seed_replays"].append(r["outcomes"].get(k, "missing"))
            fr.append(r.get("trace"))
        v = verify([fail_seed[1]] + fr)
        if v and "tests" in v:
            mine = [t for t in v["tests"] if trace_key(t["nodeid"]) == k]
            if mine:
                T["failing_seed_verify"] = {"status": mine[0]["status"], "distinct_fingerprints": mine[0]["distinct_fingerprints"]}
        T["failing_seed"] = fail_seed[0]
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
