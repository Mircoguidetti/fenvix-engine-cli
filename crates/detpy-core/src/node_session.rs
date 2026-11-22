//! The Node shells' session policy (detjs: `node/src/cache/proof.js`), in Rust as every other non-interface rule
//! (DECISIONS 2026-11-18; review R-032 claim 3): which flags make a result not cacheable (`UNCACHEABLE`, the outcome
//! rule), what a test's and a file's entry is made of (the observation of the capture log: global inputs, the
//! file's items up to the test's end, the environment dependencies, the session's writers), the comparison of a
//! verified result with the fresh one, and the receipt lines. The JavaScript keeps the runtime interface: it
//! gathers the capture logs, calls [`record_session`] once per session and writes what it returns.
//!
//! The JavaScript original is kept as a test-only reference (`node/test/legacy-proof-policy.js`); the equivalence
//! test (`node/test/policy-equivalence.test.js`) runs both on the same inputs.

use std::collections::{BTreeMap, HashMap, HashSet};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::proof::{env_all_digest, env_value_digest, CodeFile, Observed, Store};

/// Flags that make a test (or a file) not cacheable, with their description (order = report order of a flag's
/// first occurrence, not this table's).
pub const UNCACHEABLE: &[(&str, &str)] = &[
    ("spawn", "subprocess"),
    ("worker", "worker thread"),
    ("connect", "network connection"),
    ("udp", "UDP socket"),
    ("net-record", "network recording (--det-record)"),
    ("proc", "reads /proc, /sys or /dev"),
    ("rw", "reads a file another test file or the start-up code wrote"),
    ("entropy", "os entropy (not controlled; use --det-urandom)"),
    ("env-unobserved", "environment reads not observable in this process"),
    ("machine", "reads a machine fact that changes between calls"),
    ("stat", "reads file metadata that is not keyed (times, inode, owner)"),
    ("statfs", "reads file system statistics"),
    ("watch", "watches the file system"),
    ("sqlite", "opens an SQLite database that cannot be keyed by its path"),
    ("resolve", "a module specifier that could not be resolved and is not keyed (bare or mapped)"),
    ("import-glob", "an import.meta.glob call that cannot be keyed"),
    // runtimes other than Node (src/runners: bun test, deno test)
    ("runtime-api", "uses a runtime API whose inputs are not keyed"),
    ("dynamic-import", "a dynamic import whose target is not known before the run"),
    ("unobserved", "the runtime reported an access the capture did not see"),
    ("binding", "reaches native bindings directly (process.binding): reads not observable"),
    ("clock-real", "reads a clock Level 0 does not virtualize"),
    ("keygen", "OS randomness drawn in native crypto (key generation, randomized encryption or signatures)"),
    ("preload", "a preload module read the clock or OS entropy before Level 0 was installed"),
    ("loader", "an off-thread module loader (--loader, module.register): what it reads is not observable"),
    // row JS-09: native code reads files, the environment and the clock where no wrapper sees it
    ("native", "loads a native addon (its reads are not observable)"),
    // audit G-0181: a control that could not be installed leaves its source real and unrecorded
    ("level0-gap", "a Level 0 control could not be installed"),
    // parallel runs (detjs --det-workers): placement-dependent results
    ("placement", "reads the worker or pool id the runner gives its process (depends on placement)"),
    ("carried", "ran after a test file that left process-wide state changed in the same process"),
    ("cross-worker", "touched a path or port another test file running in parallel also touched"),
];

/// A flag a shell reports that this table does not know: never ignored (a source the engine cannot attribute
/// refuses reuse).
const UNKNOWN_FLAG: &str = "an input the engine cannot key";

/// The description of an uncacheable flag (None: the flag does not refuse caching).
pub fn uncacheable_flag(flag: &str) -> Option<&'static str> {
    Some(UNCACHEABLE.iter().find(|(f, _)| *f == flag).map(|(_, d)| *d).unwrap_or(UNKNOWN_FLAG))
}

/// The outcome rule and the flag rule: why a result with `outcome` and these flags (in their order of first
/// occurrence) is not cached, None when it is.
pub fn uncacheable(flags: &[(String, String)], outcome: &str) -> Option<String> {
    if !matches!(outcome, "passed" | "skipped" | "todo") {
        return Some(format!("outcome {outcome}"));
    }
    flags.iter().find_map(|(f, detail)| uncacheable_flag(f).map(|d| format!("{d}: {detail}")))
}

