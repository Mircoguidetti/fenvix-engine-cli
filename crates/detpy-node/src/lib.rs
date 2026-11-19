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
        let meta: serde_json::Value =
            serde_json::from_str(&meta_json).map_err(|e| bad(format!("bad meta json: {e}")))?;
        lock(&self.inner).open(&PathBuf::from(path), &Header::new(meta, order)).map_err(io_err)
    }

    #[napi]
    pub fn begin_test(&self, nodeid: String, index: u32) -> Result<()> {
        lock(&self.inner).begin_test(&nodeid, index as u64).map_err(io_err)
    }

    /// Record one event for the current test (ignored outside tests).
    #[napi]
    pub fn record(&self, source: String, op: String, site: String, value: String, thread: Option<u32>) {
        lock(&self.inner).record(Event {
            thread: thread.unwrap_or(0),
            source: Source::parse(&source),
            op,
            site,
            value,
        });
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
            r.record(Event {
                thread: 0,
                source: Source::parse(s),
                op: o.to_owned(),
                site: at.to_owned(),
                value: val.to_owned(),
            });
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
        .map(
            |b| serde_json::json!({"name": b.name(), "implemented": b.implemented(), "capabilities": b.capabilities()}),
        )
        .collect();
    serde_json::Value::Array(all).to_string()
}

// ---------------------------------------------------------------------------------------------------------------------
// Cache with proof (the same store, keys, receipts and reuse check as the Python shell: detpy_core::proof).

use detpy_core::proof::{self as pf, Checker, CodeFile, Current, Observed, Store};
use std::collections::{BTreeMap, BTreeSet, HashMap};

struct ProofInner {
    store: Store,
    checker: Checker,
    touched: BTreeSet<String>,
}

/// The on-disk store of one cache directory plus the reuse checker of the current session.
#[napi]
pub struct ProofCache {
    dir: PathBuf,
    inner: Mutex<ProofInner>,
}

#[derive(serde::Deserialize)]
struct ObservedJs {
    outcome: String,
    #[serde(default)]
    report: serde_json::Value,
    #[serde(default)]
    fingerprint: String,
    #[serde(default)]
    duration: f64,
    #[serde(default)]
    run: String,
    config: String,
    runtime: String,
    #[serde(default)]
    epoch: Option<i64>,
    #[serde(default)]
    env: Vec<(String, String)>,
    #[serde(default)]
    data: Vec<(String, String)>,
    #[serde(default)]
    content: Vec<u32>,
    #[serde(default)]
    startup: String,
}

#[napi(object)]
pub struct CheckResult {
    pub ok: bool,
    /// Receipt JSON when `ok`, else "kind: detail".
    pub text: String,
}

#[napi]
impl ProofCache {
    #[napi(constructor)]
    pub fn new(dir: String, root: String) -> Self {
        let dir = PathBuf::from(dir);
        let store = Store::load(&dir);
        let checker = Checker::new(Current { root: PathBuf::from(root), ..Default::default() });
        ProofCache { dir, inner: Mutex::new(ProofInner { store, checker, touched: BTreeSet::new() }) }
    }

    /// Current session state: configuration and runtime digests, clock epoch, environment at session start.
    #[napi]
    pub fn begin(&self, config: String, runtime: String, epoch: i64, env: HashMap<String, String>) {
        let mut g = lock(&self.inner);
        let root = g.checker.cur.root.clone();
        let startup = g.checker.cur.startup.clone();
        let env: BTreeMap<String, String> = env.into_iter().collect();
        g.checker = Checker::new(Current { root, config, runtime, epoch, env, startup });
    }

    /// Configuration digest the next checks compare with (per project), keeping what the checker has hashed.
    #[napi]
    pub fn set_config(&self, config: String) {
        lock(&self.inner).checker.cur.config = config;
    }

    #[napi]
    pub fn set_startup(&self, startup: String) {
        lock(&self.inner).checker.cur.startup = startup;
    }

    #[napi]
    pub fn check(&self, nodeid: String) -> Result<CheckResult> {
        let mut g = lock(&self.inner);
        let ProofInner { store, checker, .. } = &mut *g;
        Ok(match checker.check(store, &nodeid) {
            Ok(r) => CheckResult { ok: true, text: serde_json::to_string(&r).map_err(|e| bad(e.to_string()))? },
            Err(m) => CheckResult { ok: false, text: format!("{}: {}", m.kind, m.detail) },
        })
    }

