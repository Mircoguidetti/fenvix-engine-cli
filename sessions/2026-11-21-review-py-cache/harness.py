"""R-052 attack harness: run a suite plain and under --det-cache (cold, then after a change), serial and -n 2."""
import json, os, shutil, subprocess, sys, tempfile, pathlib

PY = sys.executable
CONF = "import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n"

def write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

def run(root, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    p = subprocess.run([PY, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly", *args, "tests"],
                       cwd=root, capture_output=True, text=True, env=env, timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    summ = [l for l in p.stdout.splitlines() if "reused" in l and "proof" in l]
    return p.returncode, out, (summ[-1].strip() if summ else ""), p.stdout

def scenario(name, v1, v2, par=(), plain_par=None):
    plain_par = par if plain_par is None else plain_par
    """v1: files of run 1 (cold cache); v2: changed files for run 2 (warm). Compare cache vs plain on run 2."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="r052-"))
    write(root, {"pytest.ini": "[pytest]\npythonpath = .\n", **v1})
    cache = f"--det-cache={root / '.c'}"
    rc1, o1, s1, _ = run(root, "--det", cache, *par)
    p1 = run(root, *plain_par)
    write(root, v2)
    rc2, o2, s2, out2 = run(root, "--det", cache, *par)
    prc, po, _, _ = run(root, *plain_par)
    ok = (o2 == po and (rc2 != 0) == (prc != 0))
    tag = "OK   " if ok else "WRONG"
    print(f"{tag} {name} {' '.join(par) or 'serial'}\n  run1 cache={o1} rc={rc1} | plain={p1[1]}\n  run2 cache={o2} rc={rc2} [{s2}]\n  run2 plain={po} rc={prc}")
    if not ok:
        print("  ---- run2 cache tail ----\n" + "\n".join(out2.splitlines()[-25:]))
    shutil.rmtree(root, ignore_errors=True)
    return ok
