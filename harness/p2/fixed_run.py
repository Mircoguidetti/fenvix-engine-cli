#!/usr/bin/env python3
"""Untimed engine run with a fixed epoch, for the P2 correctness check (spec, Definitions, rule 2) and Phase B.

The command is built from the spec entry's runner arguments as measure.py's `serial()` does, but with:
  * the `detjs.js` of the checkout under test (`--engine`), not of this harness checkout;
  * `--det-epoch=fixed` (session.js), so fingerprints compare across commits;
  * its own trace path `<out>/<repo>/F-<label>.jsonl` (never the timed `S<i>.jsonl` / `P<i>w<n>.jsonl`);
  * measure.py's environment: spec `env`, the per-repository TMPDIR of `tmp_env` (emptied before the run), the
    VOLATILE names removed; then only what is passed with --env / --node-options (Phase B), recorded in the row.
The tree is reset first (measure.py `clean()`: reset, optional build, reporter placed). Every run appends one row to
`<out>/fixed.jsonl` with its full command and environment, and writes the per-test extract
`<out>/<repo>/tests-F-<label>.jsonl.gz` (with each test's event list).

Usage: fixed_run.py --spec specs.json --name REPO --engine CHECKOUT --label LABEL --out DIR
                    [--workers N] [--env K=V ...] [--node-options STR] [--trace-name NAME] [--timeout S]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "parallel_measure"))
sys.path.insert(0, HERE)
import measure  # noqa: E402
import extract  # noqa: E402

ENGINE_SOURCES = ["crates", "python", "node/src", "node/bin", "Cargo.toml", "Cargo.lock", "pyproject.toml"]
TIMED_TRACE = re.compile(r"^(S\d+|P\d+w\d+)\.jsonl$")
SECRET = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_KEY|APIKEY|AUTH", re.I)


def build_cmd(spec, engine, trace, workers=1, epoch="fixed"):
    """The detjs command of a fixed-epoch run (measure.py serial() / par() with the checkout-under-test engine)."""
    runner = spec["runner"]
    if runner not in ("vitest", "jest"):
        raise ValueError(f"fixed_run.py: Node runners only (vitest, jest), got {runner}")
    detjs = os.path.join(os.path.abspath(engine), "node", "bin", "detjs.js")
    base = ["node", detjs, runner] + (["run"] if runner == "vitest" else []) + list(spec.get("args", []))
    return base + ["--det", f"--det-workers={workers}", f"--det-trace={trace}", f"--det-epoch={epoch}"]


def trace_path(out_repo, label, trace_name=None):
    name = trace_name or f"F-{label}.jsonl"
    if TIMED_TRACE.match(name) or os.path.basename(name) != name:
        raise ValueError(f"fixed_run.py: trace name {name!r} would collide with a timed trace or leave {out_repo}")
    return os.path.join(out_repo, name)


def build_env(spec, name, extra=(), node_options=None, base=None):
    env = {k: v for k, v in (os.environ if base is None else base).items() if k not in measure.VOLATILE}
    env.update({k: os.path.expandvars(v) for k, v in spec.get("env", {}).items()})
    env = measure.tmp_env(env, measure.run_tmpdir(name))
    added = {}
    for kv in extra:
        k, _, v = kv.partition("=")
        if not k:
            raise ValueError(f"fixed_run.py: --env {kv!r}: K=V expected")
        added[k] = v
    if node_options:
        added["NODE_OPTIONS"] = node_options
    env.update(added)
    return env, added


def engine_identity(engine):
    g = lambda *a: subprocess.run(["git", "-C", engine, *a], capture_output=True, text=True).stdout.strip()
    head = g("rev-parse", "HEAD")
    clean = subprocess.run(["git", "-C", engine, "diff", "--quiet", "HEAD", "--", *ENGINE_SOURCES]).returncode == 0
    addon = os.path.join(engine, "node", f"detjs.linux-x64.node")
    try:
        with open(addon, "rb") as f:
            addon_sha = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        addon_sha = None
    return {"engine": os.path.abspath(engine), "engine_commit": head if clean else head + "+modified", "addon_sha256": addon_sha}


def redact(env):
    return {k: ("<redacted>" if SECRET.search(k) else v) for k, v in sorted(env.items())}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--engine", required=True, help="the checkout whose node/bin/detjs.js and addon are under test")
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--env", action="append", default=[], help="K=V added after measure.py's environment (Phase B)")
    ap.add_argument("--node-options", default=None, help="NODE_OPTIONS of this run (Phase B --cpu-prof)")
    ap.add_argument("--trace-name", default=None)
    ap.add_argument("--epoch", default="fixed")
    ap.add_argument("--timeout", type=int, default=7200)
    ap.add_argument("--no-events", action="store_true", help="extract without the per-test event lists")
    o = ap.parse_args(argv)
    with open(o.spec) as f:
        spec = json.load(f)[o.name]
    cwd = os.path.expandvars(spec["dir"])
    out = os.path.abspath(o.out)
    out_repo = os.path.join(out, o.name)
    os.makedirs(out_repo, exist_ok=True)
    trace = trace_path(out_repo, o.label, o.trace_name)
    for stale in (trace, trace + ".phases.jsonl"):  # a DETJS_PHASES run appends to <trace>.phases.jsonl
        if os.path.exists(stale):
            os.remove(stale)
    cmd = build_cmd(spec, o.engine, trace, o.workers, o.epoch)
    env, added = build_env(spec, o.name, o.env, o.node_options)
    log = os.path.join(out_repo, "runs.log")

    # measure.py clean(): tree reset, optional build, Vitest reporter placed (same tree as a timed run)
    measure.reset_tree(cwd, spec)
    build = measure.build_after_reset(cwd, spec.get("build"), env, log)
    if spec["runner"] == "vitest":
        measure.place_reporter(cwd)
    measure.reset_tmpdir(measure.run_tmpdir(o.name))  # gate rev 4 note 8 (measure.run() empties it again)
    r, text = measure.run(cmd, cwd, env, log, o.timeout)
    _, tests = measure.trace_tests(trace)
    ext = os.path.join(out_repo, f"tests-{os.path.splitext(os.path.basename(trace))[0]}.jsonl.gz")
    n = extract.write(trace, ext, events=not o.no_events) if os.path.exists(trace) else 0
    row = {"repo": o.name, "commit": spec.get("commit"), "runner": spec["runner"], "kind": "fixed", "label": o.label,
           **({"declared_change": spec["declared_change"]} if spec.get("declared_change") else {}),
           "workers": o.workers, **engine_identity(o.engine), "cpus": os.cpu_count(), "cpu_model": measure.CPU_MODEL,
           "host": measure.HOST, "container_boot": measure.CONTAINER_BOOT, **build, "cmd": " ".join(cmd), "cwd": cwd,
           "env": redact(env), "env_added": added, "trace": os.path.relpath(trace, out), "extract": os.path.relpath(ext, out),
           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **r, "tests": len(tests),
           "outcome_counts": measure.counts({k: v[0] for k, v in tests.items()}), "extract_tests": n}
    with open(os.path.join(out, "fixed.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps({k: row[k] for k in ("repo", "label", "workers", "exit", "wall_s", "tests", "outcome_counts")}), flush=True)
    return row


if __name__ == "__main__":
    main()