/// The founder's rule for the Node cache: a result may be stored (and so reused) only when
/// [`crate::provable::judge`] calls the test provable. The cache must not have a reuse rule of its own, so this is
/// the only place the Node policy decides provability, and it decides it by calling the one predicate.
///
/// `provable` is the `meta.provable` the process that ran the file declared (`None` = none, which judge() answers
/// NOT PROVEN for every test). `unaccounted` and `marks` are that test's own findings. Returns the reason the
/// result is not cached, or None when it may be.
fn not_provable(
    provable: Option<&Value>,
    controls: &[String],
    unaccounted: &[String],
    marks: &[String],
    outside: &[String],
) -> Option<(String, String)> {
    let get = |k: &str| provable.and_then(|h| h.get(k)).and_then(|v| v.as_str());
    let att = crate::provable::Attestation {
        sensor: get("sensor"),
        contract: provable.and_then(|h| h.get("contract")).and_then(|v| v.as_u64()).map(|v| v as u32),
        surface: get("surface"),
        runtime: get("runtime"),
        controls,
        unaccounted,
        marks,
        outside,
    };
    match crate::provable::judge(&att) {
        crate::provable::Verdict::Provable => None,
        crate::provable::Verdict::NotProven { kind, detail } => Some((kind, detail)),
    }
}

/// The reason a result is not cached, or None when it may be: the one predicate decides *whether*, this decides
/// only which of two true descriptions to print.
///
/// The order follows [`crate::provable::judge`]'s own reasoning about clause order. A missing or mismatched sensor
/// ("sensor", "runtime") is the most fundamental gap and comes first. Otherwise the channel rule below is
/// preferred when it names the gap, because "network connection" tells the reader more than "not accounted for:
/// api:net._normalizeArgs"; the sensor's own finding answers when no channel rule names it (the case this wiring
/// exists for). Either way the verdict is the predicate's: if it says NOT PROVEN, nothing is stored.
fn why_not_cached(
    provable: Option<&Value>,
    controls: &[String],
    unaccounted: &[String],
    flags: &[(String, String)],
    outcome: &str,
) -> Option<String> {
    let judged = not_provable(provable, controls, unaccounted, &[], &[]);
    if let Some((kind, detail)) = &judged {
        if kind == "sensor" || kind == "runtime" || kind == "config" {
            return Some(format!("{kind}: {detail}"));
        }
    }
    if let Some(w) = uncacheable(flags, outcome) {
        return Some(w);
    }
    judged.map(|(kind, detail)| format!("{kind}: {detail}"))
}

/// A test as a capture reports it.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CapturedTest {
    pub id: String,
    /// Number of the file's items logged before the test ended (its inputs are a prefix of the log).
    #[serde(default)]
    pub upto: usize,
    pub outcome: String,
    #[serde(default)]
    pub fingerprint: Option<String>,
    #[serde(default)]
    pub duration: Option<f64>,
    /// What the general sensor saw and could not place, as `kind:name` (`api:v8.getHeapStatistics`). Handed to
    /// [`crate::provable::judge`]; the cache has no say of its own over these.
    #[serde(default)]
    pub unaccounted: Vec<String>,
}

/// The capture of one test file (one process or realm of a runner shell).
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Capture {
    pub label: String,
    #[serde(rename = "fileId")]
    pub file_id: String,
    #[serde(default)]
    pub project: Option<String>,
    #[serde(default)]
    pub duration: Option<f64>,
    #[serde(default)]
    pub ok: bool,
    #[serde(default)]
    pub notes: Vec<String>,
    #[serde(default)]
    pub tests: Vec<CapturedTest>,
    #[serde(default)]
    pub items: Vec<Vec<Value>>,
    /// `meta.provable` of the process that ran this file (src/provable.js `header`): sensor, contract, surface,
    /// runtime. `None` = that process declared no sensor, which makes every test of the file NOT PROVEN.
    #[serde(default)]
    pub provable: Option<Value>,
    /// Why there is no declaration, for the report.
    #[serde(default)]
    pub provable_absent: Option<String>,
}

