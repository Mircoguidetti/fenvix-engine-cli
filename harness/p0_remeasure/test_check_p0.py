"""Tests of check_p0.py on small synthetic fixtures (results.jsonl, runs.log in measure.py's exact header format,
traces, a plain ids file). Run: pytest harness/p0_remeasure/test_check_p0.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_p0  # noqa: E402

REPO = "demo"
CWD = "/work/demo"
STATUS = "detjs: status: failed={} not_proven={} passed={} skipped={}"


class Fx:
    """One measure.py output directory: OUT/results.jsonl, OUT/demo/runs.log, traces, plain ids."""

    def __init__(self, tmp):
        self.out = str(tmp / "out")
        self.dir = os.path.join(self.out, REPO)
        os.makedirs(self.dir)
        self.results = str(tmp / "p0.jsonl")

    def row(self, **kw):
        r = {"repo": REPO, "cwd": CWD, "engine_commit": "e7338950", "workers": 1, "rep": 1, "wall_s": 1.0, **kw}
        with open(os.path.join(self.out, "results.jsonl"), "a") as f:
            f.write(json.dumps(r) + "\n")
        return r

    def plain(self, tests, rep=1, invalid=None, write_ids=True):
        """tests: [(file, [ancestors], title)] in the plain run."""
        extra = {"invalid": invalid} if invalid else {}
        self.row(kind="plain", rep=rep, cmd=f"npx --no-install vitest run plain{rep}", exit=0, **extra)
        if write_ids:
            with open(os.path.join(self.dir, f"plain{rep}.ids.json"), "w") as f:
                json.dump({"format": "pm-vitest-ids", "tests": [
                    {"file": os.path.join(CWD, fi), "project": "", "ancestors": an, "title": ti, "status": "passed"}
                    for fi, an, ti in tests]}, f)

    def trace(self, name, recs, meta=None):
        """recs: [(nodeid, outcome)] or [(nodeid, outcome, events)]."""
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(json.dumps({"type": "header", "format": "detpy-trace", "version": 1, "meta": meta or {}, "order": []}) + "\n")
            for r in recs:
                j = {"type": "test", "nodeid": r[0], "outcome": r[1]}
                if len(r) > 2:
                    j["events"] = r[2]
                f.write(json.dumps(j) + "\n")

    def run(self, kind="serial", rep=1, workers=1, exit=0, output=(), recs=None, meta=None, trace=True):
        name = f"S{rep}.jsonl" if kind == "serial" else f"P{rep}w{workers}.jsonl"
        cmd = f"node /e/node/bin/detjs.js vitest run --det --det-workers={workers} --det-trace={self.dir}/{name}"
        self.row(kind=kind, rep=rep, workers=workers, exit=exit, cmd=cmd)
        with open(os.path.join(self.dir, "runs.log"), "a") as f:
            f.write(f"\n$ (cd {CWD} && {cmd})  # exit {exit}, 1.00 s\n" + "\n".join(output) + "\n")
        if trace:
            self.trace(name, recs if recs is not None else [("a.test.ts::t1", "passed"), ("a.test.ts::t2", "passed")], meta)

    def check(self, phase="after"):
        check_p0.main([self.out, REPO, "--phase", phase, "--results", self.results])
        with open(self.results) as f:
            return [json.loads(l) for l in f if l.strip()]


TWO = [("a.test.ts", [], "t1"), ("a.test.ts", [], "t2")]


def one(rows):
    live = [r for r in rows if not r["superseded"]]
    assert len(live) == 1
    return live[0]


def test_clean_run(tmp_path):
    """protects=a clean run reads as clean; fails_when=a correct run is counted in C1, C2 or C3;
    no_claim=says nothing about runs with failures"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(output=[STATUS.format(0, 0, 2, 0)])
    r = one(fx.check())
    assert r["completed"] and r["status_from"] == "log"
    assert (r["C1"], r["C2"], r["C2_runs"], r["C3"]) == (0, 0, 0, 0)
    assert r["P"] == 2 and r["S"] == 2 and r["D"] == 2


