#!/usr/bin/env python3
"""How well the engine EXPLAINS the real bugs it finds, against a plain shuffled runner (coordinator D17).

For every THEIRS test of a repository (classify.py's classification.json):

  plain    the plain runner, no engine, with the shuffle seed of a plain run in which the test failed
           (repro.py `shuffle-S`), rerun --runs times: how many runs fail the test, seconds to the first failure.
  engine   the engine's own command on the trunk, `python -m detpy.fenvix_js repro TEST --runner <runner>
           --confirm <runs>` (pytest: `fenvix repro TEST`): its search (fixed order, then seeds), its minimisation
           and its confirmation replays; recorded: status, replays that failed, seconds, and the cause it names
           (polluter tests / first differing event), verbatim.

Scope, the same on both sides: the test's own file (`--scope file`, default) or the whole selection (`--scope
suite`). Restricting to the file keeps a 400 s suite from being rerun 10 x per test; a test that needs another file
to fail does not reproduce with it, and that is recorded, not hidden.

Output: <out>/<repo>/explain.json and one line per test in <out>/explain.jsonl; bugs.py-style section appended to
bugs/<repo>.md with --bugs.
Usage: explain.py --spec specs.json --name REPO --out DIR [--runs 10] [--scope file|suite] [--max-runs 60]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import time

import measure as M


def plain_cmd(spec, runner, seed, files, out_json, rep_path):
    if runner == "vitest":
        return (["npx", "--no-install", "vitest", "run"] + (files or spec.get("args", [])) +
                ["--no-file-parallelism", "--sequence.shuffle", f"--sequence.seed={seed}", "--reporter=default",
                 "--reporter=json", f"--outputFile.json={out_json}", f"--reporter={rep_path}"])
    if runner == "jest":
        return (["npx", "--no-install", "jest"] + (files or spec.get("args", [])) +
                ["--runInBand", "--randomize", f"--seed={seed}", "--json", f"--outputFile={out_json}"])
    py = os.path.expandvars(spec["python"])
    return [py, "-m", "pytest"] + (files or spec.get("args", [])) + ["-p", "randomly", f"--randomly-seed={seed}",
                                                                    f"--det-outcomes={out_json}"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--scope", choices=["file", "suite"], default="file")
    ap.add_argument("--max-runs", type=int, default=60, help="runner runs the engine's search may use per test")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--only", default=None, help="comma list of test ids (default: every THEIRS test)")
    o = ap.parse_args()
    spec = json.load(open(o.spec))[o.name]
    runner = spec["runner"]
    cwd = os.path.expandvars(spec["dir"])
    base = os.path.join(os.path.abspath(o.out), o.name)
    ex = os.path.join(base, "explain")
    os.makedirs(ex, exist_ok=True)
    log = os.path.join(ex, "explain.log")
    env = {k: v for k, v in os.environ.items() if k not in M.VOLATILE}
    env.update({k: os.path.expandvars(v) for k, v in spec.get("env", {}).items()})
    env = M.tmp_env(env, M.run_tmpdir(o.name))  # D18: the same per-repository temp directory, emptied before each run
    cl = json.load(open(os.path.join(base, "classification.json")))["tests"]
    theirs = {n: r for n, r in cl.items() if r["box"] == "THEIRS"}
    if o.only:
        theirs = {n: r for n, r in theirs.items() if n in set(o.only.split(","))}
    fenvix_py = os.path.expandvars(spec.get("python") or spec["fenvix_python"])
    results = {}

    # ---- plain: per (file, seed), --runs reruns; every THEIRS test of that file read from the same runs
    groups = collections.defaultdict(list)
    for nid, r in theirs.items():
        seeds = [k.split("shuffle-")[1] for k in r.get("failed_in", []) if "shuffle-" in k]
        file = nid.split("::", 1)[0].split("@@", 1)[0]
        groups[(file if o.scope == "file" else "", seeds[0] if seeds else None)].append(nid)
    for (file, seed), nids in groups.items():
        rows = []
        if seed is None:
            for nid in nids:
                results.setdefault(nid, {})["plain"] = {"status": "no shuffled plain run failed this test (it failed "
                                                        "in another plain run: no seed to rerun)", "runs": 0}
            continue
        t_first = {}
        t0 = time.time()
        for k in range(1, o.runs + 1):
            M.reset_tree(cwd)
            M.build_after_reset(cwd, spec.get("build"), env, log)
            rep = M.place_reporter(cwd) if runner == "vitest" else None
            fj = os.path.join(ex, f"plain-{abs(hash((file, seed))) % 10**8}-{k}.raw.json")
            cmd = plain_cmd(spec, runner, seed, [file] if file else [], fj, rep)
            ids = fj.replace(".raw.json", ".ids.json")
            r, text = M.run(cmd, cwd, {**env, "PM_IDS_OUT": ids}, log, o.timeout)
            oc = M.outcomes_file(fj) if runner == "pytest" else (M.ids_outcomes(ids, cwd) if os.path.exists(ids) else M.runner_outcomes(fj, cwd))
            rows.append({"run": k, "cmd": " ".join(cmd), "exit": r["exit"], "wall_s": r["wall_s"],
                         "outcomes": {n: M.norm(oc).get(n) for n in nids}})
            for n in nids:
                if M.norm(oc).get(n) == "failed" and n not in t_first:
                    t_first[n] = round(time.time() - t0, 2)
        for n in nids:
            fails = sum(1 for x in rows if x["outcomes"][n] == "failed")
            results.setdefault(n, {})["plain"] = {
                "scope": "file " + file if file else "suite", "seed": seed, "cmd": rows[0]["cmd"],
                "reproduced": f"{fails} of {len(rows)}", "fails": fails, "runs": len(rows),
                "seconds_to_first_failure": t_first.get(n), "seconds_total": round(sum(x["wall_s"] for x in rows), 2),
                "missing_in_runs": sum(1 for x in rows if x["outcomes"][n] is None)}

    # ---- engine: its own repro command, per test
    for nid in theirs:
        file = nid.split("::", 1)[0].split("@@", 1)[0]
        outdir = os.path.join(ex, "engine-" + re.sub(r"[^A-Za-z0-9]+", "-", nid)[-80:])
        M.reset_tree(cwd)
        M.build_after_reset(cwd, spec.get("build"), env, log)
        if runner == "pytest":
            cmd = [fenvix_py, "-m", "detpy.fenvix", "repro", nid, "--confirm", str(o.runs), "--max-runs",
                   str(o.max_runs), "--out", outdir, "--json"] + (["--", file] if o.scope == "file" else [])
        else:
            cmd = [fenvix_py, "-m", "detpy.fenvix_js", "repro", nid, "--runner", runner, "--confirm", str(o.runs),
                   "--max-runs", str(o.max_runs), "--timeout", str(min(o.timeout, 900)), "--out", outdir, "--json"] + \
                  (["--", file] if o.scope == "file" else [])
        e = dict(env)
        e["FENVIX_DETJS"] = f"node {M.DETJS}"
        r, text = M.run(cmd, cwd, e, log, o.timeout * 4)
        human = text[:text.find("\n{")] if "\n{" in text else text
        try:
            b = json.loads(text[text.index("\n{") + 1:])
        except ValueError:
            b = {}
        cause = {k: b.get(k) for k in ("status", "cause", "polluters", "setters", "seed", "order", "error",
                                       "divergence", "replays", "fingerprint") if k in b}
        lines = [l.strip() for l in human.splitlines() if re.match(r"\s*(status|cause|seed|order|error|replay|check):", l)]
        results.setdefault(nid, {})["engine"] = {
            "cmd": " ".join(cmd), "scope": "file " + file if o.scope == "file" else "suite", "exit": r["exit"],
            "seconds_total": r["wall_s"], "status": b.get("status") or (lines[0] if lines else f"exit {r['exit']}"),
            "report_lines": lines, "bundle_fields": cause,
            "reproduced": (re.search(r"(\d+)/(\d+) replays", human).group(0) if re.search(r"(\d+)/(\d+) replays", human) else None)}
    # ---- points to the cause?
    for nid, res in results.items():
        en = res.get("engine", {})
        txt = " ".join(en.get("report_lines", []))
        if re.search(r"cause: test order: it fails when run after \S+", txt):
            res["points_to_cause"] = "yes"
        elif re.search(r"cause: (seed|\[)", txt) or "first diverg" in txt:
            res["points_to_cause"] = "partly"
        else:
            res["points_to_cause"] = "no"
        res["points_to_cause_text"] = next((l for l in en.get("report_lines", []) if l.startswith("cause:")), None)
    with open(os.path.join(base, "explain.json"), "w") as f:
        json.dump(results, f, indent=1)
    with open(os.path.join(os.path.abspath(o.out), "explain.jsonl"), "a") as f:
        for nid, res in results.items():
            f.write(json.dumps({"repo": o.name, "test": nid, "engine_commit": M.engine_commit(),
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **res}) + "\n")
    print(json.dumps({n: {"plain": r.get("plain", {}).get("reproduced"), "engine": r.get("engine", {}).get("status"),
                          "cause": r.get("points_to_cause")} for n, r in results.items()}, indent=1))


if __name__ == "__main__":
    main()