/// Everything [`record_session`] needs from the JavaScript session.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct RecordInput {
    /// The main process's items (`CAPTURE.global`).
    #[serde(default)]
    pub global: Vec<Vec<Value>>,
    /// Test files known to the runner (`specKeys`): infrastructure's reads of them are not global inputs.
    #[serde(default)]
    pub spec_keys: Vec<String>,
    /// `meta.controls`: the `--det` controls this run had on. [`crate::provable::judge`] refuses a run missing
    /// any control the accounting rests on, so a disabled control stores nothing (audit G-0123).
    #[serde(default)]
    pub controls: Vec<String>,
    #[serde(default)]
    pub captures: Vec<Capture>,
    /// The environment at session start (own string values only).
    #[serde(default)]
    pub cur_env: BTreeMap<String, String>,
    #[serde(default)]
    pub urandom: bool,
    #[serde(default)]
    pub epoch_ms: Option<i64>,
    pub run_id: String,
    pub runtime: String,
    #[serde(default)]
    pub startup: String,
    /// Configuration digest per project ("" = the session's).
    #[serde(default)]
    pub config_for: BTreeMap<String, String>,
    #[serde(default)]
    pub uncacheable_projects: Vec<String>,
    #[serde(default)]
    pub verify: bool,
    /// nodeid -> outcome of the result that would have been reused (verify mode).
    #[serde(default)]
    pub hits: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Verified {
    pub nodeid: String,
    pub cached: String,
    pub fresh: String,
    pub same: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct RanFile {
    pub duration: f64,
    pub tests: usize,
    pub ok: bool,
}

/// What [`record_session`] did (the store was changed in place).
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct RecordOutput {
    pub recorded: usize,
    /// (nodeid, reason), in first-occurrence order (a later reason for the same id replaces the text).
    pub not_cached: Vec<(String, String)>,
    pub verified: Vec<Verified>,
    pub ran_files: BTreeMap<String, RanFile>,
    pub session_written: BTreeMap<String, Vec<String>>,
}

/// The id of a file entry (`idOf`).
pub fn id_of(file_id: &str, project: &str) -> String {
    if project.is_empty() {
        file_id.to_string()
    } else {
        format!("{file_id}@@{project}")
    }
}

/// The id of a test entry (`testKey`): the project after the file part.
pub fn test_key(test_id: &str, project: &str) -> String {
    if project.is_empty() {
        return test_id.to_string();
    }
    // already qualified: a Vitest test of a named project carries its project in its id (src/vitest/shell.js)
    if test_id.split("::").next().is_some_and(|head| head.contains("@@")) {
        return test_id.to_string();
    }
    match test_id.find("::") {
        None => format!("{test_id}@@{project}"),
        Some(i) => format!("{}@@{project}{}", &test_id[..i], &test_id[i..]),
    }
}

fn s(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(x)) => x.clone(),
        Some(Value::Null) | None => String::new(),
        Some(other) => other.to_string().trim_matches('"').to_string(),
    }
}

/// An insertion-ordered map with "first value wins" or "set" semantics as needed.
#[derive(Clone, Default)]
struct OrderedMap {
    keys: Vec<String>,
    vals: HashMap<String, String>,
}

impl OrderedMap {
    fn insert_first(&mut self, k: &str, v: &str) {
        if !self.vals.contains_key(k) {
            self.keys.push(k.to_string());
            self.vals.insert(k.to_string(), v.to_string());
        }
    }
    fn set(&mut self, k: &str, v: &str) {
        if !self.vals.contains_key(k) {
            self.keys.push(k.to_string());
        }
        self.vals.insert(k.to_string(), v.to_string());
    }
    fn remove(&mut self, k: &str) {
        if self.vals.remove(k).is_some() {
            self.keys.retain(|x| x != k);
        }
    }
    fn has(&self, k: &str) -> bool {
        self.vals.contains_key(k)
    }
    fn items(&self) -> Vec<(String, String)> {
        self.keys.iter().map(|k| (k.clone(), self.vals[k].clone())).collect()
    }
}

/// Writers of this session and of earlier sessions: path -> labels in order of first addition.
type Writers = HashMap<String, Vec<String>>;

/// The observation of a file's log at one point.
struct Snapshot {
    flags: Vec<(String, String)>,
    env: Vec<(String, String)>,
    data: Vec<(String, String)>,
    content: Vec<u32>,
    clock: bool,
}