def test_exit0_with_failed_record(tmp_path):
    """protects=C1 sees a failed trace record behind exit 0; fails_when=a checker trusts the exit code alone;
    no_claim=the status line here is consistent with the record"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(output=[STATUS.format(1, 0, 1, 0)], recs=[("a.test.ts::t1", "failed"), ("a.test.ts::t2", "passed")])
    r = one(fx.check())
    assert r["C1"] == 1 and r["bad_records"] == 1


def test_exit0_failed_record_without_status(tmp_path):
    """protects=C1 from the trace record alone (the old engine prints no status);
    fails_when=C1 depends on the status line; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(recs=[("a.test.ts::t1", "failed"), ("a.test.ts::t2", "passed")])
    r = one(fx.check(phase="before"))
    assert r["C1"] == 1 and r["C2"] is None and r["C2_reason"] == "n/a: pre-P0 engine"


def test_exit0_not_proven_in_meta_only(tmp_path):
    """protects=a NOT PROVEN file recorded only in meta.hazard_rerun makes an exit-0 run C1;
    fails_when=the checker reads NOT PROVEN files from the log only; no_claim=the counts in meta.status are 0 on purpose"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    meta = {"status": {"failed": 0, "not_proven": 0, "passed": 2, "skipped": 0},
            "hazard_rerun": {"not_proven": [{"file": "a.test.ts", "cause": "0 tests ran"}]}}
    fx.run(kind="par", workers=2, meta=meta)
    r = one(fx.check())
    assert r["C1"] == 1 and r["status_from"] == "meta"
    assert r["not_proven_files"] == [{"file": "a.test.ts", "cause": "0 tests ran", "source": "meta"}]


def test_not_proven_log_line(tmp_path):
    """protects=the log's NOT PROVEN line is a second source; fails_when=the line is ignored;
    no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(kind="par", workers=2, output=[
        "detjs: parallel: NOT PROVEN b.test.ts: the one-lane re-run did not account for its tests (0 tests: x)",
        STATUS.format(0, 0, 2, 0)])
    r = one(fx.check())
    assert r["C1"] == 1 and r["not_proven_files"][0]["file"] == "b.test.ts"


def test_not_proven_log_line_with_the_engine_cause(tmp_path):
    """protects=the log's NOT PROVEN line as the engine writes it since the runner sends summary.proof (cause
    "<file>: the one-lane re-run ran N of its M test(s)" inside the parentheses) is still read, file and cause;
    fails_when=the new cause text breaks NP_RE; no_claim=the meta source (test_exit0_not_proven_in_meta_only)."""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(kind="par", workers=2, output=[
        "detjs: parallel: NOT PROVEN b.test.ts: the one-lane re-run did not account for its tests"
        " (b.test.ts: the one-lane re-run ran 0 of its 2 test(s))",
        STATUS.format(0, 0, 2, 0)])
    r = one(fx.check())
    assert r["C1"] == 1
    assert r["not_proven_files"] == [{"file": "b.test.ts", "cause": "b.test.ts: the one-lane re-run ran 0 of its 2 test(s)",
                                      "source": "log"}]


def test_status_sum_below_plain(tmp_path):
    """protects=C2 counts tests the user report leaves out; fails_when=a status that reports fewer tests than the
    plain run passes; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO + [("b.test.ts", ["g"], "t3")])
    fx.run(output=[STATUS.format(0, 0, 1, 0)],
           recs=[("a.test.ts::t1", "passed"), ("a.test.ts::t2", "passed"), ("b.test.ts::g::t3", "passed")])
    r = one(fx.check())
    assert r["C2"] == 2 and r["P"] == 3 and r["S"] == 1 and r["C3"] == 0


def test_no_status(tmp_path):
    """protects=a run without a status line and without meta.status is counted in C2_runs;
    fails_when=a missing user report reads as 0 dropped; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(output=["some vitest output"])
    rows = fx.check()
    r = one(rows)
    assert r["C2_runs"] == 1 and r["C2_reason"] == "no status" and r["C2"] is None
    assert check_p0.totals(rows)["C2_runs"] == 1


def test_not_written_status(tmp_path):
    """protects=`detjs: status: not written` is no status, even with meta.status in the trace;
    fails_when=the meta fallback hides the not-written line; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(output=["detjs: status: not written (the trace x could not be read back)"],
           meta={"status": {"failed": 0, "not_proven": 0, "passed": 2, "skipped": 0}})
    r = one(fx.check())
    assert r["C2_runs"] == 1 and r["status_reason"] == "no status"


def test_duplicate_status(tmp_path):
    """protects=two status lines are flagged; fails_when=the checker picks one of them;
    no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(output=[STATUS.format(0, 0, 2, 0), STATUS.format(0, 0, 2, 0)])
    r = one(fx.check())
    assert r["C2_runs"] == 1 and r["C2_reason"] == "duplicate status"


