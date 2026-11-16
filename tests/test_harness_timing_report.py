"""N5 (review R-001 recheck): the timing report describes every runner (CPU, vCPUs, image), not runner 0."""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "detpy_harness", Path(__file__).resolve().parents[1] / "harness" / "detpy_harness.py")
H = importlib.util.module_from_spec(spec)
sys.modules["detpy_harness"] = H  # dataclasses look the module up by name
spec.loader.exec_module(H)


def _t(name, cpu, cpus, image):
    return {"name": name, "tests": 10, "serial_s": [2.0, 2.0, 2.0], "det_s": [2.2, 2.2, 2.2], "slowdown_pct": 10.0,
            "precompile_s": [1.0, 0.1, 0.1],
            "runner": {"cpu_model": cpu, "cpus": cpus, "ImageOS": "ubuntu26", "ImageVersion": image,
                       "RUNNER_ENVIRONMENT": "github-hosted"}}


def test_every_runner_has_its_own_vcpus_and_image():
    timings = [_t("a", "AMD EPYC 7763", 4, "20261111.1"), _t("b", "Intel Xeon 6975P-C", 2, "20261118.7")]
    text = "\n".join(H.timing_section(timings, {"timing_runs": 3}))
    for cpu, cpus, image in (("AMD EPYC 7763", 4, "20261111.1"), ("Intel Xeon 6975P-C", 2, "20261118.7")):
        assert f"{cpu}, {cpus} vCPU, ubuntu26 {image}" in text
    rows = [line for line in text.splitlines() if line.startswith("| b |")]
    assert "2 vCPU" in rows[0] and "20261118.7" in rows[0]
