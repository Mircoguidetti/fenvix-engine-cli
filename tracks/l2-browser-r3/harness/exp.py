#!/usr/bin/env python3
"""Level 2 browser, round 3: the cheap experiments of review R-011 for one repository (called by run_exp.sh).

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
H3 = Path(__file__).resolve().parent                      # tracks/l2-browser-r3/harness
H2 = H3.parent.parent / "l2-browser-r2" / "harness"       # round 2: lib.sh, repos/*.sh
OUT = Path(os.environ["L2_OUT"])
WORK = Path(os.environ["L2_WORK"])
RESULT = Path(os.environ["L2_RESULT"])
DETJS = os.environ["DETJS_BIN"]
T0 = time.time()
RUN = json.loads((H3.parent / "RUN").read_text())
REPOS = json.loads((H2 / "repos.json").read_text())
for _n, _c in json.loads((H3 / "repos.json").read_text()).items():
    REPOS[_n] = {**REPOS.get(_n, {}), **_c}
CFG = REPOS[NAME]
SCRIPT = H3 / "repos" / f"{NAME}.sh"
if not SCRIPT.exists():
    SCRIPT = H2 / "repos" / f"{NAME}.sh"
P = {"plain": 20, "stress": 10, "base": 0, "det": 0, "freeze": 0, "freeze_control": 0, "budget_min": 320,
     "run_timeout_min": 45, "target_timeout_min": 8}
P.update(CFG.get("r3", {}).get(JOB, {}))
P.update((RUN.get("params") or {}).get(JOB, {}))
P.update((RUN.get("params") or {}).get(f"{JOB}:{NAME}", {}))
DEADLINE = T0 + P["budget_min"] * 60
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
            return
        try:
            p.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            pass


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


# ------------------------------------------------------------------ jobs
if STATE_SPEC:
    rs = subprocess.run(["node", DETJS, "state", "save", f"--det-state={STATE_SPEC}"], cwd=WORK, capture_output=True, text=True)
    R["state"] = {"spec": STATE_SPEC, "save_rc": rs.returncode, "save_log": (rs.stdout + rs.stderr)[-600:]}

E1 = CFG.get("r3", {}).get("e1_args")
SEL = E1.split() if E1 else PW_ARGS
R["e1_args"] = SEL

if JOB == "e1":
    phase_runs("plain", P["plain"], SEL)
    phase_runs("stress", P["stress"], SEL, stress=True)
    for j, extra in enumerate(CFG.get("r3", {}).get("e1_extra", []), 1):
        phase_runs(f"extra{j}-plain", P.get("extra_plain", P["plain"]), extra.split())
        phase_runs(f"extra{j}-stress", P.get("extra_stress", P["stress"]), extra.split(), stress=True)
    if P["base"]:
        phase_runs("base", P["base"], PW_ARGS)
    if P["det"]:
        base_wall = statistics.median([x["wall_s"] for x in R["runs"] if x["phase"] in ("base", "plain") and x.get("outcomes")] or [300])
        phase_runs("det", P["det"], PW_ARGS, mode="det", est=base_wall * 4)
        dets = [x for x in R["runs"] if x["phase"] == "det"]
        vd = verify([x.get("trace") for x in dets])
        if vd and "summary" in vd:
            R["det_verify"] = vd["summary"]
            R["det_fingerprints"] = {trace_key(t["nodeid"]): [t["status"], t["distinct_fingerprints"]] for t in vd["tests"]}
            R["det_reasons"] = vd["summary"].get("reasons") if isinstance(vd["summary"], dict) else None
        elif vd:
            R["det_verify"] = vd
        for x in R["runs"]:
            x.pop("trace", None)
        save()
    # E2: freeze-before-observe on listed targets (10 replays each, plus control replays without it)
    R["freeze"] = []
    for spec in CFG.get("r3", {}).get("freeze_targets", []) if P["freeze"] else []:
        F = {**spec, "frozen": [], "control": []}
        R["freeze"].append(F)
        args = target_args(spec)
        for tag, n, flags in (("frozen", P["freeze"], ("--det-freeze=on",)), ("control", P["freeze_control"], ())):
            traces = []
            for i in range(n):
                if not budget_for(180):
                    break
                r = run_pw(f"fz-{len(R['freeze'])}-{tag}-{i + 1}", "det", args=args, det_flags=flags, timeout_s=P["target_timeout_min"] * 60)
                F[tag].append(outcome_for(spec, r)[1])
                traces.append(r.get("trace"))
            vv = verify(traces)
            for t in (vv or {}).get("tests", []) if isinstance(vv, dict) else []:
                if matches(spec, trace_key(t["nodeid"])):
                    F[f"{tag}_verify"] = {"status": t["status"], "distinct_fingerprints": t["distinct_fingerprints"],
                                          "runs": len(t["fingerprints"]), "divergence": t.get("divergence")}
            save()
    # H3: the printed replay command of a failing target, run as printed
    R["replay"] = []
    for spec in CFG.get("r3", {}).get("replay_targets", []):
        if not budget_for(600):
            break
        X = {**spec}
        R["replay"].append(X)
        r = run_pw("rc-seed", "det", seed=spec.get("seed", 1), args=target_args(spec), timeout_s=P["target_timeout_min"] * 60)
        X["seed_outcome"] = outcome_for(spec, r)[1]
        X["printed"] = (r.get("replay_cmds") or [None])[0]
        if X["printed"]:
            subprocess.run(["bash", "-c", "find . -name .detjs -type d -prune -not -path './node_modules/*' | while read d; do "
                            "find \"$d\" -mindepth 1 -maxdepth 1 -not -name state -exec rm -rf {} +; done; "
                            "find . -name test-results -type d -prune -not -path '*/node_modules/*' -exec rm -rf {} +"], cwd=WORK)
            rr = run_pw("rc-printed", "det", raw_args=X["printed"].split()[3:], timeout_s=P["target_timeout_min"] * 60)
            X["printed_outcome"] = outcome_for(spec, rr)[1]
            X["printed_log_tail"] = (OUT / "logs" / "rc-printed.log").read_text(errors="replace")[-1500:]
        save()
elif JOB == "e6":
    # E6 on real targets: does any seed reproduce the real failure? Seeds 1..N with the round-2 latency list and with
    # a list that reaches the deadline (D); the first failing seed of each list replayed R times. The failure message
    # is kept so that it can be compared with the real (plain) failure.
    R["e6"] = []
    for spec in CFG["r3"].get("e6_targets", []):
        T = {**spec, "lists": []}
        R["e6"].append(T)
        args = target_args(spec)
        for lname, lat in (("round2", "0,0,0,1,5,25"), ("deadline", "0,0,1,5,25,D")):
            Lr = {"list": lname, "latency": lat, "seeds": {}, "errors": {}, "fail_seed": None, "fail_replays": [], "fail_errors": []}
            T["lists"].append(Lr)
            for sd in range(1, P.get("seeds", 8) + 1):
                if not budget_for(300):
                    break
                r = run_pw(f"e6-{len(R['e6'])}-{lname}-s{sd}", "det", seed=sd, args=args, det_flags=(f"--det-latency={lat}",),
                           timeout_s=P["target_timeout_min"] * 60)
                k, o = outcome_for(spec, r)
                Lr["seeds"][str(sd)] = o
                if o in FAIL:
                    Lr["errors"][str(sd)] = (r.get("errors") or {}).get(k, "")[:400]
                    if Lr["fail_seed"] is None:
                        Lr["fail_seed"] = sd
                save()
            if Lr["fail_seed"] is not None:
                traces = []
                for i in range(P.get("fail_replays", 5)):
                    if not budget_for(300):
                        break
                    r = run_pw(f"e6-{len(R['e6'])}-{lname}-rep{i + 1}", "det", seed=Lr["fail_seed"], args=args,
                               det_flags=(f"--det-latency={lat}",), timeout_s=P["target_timeout_min"] * 60)
                    k, o = outcome_for(spec, r)
                    Lr["fail_replays"].append(o)
                    Lr["fail_errors"].append((r.get("errors") or {}).get(k, "")[:300])
                    traces.append(r.get("trace"))
                vv = verify(traces)
                for t in (vv or {}).get("tests", []) if isinstance(vv, dict) else []:
                    if matches(spec, trace_key(t["nodeid"])):
                        Lr["fail_verify"] = {"status": t["status"], "distinct_fingerprints": t["distinct_fingerprints"],
                                             "divergence": t.get("divergence")}
            save()
elif JOB == "e5":
    # E5: the database clock (Postgres) and the app server's process clock (Prisma's Rust engine) under libfaketime,
    # pinned to the run's epoch: frozen, or advancing 1 ms per clock call. 10 --det replays of 2 targets per variant,
    # against control replays with real clocks (round 2: 10 fingerprints in 10 replays for every documenso target).
    rc, out = fn("e5_prepare", timeout=1200)
    R["e5_prepare"] = {"rc": rc, "log": out[-1500:]}
    ft = EPOCH.replace("T", " ").replace("Z", "")
    R["e5"] = []
    for vname, fake in [v for v in (("control", ""), ("start", f"@{ft}"), ("frozen", ft), ("tick", f"@{ft} i0.001"))
                        if v[0] in P.get("variants", ["control", "frozen", "tick"])]:
        if rc != 0 and fake:
            break
        rc2, out2 = fn("e5_db", fake, timeout=600)
        V = {"variant": vname, "faketime": fake, "db_rc": rc2, "db_now": out2.strip()[-200:], "db_log": out2[-3000:] if rc2 else "", "targets": []}
        R["e5"].append(V)
        if rc2 != 0:
            save()
            continue
        os.environ["E5_FAKETIME"] = fake
        for spec in CFG["r3"]["e5_targets"]:
            T = {**spec, "replays": [], "errors": []}
            V["targets"].append(T)
            traces = []
            for i in range(P["control"] if vname == "control" else P["replays"]):
                if not budget_for(240):
                    break
                r = run_pw(f"e5-{vname}-{len(V['targets'])}-{i + 1}", "det", args=target_args(spec), timeout_s=P["target_timeout_min"] * 60)
                k, o = outcome_for(spec, r)
                T["replays"].append(o)
                if r.get("errors"):
                    T["errors"].append(next(iter(r["errors"].values()))[:300])
                if r.get("error"):
                    T["errors"].append(r["error"][-300:])
                traces.append(r.get("trace"))
            vv = verify(traces)
            for t in (vv or {}).get("tests", []) if isinstance(vv, dict) else []:
                if matches(spec, trace_key(t["nodeid"])):
                    T["verify"] = {"status": t["status"], "distinct_fingerprints": t["distinct_fingerprints"],
                                   "runs": len(t["fingerprints"]), "divergence": t.get("divergence")}
            save()
    os.environ["E5_FAKETIME"] = ""
    fn("e5_db", "", timeout=600)

for x in R["runs"]:
    x.pop("trace", None)
R["status"] = "ok"
R["elapsed_min"] = round((time.time() - T0) / 60, 1)
save()
log(f"done in {R['elapsed_min']} min")
