//! Cross-run verifier.
//!
//! Given N traces of the same suite, the verifier decides for every test
//! whether Level 0 made it reproducible: all runs must produce the same
//! fingerprint. When fingerprints differ the test is reported as
//! *not covered by Level 0*, together with the first point where two runs
//! diverge and a classification of the cause.

use crate::event::{Event, Source};
use crate::fingerprint::{TestRecord, UNCONTROLLED_PREFIX};
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
    /// First differing event is a scheduling choice of the Level 1 runtime
    /// (`--det-async`): the runs delivered asyncio events in a different order.
    Sched,
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
    /// A run input recorded in the trace header (`meta.inputs`) differs between the runs: an environment variable.
    Env,
    /// The time zone the runs used differs (pinned value, or the machine's when not pinned).
    Tz,
    /// The locale the runs used differs.
    Locale,
    /// The seed of the generators and of the shuffle differs.
    Seed,
    /// `PYTHONHASHSEED` (string hashing, set and dict order of str keys) differs.
    Hashseed,
    /// The test ran after different tests (serial runs: its in-process predecessors differ).
    Order,
    /// The interpreter, its version, the platform or the test runner differs.
    Runtime,
    /// Another recorded run input differs (a control switched on in one run only, bytecode mode, ...), or one run
    /// recorded no inputs.
    Config,
    /// The test started a child process: what the child does is not controlled by Level 0.
    Child,
    /// The test waited on I/O readiness (selectors): the order in which ready I/O is delivered is not controlled.
    Io,
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
            Reason::Sched => "sched",
            Reason::Thread => "thread",
            Reason::OutcomeOnly => "outcome-only",
            Reason::BeyondTrace => "beyond-trace",
            Reason::Missing => "missing",
            Reason::Placement => "placement",
            Reason::Env => "env",
            Reason::Tz => "tz",
            Reason::Locale => "locale",
            Reason::Seed => "seed",
            Reason::Hashseed => "hashseed",
            Reason::Order => "order",
            Reason::Runtime => "runtime",
            Reason::Config => "config",
            Reason::Child => "child",
            Reason::Io => "io",
        }
    }

    /// The reason an event names by its operation, before its source: environment reads (`env.*`), time zone and
    /// locale reads (`tz.*`, `locale.*`) and the markers of uncontrolled sources (`uncontrolled.thread|child|io`).
    fn from_op(op: &str) -> Option<Reason> {
        if op.starts_with("env.") {
            return Some(Reason::Env);
        }
        if op.starts_with("tz.") {
            return Some(Reason::Tz);
        }
        if op.starts_with("locale.") {
            return Some(Reason::Locale);
        }
        match op.strip_prefix(UNCONTROLLED_PREFIX) {
            Some("thread") => Some(Reason::Thread),
            Some("child") => Some(Reason::Child),
            Some("io") => Some(Reason::Io),
            Some(_) => Some(Reason::Other),
            None => None,
        }
    }

    fn of_event(e: &Event) -> Reason {
        Reason::from_op(&e.op).unwrap_or_else(|| Reason::from_source(e.source))
    }

    fn of_uncontrolled(kind: &str) -> Reason {
        match kind {
            "thread" => Reason::Thread,
            "child" => Reason::Child,
            "io" => Reason::Io,
            _ => Reason::Other,
        }
    }

    /// The reason a differing run input names (`meta.inputs` key).
    pub fn of_input(name: &str) -> Reason {
        if name.starts_with("env:") {
            return Reason::Env;
        }
        match name {
            "tz" => Reason::Tz,
            "locale" => Reason::Locale,
            "seed" | "shuffle" => Reason::Seed,
            "hashseed" => Reason::Hashseed,
            "clock" => Reason::Time,
            "network" => Reason::Net,
            "fs" => Reason::Fs,
            "urandom" => Reason::Entropy,
            "order" => Reason::Order,
            "runtime" | "runner" => Reason::Runtime,
            "env" => Reason::Env,
            _ => Reason::Config,
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
            Source::Sched => Reason::Sched,
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
    /// Every run recorded its inputs (`meta.inputs` in the trace header): without them identical fingerprints do
    /// not show that the runs had the same time zone, locale, environment, seed, ...
    #[serde(default)]
    pub inputs_recorded: bool,
    /// Tests with no uncontrolled source, the same inputs and the same events in every run (the only ones
    /// reported identical). Equal to `stable`.
    #[serde(default)]
    pub identical: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Report {
    pub labels: Vec<String>,
    pub order_digests: Vec<String>,
    pub complete: Vec<bool>,
    pub summary: Summary,
    pub tests: Vec<TestVerdict>,
    /// Run inputs that differ between run `run_a` (always 0) and the first run `run_b` that differs, in the order
    /// the verifier names them (the first one is the first divergent event of every test).
    #[serde(default)]
    pub input_differences: Vec<InputDifference>,
    /// Run inputs left out of the comparison at the user's request (`--ignore-env`).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub ignored_inputs: Vec<String>,
}

/// One run input (a key of the trace header's `meta.inputs`) that differs between two runs.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct InputDifference {
    pub name: String,
    pub run_a: usize,
    pub run_b: usize,
    pub value_a: Option<String>,
    pub value_b: Option<String>,
    pub reason: Reason,
}

/// Key under which a producer records its run inputs in the trace header's `meta`.
pub const INPUTS_KEY: &str = "inputs";

/// The run inputs of a trace (`meta.inputs`), values as strings; None when the producer recorded none.
pub fn run_inputs(t: &Trace) -> Option<BTreeMap<String, String>> {
    let obj = t.header.meta.get(INPUTS_KEY)?.as_object()?;
    Some(
        obj.iter()
            .map(|(k, v)| (k.clone(), v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string())))
            .collect(),
    )
}

