"""P0 big trace, criterion 5: runner/fenvix-run already fails closed on what a big trace used to cause (no code change).

A stand-in detjs (the stub pattern of tests/test_runner_node.py) drives the two guard branches:

* detjs exits 0 with outcomes but a trace header WITHOUT `meta.status` (what detjs wrote for a 1.2 GB trace it could
  not read back): the job exits 1 (runner/fenvix-run: "detjs returned 0 but wrote no status");
* `detjs verify` killed by the kernel (return code -9, as the 10.3 GB OOM kill of the P0 re-measure): the verify
  summary records `verify_status: null` and `verify_exit: -9`, and the verify job is not green.
"""
from __future__ import annotations

import json

import pytest

from test_runner_node import job

STUB = r"""#!/usr/bin/env python3
# A stand-in detjs for tests/test_runner_node_p0.py. Behaviour from $STUB_MODE.
import json, os, signal, sys
a = sys.argv[1:]
if a[:1] == ["--version"]:
    print("fenvix 0.0.0-stub"); sys.exit(0)
mode = os.environ.get("STUB_MODE", "")
if a[:1] == ["verify"]:
    if mode == "verify-killed":
        os.kill(os.getpid(), signal.SIGKILL)
    print(json.dumps({"status": "identical", "summary": {"tests": 1, "identical": 1}, "tests": []})); sys.exit(0)
opt = {x.split("=", 1)[0]: x.split("=", 1)[1] for x in a if x.startswith("--det-") and "=" in x}
json.dump({"order": ["a.test.js::t"], "outcomes": {"a.test.js::t": "passed"}}, open(opt["--det-outcomes"], "w"))
# a sensor and the controls it rests on, as every real header declares them (node/src/session.js provableField;
# fenvix-run engine_signals and sensor_refusal: a sensor without contract, audited runtime or its controls is refused)
meta = {"epoch_ns": "1795392000000000000",
        "provable": {"sensor": "node-surface/1", "contract": 1, "runtime": "node22", "surface": "stub"},
        "controls": ["fs", "isolation", "net", "order", "seeds", "time", "timers"]}
if mode != "no-status":
    meta["status"] = {"failed": 0, "not_proven": 0, "passed": 1, "skipped": 0}
with open(opt["--det-trace"], "w") as fh:
    fh.write(json.dumps({"type": "header", "meta": meta}) + "\n")
sys.exit(0)
"""


@pytest.fixture
def stub(tmp_path):
    p = tmp_path / "detjs-stub"
    p.write_text(STUB)
    p.chmod(0o755)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "5.1.0"}}))
    return (str(p), {}), proj


def test_detjs_exit_0_with_a_header_without_status_is_red(stub, tmp_path):
    """protects=a job whose detjs exited 0 but left no meta.status in the trace header is red (exit 1);
    fails_when=the runner trusts detjs's 0 (the agentic-qe false green reaching the customer's CI);
    no_claim=the case where detjs itself exits non-zero (the code is forwarded)."""
    detjs, proj = stub
    code, s, md, log = job(tmp_path, proj, "ok", detjs, "--no-rerun")
    assert code == 0, f"control: with a status the job is green\n{log}"
    code, s, md, log = job(tmp_path, proj, "j", detjs, "--no-rerun", env={"STUB_MODE": "no-status"})
    assert code == 1, log
    assert s["exit"] == 1
    assert "wrote no status in" in log, log


def test_verify_killed_with_minus_9_is_recorded_and_not_green(stub, tmp_path):
    """protects=a `detjs verify` killed by SIGKILL is recorded as verify_status null, verify_exit -9, and the verify
    job is not green; fails_when=the kill is read as a verdict or as exit 0; no_claim=why it was killed (memory:
    harness/p0_big_trace/REPORT.md measures the bounded verifier)."""
    detjs, proj = stub
    code, s, md, log = job(tmp_path, proj, "j", detjs, "--no-rerun")
    assert code == 0, log
    summary = tmp_path / "j" / "summary.json"
    code, v, md, log = job(tmp_path, proj, "v", detjs, "verify", "--summary", str(summary),
                           env={"STUB_MODE": "verify-killed"})
    assert code != 0, log
    assert v["verify_status"] is None and v["exit"] == -9, v
    s = json.loads(summary.read_text())
    assert s["verify_status"] is None and s["verify_exit"] == -9, s
