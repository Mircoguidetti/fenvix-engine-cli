//! R-058: the empty fingerprint is treated as a value that can match another empty fingerprint.
//!
//! `""` is what every shell writes when it has NO evidence about a test: a test that never ended
//! (node/src/vitest/shell.js:31, node/src/jest/runner.js:391, node/src/runners/common.js:641), a test
//! an isolate lost (node/src/isolate.js:160), a reused test whose receipt is missing
//! (node/src/cache/trace-reused.js:33 `fingerprint: rc.fingerprint || ''`, and `outcome: rc.outcome
//! || 'passed'` beside it), a remote cache entry without one (node/src/cache/remote.js:361).
//!
//! Nothing in detpy-core treats `""` as "no evidence": grepping verify.rs, proof.rs, provable.rs and
//! trace.rs for an empty-fingerprint guard returns nothing. So the verifier compares `"" == ""` and
//! reports the two runs identical, and `proof::prove` compares `"" == ""` and returns `Proven`.

use detpy_core::proof::{prove, Entry, Proof, PLACEMENT_PARALLEL};
use detpy_core::provable::{required_controls, surface_digest, SENSOR_CONTRACT};
use detpy_core::trace::Header;
use detpy_core::verify::{render_text, verify_paths, Status};
use std::io::Write;
use std::path::{Path, PathBuf};

const NODEID: &str = "t.test.ts > draws";

fn clean_header() -> Header {
    let controls: Vec<String> =
        required_controls("node-vitest/1").iter().map(|s| s.to_string()).collect();
    Header::new(
        serde_json::json!({
            "provable": {
                "sensor": "node-vitest/1",
                "contract": SENSOR_CONTRACT,
                "surface": surface_digest(),
                "runtime": "node24",
            },
            "controls": controls,
            "env_reads_recorded": true,
            "inputs": {
                "runtime": "node24", "runner": "vitest-2.1.0", "seed": "0", "hashseed": "0",
                "clock": "virtual@2025-01-01Z", "tz": "UTC", "locale": "C",
                "network": "closed", "fs": "ordered", "entropy": "controlled",
            },
        }),
        vec![NODEID.to_string()],
    )
}

/// Exactly the line node/src/cache/trace-reused.js writes for a reused test whose receipt is absent:
/// no evidence at all, defaulted to `passed` with an empty fingerprint.
fn reused_line_without_a_receipt() -> serde_json::Value {
    serde_json::json!({
        "type": "test", "nodeid": NODEID, "index": 0,
        "outcome": "passed",     // rc.outcome || 'passed'
        "fingerprint": "",       // rc.fingerprint || ''
        "n_events": 0, "truncated": true, "counts": {}, "checkpoints": [], "events": [],
    })
}

fn write_cached_run(dir: &Path, name: &str) -> PathBuf {
    let path = dir.join(name);
    let mut f = std::fs::File::create(&path).unwrap();
    let header = serde_json::to_value(&clean_header()).unwrap();
    let mut header = header.as_object().unwrap().clone();
    header.insert("type".into(), serde_json::json!("header"));
    writeln!(f, "{}", serde_json::Value::Object(header)).unwrap();
    writeln!(f, "{}", reused_line_without_a_receipt()).unwrap();
    writeln!(
        f,
        "{}",
        serde_json::json!({"type":"footer","n_tests":1,"order_digest":
            detpy_core::trace::order_digest(&[NODEID])})
    )
    .unwrap();
    path
}

#[test]
fn a_test_with_no_recorded_fingerprint_is_not_reported_identical() {
    let dir = tempfile::tempdir().unwrap();
    // Two --det-cache runs, each served from the cache, each missing this test's receipt. Neither run
    // holds one byte of evidence about what the test observed.
    let a = write_cached_run(dir.path(), "cached_a.jsonl");
    let b = write_cached_run(dir.path(), "cached_b.jsonl");

    let report = verify_paths(&[&a, &b]).expect("both traces load");
    let text = render_text(&report, true);
    eprintln!("--- verifier output ---\n{text}\n--- end ---");

    assert_eq!(
        report.tests[0].status,
        Status::NotProven,
        "neither run recorded a fingerprint for this test, so there is nothing to compare; the \
         verifier reported {:?} and said: {text}",
        report.tests[0].status
    );
    assert!(
        !text.contains("IDENTICAL"),
        "two absences were compared and called an identical execution: {text}"
    );
}

