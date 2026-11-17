"""Probe: per library, install at a spec commit, run each test file (unit) plainly under candidate CI changes;
report units whose verdict flips from good to bad."""
import fnmatch, json, os, subprocess, sys
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
py = venv / "bin" / "python"
if not py.exists():
    subprocess.run(["uv", "venv", "-q", "--python", "3.13", str(venv)], check=True)
    r = subprocess.run([sys.executable, str(H / "libinstall.py"), "--py", str(py), "--src", str(src)], capture_output=True, text=True)
    print(r.stdout[-300:], r.stderr[-300:])
files = subprocess.run(["git", "ls-files"], cwd=src, capture_output=True, text=True).stdout.splitlines()
u = spec["units"]
units = sorted(f for f in files if any(fnmatch.fnmatch(f, p) for p in u["include"]) and not any(fnmatch.fnmatch(f, p) for p in u.get("exclude", [])))
units = [x for x in units if any(fnmatch.fnmatch(x.rsplit("/",1)[-1], p.rsplit("/",1)[-1]) for p in u["include"])]
units += [x for x in spec.get("dir_units", [])]
units = [x for x in units if x != "tests/test_serving.py"]
base = dict(os.environ)
for k in list(base):
    if k.startswith(("PYTEST_", "VIRTUAL_ENV")): base.pop(k)
base.update(VIRTUAL_ENV=str(venv), PATH=f"{venv}/bin:" + base["PATH"], PYTHONHASHSEED="0", CI="true")
cands = json.loads(os.environ.get("CANDS", "null")) or {"base": {}, "FORCE_COLOR": {"FORCE_COLOR": "1"}, "NO_COLOR": {"NO_COLOR": "1"},
         "WARN_ERR": {"PYTHONWARNINGS": "error"}, "TZ": {"TZ": "Asia/Kolkata"}, "COLUMNS": {"COLUMNS": "40"},
         "TERM": {"TERM": "dumb"}, "LANG_C": {"LANG": "C", "LC_ALL": "C"}, "WARN_DEP": {"PYTHONWARNINGS": "error::DeprecationWarning"}}
def run(k, unit):
    e = dict(base, **cands[k])
    p = subprocess.run([str(py), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--tb=line", "--color=no", unit],
                       cwd=src, env=e, capture_output=True, text=True, timeout=900)
    return k, unit, p.returncode, p.stdout.strip().splitlines()[-1:] 
jobs = [(k, x) for k in cands for x in units]
res = {}
with ThreadPoolExecutor(4) as ex:
    for k, x, code, tail in ex.map(lambda a: run(*a), jobs):
        res.setdefault(k, {})[x] = [code, tail]
b = res["base"]
print(name, sha[:10], "units", len(units), "base bad:", [x for x, v in b.items() if v[0] not in (0, 5)])
for k in cands:
    if k == "base": continue
    flip = [x for x in units if b[x][0] in (0, 5) and res[k][x][0] not in (0, 5)]
    print(f"  {k}: flips {len(flip)}/{len(units)} {flip[:10]} {[res[k][x][1] for x in flip[:3]]}")
(w / f"probe-{os.environ.get('TAG','env')}.json").write_text(json.dumps(res, indent=1))
