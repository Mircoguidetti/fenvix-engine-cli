//! Node.js bindings for detpy-core (napi-rs), loaded by the `detjs` shells
//! for Vitest and Jest (`node/`).
//!
//! The API mirrors the Python bindings (`crates/detpy-py`) so that both shells
//! produce the same trace and cassette formats and one verifier reads both.
//! Seeds are 64-bit and cross the boundary as `BigInt`.

use detpy_core::backend::Backend;
use detpy_core::cassette::{Cassette as CoreCassette, Direction};
use detpy_core::event::{Event, Source};
use detpy_core::fingerprint::digest_bytes;
use detpy_core::recorder::{Recorder as CoreRecorder, RecorderConfig};
use detpy_core::trace::Header;
use detpy_core::{backend::EventSink, order, trace, verify as v};
use napi::bindgen_prelude::*;
use napi_derive::napi;
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn io_err(e: std::io::Error) -> Error {
    Error::new(Status::GenericFailure, e.to_string())
}

fn bad(msg: impl Into<String>) -> Error {
    Error::new(Status::InvalidArg, msg.into())
}

fn to_u64(b: &BigInt) -> Result<u64> {
    let (signed, value, lossless) = b.get_u64();
    if signed || !lossless {
        return Err(bad("seed must be a non-negative 64-bit integer"));
    }
    Ok(value)
}

#[napi]
pub const ENCODING_VERSION: u32 = detpy_core::event::ENCODING_VERSION;
#[napi]
pub const TRACE_VERSION: u32 = trace::TRACE_VERSION;

/// Separator between the fields of a packed event (see `recordPacked`).
const FIELD_SEP: char = '\u{1f}';
/// Separator between packed events.
const EVENT_SEP: char = '\u{1e}';

/// Per-test fingerprinting recorder that streams a trace file.
#[napi]
pub struct Recorder {
    inner: Mutex<CoreRecorder>,
}

#[napi(object)]
pub struct FinishedTest {
    pub nodeid: String,
    pub outcome: String,
    pub fingerprint: String,
    pub n_events: f64,
}

#[napi]
impl Recorder {
    #[napi(constructor)]
    pub fn new(max_events: Option<u32>, checkpoint_every: Option<u32>) -> Self {
        Recorder {
            inner: Mutex::new(CoreRecorder::new(RecorderConfig {
                max_events: max_events.unwrap_or(10_000) as usize,
                checkpoint_every: checkpoint_every.unwrap_or(256) as u64,
            })),
        }
    }

    /// Start streaming the trace to `path`. `metaJson` is free-form JSON.
    #[napi]
    pub fn open(&self, path: String, meta_json: String, order: Vec<String>) -> Result<()> {
        let meta: serde_json::Value = serde_json::from_str(&meta_json).map_err(|e| bad(format!("bad meta json: {e}")))?;
        lock(&self.inner).open(&PathBuf::from(path), &Header::new(meta, order)).map_err(io_err)
    }

    #[napi]
    pub fn begin_test(&self, nodeid: String, index: u32) -> Result<()> {
        lock(&self.inner).begin_test(&nodeid, index as u64).map_err(io_err)
    }

    /// Record one event for the current test (ignored outside tests).
    #[napi]
    pub fn record(&self, source: String, op: String, site: String, value: String, thread: Option<u32>) {
        lock(&self.inner).record(Event { thread: thread.unwrap_or(0), source: Source::parse(&source), op, site, value });
    }

    /// Record many events in one call: events separated by U+001E, fields
    /// (`source`, `op`, `site`, `value`) by U+001F. The JS shell buffers its
    /// hot-path events this way to keep the boundary crossings few.
    #[napi]
    pub fn record_packed(&self, packed: String) -> Result<u32> {
        let mut r = lock(&self.inner);
        let mut n = 0;
        for ev in packed.split(EVENT_SEP) {
            if ev.is_empty() {
                continue;
            }
            let mut f = ev.splitn(4, FIELD_SEP);
            let (Some(s), Some(o), Some(at), Some(val)) = (f.next(), f.next(), f.next(), f.next()) else {
                return Err(bad(format!("malformed packed event {ev:?}")));
            };
            r.record(Event { thread: 0, source: Source::parse(s), op: o.to_owned(), site: at.to_owned(), value: val.to_owned() });
            n += 1;
        }
        Ok(n)
    }

    /// Finish the current test; returns its fingerprint (null if no test was open).
    #[napi]
    pub fn end_test(&self, outcome: String) -> Result<Option<String>> {
        Ok(lock(&self.inner).end_test(&outcome).map_err(io_err)?.map(|r| r.fingerprint))
    }

