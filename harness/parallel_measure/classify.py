#!/usr/bin/env python3
"""Classify every test whose engine verdict is not "identical" into THEIRS / OURS / UNDECIDED (coordinator spec,
2026-11-22), from the raw files of measure.py and repro.py. No run is made here.

Evidence per test:
  plain runs   (no engine) plain serial rounds 1-3 (measure.py), plain parallel 4 workers x2 and plain serial
               shuffled x2 (repro.py)
  engine runs  `--det` serial S1-S3, `--det` parallel P(round, workers)
  verdicts     `fenvix verify S_i P_i,w --json` per round and worker count, and S1 vs S2

Rules, in order (the first that applies):
  THEIRS     the outcome differs between plain runs (no engine involved): order or parallel placement alone changes
             it. Evidence: the runs where it passed and failed, and the command of a failing plain run.
  UNDECIDED  the outcome is the same in every plain run but differs in an engine run (serial or parallel): the
             engine's controls change it; whether that is an engine defect or a dependence of the test on a source
             the engine pins (clock, time zone, host name, CPU count) is not settled by these runs.
  UNDECIDED  missing from a run (not executed, or not traced).
  ENV        (checked first) the test failed with a message that names this container's environment (ENV_PATTERNS:
             no IPv6 loopback, browser not installed, package metadata missing, ...): makes the row not count
  OURS       the outcome is the same in every run, plain and engine, serial and parallel: the engine refused (not
             proven / diverged) where the outcome is stable. Sub-reason: the engine's named cause; flagged when
             the same test is also not identical serial vs serial (the refusal does not come from parallelism).

Usage: classify.py --out DIR --name REPO [--spec specs.json]   writes DIR/REPO/classification.json and prints a summary
       classify.py ... --bugs harness/parallel_measure/bugs     also writes bugs/<repo>.md for the THEIRS cases
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re

import measure as M


ENV_PATTERNS = [
    (r"EAFNOSUPPORT|address family not supported|::1", "no IPv6 loopback (::1) in this container"),
    (r"EADDRNOTAVAIL", "address not available in this container"),
    (r"Executable doesn't exist at /opt/pw-browsers|playwright install", "browser not installed in this container"),
    (r"PackageNotFoundError: No package metadata", "package metadata missing (checkout not installed as a package)"),
    (r"ENOENT: no such file or directory, copyfile", "a file the test copies is missing in this checkout"),
]


def plain_messages(d, cwd):
    """test id -> failure message text, over every plain run (vitest/jest JSON; pytest --det-outcomes exceptions)."""
    msgs = collections.defaultdict(str)
    for f in glob.glob(os.path.join(d, "plain*.runner.json")) + glob.glob(os.path.join(d, "repro", "*.raw.json")):
        try:
            j = json.load(open(f))
        except (OSError, ValueError):
            continue
        if isinstance(j, dict) and "exceptions" in j:
            for k, v in (j.get("exceptions") or {}).items():
                msgs[k] += " " + json.dumps(v)[:2000]
            continue
        for tr in (j.get("testResults") or []) if isinstance(j, dict) else []:
            rel = os.path.relpath(tr["name"], cwd)
            seen = set()
            for a in tr.get("assertionResults", []):
                k = "::".join([rel] + list(a.get("ancestorTitles") or []) + [a["title"]])
                n, base = 2, k
                while k in seen:
                    k, n = f"{base} #{n}", n + 1
                seen.add(k)
                if a.get("failureMessages"):
                    msgs[k] += " " + " ".join(a["failureMessages"])[:2000]
    for f in glob.glob(os.path.join(d, "plain*.outcomes.json")):
        j = json.load(open(f))
        for k, v in (j.get("exceptions") or {}).items():
            msgs[k] += " " + json.dumps(v)[:2000]
    return msgs


def env_cause(msg):
    for pat, why in ENV_PATTERNS:
        if msg and re.search(pat, msg):
            return why
    return None


def reported(d, nid, runs_log):
    """Condition (4): what the parallel runs report for a test. Returns per parallel trace: (outcome in P, outcome in S
    of the same round, named in that run's own output)."""
    out = {}
    for f in sorted(glob.glob(os.path.join(d, "P*w*.jsonl"))):
        m = re.search(r"P(\d+)w(\d+)", f)
        _, tp = M.trace_tests(f)
        _, ts = M.trace_tests(os.path.join(d, f"S{m.group(1)}.jsonl"))
        po = tp.get(nid, (None,))[0]
        so = ts.get(nid, (None,))[0]
        sect = runs_log.get(os.path.basename(f), "")
        named = nid.split("::")[-1] in sect
        out[os.path.basename(f)[:-6]] = {"parallel": po, "serial_reference": so, "named_in_run_output": named,
                                         "ok": po == so or named}
    return out


def run_sections(d):
    """runs.log split per parallel trace file: the output of the run that wrote it."""
    secs, cur = {}, None
    try:
        for line in open(os.path.join(d, "runs.log"), errors="replace"):
            if line.startswith("$ ("):
                m = re.search(r"--det-trace=\S*/(P\d+w\d+\.jsonl)", line)
                cur = m.group(1) if m else None
                if cur:
                    secs[cur] = ""
            elif cur:
                secs[cur] += line
    except OSError:
        pass
    return secs


def load_plain(d, name, runner, cwd):
    runs = {}
    for f in sorted(glob.glob(os.path.join(d, "plain*.outcomes.json")) + glob.glob(os.path.join(d, "plain*.runner.json"))):
        i = re.search(r"plain(\d+)", f).group(1)
        oc = M.outcomes_file(f) if f.endswith(".outcomes.json") else M.runner_outcomes(f, cwd)
        runs[f"plain serial {i}"] = M.norm(oc)
    for f in sorted(glob.glob(os.path.join(d, "repro", "*.json"))):
        if f.endswith(".raw.json"):
            continue
        runs["plain " + os.path.basename(f)[:-5]] = json.load(open(f))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--spec", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "specs.json"))
    ap.add_argument("--bugs", default=None)
    o = ap.parse_args()
    spec = json.load(open(o.spec))[o.name]
    cwd = os.path.expandvars(spec["dir"])
    d = os.path.join(os.path.abspath(o.out), o.name)
    plain = load_plain(d, o.name, spec["runner"], cwd)
    engine = {}
    for f in sorted(glob.glob(os.path.join(d, "S*.jsonl")) + glob.glob(os.path.join(d, "P*.jsonl"))):
        _, t = M.trace_tests(f)
        engine["engine " + os.path.basename(f)[:-6]] = M.norm({k: v[0] for k, v in t.items()})
    verdicts = collections.defaultdict(list)  # nodeid -> [(file, status, reason, description, event_a, event_b)]
    for f in sorted(glob.glob(os.path.join(d, "verify*.json"))):
        rep = json.load(open(f))
        for t in rep.get("tests", []):
            if t.get("status") in (None, "identical"):
                continue
            dv = t.get("divergence") or {}
            verdicts[t["nodeid"]].append({"verify": os.path.basename(f), "status": t["status"], "reason": dv.get("reason"),
                                          "description": dv.get("description"), "event_a": dv.get("event_a"),
                                          "event_b": dv.get("event_b"), "outcomes": t.get("outcomes")})
    serial_noise = {n for n, vs in verdicts.items() if any(v["verify"].startswith("verify_serial_noise") for v in vs)}
    repro_cmds = {}
    rj = os.path.join(os.path.abspath(o.out), "repro.jsonl")
    if os.path.exists(rj):
        for line in open(rj):
            j = json.loads(line)
            if j["repo"] == o.name:
                repro_cmds["plain " + j["run"]] = j["cmd"]
    msgs = plain_messages(d, cwd)
    secs = run_sections(d)
    res = {}
    for nid, vs in verdicts.items():
        po = {k: m.get(nid) for k, m in plain.items()}
        eo = {k: m.get(nid) for k, m in engine.items()}
        p_vals = {v for v in po.values() if v is not None}
        e_vals = {v for v in eo.values() if v is not None}
        missing = sorted(k for k, v in {**po, **eo}.items() if v is None)
        first = next((v for v in vs if not v["verify"].startswith("verify_serial_noise")), vs[0])
        env = env_cause(msgs.get(nid, "")) if "failed" in (p_vals | e_vals) else None
        if env:
            box, why = "ENV", env
        elif len(p_vals) > 1:
            box, why = "THEIRS", "outcome differs between plain runs (no engine)"
        elif p_vals and e_vals - p_vals:
            box, why = "UNDECIDED", "outcome stable in every plain run, different under the engine"
        elif missing:
            box, why = "UNDECIDED", "missing from: " + ", ".join(missing[:6])
        else:
            box, why = "OURS", f"outcome {sorted(p_vals | e_vals)} in every run; engine refused: {first['reason']}"
        fails = sorted(k for k, v in po.items() if v == "failed")
        extra = {}
        if box == "THEIRS":
            extra = {"reproduced": f"{len(fails)} of {len(po)} plain runs failed", "failed_in": fails,
                     "reported": reported(d, nid, secs)}
        res[nid] = {"box": box, "why": why, **extra, "reason": first["reason"], "status": first["status"],
                    "also_serial_vs_serial": nid in serial_noise, "plain": po, "engine": eo, "verdicts": vs}
    count = collections.Counter(r["box"] for r in res.values())
    sub = collections.Counter((r["box"], r["reason"], r["also_serial_vs_serial"]) for r in res.values())
    summary = {"repo": o.name, "not_identical_tests": len(res), "boxes": dict(count),
               "by_box_reason_serialnoise": [[*k, v] for k, v in sorted(sub.items(), key=lambda x: -x[1])],
               "plain_runs": sorted(plain), "engine_runs": sorted(engine)}
    theirs = [r for r in res.values() if r["box"] == "THEIRS"]
    cond4_bad = [n for n, r in res.items() if r["box"] == "THEIRS" and not all(x["ok"] for x in r["reported"].values())]
    summary["rule"] = {
        "zero_OURS_UNDECIDED_ENV": all(count.get(b, 0) == 0 for b in ("OURS", "UNDECIDED", "ENV")),
        "THEIRS_all_reproduced": all(r["failed_in"] for r in theirs),
        "THEIRS_reported_equal_or_named": not cond4_bad, "THEIRS_reported_bad": cond4_bad[:20],
    }
    with open(os.path.join(d, "classification.json"), "w") as f:
        json.dump({"summary": summary, "tests": res}, f, indent=1)
    print(json.dumps(summary, indent=1))
    if o.bugs:
        theirs = {n: r for n, r in res.items() if r["box"] == "THEIRS"}
        os.makedirs(o.bugs, exist_ok=True)
        path = os.path.join(o.bugs, f"{o.name}.md")
        with open(path, "w") as f:
            f.write(f"# {o.name}: tests whose outcome changes without the engine (THEIRS)\n\n")
            f.write(f"Repository {spec['repo']} at {spec['commit']}; engine verdicts from trunk "
                    f"{sorted({json.loads(l)['engine_commit'][:8] for l in open(os.path.join(os.path.abspath(o.out), 'results.jsonl')) if json.loads(l)['repo'] == o.name})}. "
                    f"Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.\n\n")
            f.write(f"{len(theirs)} test(s).\n\n")
            for nid, r in sorted(theirs.items()):
                fails = sorted(k for k, v in r["plain"].items() if v == "failed")
                passes = sorted(k for k, v in r["plain"].items() if v == "passed")
                v0 = r["verdicts"][0]
                f.write(f"## `{nid}`\n\n")
                f.write(f"* plain runs failed: {', '.join(fails) or '-'}; passed: {', '.join(passes) or '-'}\n")
                f.write(f"* engine runs: " + ", ".join(f"{k}={v}" for k, v in sorted(r["engine"].items())) + "\n")
                f.write(f"* engine cause ({v0['verify']}): [{v0['reason']}] {v0['description']}\n")
                f.write(f"* first differing event: {json.dumps(v0['event_a'])} vs {json.dumps(v0['event_b'])}\n")
                cmd = next((repro_cmds[k] for k in fails if k in repro_cmds), None)
                f.write(f"* reproduce (plain runner, no engine): `cd <checkout> && {cmd}`\n" if cmd else
                        "* reproduce: failed only in a plain serial round of measure.py (command in results.jsonl)\n")
                f.write(f"* reproduces: {'yes' if fails else 'no'} ({len(fails)} of {len(r['plain'])} plain runs failed)\n\n")
        print("wrote", path)


if __name__ == "__main__":
    main()
