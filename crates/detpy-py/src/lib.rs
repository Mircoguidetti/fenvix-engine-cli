//! Python bindings for detpy-core (module `detpy._core`).

use detpy_core::backend::Backend;
use detpy_core::cassette::{Cassette as CoreCassette, Direction};
use detpy_core::event::{Event, Source};
use detpy_core::fingerprint::digest_bytes;
use detpy_core::recorder::{Recorder as CoreRecorder, RecorderConfig};
use detpy_core::trace::Header;
use detpy_core::{backend::EventSink, order, trace, verify as v};
use pyo3::exceptions::{PyKeyError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};

mod capture;
mod follow;
mod level0;
mod precompile;
mod proofcache;
mod session;
mod sysmon;

// Level 0 seeds and filesystem order
mod fsorder;
mod seeds;
mod standin;

// rust-hotpaths-2: repro / reexec decisions
mod reexec;
mod repro;
// Level 0 clock, round 2: sleep, wall-derived functions, datetime, wait timeouts
mod clock;
// Level 0 closed network
mod network;
// rust-hotpaths-2: the capture's sqlite trace and rare-event helpers
mod sockcap;
mod sqlcap;
// rust-hotpaths-2: runtime identity of the cache with proof
mod identity;
// parallel-proof round 3: SQLite's clock and randomness under Level 0
mod sqlvirt;
// parallel --det: fixed plan and trace merge
mod parallel;

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    // A panic while holding the lock must not make every later call fail.
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Per-test fingerprinting recorder that streams a trace file.
#[pyclass(module = "detpy._core", frozen)]
pub(crate) struct Recorder {
    inner: Mutex<CoreRecorder>,
}

impl Recorder {
    /// Record one event for the current test (the Rust event path of `level0`).
    pub(crate) fn push(&self, event: Event) {
        lock(&self.inner).record(event);
    }
}

#[pymethods]
impl Recorder {
    #[new]
    #[pyo3(signature = (max_events = 10_000, checkpoint_every = 256))]
    fn new(max_events: usize, checkpoint_every: u64) -> Self {
        Recorder { inner: Mutex::new(CoreRecorder::new(RecorderConfig { max_events, checkpoint_every })) }
    }

    /// Start streaming the trace to `path`. `meta_json` is free-form JSON.
    fn open(&self, path: PathBuf, meta_json: &str, order: Vec<String>) -> PyResult<()> {
        let meta: serde_json::Value =
            serde_json::from_str(meta_json).map_err(|e| PyValueError::new_err(format!("bad meta json: {e}")))?;
        lock(&self.inner).open(&path, &Header::new(meta, order))?;
        Ok(())
    }

    fn begin_test(&self, nodeid: &str, index: u64) -> PyResult<()> {
        lock(&self.inner).begin_test(nodeid, index)?;
        Ok(())
    }

    /// Hot path: record one event for the current test (ignored outside tests).
    #[pyo3(signature = (source, op, site, value, thread = 0))]
    fn record(&self, source: &str, op: &str, site: &str, value: &str, thread: u32) {
        lock(&self.inner).record(Event {
            thread,
            source: Source::parse(source),
            op: op.to_owned(),
            site: site.to_owned(),
            value: value.to_owned(),
        });
    }

    /// Finish the current test; returns its fingerprint (None if no test was open).
    fn end_test(&self, outcome: &str) -> PyResult<Option<String>> {
        Ok(lock(&self.inner).end_test(outcome)?.map(|r| r.fingerprint))
    }

    /// What the run read after the header, outside any test (JSON object): written in the footer.
    fn set_late(&self, late: &str) -> PyResult<()> {
        let v: serde_json::Value = serde_json::from_str(late).map_err(|e| PyValueError::new_err(e.to_string()))?;
        lock(&self.inner).set_late(v);
        Ok(())
    }

    /// Close the trace; returns the digest of the executed order.
    fn close(&self) -> PyResult<Option<String>> {
        Ok(lock(&self.inner).close()?.map(|f| f.order_digest))
    }

    #[getter]
    fn in_test(&self) -> bool {
        lock(&self.inner).in_test()
    }

    #[getter]
    fn current_events(&self) -> u64 {
        lock(&self.inner).current_events()
    }

    #[getter]
    fn dropped(&self) -> u64 {
        lock(&self.inner).dropped
    }

