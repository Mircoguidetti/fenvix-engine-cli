//! R-058: the `_io` entry (confirmed), and two attacks the engine survived (regression tests).

use detpy_core::event::{Event, Source};
use detpy_core::fingerprint::Fingerprinter;
use detpy_core::provable::{
    account, judge, required_controls, surface_digest, Accounting, Attestation, Verdict,
    SENSOR_CONTRACT,
};

// -- CONFIRMED: the documented weak claim is a real false-green channel ----------------------------

/// The `_io` doc comment (provable.rs:427) states the gap itself: "a stream that is not a file has
/// no such `open` behind it. A test that reads `sys.stdin` goes through the same `_io` methods, and
/// nothing records what it read."
///
/// This test pins the consequence, which the doc comment stops short of: because `_io.read` is
/// `Recorded` rather than `Unaccounted`, a stdin read puts NOTHING in the record's `unaccounted`
/// list, so clause 5 of `judge` has nothing to refuse and the test is `Provable`. Two runs fed
/// different standard input therefore compare equal on every field the verifier looks at, and the
/// report says "observed the same events".
///
/// Scope, stated honestly: this is MEASURED at the level of the accounting table and `judge`. I did
/// NOT run it end to end through the pytest plugin (the extension is not built in this container and
/// maturin is not installed), so the end-to-end behaviour is UNKNOWN -- it rests on the doc
/// comment's own statement that nothing records what stdin returned.
#[test]
fn reading_standard_input_is_not_accounted_for() {
    // The table's answer for the call a `sys.stdin.read()` lands on.
    assert_eq!(
        account("_io", "BufferedReader.read"),
        Accounting::Unaccounted,
        "`_io.read` is `Recorded` on the strength of an `fs.read` event behind it; sys.stdin has no \
         such event, so this answer hands the verdict a channel nobody recorded"
    );
}

/// The same point one level up, where it turns into the verdict: nothing a stdin read does reaches
/// `judge`, so the test is provable and the runs are reported identical.
#[test]
fn a_test_that_read_stdin_is_not_provable() {
    let controls: Vec<String> =
        required_controls("py-monitoring/1").iter().map(|s| s.to_string()).collect();
    // What the recorder stores for a test whose only uncontrolled input was standard input: the
    // `_io` entry answered `Recorded`, so there is no mark and no unaccounted entry.
    let v = judge(&Attestation {
        sensor: Some("py-monitoring/1"),
        contract: Some(SENSOR_CONTRACT),
        surface: Some(&surface_digest()),
        runtime: Some("cpython3.13"),
        controls: &controls,
        unaccounted: &[],
        marks: &[],
        outside: &[],
    });
    assert_ne!(
        v,
        Verdict::Provable,
        "a test that read standard input leaves no trace in the attestation, so judge calls it \
         provable; two runs given different stdin are then reported IDENTICAL"
    );
}

// -- SURVIVED: attacks that did NOT produce a wrong result -----------------------------------------

/// `--det-max-events` truncation does NOT hide a mark or an unaccounted entry. `Fingerprinter::push`
/// updates `counts`, `uncontrolled` and `unaccounted` BEFORE the `self.events.len() < self.max_events`
/// check, so the sets survive truncation even at `max_events = 0`. This is the earlier
/// "a count that read zero because the evidence had been truncated" bug; it is fixed. Regression test.
#[test]
fn survived_truncation_does_not_hide_a_mark_or_an_unaccounted_entry() {
    let mut f = Fingerprinter::new(0, 1); // store no events at all
    f.push(Event::new(Source::Random, "random.random", "t.py:1", "0.5"));
    f.push(Event::new(Source::Other, "uncontrolled.thread", "t.py:2", ""));
    f.push(Event::new(Source::Other, "unaccounted.module", "t.py:3", "ctypes"));
    let rec = f.finish("t.py::test", 0, "passed");

    assert!(rec.truncated, "nothing was stored");
    assert!(rec.events.is_empty(), "nothing was stored");
    assert_eq!(rec.uncontrolled, vec!["thread".to_string()], "the mark survived truncation");
    assert_eq!(
        rec.unaccounted,
        vec!["module:ctypes".to_string()],
        "the unaccounted entry survived truncation"
    );
    assert_eq!(rec.n_events, 4, "the count is over all events, not the stored ones");
    assert!(!rec.counts.is_empty(), "the per-source counts survived truncation");
}

/// Truncation also cannot make two different executions share a fingerprint: the chain covers every
/// event, stored or not. Regression test.
#[test]
fn survived_truncation_does_not_collapse_two_executions_onto_one_fingerprint() {
    let fp = |v: &str| {
        let mut f = Fingerprinter::new(0, 1);
        f.push(Event::new(Source::Random, "random.random", "t.py:1", v));
        f.finish("t.py::test", 0, "passed").fingerprint
    };
    assert_ne!(fp("0.1"), fp("0.9"), "the chain covers events the record does not store");
}