    /// Close the trace; returns the digest of the executed order.
    #[napi]
    pub fn close(&self) -> Result<Option<String>> {
        Ok(lock(&self.inner).close().map_err(io_err)?.map(|f| f.order_digest))
    }

    #[napi(getter)]
    pub fn in_test(&self) -> bool {
        lock(&self.inner).in_test()
    }

    #[napi(getter)]
    pub fn current_events(&self) -> f64 {
        lock(&self.inner).current_events() as f64
    }

    #[napi(getter)]
    pub fn dropped(&self) -> f64 {
        lock(&self.inner).dropped as f64
    }

    #[napi]
    pub fn finished(&self) -> Vec<FinishedTest> {
        lock(&self.inner)
            .finished()
            .iter()
            .map(|f| FinishedTest {
                nodeid: f.nodeid.clone(),
                outcome: f.outcome.clone(),
                fingerprint: f.fingerprint.clone(),
                n_events: f.n_events as f64,
            })
            .collect()
    }
}

/// Network cassette (record/replay of outbound connections).
#[napi]
pub struct Cassette {
    inner: Mutex<CoreCassette>,
}

#[napi(object)]
pub struct ConnectionInfo {
    pub host: String,
    pub port: u32,
    pub tls: bool,
    pub n_segments: u32,
}

#[napi(object)]
pub struct Segment {
    pub dir: String,
    pub data: Buffer,
}

fn parse_dir(dir: &str) -> Result<Direction> {
    Direction::parse(dir).ok_or_else(|| bad(format!("direction must be send/recv, got {dir:?}")))
}

fn port16(port: u32) -> Result<u16> {
    u16::try_from(port).map_err(|_| bad(format!("bad port {port}")))
}

#[napi]
impl Cassette {
    #[napi(constructor)]
    pub fn new() -> Self {
        Cassette { inner: Mutex::new(CoreCassette::default()) }
    }

    #[napi(factory)]
    pub fn load(path: String) -> Result<Self> {
        Ok(Cassette { inner: Mutex::new(CoreCassette::load(&PathBuf::from(path)).map_err(io_err)?) })
    }

    #[napi]
    pub fn save(&self, path: String) -> Result<()> {
        lock(&self.inner).save(&PathBuf::from(path)).map_err(io_err)
    }

    #[napi]
    pub fn tests(&self) -> Vec<String> {
        lock(&self.inner).tests.keys().cloned().collect()
    }

    #[napi]
    pub fn clear_test(&self, nodeid: String) {
        lock(&self.inner).clear_test(&nodeid)
    }

    #[napi]
    pub fn open_connection(&self, nodeid: String, host: String, port: u32) -> Result<u32> {
        Ok(lock(&self.inner).open(&nodeid, &host, port16(port)?) as u32)
    }

    #[napi]
    pub fn append(&self, nodeid: String, idx: u32, dir: String, data: Buffer) -> Result<()> {
        let dir = parse_dir(&dir)?;
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(&nodeid, idx as usize).ok_or_else(|| bad(format!("{nodeid}#{idx}")))?;
        conn.append(dir, &data);
        Ok(())
    }

    #[napi]
    pub fn set_tls(&self, nodeid: String, idx: u32) -> Result<()> {
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(&nodeid, idx as usize).ok_or_else(|| bad(format!("{nodeid}#{idx}")))?;
        conn.tls = true;
        Ok(())
    }

    /// Index of the `nth` connection of `nodeid` to `host:port`, if recorded.
    #[napi]
    pub fn find(&self, nodeid: String, host: String, port: u32, nth: u32) -> Result<Option<u32>> {
        Ok(lock(&self.inner).find(&nodeid, &host, port16(port)?, nth as usize).map(|(i, _)| i as u32))
    }

    /// Number of recorded connections of `nodeid`.
    #[napi]
    pub fn count(&self, nodeid: String) -> u32 {
        lock(&self.inner).tests.get(&nodeid).map(|c| c.len() as u32).unwrap_or(0)
    }

    #[napi]
    pub fn info(&self, nodeid: String, idx: u32) -> Result<ConnectionInfo> {
        let c = lock(&self.inner);
        let conn = c.connection(&nodeid, idx as usize).ok_or_else(|| bad(format!("{nodeid}#{idx}")))?;
        Ok(ConnectionInfo {
            host: conn.host.clone(),
            port: conn.port as u32,
            tls: conn.tls,
            n_segments: conn.segments.len() as u32,
        })
    }

