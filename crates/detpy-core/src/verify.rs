//! Cross-run verifier.
//!
//! Given N traces of the same suite, the verifier decides for every test
//! whether Level 0 made it reproducible: all runs must produce the same
//! fingerprint. When fingerprints differ the test is reported as
//! *not covered by Level 0*, together with the first point where two runs
//! diverge and a classification of the cause.

use crate::event::{Event, Source};
use crate::fingerprint::TestRecord;
use crate::trace::{order_digest, read_trace, Trace, TraceError};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

/// Why two executions of a test diverged.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Reason {
    /// First differing event is a clock interaction.
    Time,
    Random,
    Fs,
    Net,
    /// OS entropy (urandom, uuid4, secrets): observed but not controlled.
    Entropy,
    Syscall,
    Other,
    /// The differing events come from different threads or from a non-main
    /// thread: scheduling is not controlled by Level 0.
    Thread,
    /// Same observed events, different outcome: the cause is a source that
    /// Level 0 does not observe (C extensions, memory addresses, external state).
    OutcomeOnly,
    /// The stored prefixes are identical; the difference lies past the
    /// stored events (see `window`).
    BeyondTrace,
    /// The test did not run in every trace.
    Missing,
    /// One run is a parallel run under a plan (merged trace), the other serial, and the test ran in its worker
    /// without some of its serial in-process predecessors (`lost_predecessors`): it observed process state that
    /// depends on where it ran (docs/PARALLEL-PROOF-DESIGN.md 2.4). Entropy and thread divergences keep their class.
    Placement,
}