    /// Recorded entry of `nodeid` as JSON, or null.
    #[napi]
    pub fn entry(&self, nodeid: String) -> Result<Option<String>> {
        let g = lock(&self.inner);
        match g.store.tests.get(&nodeid) {
            None => Ok(None),
            Some(e) => Ok(Some(serde_json::to_string(e).map_err(|e| bad(e.to_string()))?)),
        }
    }

    #[napi]
    pub fn ids(&self) -> Vec<String> {
        lock(&self.inner).store.tests.keys().cloned().collect()
    }

    /// Add (or find) a code file version keyed by its whole content; returns its index.
    #[napi]
    pub fn add_file(&self, path: String, content: String) -> u32 {
        let f = CodeFile {
            path,
            skeleton: content.clone(),
            hooks: content.clone(),
            content,
            units: vec![],
            imports: vec![],
        };
        lock(&self.inner).store.add_file(f)
    }

    /// Add facts as the Python shell stores them (shared-cache documents); returns the index.
    #[napi]
    pub fn add_file_facts(&self, json: String) -> Result<u32> {
        let f: CodeFile = serde_json::from_str(&json).map_err(|e| bad(format!("file facts: {e}")))?;
        Ok(lock(&self.inner).store.add_file(f))
    }

    /// Record the inputs and result of a test that ran (`observed` as JSON); returns its key.
    #[napi]
    pub fn record(&self, nodeid: String, observed: String) -> Result<String> {
        let o: ObservedJs = serde_json::from_str(&observed).map_err(|e| bad(format!("observed: {e}")))?;
        let mut g = lock(&self.inner);
        g.touched.insert(nodeid.clone());
        Ok(g.store.record(
            &nodeid,
            Observed {
                outcome: o.outcome,
                report: o.report,
                fingerprint: o.fingerprint,
                duration: o.duration,
                run: o.run,
                config: o.config,
                runtime: o.runtime,
                epoch: o.epoch,
                env: o.env,
                data: o.data,
                content: o.content,
                skeleton: vec![],
                hooks: vec![],
                units: vec![],
                startup: o.startup,
            },
        ))
    }

    #[napi]
    pub fn remove(&self, nodeid: String) -> bool {
        let mut g = lock(&self.inner);
        g.touched.insert(nodeid.clone());
        g.store.remove(&nodeid)
    }

    /// Paths written by earlier sessions: JSON `{path: [writer contexts]}`.
    #[napi]
    pub fn written(&self) -> String {
        serde_json::to_string(&lock(&self.inner).store.written).unwrap_or_else(|_| "{}".into())
    }

    #[napi]
    pub fn add_written(&self, json: String) -> Result<()> {
        let w: BTreeMap<String, Vec<String>> = serde_json::from_str(&json).map_err(|e| bad(format!("written: {e}")))?;
        let mut g = lock(&self.inner);
        for (p, ws) in w {
            g.store.written.entry(p).or_default().extend(ws);
        }
        Ok(())
    }

    #[napi(getter)]
    pub fn size(&self) -> u32 {
        lock(&self.inner).store.tests.len() as u32
    }

    #[napi(getter)]
    pub fn n_files(&self) -> u32 {
        lock(&self.inner).store.files.len() as u32
    }

    /// Merge this session's changes into the store on disk (under a lock) and write it atomically.
    #[napi]
    pub fn save(&self) -> Result<()> {
        let g = lock(&self.inner);
        g.store.save_merged(&self.dir, &g.touched).map_err(io_err)
    }
}

#[napi]
pub fn file_digest(path: String) -> Option<String> {
    pf::file_digest(std::path::Path::new(&path))
}

#[napi]
pub fn listing_digest(path: String) -> Option<String> {
    pf::listing_digest(std::path::Path::new(&path))
}

/// Dependency string of a recorded data dependency kind, now ("f:..", "missing", "d:..", "s:<kind>", "l:..").
#[napi]
pub fn data_now(path: String, recorded: String) -> String {
    pf::data_now(std::path::Path::new(&path), &recorded)
}

#[napi]
pub fn package_resolution_digest(path: String) -> Option<String> {
    pf::package_resolution_digest(std::path::Path::new(&path))
}

#[napi]
pub fn stem_listing_digest(path: String) -> Option<String> {
    pf::stem_listing_digest(std::path::Path::new(&path))
}

#[napi]
pub fn link_dep(path: String) -> String {
    pf::link_dep(std::path::Path::new(&path))
}

#[napi]
pub fn stat_kind(path: String) -> String {
    pf::stat_kind(std::path::Path::new(&path)).to_string()
}

