//! Python bindings for detpy-core (module `detpy._core`).

use detpy_core::backend::Backend;
use detpy_core::cassette::{Cassette as CoreCassette, Direction};
use detpy_core::event::{Event, Source};
use detpy_core::fingerprint::digest_bytes;
use detpy_core::recorder::{Recorder as CoreRecorder, RecorderConfig};
use detpy_core::trace::Header;
use detpy_core::{backend::EventSink, order, trace, verify as v};
use pyo3::exceptions::{PyKeyError, PyRecursionError, PyRuntimeError, PyValueError};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyString};
use std::path::PathBuf;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Mutex, MutexGuard};

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    // A panic while holding the lock must not make every later call fail.
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Trace function for line preemption (`detpy.threads`, exploration seeds), set
/// with `sys.settrace`. A C callable: calling it pushes no Python frame, so near the
/// recursion limit the test's own call raises its RecursionError, not the tracer
/// (a Python trace function moved it one frame up: structlog `test_recursive`).
/// It is also cheaper on every traced line.
///
/// * `call`: project code (per code object, `cache` filled by `classify`) gets
///   this object as its local trace function; other frames are not traced.
/// * `line`: one unit of the budget; at zero `on_budget()` returns the next budget
///   (and may hand the baton to another thread). A RecursionError raised inside the
///   callbacks is swallowed: the preemption is skipped, not the test's code.
#[pyclass(module = "detpy._core", frozen)]
struct LineTracer {
    cache: Py<PyDict>,
    classify: Py<PyAny>,
    on_budget: Py<PyAny>,
    budget: AtomicI64,
}

fn is_recursion_error(py: Python<'_>, e: &PyErr) -> bool {
    e.is_instance_of::<PyRecursionError>(py)
}

#[pymethods]
impl LineTracer {
    #[new]
    fn new(cache: Py<PyDict>, classify: Py<PyAny>, on_budget: Py<PyAny>, budget: i64) -> Self {
        LineTracer {
            cache,
            classify,
            on_budget,
            budget: AtomicI64::new(budget),
        }
    }

    #[getter]
    fn budget(&self) -> i64 {
        self.budget.load(Ordering::Relaxed)
    }

    fn __call__(
        slf: &Bound<'_, Self>,
        frame: &Bound<'_, PyAny>,
        event: &Bound<'_, PyString>,
        _arg: &Bound<'_, PyAny>,
    ) -> PyResult<Option<Py<PyAny>>> {
        let py = slf.py();
        let me = slf.get();
        let ev = event.to_cow()?;
        match ev.as_bytes().first() {
            Some(b'l') => {
                if me.budget.fetch_sub(1, Ordering::Relaxed) <= 1 {
                    match me.on_budget.bind(py).call0() {
                        Ok(nb) => me
                            .budget
                            .store(nb.extract::<i64>().unwrap_or(1).max(1), Ordering::Relaxed),
                        Err(e) if is_recursion_error(py, &e) => {
                            me.budget.store(1, Ordering::Relaxed)
                        }
                        Err(e) => {
                            me.budget.store(1, Ordering::Relaxed);
                            return Err(e);
                        }
                    }
                }
                Ok(Some(slf.clone().into_any().unbind()))
            }
            Some(b'c') if ev == "call" => {
                let code = frame.getattr(intern!(py, "f_code"))?;
                let hit = match me.cache.bind(py).get_item(&code)? {
                    Some(v) => v.is_truthy()?,
                    None => match me.classify.bind(py).call1((code,)) {
                        Ok(v) => v.is_truthy()?,
                        Err(e) if is_recursion_error(py, &e) => false,
                        Err(e) => return Err(e),
                    },
                };
                Ok(if hit {
                    Some(slf.clone().into_any().unbind())
                } else {
                    None
                })
            }
            _ => Ok(Some(slf.clone().into_any().unbind())),
        }
    }
}

thread_local! {
    /// Per-thread state of [`LineMonitor`]: the budget callback and the lines left.
    static MON_THREAD: std::cell::RefCell<Option<(Py<PyAny>, i64)>> = const { std::cell::RefCell::new(None) };
}

/// Line preemption through `sys.monitoring` (Python 3.12+), for exploration seeds.
/// Unlike `sys.settrace` it does not replace the project's own trace function
/// (coverage: arrow's `--cov-fail-under` failed under seeds, review R-007 FIX 3).
/// Its callbacks are C callables (no Python frame, as with [`LineTracer`]).
///
/// * `py_start(code, offset)`: project code (per code object, `cache` filled by
///   `classify`) gets LINE events through `set_local_events`; the PY_START event
///   is then disabled at that location.
/// * `line(code, line)`: in a thread that called `enter`, one unit of its budget;
///   at zero `on_budget()` returns the next one (and may switch threads). Other
///   threads are ignored. A RecursionError of the callback is swallowed.
#[pyclass(module = "detpy._core", frozen)]
struct LineMonitor {
    cache: Py<PyDict>,
    classify: Py<PyAny>,
    set_local_events: Py<PyAny>,
    tool: i64,
    line_event: i64,
    disable: Py<PyAny>,
}

#[pymethods]
impl LineMonitor {
    #[new]
    fn new(
        cache: Py<PyDict>,
        classify: Py<PyAny>,
        set_local_events: Py<PyAny>,
        tool: i64,
        line_event: i64,
        disable: Py<PyAny>,
    ) -> Self {
        LineMonitor {
            cache,
            classify,
            set_local_events,
            tool,
            line_event,
            disable,
        }
    }