struct Observation<'a> {
    label: String,
    base: Vec<(String, String)>,
    flags: OrderedMap,
    env: OrderedMap,
    data_keys: Vec<(String, String)>,
    data_seen: HashSet<(String, String)>,
    content: Vec<u32>,
    content_seen: HashSet<u32>,
    clock: bool,
    rw_first: Option<String>,
    pos: usize,
    writers: &'a Writers,
}

struct Ctx<'a> {
    writers: &'a Writers,
    env_all: String,
    cur_env: &'a BTreeMap<String, String>,
    urandom: bool,
    file_ix: HashMap<(String, String), u32>,
}

impl Ctx<'_> {
    /// `envDep`: the whole environment's digest for "*", else the variable's value digest ("-" when unset).
    fn env_dep(&self, name: &str) -> String {
        if name == "*" {
            self.env_all.clone()
        } else {
            env_value_digest(self.cur_env.get(name).map(|v| v.as_str()))
        }
    }

    fn code_index(&mut self, store: &mut Store, rel: &str, d: &str) -> u32 {
        let k = (rel.to_string(), d.to_string());
        if let Some(&i) = self.file_ix.get(&k) {
            return i;
        }
        let i = store.add_file(CodeFile {
            path: rel.to_string(),
            skeleton: d.to_string(),
            hooks: d.to_string(),
            content: d.to_string(),
            units: vec![],
            imports: vec![],
        });
        self.file_ix.insert(k, i);
        i
    }
}

impl<'a> Observation<'a> {
    fn new(label: &str, base: Vec<(String, String)>, writers: &'a Writers) -> Self {
        Observation {
            label: label.to_string(),
            base,
            flags: OrderedMap::default(),
            env: OrderedMap::default(),
            data_keys: Vec::new(),
            data_seen: HashSet::new(),
            content: Vec::new(),
            content_seen: HashSet::new(),
            clock: false,
            rw_first: None,
            pos: 0,
            writers,
        }
    }

    fn take(&mut self, it: &[Value], ctx: &mut Ctx<'_>, store: &mut Store) {
        match s(it.first()).as_str() {
            "data" => {
                let (k, dep) = (s(it.get(1)), s(it.get(2)));
                let dk = (k.clone(), dep.clone());
                if self.data_seen.insert(dk.clone()) {
                    self.data_keys.push(dk);
                    if self.rw_first.is_none() {
                        if let Some(ws) = self.writers.get(&k) {
                            let others: Vec<&String> = ws.iter().filter(|w| **w != self.label).collect();
                            if !others.is_empty() {
                                let joined = others.iter().map(|w| w.as_str()).collect::<Vec<_>>().join(",");
                                let who = if joined.is_empty() { "start-up".to_string() } else { joined };
                                self.rw_first = Some(format!("{k} written by {who}"));
                            }
                        }
                    }
                }
            }
            "code" => {
                let i = ctx.code_index(store, &s(it.get(1)), &s(it.get(2)));
                if self.content_seen.insert(i) {
                    self.content.push(i);
                }
            }
            "env" => {
                let n = s(it.get(1));
                if !self.env.has(&n) {
                    let d = ctx.env_dep(&n);
                    self.env.insert_first(&n, &d);
                }
            }
            "clock" => self.clock = true,
            "flag" => {
                // as the JavaScript template literal `${detail}` writes it
                let detail = match it.get(2) {
                    Some(Value::String(x)) => x.clone(),
                    Some(Value::Null) => "null".to_string(),
                    None => "undefined".to_string(),
                    Some(Value::Object(_)) => "[object Object]".to_string(),
                    Some(Value::Array(a)) => js_join(a),
                    Some(v) => v.to_string(),
                };
                self.flags.insert_first(&s(it.get(1)), &detail);
            }
            _ => {}
        }
    }

    fn at(&mut self, items: &[Vec<Value>], upto: usize, ctx: &mut Ctx<'_>, store: &mut Store) -> Snapshot {
        while self.pos < upto && self.pos < items.len() {
            let it = items[self.pos].clone();
            self.take(&it, ctx, store);
            self.pos += 1;
        }
        let mut f = self.flags.clone();
        for (k, d) in &self.base {
            f.insert_first(k, d);
        }
        if let Some(rw) = &self.rw_first {
            f.insert_first("rw", rw);
        }
        if f.has("entropy") && ctx.urandom {
            f.remove("entropy");
        }
        Snapshot {
            flags: f.items(),
            env: self.env.items(),
            data: self.data_keys.clone(),
            content: self.content.clone(),
            clock: self.clock,
        }
    }
}

