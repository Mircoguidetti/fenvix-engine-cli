"""``manage.py test --parallel N`` under ``--det``: Django's own parallel mode, with a fixed plan (row PY-04,
founder decision 2026-11-21: parallel is the heart of the product).

Django's parallel runner forks workers that take test classes from a shared queue as they free up: which classes
share a process, and in which order, depends on timing. Under ``--det`` the same parallelism is kept with a plan
that does not:

1. **Collect** (this process, the controller): Django builds the suite as for a serial run, the unittest shell
   orders it exactly as the serial ``--det`` run would (Django's groups kept, ``--det-seed`` applied) and gives
   every test its id.
2. **Plan**: Django's unit of parallelism is kept: a test class (its ``setUpClass`` / ``setUpTestData`` run once).
   Classes go to ``N`` lanes, largest first onto the least loaded lane by number of tests (ties: the earlier lane),
   and every lane keeps the serial order. The plan is a pure function of the ordered ids and ``N``: the same in
   every run on the same code (it does not depend on timings).
3. **Run**: one engine process per lane at the same time (``python -m detpy django ... --det --det-order=<lane>``,
   the option ``detpy repro`` replays with), each with its own test database (``_djangodb``: a clean copy of the
   sealed template, named ``..._lane<k>``).
4. **Merge**: the lanes' traces into one (``_core.merge_traces``, as pytest-xdist's workers'), their outcomes into
   one outcomes file; the exit status is Django's (failures and errors). The lanes' output is printed lane by lane.

Refused (serial, said in the summary): ``--det-cache`` (one proof session decides and records: the lanes would be
separate stores), ``--det-order`` / ``--det-record`` (one exact order / one cassette).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from .. import _core, _level0

_DROP_WITH_VALUE = ("--det-trace", "--det-outcomes", "--det-order", "--det-plan", "--parallel")


def refusal(run) -> str | None:
    ns = run.ns
    why = []
    if run.proof is not None:
        why.append("--det-cache (one proof session decides and records)")
    if getattr(ns, "det_order", None):
        why.append("--det-order (one exact order)")
    if getattr(ns, "det_record", False):
        why.append("--det-record (one cassette)")
    return "; ".join(why) or None


def _child_argv(lane: int, order_file: str, trace: str, outcomes: str) -> list[str]:
    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    out: list[str] = [sys.executable]
    i = 1
    while i < len(argv):
        a = argv[i]
        name = a.split("=", 1)[0]
        if name in _DROP_WITH_VALUE:
            if "=" not in a and i + 1 < len(argv):
                nxt = argv[i + 1]
                # --parallel takes an optional value (a number or "auto")
                if name != "--parallel" or nxt == "auto" or nxt.isdigit():
                    i += 1
            i += 1
            continue
        out.append(a)
        i += 1
    # the --det* options are read anywhere on the command line (driver.parse)
    return out + [f"--det-order={order_file}", f"--det-trace={trace}", f"--det-outcomes={outcomes}"]


def plan(units: list[tuple[str, list[str]]], workers: int) -> list[list[str]]:
    """``units``: (unit, ids) in serial order. Returns the lanes' id lists, each in serial order."""
    index = {}
    for u, ids in units:
        for i in ids:
            index[i] = len(index)
    n = max(1, min(workers, len(units)))
    loads = [0] * n
    lanes: list[list[str]] = [[] for _ in range(n)]
    for pos, (_u, ids) in sorted(enumerate(units), key=lambda x: (-len(x[1][1]), x[0])):
        k = min(range(n), key=lambda j: (loads[j], j))
        loads[k] += len(ids)
        lanes[k].extend(ids)
    return [sorted(lane, key=index.__getitem__) for lane in lanes if lane]


def collect(shell, suite) -> list[tuple[str, list[str]]]:
    """The serial run's ordered ids, grouped by Django's unit of parallelism (a test class)."""
    from .unittest_shell import _isnotsuite

    flat: list = []
    opaque: list = []
    shell.flatten(suite, flat, opaque)
    flat = shell.order(flat)
    seen: dict[str, int] = {}
    units: dict[str, list[str]] = {}
    for n, t in enumerate(flat):
        members = [t] if _isnotsuite(t) else list(shell.iter_tests(t))
        for m in members:
            base = shell.base_id(m)
            c = seen.get(base, 0)
            seen[base] = c + 1
            nid = base if c == 0 else f"{base}[{c}]"
            unit = (shell.unit_of(m) or nid) if _isnotsuite(t) else f"suite:{n}"
            units.setdefault(unit, []).append(nid)
    return list(units.items())


