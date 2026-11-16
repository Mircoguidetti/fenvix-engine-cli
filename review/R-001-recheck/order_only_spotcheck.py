"""Item 5 spot check: rerun 5 reproduced tests 3x with only the order control (harness prepare/run_pytest)."""
import json, sys, collections
from pathlib import Path
HARNESS = Path(sys.argv[1]); WORK = Path(sys.argv[2]); OUT = Path(sys.argv[3]); names = sys.argv[4:]
sys.path.insert(0, str(HARNESS))
import detpy_harness as h
cfg = json.loads((HARNESS / "repos.json").read_text())
flaky, popular = h.load_pools(cfg)
by_name = {r["name"]: r for r in popular + flaky}
PICKS = {
    "anyio": ("2", "tests/streams/test_tls.py::TestTLSStream::test_send_eof_not_implemented[asyncio-tlsv12]"),
    "idoft-crom": ("9", "tests/test_model.py::TestBaseResource::test_allows_multiple"),
    "idoft-easypy": ("fixed", "tests/test_concurrency.py::test_multiobject_1"),
    "idoft-freezegun": ("7", "tests/test_datetimes.py::test_time_ns"),
    "rich": ("1", "tests/test_box.py::test_get_row"),
}
wheel = str(sorted((WORK / "dist").glob("detpy-*.whl"))[-1])
disable = "seeds,time,fs,net,hashseed,bytecode"
res = json.loads(OUT.read_text()) if OUT.exists() else {}
for name in names:
    config, nid = PICKS[name]
    summ = json.loads((HARNESS / "results/mixed-after-fixes" / f"{name}.summary.json").read_text())
    repo = dict(by_name[name])
    p = h.prepare(repo, WORK, wheel, summ["python"], 900)
    entry = {"status": p.status, "detail": p.detail[-300:], "python": p.python_version, "want_python": summ["python"],
             "commit": p.commit, "want_commit": summ["commit"], "config": config, "nodeid": nid}
    if p.status == "ok":
        rundir = WORK / "spot" / name; rundir.mkdir(parents=True, exist_ok=True)
        seed = None if config == "fixed" else int(config)
        outs = []
        for i in range(3):
            r = h.run_pytest(p, rundir, "seed" if seed is not None else "det", i, 900, seed=seed, disable=disable)
            outs.append(r.outcomes.get(nid, "missing"))
            # control: same config, full L0 (no disable)
        full = h.run_pytest(p, rundir, "seed" if seed is not None else "det", 9, 900, seed=seed)
        entry.update(order_only=outs, full_l0=full.outcomes.get(nid, "missing"))
    res[name] = entry
    OUT.write_text(json.dumps(res, indent=2))
    print(name, json.dumps(entry), flush=True)