/// `String(array)` in JavaScript: elements joined by ",", null as "", objects as "[object Object]", arrays
/// recursively.
fn js_join(a: &[Value]) -> String {
    a.iter()
        .map(|x| match x {
            Value::String(t) => t.clone(),
            Value::Null => String::new(),
            Value::Object(_) => "[object Object]".to_string(),
            Value::Array(b) => js_join(b),
            o => o.to_string(),
        })
        .collect::<Vec<_>>()
        .join(",")
}

fn observed(snap: &Snapshot, outcome: &str, report: Value, fingerprint: String, duration: f64, input: &RecordInput, config: &str) -> Observed {
    Observed {
        outcome: outcome.to_string(),
        report,
        fingerprint,
        duration,
        run: input.run_id.clone(),
        config: config.to_string(),
        runtime: input.runtime.clone(),
        epoch: if snap.clock { input.epoch_ms } else { None },
        env: snap.env.clone(),
        data: snap.data.iter().map(|(k, v)| (k.as_str().into(), v.as_str().into())).collect(),
        fixtures: Vec::new(),
        content: snap.content.clone(),
        skeleton: vec![],
        hooks: vec![],
        units: vec![],
        startup: input.startup.clone(),
    }
}

/// Record the entries of the files that ran in a Node session (`ProofSession.recordAll`): for each capture, each
/// test's entry (its inputs: the global items and the file's items up to the test's end) and the file's entry (the
/// whole log), or why it is not cached; the session's written paths; the verified comparisons.
pub fn record_session(store: &mut Store, input: &RecordInput) -> RecordOutput {
    let spec: HashSet<&str> = input.spec_keys.iter().map(|x| x.as_str()).collect();
    let global: Vec<Vec<Value>> = input
        .global
        .iter()
        .filter(|it| {
            !(s(it.first()) == "data"
                && matches!(s(it.get(3)).as_str(), "infra" | "plugin")
                && spec.contains(s(it.get(1)).as_str()))
        })
        .cloned()
        .collect();
    // writers of this session and of earlier sessions
    let mut writers: Writers = HashMap::new();
    let mut order: Vec<String> = Vec::new();
    let mut add_w = |writers: &mut Writers, k: String, l: String| {
        let e = writers.entry(k.clone()).or_insert_with(|| {
            order.push(k);
            Vec::new()
        });
        if !e.contains(&l) {
            e.push(l);
        }
    };
    for it in &input.global {
        if s(it.first()) == "write" {
            add_w(&mut writers, s(it.get(1)), String::new());
        }
    }
    for c in &input.captures {
        for it in &c.items {
            if s(it.first()) == "write" {
                add_w(&mut writers, s(it.get(1)), c.label.clone());
            }
        }
    }
    let past = store.written.clone();
    for (k, ls) in &past {
        for l in ls {
            add_w(&mut writers, k.clone(), l.clone());
        }
    }
    let session_written: BTreeMap<String, Vec<String>> = writers.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
    let mut ctx = Ctx {
        writers: &writers,
        env_all: env_all_digest(&input.cur_env),
        cur_env: &input.cur_env,
        urandom: input.urandom,
        file_ix: HashMap::new(),
    };
    let unc: HashSet<&str> = input.uncacheable_projects.iter().map(|x| x.as_str()).collect();
    let mut out = RecordOutput::default();
    let mut nc = OrderedMap::default();
    let verify_one = |out: &mut RecordOutput, nid: &str, outcome: &str| {
        if !input.verify {
            return;
        }
        if let Some(cached) = input.hits.get(nid) {
            out.verified.push(Verified {
                nodeid: nid.to_string(),
                cached: cached.clone(),
                fresh: outcome.to_string(),
                same: cached == outcome,
            });
        }
    };
    for c in &input.captures {
        let proj = c.project.clone().unwrap_or_default();
        let mid = id_of(&c.file_id, &proj);
        out.ran_files.insert(
            mid.clone(),
            RanFile { duration: (c.duration.unwrap_or(0.0) * 1000.0).round() / 1000.0, tests: c.tests.len(), ok: c.ok },
        );
        if unc.contains(proj.as_str()) {
            continue;
        }
        let config = input.config_for.get(&proj).cloned().unwrap_or_default();
        let base: Vec<(String, String)> = if c.notes.iter().any(|n| n.starts_with("process.env not replaceable")) {
            vec![("env-unobserved".into(), "process.env".into())]
        } else {
            vec![]
        };
        let mut obs = Observation::new(&c.label, base, &writers);
        for it in &global {
            obs.take(it, &mut ctx, store);
        }
        // tests in log order (each one's inputs are a prefix of the next one's)
        let mut by_order: Vec<usize> = (0..c.tests.len()).collect();
        by_order.sort_by(|&a, &b| c.tests[a].upto.cmp(&c.tests[b].upto).then(a.cmp(&b)));
        let mut snaps: Vec<Option<Snapshot>> = (0..c.tests.len()).map(|_| None).collect();
        for i in by_order {
            snaps[i] = Some(obs.at(&c.items, c.tests[i].upto, &mut ctx, store));
        }
        let mut ids = Vec::new();
        for (i, t) in c.tests.iter().enumerate() {
            let nid = test_key(&t.id, &proj);
            ids.push(Value::String(t.id.clone()));
            let o = snaps[i].as_ref().expect("snapshot");
            // the one predicate first: a channel the sensor could not place refuses reuse whatever the
            // channel list below says (crates/detpy-core/src/provable.rs judge)
            let why = why_not_cached(c.provable.as_ref(), &input.controls, &t.unaccounted, &o.flags, &t.outcome);
            verify_one(&mut out, &nid, &t.outcome);
            if let Some(w) = why {
                store.remove(&nid);
                nc.set(&nid, &w);
                continue;
            }
            let report = serde_json::json!({ "outcome": t.outcome });
            store.record(
                &nid,
                observed(o, &t.outcome, report, t.fingerprint.clone().unwrap_or_default(), t.duration.unwrap_or(0.0), input, &config),
            );
            out.recorded += 1;
        }
        let o = obs.at(&c.items, c.items.len(), &mut ctx, store);
        let outcome = if c.ok { "passed" } else { "failed" };
        verify_one(&mut out, &mid, outcome);
        // the file's entry lets the whole file be skipped, so it answers for every test in it
        let file_unaccounted: Vec<String> = {
            let mut v: Vec<String> = c.tests.iter().flat_map(|t| t.unaccounted.iter().cloned()).collect();
            v.sort();
            v.dedup();
            v
        };
        let file_why =
            why_not_cached(c.provable.as_ref(), &input.controls, &file_unaccounted, &o.flags, outcome);
        if let Some(w) = file_why {
            store.remove(&mid);
            nc.set(&mid, &w);
            continue;
        }
        let report = serde_json::json!({
            "kind": "file", "file": c.file_id,
            "project": if proj.is_empty() { Value::Null } else { Value::String(proj.clone()) },
            "tests": ids,
        });
        store.record(&mid, observed(&o, outcome, report, String::new(), c.duration.unwrap_or(0.0), input, &config));
    }
    for (p, ws) in &session_written {
        let e = store.written.entry(p.clone()).or_default();
        e.extend(ws.iter().cloned());
    }
    out.not_cached = nc.items();
    out.session_written = session_written;
    out
}

