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

mod proofcache;
mod sysmon;

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    // A panic while holding the lock must not make every later call fail.
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Per-test fingerprinting recorder that streams a trace file.
#[pyclass(module = "detpy._core")]
struct Recorder {
    inner: Mutex<CoreRecorder>,
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
        lock(&self.inner).clear_test(nodeid)
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
}

fn trace_err(e: trace::TraceError) -> PyErr {
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
    m.add_function(wrap_pyfunction!(derive_seed, m)?)?;
    m.add_function(wrap_pyfunction!(shuffle_order, m)?)?;
    m.add_function(wrap_pyfunction!(order_digest, m)?)?;
    m.add_function(wrap_pyfunction!(digest, m)?)?;
    m.add_function(wrap_pyfunction!(backends, m)?)?;
    m.add_class::<sysmon::LineRecorder>()?;
    m.add_function(wrap_pyfunction!(sysmon::set_audit_hook, m)?)?;
    m.add_class::<proofcache::ProofCache>()?;
    m.add_function(wrap_pyfunction!(proofcache::file_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::listing_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::env_value_digest, m)?)?;
    m.add_function(wrap_pyfunction!(proofcache::env_all_digest, m)?)?;
    Ok(())
}