    /// `[(nodeid, outcome, fingerprint, n_events), ...]` for finished tests.
    fn finished(&self) -> Vec<(String, String, String, u64)> {
        lock(&self.inner)
            .finished()
            .iter()
            .map(|f| (f.nodeid.clone(), f.outcome.clone(), f.fingerprint.clone(), f.n_events))
            .collect()
    }
}

/// Network cassette (record/replay of outbound connections).
#[pyclass(module = "detpy._core")]
struct Cassette {
    inner: Mutex<CoreCassette>,
}

fn parse_dir(dir: &str) -> PyResult<Direction> {
    Direction::parse(dir).ok_or_else(|| PyValueError::new_err(format!("direction must be send/recv, got {dir:?}")))
}

#[pymethods]
impl Cassette {
    #[new]
    fn new() -> Self {
        Cassette { inner: Mutex::new(CoreCassette::default()) }
    }

    #[staticmethod]
    fn load(path: PathBuf) -> PyResult<Self> {
        Ok(Cassette { inner: Mutex::new(CoreCassette::load(&path)?) })
    }

    fn save(&self, path: PathBuf) -> PyResult<()> {
        lock(&self.inner).save(&path)?;
        Ok(())
    }

    fn tests(&self) -> Vec<String> {
        lock(&self.inner).tests.keys().cloned().collect()
    }

    fn clear_test(&self, nodeid: &str) {
        let mut c = lock(&self.inner);
        c.clear_test(nodeid);
        c.recorded.remove(nodeid);
    }

    fn open_connection(&self, nodeid: &str, host: &str, port: u16) -> usize {
        lock(&self.inner).open(nodeid, host, port)
    }

    fn append(&self, nodeid: &str, idx: usize, dir: &str, data: &[u8]) -> PyResult<()> {
        let dir = parse_dir(dir)?;
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.append(dir, data);
        Ok(())
    }

    fn set_tls(&self, nodeid: &str, idx: usize) -> PyResult<()> {
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.tls = true;
        Ok(())
    }

    /// Index of the `nth` connection of `nodeid` to `host:port`, if recorded.
    fn find(&self, nodeid: &str, host: &str, port: u16, nth: usize) -> Option<usize> {
        lock(&self.inner).find(nodeid, host, port, nth).map(|(i, _)| i)
    }

    /// `nodeid` goes on with connection `idx` of `from` (kept alive across tests): the index of its continuation.
    fn continue_in(&self, from: &str, idx: usize, nodeid: &str) -> PyResult<usize> {
        lock(&self.inner).continue_in(from, idx, nodeid).ok_or_else(|| PyKeyError::new_err(format!("{from}#{idx}")))
    }

    /// Forget what was recorded on a connection so far (the TLS handshake's ciphertext, once the TLS object above
    /// it is known to record the plaintext).
    fn clear_segments(&self, nodeid: &str, idx: usize) -> PyResult<()> {
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.segments.clear();
        Ok(())
    }

    /// The server closed this connection (a read returned end of file): its replay ends with end of file.
    fn set_closed(&self, nodeid: &str, idx: usize) -> PyResult<()> {
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.kept_open = false;
        Ok(())
    }