/// The receipt lines of a session (`writeReceipts`): one per decided result, reused (or, in verify mode, would
/// reuse) first, in decision order, then the misses. `hits`: (nodeid, receipt as a JSON object text, its keys in
/// the session's order); `misses`: (nodeid, why).
pub fn receipt_lines(hits: &[(String, String)], misses: &[(String, String)], verify: bool) -> String {
    let mut lines: Vec<String> = Vec::new();
    for (nid, r) in hits {
        let inner = r.trim().strip_prefix('{').and_then(|x| x.strip_suffix('}')).unwrap_or("").trim();
        let mut l = format!("{{\"nodeid\":{},\"reused\":{}", Value::String(nid.clone()), !verify);
        if verify {
            l.push_str(",\"would_reuse\":true");
        }
        if !inner.is_empty() {
            l.push(',');
            l.push_str(inner);
        }
        l.push('}');
        lines.push(l);
    }
    for (nid, why) in misses {
        lines.push(format!(
            "{{\"nodeid\":{},\"reused\":false,\"why\":{}}}",
            Value::String(nid.clone()),
            Value::String(why.clone())
        ));
    }
    if lines.is_empty() {
        String::new()
    } else {
        format!("{}\n", lines.join("\n"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outcome_and_flag_rules() {
        assert_eq!(uncacheable(&[], "failed").as_deref(), Some("outcome failed"));
        assert_eq!(uncacheable(&[], "todo"), None);
        let f = vec![("spawn".to_string(), "ls".to_string()), ("connect".into(), "h".into())];
        assert_eq!(uncacheable(&f, "passed").as_deref(), Some("subprocess: ls"));
        // a flag the table does not know refuses reuse (P-041): it is never ignored
        let u = vec![("note".to_string(), "x".to_string()), ("spawn".to_string(), "ls".to_string())];
        assert_eq!(uncacheable(&u, "passed").as_deref(), Some("an input the engine cannot key: x"));
    }

    #[test]
    fn keys_carry_the_project_after_the_file() {
        assert_eq!(test_key("a.test.js::x", "p"), "a.test.js@@p::x");
        assert_eq!(test_key("a.test.js", "p"), "a.test.js@@p");
        assert_eq!(test_key("a.test.js::x", ""), "a.test.js::x");
        assert_eq!(test_key("a.test.js@@p::x", "p"), "a.test.js@@p::x");
        assert_eq!(id_of("a.test.js", "p"), "a.test.js@@p");
    }

    #[test]
    fn a_read_of_a_file_another_label_wrote_refuses_the_test_and_entropy_follows_urandom() {
        let d = tempfile::tempdir().unwrap();
        let mut store = Store::load(d.path());
        let j = |v: Value| -> Vec<Value> { v.as_array().unwrap().clone() };
        // a well-formed Node sensor declaration and every control it rests on, so `judge` passes the clean writer
        // and the refusal below is the cross-file read, the thing this test is about
        let header = serde_json::json!({
            "sensor": "node-surface/1", "contract": crate::provable::SENSOR_CONTRACT,
            "surface": crate::provable::surface_digest(), "runtime": "node22",
        });
        let controls: Vec<String> =
            crate::provable::required_controls("node-surface/1").iter().map(|s| s.to_string()).collect();
        let input = RecordInput {
            captures: vec![
                Capture {
                    provable: Some(header.clone()),
                    label: "w".into(), file_id: "w.test.js".into(), ok: true,
                    tests: vec![CapturedTest { id: "w.test.js::w".into(), upto: 1, outcome: "passed".into(), ..Default::default() }],
                    items: vec![j(serde_json::json!(["write", "out.txt"]))],
                    ..Default::default()
                },
                Capture {
                    provable: Some(header.clone()),
                    label: "r".into(), file_id: "r.test.js".into(), ok: true,
                    tests: vec![CapturedTest { id: "r.test.js::r".into(), upto: 2, outcome: "passed".into(), ..Default::default() }],
                    items: vec![j(serde_json::json!(["data", "out.txt", "f:1"])), j(serde_json::json!(["flag", "entropy", "crypto"]))],
                    ..Default::default()
                },
            ],
            run_id: "R".into(), runtime: "T".into(), urandom: true, controls,
            ..Default::default()
        };
        let out = record_session(&mut store, &input);
        assert!(store.tests.contains_key("w.test.js::w"));
        assert_eq!(out.not_cached[0].0, "r.test.js::r");
        assert!(out.not_cached[0].1.starts_with("reads a file another test file or the start-up code wrote: out.txt written by w"));
        assert_eq!(out.session_written["out.txt"], vec!["w".to_string()]);
    }

    #[test]
    fn receipt_lines_keep_the_receipt_fields_after_the_id() {
        let l = receipt_lines(&[("a".into(), "{\"key\":\"k\",\"kind\":\"file\"}".into())], &[("b".into(), "new: x".into())], true);
        assert_eq!(l, "{\"nodeid\":\"a\",\"reused\":false,\"would_reuse\":true,\"key\":\"k\",\"kind\":\"file\"}\n{\"nodeid\":\"b\",\"reused\":false,\"why\":\"new: x\"}\n");
        assert_eq!(receipt_lines(&[], &[], false), "");
    }
}
