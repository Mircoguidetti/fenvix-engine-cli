"""Item 9: which ingredient of the baseline makes these tests fail 10/10 (and --det pass)?"""
from pathlib import Path
import json, os, sys, csv
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import detpy_harness as H

W = Path(sys.argv[0]).resolve().parent / "i9-work"
wheel = str(next((Path(os.environ["DETPY_WHEEL_DIR"])).glob("*.whl")))
cfg = json.loads((H.HERE / "repos.json").read_text())
flaky, popular = H.load_pools(cfg)
by = {r["name"]: r for r in flaky + popular}
targets = {}
def parse(x): return dict((k, int(v)) for k, v in (kv.split("=") for kv in x.split(";") if "=" in kv))
for f in sorted((H.HERE / "results/mixed-after-fixes").glob("*.csv")):
    if f.name.endswith(("_runs.csv", "causes.csv")) or f.name == "summary.csv":
        continue
    rows = list(csv.DictReader(open(f)))
    if not rows or "det_outcomes" not in rows[0]:
        continue
    for r in rows:
        b, d = parse(r["baseline_outcomes"]), parse(r["det_outcomes"])
        if b.get("passed", 0) == 0 and any(k.startswith(("failed", "error")) for k in b) and d.get("passed", 0) >= 10 and len(d) == 1:
            targets.setdefault(f.stem, []).append(r["nodeid"])
VARIANTS = {
    "baseline(randomly seed, xdist)": lambda p, i: [f"--randomly-seed={1000+i}"] + (["-n", "2"] if p.xdist else []),
    "randomly seed, serial": lambda p, i: [f"--randomly-seed={1000+i}"] + (["-n", "0"] if p.has_xdist else []),
    "file order + randomly reseed, serial": lambda p, i: ["--randomly-dont-reorganize", f"--randomly-seed={1000+i}"] + (["-n", "0"] if p.has_xdist else []),
    "file order, no reseed, xdist": lambda p, i: ["--randomly-dont-reorganize", "--randomly-dont-reset-seed"] + (["-n", "2"] if p.xdist else []),
    "file order, no reseed, serial": lambda p, i: ["--randomly-dont-reorganize", "--randomly-dont-reset-seed"] + (["-n", "0"] if p.has_xdist else []),
    "--det": lambda p, i: ["--det"] + (["-n", "0"] if p.has_xdist else []),
}
only = sys.argv[1:] or list(targets)
out = {}
for name in only:
    p = H.prepare(by[name], W / "work", wheel, "3.13", 100000)
    print(name, p.status, p.python_version, p.xdist, p.detail[-200:], flush=True)
    if p.status != "ok":
        out[name] = {"status": p.status}
        continue
    res = {}
    for label, fn in VARIANTS.items():
        counts = {nid: {} for nid in targets[name]}
        for i in range(3):
            j = W / f"{name}-{abs(hash(label))}-{i}.json"
            cmd = [p.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--det-outcomes={j}", *p.pytest_args, *fn(p, i)]
            H.sh(cmd, cwd=p.src, env=H.clean_env(p.python, p.env), timeout=1800)
            try:
                oc = json.loads(j.read_text())["outcomes"]
                exc = json.loads(j.read_text()).get("exceptions", {})
            except Exception:
                oc, exc = {}, {}
            for nid in targets[name]:
                o = oc.get(nid, "missing")
                counts[nid][o] = counts[nid].get(o, 0) + 1
                if o != "passed" and nid in exc:
                    counts[nid]["exc"] = str(exc[nid])[:300]
        res[label] = counts
        print(name, label, {k[-50:]: v for k, v in counts.items()}, flush=True)
    out[name] = res
    (W / "result.json").write_text(json.dumps(out, indent=1))