    #[napi]
    pub fn segments(&self, nodeid: String, idx: u32) -> Result<Vec<Segment>> {
        let c = lock(&self.inner);
        let conn = c.connection(&nodeid, idx as usize).ok_or_else(|| bad(format!("{nodeid}#{idx}")))?;
        Ok(conn
            .segments
            .iter()
            .map(|s| Segment { dir: s.dir.as_str().to_string(), data: Buffer::from(s.data.clone()) })
            .collect())
    }

    #[napi]
    pub fn merge(&self, other: &Cassette) {
        let o = lock(&other.inner).clone();
        lock(&self.inner).merge(o);
    }
}

fn trace_err(e: trace::TraceError) -> Error {
    match e {
        trace::TraceError::Io(e) => io_err(e),
        other => bad(other.to_string()),
    }
}

/// Verify traces of the same suite; returns the report as JSON.
#[napi]
pub fn verify(paths: Vec<String>) -> Result<String> {
    let report = v::verify_paths(&paths).map_err(trace_err)?;
    serde_json::to_string(&report).map_err(|e| Error::from_reason(e.to_string()))
}

/// Verify traces and render a human-readable report.
#[napi]
pub fn verify_text(paths: Vec<String>, show_stable: Option<bool>) -> Result<String> {
    let report = v::verify_paths(&paths).map_err(trace_err)?;
    Ok(v::render_text(&report, show_stable.unwrap_or(false)))
}

#[napi]
pub fn derive_seed(base: BigInt, key: String) -> Result<BigInt> {
    Ok(BigInt::from(order::derive_seed(to_u64(&base)?, &key)))
}

/// The same derived seed as two 32-bit halves `[hi, lo]` (cheap to use in JS).
#[napi]
pub fn derive_seed_words(base: BigInt, key: String) -> Result<Vec<u32>> {
    let s = order::derive_seed(to_u64(&base)?, &key);
    Ok(vec![(s >> 32) as u32, s as u32])
}

/// Hierarchical shuffle of pytest-style ids (`a::b::c`), as in Python.
#[napi]
pub fn shuffle_order(ids: Vec<String>, seed: BigInt) -> Result<Vec<u32>> {
    Ok(order::shuffle_order(&ids, to_u64(&seed)?).into_iter().map(|i| i as u32).collect())
}

/// Permutation of one group of the hierarchical shuffle (`key` = group id).
#[napi]
pub fn shuffle_indices(n: u32, seed: BigInt, key: String) -> Result<Vec<u32>> {
    Ok(order::shuffle_indices(n as usize, to_u64(&seed)?, &key).into_iter().map(|i| i as u32).collect())
}

#[napi]
pub fn order_digest(ids: Vec<String>) -> String {
    trace::order_digest(&ids)
}

/// Short (128-bit) BLAKE3 hex digest of a Buffer or a string (UTF-8).
#[napi]
pub fn digest(data: Either<Buffer, String>) -> String {
    match data {
        Either::A(b) => digest_bytes(&b).short(),
        Either::B(s) => digest_bytes(s.as_bytes()).short(),
    }
}

#[napi(object)]
pub struct MergeResult {
    pub n_tests: u32,
    pub order_digest: String,
    pub skipped: Vec<String>,
}

/// Concatenate partial traces (one per test file, in execution order) into one trace.
#[napi]
pub fn merge_traces(parts: Vec<String>, out: String, meta_json: String, order: Vec<String>) -> Result<MergeResult> {
    let meta: serde_json::Value = serde_json::from_str(&meta_json).map_err(|e| bad(format!("bad meta json: {e}")))?;
    let (footer, skipped) =
        trace::merge_traces(&parts, &PathBuf::from(out), &Header::new(meta, order)).map_err(io_err)?;
    Ok(MergeResult { n_tests: footer.n_tests as u32, order_digest: footer.order_digest, skipped })
}

/// JSON description of the interception backends and their capabilities.
#[napi]
pub fn backends() -> String {
    let all: Vec<serde_json::Value> = [Backend::PythonHooks, Backend::Syscall]
        .iter()
        .map(|b| serde_json::json!({"name": b.name(), "implemented": b.implemented(), "capabilities": b.capabilities()}))
        .collect();
    serde_json::Value::Array(all).to_string()
}

// ------------------------------------------------------------------ lockstep (Level 2 browser, round 4)
use detpy_core::lockstep::{self as ls, Action as LsAction, Scheduler};

/// The lockstep scheduler (see `detpy_core::lockstep`). Times are virtual nanoseconds (f64: exact below 2^53).
#[napi]
pub struct Lockstep {
    inner: Mutex<Scheduler>,
}