    /// Whether the replay keeps this connection open after its last segment (a later test went on using it, or
    /// the server had not closed it).
    fn keeps_open(&self, nodeid: &str, idx: usize) -> PyResult<bool> {
        let c = lock(&self.inner);
        let conn = c.connection(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        Ok(conn.keep())
    }

    /// `(host, port, tls, n_segments)` of a recorded connection.
    fn info(&self, nodeid: &str, idx: usize) -> PyResult<(String, u16, bool, usize)> {
        let c = lock(&self.inner);
        let conn = c.connection(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        Ok((conn.host.clone(), conn.port, conn.tls, conn.segments.len()))
    }

    fn segments<'py>(&self, py: Python<'py>, nodeid: &str, idx: usize) -> PyResult<Vec<(String, Bound<'py, PyBytes>)>> {
        let c = lock(&self.inner);
        let conn = c.connection(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        Ok(conn.segments.iter().map(|s| (s.dir.as_str().to_string(), PyBytes::new(py, &s.data))).collect())
    }

    fn merge(&self, other: &Cassette) {
        let o = lock(&other.inner).clone();
        lock(&self.inner).merge(o);
    }

    /// A UDP exchange of `nodeid` with `host:port` (audit G-1518); returns its index.
    fn open_udp(&self, nodeid: &str, host: &str, port: u16) -> usize {
        lock(&self.inner).open_udp(nodeid, host, port)
    }

    /// TLS details of a recorded connection (JSON text), set at record time.
    fn set_tls_info(&self, nodeid: &str, idx: usize, info: &str) -> PyResult<()> {
        let v: serde_json::Value = serde_json::from_str(info).map_err(|e| PyValueError::new_err(e.to_string()))?;
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.tls_info = Some(v);
        Ok(())
    }

    fn tls_info(&self, nodeid: &str, idx: usize) -> Option<String> {
        let c = lock(&self.inner);
        c.connection(nodeid, idx).and_then(|k| k.tls_info.as_ref()).map(|v| v.to_string())
    }

    /// Whether any test has a UDP exchange recorded.
    fn has_udp(&self) -> bool {
        lock(&self.inner).tests.values().any(|cs| cs.iter().any(|c| c.udp))
    }

    fn find_udp(&self, nodeid: &str, host: &str, port: u16) -> Option<usize> {
        lock(&self.inner).find_udp(nodeid, host, port)
    }

    /// One datagram of a UDP exchange (never merged with the previous one).
    fn append_datagram(&self, nodeid: &str, idx: usize, dir: &str, data: &[u8]) -> PyResult<()> {
        let dir = parse_dir(dir)?;
        let mut c = lock(&self.inner);
        let conn = c.connection_mut(nodeid, idx).ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.append_datagram(dir, data);
        Ok(())
    }

    /// Note when `nodeid`'s connections were recorded (UTC, RFC 3339).
    fn set_recorded(&self, nodeid: &str, when: &str) {
        lock(&self.inner).recorded.insert(nodeid.to_string(), when.to_string());
    }

    /// When `nodeid`'s connections were recorded, if the cassette says.
    fn recorded(&self, nodeid: &str) -> Option<String> {
        lock(&self.inner).recorded.get(nodeid).cloned()
    }

    /// Rename a test's recordings (`fenvix cassette rename`); False when the old one has none.
    fn rename_test(&self, old: &str, new: &str) -> bool {
        let mut c = lock(&self.inner);
        match c.tests.remove(old) {
            Some(conns) => {
                c.tests.insert(new.to_string(), conns);
                if let Some(w) = c.recorded.remove(old) {
                    c.recorded.insert(new.to_string(), w);
                }
                true
            }
            None => false,
        }
    }
}

/// The bytes with the values of secret HTTP headers masked (same length): what a cassette stores and what replay
/// compares (detpy_core::cassette::redact).
#[pyfunction]
fn net_redact<'py>(py: Python<'py>, data: &[u8]) -> Bound<'py, PyBytes> {
    PyBytes::new(py, &detpy_core::cassette::redact(data))
}

pub(crate) fn trace_err(e: trace::TraceError) -> PyErr {
    match e {
        trace::TraceError::Io(e) => e.into(),
        other => PyValueError::new_err(other.to_string()),
    }
}

/// Verify traces of the same suite; returns the report as JSON.
#[pyfunction]
fn verify(paths: Vec<PathBuf>) -> PyResult<String> {
    let report = v::verify_paths(&paths).map_err(trace_err)?;
    serde_json::to_string(&report).map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

/// `fenvix verify`: (report JSON, text) with `--ignore-env` names left out of the run inputs.
#[pyfunction]
#[pyo3(signature = (paths, ignore_env = Vec::new(), show_stable = false))]
fn verify_with(paths: Vec<PathBuf>, ignore_env: Vec<String>, show_stable: bool) -> PyResult<(String, String)> {
    let report = v::verify_paths_ignoring(&paths, &ignore_env).map_err(trace_err)?;
    let json = serde_json::to_string(&report).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    Ok((json, v::render_text(&report, show_stable)))
}

/// A `std::io::Write` that hands what it is given to a Python file object (`sys.stdout`) in chunks of about 1 MiB,
/// cut at UTF-8 character boundaries, so a large report is never held whole as a string on either side.
struct PyChunkWriter<'py> {
    out: Bound<'py, PyAny>,
    buf: Vec<u8>,
}

impl PyChunkWriter<'_> {
    fn send(&mut self, all: bool) -> std::io::Result<()> {
        let valid = match std::str::from_utf8(&self.buf) {
            Ok(_) => self.buf.len(),
            Err(e) => e.valid_up_to(),
        };
        let n = if all { self.buf.len() } else { valid };
        if n == 0 {
            return Ok(());
        }
        let text = String::from_utf8_lossy(&self.buf[..n]).into_owned();
        self.out.call_method1("write", (text,)).map_err(std::io::Error::other)?;
        self.buf.drain(..n);
        Ok(())
    }
}

