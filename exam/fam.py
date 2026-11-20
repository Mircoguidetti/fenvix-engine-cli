"""Check families shared by the rows: DET2, CACHE2, EDIT (Python and Node), probes."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import lib
from lib import Ctx, Skip
from projects import P

# =====================================================================================================================
# Python
# =====================================================================================================================


def py_setup(ctx: Ctx, name: str, extra: list | None = None, key=None) -> tuple:
    ctx.need_install()
    proj = P[name]
    d = ctx.clone(proj)
    env = lib.venv(ctx, d, proj.get("install", []) + (extra or []), key=key)
    return d, env


def py_det2(ctx: Ctx, d: Path, env: dict, args: list, tag: str, extra_env=None, plain_args=None) -> tuple:
    rc0, out0, plain = lib.pytest_plain(ctx, d, env, plain_args if plain_args is not None else args, tag, extra_env)
    t = [ctx.work / f"{tag}-det1.jsonl", ctx.work / f"{tag}-det2.jsonl"]
    outs = []
    for i in (0, 1):
        if t[i].exists():
            t[i].unlink()
        rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-trace={t[i]}"] + args, f"{tag}-det{i + 1}", extra_env)
        outs.append((rc, out, o))
    vok, vdesc, rep = lib.verify(ctx, d, env, t[0], t[1], f"{tag}-verify")
    cok, cdesc = lib.cmp_outcomes(outs[0][2], plain)
    ok = vok and cok
    return ok, f"verify: {vdesc}; outcomes vs plain: {cdesc}", {"first_divergence": lib.first_divergence(rep)[:5],
                                                               "plain_rc": rc0, "det_rc": [o[0] for o in outs]}


def py_cache2(ctx: Ctx, d: Path, env: dict, args: list, tag: str, min_share=0.5, extra_env=None) -> tuple:
    cache = ctx.work / f"{tag}-cache"
    shutil.rmtree(cache, ignore_errors=True)
    rc0, _, plain = lib.pytest_plain(ctx, d, env, args, tag, extra_env)
    res = []
    for i in (1, 2):
        rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}"] + args, f"{tag}-cache{i}", extra_env)
        res.append((rc, out, o, lib.reused_count(out)))
    reused = res[1][3]
    npass = sum(1 for v in plain.values() if lib.norm(v) == "passed")
    cok, cdesc = lib.cmp_outcomes(res[1][2], plain)
    share_ok = npass > 0 and reused >= max(1, int(min_share * npass))
    return (cok and share_ok, f"run 2 reused {reused} of {npass} passing (needed >= {max(1, int(min_share * npass))}); "
                              f"outcomes vs plain: {cdesc}", {"rc": [r[0] for r in res], "plain_rc": rc0})


def py_edit(ctx: Ctx, d: Path, env: dict, args: list, tag: str, edit, extra_env=None) -> tuple:
    """EDIT family: cache run 1, apply edit(d), cache run 2, plain run of the edited checkout."""
    cache = ctx.work / f"{tag}-cache"
    shutil.rmtree(cache, ignore_errors=True)
    rc1, out1, o1 = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}"] + args, f"{tag}-run1", extra_env)
    _, _, plain_before = lib.pytest_plain(ctx, d, env, args, f"{tag}-before", extra_env)
    what = edit(d)
    rc2, out2, o2 = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}"] + args, f"{tag}-run2", extra_env)
    _, _, plain = lib.pytest_plain(ctx, d, env, args, f"{tag}-after", extra_env)
    ctx.reset(d)
    flipped = sorted(k for k in plain if lib.norm(plain[k]) != lib.norm(plain_before.get(k)))
    cok, cdesc = lib.cmp_outcomes(o2, plain)
    reused = lib.reused_count(out2)
    ran = re.findall(r"ran (\d+)", out2)
    ok = cok and reused > 0 and bool(flipped or "no flip expected" in what)
    return ok, (f"edit: {what}; plain outcome changed for {len(flipped)} tests {flipped[:3]}; run 2 reused {reused}, "
                f"ran {ran[-1] if ran else '?'}; outcomes vs plain rerun: {cdesc}"), {"stale": [k for k in flipped if
                                                                                  lib.norm(o2.get(k)) != lib.norm(plain.get(k))][:10]}


def replace_in(path: Path, old: str, new: str, count=1) -> bool:
    s = path.read_text()
    if old not in s:
        raise Skip(f"edit anchor not found in {path.name}: {old[:60]!r}")
    path.write_text(s.replace(old, new, count))
    return True


# --------------------------------------------------------------------------------------------------------------------
# Python probes: test files written into a pinned host project (itsdangerous), run with the customer's commands
# --------------------------------------------------------------------------------------------------------------------

PROBE_HOST = "itsdangerous"


def probe_host(ctx: Ctx) -> tuple:
    return py_setup(ctx, PROBE_HOST)


def write_probe(d: Path, name: str, body: str) -> str:
    rel = f"tests/test_exam_{name}.py"
    lib.write(d / rel, body)
    return rel


def py_value_probe(ctx: Ctx, name: str, body: str, envs: list, det_args=None, filterwarnings=True) -> dict:
    """Write a probe that stores a value in $EXAM_OUT, run it under --det once per env; return values, traces,
    outcomes and the verify result between the first two runs."""
    d, env = probe_host(ctx)
    rel = write_probe(d, name, body)
    vals, traces, outs = [], [], []
    for i, e in enumerate(envs):
        out_p = ctx.work / f"probe-{name}-{i}.out"
        if out_p.exists():
            out_p.unlink()
        t = ctx.work / f"probe-{name}-{i}.jsonl"
        if t.exists():
            t.unlink()
        ee = dict(e, EXAM_OUT=str(out_p))
        rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-trace={t}", "-W", "ignore"] + (det_args or []) + [rel],
                                       f"probe-{name}-{i}", ee)
        vals.append(out_p.read_text() if out_p.exists() else None)
        traces.append(t)
        outs.append((rc, o))
    vok, vdesc, rep = lib.verify(ctx, d, env, traces[0], traces[1], f"probe-{name}-verify")
    (d / rel).unlink(missing_ok=True)
    return {"values": vals, "verify_ok": vok, "verify": vdesc, "report": rep, "outcomes": outs, "d": d, "env": env}


def py_cache_probe(ctx: Ctx, name: str, body: str, env1: dict, env2: dict, between=None, args=None) -> tuple:
    """Run a probe under --det-cache with env1 (record), change something (env2 and/or between(d)), run again; the
    second run must give the plain run's outcome under the changed condition (no stale reuse)."""
    d, env = probe_host(ctx)
    rel = write_probe(d, name, body)
    cache = ctx.work / f"cprobe-{name}"
    shutil.rmtree(cache, ignore_errors=True)
    a = ["--det", f"--det-cache={cache}", "-W", "ignore"] + (args or []) + [rel]
    rc1, out1, o1 = lib.pytest_engine(ctx, d, env, a, f"cprobe-{name}-1", env1)
    if between:
        between(d)
    rc2, out2, o2 = lib.pytest_engine(ctx, d, env, a, f"cprobe-{name}-2", env2)
    _, _, plain = lib.pytest_plain(ctx, d, env, ["-W", "ignore"] + (args or []) + [rel], f"cprobe-{name}-plain", env2)
    (d / rel).unlink(missing_ok=True)
    reused = lib.reused_count(out2)
    cok, cdesc = lib.cmp_outcomes(o2, plain)
    first = list(o1.values())[:1]
    return cok, f"run1 {first}; run2 reused {reused}; run2 vs plain under the changed input: {cdesc}", {"o1": o1, "o2": o2, "plain": plain}


