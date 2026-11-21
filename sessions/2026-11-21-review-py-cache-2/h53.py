"""R-053 attack harness: run 1 cold cache, change, run 2 warm cache; compare with plain pytest and uncached --det,
same parallel arguments. Files a test writes (flag.txt) are removed before every run, as in a fresh checkout."""
import os, shutil, subprocess, sys, tempfile, pathlib

PY = sys.executable

def write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

def clean(root):
    (root / "flag.txt").unlink(missing_ok=True)

def run(root, *args):
    clean(root)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    p = subprocess.run([PY, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly", *args, "tests"],
                       cwd=root, capture_output=True, text=True, env=env, timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    summ = [l.strip() for l in p.stdout.splitlines() if l.startswith(("reused ", "plan "))]
    return p.returncode, out, summ, p.stdout

def scenario(name, v1, v2, par=()):
    root = pathlib.Path(tempfile.mkdtemp(prefix="r053-"))
    write(root, {"pytest.ini": "[pytest]\npythonpath = .\n", **v1})
    cache = f"--det-cache={root / '.c'}"
    rc1, o1, s1, _ = run(root, "--det", cache, *par)
    run(root, *par)  # the developer's plain run in between
    write(root, v2)
    rc2, o2, s2, out2 = run(root, "--det", cache, *par)
    prc, po, _, _ = run(root, *par)
    drc, do, _, _ = run(root, "--det", *par)
    ok = o2 == do and (rc2 != 0) == (drc != 0)
    plain_eq = o2 == po
    print(f"{'OK   ' if ok else 'WRONG'} {name} (vs plain: {'same' if plain_eq else 'DIFFERS'}) [{' '.join(par) or 'serial'}]\n  run1 cache={o1} rc={rc1}\n"
          f"  run2 cache={o2} rc={rc2} {s2}\n  run2 plain={po} rc={prc}\n  run2 --det={do} rc={drc}", flush=True)
    if not ok:
        print("  ---- run2 cache tail ----\n" + "\n".join(out2.splitlines()[-30:]))
    shutil.rmtree(root, ignore_errors=True)
    return ok

def scenario2(name, v1, v2, par1=(), par2=()):
    """Run 1 with par1 (cold), change, run 2 with par2 (warm); compare with plain and --det under par2."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="r053-"))
    write(root, {"pytest.ini": "[pytest]\npythonpath = .\n", **v1})
    cache = f"--det-cache={root / '.c'}"
    rc1, o1, s1, _ = run(root, "--det", cache, *par1)
    write(root, v2)
    rc2, o2, s2, out2 = run(root, "--det", cache, *par2)
    prc, po, _, _ = run(root, *[a for a in par2 if not a.startswith("--det")])
    drc, do, _, _ = run(root, "--det", *par2)
    ok = o2 == do and (rc2 != 0) == (drc != 0)
    print(f"{'OK   ' if ok else 'WRONG'} {name} (vs plain: {'same' if o2 == po else 'DIFFERS'}) "
          f"[{' '.join(par1) or 'serial'} -> {' '.join(par2) or 'serial'}]\n  run1 cache={o1} rc={rc1} {s1}\n"
          f"  run2 cache={o2} rc={rc2} {s2}\n  run2 plain={po} rc={prc}\n  run2 --det={do} rc={drc}", flush=True)
    if not ok:
        print("  ---- run2 cache tail ----\n" + "\n".join(out2.splitlines()[-30:]))
    shutil.rmtree(root, ignore_errors=True)
    return ok