/// The order in which differing inputs are named: what decides the most first (the interpreter and the runner,
/// the hash seed, the seed, the clock, the time zone, the locale, the environment, then the other controls).
fn input_rank(name: &str) -> (usize, &str) {
    const ORDER: [&str; 13] = [
        "runtime", "runner", "seed", "shuffle", "hashseed", "clock", "tz", "locale", "env", "network", "fs",
        "urandom", "bytecode",
    ];
    let base = name.split(':').next().unwrap_or(name);
    (ORDER.iter().position(|o| *o == base).unwrap_or(ORDER.len()), name)
}

/// Differing inputs between two runs (empty when equal, or when neither run recorded inputs).
pub fn diff_inputs(
    a: Option<&BTreeMap<String, String>>,
    b: Option<&BTreeMap<String, String>>,
    run_a: usize,
    run_b: usize,
) -> Vec<InputDifference> {
    let (a, b) = match (a, b) {
        (None, None) => return Vec::new(),
        (Some(a), Some(b)) => (a, b),
        (a, b) => {
            return vec![InputDifference {
                name: "inputs".into(),
                run_a,
                run_b,
                value_a: a.map(|_| "recorded".into()),
                value_b: b.map(|_| "recorded".into()),
                reason: Reason::Config,
            }]
        }
    };
    let names: BTreeSet<&String> = a.keys().chain(b.keys()).collect();
    let mut out: Vec<InputDifference> = names
        .into_iter()
        .filter(|k| a.get(*k) != b.get(*k))
        .map(|k| InputDifference {
            name: k.clone(),
            run_a,
            run_b,
            value_a: a.get(k).cloned(),
            value_b: b.get(k).cloned(),
            reason: Reason::of_input(k),
        })
        .collect();
    out.sort_by(|x, y| input_rank(&x.name).cmp(&input_rank(&y.name)));
    out
}

fn show_input(v: &Option<String>) -> String {
    match v {
        Some(v) => format!("{v:?}"),
        None => "<not recorded>".into(),
    }
}

