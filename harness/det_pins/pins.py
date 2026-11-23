#!/usr/bin/env python3
"""Lane C: how many `--det` outcome flips disappear when the engine's pins match the host?

Phases (one repository of harness/parallel_measure/specs.json at a time):

  find      2 plain serial runs (npx vitest run --no-file-parallelism + ids/JSON reporters) and 2 whole-suite runs
            under `detjs vitest run --det --det-workers=1 --det-outcomes=... --det-trace=...`. A flip = passed in both
            plain runs and failed/error in both --det runs; tests absent from or skipped in a --det run are counted
            separately. Writes <out>/<repo>/flips.json.
  variants  seeded sample (random.Random(1) over the sorted flip ids, 50 if more), then per affected test file
            (file + Vitest project) V0..V6, two runs each, the file alone, serial, under --det.
  rows      one row per sampled flip into harness/det_pins/results.jsonl (repo rows replaced).

Every run: tree reset (git checkout/clean, keeps node_modules; removes .detjs/), TMPDIR=TMP=TEMP=/tmp/pm-<repo>
emptied (measure.py D18, done by measure.run), recorded per run in <out>/<repo>/runs.jsonl and in data/.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PM = os.path.join(HERE, "..", "parallel_measure")
sys.path.insert(0, os.path.abspath(PM))
import measure  # noqa: E402  (main() runs only under __main__)
from measure import place_reporter, ids_outcomes, runner_outcomes, reset_tree, run, tmp_env, run_tmpdir  # noqa: E402

ENGINE = measure.ENGINE
DETJS = measure.DETJS
DATA = os.path.join(HERE, "data")

VARIANTS = {
    "V0": [],
    "V1": ["EPOCH"],
    "V2": ["EPOCH", "--det-tz=keep", "--det-locale=keep"],
    "V3": ["EPOCH", "--det-tz=keep", "--det-locale=keep", "--det-timers=real"],
    "V4": ["EPOCH", "--det-tz=keep", "--det-locale=keep", "--det-timers=real", "--det-disable=net"],
    "V5": ["EPOCH", "--det-tz=keep", "--det-locale=keep", "--det-timers=real", "--det-disable=net,fs"],
    "V6": ["--det-disable=time,timers,net,fs", "--det-tz=keep", "--det-locale=keep"],
}
# V5 = V4 + fs: one --det-disable list (net,fs) rather than two flags.

FAILED = ("failed", "error")
# a failure that names this container (network unreachable from the sandbox, DNS, proxy), only counted on V4-V6
ENV_RE = re.compile(r"ENOTFOUND|EAI_AGAIN|ENETUNREACH|EHOSTUNREACH|getaddrinfo|fetch failed|"
                    r"tunneling socket|UNABLE_TO_GET_ISSUER", re.I)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load_spec(name):
    with open(os.path.join(PM, "specs.json")) as f:
        return json.load(f)[name]


def base_env(name, spec):
    env = {k: v for k, v in os.environ.items() if k not in measure.VOLATILE}
    env.update({k: os.path.expandvars(v) for k, v in spec.get("env", {}).items()})
    return tmp_env(env, run_tmpdir(name))


def engine_commit():
    return measure.engine_commit()


def record(out, row):
    with open(os.path.join(out, "runs.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")


def do_run(name, kind, cmd, cwd, env, out, extra):
    reset_tree(cwd)  # also removes .detjs/ and .fenvix-harness/
    detjs_gone = not os.path.exists(os.path.join(cwd, ".detjs"))
    if kind == "plain":
        place_reporter(cwd)
    r, text = run(cmd, cwd, env, os.path.join(out, "runs.log"), 3600)
    row = {"repo": name, "kind": kind, **extra, "cmd": " ".join(cmd), "cwd": cwd, "engine_commit": engine_commit(),
           "detjs_dir_removed": detjs_gone, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **r,
           "tail": text[-1500:]}
    record(out, row)
    return row, text


def det_outcomes(path):
    """--det-outcomes file -> (outcomes {id: outcome}, exceptions {id: [type, phase, message, where]})."""
    if not os.path.exists(path):
        return {}, {}
    with open(path) as f:
        j = json.load(f)
    return dict(j.get("outcomes") or {}), dict(j.get("exceptions") or {})


def find(o):
    spec = load_spec(o.repo)
    cwd = os.path.expandvars(spec["dir"])
    out = os.path.join(o.out, o.repo)
    os.makedirs(out, exist_ok=True)
    env = base_env(o.repo, spec)
    args = spec.get("args", [])
    for i in (1, 2):
        rj, ij = f"{out}/plain{i}.runner.json", f"{out}/plain{i}.ids.json"
        if not (o.resume and os.path.exists(ij)):
            ids_path = os.path.join(cwd, measure.REPORTER_IN_REPO)
            cmd = (["npx", "--no-install", "vitest", "run"] + args +
                   ["--no-file-parallelism", "--reporter=default", f"--reporter={ids_path}", "--reporter=json",
                    f"--outputFile.json={rj}"])
            do_run(o.repo, "plain", cmd, cwd, {**env, "PM_IDS_OUT": ij}, out, {"rep": i, "outcomes_file": ij})
    for i in (1, 2):
        of, tf = f"{out}/det{i}.outcomes.json", f"{out}/det{i}.trace.jsonl"
        if not (o.resume and os.path.exists(of)):
            cmd = (["node", DETJS, "vitest", "run"] + args +
                   ["--det", "--det-workers=1", f"--det-outcomes={of}", f"--det-trace={tf}"])
            do_run(o.repo, "det", cmd, cwd, env, out, {"rep": i, "outcomes_file": of, "trace": tf})
    plain = [runner_outcomes(f"{out}/plain{i}.runner.json", cwd) for i in (1, 2)]
    det = [det_outcomes(f"{out}/det{i}.outcomes.json") for i in (1, 2)]
    dets = [d[0] for d in det]
    both_pass = sorted(k for k in plain[0] if plain[0].get(k) == "passed" and plain[1].get(k) == "passed")
    flips, absent, skipped_det, mixed, det_passed = [], [], [], [], 0
    for k in both_pass:
        a, b = dets[0].get(k), dets[1].get(k)
        if a is None or b is None:
            absent.append({"id": k, "det1": a, "det2": b})
        elif a == "skipped" or b == "skipped":
            skipped_det.append({"id": k, "det1": a, "det2": b})
        elif a in FAILED and b in FAILED:
            flips.append(k)
        elif a == "passed" and b == "passed":
            det_passed += 1
        else:
            mixed.append({"id": k, "det1": a, "det2": b})
    det_only = sorted((set(dets[0]) | set(dets[1])) - (set(plain[0]) | set(plain[1])))
    summary = {
        "repo": o.repo, "engine_commit": engine_commit(),
        "plain_counts": [measure.counts(p) for p in plain], "det_counts": [measure.counts(d) for d in dets],
        "plain_both_passed": len(both_pass), "det_both_passed": det_passed, "flips": flips, "n_flips": len(flips),
        "absent_in_det": absent, "n_absent_in_det": len(absent), "skipped_in_det": skipped_det,
        "n_skipped_in_det": len(skipped_det), "mixed_in_det": mixed, "n_mixed_in_det": len(mixed),
        "ids_only_in_det": det_only[:50], "n_ids_only_in_det": len(det_only),
        "flip_exceptions": {k: [det[0][1].get(k), det[1][1].get(k)] for k in flips},
    }
    with open(f"{out}/flips.json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k.startswith("n_") or k.endswith("counts") or
                      k in ("plain_both_passed", "det_both_passed")}, indent=1))


def split_id(tid):
    head = tid.split("::", 1)[0]
    if "@@" in head:
        f, p = head.split("@@", 1)
        return f, p
    return head, ""


def sample(o):
    out = os.path.join(o.out, o.repo)
    with open(f"{out}/flips.json") as f:
        flips = sorted(json.load(f)["flips"])
    picked = sorted(random.Random(1).sample(flips, 50)) if len(flips) > 50 else flips
    with open(f"{out}/sample.json", "w") as f:
        json.dump({"n_flips": len(flips), "seed": 1, "method": "random.Random(1).sample(sorted(flips), 50)"
                   if len(flips) > 50 else "all", "sample": picked}, f, indent=1)
    return picked


def variants(o):
    spec = load_spec(o.repo)
    cwd = os.path.expandvars(spec["dir"])
    out = os.path.join(o.out, o.repo)
    env = base_env(o.repo, spec)
    picked = sample(o)
    groups = sorted({split_id(t) for t in picked})
    only = set(o.variants.split(",")) if o.variants else set(VARIANTS)
    vdir = os.path.join(out, "variants")
    os.makedirs(vdir, exist_ok=True)
    for gi, (fpath, proj) in enumerate(groups):
        for v, flags in VARIANTS.items():
            if v not in only:
                continue
            for rep in (1, 2):
                tag = f"g{gi:02d}.{v}.r{rep}"
                of, tf = f"{vdir}/{tag}.outcomes.json", f"{vdir}/{tag}.trace.jsonl"
                if o.resume and os.path.exists(of):
                    continue
                epoch = now_iso()
                fl = [f"--det-epoch={epoch}" if x == "EPOCH" else x for x in flags]
                cmd = (["node", DETJS, "vitest", "run", fpath] + (["--project", proj] if proj else []) +
                       ["--det", "--det-workers=1", f"--det-outcomes={of}", f"--det-trace={tf}"] + fl)
                row, _ = do_run(o.repo, "variant", cmd, cwd, env, out,
                                {"group": gi, "file": fpath, "project": proj, "variant": v, "rep": f"{rep}",
                                 "outcomes_file": of, "trace": tf})
                print(f"{tag} {fpath} {proj} exit={row['exit']} {row['wall_s']}s", flush=True)


def classify(msg):
    m = msg or ""
    if re.search(r"timed? ?out|timeout|not met within \d+ ?ms", m, re.I):
        return "timeout"
    if re.search(r"ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ENETUNREACH|fetch failed|socket|network|"
                 r"refused.*(host|connect)|detjs.*net", m, re.I):
        return "network error"
    if re.search(r"ENOENT|EEXIST|EACCES|EPERM|ENOTDIR|EISDIR|ENOTEMPTY|\bmtime\b|\bino\b|readdir|no such file", m, re.I):
        return "file error"
    if re.search(r"\b(19|20)\d\d-\d\d-\d\d|Date|date|clock|epoch|toISOString|expired|ago\b|\bms\b|seconds?|"
                 r"minutes?|hours?|days?|time ?zone|timestamp", m):
        return "date/time assertion"
    return "other"


def first_line(exc):
    if not exc:
        return None
    t, phase, msg, where = (list(exc) + [None] * 4)[:4]
    line = (msg or "").strip().splitlines()[0] if msg else ""
    return f"{t}: {line}"[:300] + (f" [{phase} @ {where}]" if phase or where else "")


def verdict(v, a, b):
    if a in FAILED and b in FAILED:
        return "still fails"
    if a == "passed" and b == "passed":
        return "cleared"
    if a in ("passed",) + FAILED and b in ("passed",) + FAILED:
        return f"unstable in {v}"
    return "absent/skipped"


def verify_v0(fpath, proj, vrun, cache):
    """Optional: `detjs verify --json` on the two V0 traces of a file; nodeid -> divergence.reason (+ command)."""
    key = (fpath, proj)
    if key in cache:
        return cache[key]
    a, b = vrun.get((fpath, proj, "V0", "1")), vrun.get((fpath, proj, "V0", "2"))
    res = {"cmd": None, "reasons": {}}
    if a and b:
        cmd = ["node", DETJS, "verify", "--json", a["trace"], b["trace"]]
        p = subprocess.run(cmd, capture_output=True, text=True)
        res["cmd"], res["exit"] = " ".join(cmd), p.returncode
        try:
            j = json.loads(p.stdout)
            res["reasons"] = {t["nodeid"]: ((t.get("divergence") or {}).get("reason"), t.get("status"))
                              for t in j.get("tests", [])}
        except ValueError:
            res["error"] = (p.stderr or p.stdout)[-500:]
    cache[key] = res
    return res


def rows(o):
    out = os.path.join(o.out, o.repo)
    vcache = {}
    with open(f"{out}/sample.json") as f:
        picked = json.load(f)["sample"]
    runs = [json.loads(x) for x in open(f"{out}/runs.jsonl")]
    vrun = {}
    for r in runs:
        if r["kind"] == "variant":
            vrun[(r["file"], r["project"], r["variant"], r["rep"])] = r  # the last run of a key wins (resume)
    finds = [r for r in runs if r["kind"] in ("plain", "det")]
    res = []
    for tid in picked:
        fpath, proj = split_id(tid)
        row = {"repo": o.repo, "test_id": tid, "file": fpath, "project": proj, "engine_commit": engine_commit(),
               "find_commands": [{"kind": r["kind"], "rep": r["rep"], "cmd": r["cmd"], "cwd": r["cwd"],
                                  "exit": r["exit"], "ts": r["ts"], "tmpdir_reset": r.get("tmpdir_reset"),
                                  "detjs_dir_removed": r.get("detjs_dir_removed")} for r in finds],
               "variants": {}}
        v0_msg = None
        for v in VARIANTS:
            runs2 = []
            for rep in ("1", "2"):
                r = vrun.get((fpath, proj, v, rep))
                if r is None:
                    runs2.append({"outcome": "not run"})
                    continue
                oc, ex = det_outcomes(r["outcomes_file"])
                outcome = oc.get(tid, "absent")
                fl = first_line(ex.get(tid))
                if outcome in FAILED and v in ("V4", "V5", "V6") and fl and ENV_RE.search(fl):
                    outcome = "ENV"
                runs2.append({"outcome": outcome, "failure": fl, "cmd": r["cmd"], "cwd": r["cwd"], "exit": r["exit"],
                              "wall_s": r["wall_s"], "ts": r["ts"], "tmpdir_reset": r.get("tmpdir_reset"),
                              "detjs_dir_removed": r.get("detjs_dir_removed")})
                if v == "V0" and fl and not v0_msg:
                    v0_msg = fl
            a, b = runs2[0]["outcome"], runs2[1]["outcome"]
            if "not run" in (a, b):
                vd = "not run"
            elif "ENV" in (a, b):
                vd = "ENV"
            else:
                vd = verdict(v, a, b)
            row["variants"][v] = {"verdict": vd, "runs": runs2}
        v0 = row["variants"]["V0"]["verdict"]
        if v0 == "cleared":
            status = "not reproduced alone"
        elif v0.startswith("unstable"):
            status = "unstable at V0"
        elif v0 == "still fails":
            status = "reproduced"
        else:
            status = f"V0 {v0}"
        first = None
        if status == "reproduced":
            first = next((v for v in list(VARIANTS)[1:] if row["variants"][v]["verdict"] == "cleared"), None)
        vf = verify_v0(fpath, proj, vrun, vcache)
        rs = vf["reasons"].get(tid)
        row["v0_verify"] = {"cmd": vf["cmd"], "exit": vf.get("exit"), "divergence_reason": rs[0] if rs else None,
                            "status": rs[1] if rs else None}
        row.update({"status": status, "first_clearing_variant": first, "v0_failure_line": v0_msg,
                    "failure_class": classify(v0_msg) if v0_msg else None,
                    "outcomes": {v: [x["outcome"] for x in row["variants"][v]["runs"]] for v in VARIANTS},
                    "verdicts": {v: row["variants"][v]["verdict"] for v in VARIANTS}})
        res.append(row)
    path = os.path.join(HERE, "results.jsonl")
    keep = [x for x in (open(path).read().splitlines() if os.path.exists(path) else [])
            if x.strip() and json.loads(x)["repo"] != o.repo]
    with open(path, "w") as f:
        for x in keep:
            f.write(x + "\n")
        for r in res:
            f.write(json.dumps(r) + "\n")
    print(f"{len(res)} rows for {o.repo}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["find", "sample", "variants", "rows"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="/tmp/pm/det_pins")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--variants", default="")
    o = ap.parse_args()
    {"find": find, "sample": sample, "variants": variants, "rows": rows}[o.phase](o)


if __name__ == "__main__":
    main()