impl Reason {
    pub fn as_str(self) -> &'static str {
        match self {
            Reason::Time => "time",
            Reason::Random => "random",
            Reason::Fs => "fs",
            Reason::Net => "net",
            Reason::Entropy => "entropy",
            Reason::Syscall => "syscall",
            Reason::Other => "other",
            Reason::Thread => "thread",
            Reason::OutcomeOnly => "outcome-only",
            Reason::BeyondTrace => "beyond-trace",
            Reason::Missing => "missing",
            Reason::Placement => "placement",
        }
    }

    fn from_source(s: Source) -> Reason {
        match s {
            Source::Time => Reason::Time,
            Source::Random => Reason::Random,
            Source::Fs => Reason::Fs,
            Source::Net => Reason::Net,
            Source::Entropy => Reason::Entropy,
            Source::Syscall => Reason::Syscall,
            Source::Outcome => Reason::OutcomeOnly,
            Source::Other => Reason::Other,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Divergence {
    pub run_a: usize,
    pub run_b: usize,
    /// 0-based index of the first differing event, when known exactly.
    pub index: Option<u64>,
    /// `[lo, hi)` event range containing the first difference when it cannot
    /// be located exactly (past the stored prefix).
    pub window: Option<(u64, u64)>,
    pub event_a: Option<Event>,
    pub event_b: Option<Event>,
    pub reason: Reason,
    pub description: String,
    /// `placement`: serial in-process predecessors the test did not have in its worker (serial order, at most 20).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub lost_predecessors: Vec<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Status {
    /// Same fingerprint in every run: covered by Level 0.
    Stable,
    /// Fingerprints differ: not covered by Level 0.
    Diverged,
    /// Not executed in every run.
    Missing,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TestVerdict {
    pub nodeid: String,
    pub status: Status,
    pub fingerprints: Vec<Option<String>>,
    pub outcomes: Vec<Option<String>>,
    pub distinct_fingerprints: usize,
    /// All runs that executed the test agree on the outcome.
    pub outcome_stable: bool,
    pub divergence: Option<Divergence>,
}

impl TestVerdict {
    pub fn covered(&self) -> bool {
        self.status == Status::Stable
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Summary {
    pub runs: usize,
    pub tests: usize,
    pub stable: usize,
    pub diverged: usize,
    pub missing: usize,
    /// Tests whose outcome differs between runs (flaky even under Level 0).
    pub outcome_unstable: usize,
    pub order_identical: bool,
    pub reasons: BTreeMap<String, usize>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Report {
    pub labels: Vec<String>,
    pub order_digests: Vec<String>,
    pub complete: Vec<bool>,
    pub summary: Summary,
    pub tests: Vec<TestVerdict>,
}

/// In-process predecessors of every test of one trace: the tests before it in the trace (serial run), or before it
/// in its worker (merged trace of a parallel run: records carry `worker` / `worker_index`).
struct Predecessors<'a> {
    parallel: bool,
    /// Serial: the executed order. Parallel: per worker, its tests by worker index.
    lists: BTreeMap<&'a str, Vec<&'a str>>,
    at: BTreeMap<&'a str, (&'a str, usize)>,
}

impl<'a> Predecessors<'a> {
    fn of(t: &'a Trace) -> Self {
        let parallel = t.tests.iter().any(|r| r.worker.is_some());
        let mut lists: BTreeMap<&str, Vec<(u64, &str)>> = BTreeMap::new();
        for r in &t.tests {
            let w = r.worker.as_deref().unwrap_or("");
            lists.entry(w).or_default().push((r.worker_index.unwrap_or(r.index), r.nodeid.as_str()));
        }
        let mut out = Predecessors { parallel, lists: BTreeMap::new(), at: BTreeMap::new() };
        for (w, mut l) in lists {
            l.sort();
            for (i, (_, n)) in l.iter().enumerate() {
                out.at.insert(n, (w, i));
            }
            out.lists.insert(w, l.into_iter().map(|(_, n)| n).collect());
        }
        out
    }

    fn before(&self, id: &str) -> &[&'a str] {
        match self.at.get(id) {
            Some((w, i)) => &self.lists[w][..*i],
            None => &[],
        }
    }
}

/// Reclassify a divergence as `placement` when exactly one side ran under a plan and lost serial predecessors.
fn placement(d: &mut Divergence, id: &str, a: &Predecessors, b: &Predecessors) {
    if a.parallel == b.parallel || matches!(d.reason, Reason::Entropy | Reason::Thread | Reason::Missing) {
        return;
    }
    let (serial, plan) = if a.parallel { (b, a) } else { (a, b) };
    let kept: BTreeSet<&str> = plan.before(id).iter().copied().collect();
    let lost: Vec<String> = serial.before(id).iter().filter(|n| !kept.contains(**n)).map(|n| n.to_string()).collect();
    if lost.is_empty() {
        return;
    }
    let worker = plan.at.get(id).map(|(w, _)| *w).unwrap_or("?");
    d.description = format!(
        "placement: ran in worker {worker} without {} of its serial predecessors (first difference: {})",
        lost.len(),
        d.description
    );
    d.reason = Reason::Placement;
    d.lost_predecessors = lost.into_iter().take(20).collect();
}

/// Locate the first divergence between two records of the same test.
pub fn diff_records(a: &TestRecord, b: &TestRecord, run_a: usize, run_b: usize) -> Option<Divergence> {
    if a.fingerprint == b.fingerprint {
        return None;
    }
    let common = a.events.len().min(b.events.len());
    for i in 0..common {
        let (ea, eb) = (&a.events[i], &b.events[i]);
        if ea != eb {
            let reason = classify(Some(ea), Some(eb));
            return Some(Divergence {
                run_a,
                run_b,
                index: Some(i as u64),
                window: None,
                event_a: Some(ea.clone()),
                event_b: Some(eb.clone()),
                reason,
                description: describe(i as u64, Some(ea), Some(eb)),
                lost_predecessors: Vec::new(),
            });
        }
    }
    // Stored prefixes agree up to `common`.
    if !a.truncated && !b.truncated {
        // Both complete: one sequence is a strict prefix of the other except
        // for the outcome event (the outcome is always last).
        let i = common;
        let ea = a.events.get(i);
        let eb = b.events.get(i);
        let reason = classify(ea, eb);
        return Some(Divergence {
            run_a,
            run_b,
            index: Some(i as u64),
            window: None,
            event_a: ea.cloned(),
            event_b: eb.cloned(),
            reason,
            description: describe(i as u64, ea, eb),
            lost_predecessors: Vec::new(),
        });
    }
    // Both truncated (or not decidable from stored events): bracket with checkpoints.
    let ca: BTreeMap<u64, &String> = a.checkpoints.iter().map(|(n, h)| (*n, h)).collect();
    let mut lo = common as u64;
    let mut hi = a.n_events.max(b.n_events);
    for (n, hb) in &b.checkpoints {
        if let Some(ha) = ca.get(n) {
            if *ha == hb {
                lo = lo.max(*n);
            } else {
                hi = hi.min(*n);
                break;
            }
        }
    }
    if a.n_events != b.n_events {
        hi = hi.min(a.n_events.min(b.n_events));
    }
    lo = lo.min(hi);
    Some(Divergence {
        run_a,
        run_b,
        index: None,
        window: Some((lo, hi)),
        event_a: None,
        event_b: None,
        reason: Reason::BeyondTrace,
        description: format!(
            "stored events are identical; first difference in events [{lo}, {hi}) \
             (raise --det-max-events to capture it exactly)"
        ),
        lost_predecessors: Vec::new(),
    })
}

/// Site used by producers for summary events emitted when a test ends
/// (e.g. final generator state). Like the outcome, they close the sequence.
pub const END_SITE: &str = "<end>";

fn is_terminal(e: &Event) -> bool {
    e.source == Source::Outcome || e.site == END_SITE
}

fn classify(a: Option<&Event>, b: Option<&Event>) -> Reason {
    match (a, b) {
        (Some(ea), Some(eb)) => {
            if ea.thread != eb.thread || ea.thread != 0 {
                Reason::Thread
            } else if ea.source == Source::Outcome && eb.source == Source::Outcome {
                Reason::OutcomeOnly
            } else if is_terminal(ea) && !is_terminal(eb) {
                // Run A already ended: run B performed an extra interaction.
                Reason::from_source(eb.source)
            } else {
                Reason::from_source(ea.source)
            }
        }
        (Some(e), None) | (None, Some(e)) => {
            if e.thread != 0 {
                Reason::Thread
            } else {
                Reason::from_source(e.source)
            }
        }
        (None, None) => Reason::Other,
    }
}

fn describe(i: u64, a: Option<&Event>, b: Option<&Event>) -> String {
    let show = |e: Option<&Event>| e.map(|e| e.to_string()).unwrap_or_else(|| "<no event>".into());
    match (a, b) {
        (Some(ea), Some(eb)) if ea.source == Source::Outcome && eb.source == Source::Outcome => format!(
            "identical observed events, different outcome ({} vs {}): \
             the cause is a source Level 0 does not observe",
            ea.value, eb.value
        ),
        (Some(ea), Some(eb)) if ea.op == eb.op && ea.site == eb.site && ea.thread == eb.thread => format!(
            "event #{i}: {} @ {} returned different values: {:?} vs {:?}",
            ea.op, ea.site, ea.value, eb.value
        ),
        _ => format!("event #{i}: {}  <>  {}", show(a), show(b)),
    }
}

/// Verify a set of traces of the same suite.
pub fn verify(traces: &[Trace], labels: &[String]) -> Report {
    let n = traces.len();
    let mut all_ids: BTreeSet<&str> = BTreeSet::new();
    let indexes: Vec<BTreeMap<&str, &TestRecord>> = traces
        .iter()
        .map(|t| {
            let m: BTreeMap<&str, &TestRecord> = t.tests.iter().map(|r| (r.nodeid.as_str(), r)).collect();
            all_ids.extend(m.keys().copied());
            m
        })
        .collect();

    let preds: Vec<Predecessors> = traces.iter().map(Predecessors::of).collect();
    // Report tests in the executed order of the first run, then the rest.
    let mut ordered: Vec<&str> = Vec::new();
    let mut seen = BTreeSet::new();
    for t in traces {
        for r in &t.tests {
            if seen.insert(r.nodeid.as_str()) {
                ordered.push(r.nodeid.as_str());
            }
        }
    }

    let mut summary = Summary { runs: n, ..Default::default() };
    let mut tests = Vec::with_capacity(ordered.len());
    for id in ordered {
        let recs: Vec<Option<&TestRecord>> = indexes.iter().map(|m| m.get(id).copied()).collect();
        let fingerprints: Vec<Option<String>> = recs.iter().map(|r| r.map(|r| r.fingerprint.clone())).collect();
        let outcomes: Vec<Option<String>> = recs.iter().map(|r| r.map(|r| r.outcome.clone())).collect();
        let distinct: BTreeSet<&str> = recs.iter().flatten().map(|r| r.fingerprint.as_str()).collect();
        let distinct_outcomes: BTreeSet<&str> = recs.iter().flatten().map(|r| r.outcome.as_str()).collect();
        let outcome_stable = distinct_outcomes.len() <= 1;
        let present = recs.iter().filter(|r| r.is_some()).count();

        let (status, divergence) = if present < n {
            let missing_in: Vec<String> =
                recs.iter().enumerate().filter(|(_, r)| r.is_none()).map(|(i, _)| i.to_string()).collect();
            (
                Status::Missing,
                Some(Divergence {
                    run_a: 0,
                    run_b: 0,
                    index: None,
                    window: None,
                    event_a: None,
                    event_b: None,
                    reason: Reason::Missing,
                    description: format!("not executed in run(s) {}", missing_in.join(", ")),
                    lost_predecessors: Vec::new(),
                }),
            )
        } else if distinct.len() <= 1 {
            (Status::Stable, None)
        } else {
            let a = recs[0].unwrap();
            let j = recs.iter().position(|r| r.unwrap().fingerprint != a.fingerprint).unwrap();
            let mut d = diff_records(a, recs[j].unwrap(), 0, j);
            if let Some(d) = d.as_mut() {
                placement(d, id, &preds[0], &preds[j]);
            }
            (Status::Diverged, d)
        };

        match status {
            Status::Stable => summary.stable += 1,
            Status::Diverged => summary.diverged += 1,
            Status::Missing => summary.missing += 1,
        }
        if !outcome_stable {
            summary.outcome_unstable += 1;
        }
        if let Some(d) = &divergence {
            *summary.reasons.entry(d.reason.as_str().to_string()).or_insert(0) += 1;
        }
        tests.push(TestVerdict {
            nodeid: id.to_string(),
            status,
            fingerprints,
            outcomes,
            distinct_fingerprints: distinct.len(),
            outcome_stable,
            divergence,
        });
    }
    summary.tests = tests.len();
    let order_digests: Vec<String> = traces.iter().map(|t| order_digest(&t.executed_order())).collect();
    summary.order_identical = order_digests.windows(2).all(|w| w[0] == w[1]);
    Report {
        labels: labels.to_vec(),
        order_digests,
        complete: traces.iter().map(|t| t.is_complete()).collect(),
        summary,
        tests,
    }
}

pub fn verify_paths<P: AsRef<Path>>(paths: &[P]) -> Result<Report, TraceError> {
    let mut traces = Vec::new();
    let mut labels = Vec::new();
    for p in paths {
        traces.push(read_trace(p.as_ref())?);
        labels.push(p.as_ref().display().to_string());
    }
    Ok(verify(&traces, &labels))
}

/// Human-readable rendering of a report.
pub fn render_text(report: &Report, show_stable: bool) -> String {
    use std::fmt::Write;
    let s = &report.summary;
    let mut out = String::new();
    let _ = writeln!(out, "detpy verify: {} runs, {} tests", s.runs, s.tests);
    for (i, l) in report.labels.iter().enumerate() {
        let partial = if report.complete.get(i).copied().unwrap_or(true) { "" } else { " (partial)" };
        let _ = writeln!(out, "  run {i}: {l}{partial}");
    }
    let _ = writeln!(
        out,
        "order: {}",
        if s.order_identical { "identical in every run" } else { "DIFFERS between runs" }
    );
    let _ = writeln!(
        out,
        "covered by Level 0: {}  not covered: {}  missing: {}  outcome-unstable: {}",
        s.stable, s.diverged, s.missing, s.outcome_unstable
    );
    if !s.reasons.is_empty() {
        let rs: Vec<String> = s.reasons.iter().map(|(k, v)| format!("{k}={v}")).collect();
        let _ = writeln!(out, "reasons: {}", rs.join(" "));
    }
    for t in &report.tests {
        match &t.divergence {
            None if show_stable => {
                let _ = writeln!(out, "STABLE   {}", t.nodeid);
            }
            None => {}
            Some(d) => {
                let tag = if t.status == Status::Missing { "MISSING " } else { "NOT-COVERED" };
                let outcomes: Vec<&str> = t.outcomes.iter().map(|o| o.as_deref().unwrap_or("-")).collect();
                let _ = writeln!(out, "{tag} {}  [{}] outcomes={}", t.nodeid, d.reason.as_str(), outcomes.join(","));
                let _ = writeln!(out, "    runs {} vs {}: {}", d.run_a, d.run_b, d.description);
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fingerprint::Fingerprinter;
    use crate::trace::Header;

    fn rec(nodeid: &str, events: &[Event], outcome: &str, max: usize) -> TestRecord {
        let mut f = Fingerprinter::new(max, 4);
        for e in events {
            f.push(e.clone());
        }
        f.finish(nodeid, 0, outcome)
    }

    fn trace(recs: Vec<TestRecord>) -> Trace {
        Trace { header: Header::new(serde_json::Value::Null, vec![]), tests: recs, footer: None }
    }

    fn t(v: &str) -> Event {
        Event::new(Source::Time, "time.time", "t.py:1", v)
    }

    #[test]
    fn identical_runs_are_stable() {
        let a = trace(vec![rec("x", &[t("1")], "passed", 100)]);
        let b = trace(vec![rec("x", &[t("1")], "passed", 100)]);
        let r = verify(&[a, b], &["a".into(), "b".into()]);
        assert_eq!(r.summary.stable, 1);
        assert_eq!(r.summary.diverged, 0);
        assert!(r.tests[0].covered());
        assert!(r.summary.order_identical);
    }

    #[test]
    fn value_divergence_is_located_exactly() {
        let ent = |v: &str| Event::new(Source::Entropy, "os.urandom", "t.py:9", v);
        let a = trace(vec![rec("x", &[t("1"), ent("aa"), t("2")], "passed", 100)]);
        let b = trace(vec![rec("x", &[t("1"), ent("bb"), t("2")], "passed", 100)]);
        let r = verify(&[a, b], &[]);
        let v = &r.tests[0];
        assert_eq!(v.status, Status::Diverged);
        assert!(v.outcome_stable);
        let d = v.divergence.as_ref().unwrap();
        assert_eq!(d.index, Some(1));
        assert_eq!(d.reason, Reason::Entropy);
        assert!(d.description.contains("os.urandom"), "{}", d.description);
        assert_eq!(r.summary.reasons["entropy"], 1);
    }

    #[test]
    fn outcome_only_divergence() {
        let a = trace(vec![rec("x", &[t("1")], "passed", 100)]);
        let b = trace(vec![rec("x", &[t("1")], "failed", 100)]);
        let r = verify(&[a, b], &[]);
        let v = &r.tests[0];
        assert!(!v.outcome_stable);
        assert_eq!(r.summary.outcome_unstable, 1);
        let d = v.divergence.as_ref().unwrap();
        assert_eq!(d.reason, Reason::OutcomeOnly);
        assert_eq!(d.index, Some(1));
    }

    #[test]
    fn extra_event_divergence() {
        let a = trace(vec![rec("x", &[t("1")], "passed", 100)]);
        let fs = Event::new(Source::Fs, "os.listdir", "t.py:4", "3:abc");
        let b = trace(vec![rec("x", &[t("1"), fs.clone()], "passed", 100)]);
        let r = verify(&[a, b], &[]);
        let d = r.tests[0].divergence.as_ref().unwrap();
        assert_eq!(d.index, Some(1));
        assert_eq!(d.reason, Reason::Fs);
        assert_eq!(d.event_b.as_ref(), Some(&fs));
    }

    #[test]
    fn extra_event_blamed_over_end_summary() {
        let end = Event::new(Source::Random, "random.state", END_SITE, "x");
        let a = trace(vec![rec("x", &[end.clone()], "passed", 100)]);
        let b = trace(vec![rec("x", &[t("1"), end], "passed", 100)]);
        let r = verify(&[a, b], &[]);
        let d = r.tests[0].divergence.as_ref().unwrap();
        assert_eq!((d.index, d.reason), (Some(0), Reason::Time));
    }

    #[test]
    fn thread_divergence() {
        let a = trace(vec![rec("x", &[t("1"), t("2").with_thread(1)], "passed", 100)]);
        let b = trace(vec![rec("x", &[t("1").with_thread(1), t("2")], "passed", 100)]);
        let r = verify(&[a, b], &[]);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Thread);
    }

    #[test]
    fn beyond_trace_uses_checkpoints() {
        let mut ea: Vec<Event> = (0..20).map(|i| t(&i.to_string())).collect();
        let eb = ea.clone();
        ea[13] = t("changed");
        let a = trace(vec![rec("x", &ea, "passed", 5)]);
        let b = trace(vec![rec("x", &eb, "passed", 5)]);
        let r = verify(&[a, b], &[]);
        let d = r.tests[0].divergence.as_ref().unwrap();
        assert_eq!(d.reason, Reason::BeyondTrace);
        assert_eq!(d.index, None);
        // checkpoints every 4 events: 12 equal, 16 differs.
        assert_eq!(d.window, Some((12, 16)));
    }

    #[test]
    fn missing_and_order() {
        let a = trace(vec![rec("x", &[], "passed", 10), rec("y", &[], "passed", 10)]);
        let b = trace(vec![rec("y", &[], "passed", 10)]);
        let r = verify(&[a, b], &[]);
        assert_eq!(r.summary.missing, 1);
        assert_eq!(r.summary.stable, 1);
        assert!(!r.summary.order_identical);
        let text = render_text(&r, true);
        assert!(text.contains("MISSING"), "{text}");
        assert!(text.contains("STABLE   y"), "{text}");
    }

    #[test]
    fn three_runs_compare_against_first_differing() {
        let a = trace(vec![rec("x", &[t("1")], "passed", 10)]);
        let b = trace(vec![rec("x", &[t("1")], "passed", 10)]);
        let c = trace(vec![rec("x", &[t("2")], "passed", 10)]);
        let r = verify(&[a, b, c], &[]);
        let v = &r.tests[0];
        assert_eq!(v.distinct_fingerprints, 2);
        let d = v.divergence.as_ref().unwrap();
        assert_eq!((d.run_a, d.run_b), (0, 2));
        assert_eq!(d.reason, Reason::Time);
    }

    #[test]
    fn placement_divergence_names_the_lost_predecessors() {
        // serial: polluter, victim; parallel: victim alone in gw1, with a different event
        let pol = rec("p", &[r("1")], "passed", 10);
        let vic_serial = rec("v", &[r("2")], "passed", 10);
        let mut pol2 = pol.clone();
        pol2.worker = Some("gw0".into());
        pol2.worker_index = Some(0);
        let mut vic_par = rec("v", &[t("3")], "passed", 10);
        vic_par.worker = Some("gw1".into());
        vic_par.worker_index = Some(0);
        let serial = trace(vec![pol, vic_serial]);
        let par = trace(vec![pol2, vic_par]);
        let rep = verify(&[serial, par], &["s".into(), "p".into()]);
        let v = rep.tests.iter().find(|x| x.nodeid == "v").unwrap();
        let d = v.divergence.as_ref().unwrap();
        assert_eq!(d.reason, Reason::Placement);
        assert_eq!(d.lost_predecessors, vec!["p".to_string()]);
        assert_eq!(rep.summary.reasons["placement"], 1);
        // two serial runs: never placement
        let rep2 = verify(&[trace(vec![rec("v", &[r("2")], "passed", 10)]), trace(vec![rec("v", &[t("3")], "passed", 10)])],
                          &["a".into(), "b".into()]);
        assert_ne!(rep2.tests[0].divergence.as_ref().unwrap().reason, Reason::Placement);
    }

    fn r(v: &str) -> Event {
        Event::new(Source::Random, "random.random", "t.py:1", v)
    }
}