# =====================================================================================================================
# Node
# =====================================================================================================================

NODE_RUNNERS = {
    # runner: (plain command, engine subcommand, json-capable)
    "vitest": ("npx vitest run", "vitest run", "vitest"),
    "jest": ("npx jest --ci", "jest --ci", "jest"),
    "mocha": ("npx mocha", "mocha", None),
    "node-test": ("node --test", "node-test", None),
    "ava": ("npx ava", "ava", None),
    "tap": ("npx tap", "tap", None),
    "uvu": ("npx uvu", "uvu", None),
    "jasmine": ("npx jasmine", "jasmine", None),
    "bun-test": ("bun test", "bun-test", None),
    "deno-test": ("deno test", "deno-test", None),
}


def js_setup(ctx: Ctx, name: str, pm="npm", extra=None, pre=None, key=None) -> Path:
    proj = P[name]
    d = ctx.clone(proj, name=key)
    ctx.need_install()
    if pre:
        pre(ctx, d)
    if pm != "none":
        lib.npm_install(ctx, d, pm, extra)
    return d


def _json_outcomes(path: Path, root: Path) -> dict:
    """Vitest/Jest JSON report -> {file: {"passed": n, "failed": n, "skipped": n}}."""
    d = lib.load_json(path)
    res = {}
    for f in d.get("testResults", []):
        name = os.path.relpath(f.get("name", ""), root)
        c = res.setdefault(name, {"passed": 0, "failed": 0, "skipped": 0})
        for a in f.get("assertionResults", []):
            c[lib.norm(a.get("status"))] = c.get(lib.norm(a.get("status")), 0) + 1
        if not f.get("assertionResults") and f.get("status") == "failed":
            c["failed"] += 1
    return res