def test_plain_id_missing_from_trace(tmp_path):
    """protects=C3 counts a plain-run test absent from the trace; fails_when=missing tests read as 0;
    no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(output=[STATUS.format(0, 0, 1, 0)], recs=[("a.test.ts::t1", "passed")])
    r = one(fx.check())
    assert r["C3"] == 1 and r["missing_ids"] == ["a.test.ts::t2"]


def test_never_started_as_skipped(tmp_path):
    """protects=a never-started test written as skipped is in the trace (C3 = 0) and is counted;
    fails_when=the never-started record is missed or counted as missing; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    ev = [{"k": "sched", "o": "sched.never_started", "a": "", "s": "<detjs>"}]
    fx.run(exit=1, output=[STATUS.format(0, 0, 1, 1)], recs=[("a.test.ts::t1", "passed"), ("a.test.ts::t2", "skipped", ev)])
    r = one(fx.check())
    assert r["C3"] == 0 and r["never_started"] == 1 and r["C1"] == 0


def test_invalid_plain_row(tmp_path):
    """protects=an invalid plain run gives UNKNOWN, never 0; fails_when=C3 or C2 reads 0 without a valid plain run;
    no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO, invalid="0 tests reported, exit 1 after 1 s")
    fx.run(output=[STATUS.format(0, 0, 2, 0)])
    rows = fx.check()
    r = one(rows)
    assert r["C3"] == "UNKNOWN" and r["C2"] == "UNKNOWN" and "INVALID" in r["C3_reason"]
    assert check_p0.totals(rows)["C3"] == "UNKNOWN"


def test_missing_plain_ids(tmp_path):
    """protects=a missing plain ids file gives UNKNOWN; fails_when=no ids reads as 0 missing; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO, write_ids=False)
    fx.run(output=[STATUS.format(0, 0, 2, 0)])
    r = one(fx.check())
    assert r["C3"] == "UNKNOWN" and r["C2"] == "UNKNOWN"


def test_timeout_not_completed(tmp_path):
    """protects=a timed-out run is not completed and counts nowhere; fails_when=exit 124 counts in C1-C3;
    no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(exit=124, trace=False)
    rows = fx.check()
    r = one(rows)
    assert r["completed"] is False and r["C1"] is None and r["C3"] is None
    t = check_p0.totals(rows)
    assert t["C1"] == 0 and t["completed"] == 0 and t["not_completed"] == [("serial", 1, 1, 124)]


def test_superseded_and_last_log_block(tmp_path):
    """protects=a re-run row supersedes the earlier one, and the last log block of a repeated header is used;
    fails_when=the old run's failure or status is counted; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(exit=124, output=["killed"], trace=False)
    fx.run(output=[STATUS.format(0, 0, 2, 0)])
    rows = fx.check()
    assert len([r for r in rows if r["superseded"]]) == 1
    r = one(rows)
    assert r["completed"] and r["status_from"] == "log" and r["C1"] == 0


def test_rerun_does_not_duplicate(tmp_path):
    """protects=re-running the checker replaces its rows of the same (repo, phase), keeps others;
    fails_when=rows pile up; no_claim=-"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(output=[STATUS.format(0, 0, 2, 0)])
    fx.check(phase="before")
    fx.check()
    rows = fx.check()
    assert len(rows) == 2 and {r["phase"] for r in rows} == {"before", "after"}


def test_verify_attached(tmp_path):
    """protects=the round's verify verdict is attached to the parallel run; fails_when=it is lost or mismatched;
    no_claim=the verdict is reported, not gated"""
    fx = Fx(tmp_path)
    fx.plain(TWO)
    fx.run(kind="par", workers=2, output=[STATUS.format(0, 0, 2, 0)])
    fx.row(kind="verify", workers=2, exit=0, verdict="IDENTICAL", cmd="fenvix verify")
    r = one(fx.check())
    assert r["verify_verdict"] == "IDENTICAL" and r["verify_exit"] == 0
