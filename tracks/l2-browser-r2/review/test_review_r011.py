#!/usr/bin/env python3
"""Review R-011 (L2 browser, round 2): defects of the measurement, as tests.

Each test FAILS on the delivered commit (claude/l2-browser-r2 @ 786181b) and passes once fixed.
Run from the repository root:  python3 -m unittest tracks/l2-browser-r2/review/test_review_r011.py -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACK = HERE.parent
RESULTS = TRACK / "results"
AGGREGATE = TRACK / "harness" / "aggregate.py"
FAIL = ("failed", "timedOut")


def aggregate_totals(results_dir):
    out = subprocess.run([sys.executable, str(AGGREGATE), str(results_dir)], capture_output=True, text=True, check=True).stdout
    line = next(l for l in out.splitlines() if l.startswith("totals: "))
    return json.loads(line[len("totals: "):]), out


def load(name):
    return json.loads((RESULTS / f"{name}.json").read_text())


def target_key(t):
    return t.get("matched_key") or t.get("key")


def control_induced(t, broken_keys):
    """A target whose --det failures are ours: listed as broken by the controls, or it passes in every plain run of the
    same filter while every default-seed --det replay fails."""
    plain = t.get("plain_runs") or ""
    reps = t.get("replays") or []
    return target_key(t) in broken_keys or (plain and set(plain) == {"P"} and reps and all(o in FAIL for o in reps))


def synthetic_project(tmp):
    """One target the controls break deterministically: passes in every plain/baseline run, fails in every --det
    replay, every seed and every failing-seed replay, always with one fingerprint."""
    key = "spec.ts::broken by detjs [chromium]"
    one = {"status": "stable", "distinct_fingerprints": 1}
    r = {
        "name": "synthetic", "status": "ok", "tests_baseline": 1,
        "baseline_wall_median_s": 10, "serial_wall_median_s": 10, "det_wall_median_s": 20,
        "det_verify": {"tests": 1, "stable": 1}, "det_fingerprints": {key: ["stable", 1, "FF"]},
        "broken_by_controls": [{"key": key, "det": "FF", "always": True}],
        "runs": [{"label": f"baseline-{i}", "outcomes": {key: "passed"}} for i in (1, 2, 3)]
                + [{"label": f"det-{i}", "outcomes": {key: "failed"}} for i in (1, 2)],
        "targets": [{"key": key, "matched_key": key, "known": True, "plain_runs": "PPP",
                     "replays": ["failed"] * 10, "replay_verify": one,
                     "seeds": {str(s): "failed" for s in range(1, 9)}, "failing_seed": 1,
                     "failing_seed_replays": ["failed"] * 10, "failing_seed_verify": one,
                     "replay_cmd": "npx detjs playwright --det --det-seed=1 test spec.ts:1",
                     "replay_cmd_outcome": "failed", "replay_cmd_verify": one}],
        "flaky": [], "ablation": [],
    }
    (Path(tmp) / "synthetic.json").write_text(json.dumps(r))


class ExitMetric(unittest.TestCase):
    def test_h1_control_broken_target_is_not_a_reproduced_flake(self):
        """The exit number counts 'replays 10/10 with one fingerprint AND fails in some seed'. A test the controls
        break deterministically satisfies both; aggregate.py counts it as a reproduced flake. The next design's
        number would be inflated by exactly the tests we break."""
        with tempfile.TemporaryDirectory() as tmp:
            synthetic_project(tmp)
            tot, _ = aggregate_totals(tmp)
        self.assertEqual(tot["identical"] + tot["fail_seed_repro"] + tot["replay_cmd_ok"], 0,
                         f"a target broken by the controls counted toward the exit number: {tot}")

    def test_h2_fail_in_some_seed_excludes_failures_we_cause(self):
        """REPORT.md: '3 of 15 fail in at least one of seeds 1-8'. All 3 are failures caused by the controls (plain
        runs of the same filter PPP; uptime-kuma's two are in broken_by_controls; actual's times out in 10 of 10
        default-seed replays). None is a flake found by a seed."""
        tot, _ = aggregate_totals(RESULTS)
        ours, real = [], 0
        for f in sorted(RESULTS.glob("*.json")):
            r = json.loads(f.read_text())
            broken = {b["key"] for b in r.get("broken_by_controls") or []}
            for t in r.get("targets") or []:
                outs = list(t.get("replays") or []) + list((t.get("seeds") or {}).values())
                if not any(o in FAIL for o in outs):
                    continue
                if control_induced(t, broken):
                    ours.append(f"{r['name']}: {target_key(t)[:70]} (plain {t.get('plain_runs')}, replays "
                                f"{''.join(o[0] for o in t.get('replays') or [])})")
                else:
                    real += 1
        self.assertEqual(tot["fail_seed"], real, "aggregate.py 'fail in some seed' counts failures caused by the "
                         "controls:\n" + "\n".join(ours))


class ReplayCommand(unittest.TestCase):
    def test_h3_printed_replay_command_runs_its_test(self):
        """REPORT.md: the printed command 'runs' for the 3 failing seeds. For actual it produced no outcome for its
        test ('missing'); its trace adds no run to the fingerprint set (7 fp before and after)."""
        bad = []
        for f in sorted(RESULTS.glob("*.json")):
            r = json.loads(f.read_text())
            for t in r.get("targets") or []:
                if t.get("replay_cmd") and t.get("replay_cmd_outcome") not in ("passed", "failed", "timedOut"):
                    bad.append(f"{r['name']}: {t['replay_cmd']} -> {t.get('replay_cmd_outcome')}")
        self.assertEqual(bad, [], "printed replay commands that did not run their test:\n" + "\n".join(bad))


class SilentOutcomeChange(unittest.TestCase):
    def test_h4_fail_to_pass_under_det_is_counted(self):
        """broken_by_controls counts only pass -> fail. documenso 'should reject order change on a PENDING envelope'
        fails in 3 of 3 configured runs and passes in both --det runs (and in the --workers=1 run): --det hides a
        failure the developer's CI shows (cause: --det forces --workers=1). It appears in no table and no total."""
        r = load("documenso")
        base = [x for x in r["runs"] if x["label"].startswith("baseline")]
        det = [x for x in r["runs"] if x["label"].startswith("det")]
        masked = sorted(k for k in det[0]["outcomes"]
                        if all(b["outcomes"].get(k) in FAIL for b in base) and all(d["outcomes"].get(k) == "passed" for d in det))
        self.assertEqual(len(masked), 1, masked)  # the data: one such test
        tot, out = aggregate_totals(RESULTS)
        reported = any(k in tot for k in ("masked", "fixed_by_controls", "hidden_by_controls")) or "hidden by" in out.split("totals:")[1]
        self.assertTrue(reported, f"aggregate.py does not report tests that fail without detjs and pass under --det: {masked}")


if __name__ == "__main__":
    unittest.main()