def _receipt_outcomes(d: Path, run_json: dict | None = None) -> tuple:
    """Per-file counts of a cached run: files that ran come from the runner's JSON report (when it has one), files
    reused with proof from the engine's receipts. Returns (counts, number of tests reused)."""
    o, n = lib.detjs_receipts(d, reused_only=bool(run_json))
    res = {k: dict(v) for k, v in ((run_json or {}).get("files") or {}).items()}
    ran_files = set(res)
    for nid, out in o.items():
        if "::" not in nid or nid.split("::")[0] in ran_files:
            continue
        f = nid.split("::")[0]
        c = res.setdefault(f, {"passed": 0, "failed": 0, "skipped": 0})
        c[lib.norm(out)] = c.get(lib.norm(out), 0) + 1
    return res, n


def js_run(ctx: Ctx, d: Path, runner: str, args: str, tag: str, engine: bool, det_opts="", env=None) -> tuple:
    """Run a Node runner plainly or through `fenvix node`; returns (rc, out, outcome) where outcome is a per-file
    count map (JSON-capable runners) or the summary counts."""
    plain_cmd, sub, js = NODE_RUNNERS[runner]
    rep = ctx.work / f"js-{tag}-{ctx._n + 1}.json"
    jargs = ""
    if js == "vitest":
        jargs = f" --reporter=json --outputFile={rep}"
    elif js == "jest":
        jargs = f" --json --outputFile={rep}"
    if engine:
        cmd = f"fenvix node {sub} {det_opts} {args}{jargs}"
    else:
        cmd = f"{plain_cmd} {args}{jargs}"
    rc, out = ctx.sh(f"{'fenvix' if engine else 'plain'}-{tag}", cmd, cwd=d, env=env, timeout=2400)
    if js and rep.exists():
        return rc, out, {"files": _json_outcomes(rep, d)}
    return rc, out, {"rc": rc, "counts": lib.counts(out)}


def js_cmp(eng: dict, plain: dict) -> tuple:
    if "files" in plain and "files" in eng:
        a, b = eng["files"], plain["files"]
        if not b:
            return False, "plain run produced no outcomes"
        diff = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f))
        tot = sum(sum(v.values()) for v in b.values())
        return not diff, f"{len(b)} files / {tot} tests in plain; differing files {len(diff)} {diff[:4]}"
    ok = eng.get("rc") == plain.get("rc") and eng.get("counts") == plain.get("counts") and bool(plain.get("counts"))
    return ok, f"engine rc={eng.get('rc')} counts={eng.get('counts')}; plain rc={plain.get('rc')} counts={plain.get('counts')}"


def js_det2(ctx: Ctx, d: Path, runner: str, args: str, tag: str, env=None, det_extra="") -> tuple:
    rc0, _, plain = js_run(ctx, d, runner, args, f"{tag}-plain", False, env=env)
    t = [ctx.work / f"{tag}-det1.jsonl", ctx.work / f"{tag}-det2.jsonl"]
    res = []
    for i in (0, 1):
        if t[i].exists():
            t[i].unlink()
        res.append(js_run(ctx, d, runner, args, f"{tag}-det{i + 1}", True, f"--det --det-trace={t[i]} {det_extra}", env=env))
    vok, vdesc, rep = lib.verify(ctx, d, env or {}, t[0], t[1], f"{tag}-verify")
    cok, cdesc = js_cmp(res[0][2], plain)
    return vok and cok, f"verify: {vdesc}; outcomes vs plain: {cdesc}", {"first_divergence": lib.first_divergence(rep)[:5],
                                                                         "rc": [r[0] for r in res], "plain_rc": rc0}