#[napi(object)]
pub struct LockstepAction {
    /// `release`, `advance` or `idle`.
    pub kind: String,
    pub id: Option<f64>,
    pub idx: Option<u32>,
    pub n: Option<u32>,
    pub latency_ns: Option<f64>,
    pub fault: Option<String>,
    pub decision: Option<f64>,
    pub to_ns: Option<f64>,
    pub budget_ns: Option<f64>,
}

#[napi]
impl Lockstep {
    #[napi(constructor)]
    pub fn new(seed: BigInt, seeded: bool, start_ns: f64, quantum_ns: f64, base_latency_ns: f64) -> Result<Self> {
        Ok(Lockstep {
            inner: Mutex::new(Scheduler::new(to_u64(&seed)?, seeded, start_ns as u64, quantum_ns as u64, base_latency_ns as u64)),
        })
    }

    /// Seed space: latency choices (ns), fault list (`reset-request,reset-response,partial:MS,close-after`), the
    /// message kinds faults apply to, the fault probability (per mille), and whether the order is perturbed.
    #[napi]
    pub fn set_space(&self, latencies_ns: Vec<f64>, faults: String, fault_kinds: Vec<String>, fault_per_mille: u32, reorder: bool) {
        let mut s = lock(&self.inner);
        s.space = ls::SeedSpace {
            latencies_ns: latencies_ns.into_iter().map(|x| x as u64).collect(),
            faults: ls::parse_faults(&faults),
            fault_kinds,
            fault_per_mille,
            reorder,
        };
    }

    /// Focus of the seed: test id substring, decision window (0 = open) and message key substrings.
    #[napi]
    pub fn set_focus(&self, test: String, from: f64, to: f64, keys: Vec<String>) {
        lock(&self.inner).focus = ls::Focus { test, from: from as u64, to: to as u64, keys };
    }

    #[napi]
    pub fn now(&self) -> f64 {
        lock(&self.inner).now() as f64
    }

    #[napi]
    pub fn advance_to(&self, t_ns: f64) {
        lock(&self.inner).advance_to(t_ns as u64)
    }

    #[napi]
    pub fn set_deadline(&self, participant: String, due_ns: Option<f64>) {
        lock(&self.inner).set_deadline(&participant, due_ns.map(|d| d as u64))
    }

    #[napi]
    pub fn set_waiting(&self, participant: String, waiting: bool) {
        lock(&self.inner).set_waiting(&participant, waiting)
    }

    #[napi]
    pub fn remove_participant(&self, participant: String) {
        lock(&self.inner).remove_participant(&participant)
    }

    #[napi]
    pub fn enqueue(&self, id: f64, key: String, test: String, conn: Option<f64>, owner: String, kind: String) {
        lock(&self.inner).enqueue(id as u64, &key, &test, conn.map(|c| c as u64), &owner, &kind)
    }

    #[napi]
    pub fn cancel(&self, id: f64) -> bool {
        lock(&self.inner).cancel(id as u64)
    }

    #[napi]
    pub fn pending(&self) -> u32 {
        lock(&self.inner).pending_len() as u32
    }

    #[napi]
    pub fn next_deadline(&self) -> Option<f64> {
        lock(&self.inner).next_deadline().map(|d| d as f64)
    }

    /// Next action; call only when every participant is quiet.
    #[napi]
    pub fn next(&self) -> LockstepAction {
        let none = LockstepAction {
            kind: String::new(),
            id: None,
            idx: None,
            n: None,
            latency_ns: None,
            fault: None,
            decision: None,
            to_ns: None,
            budget_ns: None,
        };
        match lock(&self.inner).next() {
            LsAction::Release { id, idx, n, latency_ns, fault, decision } => LockstepAction {
                kind: "release".into(),
                id: Some(id as f64),
                idx: Some(idx),
                n: Some(n),
                latency_ns: Some(latency_ns as f64),
                fault: Some(fault.name()),
                decision: Some(decision as f64),
                ..none
            },
            LsAction::Advance { to_ns, budget_ns } => {
                LockstepAction { kind: "advance".into(), to_ns: Some(to_ns as f64), budget_ns: Some(budget_ns as f64), ..none }
            }
            LsAction::Idle => LockstepAction { kind: "idle".into(), ..none },
        }
    }

    /// Decisions taken so far (tab-separated: test, decision, idx/n, latency ns, fault, key).
    #[napi]
    pub fn log(&self) -> Vec<String> {
        lock(&self.inner).log.clone()
    }
}
