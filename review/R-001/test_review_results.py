"""R-001 review: failing checks of the delivered result files (fenvix-engine-cli 0aef0ae).

Run from the repository root: pytest <this file> (needs only the files under harness/results/).
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if (Path(__file__).resolve().parents[1] / "harness").exists() \
    else Path("/home/user/fenvix-engine-cli/.claude/worktrees/agent-af0a85a6ecb497a41")
RES = ROOT / "harness" / "results"


def test_timing_report_names_every_runner_cpu():
    """Why it matters: the report states one runner CPU for the whole quiet timing pass (write_report
    takes timings[0]["runner"]); the raw files show 4 different CPU models (AMD EPYC 9V74, 9V45,
    7763, Intel Xeon 8573C). Per-repository ratios are still same-runner, but the hardware statement
    in the founder-facing report is wrong."""
    cpus = {json.loads(p.read_text())["runner"].get("cpu_model")
            for p in (RES / "timing-after-fixes").glob("*.timing.json")}
    assert len(cpus) > 1
    for report in (RES / "mixed-after-fixes" / "REPORT.md", RES / "timing-after-fixes" / "REPORT.md"):
        timing = report.read_text().split("## Timing", 1)[1].split("\n## ", 1)[0]
        missing = sorted(c for c in cpus if c not in timing)
        assert not missing, f"{report.relative_to(ROOT)} omits runner CPUs {missing}"


def test_p005_same_mechanism_same_class():
    """Why it matters: P-005 classes decide the Block 1 outcome tree. In panamah-sdk-python the three
    tests test_expiration_by_max_{length,size,age} are one-line calls of the same helper
    test_expiration(), which works in the relative directory ./.panamah that setUp() deletes with
    shutil.rmtree: under the xdist baseline the two workers share that directory (cross-process
    filesystem state, never present in a serial --det run). The classifier gives them three
    different classes (d, b, c); the 'c' one is counted as an L0 gap ("our bug")."""
    rows = {r["nodeid"].rsplit("::", 1)[-1]: r["class"]
            for r in csv.DictReader(open(RES / "mixed-after-fixes" / "not-reproduced-causes.csv"))
            if r["repo"] == "idoft-panamah-sdk-python" and "test_expiration_by_" in r["nodeid"]}
    assert len(rows) == 3
    assert len(set(rows.values())) == 1, rows
    assert "c" not in rows.values(), rows
