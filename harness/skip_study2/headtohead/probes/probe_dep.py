"""Probe dependency-version changes: base venv (latest, as the walker installs) vs copies with pins.
CANDS='{"pytest84": ["pytest==8.4.2"], ...}' python3 probe_dep.py <lib>"""
import fnmatch, json, os, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
H = Path("/home/user/fenvix-engine-cli/harness/skip_study2/headtohead")
name = sys.argv[1]
spec = json.loads((H / "specs" / f"{name}.json").read_text())
w = Path("/tmp/claude-0/cand/w") / name
src, venv = w / "src", w / "venv"
w.mkdir(parents=True, exist_ok=True)
if not src.exists():
    subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", spec["url"], str(src)], check=True)
sha = spec["seq"]["commits"][int(os.environ.get("IDX", "0"))]
subprocess.run(["git", "checkout", "-q", "--force", sha], cwd=src, check=True)
if not (venv / "bin" / "python").exists():
    subprocess.run(["uv", "venv", "-q", "--python", "3.13", str(venv)], check=True)
    extra = []
    for c in spec["install"]:
        if "--extra" in c:
            extra = c.split("--extra", 1)[1].split()
    r = subprocess.run([sys.executable, str(H / "libinstall.py"), "--py", str(venv / "bin/python"), "--src", str(src)] + sum((["--extra", x] for x in extra), []), capture_output=True, text=True)
    print(r.stdout[-300:], r.stderr[-300:])
cands = json.loads(os.environ["CANDS"])
venvs = {"base": venv}
for k, pins in cands.items():
    v = w / f"venv-{k}"
    shutil.rmtree(v, ignore_errors=True)
    shutil.copytree(venv, v, symlinks=True)
    r = subprocess.run(["uv", "pip", "install", "-q", "--python", str(v / "bin/python")] + pins, capture_output=True, text=True)
    print(k, pins, r.returncode, r.stderr[-400:])
    venvs[k] = v
files = subprocess.run(["git", "ls-files"], cwd=src, capture_output=True, text=True).stdout.splitlines()
u = spec["units"]
units = sorted(f for f in files if any(fnmatch.fnmatch(f, p) for p in u["include"]) and not any(fnmatch.fnmatch(f, p) for p in u.get("exclude", [])))
units = [x for x in units if any(fnmatch.fnmatch(x.rsplit("/",1)[-1], p.rsplit("/",1)[-1]) for p in u["include"])]
units += [x for x in spec.get("dir_units", [])]
base = dict(os.environ)
for k in list(base):
    if k.startswith(("PYTEST_", "VIRTUAL_ENV")): base.pop(k)
def run(k, unit):
    v = venvs[k]
    e = dict(base, VIRTUAL_ENV=str(v), PATH=f"{v}/bin:" + base["PATH"], PYTHONHASHSEED="0", CI="true")
    p = subprocess.run([str(v / "bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--tb=line", "--color=no", unit],
                       cwd=src, env=e, capture_output=True, text=True, timeout=900)
    return k, unit, p.returncode, p.stdout.strip().splitlines()[-1:]
res = {}
with ThreadPoolExecutor(int(os.environ.get("J", "4"))) as ex:
    for k, x, code, tail in ex.map(lambda a: run(*a), [(k, x) for k in venvs for x in units]):
        res.setdefault(k, {})[x] = [code, tail]
good = lambda c: c in (0, 5)
b = res["base"]
print(name, sha[:10], "units", len(units), "base bad:", [x for x, v in b.items() if not good(v[0])])
for k in cands:
    up = [x for x in units if good(res[k][x][0]) and not good(b[x][0])]
    down = [x for x in units if not good(res[k][x][0]) and good(b[x][0])]
    print(f"  {k}: good->bad vs base {len(down)} {down[:8]} | bad->good {len(up)} {up[:8]}", [res[k][x][1] for x in down[:2]])
(w / f"probe-dep.json").write_text(json.dumps(res, indent=1))