fn describe_input(d: &InputDifference) -> String {
    match d.name.strip_prefix("env:") {
        Some(var) => format!(
            "environment variable {var} differs between the runs ({} vs {}; value digests): every test may read it \
             (C code and child processes read the environment without an event)",
            show_input(&d.value_a),
            show_input(&d.value_b)
        ),
        None => format!("run input {} differs: {} vs {}", d.name, show_input(&d.value_a), show_input(&d.value_b)),
    }
}

/// The divergence every test of two runs with different inputs gets: the first differing input, as an event that
/// happened before the test started (`input.<name>` @ `<run>`), the others listed in the description.
fn input_divergence(diffs: &[InputDifference]) -> Divergence {
    let d = &diffs[0];
    let mut description = format!("before the test started: {}", describe_input(d));
    if diffs.len() > 1 {
        let rest: Vec<&str> = diffs[1..].iter().map(|x| x.name.as_str()).collect();
        description.push_str(&format!("; also differ: {}", rest.join(", ")));
    }
    let ev = |v: &Option<String>| v.as_ref().map(|v| Event::new(Source::Other, format!("input.{}", d.name), "<run>", v.clone()));
    Divergence {
        run_a: d.run_a,
        run_b: d.run_b,
        index: None,
        window: None,
        event_a: ev(&d.value_a),
        event_b: ev(&d.value_b),
        reason: d.reason,
        description,
        lost_predecessors: Vec::new(),
    }
}

/// Serial runs only: the test ran after different tests (its in-process predecessors differ).
fn order_divergence(id: &str, a: &Predecessors, b: &Predecessors, run_a: usize, run_b: usize) -> Option<Divergence> {
    if a.parallel || b.parallel {
        return None; // a parallel run is compared by placement (docs/PARALLEL-PROOF-DESIGN.md 2.4)
    }
    let (pa, pb) = (a.before(id), b.before(id));
    if pa == pb {
        return None;
    }
    let k = pa.iter().zip(pb.iter()).position(|(x, y)| x != y).unwrap_or(pa.len().min(pb.len()));
    let at = |p: &[&str]| p.get(k).map(|s| s.to_string()).unwrap_or_else(|| "<none>".into());
    let list = |p: &[&str]| {
        let shown: Vec<&str> = p.iter().rev().take(5).rev().copied().collect();
        let more = if p.len() > 5 { format!("{} earlier, then ", p.len() - 5) } else { String::new() };
        format!("[{more}{}]", shown.join(", "))
    };
    Some(Divergence {
        run_a,
        run_b,
        index: None,
        window: None,
        event_a: Some(Event::new(Source::Other, "order.predecessor", "<run>", at(pa))),
        event_b: Some(Event::new(Source::Other, "order.predecessor", "<run>", at(pb))),
        reason: Reason::Order,
        description: format!(
            "before the test started: it ran after different tests in its process: {} vs {} (first difference at \
             position {k}: {} vs {})",
            list(pa),
            list(pb),
            at(pa),
            at(pb)
        ),
        lost_predecessors: Vec::new(),
    })
}