def js_cache2(ctx: Ctx, d: Path, runner: str, args: str, tag: str, env=None, min_share=0.5) -> tuple:
    cache = ctx.work / f"{tag}-cache"
    shutil.rmtree(cache, ignore_errors=True)
    rc0, _, plain = js_run(ctx, d, runner, args, f"{tag}-plain", False, env=env)
    res = []
    for i in (1, 2):
        shutil.rmtree(d / ".detjs", ignore_errors=True)
        rc, out, o = js_run(ctx, d, runner, args, f"{tag}-cache{i}", True, f"--det --det-cache={cache}", env=env)
        ro, n = _receipt_outcomes(d, o)
        m = re.findall(r"reused with proof (\d+) tests", out)
        res.append((rc, out, o, ro, max(n, int(m[-1]) if m else 0)))
    rc2, out2, o2, ro2, reused = res[1]
    total = sum(v.get("passed", 0) for v in plain.get("files", {}).values()) if "files" in plain else (plain.get("counts", {}).get("passed") or 0)
    if "files" in plain:
        cok, cdesc = js_cmp({"files": ro2}, plain)
    else:
        cok, cdesc = (rc2 == plain.get("rc")), f"engine rc={rc2}, plain rc={plain.get('rc')} counts={plain.get('counts')}"
    need = max(1, int(min_share * total))
    return cok and reused >= need, f"run 2 reused {reused} (needed >= {need} of {total} passing); outcomes vs plain: {cdesc}", {
        "rc": [r[0] for r in res], "plain_rc": rc0}


def js_cache_probe(ctx: Ctx, d: Path, runner: str, relfile: str, body: str, env1: dict, env2: dict, between=None,
                   args="") -> tuple:
    lib.write(d / relfile, body)
    cache = ctx.work / f"jcprobe-{Path(relfile).stem}"
    shutil.rmtree(cache, ignore_errors=True)
    shutil.rmtree(d / ".detjs", ignore_errors=True)
    rc1, out1, _ = js_run(ctx, d, runner, f"{args} {relfile}", "jcprobe-1", True, f"--det --det-cache={cache}", env=env1)
    o1, _ = _receipt_outcomes(d, _)
    if between:
        between(d)
    shutil.rmtree(d / ".detjs", ignore_errors=True)
    rc2, out2, j2 = js_run(ctx, d, runner, f"{args} {relfile}", "jcprobe-2", True, f"--det --det-cache={cache}", env=env2)
    o2, n = _receipt_outcomes(d, j2)
    rcp, outp, plain = js_run(ctx, d, runner, f"{args} {relfile}", "jcprobe-plain", False, env=env2)
    (d / relfile).unlink(missing_ok=True)
    if "files" in plain:
        cok, cdesc = js_cmp({"files": o2}, plain)
    else:
        cok, cdesc = rc2 == rcp, f"engine rc={rc2}, plain rc={rcp}"
    return cok, f"run1 {o1}; run2 reused {n}, outcomes {o2}; vs plain under the changed input: {cdesc}", {}


def js_value_probe(ctx: Ctx, d: Path, runner: str, relfile: str, body: str, envs: list, args="", det_extra="") -> dict:
    lib.write(d / relfile, body)
    vals, traces = [], []
    for i, e in enumerate(envs):
        out_p = ctx.work / f"jprobe-{Path(relfile).stem}-{i}.out"
        if out_p.exists():
            out_p.unlink()
        t = ctx.work / f"jprobe-{Path(relfile).stem}-{i}.jsonl"
        if t.exists():
            t.unlink()
        js_run(ctx, d, runner, f"{args} {relfile}", f"jprobe-{i}", True, f"--det --det-trace={t} {det_extra}",
               env=dict(e, EXAM_OUT=str(out_p)))
        vals.append(out_p.read_text() if out_p.exists() else None)
        traces.append(t)
    vok, vdesc, rep = lib.verify(ctx, d, {}, traces[0], traces[1], f"jprobe-{Path(relfile).stem}-verify")
    (d / relfile).unlink(missing_ok=True)
    return {"values": vals, "verify_ok": vok, "verify": vdesc, "report": rep}