impl std::io::Write for PyChunkWriter<'_> {
    fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
        self.buf.extend_from_slice(data);
        if self.buf.len() >= 1 << 20 {
            self.send(false)?;
        }
        Ok(data.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.send(true)
    }
}

/// `fenvix verify` / `detpy verify` in bounded memory (P0 big trace): the report is written to `out` (a Python file
/// object) as it is serialized -- the JSON report plus a newline with `as_json`, else the text rendering with its
/// first `detpy verify` replaced by `prog` -- and only the report's `summary` is returned (JSON), for the exit code.
/// The bytes written are those `verify_with` returned; a report of 1.2 GB (agentic-qe: 30765 tests, each naming 537
/// differing inputs) is no longer held as one Rust string, one Python string and one parsed Python object at once.
#[pyfunction]
#[pyo3(signature = (paths, ignore_env, show_stable, as_json, out, prog))]
fn verify_write(
    paths: Vec<PathBuf>,
    ignore_env: Vec<String>,
    show_stable: bool,
    as_json: bool,
    out: Bound<'_, PyAny>,
    prog: String,
) -> PyResult<String> {
    use std::io::Write;
    let report = v::verify_paths_ignoring(&paths, &ignore_env).map_err(trace_err)?;
    let summary = serde_json::to_string(&report.summary).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
    let io = |e: std::io::Error| PyRuntimeError::new_err(e.to_string());
    let mut w = PyChunkWriter { out, buf: Vec::with_capacity(1 << 20) };
    if as_json {
        serde_json::to_writer(&mut w, &report).map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        w.write_all(b"\n").map_err(io)?;
    } else {
        let text = v::render_text(&report, show_stable);
        drop(report);
        w.write_all(text.replacen("detpy verify", &prog, 1).as_bytes()).map_err(io)?;
    }
    w.flush().map_err(io)?;
    Ok(summary)
}

/// Verify traces and render a human-readable report.
#[pyfunction]
#[pyo3(signature = (paths, show_stable = false))]
fn verify_text(paths: Vec<PathBuf>, show_stable: bool) -> PyResult<String> {
    let report = v::verify_paths(&paths).map_err(trace_err)?;
    Ok(v::render_text(&report, show_stable))
}

#[pyfunction]
fn derive_seed(base: u64, key: &str) -> u64 {
    order::derive_seed(base, key)
}

#[pyfunction]
fn shuffle_order(ids: Vec<String>, seed: u64) -> Vec<usize> {
    order::shuffle_order(&ids, seed)
}

#[pyfunction]
fn order_digest(ids: Vec<String>) -> String {
    trace::order_digest(&ids)
}

/// Short (128-bit) BLAKE3 hex digest of `data`.
#[pyfunction]
fn digest(data: &[u8]) -> String {
    digest_bytes(data).short()
}

// ---------------------------------------------------------------------------
// The general rule (detpy_core::provable). The table and the predicate live in the core; the Python sensor asks
// it to classify a callable and reports what it could not place. One implementation, used by the shell here, by
// the verifier and by the cache.

/// Classify one callable by its defining module and qualified name: `pure`, `controlled`, `recorded`, `input` or
/// `unaccounted`. Anything the core's table does not list answers `unaccounted`, which is what makes the sensor
/// default-deny.
#[pyfunction]
fn provable_account(module: &str, qualname: &str) -> &'static str {
    detpy_core::provable::account(module, qualname).as_str()
}

/// What the shell must write into the trace header as `meta.provable`, with the runtime key it is running on,
/// as a JSON object. The verifier refuses a trace whose values are not these.
#[pyfunction]
fn provable_header(sensor: &str, runtime: &str) -> String {
    serde_json::json!({
        "sensor": sensor,
        "contract": detpy_core::provable::SENSOR_CONTRACT,
        "surface": detpy_core::provable::surface_digest(),
        "runtime": runtime,
    })
    .to_string()
}

/// The runtime keys the accounting table was audited against. A run on anything else is NOT PROVEN, so the shell
/// checks this before claiming a sensor.
#[pyfunction]
fn provable_runtimes() -> Vec<&'static str> {
    detpy_core::provable::AUDITED_RUNTIMES.to_vec()
}

/// The native extension modules whose own C code the engine has reasoned about. A test that loads any other one
/// is NOT PROVEN (the declared residual: C code emits no Python-level call).
#[pyfunction]
fn provable_native() -> Vec<&'static str> {
    detpy_core::provable::CONTROLLED_NATIVE.to_vec()
}