/// A test with identical fingerprints that used a source Level 0 does not control: never reported covered.
fn uncontrolled_divergence(r: &TestRecord, run: usize) -> Option<Divergence> {
    r.uncontrolled.first()?;
    // the first one the test used (event order), else (past the stored events) the first by name
    let pos = r.events.iter().position(|e| e.op.starts_with(UNCONTROLLED_PREFIX));
    let ev = pos.map(|i| r.events[i].clone());
    let kind = ev
        .as_ref()
        .and_then(|e| e.op.strip_prefix(UNCONTROLLED_PREFIX))
        .map(str::to_string)
        .unwrap_or_else(|| r.uncontrolled[0].clone());
    let what = match kind.as_str() {
        "thread" => "started a thread: thread scheduling",
        "child" => "started a child process: what the child does",
        "io" => "waited for I/O readiness: the order in which ready I/O is delivered",
        _ => "used an uncontrolled source: it",
    };
    let at = ev.as_ref().map(|e| format!(" ({} @ {})", e.op, e.site)).unwrap_or_default();
    Some(Divergence {
        run_a: run,
        run_b: run,
        index: pos.map(|i| i as u64),
        window: None,
        event_a: ev.clone(),
        event_b: ev,
        reason: Reason::of_uncontrolled(&kind),
        description: format!(
            "the test {what}{at} is not controlled by this release, so identical fingerprints are no evidence of \
             an identical execution (uncontrolled: {})",
            r.uncontrolled.join(", ")
        ),
        lost_predecessors: Vec::new(),
    })
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
        for (pos, r) in t.tests.iter().enumerate() {
            let w = r.worker.as_deref().unwrap_or("");
            // serial: the executed order is the order of the trace lines
            let at = if parallel { r.worker_index.unwrap_or(r.index) } else { pos as u64 };
            lists.entry(w).or_default().push((at, r.nodeid.as_str()));
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
                Reason::of_event(eb)
            } else {
                Reason::of_event(ea)
            }
        }
        (Some(e), None) | (None, Some(e)) => {
            if e.thread != 0 {
                Reason::Thread
            } else {
                Reason::of_event(e)
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
        (Some(ea), Some(eb)) if ea.source == Source::Sched && eb.source == Source::Sched => format!(
            "event #{i}: first diverging scheduling choice: {} {} @ {}  <>  {} {} @ {}",
            ea.op, ea.value, ea.site, eb.op, eb.value, eb.site
        ),
        (Some(ea), Some(eb)) if ea.op.starts_with("env.") && ea.op == eb.op && ea.site == eb.site => format!(
            "event #{i}: {} @ {} read the environment differently: {} vs {} (name=value digest)",
            ea.op, ea.site, ea.value, eb.value
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
    let inputs: Vec<Option<BTreeMap<String, String>>> = traces.iter().map(run_inputs).collect();
    // the first run whose inputs differ from run 0's: its differences are every test's first divergent event
    let input_differences: Vec<InputDifference> =
        (1..n).map(|j| diff_inputs(inputs[0].as_ref(), inputs[j].as_ref(), 0, j)).find(|d| !d.is_empty()).unwrap_or_default();
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

    let mut summary = Summary { runs: n, inputs_recorded: n > 0 && inputs.iter().all(|i| i.is_some()), ..Default::default() };
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
        } else if !input_differences.is_empty() {
            // the runs did not have the same inputs: no test is identical, whatever its fingerprint. When the test
            // itself read a differing environment variable, that read (an event with its site) is named instead.
            let j = input_differences[0].run_b;
            let read = match (recs[0], recs[j]) {
                (Some(a), Some(b)) if a.fingerprint != b.fingerprint => diff_records(a, b, 0, j)
                    .filter(|d| d.reason == Reason::Env && input_differences.iter().all(|x| x.reason == Reason::Env)),
                _ => None,
            };
            match read {
                Some(mut d) => {
                    let names: Vec<&str> = input_differences.iter().map(|x| x.name.as_str()).collect();
                    d.description = format!("{} (run inputs that differ: {})", d.description, names.join(", "));
                    (Status::Diverged, Some(d))
                }
                None => (Status::Diverged, Some(input_divergence(&input_differences))),
            }
        } else if let Some(d) = (1..n).find_map(|j| order_divergence(id, &preds[0], &preds[j], 0, j)) {
            (Status::Diverged, Some(d))
        } else if distinct.len() <= 1 {
            match recs.iter().flatten().find(|r| !r.uncontrolled.is_empty()) {
                Some(r) => (Status::Diverged, uncontrolled_divergence(r, 0)),
                None => (Status::Stable, None),
            }
        } else {
            let a = recs[0].unwrap();
            let j = recs.iter().position(|r| r.unwrap().fingerprint != a.fingerprint).unwrap();
            let mut d = diff_records(a, recs[j].unwrap(), 0, j);
            if let Some(d) = d.as_mut() {
                placement(d, id, &preds[0], &preds[j]);
                // same observed events, different outcome, and the test used an uncontrolled source: that source
                // is the named cause, not "a source Level 0 does not observe"
                if d.reason == Reason::OutcomeOnly {
                    if let Some(k) = recs.iter().flatten().find_map(|r| r.uncontrolled.first()) {
                        d.reason = Reason::of_uncontrolled(k);
                        d.description = format!("{} (the test used an uncontrolled source: {k})", d.description);
                    }
                }
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
    summary.identical = summary.stable;
    let order_digests: Vec<String> = traces.iter().map(|t| order_digest(&t.executed_order())).collect();
    summary.order_identical = order_digests.windows(2).all(|w| w[0] == w[1]);
    Report {
        labels: labels.to_vec(),
        order_digests,
        complete: traces.iter().map(|t| t.is_complete()).collect(),
        summary,
        tests,
        input_differences,
        ignored_inputs: Vec::new(),
    }
}

/// `verify_paths` with run inputs the user declared irrelevant removed before the comparison: `ignore_env` holds
/// environment variable names, or prefixes ending in `*`. The report lists what was ignored.
pub fn verify_paths_ignoring<P: AsRef<Path>>(paths: &[P], ignore_env: &[String]) -> Result<Report, TraceError> {
    let mut traces = Vec::new();
    let mut labels = Vec::new();
    for p in paths {
        traces.push(read_trace(p.as_ref())?);
        labels.push(p.as_ref().display().to_string());
    }
    check_compatible(&traces, &labels)?;
    let matches = |var: &str| {
        ignore_env.iter().any(|g| match g.strip_suffix('*') {
            Some(prefix) => var.starts_with(prefix),
            None => var == g,
        })
    };
    let mut ignored: BTreeSet<String> = BTreeSet::new();
    for t in traces.iter_mut() {
        if let Some(obj) = t.header.meta.get_mut(INPUTS_KEY).and_then(|v| v.as_object_mut()) {
            let drop: Vec<String> =
                obj.keys().filter(|k| k.strip_prefix("env:").is_some_and(&matches)).cloned().collect();
            for k in drop {
                obj.remove(&k);
                ignored.insert(k);
            }
        }
    }
    let mut r = verify(&traces, &labels);
    r.ignored_inputs = ignored.into_iter().collect();
    Ok(r)
}

pub fn verify_paths<P: AsRef<Path>>(paths: &[P]) -> Result<Report, TraceError> {
    let mut traces = Vec::new();
    let mut labels = Vec::new();
    for p in paths {
        traces.push(read_trace(p.as_ref())?);
        labels.push(p.as_ref().display().to_string());
    }
    check_compatible(&traces, &labels)?;
    Ok(verify(&traces, &labels))
}

/// Traces with different event encodings are never compared: their
/// fingerprints differ by construction, which is not a divergence.
pub fn check_compatible(traces: &[Trace], labels: &[String]) -> Result<(), TraceError> {
    let Some(first) = traces.first() else { return Ok(()) };
    let base = first.header.encoding;
    for (t, l) in traces.iter().zip(labels).skip(1) {
        if t.header.encoding != base {
            return Err(TraceError::Incompatible(format!(
                "{} uses event encoding {} but {} uses {}; re-run both with the same detpy version",
                labels[0], base, l, t.header.encoding
            )));
        }
    }
    Ok(())
}

/// What to do for each reason (audit G-2210, G-2019): printed once per reason present.
pub const HINTS: &[(&str, &str)] = &[
    ("entropy", "the test reads OS entropy (os.urandom, uuid4, secrets), observed but not controlled by --det; add \
                 --det-urandom to draw it from the seeded stream (not for tests of cryptography)"),
    ("env", "an environment variable differs between the runs; give both runs the same environment, or declare it \
             irrelevant with --ignore-env NAME"),
    ("tz", "the runs used different time zones; keep the default --det-tz=UTC (or the same zone in both runs)"),
    ("locale", "the runs used different locales; keep the default --det-locale (or the same locale in both runs)"),
    ("order", "the test ran after different tests: an order dependency; `fenvix repro TEST` names the tests it \
               depends on"),
    ("thread", "threads are not scheduled deterministically by this release: the test cannot be proven identical"),
    ("child", "a child process is not controlled by this release: the test cannot be proven identical"),
    ("io", "the order of ready I/O is not controlled by this release: the test cannot be proven identical"),
    ("outcome-only", "same observed events, different outcome: the cause is outside what is observed (C code, \
                      memory addresses, files or services outside the test); `fenvix repro TEST` searches for it"),
];

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
    let verdict = if s.tests == 0 {
        "NOTHING VERIFIED: no test ran in these runs".to_string()
    } else if s.diverged == 0 && s.missing == 0 {
        format!("IDENTICAL: all {} tests ran with the same inputs and observed the same events", s.tests)
    } else {
        format!(
            "DIVERGENT: {} of {} tests are not identical (the first divergent event of each is named below)",
            s.diverged + s.missing,
            s.tests
        )
    };
    let _ = writeln!(out, "verdict: {verdict}");
    if !s.inputs_recorded {
        let _ = writeln!(
            out,
            "run inputs: NOT RECORDED in every trace (time zone, locale, environment, seed, ... cannot be compared; \
             fingerprints alone do not prove the runs had the same inputs)"
        );
    } else if report.input_differences.is_empty() {
        let _ = writeln!(out, "run inputs: identical in every run");
    } else {
        let d = &report.input_differences;
        let _ = writeln!(out, "run inputs: DIFFER between run {} and run {}:", d[0].run_a, d[0].run_b);
        for x in d.iter().take(20) {
            let _ = writeln!(out, "    {}: {} vs {}", x.name, show_input(&x.value_a), show_input(&x.value_b));
        }
        if d.len() > 20 {
            let _ = writeln!(out, "    ... and {} more", d.len() - 20);
        }
    }
    if !report.ignored_inputs.is_empty() {
        let _ = writeln!(out, "ignored at your request (--ignore-env): {}", report.ignored_inputs.join(", "));
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
        for (k, hint) in HINTS {
            if s.reasons.contains_key(*k) {
                let _ = writeln!(out, "hint [{k}]: {hint}");
            }
        }
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
                if d.run_a == d.run_b && t.status != Status::Missing {
                    let _ = writeln!(out, "    every run: {}", d.description);
                } else {
                    let _ = writeln!(out, "    runs {} vs {}: {}", d.run_a, d.run_b, d.description);
                }
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
    fn sched_divergence_is_named() {
        let a = Event::new(Source::Sched, "sched.io", "tests/t.py:7", "0/2:tests/t.py:7#1");
        let b = Event::new(Source::Sched, "sched.io", "tests/t.py:7", "1/2:tests/t.py:7#2");
        assert_eq!(classify(Some(&a), Some(&b)), Reason::Sched);
        let d = describe(4, Some(&a), Some(&b));
        assert!(d.starts_with("event #4: first diverging scheduling choice: sched.io 0/2:"), "{d}");
        assert!(d.contains("1/2:tests/t.py:7#2"), "{d}");
    }

    #[test]
    fn different_encodings_are_not_compared() {
        let mut a = trace(vec![]);
        let b = trace(vec![]);
        a.header.encoding = 1;
        let labels = vec!["old.jsonl".to_string(), "new.jsonl".to_string()];
        let err = check_compatible(&[a, b], &labels).unwrap_err();
        assert!(matches!(err, TraceError::Incompatible(_)));
        assert!(err.to_string().contains("old.jsonl uses event encoding 1 but new.jsonl uses 2"), "{err}");
        assert!(check_compatible(&[trace(vec![]), trace(vec![])], &labels).is_ok());
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
        // y ran after x in run 0 and first in run 1: not identical, the order is its first divergent event
        assert_eq!(r.summary.stable, 0);
        assert_eq!(r.tests[1].divergence.as_ref().unwrap().reason, Reason::Order);
        assert!(!r.summary.order_identical);
        let text = render_text(&r, true);
        assert!(text.contains("MISSING"), "{text}");
        assert!(text.contains("NOT-COVERED y  [order]"), "{text}");
        assert!(text.contains("verdict: DIVERGENT"), "{text}");
    }

    fn with_inputs(mut t: Trace, inputs: &[(&str, &str)]) -> Trace {
        let m: serde_json::Map<String, serde_json::Value> =
            inputs.iter().map(|(k, v)| (k.to_string(), serde_json::Value::String(v.to_string()))).collect();
        t.header.meta = serde_json::json!({ "inputs": m });
        t
    }

    const BASE: [(&str, &str); 10] = [
        ("runtime", "CPython 3.13.0 linux x86_64"),
        ("runner", "pytest 9.0"),
        ("hashseed", "0"),
        ("seed", "0"),
        ("clock", "virtual epoch=1 tick=1000"),
        ("tz", "UTC (pinned)"),
        ("locale", "C.UTF-8 (pinned)"),
        ("env:HOME", "aaaa"),
        ("network", "closed"),
        ("fs", "sorted"),
    ];

    /// The family of G-0139 / G-0180 / G-0041 / G-0054: two runs that differ only in one recorded input are
    /// divergent, with that input named as the first divergent event, whatever the fingerprints say.
    #[test]
    fn every_recorded_input_is_compared_and_named() {
        let cases: [(&str, &str, Reason); 11] = [
            ("runtime", "CPython 3.12.0 linux x86_64", Reason::Runtime),
            ("hashseed", "7", Reason::Hashseed),
            ("seed", "3", Reason::Seed),
            ("clock", "virtual epoch=2 tick=1000", Reason::Time),
            ("tz", "Asia/Tokyo (not pinned)", Reason::Tz),
            ("locale", "de_DE.UTF-8 (pinned)", Reason::Locale),
            ("env:HOME", "bbbb", Reason::Env),
            ("env:MY_FLAG", "cccc", Reason::Env),
            ("network", "record", Reason::Net),
            ("fs", "real", Reason::Fs),
            ("urandom", "controlled", Reason::Entropy),
        ];
        for (name, value, reason) in cases {
            let a = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE);
            let mut changed: Vec<(&str, &str)> = BASE.iter().filter(|(k, _)| *k != name).copied().collect();
            changed.push((name, value));
            let b = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &changed);
            let r = verify(&[a, b], &["a".into(), "b".into()]);
            assert_eq!(r.summary.stable, 0, "{name}: identical although {name} differs");
            assert_eq!(r.summary.diverged, 1, "{name}");
            let d = r.tests[0].divergence.as_ref().unwrap();
            assert_eq!(d.reason, reason, "{name}");
            assert_eq!(d.event_a.as_ref().map(|e| e.op.clone()).or(d.event_b.as_ref().map(|e| e.op.clone())),
                       Some(format!("input.{name}")), "{name}");
            assert_eq!(r.input_differences[0].name, name);
            let text = render_text(&r, false);
            assert!(text.contains("run inputs: DIFFER"), "{text}");
            assert!(text.contains(&format!("[{}]", reason.as_str())), "{text}");
        }
        // same inputs: identical
        let a = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE);
        let b = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE);
        let r = verify(&[a, b], &[]);
        assert_eq!((r.summary.stable, r.summary.identical), (1, 1));
        assert!(r.summary.inputs_recorded);
        assert!(render_text(&r, false).contains("verdict: IDENTICAL"));
    }

    #[test]
    fn first_named_input_follows_the_rank_and_lists_the_others() {
        let a = with_inputs(trace(vec![rec("x", &[], "passed", 10)]), &[("tz", "UTC"), ("env:A", "1"), ("seed", "0")]);
        let b = with_inputs(trace(vec![rec("x", &[], "passed", 10)]), &[("tz", "Asia/Tokyo"), ("env:A", "2"), ("seed", "1")]);
        let r = verify(&[a, b], &[]);
        let d = r.tests[0].divergence.as_ref().unwrap();
        assert_eq!(d.reason, Reason::Seed);
        assert!(d.description.contains("also differ: tz, env:A"), "{}", d.description);
    }

    #[test]
    fn inputs_missing_in_one_run_is_a_divergence_and_in_both_is_reported() {
        let a = with_inputs(trace(vec![rec("x", &[], "passed", 10)]), &BASE);
        let b = trace(vec![rec("x", &[], "passed", 10)]);
        let r = verify(&[a, b], &[]);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Config);
        let r = verify(&[trace(vec![rec("x", &[], "passed", 10)]), trace(vec![rec("x", &[], "passed", 10)])], &[]);
        assert!(!r.summary.inputs_recorded);
        assert!(render_text(&r, false).contains("run inputs: NOT RECORDED"));
    }

    #[test]
    fn uncontrolled_sources_are_never_identical() {
        for (kind, reason) in [("thread", Reason::Thread), ("child", Reason::Child), ("io", Reason::Io)] {
            let marker = Event::new(Source::Other, format!("uncontrolled.{kind}"), "t.py:3", "x");
            let a = trace(vec![rec("x", &[t("1"), marker.clone()], "passed", 10)]);
            let b = trace(vec![rec("x", &[t("1"), marker.clone()], "passed", 10)]);
            assert_eq!(a.tests[0].uncontrolled, vec![kind.to_string()]);
            let r = verify(&[a, b], &[]);
            assert_eq!(r.summary.stable, 0, "{kind}");
            let d = r.tests[0].divergence.as_ref().unwrap();
            assert_eq!((d.reason, d.index), (reason, Some(1)), "{kind}");
            assert!(d.description.contains("not controlled"), "{}", d.description);
            // a marker past the stored events still counts
            let mut evs: Vec<Event> = (0..10).map(|i| t(&i.to_string())).collect();
            evs.push(marker);
            let a = trace(vec![rec("x", &evs, "passed", 3)]);
            let b = trace(vec![rec("x", &evs, "passed", 3)]);
            assert!(a.tests[0].truncated);
            assert_eq!(verify(&[a, b], &[]).tests[0].divergence.as_ref().unwrap().reason, reason);
        }
        // different outcomes with a thread: the thread is named, not "a source Level 0 does not observe"
        let m = Event::new(Source::Other, "uncontrolled.thread", "t.py:3", "x");
        let a = trace(vec![rec("x", &[m.clone()], "passed", 10)]);
        let b = trace(vec![rec("x", &[m], "failed", 10)]);
        assert_eq!(verify(&[a, b], &[]).tests[0].divergence.as_ref().unwrap().reason, Reason::Thread);
    }

    #[test]
    fn env_tz_locale_reads_are_named_by_their_op() {
        let e = |v: &str| Event::new(Source::Other, "env.get", "t.py:2", v);
        let a = trace(vec![rec("x", &[e("MY_FLAG=aa")], "passed", 10)]);
        let b = trace(vec![rec("x", &[e("MY_FLAG=bb")], "failed", 10)]);
        let d = verify(&[a, b], &[]).tests[0].divergence.clone().unwrap();
        assert_eq!(d.reason, Reason::Env);
        assert!(d.description.contains("MY_FLAG=aa vs MY_FLAG=bb"), "{}", d.description);
        assert_eq!(Reason::from_op("tz.localtime"), Some(Reason::Tz));
        assert_eq!(Reason::from_op("locale.setlocale"), Some(Reason::Locale));
    }

    #[test]
    fn empty_runs_verify_nothing() {
        let r = verify(&[trace(vec![]), trace(vec![])], &[]);
        assert!(render_text(&r, false).contains("verdict: NOTHING VERIFIED"));
    }

    #[test]
    fn same_order_same_events_is_identical_and_order_change_is_named() {
        let a = trace(vec![rec("p", &[], "passed", 10), rec("v", &[], "passed", 10)]);
        let b = trace(vec![rec("v", &[], "passed", 10), rec("p", &[], "passed", 10)]);
        let r = verify(&[a.clone(), a.clone()], &[]);
        assert_eq!(r.summary.stable, 2);
        let r = verify(&[a, b], &[]);
        assert_eq!(r.summary.stable, 0);
        for v in &r.tests {
            assert_eq!(v.divergence.as_ref().unwrap().reason, Reason::Order);
        }
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