fn entry(fingerprint: &str, placement: &str) -> Entry {
    Entry {
        outcome: "passed".into(),
        report: serde_json::Value::Null,
        fingerprint: fingerprint.into(),
        duration: 0.0,
        run: "r".into(),
        key: "the-same-key".into(),
        config: "c".into(),
        runtime: "node24".into(),
        epoch: None,
        env: vec![],
        data: vec![],
        content: 0,
        skeleton: 0,
        hooks: 0,
        units: vec![],
        fixtures: vec![],
        placement: placement.into(),
        serial_fp: None,
        serial_noise: false,
        preds: String::new(),
        startup: String::new(),
    }
}

#[test]
fn an_empty_fingerprint_does_not_prove_a_parallel_result_equal_to_the_serial_one() {
    // A serial entry recorded with no fingerprint (the test never ended, or its receipt was absent)
    // and a parallel entry likewise. P5 asks "same key, same fingerprint as the stable serial one".
    let stored = entry("", "");
    let parallel = entry("", PLACEMENT_PARALLEL);
    assert_ne!(
        prove(&parallel, Some(&stored)),
        Proof::Proven,
        "`\"\" == \"\"` is two absences agreeing, not a proof that the parallel run observed what \
         the serial run observed; a serial session may now reuse this parallel result as if it were \
         the serial one"
    );
}

/// End to end, with the header a fully-cached Node run really writes.
///
/// `node/src/session.js:327` (`provableField`): when no process declared a sensor -- which is the
/// case when nothing ran, because every test came from the cache -- the run declares
/// `cache-reuse/1`. `provable_header` stamps this core's real contract and real surface onto it.
/// `required_controls("cache-reuse/1")` is `&[]` (neither the `py-` nor the `node-` prefix), so
/// clause 3 of `judge` checks nothing and the run passes with `--det-disable` having switched off
/// every control. The reused test lines carry `fingerprint: ''` whenever the receipt holds none.
#[test]
fn two_fully_cached_runs_with_every_control_off_are_not_reported_identical() {
    let dir = tempfile::tempdir().unwrap();
    let header = serde_json::json!({
        "type": "header", "format": "detpy-trace", "version": 1, "encoding": 2,
        "meta": {
            "provable": {
                "sensor": "cache-reuse/1",
                "contract": SENSOR_CONTRACT,
                "surface": surface_digest(),
                "runtime": "node24",
            },
            "controls": [],                       // --det-disable=time,seeds,fs,net,timers
            "env_reads_recorded": true,
            "reused_tests": [NODEID],
            "inputs": { "runtime": "node24", "runner": "vitest-2.1.0" },
        },
        "order": [NODEID],
    });
    let mut paths = Vec::new();
    for name in ["all_cached_a.jsonl", "all_cached_b.jsonl"] {
        let path = dir.path().join(name);
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(f, "{header}").unwrap();
        writeln!(f, "{}", reused_line_without_a_receipt()).unwrap();
        writeln!(
            f,
            "{}",
            serde_json::json!({"type":"footer","n_tests":1,
                "order_digest": detpy_core::trace::order_digest(&[NODEID])})
        )
        .unwrap();
        paths.push(path);
    }

    let report = verify_paths(&paths).expect("both traces load");
    let text = render_text(&report, true);
    eprintln!("--- verifier output ---\n{text}\n--- end ---");

    assert!(
        !text.contains("IDENTICAL"),
        "two runs that ran nothing, recorded no fingerprint and had every --det control switched \
         off are reported as an identical execution: {text}"
    );
}