    /// The calling thread starts counting lines.
    fn enter(&self, on_budget: Py<PyAny>, budget: i64) {
        MON_THREAD.with(|c| *c.borrow_mut() = Some((on_budget, budget.max(1))));
    }

    /// The calling thread stops counting lines.
    fn leave(&self) {
        let old = MON_THREAD.with(|c| c.borrow_mut().take());
        drop(old);
    }

    fn py_start(
        &self,
        py: Python<'_>,
        code: &Bound<'_, PyAny>,
        _offset: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let hit = match self.cache.bind(py).get_item(code)? {
            Some(v) => v.is_truthy()?,
            None => match self.classify.bind(py).call1((code,)) {
                Ok(v) => v.is_truthy()?,
                Err(e) if is_recursion_error(py, &e) => return Ok(py.None()),
                Err(e) => return Err(e),
            },
        };
        if hit {
            self.set_local_events
                .bind(py)
                .call1((self.tool, code, self.line_event))?;
        }
        Ok(self.disable.clone_ref(py))
    }

    fn line(
        &self,
        py: Python<'_>,
        _code: &Bound<'_, PyAny>,
        _line: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        // Count without holding the borrow across the Python call below.
        let due = MON_THREAD.with(|c| {
            let mut b = c.borrow_mut();
            match b.as_mut() {
                Some((cb, left)) => {
                    *left -= 1;
                    if *left <= 0 {
                        *left = 1;
                        Some(cb.clone_ref(py))
                    } else {
                        None
                    }
                }
                None => None,
            }
        });
        if let Some(cb) = due {
            let next = match cb.bind(py).call0() {
                Ok(nb) => nb.extract::<i64>().unwrap_or(1).max(1),
                Err(e) if is_recursion_error(py, &e) => 1,
                Err(e) => return Err(e),
            };
            MON_THREAD.with(|c| {
                if let Some((_, left)) = c.borrow_mut().as_mut() {
                    *left = next;
                }
            });
        }
        Ok(())
    }
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
        Recorder {
            inner: Mutex::new(CoreRecorder::new(RecorderConfig {
                max_events,
                checkpoint_every,
            })),
        }
    }

    /// Start streaming the trace to `path`. `meta_json` is free-form JSON.
    fn open(&self, path: PathBuf, meta_json: &str, order: Vec<String>) -> PyResult<()> {
        let meta: serde_json::Value = serde_json::from_str(meta_json)
            .map_err(|e| PyValueError::new_err(format!("bad meta json: {e}")))?;
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
            .map(|f| {
                (
                    f.nodeid.clone(),
                    f.outcome.clone(),
                    f.fingerprint.clone(),
                    f.n_events,
                )
            })
            .collect()
    }
}

/// Network cassette (record/replay of outbound connections).
#[pyclass(module = "detpy._core")]
struct Cassette {
    inner: Mutex<CoreCassette>,
}

fn parse_dir(dir: &str) -> PyResult<Direction> {
    Direction::parse(dir)
        .ok_or_else(|| PyValueError::new_err(format!("direction must be send/recv, got {dir:?}")))
}

#[pymethods]
impl Cassette {
    #[new]
    fn new() -> Self {
        Cassette {
            inner: Mutex::new(CoreCassette::default()),
        }
    }

    #[staticmethod]
    fn load(path: PathBuf) -> PyResult<Self> {
        Ok(Cassette {
            inner: Mutex::new(CoreCassette::load(&path)?),
        })
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
        let conn = c
            .connection_mut(nodeid, idx)
            .ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.append(dir, data);
        Ok(())
    }

    fn set_tls(&self, nodeid: &str, idx: usize) -> PyResult<()> {
        let mut c = lock(&self.inner);
        let conn = c
            .connection_mut(nodeid, idx)
            .ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        conn.tls = true;
        Ok(())
    }

    /// Index of the `nth` connection of `nodeid` to `host:port`, if recorded.
    fn find(&self, nodeid: &str, host: &str, port: u16, nth: usize) -> Option<usize> {
        lock(&self.inner)
            .find(nodeid, host, port, nth)
            .map(|(i, _)| i)
    }

    /// `(host, port, tls, n_segments)` of a recorded connection.
    fn info(&self, nodeid: &str, idx: usize) -> PyResult<(String, u16, bool, usize)> {
        let c = lock(&self.inner);
        let conn = c
            .connection(nodeid, idx)
            .ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        Ok((conn.host.clone(), conn.port, conn.tls, conn.segments.len()))
    }

    fn segments<'py>(
        &self,
        py: Python<'py>,
        nodeid: &str,
        idx: usize,
    ) -> PyResult<Vec<(String, Bound<'py, PyBytes>)>> {
        let c = lock(&self.inner);
        let conn = c
            .connection(nodeid, idx)
            .ok_or_else(|| PyKeyError::new_err(format!("{nodeid}#{idx}")))?;
        Ok(conn
            .segments
            .iter()
            .map(|s| (s.dir.as_str().to_string(), PyBytes::new(py, &s.data)))
            .collect())
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
    m.add_class::<LineTracer>()?;
    m.add_class::<LineMonitor>()?;
    m.add_function(wrap_pyfunction!(verify, m)?)?;
    m.add_function(wrap_pyfunction!(verify_text, m)?)?;
    m.add_function(wrap_pyfunction!(derive_seed, m)?)?;
    m.add_function(wrap_pyfunction!(shuffle_order, m)?)?;
    m.add_function(wrap_pyfunction!(order_digest, m)?)?;
    m.add_function(wrap_pyfunction!(digest, m)?)?;
    m.add_function(wrap_pyfunction!(backends, m)?)?;
    Ok(())
}