/// Paths of the shared objects mapped into this process (`/proc/self/maps` on Linux, dyld on macOS); None
/// where the OS gives no list (detpy_core::host).
#[pyfunction]
fn loaded_images() -> Option<Vec<String>> {
    detpy_core::host::loaded_images()
}

/// The CPU's feature description where /proc/cpuinfo does not exist (macOS); None elsewhere.
#[pyfunction]
fn cpu_features() -> Option<String> {
    detpy_core::host::cpu_features()
}

/// JSON description of the interception backends and their capabilities.
#[pyfunction]
fn backends() -> String {
    let all: Vec<serde_json::Value> = [Backend::PythonHooks, Backend::Syscall]
        .iter()
        .map(|b| {
            serde_json::json!({
                "name": b.name(),
                "implemented": b.implemented(),
                "capabilities": b.capabilities(),
            })
        })
        .collect();
    serde_json::Value::Array(all).to_string()
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("ENCODING_VERSION", detpy_core::event::ENCODING_VERSION)?;
    m.add("TRACE_VERSION", trace::TRACE_VERSION)?;
    m.add_class::<Recorder>()?;
    m.add_class::<Cassette>()?;
    m.add_function(wrap_pyfunction!(verify, m)?)?;
    m.add_function(wrap_pyfunction!(verify_text, m)?)?;
    m.add_function(wrap_pyfunction!(verify_with, m)?)?;
    m.add_function(wrap_pyfunction!(verify_write, m)?)?;
    m.add_function(wrap_pyfunction!(net_redact, m)?)?;
    m.add_function(wrap_pyfunction!(derive_seed, m)?)?;
    m.add_function(wrap_pyfunction!(shuffle_order, m)?)?;
    m.add_function(wrap_pyfunction!(order_digest, m)?)?;
    m.add_function(wrap_pyfunction!(digest, m)?)?;
    m.add_function(wrap_pyfunction!(backends, m)?)?;
    m.add_function(wrap_pyfunction!(loaded_images, m)?)?;
    m.add_function(wrap_pyfunction!(provable_account, m)?)?;
    m.add_function(wrap_pyfunction!(provable_header, m)?)?;
    m.add_function(wrap_pyfunction!(provable_runtimes, m)?)?;
    m.add_function(wrap_pyfunction!(provable_native, m)?)?;
    m.add_function(wrap_pyfunction!(cpu_features, m)?)?;
    m.add_class::<sysmon::LineRecorder>()?;
    m.add_function(wrap_pyfunction!(sysmon::set_audit_hook, m)?)?;
    m.add_function(wrap_pyfunction!(sysmon::audit_hooks_off, m)?)?;
    m.add_class::<sysmon::SocketScan>()?;
    m.add_function(wrap_pyfunction!(sysmon::tracer_prefixes, m)?)?;
    m.add_class::<proofcache::ProofCache>()?;
    m.add_class::<proofcache::DistFiles>()?;
    m.add_function(wrap_pyfunction!(proofcache::dist_top_of, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::stat_dep, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::compact_stats, m)?)?;
    m.add_class::<session::CacheSession>()?;
    m.add_function(wrap_pyfunction!(session::det_outcome, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::file_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::py_repr_float, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::json_dumps_str, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::listing_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::stat_kind, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::size_kind, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::time_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::fields_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::lstat_kind, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::importable_dep, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::importable_name_dep, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::probe_dep, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::probe_key, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::import_probe, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::import_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::collection_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::dist_identity, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::env_value_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::env_all_digest, m)?)?;
    level0::register(m)?;
    capture::register(m)?;
    precompile::register(m)?;
    follow::register(m)?;
    // Level 0 seeds and filesystem order
    standin::register(m)?;
    seeds::register(m)?;
    fsorder::register(m)?;
    // rust-hotpaths-2: repro / reexec decisions
    reexec::register(m)?;
    repro::register(m)?;
    // Level 0 clock, round 2
    clock::register(m)?;
    // Level 0 closed network
    network::register(m)?;
    // rust-hotpaths-2: the capture's sqlite trace and rare-event helpers
    sqlcap::register(m)?;
    sockcap::register(m)?;
    // rust-hotpaths-2: runtime identity of the cache with proof
    identity::register(m)?;
    sqlvirt::register(m)?;
    // parallel --det: fixed plan and trace merge
    parallel::register(m)?;
    Ok(())
}
