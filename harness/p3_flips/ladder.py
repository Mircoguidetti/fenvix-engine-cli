#!/usr/bin/env python3
"""P3 step B, per test file: alone runs, predecessor search, engine-control ladder L1-L7 and plain reproduction.

    PM_WORK=/tmp/pm-p3 python3 harness/p3_flips/ladder.py file --repo R --find /tmp/pm-p3/find --file 'test/x.test.ts'
    PM_WORK=/tmp/pm-p3 python3 harness/p3_flips/ladder.py neutral --repo R --find /tmp/pm-p3/find
    python3 harness/p3_flips/ladder.py rows --find /tmp/pm-p3/find        -> harness/p3_flips/rows.jsonl

Every run: tree reset (pins.do_run / measure.reset_tree), TMPDIR emptied, the run recorded in <work>/runs.jsonl.
A case's outcome in a run is read from the outcome of its own test id (the --det-outcomes file, or the plain runner's
ids/JSON report), never from the command's exit code (spec B0). This script records evidence only; the verdict rule
lives in classify.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "det_pins"))
sys.path.append(os.path.join(HERE, "..", "parallel_measure"))
import measure  # noqa: E402
import pins  # noqa: E402
from cases import norm, shape  # noqa: E402

DETJS = measure.DETJS
DATA = os.path.join(HERE, "data")

# spec B2: each step adds exactly one control
LADDER = [
    ("L1", ["--det-timers=real"], None),
    ("L2a", ["--det-disable=timers"], {"timers"}),
    ("L2b", ["--det-disable=timers,net"], {"timers", "net"}),
    ("L3", ["--det-disable=timers,net,fs"], {"timers", "net", "fs"}),
    ("L4", ["--det-disable=time,timers,net,fs"], {"time", "timers", "net", "fs"}),
    ("L5", ["--det-disable=time,timers,net,fs,seeds"], {"time", "timers", "net", "fs", "seeds"}),
    ("L6", ["--det-disable=time,timers,net,fs,seeds,order"], {"time", "timers", "net", "fs", "seeds", "order"}),
    ("L7", ["--det-disable=order,seeds,time,timers,fs,net,isolation"],
     {"order", "seeds", "time", "timers", "fs", "net", "isolation"}),
]
CAUSE = {"L1": "timers progression (virtual)", "L2a": "timers", "L2b": "net", "L3": "fs", "L4": "time", "L5": "seeds",
         "L6": "order", "L7": "isolation"}
MAX_PROBES = 8
SKIP_KINDS = ("other",)  # recorded UNDECIDED, no verdict search (unstable ids likewise)


# ---------------------------------------------------------------------------------------------- per-kind outcome rule
def state(kind, o):
    """'repro' | 'clear' | 'invalid' | 'neither' for a case of `kind` whose id had outcome `o` (normalised; None =
    missing) in one --det run (spec B intro and B0)."""
    if kind in ("flip", "mixed"):
        return "invalid" if o is None else "repro" if o == "failed" else "clear" if o == "passed" else "neither"
    if kind == "absent":
        return "repro" if o is None else "clear" if o == "passed" else "neither"
    if kind == "skipped-in-det":
        return "invalid" if o is None else "repro" if o == "skipped" else "clear" if o == "passed" else "neither"
    if kind == "det-only":
        return "repro" if o is not None else "clear"
    if kind == "reverse":
        return "invalid" if o is None else "repro" if o in ("passed", "skipped") else "clear"
    raise ValueError(kind)


def plain_state(kind, o):
    """'plain' (the plain outcome of A) | 'det' (the --det outcome of A) | 'invalid' | 'neither', for a plain run."""
    if kind == "det-only":
        return "plain" if o is None else "det"
    if o is None:
        return "invalid"
    if kind == "reverse":
        return "plain" if o == "failed" else "det"
    if kind in ("flip", "mixed"):
        return "plain" if o == "passed" else "det" if o == "failed" else "neither"
    if kind in ("absent", "skipped-in-det"):  # the --det outcome was "not run / skipped"
        return "plain" if o == "passed" else "det" if o == "skipped" else "neither"
    raise ValueError(kind)


def step_states(case, runs):
    """A ladder step's per-run states for one case, from the outcome of the case's own id (never the exit code); an
    invalid run (flag not in effect) is 'invalid', never 'did not clear'. Cleared = every run clears (2 of 2; 5 of 5
    for a mixed-outcome case, whose caller passes its 5 runs)."""
    st = [state(case["kind"], r["outcomes"].get(case["id"])) if r.get("valid", True) else "invalid" for r in runs]
    return st, bool(st) and all(x == "clear" for x in st)


def mixed_outcome(case):
    return case["kind"] in ("mixed", "det-only", "reverse") and case["results"][2] != case["results"][3]


# -------------------------------------------------------------------------------------------------------- runs
def split_file(f):
    return f.split("@@", 1) if "@@" in f else (f, "")


def file_of(tid):
    return tid.split("::", 1)[0]


class Ctx:
    def __init__(self, o):
        self.repo = o.repo
        self.spec = pins.load_spec(o.repo)
        self.cwd = os.path.expandvars(self.spec["dir"])
        self.env = pins.base_env(o.repo, self.spec)
        self.args = self.spec.get("args", [])
        self.find = os.path.join(o.find, o.repo)
        self.work = os.path.join(o.find, o.repo, "b")
        os.makedirs(self.work, exist_ok=True)
        self.cases = json.load(open(os.path.join(self.find, "cases.json")))["cases"]
        self.det_orders = [json.load(open(f"{self.find}/det{i}.outcomes.json")).get("order") or [] for i in (1, 2)]

    def run(self, tag, cmd, env=None, plain=False, harness=False, timeout=3600):
        measure.reset_tree(self.cwd)
        if plain:
            measure.place_reporter(self.cwd)
        if harness:
            place_harness_config(self.cwd)
        r, text = measure.run(cmd, self.cwd, env or self.env, os.path.join(self.work, "runs.log"), timeout)
        row = {"repo": self.repo, "tag": tag, "cmd": " ".join(cmd), "cwd": self.cwd, "engine_commit": pins.engine_commit(),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **r, "tail": text[-1500:]}
        with open(os.path.join(self.work, "runs.jsonl"), "a") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def det(self, tag, files, flags, order_ids=None):
        """One --det --det-workers=1 run of `files` (or of the ids in order_ids, in that order)."""
        d = os.path.join(self.work, "runs")
        os.makedirs(d, exist_ok=True)
        of, tf = f"{d}/{tag}.outcomes.json", f"{d}/{tag}.trace.jsonl"
        sel = []
        if order_ids is not None:
            op = f"{d}/{tag}.order.txt"
            with open(op, "w") as f:
                f.write("\n".join(order_ids) + "\n")
            sel = [f"--det-order={op}"]
        else:
            for fid in files:
                p, proj = split_file(fid)
                sel += [p] + (["--project", proj] if proj else [])
        cmd = (["node", DETJS, "vitest", "run"] + self.args + sel +
               ["--det", "--det-workers=1", f"--det-outcomes={of}", f"--det-trace={tf}"] + flags)
        row = self.run(tag, cmd)
        oc, ex = pins.det_outcomes(of)
        meta, controls = trace_meta(tf), None
        if os.path.exists(of):
            controls = json.load(open(of)).get("controls")
        for p in (tf,):  # traces are large; the meta is kept in the row
            if os.path.exists(p):
                os.remove(p)
        return {"tag": tag, "cmd": row["cmd"], "exit": row["exit"], "wall_s": row["wall_s"],
                "outcomes": {k: norm(v) for k, v in oc.items()}, "exc": {k: pins.first_line(v) for k, v in ex.items()},
                "meta": meta, "controls": controls, "order": (json.load(open(of)).get("order") if os.path.exists(of) else None)}

    def plain(self, tag, files, order=None, harness=True, prefix=None):
        """One plain serial run (no detjs, no engine path) of `files` through the harness config; `order` = the file
        order the sequencer replays (None: Vitest's default order)."""
        d = os.path.join(self.work, "runs")
        os.makedirs(d, exist_ok=True)
        rj, ij, ap = f"{d}/{tag}.runner.json", f"{d}/{tag}.ids.json", f"{d}/{tag}.applied.txt"
        env = {**self.env, "PM_IDS_OUT": ij, "P3_APPLIED": ap}
        env.pop("P3_ORDER", None)
        if order is not None:
            op = f"{d}/{tag}.order.txt"
            with open(op, "w") as f:
                f.write("\n".join(order) + "\n")
            env["P3_ORDER"] = op
        sel = []
        for fid in files or []:
            p, proj = split_file(fid)
            sel += [p] + (["--project", proj] if proj else [])
        ids_path = os.path.join(self.cwd, measure.REPORTER_IN_REPO)
        cmd = (["npx", "--no-install", "vitest", "run"] + self.args + sel +
               (["--config", os.path.join(self.cwd, HARNESS_CONFIG)] if harness else []) +
               ["--no-file-parallelism", "--reporter=default", f"--reporter={ids_path}", "--reporter=json",
                f"--outputFile.json={rj}"])
        if prefix:
            cmd = prefix[:-1] + [prefix[-1] + " ".join(shq(x) for x in cmd)]
        row = self.run(tag, cmd, env=env, plain=True, harness=harness)
        oc = measure.runner_outcomes(rj, self.cwd)
        applied = open(ap).read().split() if os.path.exists(ap) else None
        fails = failure_lines(rj, self.cwd)
        return {"tag": tag, "cmd": row["cmd"], "exit": row["exit"], "wall_s": row["wall_s"],
                "outcomes": {k: norm(v) for k, v in oc.items()}, "exc": fails, "applied": applied,
                "intended": order}


def shq(s):
    import shlex
    return shlex.quote(s)


NET_PREFIX = ["unshare", "-n", "sh", "-c", "ip link set lo up && exec "]
HARNESS_CONFIG = os.path.join(".fenvix-harness", "p3.vitest.config.mjs")


def customer_config(cwd):
    for n in ("vitest.config.ts", "vitest.config.mts", "vitest.config.js", "vitest.config.mjs", "vite.config.ts",
              "vite.config.mts", "vite.config.js", "vite.config.mjs"):
        if os.path.exists(os.path.join(cwd, n)):
            return n
    return None


def place_harness_config(cwd):
    """A harness-only config under .fenvix-harness/ (removed by the next tree reset) that extends the customer config
    and sets the P3 sequencer; the customer repository's files are not touched."""
    dst = os.path.join(cwd, ".fenvix-harness")
    os.makedirs(dst, exist_ok=True)
    shutil.copyfile(os.path.join(HERE, "sequencer.mjs"), os.path.join(dst, "p3-sequencer.mjs"))
    base = customer_config(cwd)
    imp = f"import base from '../{base}';\n" if base else "const base = {};\n"
    src = (imp + "import { mergeConfig } from 'vitest/config';\n"
           "import P3Sequencer from './p3-sequencer.mjs';\n"
           "const b = typeof base === 'function' ? await base({ command: 'serve', mode: 'test' }) : base;\n"
           f"export default mergeConfig(b, {{ root: {json.dumps(cwd)}, test: {{ sequence: {{ sequencer: P3Sequencer }} }} }});\n")
    with open(os.path.join(cwd, HARNESS_CONFIG), "w") as f:
        f.write(src)


def trace_meta(tf):
    try:
        with open(tf) as f:
            head = json.loads(f.readline())
        m = head.get("meta") or {}
        return {k: m.get(k) for k in ("timers", "network", "epoch", "seed")}
    except (OSError, ValueError):
        return None


def failure_lines(rj, cwd):
    out = {}
    try:
        j = json.load(open(rj))
    except (OSError, ValueError):
        return out
    for tr in j.get("testResults", []):
        rel = os.path.relpath(tr["name"], cwd)
        for a in tr.get("assertionResults", []):
            msgs = a.get("failureMessages") or []
            if msgs:
                k = "::".join([rel] + list(a.get("ancestorTitles") or []) + [a["title"]])
                out.setdefault(k, (msgs[0].strip().splitlines() or [""])[0][:300])
    return out


def valid_ladder_run(step, flags_disabled, r):
    if r["meta"] is None or r["controls"] is None:
        return False, "no trace meta or outcomes file"
    if step == "L1":
        return (r["meta"].get("timers") == "real", f"meta timers={r['meta'].get('timers')}")
    left = set(r["controls"]) & flags_disabled
    return (not left, f"controls still on: {sorted(left)}" if left else "ok")


# ------------------------------------------------------------------------------------------------- procedure
def states(cases, runs):
    return {c["id"]: [state(c["kind"], r["outcomes"].get(c["id"])) for r in runs] for c in cases}


def repro_all(cases, runs):
    st = states(cases, runs)
    return {c["id"]: all(s == "repro" for s in st[c["id"]]) for c in cases}


def order_ids_for(ctx, src, files_keep, target, cases):
    """The ids of the recorded --det order of run `src` whose file is in files_keep or is the target file, in that
    order; ids of the target's cases missing from it (absent kinds) are appended after the target file's block."""
    order = ctx.det_orders[src]
    keep = set(files_keep) | {target}
    ids = [i for i in order if file_of(i) in keep]
    missing = [c["id"] for c in cases if c["id"] not in set(ids)]
    if missing:
        last = max((n for n, i in enumerate(ids) if file_of(i) == target), default=len(ids) - 1)
        ids = ids[:last + 1] + missing + ids[last + 1:]
    return ids


def file_order(order):
    seen = []
    for i in order:
        f = file_of(i)
        if f not in seen:
            seen.append(f)
    return seen


def do_file(o):
    ctx = Ctx(o)
    target = o.file
    slug = hashlib.sha1(f"{ctx.repo}:{target}".encode()).hexdigest()[:10]
    cases = [c for c in ctx.cases if file_of(c["id"]) == target]
    res = {"repo": ctx.repo, "file": target, "slug": slug, "engine_commit": pins.engine_commit(), "cases": {}, "steps": []}
    work = [c for c in cases if c["kind"] not in SKIP_KINDS and not c["unstable"]]
    for c in cases:
        res["cases"][c["id"]] = {"kind": c["kind"], "results": c["results"], "unstable": c["unstable"],
                                 "pattern": c.get("pattern"), "det_failure": c["det_failure"],
                                 "mixed_outcome": mixed_outcome(c)}
    out_path = os.path.join(DATA, ctx.repo, "b", f"{slug}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def save():
        with open(out_path, "w") as f:
            json.dump(res, f, indent=1)

    if not work:
        save()
        return
    # B1 triage: the file alone, 2 runs
    alone = [ctx.det(f"{slug}.alone.r{i}", [target], []) for i in (1, 2)]
    res["alone"] = alone_rec = [strip(r, work) for r in alone]
    rep = repro_all(work, alone)
    for c in work:
        res["cases"][c["id"]]["alone"] = {"states": states([c], alone)[c["id"]], "reproduces": rep[c["id"]]}
    groups = []
    g_alone = [c for c in work if rep[c["id"]]]
    if g_alone:
        groups.append({"set": "alone", "files": [target], "order_ids": None, "cases": g_alone})
    rest = [c for c in work if not rep[c["id"]]]
    if rest:
        # which recorded --det run: the first in which every remaining case reproduced, else run 1
        src = 0
        for i in (0, 1):
            if all(state(c["kind"], c["results"][2 + i]) == "repro" for c in rest):
                src = i
                break
        files = file_order(ctx.det_orders[src])
        preds = files[:files.index(target)] if target in files else files
        res["pred"] = {"src_run": src + 1, "n_preds": len(preds), "probes": []}
        full_ids = order_ids_for(ctx, src, preds, target, rest)
        full = [ctx.det(f"{slug}.full.r{i}", None, [], full_ids) for i in (1, 2)]
        res["pred"]["full"] = [strip(r, rest) for r in full]
        frep = repro_all(rest, full)
        not_full = [c for c in rest if not frep[c["id"]]]
        for c in not_full:
            res["cases"][c["id"]]["undecided"] = "not reproduced outside the whole suite"
        rest = [c for c in rest if frep[c["id"]]]
        cur = preds
        n = 0
        while rest and len(cur) > 1 and n < MAX_PROBES:
            half = len(cur) // 2
            moved = False
            for part in (cur[:half], cur[half:]):
                if n >= MAX_PROBES:
                    break
                n += 1
                ids = order_ids_for(ctx, src, part, target, rest)
                pr = [ctx.det(f"{slug}.probe{n}.r{i}", None, [], ids) for i in (1, 2)]
                ok = any(repro_all(rest, pr).values())
                res["pred"]["probes"].append({"n": n, "files": part, "reproduces": ok, "runs": [strip(r, rest) for r in pr],
                                              "per_case": repro_all(rest, pr)})
                if ok:
                    cur, moved = part, True
                    last = repro_all(rest, pr)
                    break
            if not moved:
                break
        res["pred"]["smallest"] = cur
        if rest:
            if cur is preds:
                in_small = {c["id"]: True for c in rest}
            else:
                in_small = last
            small = [c for c in rest if in_small[c["id"]]]
            other = [c for c in rest if not in_small[c["id"]]]
            if small:
                groups.append({"set": "smallest", "files": cur + [target], "order_ids": order_ids_for(ctx, src, cur, target, small),
                               "cases": small, "src": src})
            if other:
                groups.append({"set": "full", "files": preds + [target], "order_ids": full_ids, "cases": other, "src": src})
    for gi, g in enumerate(groups):
        for c in g["cases"]:
            res["cases"][c["id"]]["set"] = {"name": g["set"], "files": g["files"]}
        ladder(ctx, res, slug, gi, g)
        save()
        plain_repro(ctx, res, slug, gi, g)
        save()
    save()


def strip(r, cases):
    ids = [c["id"] for c in cases]
    return {k: r[k] for k in ("tag", "cmd", "exit", "wall_s", "meta", "controls")} | {
        "outcomes": {i: r["outcomes"].get(i) for i in ids}, "exc": {i: r["exc"].get(i) for i in ids}}


def ladder(ctx, res, slug, gi, g):
    pending = {c["id"]: c for c in g["cases"]}
    nrun = 5 if any(mixed_outcome(c) for c in g["cases"]) else 2
    for step, flags, disabled in LADDER:
        if not pending:
            break
        runs = []
        for i in range(1, nrun + 1):
            if g["order_ids"] is None:
                r = ctx.det(f"{slug}.g{gi}.{step}.r{i}", g["files"], flags)
            else:
                r = ctx.det(f"{slug}.g{gi}.{step}.r{i}", None, flags, g["order_ids"])
            ok, why = valid_ladder_run(step, disabled or {"timers"}, r) if step != "L1" else valid_ladder_run(step, set(), r)
            r["valid"], r["valid_why"] = ok, why
            runs.append(r)
        for cid, c in list(pending.items()):
            use = runs if mixed_outcome(c) else runs[:2]
            st, cleared = step_states(c, use)
            rec = res["cases"][cid].setdefault("ladder", {})
            rec[step] = {"states": st, "runs": [{"tag": r["tag"], "cmd": r["cmd"], "exit": r["exit"], "valid": r["valid"],
                                                  "valid_why": r["valid_why"], "outcome": r["outcomes"].get(cid),
                                                  "failure": r["exc"].get(cid), "meta": r["meta"]} for r in use]}
            if cleared:
                res["cases"][cid]["clears_at"] = step
                del pending[cid]
    for cid in pending:
        lad = res["cases"][cid].get("ladder", {})
        l7 = lad.get("L7", {}).get("states", [])
        if l7 and all(s == "repro" for s in l7):
            res["cases"][cid]["clears_at"] = "wrapper"


def plain_repro(ctx, res, slug, gi, g):
    files = g["files"]
    # control: identical plain command, harness config, Vitest's default order
    ctl = [ctx.plain(f"{slug}.g{gi}.control.r{i}", files) for i in (1, 2, 3)]
    for c in g["cases"]:
        cid = c["id"]
        ps = [plain_state(c["kind"], r["outcomes"].get(cid)) for r in ctl]
        res["cases"][cid]["control"] = {"states": ps, "runs": [{"tag": r["tag"], "cmd": r["cmd"], "exit": r["exit"],
                                        "outcome": r["outcomes"].get(cid), "failure": r["exc"].get(cid),
                                        "applied": r["applied"]} for r in ctl]}
    order_cond = g["set"] != "alone" or any(res["cases"][c["id"]].get("clears_at") == "L6" for c in g["cases"])
    net_cond = [c["id"] for c in g["cases"] if net_trigger(res["cases"][c["id"]])]
    if order_cond and g["order_ids"] is not None:
        want = file_order(g["order_ids"])
        cond = [ctx.plain(f"{slug}.g{gi}.order.r{i}", files, order=[split_file(f)[0] for f in want]) for i in (1, 2, 3)]
        for c in g["cases"]:
            cid = c["id"]
            res["cases"][cid]["condition"] = {"kind": "order", "states": [
                plain_state(c["kind"], r["outcomes"].get(cid)) if r["applied"] == r["intended"] else "invalid" for r in cond],
                "runs": [{"tag": r["tag"], "cmd": r["cmd"], "exit": r["exit"], "outcome": r["outcomes"].get(cid),
                          "failure": r["exc"].get(cid), "applied": r["applied"], "intended": r["intended"]} for r in cond]}
    elif order_cond:  # alone set, cause order (L6): the file's own test order is the engine's; no plain file order
        for c in g["cases"]:
            res["cases"][c["id"]].setdefault("condition", {"kind": "order", "not_forced": "single file: no file order to replay"})
    for cid in net_cond:
        c = next(x for x in g["cases"] if x["id"] == cid)
        runs = []
        for i in (1, 2, 3):
            r = ctx.plain(f"{slug}.g{gi}.net.r{i}", files, prefix=NET_PREFIX)
            runs.append(r)
        res["cases"][cid]["condition"] = {"kind": "network", "states": [plain_state(c["kind"], r["outcomes"].get(cid)) for r in runs],
                                          "runs": [{"tag": r["tag"], "cmd": r["cmd"], "exit": r["exit"],
                                                    "outcome": r["outcomes"].get(cid), "failure": r["exc"].get(cid)} for r in runs]}
    # control 3/3 differs on the smallest set: whole-suite default order vs forced --det order (spec B3)
    for c in g["cases"]:
        ps = res["cases"][c["id"]]["control"]["states"]
        if all(s == "det" for s in ps):
            whole_suite_order(ctx, res, slug, c, g)


def whole_suite_order(ctx, res, slug, c, g):
    cid = c["id"]
    key = f"{slug}.ws"
    src = g.get("src", 0)
    want = [split_file(f)[0] for f in file_order(ctx.det_orders[src])]
    dflt = [ctx.plain(f"{key}.default.r{i}", None) for i in (1, 2, 3)]
    forced = [ctx.plain(f"{key}.forced.r{i}", None, order=want) for i in (1, 2, 3)]
    res["cases"][cid]["whole_suite_order"] = {
        "default": {"states": [plain_state(c["kind"], r["outcomes"].get(cid)) for r in dflt],
                    "runs": [{"tag": r["tag"], "cmd": r["cmd"], "exit": r["exit"], "outcome": r["outcomes"].get(cid),
                              "failure": r["exc"].get(cid)} for r in dflt]},
        "forced": {"states": [plain_state(c["kind"], r["outcomes"].get(cid)) if r["applied"] == r["intended"] else "invalid"
                              for r in forced],
                   "runs": [{"tag": r["tag"], "cmd": r["cmd"], "exit": r["exit"], "outcome": r["outcomes"].get(cid),
                             "failure": r["exc"].get(cid), "applied_ok": r["applied"] == r["intended"]} for r in forced]}}


def net_trigger(case):
    lines = [x or "" for x in case.get("det_failure") or []]
    if any("NetworkBlockedError" in x for x in lines):
        return True
    for step in (case.get("ladder") or {}).values():
        for r in step["runs"]:
            if (r.get("meta") or {}).get("network") in ("block", "replay"):
                return True
    return False


def neutral(o):
    """Gate rev 5 note 1: the harness config, default order, whole suite: per-id outcomes must equal plain run 1 of A.
    `neutral_strict` is that rule; `neutral` (used by classify.py) leaves out the ids whose outcome differs between
    plain runs 1 and 2 of A themselves (interpretation sent to the coordinator at the end of A). --reuse: recompute
    from the recorded run instead of running again."""
    ctx = Ctx(o)
    if o.reuse:
        d = os.path.join(ctx.work, "runs")
        row = [json.loads(x) for x in open(os.path.join(ctx.work, "runs.jsonl")) if '"neutral.default"' in x][-1]
        r = {"cmd": row["cmd"], "exit": row["exit"], "wall_s": row["wall_s"],
             "outcomes": {k: norm(v) for k, v in measure.runner_outcomes(f"{d}/neutral.default.runner.json", ctx.cwd).items()},
             "applied": open(f"{d}/neutral.default.applied.txt").read().split()}
    else:
        r = ctx.plain("neutral.default", None)
    base = {k: norm(v) for k, v in measure.runner_outcomes(f"{ctx.find}/plain1.runner.json", ctx.cwd).items()}
    diff = sorted(k for k in set(base) | set(r["outcomes"]) if base.get(k) != r["outcomes"].get(k))
    base2 = {k: norm(v) for k, v in measure.runner_outcomes(f"{ctx.find}/plain2.runner.json", ctx.cwd).items()}
    # ids whose outcome already differs between plain runs 1 and 2 of A (plain flaky, or an unstable id missing from
    # one of them) cannot tell a neutral config from a non-neutral one: listed, and the second verdict leaves them out
    variable = {k for k in set(base) | set(base2) if base.get(k) != base2.get(k)}
    # an unstable id (its name embeds a pid or a wall-clock date) gets a new name in every run: one whose
    # digits-to-# shape is that of a plain-variable id counts as plain-variable too
    vshape = {shape(k) for k in variable if shape(k) != k}
    rest = [k for k in diff if k not in variable and shape(k) not in vshape]
    out = {"repo": ctx.repo, "cmd": r["cmd"], "exit": r["exit"], "wall_s": r["wall_s"], "n_plain1": len(base),
           "n_harness": len(r["outcomes"]), "n_differ": len(diff), "differ": [[k, base.get(k), r["outcomes"].get(k)] for k in diff],
           "applied_n": len(r["applied"] or []), "neutral_strict": not diff,
           "n_differ_outside_plain_variable": len(rest), "neutral_outside_plain_variable": not rest,
           "neutral": not rest}
    os.makedirs(os.path.join(DATA, ctx.repo), exist_ok=True)
    with open(os.path.join(DATA, ctx.repo, "neutral.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "differ"}))


def files_cmd(o):
    ctx = Ctx(o)
    fs = sorted({file_of(c["id"]) for c in ctx.cases})
    print("\n".join(fs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["file", "neutral", "files"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--find", default="/tmp/pm-p3/find")
    ap.add_argument("--file")
    ap.add_argument("--reuse", action="store_true")
    o = ap.parse_args()
    {"file": do_file, "neutral": neutral, "files": files_cmd}[o.phase](o)


if __name__ == "__main__":
    main()