def run_lanes(hooks, runner, test_labels, workers: int):
    """Run the suite in lanes; returns Django's failure count, or None when there is nothing to split (the caller
    then runs it serially)."""
    run, shell = hooks.run, hooks.shell
    suite = runner.build_suite(test_labels)
    units = collect(shell, suite)
    lanes = plan(units, workers)
    if len(lanes) < 2:
        return None
    order = [i for _u, ids in units for i in ids]
    d = os.path.join(run.root, ".detpy", "django-lanes")
    os.makedirs(d, exist_ok=True)
    trace = run.trace_path or os.path.join(run.root, ".detpy", "trace.jsonl")
    procs = []
    for k, ids in enumerate(lanes, 1):
        of = os.path.join(d, f"lane{k}.order")
        with open(of, "w") as f:
            f.write("\n".join(ids) + "\n")
        tr = f"{trace}.lane{k}.jsonl"
        oc = os.path.join(d, f"lane{k}.outcomes.json")
        for p in (tr, oc):
            if os.path.exists(p):
                os.remove(p)
        log = tempfile.TemporaryFile()
        env = dict(os.environ, DETPY_DJANGO_LANE=str(k))
        procs.append((k, ids, tr, oc, log, subprocess.Popen(_child_argv(k, of, tr, oc), cwd=os.getcwd(), env=env,
                                                             stdout=log, stderr=subprocess.STDOUT)))
    outcomes: dict = {}
    exceptions: dict = {}
    times: dict = {}
    codes = []
    for k, ids, tr, oc, log, p in procs:
        codes.append(p.wait())
        log.seek(0)
        sys.stdout.flush()
        sys.stderr.write(f"detpy: lane {k}/{len(lanes)}: {len(ids)} tests\n")
        sys.stderr.write(log.read().decode(errors="replace"))
        log.close()
        try:
            with open(oc) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        outcomes.update(data.get("outcomes") or {})
        exceptions.update(data.get("exceptions") or {})
        times.update(data.get("times") or {})
    lists = [ids for ids in lanes]
    digest = _core.sched_plan_digest(lists)
    meta = _lane_meta(procs[0][2]) or _level0.trace_meta(run.status, run.net_mode, len(run.rebound), None,
                                                         run.runner, run.version, (), run.adjustments)
    run.order = order
    run.order_digest = _core.order_digest(order)
    meta["order_digest"] = run.order_digest
    meta["parallel"] = {"runner": "django --parallel", "workers": len(lanes), "plan_digest": digest,
                        "lanes": [len(x) for x in lists], "unit": "test class", "codes": codes}
    workers_ = [(f"lane{k}", tr, ids) for k, ids, tr, _oc, _log, _p in procs]
    summary = json.loads(_core.merge_traces(order, workers_, json.dumps(meta, sort_keys=True), digest, trace))
    for nid, fp, _o, _w in summary["tests"]:
        if fp:
            run.fingerprints[nid] = fp
    missing = [i for i in order if i not in outcomes]
    for nid in missing:  # a lane that died: its tests did not run here, and never pass
        outcomes[nid] = "error"
    run.outcomes.update(outcomes)
    run.exceptions.update(exceptions)
    run.times.update(times)
    run.adjust(f"Django --parallel {workers}: {len(lanes)} lanes with a fixed plan (by test class, "
               f"{'/'.join(str(len(x)) for x in lists)} tests, plan {digest[:12]})"
               + (f"; {len(missing)} tests did not run (a lane exited with {max(codes)})" if missing else ""))
    for k, ids, _tr, _oc, _log, _p in procs:
        failed = [i for i in ids if outcomes.get(i) in ("failed", "error")]
        if failed:
            of = os.path.relpath(os.path.join(d, f"lane{k}.order"), os.getcwd())
            run.adjust(f"lane {k}: {len(failed)} failed (first {failed[0]}); replay that lane alone, same order and "
                       f"process: python -m detpy django <the same command, without --parallel> --det-order={of}")
    bad = sum(1 for o in outcomes.values() if o in ("failed", "error", "xpassed"))
    return bad


def _lane_meta(trace: str) -> dict | None:
    try:
        with open(trace) as f:
            h = json.loads(f.readline())
        return dict(h.get("meta") or {})
    except (OSError, ValueError):
        return None
