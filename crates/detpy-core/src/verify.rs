//! Cross-run verifier.
//!
//! Given N traces of the same suite, the verifier decides for every test
//! whether Level 0 made it reproducible: all runs must produce the same
//! fingerprint. When fingerprints differ the test is reported as
//! *not covered by Level 0*, together with the first point where two runs
//! diverge and a classification of the cause.

use crate::event::{Event, Source};
use crate::fingerprint::{TestRecord, UNCONTROLLED_PREFIX};
use crate::record_source::{FileTrace, MemTrace, RecordSource, SlimRecord};
use crate::provable::{self, Verdict};
use crate::trace::{order_digest, Footer, Header, Trace, TraceError};
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
    /// The test used a native network client (grpcio, pycurl, libpq, ...): its sockets are outside the closed
    /// network and the cassette.
    Native,
    /// One run is a parallel run under a plan (merged trace), the other serial, and the test ran in its worker
    /// without some of its serial in-process predecessors (`lost_predecessors`): it observed process state that
    /// depends on where it ran (docs/PARALLEL-PROOF-DESIGN.md 2.4). Entropy and thread divergences keep their class.
    Placement,
    /// The installed dependencies the run loaded differ (`inputs.deps`, docs/VERIFY-CONTRACT.md).
    Deps,
    /// The project's own source the run loaded differs (`inputs.code`): an edit, committed or not.
    Code,
    /// The run declared no wide sensor, or one this core does not understand: nothing says what the test did, so
    /// it cannot be shown identical (the general rule, [`crate::provable`]).
    Sensor,
    /// The sensor saw the test call something the accounting table does not account for: a standard-library
    /// callable with no rule, a module nobody wrote a rule for, an audit event with no rule.
    Api,
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
            Reason::Native => "native",
            Reason::Deps => "deps",
            Reason::Code => "code",
            Reason::Sensor => "sensor",
            Reason::Api => "api",
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
            Some("native") => Some(Reason::Native),
            Some("net") => Some(Reason::Net),
            Some("env") => Some(Reason::Env),
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
            "native" => Reason::Native,
            "net" => Reason::Net,
            "env" => Reason::Env,
            "file" => Reason::Fs,
            // the general rule's classes ([`crate::provable`])
            "sensor" => Reason::Sensor,
            "runtime" => Reason::Runtime,
            "api" | "module" | "audit" => Reason::Api,
            _ => Reason::Other,
        }
    }

    /// The reason a differing run input names (`meta.inputs` key).
    pub fn of_input(name: &str) -> Reason {
        if name.starts_with("env:") {
            return Reason::Env;
        }
        if name.starts_with(FILE_INPUT_PREFIX) {
            return Reason::Fs;
        }
        match name {
            "tz" => Reason::Tz,
            "locale" => Reason::Locale,
            "seed" | "shuffle" => Reason::Seed,
            "hashseed" => Reason::Hashseed,
            "clock" => Reason::Time,
            "network" => Reason::Net,
            "fs" => Reason::Fs,
            // the entropy control ("urandom" in traces written before it was named after the control)
            "entropy" | "urandom" => Reason::Entropy,
            "order" => Reason::Order,
            "runtime" | "runner" => Reason::Runtime,
            "deps" => Reason::Deps,
            "code" => Reason::Code,
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
    /// The runs differed only in an environment variable the test read (design A, 2026-11-20): the test is not
    /// identical, and not unstable either; the variable is named.
    InputDiffers,
    /// Same inputs and events, but the test used a source that is not controlled (a thread, a child process, a
    /// CI-volatile or proxy variable, ...: an `uncontrolled.*` mark, or `not_proven_outside_tests`): it cannot be
    /// shown identical, and nothing shows it differed (review R-055 D1, docs/VERIFY-CONTRACT.md section 4).
    NotProven,
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
    /// Tests that read an environment variable whose value differs between the runs, and are otherwise identical.
    #[serde(default)]
    pub input_differs: usize,
    /// Tests that used an uncontrolled source and are otherwise identical (`Status::NotProven`).
    #[serde(default)]
    pub not_proven: usize,
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
    /// Environment variables whose values differ between the runs but that no test read: not compared (a test that
    /// reads one of them is reported `input-differs`).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub env_not_read: Vec<String>,
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

/// The run inputs of a trace (`meta.inputs`), values as strings; None when the producer recorded none (no
/// `inputs`, or an empty one: R-051 R1, an empty object is no record of the inputs). An input named after an older
/// spelling is read under its current name (`urandom` is `entropy`, R-051 R2).
pub fn run_inputs(t: &Trace) -> Option<BTreeMap<String, String>> {
    run_inputs_of(&t.header, t.footer.as_ref())
}

fn run_inputs_of(header: &Header, footer: Option<&Footer>) -> Option<BTreeMap<String, String>> {
    let obj = header.meta.get(INPUTS_KEY)?.as_object()?;
    if obj.is_empty() {
        return None;
    }
    let one = |(k, v): (&String, &serde_json::Value)| {
        let k = if k == "urandom" { "entropy".to_string() } else { k.clone() };
        (k, v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string()))
    };
    let mut m: BTreeMap<String, String> = obj.iter().map(one).collect();
    // what the run read after the header was written, outside any test (the footer, R-055 V12): its inputs too
    if let Some(late) = late(footer).and_then(|l| l.get(INPUTS_KEY)).and_then(|v| v.as_object()) {
        m.extend(late.iter().map(one));
    }
    Some(m)
}

/// The trace footer's `late` object: the header fields of docs/VERIFY-CONTRACT.md section 1 a shell could only know
/// after the header was written (Python: reads at session end, R-055 V12). Same names as in the header.
fn late(footer: Option<&Footer>) -> Option<&serde_json::Value> {
    footer.and_then(|f| f.late.as_ref())
}

/// The entries of a contract array field (`files_read_outside_tests`, `env_read_outside_tests`,
/// `not_proven_outside_tests`): the header's, then the footer's `late` ones.
fn meta_array<'a>(
    header: &'a Header,
    footer: Option<&'a Footer>,
    key: &str,
) -> impl Iterator<Item = &'a serde_json::Value> {
    [header.meta.get(key), late(footer).and_then(|l| l.get(key))]
        .into_iter()
        .flatten()
        .filter_map(|v| v.as_array())
        .flatten()
}

/// The order in which differing inputs are named: what decides the most first (the interpreter and the runner,
/// the hash seed, the seed, the clock, the time zone, the locale, the environment, then the other controls).
fn input_rank(name: &str) -> (usize, &str) {
    const ORDER: [&str; 14] = [
        "runtime", "runner", "seed", "shuffle", "hashseed", "clock", "tz", "locale", "env", "network", "fs",
        "entropy", "urandom", "bytecode",
    ];
    let base = name.split(':').next().unwrap_or(name);
    (ORDER.iter().position(|o| *o == base).unwrap_or(ORDER.len()), name)
}

/// Key prefix of the synthetic run inputs made from `meta.files_read_outside_tests` (docs/VERIFY-CONTRACT.md).
pub const FILE_INPUT_PREFIX: &str = "file:";
/// A hash seed nobody fixed: two runs with it never had the same input (review R-055 V13).
const RANDOM_HASHSEED: &str = "<random>";

/// The run inputs of a trace for comparison: `meta.inputs` plus one `file:<path>` input per file read outside any
/// test (`meta.files_read_outside_tests`, its digests joined in order). None when the trace records no inputs.
/// `scoped`: entries that carry the test file they were read for (`file`) are left out (P1 B1: [`scoped_inputs`]).
fn compared_inputs(header: &Header, footer: Option<&Footer>, scoped: bool) -> Option<BTreeMap<String, String>> {
    let mut m = run_inputs_of(header, footer)?;
    let has = header.meta.get("files_read_outside_tests").is_some()
        || late(footer).is_some_and(|l| l.get("files_read_outside_tests").is_some());
    if has {
        let mut by: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for f in meta_array(header, footer, "files_read_outside_tests") {
            if scoped && f.get("file").and_then(|v| v.as_str()).is_some() {
                continue;
            }
            let (Some(p), Some(d)) = (f.get("path").and_then(|v| v.as_str()), f.get("digest").and_then(|v| v.as_str())) else { continue };
            by.entry(p.to_string()).or_default().push(d.to_string());
        }
        for (p, mut ds) in by {
            ds.sort();
            ds.dedup();
            m.insert(format!("{FILE_INPUT_PREFIX}{p}"), ds.join(","));
        }
        m.insert("files_read_outside_tests".into(), "recorded".into());
    }
    Some(m)
}

/// Whether the files read outside any test are compared per test file (P1 B1, docs/VERIFY-CONTRACT.md section 1):
/// every run declares `files_outside_scope: "file"` (its runner isolates test files from one another, so what one
/// file's module scope or hooks read can reach that file's tests only).
fn files_scoped<S: RecordSource>(traces: &[S]) -> bool {
    !traces.is_empty()
        && traces.iter().all(|t| t.header().meta.get("files_outside_scope").and_then(|v| v.as_str()) == Some("file"))
}

/// P1 B1: the entries of `files_read_outside_tests` that carry the test file they were read for, as `file:<path>`
/// inputs per test file (the file path, without a Vitest project).
fn scoped_inputs(header: &Header, footer: Option<&Footer>) -> BTreeMap<String, BTreeMap<String, String>> {
    let mut by: BTreeMap<String, BTreeMap<String, Vec<String>>> = BTreeMap::new();
    for f in meta_array(header, footer, "files_read_outside_tests") {
        let (Some(p), Some(d), Some(file)) = (
            f.get("path").and_then(|v| v.as_str()),
            f.get("digest").and_then(|v| v.as_str()),
            f.get("file").and_then(|v| v.as_str()),
        ) else {
            continue;
        };
        by.entry(file.to_string()).or_default().entry(format!("{FILE_INPUT_PREFIX}{p}")).or_default().push(d.to_string());
    }
    by.into_iter()
        .map(|(file, m)| {
            let m = m
                .into_iter()
                .map(|(k, mut ds)| {
                    ds.sort();
                    ds.dedup();
                    (k, ds.join(","))
                })
                .collect();
            (file, m)
        })
        .collect()
}

