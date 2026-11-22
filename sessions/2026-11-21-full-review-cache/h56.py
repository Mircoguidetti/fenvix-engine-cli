"""R-056 attack harness. A scenario: files v1 -> cold cached run -> change (files v2 and/or a run-time context) ->
warm cached run. The warm cached outcomes are compared with an uncached `pytest --det` under the same arguments and
context (the verdict) and with plain pytest. Modes: serial, -n 2, -n 1 (both files on one worker)."""
import os, shutil, subprocess, sys, tempfile, pathlib, json, concurrent.futures as cf

PY = os.environ.get("R056_PY", sys.executable)
MODES = {"serial": (), "n2": ("-n", "2"), "n1": ("-n", "1")}
INI = {"pytest.ini": "[pytest]\npythonpath = .\n"}

def write(root, files):
    for rel, text in files.items():
        p = root / rel
        if text is None:
            if p.is_dir(): shutil.rmtree(p)
            else: p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

def run(root, args, ctx):
    for f in ctx.get("clean", ("flag.txt",)):
        (root / f).unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    env.update(ctx.get("env", {}))
    for k in ctx.get("unset", ()):
        env.pop(k, None)
    cwd = root / ctx.get("cwd", ".")
    target = [str(root / t) for t in ctx.get("targets", ["tests"])]
    cmd = [*ctx.get("prefix", ()), PY, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly",
           *args, *ctx.get("args", ()), *target]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ", "SKIPPED ", "XFAIL ", "XPASS ")):
            parts = line.split()
            nid = parts[1]
            out[nid.split(str(root) + "/")[-1]] = parts[0].lower()
    summ = [l.strip() for l in p.stdout.splitlines() if l.startswith(("reused ", "plan "))]
    return p.returncode, out, summ, p.stdout + p.stderr

def scenario(name, v1, v2=None, mode="serial", ctx1=None, ctx2=None, between=None, quiet=False):
    """ctx1: context of the cold run; ctx2: of the warm run and the comparisons (env, prefix, cwd, unset, args)."""
    ctx1 = ctx1 or {}
    ctx2 = ctx2 if ctx2 is not None else ctx1
    par = MODES[mode]
    root = pathlib.Path(tempfile.mkdtemp(prefix="r056-"))
    try:
        write(root, {**INI, **v1})
        cache = f"--det-cache={root / '.c'}"
        rc1, o1, s1, out1 = run(root, ("--det", cache, *par), ctx1)
        if between: between(root)
        if v2: write(root, v2)
        rc2, o2, s2, out2 = run(root, ("--det", cache, *par), ctx2)
        drc, do, _, dout = run(root, ("--det", *par), ctx2)
        prc, po, _, _ = run(root, par, ctx2)
        ok = o2 == do and (rc2 != 0) == (drc != 0)
        res = dict(name=name, mode=mode, ok=ok, run1=o1, rc1=rc1, s1=s1, run2=o2, rc2=rc2, s2=s2, det=do, drc=drc,
                   plain=po, prc=prc, tail=out2[-2500:] if not ok else "", out1tail=out1[-1500:] if not ok else "")
        return res
    finally:
        shutil.rmtree(root, ignore_errors=True)

def show(r):
    print(f"{'OK   ' if r['ok'] else 'WRONG'} {r['name']} [{r['mode']}] (vs plain: {'same' if r['run2'] == r['plain'] else 'DIFFERS'})\n"
          f"  run1 cache={r['run1']} rc={r['rc1']} {r['s1']}\n  run2 cache={r['run2']} rc={r['rc2']} {r['s2']}\n"
          f"  --det     ={r['det']} rc={r['drc']}\n  plain     ={r['plain']} rc={r['prc']}", flush=True)
    if not r["ok"] and os.environ.get("R056_TAIL"):
        print("  ---- run2 tail ----\n" + r["tail"])

def run_all(scens, workers=6):
    """scens: list of kwargs dicts for scenario()."""
    with cf.ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda k: scenario(**k), scens))
    for r in res:
        show(r)
    bad = [r["name"] + "[" + r["mode"] + "]" for r in res if not r["ok"]]
    print(f"== {len(res) - len(bad)} OK, {len(bad)} WRONG: {bad}")
    return res
