//! R-058: the `_io` entry (confirmed), and two attacks the engine survived (regression tests).

use detpy_core::event::{Event, Source};
use detpy_core::fingerprint::Fingerprinter;
use detpy_core::provable::{
    judge, required_controls, surface_digest, Attestation, Verdict, SENSOR_CONTRACT,
};

// -- CONFIRMED: the documented weak claim is a real false-green channel ----------------------------

/// R-058 #5, fixed: a test that reads standard input is NOT PROVEN.
///
/// The reviewer's own two tests asserted one particular remedy -- `account("_io", "read")` answering
/// `Unaccounted` -- and that remedy is the wrong one, so they are replaced here by the guarantee
/// itself rather than deleted. Two reasons, both measured:
///
/// 1. The table answers for a NAME, and the name is the same for a file and for standard input
///    (`_io.TextIOWrapper.readline` either way). Making it `Unaccounted` would refuse every test
///    that reads an ordinary file -- which the `fs.read` event behind `open` genuinely accounts for
///    -- and the provable share is what the customer is sold in skipped tests and spread cores.
/// 2. `judge` cannot see a channel nobody reported: the reviewer's second test asserted that a
///    clean attestation is not provable, which would refuse every test in existence.
///
/// The fix belongs where the stream object is, which is the sensor:
/// `python/detpy/provable.py`, `_refresh_standard_streams` + the `_IO_MODULES` branch of `_on_call`.
/// A call on `sys.stdin`, its buffer, or `sys.__stdin__` is reported as `io:standard input`.
///
/// The end-to-end proof the reviewer could not run (no built extension in a review container) is
/// `tests/test_provable_general_rule.py::test_a_test_that_reads_standard_input_is_not_identical`:
/// two runs fed different bytes on stdin, which were IDENTICAL before this fix and are NOT PROVEN
/// after it, with a control leg that is still IDENTICAL without the read. MEASURED.
///
/// What this test pins is the core's half of that: the entry the sensor writes must reach a refusal.
#[test]
fn a_reported_standard_input_read_is_not_proven() {
    let controls: Vec<String> =
        required_controls("py-monitoring/1").iter().map(|s| s.to_string()).collect();
    let unaccounted = vec!["io:standard input".to_string()];
    let v = judge(&Attestation {
        sensor: Some("py-monitoring/1"),
        contract: Some(SENSOR_CONTRACT),
        surface: Some(&surface_digest()),
        runtime: Some("cpython3.13"),
        controls: &controls,
        unaccounted: &unaccounted,
        marks: &[],
        outside: &[],
    });
    match v {
        Verdict::NotProven { kind, detail } => {
            assert_eq!(kind, "io", "the refusal names the channel: {detail}");
            assert!(detail.contains("standard input"), "{detail}");
        }
        Verdict::Provable => panic!("a reported standard input read must never be provable"),
    }
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
