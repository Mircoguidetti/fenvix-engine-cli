//! R-058: the verifier never checks a test record's `fingerprint` against the record's own `events`.
//!
//! `fingerprint::fingerprint_of` carries the doc comment
//!     "Recompute the fingerprint of a complete (non-truncated) event list.
//!      Used by the verifier to validate traces and by tests."
//! It has no caller outside its own unit test. `verify::verify` compares the stored `fingerprint`
//! strings and, when they agree, never looks at the events at all (`diff_records` is reached only on
//! the unequal branch). So two traces whose tests observed demonstrably different values are reported
//! IDENTICAL / stable as long as the stored strings match.

use detpy_core::event::{Event, Source};
use detpy_core::fingerprint::{Fingerprinter, TestRecord};
use detpy_core::provable::{required_controls, surface_digest, SENSOR_CONTRACT};
use detpy_core::trace::{Header, TraceWriter};
use detpy_core::verify::{verify_paths, render_text, Status};
use std::path::{Path, PathBuf};

const NODEID: &str = "t.py::test_draw";

/// A header that satisfies every clause of `provable::judge`, so the only thing left to decide the
/// verdict is the fingerprint comparison itself.
fn clean_header() -> Header {
    let controls: Vec<String> =
        required_controls("py-monitoring/1").iter().map(|s| s.to_string()).collect();
    Header::new(
        serde_json::json!({
            "provable": {
                "sensor": "py-monitoring/1",
                "contract": SENSOR_CONTRACT,
                "surface": surface_digest(),
                "runtime": "cpython3.13",
            },
            "controls": controls,
            "env_reads_recorded": true,
            // identical run inputs in both traces, so nothing else can hold the verdict back
            "inputs": {
                "runtime": "cpython3.13",
                "runner": "pytest-8.3.2",
                "seed": "0",
                "hashseed": "0",
                "clock": "virtual@2025-01-01Z",
                "tz": "UTC",
                "locale": "C",
                "network": "closed",
                "fs": "ordered",
                "entropy": "controlled",
                "bytecode": "precompiled",
            },
        }),
        vec![NODEID.to_string()],
    )
}

/// One test that drew `value` from `random.random()`, with the honest fingerprint of that draw.
fn record_drawing(value: &str) -> TestRecord {
    let mut f = Fingerprinter::default();
    f.push(Event::new(Source::Random, "random.random", "t.py:4", value));
    f.finish(NODEID, 0, "passed")
}

fn write(dir: &Path, name: &str, rec: &TestRecord) -> PathBuf {
    let path = dir.join(name);
    let mut w = TraceWriter::create(&path, &clean_header()).unwrap();
    w.write_test(rec).unwrap();
    w.finish().unwrap();
    path
}

#[test]
fn two_runs_that_observed_different_values_are_not_reported_identical() {
    let dir = tempfile::tempdir().unwrap();

    // Run A genuinely drew 0.1. Run B genuinely drew 0.9 -- the events on disk differ in value.
    let run_a = record_drawing("0.1");
    let mut run_b = record_drawing("0.9");

    // The two honest fingerprints differ, as they must.
    assert_ne!(run_a.fingerprint, run_b.fingerprint, "the draws differ, so the honest chains differ");

    // Now the only thing wrong with run B's trace: its `fingerprint` field does not belong to its
    // events. Everything else -- events, n_events, counts, checkpoints, outcome -- is run B's own.
    // This is what a hand-written trace, a shell whose chain disagrees with this core, or a
    // tampered CI artifact looks like on disk. Nothing in the format signs the record.
    run_b.fingerprint = run_a.fingerprint.clone();

    let pa = write(dir.path(), "run_a.jsonl", &run_a);
    let pb = write(dir.path(), "run_b.jsonl", &run_b);

    let report = verify_paths(&[&pa, &pb]).expect("both traces load and are compatible");
    let text = render_text(&report, true);

    // What the engine actually says today.
    eprintln!("--- verifier output ---\n{text}\n--- end ---");

    let v = &report.tests[0];
    assert_eq!(
        v.status,
        Status::NotProven,
        "two runs whose recorded events hold different values must never be reported \
         identical/stable; the verifier reported {:?} and summarised: {}",
        v.status,
        text.lines().last().unwrap_or("")
    );
    assert_eq!(report.summary.identical, 0, "no test observed the same events: {text}");
    assert!(
        !text.contains("IDENTICAL"),
        "the report claims the runs 'observed the same events' while their stored events differ: {text}"
    );
}