/// The test file of a test id: before the first `::`, without a Vitest project (`@@<name>`).
fn test_file(id: &str) -> &str {
    let head = id.split("::").next().unwrap_or(id);
    head.split("@@").next().unwrap_or(head)
}

/// P1 B1: the test's own file read something outside any test that differs between run 0 and another run.
fn scoped_divergence(id: &str, scoped: &[BTreeMap<String, BTreeMap<String, String>>]) -> Option<Divergence> {
    let empty = BTreeMap::new();
    let file = test_file(id);
    let base = scoped.first()?.get(file).unwrap_or(&empty);
    (1..scoped.len()).find_map(|j| {
        let diffs = diff_inputs(Some(base), Some(scoped[j].get(file).unwrap_or(&empty)), 0, j);
        (!diffs.is_empty()).then(|| {
            let mut d = input_divergence(&diffs);
            d.description = format!("{} (read outside any test by the test's own file {file})", d.description);
            d
        })
    })
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
        .filter(|k| a.get(*k) != b.get(*k) || (k.as_str() == "hashseed" && a.get(*k).map(String::as_str) == Some(RANDOM_HASHSEED)))
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

/// The `not_proven_outside_tests` entries of the runs that still make every test NOT PROVEN in this comparison,
/// sorted and deduplicated.
///
/// P1 A1 (docs/DESIGN-P1.md section A, docs/VERIFY-CONTRACT.md section 1): the Node shell writes an uncontrolled
/// variable read outside any test as `env:<NAME>=<digest of NAME=value>` (`*` for an enumeration). Its value is no
/// run input (it differs between machines, so the cache never reuses such a test), but two runs that saw the same
/// value did not differ through it: when every run has entries for `<NAME>` and they all carry the same set of
/// digests, those entries are discharged for this comparison. A different value, a read in some runs only, an entry
/// without a digest (older traces, the Python shell) and every non-`env` entry stay: every test is NOT PROVEN.
fn undischarged_outside<S: RecordSource>(traces: &[S]) -> Vec<String> {
    let per_run: Vec<BTreeSet<String>> = traces
        .iter()
        .map(|t| meta_array(t.header(), t.footer(), "not_proven_outside_tests").filter_map(|v| v.as_str().map(str::to_string)).collect())
        .collect();
    // name -> digests, per run; None when the run has an `env:<NAME>` entry without a digest
    let digests = |run: &BTreeSet<String>, name: &str| -> Option<BTreeSet<String>> {
        let mut out = BTreeSet::new();
        for e in run {
            let Some(rest) = e.strip_prefix("env:") else { continue };
            match rest.split_once('=') {
                Some((n, d)) if n == name => {
                    out.insert(d.to_string());
                }
                None if rest == name => return None,
                _ => {}
            }
        }
        Some(out)
    };
    let names: BTreeSet<String> = per_run
        .iter()
        .flatten()
        .filter_map(|e| e.strip_prefix("env:").and_then(|r| r.split_once('=')).map(|(n, _)| n.to_string()))
        .collect();
    let discharged: BTreeSet<String> = names
        .into_iter()
        .filter(|name| {
            let sets: Vec<Option<BTreeSet<String>>> = per_run.iter().map(|r| digests(r, name)).collect();
            // at least two runs: a value is discharged only when another run saw the same one (one run has nothing
            // to compare it with: review 2026-11-24)
            traces.len() > 1
                && sets.iter().all(|s| s.as_ref().is_some_and(|s| !s.is_empty()))
                && sets.windows(2).all(|w| w[0] == w[1])
        })
        .collect();
    let all: BTreeSet<String> = per_run.into_iter().flatten().collect();
    all.into_iter()
        .filter(|e| {
            !e.strip_prefix("env:").and_then(|r| r.split_once('=')).is_some_and(|(n, _)| discharged.contains(n))
        })
        .collect()
}

/// Every test of runs that read an uncontrolled source outside any test (`not_proven_outside_tests`).
fn outside_not_proven(entries: &[String]) -> Divergence {
    let kind = entries[0].split(':').next().unwrap_or("");
    Divergence {
        run_a: 0,
        run_b: 0,
        index: None,
        window: None,
        event_a: None,
        event_b: None,
        reason: Reason::of_uncontrolled(kind),
        description: format!(
            "outside any test the run read sources that are not controlled ({}): every test may have observed them, \
             so identical fingerprints are no evidence of an identical execution",
            entries.join(", ")
        ),
        lost_predecessors: Vec::new(),
    }
}

/// A test with identical fingerprints that used a source Level 0 does not control: never reported covered.
/// Turn a [`Verdict::NotProven`] into the divergence the report shows.
///
/// The existing wordings are kept where the gap is one of the channels that already had a rule (a thread, a child
/// process, a volatile variable, something read outside the tests), so the messages the reports and the exam
/// depend on do not change. Only the classes the general rule adds get a new sentence.
fn not_proven_divergence(
    r: &SlimRecord,
    run: usize,
    kind: &str,
    detail: &str,
    outside: &[String],
) -> Divergence {
    // a channel that already had a rule: its own sentence, naming the site the test used it at
    if !r.uncontrolled.is_empty() && r.uncontrolled.iter().any(|k| k.split(':').next() == Some(kind) || k == kind) {
        if let Some(d) = uncontrolled_divergence(r, run) {
            return d;
        }
    }
    if !outside.is_empty() && outside.iter().any(|e| e.split(':').next() == Some(kind)) && r.unaccounted.is_empty() {
        return outside_not_proven(outside);
    }
    let what = match kind {
        "sensor" => "this run cannot say what the test did",
        "runtime" => "this runtime was never audited against the engine's accounting table",
        "native" => "the test loaded a native extension whose own C code the engine has not reasoned about",
        "module" => "the test used a module the engine has no rule for",
        "audit" => "the test caused an operation the engine has no rule for",
        _ => "the test called something the engine cannot account for",
    };
    Divergence {
        run_a: run,
        run_b: run,
        index: None,
        window: None,
        event_a: None,
        event_b: None,
        reason: Reason::of_uncontrolled(kind),
        description: format!(
            "{what}: {detail}. Identical fingerprints are no evidence of an identical execution, so the verdict is \
             NOT PROVEN and the test must be rerun"
        ),
        lost_predecessors: Vec::new(),
    }
}

fn uncontrolled_divergence(r: &SlimRecord, run: usize) -> Option<Divergence> {
    r.uncontrolled.first()?;
    // the first one the test used (event order), else (past the stored events) the first by name
    let pos = r.first_uncontrolled.as_ref().map(|(i, _)| *i);
    let ev = r.first_uncontrolled.as_ref().map(|(_, e)| e.clone());
    let kind = ev
        .as_ref()
        .and_then(|e| e.op.strip_prefix(UNCONTROLLED_PREFIX))
        .map(str::to_string)
        .unwrap_or_else(|| r.uncontrolled[0].clone());
    let what = match kind.as_str() {
        "thread" => "started a thread: thread scheduling",
        "child" => "started a child process: what the child does",
        "io" => "waited for I/O readiness: the order in which ready I/O is delivered",
        "native" => "used a native network client: its connections (outside the closed network and the cassette)",
        "env" => "read a CI-volatile or proxy environment variable: its value",
        "net" => "talked to a live endpoint (UDP, a unix socket, ...): what it answered",
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
    fn of<S: RecordSource>(t: &'a S) -> Self {
        let recs = || (0..t.len()).map(|i| t.slim(i));
        let parallel = recs().any(|r| r.worker.is_some());
        let mut lists: BTreeMap<&str, Vec<(u64, &str)>> = BTreeMap::new();
        for (pos, r) in recs().enumerate() {
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
    let sources: Vec<MemTrace> = traces.iter().map(MemTrace::new).collect();
    verify_sources(&sources, labels).expect("an in-memory record always loads")
}

/// [`verify`] over any [`RecordSource`]: the slim records decide every verdict; the two full records of a test are
/// loaded (and dropped) only where the events are compared one by one (`diff_records`). Nothing holds more than two
/// full records at a time.
pub fn verify_sources<S: RecordSource>(traces: &[S], labels: &[String]) -> std::io::Result<Report> {
    let n = traces.len();
    // nodeid -> position of its record (the last one, for a duplicated id)
    let indexes: Vec<BTreeMap<&str, usize>> =
        traces.iter().map(|t| (0..t.len()).map(|i| (t.slim(i).nodeid.as_str(), i)).collect()).collect();

    let preds: Vec<Predecessors> = traces.iter().map(Predecessors::of).collect();
    let scoped = files_scoped(traces);
    let inputs: Vec<Option<BTreeMap<String, String>>> =
        traces.iter().map(|t| compared_inputs(t.header(), t.footer(), scoped)).collect();
    let scoped_files: Vec<BTreeMap<String, BTreeMap<String, String>>> =
        if scoped { traces.iter().map(|t| scoped_inputs(t.header(), t.footer())).collect() } else { Vec::new() };
    // what each run declared about its wide sensor (`meta.provable`): the general rule needs it per run, because
    // a run without one cannot have any of its tests reported identical
    let provable_meta: Vec<Option<serde_json::Value>> =
        traces.iter().map(|t| t.header().meta.get("provable").cloned()).collect();
    // the `--det` controls each run had on: the general rule's `Controlled` answers rest on them, so a run
    // missing one cannot have any of its tests reported identical (crate::provable::required_controls)
    let run_controls: Vec<Vec<String>> = traces
        .iter()
        .map(|t| {
            t.header()
                .meta
                .get("controls")
                .and_then(|v| v.as_array())
                .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
                .unwrap_or_default()
        })
        .collect();
    // the first run whose inputs differ from run 0's: its differences are every test's first divergent event
    let input_differences: Vec<InputDifference> =
        (1..n).map(|j| diff_inputs(inputs[0].as_ref(), inputs[j].as_ref(), 0, j)).find(|d| !d.is_empty()).unwrap_or_default();
    // Report tests in the executed order of the first run, then the rest.
    let mut ordered: Vec<&str> = Vec::new();
    let mut seen = BTreeSet::new();
    for t in traces {
        for i in 0..t.len() {
            let r = t.slim(i);
            if seen.insert(r.nodeid.as_str()) {
                ordered.push(r.nodeid.as_str());
            }
        }
    }

    // Design A (2026-11-20): environment variables are inputs only for the tests that read them; any other run
    // input that differs makes every test diverge.
    let (env_diffs, other_diffs): (Vec<InputDifference>, Vec<InputDifference>) =
        input_differences.iter().cloned().partition(|d| d.name.starts_with("env:"));
    let mut env_read_anywhere: BTreeSet<String> = BTreeSet::new();
    // a shell that does not record environment reads (meta.env_reads_recorded is not true: the Node shell, a
    // Python run without the env control) cannot say which test read a variable: every test counts as reading it
    let reads_recorded = traces.iter().all(|t| t.header().meta.get("env_reads_recorded").and_then(|v| v.as_bool()) == Some(true));
    // variables read outside any test (module scope, hooks, a dependency at import): no test's event, read by every
    // test as far as anyone can tell (R-054 N1, N2); "*": the environment was enumerated there
    let outside: BTreeSet<String> = traces
        .iter()
        .flat_map(|t| meta_array(t.header(), t.footer(), "env_read_outside_tests"))
        .filter_map(|v| v.as_str().map(str::to_string))
        .collect();
    // uncontrolled reads outside any test (a CI-volatile or proxy variable at module scope, ...): every test is
    // not proven (docs/VERIFY-CONTRACT.md section 1)
    let not_proven_outside: Vec<String> = undischarged_outside(traces);
    let mut summary = Summary { runs: n, inputs_recorded: n > 0 && inputs.iter().all(|i| i.is_some()), ..Default::default() };
    let mut tests = Vec::with_capacity(ordered.len());
    for id in ordered {
        let at: Vec<Option<usize>> = indexes.iter().map(|m| m.get(id).copied()).collect();
        let recs: Vec<Option<&SlimRecord>> =
            at.iter().zip(traces).map(|(i, t)| i.map(|i| t.slim(i))).collect();
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
        } else if !other_diffs.is_empty() {
            // the runs did not have the same inputs: no test is identical, whatever its fingerprint
            let mut all = other_diffs.clone();
            all.extend(env_diffs.iter().cloned());
            (Status::Diverged, Some(input_divergence(&all)))
        } else if let Some(d) = scoped_divergence(id, &scoped_files) {
            // P1 B1: what the test's own file read outside any test differs
            (Status::Diverged, Some(d))
        } else if let Some(d) = (1..n).find_map(|j| order_divergence(id, &preds[0], &preds[j], 0, j)) {
            (Status::Diverged, Some(d))
        } else if distinct.len() <= 1 {
            // Every run agrees on the fingerprint. That is not enough to say IDENTICAL: the general rule
            // (`crate::provable`) asks whether everything the test did was accounted for, and answers NOT PROVEN
            // when it was not. `judge_slim` is the only predicate allowed to conclude that it was, and the
            // cache reaches the same one (through `judge_record`), so the two cannot drift apart. Its default is NOT PROVEN, which is what
            // keeps a channel nobody has thought of yet out of this verdict.
            match recs
                .iter()
                .enumerate()
                .filter_map(|(i, r)| r.map(|r| (i, r)))
                .find_map(|(i, r)| match provable::judge_slim(
                    r,
                    provable_meta[i].as_ref(),
                    &run_controls[i],
                    &not_proven_outside,
                ) {
                    Verdict::Provable => None,
                    Verdict::NotProven { kind, detail } => Some((i, r, kind, detail)),
                })
            {
                Some((i, r, kind, detail)) => {
                    (Status::NotProven, Some(not_proven_divergence(r, i, &kind, &detail, &not_proven_outside)))
                }
                None => (Status::Stable, None),
            }
        } else {
            let a = recs[0].unwrap();
            let j = recs.iter().position(|r| r.unwrap().fingerprint != a.fingerprint).unwrap();
            // the only place the events of a record are compared one by one: the two records are loaded here and
            // dropped at the end of this block
            let full_a = traces[0].full(at[0].unwrap())?;
            let full_b = traces[j].full(at[j].unwrap())?;
            let mut d = diff_records(&full_a, &full_b, 0, j);
            drop((full_a, full_b));
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

        // an environment variable the test read differs between the runs: `input-differs`, unless the test also
        // diverged for another reason (order, uncontrolled source, an event other than an environment read)
        let (status, divergence) = match status {
            Status::Stable | Status::Diverged | Status::NotProven if !env_diffs.is_empty() => {
                let mut read = env_reads(&recs);
                read.all |= !reads_recorded || outside.contains("*");
                read.names.extend(outside.iter().cloned());
                let hit: Vec<&InputDifference> = env_diffs
                    .iter()
                    .filter(|d| read.all || read.names.contains(d.name.trim_start_matches("env:")))
                    .collect();
                let env_only = status == Status::Stable
                    || status == Status::NotProven
                    || divergence.as_ref().is_some_and(|d| d.reason == Reason::Env);
                if !hit.is_empty() && env_only {
                    for h in &hit {
                        env_read_anywhere.insert(h.name.clone());
                    }
                    (Status::InputDiffers, Some(input_differs(&hit, &read)))
                } else {
                    (status, divergence)
                }
            }
            _ => (status, divergence),
        };
        match status {
            Status::Stable => summary.stable += 1,
            Status::Diverged => summary.diverged += 1,
            Status::Missing => summary.missing += 1,
            Status::InputDiffers => summary.input_differs += 1,
            Status::NotProven => summary.not_proven += 1,
        }
        if !outcome_stable {
            summary.outcome_unstable += 1;
        }
        if let (Some(d), true) = (&divergence, status != Status::InputDiffers) {
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
    let order_digests: Vec<String> = traces
        .iter()
        .map(|t| order_digest(&(0..t.len()).map(|i| t.slim(i).nodeid.as_str()).collect::<Vec<&str>>()))
        .collect();
    summary.order_identical = order_digests.windows(2).all(|w| w[0] == w[1]);
    Ok(Report {
        labels: labels.to_vec(),
        order_digests,
        complete: traces.iter().map(|t| t.footer().is_some()).collect(),
        summary,
        tests,
        env_not_read: env_diffs.iter().filter(|d| !env_read_anywhere.contains(&d.name)).map(|d| d.name.clone()).collect(),
        input_differences,
        ignored_inputs: Vec::new(),
    })
}

/// The environment variables a test read in any run (`env.get` / `env.has` events: `NAME=...`), or all of them
/// (`env.list`: it enumerated the environment).
struct EnvReads {
    names: BTreeSet<String>,
    all: bool,
    site: Option<String>,
}

fn env_reads(recs: &[Option<&SlimRecord>]) -> EnvReads {
    let mut r = EnvReads { names: BTreeSet::new(), all: false, site: None };
    // per record, its stored events in order (record_source::SlimRecord::of): the first site of the first record
    // that has one, as the event-by-event walk over the records in run order gave
    for rec in recs.iter().flatten() {
        let e = &rec.env_reads;
        r.names.extend(e.names.iter().cloned());
        r.all |= e.list;
        if r.site.is_none() {
            r.site.clone_from(&e.site);
        }
    }
    r
}

/// `input-differs`: the variables the test read whose values differ between the runs.
fn input_differs(hit: &[&InputDifference], read: &EnvReads) -> Divergence {
    let names: Vec<&str> = hit.iter().map(|d| d.name.trim_start_matches("env:")).collect();
    let d = hit[0];
    let at = read.site.as_deref().map(|s| format!(" (read at {s})")).unwrap_or_default();
    let ev = |v: &Option<String>| v.as_ref().map(|v| Event::new(Source::Other, format!("input.{}", d.name), "<run>", v.clone()));
    Divergence {
        run_a: d.run_a,
        run_b: d.run_b,
        index: None,
        window: None,
        event_a: ev(&d.value_a),
        event_b: ev(&d.value_b),
        reason: Reason::Env,
        description: format!("input differs: {}{at}: the test read an environment variable whose value differs \
                              between the runs; otherwise identical", names.join(", ")),
        lost_predecessors: Vec::new(),
    }
}

/// `verify_paths` with run inputs the user declared irrelevant removed before the comparison: `ignore_env` holds
/// environment variable names, or prefixes ending in `*`. The report lists what was ignored.
///
/// Bounded memory (P0 big trace): the traces are read through [`FileTrace`], one slim record per test; whole records
/// are loaded two at a time where the verifier compares events.
pub fn verify_paths_ignoring<P: AsRef<Path>>(paths: &[P], ignore_env: &[String]) -> Result<Report, TraceError> {
    let (mut traces, labels) = open_paths(paths)?;
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
    let mut r = verify_sources(&traces, &labels)?;
    r.ignored_inputs = ignored.into_iter().collect();
    Ok(r)
}

pub fn verify_paths<P: AsRef<Path>>(paths: &[P]) -> Result<Report, TraceError> {
    let (traces, labels) = open_paths(paths)?;
    Ok(verify_sources(&traces, &labels)?)
}

fn open_paths<P: AsRef<Path>>(paths: &[P]) -> Result<(Vec<FileTrace>, Vec<String>), TraceError> {
    let mut traces = Vec::new();
    let mut labels = Vec::new();
    for p in paths {
        traces.push(FileTrace::open(p.as_ref())?);
        labels.push(p.as_ref().display().to_string());
    }
    check_headers(&traces.iter().map(|t| &t.header).collect::<Vec<_>>(), &labels)?;
    Ok((traces, labels))
}

/// Traces with different event encodings are never compared: their
/// fingerprints differ by construction, which is not a divergence.
pub fn check_compatible(traces: &[Trace], labels: &[String]) -> Result<(), TraceError> {
    check_headers(&traces.iter().map(|t| &t.header).collect::<Vec<_>>(), labels)
}

fn check_headers(headers: &[&Header], labels: &[String]) -> Result<(), TraceError> {
    let Some(first) = headers.first() else { return Ok(()) };
    let base = first.encoding;
    for (t, l) in headers.iter().zip(labels).skip(1) {
        if t.encoding != base {
            return Err(TraceError::Incompatible(format!(
                "{} uses event encoding {} but {} uses {}; re-run both with the same detpy version",
                labels[0], base, l, t.encoding
            )));
        }
    }
    Ok(())
}

/// What to do for each reason (audit G-2210, G-2019): printed once per reason present.
pub const HINTS: &[(&str, &str)] = &[
    ("entropy", "the test reads OS entropy (os.urandom, uuid4, secrets) and the runs did not control it alike: \
                 Python controls it by default under --det (--det-entropy=observe leaves it real); Node controls \
                 crypto.randomBytes & co. by default (--det-urandom=off leaves them real; not for tests of \
                 cryptography)"),
    ("env", "an environment variable differs between the runs; give both runs the same environment, or declare it \
             irrelevant with --ignore-env NAME"),
    ("tz", "the runs used different time zones; keep the default --det-tz=UTC (or the same zone in both runs)"),
    ("locale", "the runs used different locales; keep the default --det-locale (or the same locale in both runs)"),
    ("order", "the test ran after different tests: an order dependency; `fenvix repro TEST` names the tests it \
               depends on"),
    ("thread", "threads are not scheduled deterministically by this release: the test cannot be proven identical"),
    ("child", "a child process is not controlled by this release: the test cannot be proven identical"),
    ("io", "the order of ready I/O is not controlled by this release: the test cannot be proven identical"),
    ("native", "a native network client (grpcio, pycurl, libpq, ...) opens its sockets in C, outside the closed \
                network: the test cannot be proven identical (needs the syscall backend)"),
    ("deps", "the installed dependencies the runs loaded differ (node_modules, site-packages): install the same \
              lockfile in both runs"),
    ("code", "the project's source the runs loaded differs (an edit, committed or not): compare runs of one tree"),
    ("outcome-only", "same observed events, different outcome: the cause is outside what is observed (C code, \
                      memory addresses, files or services outside the test); `fenvix repro TEST` searches for it"),
];

/// Human-readable rendering of a report.
pub fn render_text(report: &Report, show_stable: bool) -> String {
    let mut out = String::new();
    let _ = render_text_to(report, show_stable, &mut out);
    out
}

/// [`render_text`] written to `out` as it is rendered (P0 big trace: the text of a 30765-test report is 1.2 GB; the
/// Python CLI streams it instead of holding it whole next to the report). Same text, piece by piece.
pub fn render_text_to<W: std::fmt::Write>(report: &Report, show_stable: bool, out: &mut W) -> std::fmt::Result {
    let s = &report.summary;
    let _ = writeln!(out, "detpy verify: {} runs, {} tests", s.runs, s.tests);
    for (i, l) in report.labels.iter().enumerate() {
        let partial = if report.complete.get(i).copied().unwrap_or(true) { "" } else { " (partial)" };
        let _ = writeln!(out, "  run {i}: {l}{partial}");
    }
    let verdict = if s.tests == 0 {
        "NOTHING VERIFIED: no test ran in these runs".to_string()
    } else if s.diverged == 0 && s.missing == 0 && s.input_differs == 0 && s.not_proven > 0 {
        format!(
            "NOT PROVEN: {} of {} tests used a source this release does not control (named below); no test is shown \
             to differ",
            s.not_proven, s.tests
        )
    } else if s.diverged == 0 && s.missing == 0 && s.input_differs == 0 && !s.inputs_recorded {
        // reviewer #8 (G-0041, G-0054): same events but no recorded inputs is not "the same inputs"
        format!(
            "NOT PROVEN: all {} tests observed the same events, but the traces do not record the run inputs, so \
             the runs cannot be shown to have had the same inputs",
            s.tests
        )
    } else if s.diverged == 0 && s.missing == 0 && s.input_differs == 0 {
        format!("IDENTICAL: all {} tests ran with the same inputs and observed the same events", s.tests)
    } else if s.diverged == 0 && s.missing == 0 {
        let names: Vec<&str> = report
            .input_differences
            .iter()
            .filter(|d| d.name.starts_with("env:") && !report.env_not_read.contains(&d.name))
            .map(|d| d.name.trim_start_matches("env:"))
            .collect();
        format!(
            "INPUT DIFFERS: {}: {} of {} tests read it with a different value and are otherwise identical",
            names.join(", "),
            s.input_differs,
            s.tests
        )
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
    if !report.env_not_read.is_empty() {
        let _ = writeln!(
            out,
            "not compared: environment variables that differ but no test read: {}",
            report.env_not_read.iter().map(|n| n.trim_start_matches("env:")).collect::<Vec<_>>().join(", ")
        );
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
        "covered by Level 0: {}  not covered: {}  missing: {}  input differs: {}  not proven: {}  outcome-unstable: {}",
        s.stable, s.diverged, s.missing, s.input_differs, s.not_proven, s.outcome_unstable
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
                let tag = match t.status {
                    Status::Missing => "MISSING ",
                    Status::InputDiffers => "INPUT-DIFFERS",
                    Status::NotProven => "NOT-PROVEN",
                    _ => "NOT-COVERED",
                };
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
    Ok(())
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

    /// A trace as a real shell writes it: with the wide sensor declared (`meta.provable`).
    ///
    /// The declaration is part of what a run has to say about itself since the general rule exists
    /// ([`crate::provable`]): without it the core cannot know what was watched, and every test is NOT PROVEN.
    /// `trace_without_sensor` below builds one that says nothing, which is what an older shell produces.
    fn trace(recs: Vec<TestRecord>) -> Trace {
        Trace { header: Header::new(sensor_meta(), vec![]), tests: recs, footer: None }
    }

    fn sensor_meta() -> serde_json::Value {
        serde_json::json!({
            "provable": {
                "sensor": "py-monitoring/1",
                "contract": crate::provable::SENSOR_CONTRACT,
                "surface": crate::provable::surface_digest(),
                "runtime": "cpython3.13",
            },
            // the controls the general rule's `Controlled` answers rest on: part of every real trace, and a run
            // missing one cannot have any test reported identical
            "controls": crate::provable::required_controls("py-monitoring/1"),
        })
    }

    fn trace_without_sensor(recs: Vec<TestRecord>) -> Trace {
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
        // the sensor declaration is kept: it is part of every real trace, and dropping it would make every test
        // NOT PROVEN for want of a sensor instead of for the reason the test is about
        t.header.meta = serde_json::json!({
            "inputs": m,
            "env_reads_recorded": true,
            "provable": sensor_meta()["provable"].clone(),
            "controls": sensor_meta()["controls"].clone(),
        });
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
        // environment variables: design A (input-differs for the tests that read them), see env_* tests below
        let cases: [(&str, &str, Reason); 9] = [
            ("runtime", "CPython 3.12.0 linux x86_64", Reason::Runtime),
            ("hashseed", "7", Reason::Hashseed),
            ("seed", "3", Reason::Seed),
            ("clock", "virtual epoch=2 tick=1000", Reason::Time),
            ("tz", "Asia/Tokyo (not pinned)", Reason::Tz),
            ("locale", "de_DE.UTF-8 (pinned)", Reason::Locale),
            ("network", "record", Reason::Net),
            ("fs", "real", Reason::Fs),
            ("entropy", "controlled", Reason::Entropy),
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
        // an older trace's `urandom` is the same input as `entropy` (R-051 R2); an empty `inputs` records nothing (R1)
        let mut old: Vec<(&str, &str)> = BASE.to_vec();
        old.push(("urandom", "controlled"));
        let mut new: Vec<(&str, &str)> = BASE.to_vec();
        new.push(("entropy", "controlled"));
        let r = verify(
            &[with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &old),
              with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &new)],
            &[],
        );
        assert_eq!((r.summary.stable, r.summary.identical), (1, 1), "{:?}", r.input_differences);
        let empty = || with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &[]);
        let r = verify(&[empty(), empty()], &[]);
        assert!(!r.summary.inputs_recorded && !render_text(&r, false).contains("verdict: IDENTICAL"));
        // same inputs: identical
        let a = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE);
        let b = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE);
        let r = verify(&[a, b], &[]);
        assert_eq!((r.summary.stable, r.summary.identical), (1, 1));
        assert!(r.summary.inputs_recorded);
        assert!(render_text(&r, false).contains("verdict: IDENTICAL"));
    }

    fn env_ev(op: &str, v: &str) -> Event {
        Event::new(Source::Other, op, "t.py:3", v)
    }

    /// Design A (2026-11-20): a differing environment variable that no test read is not compared (listed); a test
    /// that read it is `input-differs` (named, not unstable, not identical); with another difference it diverges.
    #[test]
    fn env_differences_are_input_differs_for_the_tests_that_read_them() {
        let base: Vec<(&str, &str)> = vec![("tz", "UTC"), ("env:MY_FLAG", "aaaa"), ("env:OTHER", "1111")];
        let changed: Vec<(&str, &str)> = vec![("tz", "UTC"), ("env:MY_FLAG", "bbbb"), ("env:OTHER", "1111")];
        let reads = [env_ev("env.get", "MY_FLAG=set"), t("1")];
        let a = with_inputs(trace(vec![rec("reads", &reads, "passed", 10), rec("plain", &[t("1")], "passed", 10)]), &base);
        let b = with_inputs(trace(vec![rec("reads", &reads, "passed", 10), rec("plain", &[t("1")], "passed", 10)]), &changed);
        let r = verify(&[a, b], &[]);
        let by: BTreeMap<&str, &TestVerdict> = r.tests.iter().map(|t| (t.nodeid.as_str(), t)).collect();
        assert_eq!(by["reads"].status, Status::InputDiffers);
        assert_eq!(by["plain"].status, Status::Stable);
        assert_eq!((r.summary.input_differs, r.summary.stable, r.summary.diverged), (1, 1, 0));
        assert!(r.summary.reasons.is_empty(), "{:?}", r.summary.reasons);
        let d = by["reads"].divergence.as_ref().unwrap();
        assert!(d.description.starts_with("input differs: MY_FLAG (read at t.py:3)"), "{}", d.description);
        let text = render_text(&r, false);
        assert!(text.contains("verdict: INPUT DIFFERS: MY_FLAG: 1 of 2 tests"), "{text}");
        assert!(text.contains("INPUT-DIFFERS reads"), "{text}");
        // nobody read it: identical, and listed as not compared
        let a = with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &base);
        let b = with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &changed);
        let r = verify(&[a, b], &[]);
        assert_eq!((r.summary.stable, r.summary.input_differs), (1, 0));
        assert_eq!(r.env_not_read, vec!["env:MY_FLAG".to_string()]);
        assert!(render_text(&r, false).contains("not compared: environment variables that differ but no test read: MY_FLAG"));
        // a trace that does not record environment reads (Node): every test counts as reading it
        let unrec = |t: Trace| {
            let mut t = t;
            t.header.meta.as_object_mut().unwrap().remove("env_reads_recorded");
            t
        };
        let a = unrec(with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &base));
        let b = unrec(with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &changed));
        assert_eq!(verify(&[a, b], &[]).tests[0].status, Status::InputDiffers);
        // an enumeration of the environment reads every variable
        let a = with_inputs(trace(vec![rec("lists", &[env_ev("env.list", "3:abc")], "passed", 10)]), &base);
        let b = with_inputs(trace(vec![rec("lists", &[env_ev("env.list", "3:abc")], "passed", 10)]), &changed);
        assert_eq!(verify(&[a, b], &[]).tests[0].status, Status::InputDiffers);
        // read, and another event differs too: diverged
        let a = with_inputs(trace(vec![rec("x", &[env_ev("env.get", "MY_FLAG=set"), t("1")], "passed", 10)]), &base);
        let b = with_inputs(trace(vec![rec("x", &[env_ev("env.get", "MY_FLAG=set"), t("2")], "passed", 10)]), &changed);
        let r = verify(&[a, b], &[]);
        assert_eq!(r.tests[0].status, Status::Diverged);
        assert_eq!(r.summary.diverged, 1);
        // another input differs too: every test diverges, the other input named first
        let other: Vec<(&str, &str)> = vec![("tz", "Asia/Tokyo"), ("env:MY_FLAG", "bbbb"), ("env:OTHER", "1111")];
        let a = with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &base);
        let b = with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &other);
        let r = verify(&[a, b], &[]);
        assert_eq!(r.tests[0].status, Status::Diverged);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Tz);
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
        let text = render_text(&r, false);
        assert!(text.contains("run inputs: NOT RECORDED"));
        assert!(text.contains("verdict: NOT PROVEN") && !text.contains("IDENTICAL"), "{text}");
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

    // ---- review R-055 (docs/VERIFY-CONTRACT.md) ----

    fn meta_extra(mut t: Trace, key: &str, v: serde_json::Value) -> Trace {
        t.header.meta.as_object_mut().unwrap().insert(key.into(), v);
        t
    }

    /// V3: a file read outside any test with different bytes makes every test diverge (reason fs).
    #[test]
    fn r055_files_read_outside_tests_differ() {
        let f = |d: &str| serde_json::json!([{ "path": "data.txt", "digest": d }]);
        let mk = |d: &str| meta_extra(with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE), "files_read_outside_tests", f(d));
        let r = verify(&[mk("2:aa"), mk("2:bb")], &[]);
        assert_eq!(r.tests[0].status, Status::Diverged);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Fs);
        assert!(render_text(&r, false).contains("file:data.txt"));
        let r = verify(&[mk("2:aa"), mk("2:aa")], &[]);
        assert_eq!(r.tests[0].status, Status::Stable);
        // a run with the field against one without it: not the same inputs
        let plain = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE);
        assert_eq!(verify(&[mk("2:aa"), plain], &[]).tests[0].status, Status::Diverged);
    }

    /// V4, V5: `inputs.code` and `inputs.deps` are run inputs with their own reasons.
    #[test]
    fn r055_code_and_deps_inputs() {
        for (k, reason) in [("deps", Reason::Deps), ("code", Reason::Code)] {
            let mut a: Vec<(&str, &str)> = BASE.to_vec();
            let mut b = a.clone();
            a.push((k, "3 files aa"));
            b.push((k, "3 files bb"));
            let ra = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &a);
            let rb = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &b);
            let r = verify(&[ra, rb], &[]);
            assert_eq!(r.tests[0].status, Status::Diverged);
            assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, reason);
        }
    }

    /// V13: a hash seed nobody fixed never compares equal.
    #[test]
    fn r055_random_hashseed_is_never_equal() {
        let mut a: Vec<(&str, &str)> = BASE.iter().filter(|(k, _)| *k != "hashseed").copied().collect();
        a.push(("hashseed", "<random>"));
        let ra = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &a);
        let rb = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &a);
        let r = verify(&[ra, rb], &[]);
        assert_eq!(r.tests[0].status, Status::Diverged);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Hashseed);
    }

    /// The general rule, at the verifier's level: two runs that agree on everything are still NOT PROVEN when the
    /// run did not say what it watched. This is the clause that makes the default "I do not know" instead of
    /// "identical", and it does not depend on any list of channels.
    #[test]
    fn a_run_that_declares_no_sensor_is_never_identical() {
        let a = with_inputs(trace_without_sensor(vec![rec("x", &[t("1")], "passed", 100)]), &BASE);
        let b = with_inputs(trace_without_sensor(vec![rec("x", &[t("1")], "passed", 100)]), &BASE);
        // with_inputs puts the declaration back, so take it away again: this is what an older shell writes
        let strip = |mut tr: Trace| {
            tr.header.meta.as_object_mut().unwrap().remove("provable");
            tr
        };
        let r = verify(&[strip(a), strip(b)], &["a".into(), "b".into()]);
        assert_eq!(r.tests[0].status, Status::NotProven);
        assert_eq!(r.summary.stable, 0);
        assert_eq!(r.summary.not_proven, 1);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Sensor);
        assert!(!r.tests[0].covered());
        let text = render_text(&r, false);
        assert!(text.contains("verdict: NOT PROVEN"), "{text}");
    }

    /// A sensor built against a different accounting table, or a runtime nobody audited the table against, is
    /// refused the same way: the core will not apply today's table to yesterday's sensor.
    #[test]
    fn a_sensor_or_runtime_the_core_does_not_know_is_never_identical() {
        for (field, value) in [("surface", "deadbeefdeadbeefdeadbeefdeadbeef"), ("runtime", "cpython3.99")] {
            let mk = || {
                let mut tr = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 100)]), &BASE);
                tr.header.meta["provable"][field] = serde_json::json!(value);
                tr
            };
            let r = verify(&[mk(), mk()], &[]);
            assert_eq!(r.tests[0].status, Status::NotProven, "{field}");
            assert_eq!(r.summary.stable, 0, "{field}");
        }
    }

    /// The channel nobody has thought of: the sensor reports a name the table does not list, and the verdict is
    /// NOT PROVEN with that name in it. No channel-specific rule is involved.
    #[test]
    fn a_channel_the_table_does_not_know_is_not_proven_and_named() {
        // `unaccounted.api` + the value is how a shell reports it; the recorder turns it into the record's list
        let u = Event::new(Source::Other, "unaccounted.api", "t.py:3", "posix.getxattr");
        let mk = || with_inputs(trace(vec![rec("x", &[u.clone(), t("1")], "passed", 10)]), &BASE);
        let r = verify(&[mk(), mk()], &[]);
        assert_eq!(r.tests[0].status, Status::NotProven);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Api);
        let d = &r.tests[0].divergence.as_ref().unwrap().description;
        assert!(d.contains("posix.getxattr"), "{d}");
        assert!(d.contains("NOT PROVEN"), "{d}");
        assert_eq!((r.summary.stable, r.summary.not_proven), (0, 1));
        // and the recorder really did carry it on the record, truncation or not
        assert_eq!(r.tests[0].distinct_fingerprints, 1);
    }

    /// V1, V2 and D1: a mark (or an uncontrolled read outside any test) is NOT PROVEN, never IDENTICAL, never DIVERGENT.
    #[test]
    fn r055_marks_are_not_proven() {
        let m = Event::new(Source::Other, "uncontrolled.env", "t.py:3", "TMPDIR");
        let a = with_inputs(trace(vec![rec("x", &[m.clone(), t("1")], "passed", 10), rec("y", &[t("1")], "passed", 10)]), &BASE);
        let b = with_inputs(trace(vec![rec("x", &[m, t("1")], "passed", 10), rec("y", &[t("1")], "passed", 10)]), &BASE);
        let r = verify(&[a, b], &[]);
        assert_eq!(r.tests[0].status, Status::NotProven);
        assert_eq!(r.tests[0].divergence.as_ref().unwrap().reason, Reason::Env);
        assert_eq!((r.summary.stable, r.summary.not_proven, r.summary.diverged), (1, 1, 0));
        let text = render_text(&r, false);
        assert!(text.contains("verdict: NOT PROVEN") && text.contains("NOT-PROVEN x"), "{text}");
        let mk = || meta_extra(with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE), "not_proven_outside_tests", serde_json::json!(["env:HTTPS_PROXY"]));
        let r = verify(&[mk(), mk()], &[]);
        assert_eq!(r.tests[0].status, Status::NotProven);
        assert!(r.tests[0].divergence.as_ref().unwrap().description.contains("env:HTTPS_PROXY"));
    }

    /// P1 B1 (docs/DESIGN-P1.md section B). protects=a file read outside any test by one test file's module scope or
    /// hooks diverges that file's tests only, when every run's runner isolates files; fails_when=another file's test
    /// diverges for it, the reading file's test is stable although the bytes differ, or an unscoped entry, a run
    /// without `files_outside_scope: "file"` or a missing entry stops diverging every test; no_claim=the shells decide
    /// isolation (`files_outside_scope`), not exercised here.
    #[test]
    fn p1_b1_file_read_outside_tests_scoped_to_its_test_file() {
        let mk = |entries: serde_json::Value, scope: &str| {
            let t = with_inputs(
                trace(vec![rec("a.test.js::a1", &[t("1")], "passed", 10), rec("b.test.js::b1", &[t("2")], "passed", 10), rec("c.test.mjs@@web::c1", &[t("3")], "passed", 10)]),
                &BASE,
            );
            meta_extra(meta_extra(t, "files_read_outside_tests", entries), "files_outside_scope", serde_json::json!(scope))
        };
        let e = |d: &str, file: Option<&str>| match file {
            Some(f) => serde_json::json!([{"path": "<tmp>/x", "digest": d, "file": f}]),
            None => serde_json::json!([{"path": "<tmp>/x", "digest": d}]),
        };
        let st = |r: &Report| r.tests.iter().map(|t| (t.nodeid.clone(), t.status)).collect::<Vec<_>>();
        // scoped: only a's test diverges
        let r = verify(&[mk(e("1:aa", Some("a.test.js")), "file"), mk(e("1:bb", Some("a.test.js")), "file")], &[]);
        assert_eq!(st(&r), vec![("a.test.js::a1".into(), Status::Diverged), ("b.test.js::b1".into(), Status::Stable), ("c.test.mjs@@web::c1".into(), Status::Stable)]);
        assert!(r.tests[0].divergence.as_ref().unwrap().description.contains("file:<tmp>/x"));
        // a Vitest project's test is matched by its file
        let r = verify(&[mk(e("1:aa", Some("c.test.mjs")), "file"), mk(e("1:bb", Some("c.test.mjs")), "file")], &[]);
        assert_eq!(r.tests[2].status, Status::Diverged);
        assert_eq!((r.tests[0].status, r.tests[1].status), (Status::Stable, Status::Stable));
        // read in one run only: the file's tests diverge
        let r = verify(&[mk(e("1:aa", Some("a.test.js")), "file"), mk(serde_json::json!([]), "file")], &[]);
        assert_eq!((r.tests[0].status, r.tests[1].status), (Status::Diverged, Status::Stable));
        // equal: nothing differs
        let r = verify(&[mk(e("1:aa", Some("a.test.js")), "file"), mk(e("1:aa", Some("a.test.js")), "file")], &[]);
        assert_eq!(r.summary.stable, 3);
        // an entry without a file (main process, globalSetup): every test, as before
        let r = verify(&[mk(e("1:aa", None), "file"), mk(e("1:bb", None), "file")], &[]);
        assert_eq!(r.summary.diverged, 3);
        // a run whose runner does not isolate files: every test, as before
        let r = verify(&[mk(e("1:aa", Some("a.test.js")), "run"), mk(e("1:bb", Some("a.test.js")), "file")], &[]);
        assert_eq!(r.summary.diverged, 3);
        let r = verify(&[mk(e("1:aa", Some("a.test.js")), "run"), mk(e("1:bb", Some("a.test.js")), "run")], &[]);
        assert_eq!(r.summary.diverged, 3);
    }

    /// P1 A1 (docs/DESIGN-P1.md section A). protects=an uncontrolled variable read outside any test with the same
    /// value in every run no longer makes every test NOT PROVEN; fails_when=equal `env:<NAME>=<digest>` entries leave a
    /// test NOT PROVEN, or different digests, a digest in one run only, an entry without a digest or a non-env entry
    /// let a test be stable; no_claim=the cache's own judgement (one run) is not exercised here.
    #[test]
    fn p1_a1_env_read_outside_tests_compared_by_value() {
        let mk = |entries: serde_json::Value| {
            meta_extra(with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10), rec("y", &[t("2")], "passed", 10)]), &BASE), "not_proven_outside_tests", entries)
        };
        let j = |v: &[&str]| serde_json::json!(v);
        // the same value in both runs: discharged, nothing differs
        let r = verify(&[mk(j(&["env:*=1111", "env:TMPDIR=aaaa"])), mk(j(&["env:*=1111", "env:TMPDIR=aaaa"]))], &[]);
        assert_eq!((r.summary.stable, r.summary.not_proven), (2, 0), "{:?}", r.tests);
        // several values in one run (the variable was changed): the same set in both runs
        let r = verify(&[mk(j(&["env:TMPDIR=aaaa", "env:TMPDIR=bbbb"])), mk(j(&["env:TMPDIR=bbbb", "env:TMPDIR=aaaa"]))], &[]);
        assert_eq!(r.summary.stable, 2);
        // a different value: every test NOT PROVEN, the variable named
        let r = verify(&[mk(j(&["env:TMPDIR=aaaa"])), mk(j(&["env:TMPDIR=bbbb"]))], &[]);
        assert_eq!((r.summary.stable, r.summary.not_proven), (0, 2));
        assert!(r.tests[0].divergence.as_ref().unwrap().description.contains("env:TMPDIR"), "{:?}", r.tests[0]);
        // read outside any test in one run only
        let r = verify(&[mk(j(&["env:TMPDIR=aaaa"])), mk(j(&[]))], &[]);
        assert_eq!(r.summary.stable, 0);
        let r = verify(&[mk(j(&["env:TMPDIR=aaaa", "env:*=1111"])), mk(j(&["env:TMPDIR=aaaa"]))], &[]);
        assert_eq!(r.summary.stable, 0);
        // an entry without a digest (older traces, the Python shell): today's verdict
        let r = verify(&[mk(j(&["env:TMPDIR"])), mk(j(&["env:TMPDIR=aaaa"]))], &[]);
        assert_eq!(r.summary.stable, 0);
        let r = verify(&[mk(j(&["env:TMPDIR"])), mk(j(&["env:TMPDIR"]))], &[]);
        assert_eq!(r.summary.stable, 0);
        // a non-env entry is never discharged
        let r = verify(&[mk(j(&["api:process.reallyExit", "env:TMPDIR=aaaa"])), mk(j(&["api:process.reallyExit", "env:TMPDIR=aaaa"]))], &[]);
        assert_eq!((r.summary.stable, r.summary.not_proven), (0, 2));
        let d = r.tests[0].divergence.as_ref().unwrap().description.clone();
        assert!(d.contains("api:process.reallyExit") && !d.contains("env:TMPDIR"), "{d}");
        // three runs: discharged only if all agree
        let r = verify(&[mk(j(&["env:TMPDIR=aaaa"])), mk(j(&["env:TMPDIR=aaaa"])), mk(j(&["env:TMPDIR=cccc"]))], &[]);
        assert_eq!(r.summary.stable, 0);
        // one run: nothing to compare the value with, nothing discharged (review 2026-11-24)
        let r = verify(&[mk(j(&["env:TMPDIR=aaaa"]))], &[]);
        assert_eq!((r.summary.stable, r.summary.not_proven), (0, 2), "{:?}", r.tests);
    }

    // ---- golden corpus (P0 big trace, criterion 6) ----
    //
    // `golden_corpus_generate` writes every case below to tests/golden/ (`<case>.runN.jsonl`) with the report the
    // verifier gives for it (`<case>.report.json`, labels set to run0, run1, ...). It is run once, on the code before
    // the bounded-memory refactor, and its output is committed; `tests/golden_verify.rs` then requires the refactored
    // verifier to give the same report byte for byte, over in-memory traces and over the files.
    // Run: cargo test -p detpy-core --lib golden_corpus_generate -- --ignored

    fn golden_line(kind: &str, v: serde_json::Value) -> String {
        let mut o = v.as_object().unwrap().clone();
        o.insert("type".into(), serde_json::json!(kind));
        serde_json::Value::Object(o).to_string()
    }

    fn golden_trace_text(t: &Trace) -> String {
        let mut s = golden_line("header", serde_json::to_value(&t.header).unwrap());
        s.push('\n');
        for r in &t.tests {
            s.push_str(&golden_line("test", serde_json::to_value(r).unwrap()));
            s.push('\n');
        }
        if let Some(f) = &t.footer {
            s.push_str(&golden_line("footer", serde_json::to_value(f).unwrap()));
            s.push('\n');
        }
        s
    }

    fn golden_labels(r: &mut Report) {
        r.labels = (0..r.labels.len()).map(|i| format!("run{i}")).collect();
    }

    /// The traces of every `verify(&[...])` call of this module's tests (same constructions), plus the extra
    /// pairs of criterion 6. Each case is the list of runs passed to `verify`.
    fn golden_cases() -> Vec<(String, Vec<Trace>)> {
        let mut out: Vec<(String, Vec<Trace>)> = Vec::new();
        let mut add = |name: &str, ts: Vec<Trace>| out.push((name.to_string(), ts));
        let one = |v: &str, o: &str| trace(vec![rec("x", &[t(v)], o, 100)]);
        add("identical_runs_are_stable", vec![one("1", "passed"), one("1", "passed")]);
        {
            let ent = |v: &str| Event::new(Source::Entropy, "os.urandom", "t.py:9", v);
            add("value_divergence", vec![
                trace(vec![rec("x", &[t("1"), ent("aa"), t("2")], "passed", 100)]),
                trace(vec![rec("x", &[t("1"), ent("bb"), t("2")], "passed", 100)]),
            ]);
        }
        add("outcome_only", vec![one("1", "passed"), one("1", "failed")]);
        {
            let fs = Event::new(Source::Fs, "os.listdir", "t.py:4", "3:abc");
            add("extra_event", vec![one("1", "passed"), trace(vec![rec("x", &[t("1"), fs], "passed", 100)])]);
            let end = Event::new(Source::Random, "random.state", END_SITE, "x");
            add("extra_event_over_end", vec![
                trace(vec![rec("x", &[end.clone()], "passed", 100)]),
                trace(vec![rec("x", &[t("1"), end], "passed", 100)]),
            ]);
        }
        add("thread", vec![
            trace(vec![rec("x", &[t("1"), t("2").with_thread(1)], "passed", 100)]),
            trace(vec![rec("x", &[t("1").with_thread(1), t("2")], "passed", 100)]),
        ]);
        {
            let mut ea: Vec<Event> = (0..20).map(|i| t(&i.to_string())).collect();
            let eb = ea.clone();
            ea[13] = t("changed");
            add("beyond_trace", vec![trace(vec![rec("x", &ea, "passed", 5)]), trace(vec![rec("x", &eb, "passed", 5)])]);
        }
        add("missing_and_order", vec![
            trace(vec![rec("x", &[], "passed", 10), rec("y", &[], "passed", 10)]),
            trace(vec![rec("y", &[], "passed", 10)]),
        ]);
        {
            let cases: [(&str, &str); 9] = [
                ("runtime", "CPython 3.12.0 linux x86_64"),
                ("hashseed", "7"),
                ("seed", "3"),
                ("clock", "virtual epoch=2 tick=1000"),
                ("tz", "Asia/Tokyo (not pinned)"),
                ("locale", "de_DE.UTF-8 (pinned)"),
                ("network", "record"),
                ("fs", "real"),
                ("entropy", "controlled"),
            ];
            for (name, value) in cases {
                let a = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE);
                let mut changed: Vec<(&str, &str)> = BASE.iter().filter(|(k, _)| *k != name).copied().collect();
                changed.push((name, value));
                let b = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &changed);
                add(&format!("input_{name}"), vec![a, b]);
            }
            let mut old: Vec<(&str, &str)> = BASE.to_vec();
            old.push(("urandom", "controlled"));
            let mut new: Vec<(&str, &str)> = BASE.to_vec();
            new.push(("entropy", "controlled"));
            add("input_urandom_is_entropy", vec![
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &old),
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &new),
            ]);
            let empty = || with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &[]);
            add("input_empty", vec![empty(), empty()]);
            add("input_same", vec![
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE),
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE),
            ]);
        }
        {
            let base: Vec<(&str, &str)> = vec![("tz", "UTC"), ("env:MY_FLAG", "aaaa"), ("env:OTHER", "1111")];
            let changed: Vec<(&str, &str)> = vec![("tz", "UTC"), ("env:MY_FLAG", "bbbb"), ("env:OTHER", "1111")];
            let reads = [env_ev("env.get", "MY_FLAG=set"), t("1")];
            add("env_read", vec![
                with_inputs(trace(vec![rec("reads", &reads, "passed", 10), rec("plain", &[t("1")], "passed", 10)]), &base),
                with_inputs(trace(vec![rec("reads", &reads, "passed", 10), rec("plain", &[t("1")], "passed", 10)]), &changed),
            ]);
            add("env_not_read", vec![
                with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &base),
                with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &changed),
            ]);
            let unrec = |t: Trace| {
                let mut t = t;
                t.header.meta.as_object_mut().unwrap().remove("env_reads_recorded");
                t
            };
            add("env_unrecorded", vec![
                unrec(with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &base)),
                unrec(with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &changed)),
            ]);
            add("env_list", vec![
                with_inputs(trace(vec![rec("lists", &[env_ev("env.list", "3:abc")], "passed", 10)]), &base),
                with_inputs(trace(vec![rec("lists", &[env_ev("env.list", "3:abc")], "passed", 10)]), &changed),
            ]);
            add("env_read_and_other_event", vec![
                with_inputs(trace(vec![rec("x", &[env_ev("env.get", "MY_FLAG=set"), t("1")], "passed", 10)]), &base),
                with_inputs(trace(vec![rec("x", &[env_ev("env.get", "MY_FLAG=set"), t("2")], "passed", 10)]), &changed),
            ]);
            let other: Vec<(&str, &str)> = vec![("tz", "Asia/Tokyo"), ("env:MY_FLAG", "bbbb"), ("env:OTHER", "1111")];
            add("env_and_tz", vec![
                with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &base),
                with_inputs(trace(vec![rec("plain", &[t("1")], "passed", 10)]), &other),
            ]);
        }
        add("input_rank", vec![
            with_inputs(trace(vec![rec("x", &[], "passed", 10)]), &[("tz", "UTC"), ("env:A", "1"), ("seed", "0")]),
            with_inputs(trace(vec![rec("x", &[], "passed", 10)]), &[("tz", "Asia/Tokyo"), ("env:A", "2"), ("seed", "1")]),
        ]);
        add("inputs_in_one_run", vec![
            with_inputs(trace(vec![rec("x", &[], "passed", 10)]), &BASE),
            trace(vec![rec("x", &[], "passed", 10)]),
        ]);
        add("inputs_in_no_run", vec![trace(vec![rec("x", &[], "passed", 10)]), trace(vec![rec("x", &[], "passed", 10)])]);
        for kind in ["thread", "child", "io"] {
            let marker = Event::new(Source::Other, format!("uncontrolled.{kind}"), "t.py:3", "x");
            add(&format!("uncontrolled_{kind}"), vec![
                trace(vec![rec("x", &[t("1"), marker.clone()], "passed", 10)]),
                trace(vec![rec("x", &[t("1"), marker.clone()], "passed", 10)]),
            ]);
            let mut evs: Vec<Event> = (0..10).map(|i| t(&i.to_string())).collect();
            evs.push(marker);
            add(&format!("uncontrolled_{kind}_truncated"), vec![
                trace(vec![rec("x", &evs, "passed", 3)]),
                trace(vec![rec("x", &evs, "passed", 3)]),
            ]);
        }
        {
            let m = Event::new(Source::Other, "uncontrolled.thread", "t.py:3", "x");
            add("uncontrolled_outcome", vec![
                trace(vec![rec("x", &[m.clone()], "passed", 10)]),
                trace(vec![rec("x", &[m], "failed", 10)]),
            ]);
            let e = |v: &str| Event::new(Source::Other, "env.get", "t.py:2", v);
            add("env_event_value", vec![
                trace(vec![rec("x", &[e("MY_FLAG=aa")], "passed", 10)]),
                trace(vec![rec("x", &[e("MY_FLAG=bb")], "failed", 10)]),
            ]);
        }
        add("empty_runs", vec![trace(vec![]), trace(vec![])]);
        {
            let a = trace(vec![rec("p", &[], "passed", 10), rec("v", &[], "passed", 10)]);
            let b = trace(vec![rec("v", &[], "passed", 10), rec("p", &[], "passed", 10)]);
            add("same_order", vec![a.clone(), a.clone()]);
            add("order_change", vec![a, b]);
        }
        add("three_runs", vec![one("1", "passed"), one("1", "passed"), trace(vec![rec("x", &[t("2")], "passed", 10)])]);
        {
            let pol = rec("p", &[r("1")], "passed", 10);
            let vic_serial = rec("v", &[r("2")], "passed", 10);
            let mut pol2 = pol.clone();
            pol2.worker = Some("gw0".into());
            pol2.worker_index = Some(0);
            let mut vic_par = rec("v", &[t("3")], "passed", 10);
            vic_par.worker = Some("gw1".into());
            vic_par.worker_index = Some(0);
            add("placement", vec![trace(vec![pol, vic_serial]), trace(vec![pol2, vic_par])]);
            add("two_serial_not_placement", vec![
                trace(vec![rec("v", &[r("2")], "passed", 10)]),
                trace(vec![rec("v", &[t("3")], "passed", 10)]),
            ]);
        }
        {
            let f = |d: &str| serde_json::json!([{ "path": "data.txt", "digest": d }]);
            let mk = |d: &str| meta_extra(with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE), "files_read_outside_tests", f(d));
            add("files_outside_differ", vec![mk("2:aa"), mk("2:bb")]);
            add("files_outside_same", vec![mk("2:aa"), mk("2:aa")]);
            add("files_outside_one_run", vec![mk("2:aa"), with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE)]);
        }
        for k in ["deps", "code"] {
            let mut a: Vec<(&str, &str)> = BASE.to_vec();
            let mut b = a.clone();
            a.push((k, "3 files aa"));
            b.push((k, "3 files bb"));
            add(&format!("input_{k}"), vec![
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &a),
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &b),
            ]);
        }
        {
            let mut a: Vec<(&str, &str)> = BASE.iter().filter(|(k, _)| *k != "hashseed").copied().collect();
            a.push(("hashseed", "<random>"));
            add("random_hashseed", vec![
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &a),
                with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &a),
            ]);
        }
        {
            let strip = |mut tr: Trace| {
                tr.header.meta.as_object_mut().unwrap().remove("provable");
                tr
            };
            add("no_sensor", vec![
                strip(with_inputs(trace_without_sensor(vec![rec("x", &[t("1")], "passed", 100)]), &BASE)),
                strip(with_inputs(trace_without_sensor(vec![rec("x", &[t("1")], "passed", 100)]), &BASE)),
            ]);
            for (field, value) in [("surface", "deadbeefdeadbeefdeadbeefdeadbeef"), ("runtime", "cpython3.99")] {
                let mk = || {
                    let mut tr = with_inputs(trace(vec![rec("x", &[t("1")], "passed", 100)]), &BASE);
                    tr.header.meta["provable"][field] = serde_json::json!(value);
                    tr
                };
                add(&format!("unknown_{field}"), vec![mk(), mk()]);
            }
            let u = Event::new(Source::Other, "unaccounted.api", "t.py:3", "posix.getxattr");
            let mk = || with_inputs(trace(vec![rec("x", &[u.clone(), t("1")], "passed", 10)]), &BASE);
            add("unaccounted_api", vec![mk(), mk()]);
        }
        {
            let m = Event::new(Source::Other, "uncontrolled.env", "t.py:3", "TMPDIR");
            add("marks_not_proven", vec![
                with_inputs(trace(vec![rec("x", &[m.clone(), t("1")], "passed", 10), rec("y", &[t("1")], "passed", 10)]), &BASE),
                with_inputs(trace(vec![rec("x", &[m, t("1")], "passed", 10), rec("y", &[t("1")], "passed", 10)]), &BASE),
            ]);
            let mk = || meta_extra(with_inputs(trace(vec![rec("x", &[t("1")], "passed", 10)]), &BASE), "not_proven_outside_tests", serde_json::json!(["env:HTTPS_PROXY"]));
            add("not_proven_outside", vec![mk(), mk()]);
        }
        // ---- criterion 6 extras ----
        // a generated pair where every test diverges: a serial run against a parallel one, different values,
        // different outcomes, truncated records, extra events, threads
        {
            let mut sa = Vec::new();
            let mut pb = Vec::new();
            for i in 0..300u64 {
                let id = format!("tests/f{}.test.ts::suite::case {i}", i % 17);
                let n = 2 + (i % 9) as usize;
                let ea: Vec<Event> = (0..n).map(|k| t(&format!("{i}.{k}"))).collect();
                let mut eb = ea.clone();
                match i % 5 {
                    0 => eb[n / 2] = r(&format!("{i}")),
                    1 => eb.push(Event::new(Source::Fs, "fs.readdir", "f.ts:3", format!("{i}"))),
                    2 => eb[0] = t("x").with_thread(1),
                    _ => eb[n - 1] = t(&format!("{i}.changed")),
                }
                let max = if i % 7 == 0 { 2 } else { 100 };
                let mut a = rec(&id, &ea, if i % 11 == 0 { "failed" } else { "passed" }, max);
                a.index = i;
                let mut b = rec(&id, &eb, if i % 13 == 0 { "failed" } else { "passed" }, max);
                b.index = i;
                b.worker = Some(format!("w{}", i % 4));
                b.worker_index = Some(i / 4);
                sa.push(a);
                pb.push(b);
            }
            let mut a = with_inputs(trace(sa), &BASE);
            let mut b = with_inputs(trace(pb), &BASE);
            a.footer = Some(crate::trace::Footer { n_tests: 300, order_digest: "x".into(), missing: vec![], plan_digest: None, late: None });
            b.footer = Some(crate::trace::Footer { n_tests: 300, order_digest: "y".into(), missing: vec!["gone".into()], plan_digest: Some("pd".into()), late: None });
            add("all_diverge", vec![a, b]);
        }
        // env differences with env.list, an uncontrolled event past truncation, a record whose fingerprint does not
        // match its events, and a footer `late` input
        {
            let base: Vec<(&str, &str)> = vec![("tz", "UTC"), ("env:MY_FLAG", "aaaa"), ("env:LISTED", "1"), ("seed", "0")];
            let changed: Vec<(&str, &str)> = vec![("tz", "UTC"), ("env:MY_FLAG", "bbbb"), ("env:LISTED", "2"), ("seed", "0")];
            let mut long: Vec<Event> = (0..10).map(|i| t(&i.to_string())).collect();
            long.push(Event::new(Source::Other, "uncontrolled.child", "t.py:8", "sh"));
            let mk = |inputs: &[(&str, &str)], tamper: &str, diff: &str| {
                let mut bad = rec("tampered", &[t("1"), t("2")], "passed", 10);
                bad.fingerprint = tamper.into();
                let recs = vec![
                    rec("lists", &[env_ev("env.list", "3:abc"), t("1")], "passed", 10),
                    rec("reads", &[env_ev("env.has", "MY_FLAG"), t("1")], "passed", 10),
                    rec("reads_and_differs", &[env_ev("env.get", "MY_FLAG=x"), t(diff)], "passed", 10),
                    rec("late_mark", &long, "passed", 3),
                    bad,
                    rec("plain", &[t("1")], "passed", 10),
                ];
                let mut tr = with_inputs(trace(recs), inputs);
                tr.footer = Some(crate::trace::Footer {
                    n_tests: 6,
                    order_digest: "z".into(),
                    missing: vec![],
                    plan_digest: None,
                    late: Some(serde_json::json!({"inputs": {"late:x": "1"}, "env_read_outside_tests": ["OUTSIDE"]})),
                });
                tr
            };
            add("env_list_truncated_mark_tampered", vec![
                mk(&base, "00000000000000000000000000000000", "1"),
                mk(&changed, "00000000000000000000000000000000", "2"),
            ]);
        }
        out
    }

    /// The r058 integration pairs (tests/r058_false_identical.rs, tests/r058_empty_fingerprint.rs), as the text
    /// those tests write.
    fn golden_r058_cases() -> Vec<(String, Vec<String>)> {
        use crate::provable::{required_controls, surface_digest, SENSOR_CONTRACT};
        let mut out = Vec::new();
        // r058_false_identical: run B's fingerprint field is run A's
        {
            const NODEID: &str = "t.py::test_draw";
            let controls: Vec<String> = required_controls("py-monitoring/1").iter().map(|s| s.to_string()).collect();
            let header = Header::new(
                serde_json::json!({
                    "provable": {"sensor": "py-monitoring/1", "contract": SENSOR_CONTRACT, "surface": surface_digest(), "runtime": "cpython3.13"},
                    "controls": controls,
                    "env_reads_recorded": true,
                    "inputs": {"runtime": "cpython3.13", "runner": "pytest-8.3.2", "seed": "0", "hashseed": "0",
                               "clock": "virtual@2025-01-01Z", "tz": "UTC", "locale": "C", "network": "closed",
                               "fs": "ordered", "entropy": "controlled", "bytecode": "precompiled"},
                }),
                vec![NODEID.to_string()],
            );
            let draw = |v: &str| {
                let mut f = Fingerprinter::default();
                f.push(Event::new(Source::Random, "random.random", "t.py:4", v));
                f.finish(NODEID, 0, "passed")
            };
            let a = draw("0.1");
            let mut b = draw("0.9");
            b.fingerprint = a.fingerprint.clone();
            let footer = crate::trace::Footer { n_tests: 1, order_digest: order_digest(&[NODEID]), missing: vec![], plan_digest: None, late: None };
            let mk = |r: TestRecord| golden_trace_text(&Trace { header: header.clone(), tests: vec![r], footer: Some(footer.clone()) });
            out.push(("r058_false_identical".to_string(), vec![mk(a), mk(b)]));
        }
        // r058_empty_fingerprint: two cached runs, then two fully-cached runs with every control off
        {
            const NODEID: &str = "t.test.ts > draws";
            let controls: Vec<String> = required_controls("node-vitest/1").iter().map(|s| s.to_string()).collect();
            let header = Header::new(
                serde_json::json!({
                    "provable": {"sensor": "node-vitest/1", "contract": SENSOR_CONTRACT, "surface": surface_digest(), "runtime": "node24"},
                    "controls": controls,
                    "env_reads_recorded": true,
                    "inputs": {"runtime": "node24", "runner": "vitest-2.1.0", "seed": "0", "hashseed": "0",
                               "clock": "virtual@2025-01-01Z", "tz": "UTC", "locale": "C", "network": "closed",
                               "fs": "ordered", "entropy": "controlled"},
                }),
                vec![NODEID.to_string()],
            );
            let line = serde_json::json!({
                "type": "test", "nodeid": NODEID, "index": 0, "outcome": "passed", "fingerprint": "",
                "n_events": 0, "truncated": true, "counts": {}, "checkpoints": [], "events": [],
            });
            let footer = serde_json::json!({"type":"footer","n_tests":1,"order_digest": order_digest(&[NODEID])});
            let text = format!("{}\n{line}\n{footer}\n", golden_line("header", serde_json::to_value(&header).unwrap()));
            out.push(("r058_empty_fingerprint".to_string(), vec![text.clone(), text]));
            let header = serde_json::json!({
                "type": "header", "format": "detpy-trace", "version": 1, "encoding": 2,
                "meta": {
                    "provable": {"sensor": "cache-reuse/1", "contract": SENSOR_CONTRACT, "surface": surface_digest(), "runtime": "node24"},
                    "controls": [], "env_reads_recorded": true, "reused_tests": [NODEID],
                    "inputs": { "runtime": "node24", "runner": "vitest-2.1.0" },
                },
                "order": [NODEID],
            });
            let text = format!("{header}\n{line}\n{footer}\n");
            out.push(("r058_all_cached".to_string(), vec![text.clone(), text]));
        }
        out
    }

    #[test]
    #[ignore]
    fn golden_corpus_generate() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("golden");
        std::fs::create_dir_all(&dir).unwrap();
        let mut texts: Vec<(String, Vec<String>, Option<Report>)> = Vec::new();
        for (name, ts) in golden_cases() {
            let labels: Vec<String> = (0..ts.len()).map(|i| format!("run{i}")).collect();
            let mem = verify(&ts, &labels);
            texts.push((name, ts.iter().map(golden_trace_text).collect(), Some(mem)));
        }
        for (name, ts) in golden_r058_cases() {
            texts.push((name, ts, None));
        }
        for (name, ts, mem) in texts {
            let paths: Vec<std::path::PathBuf> = ts
                .iter()
                .enumerate()
                .map(|(i, text)| {
                    let p = dir.join(format!("{name}.run{i}.jsonl"));
                    std::fs::write(&p, text).unwrap();
                    p
                })
                .collect();
            let mut rep = verify_paths(&paths).unwrap();
            golden_labels(&mut rep);
            let json = serde_json::to_string_pretty(&rep).unwrap();
            // the files describe the in-memory case exactly: today's verifier gives the same report for both
            if let Some(mut mem) = mem {
                golden_labels(&mut mem);
                assert_eq!(serde_json::to_string_pretty(&mem).unwrap(), json, "{name}: file round trip");
            }
            std::fs::write(dir.join(format!("{name}.report.json")), format!("{json}\n")).unwrap();
        }
    }
}