#[napi]
pub fn env_value_digest(value: Option<String>) -> String {
    pf::env_value_digest(value.as_deref())
}

#[napi]
pub fn env_all_digest(env: HashMap<String, String>) -> String {
    pf::env_all_digest(&env.into_iter().collect())
}

/// Content digest of directory trees: `roots` = [[label, dir], ...]; returns the TreeDigest as JSON.
#[napi]
pub fn tree_digest(
    roots: Vec<Vec<String>>,
    inside: String,
    exclude: Vec<String>,
    memo: Option<String>,
    max_files: u32,
    threads: u32,
) -> Result<String> {
    let roots: Vec<(String, PathBuf)> =
        roots.into_iter().filter(|r| r.len() == 2).map(|r| (r[0].clone(), PathBuf::from(&r[1]))).collect();
    let memo = memo.map(PathBuf::from);
    let d = detpy_core::treehash::tree_digest(
        &roots,
        std::path::Path::new(&inside),
        &exclude,
        memo.as_deref(),
        max_files as usize,
        threads as usize,
    );
    serde_json::to_string(&d).map_err(|e| bad(e.to_string()))
}

/// The work of [`tree_digest`] on a thread of libuv's pool (the identity is computed while the runner starts).
pub struct TreeDigestTask {
    roots: Vec<(String, PathBuf)>,
    inside: String,
    exclude: Vec<String>,
    memo: Option<PathBuf>,
    max_files: usize,
    threads: usize,
}

impl Task for TreeDigestTask {
    type Output = String;
    type JsValue = String;

    fn compute(&mut self) -> Result<Self::Output> {
        let d = detpy_core::treehash::tree_digest(
            &self.roots,
            std::path::Path::new(&self.inside),
            &self.exclude,
            self.memo.as_deref(),
            self.max_files,
            self.threads,
        );
        serde_json::to_string(&d).map_err(|e| bad(e.to_string()))
    }

    fn resolve(&mut self, _env: Env, output: Self::Output) -> Result<Self::JsValue> {
        Ok(output)
    }
}

/// [`tree_digest`] without blocking the event loop: a Promise of the same JSON.
#[napi]
pub fn tree_digest_async(
    roots: Vec<Vec<String>>,
    inside: String,
    exclude: Vec<String>,
    memo: Option<String>,
    max_files: u32,
    threads: u32,
) -> AsyncTask<TreeDigestTask> {
    let roots = roots.into_iter().filter(|r| r.len() == 2).map(|r| (r[0].clone(), PathBuf::from(&r[1]))).collect();
    AsyncTask::new(TreeDigestTask {
        roots,
        inside,
        exclude,
        memo: memo.map(PathBuf::from),
        max_files: max_files as usize,
        threads: threads as usize,
    })
}

// Dependency kinds of review r021 (detpy_core::deps): stat metadata, realpath, typed / recursive listings, copies.

#[napi]
pub fn stat_meta_digest(path: String) -> Option<String> {
    detpy_core::deps::stat_meta_digest(std::path::Path::new(&path))
}

#[napi]
pub fn stat_field_digest(path: String, field: String, follow: bool) -> Option<String> {
    detpy_core::deps::stat_field_digest(std::path::Path::new(&path), &field, follow)
}

#[napi]
pub fn realpath_digest(path: String) -> Option<String> {
    detpy_core::deps::realpath_digest(std::path::Path::new(&path))
}

#[napi]
pub fn typed_listing_digest(path: String) -> Option<String> {
    detpy_core::deps::typed_listing_digest(std::path::Path::new(&path))
}

#[napi]
pub fn tree_listing_digest(path: String) -> Option<String> {
    detpy_core::deps::tree_listing_digest(std::path::Path::new(&path))
}

#[napi]
pub fn tree_listing_nofollow_digest(path: String) -> Option<String> {
    detpy_core::deps::tree_listing_nofollow_digest(std::path::Path::new(&path))
}

#[napi]
pub fn copy_tree_digest(path: String) -> Option<String> {
    detpy_core::deps::copy_tree_digest(std::path::Path::new(&path))
}

#[napi(object)]
pub struct GlobBaseJs {
    pub dir: String,
    pub recursive: bool,
}

/// Base directories of the `import.meta.glob` calls of a module source; null when one cannot be read soundly.
#[napi]
pub fn import_glob_bases(source: Buffer) -> Option<Vec<GlobBaseJs>> {
    detpy_core::deps::import_glob_bases(&source)
        .map(|v| v.into_iter().map(|g| GlobBaseJs { dir: g.dir, recursive: g.recursive }).collect())
}
