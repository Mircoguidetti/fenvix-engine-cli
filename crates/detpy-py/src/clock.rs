//! The rest of the virtual clock in Rust: `time.sleep`, the wall-derived `time` functions, `clock_gettime(_ns)`,
//! `datetime.now` / `utcnow`, the timeout rules of the wait primitives, the "a process was started" flag and the
//! `time_machine` travel.
//!
//! Port of `detpy/clock.py` (`sleep`, `_other_threads_alive`, `_in_event_loop`, `_children_alive`, `_EXTERNAL`,
//! `_mark_external`, `_wall_secs`, `localtime`, `gmtime`, `ctime`, `asctime`, `strftime`, `clock_gettime`,
//! `clock_gettime_ns`, `_dt_now`, `_dt_utcnow`, `_condition_wait`, `_wrap_selector_select`, `_TimedLock.acquire`,
//! `_time_machine_ns`), round 2 of the rust-hotpaths session; the clock's state and the six `time.*` reads were
//! round 1 (`level0.rs`). The Python original is kept verbatim in `tests/rust_hotpaths_ref/_ref_l0_clock_r2.py`;
//! traces, stores, receipts and printed values are tested byte-identical against it (`tests/test_clock_rust.py`).
//!
//! What stays Python (`detpy/clock.py`): the patching itself, and the functions that must bind as methods and call
//! back into Python code (`Condition.wait`, `selectors.*.select`, `_TimedLock.acquire`): thin one-line shims over
//! the Rust functions here, so the frames under them (`threading.Condition.wait`, the real `select`) keep the same
//! detpy frame above them, which ends every call-site search (`_sites.resolve`) as before.
//!
//! Each stand-in reads the objects the Python function read as module globals of `detpy.clock` (`real_sleep`,
//! `real_localtime`, `_REALTIME`, `threading`, `sys`, ...) from that module's dict at call time, as Python did; the
//! clock itself is `level0`'s. Python semantics are kept by calling the same Python operations (`float(x)`,
//! `x != x`, `x < 0`, `int(x * NS)`, `in`, truthiness) on the same objects, in the same order. The call sites of the
//! recorded events are the stand-ins' callers: a Rust stand-in has no frame, so where the Python one passed `depth`
//! (1 for `sleep`, 2 through `_wall_secs`) this passes `skip = 0`.
//!
//! `_children_alive` lists `/proc/self/task` and reads each `children` file with `std::fs`, and raises the audit
//! events the Python calls raised (`os.listdir` with the path; `open` with the path, `"r"` and `O_RDONLY |
//! O_CLOEXEC`) through `sys.audit`, before each operation as CPython does: the cache with proof sees the same reads
//! (they flag the test "reads /proc": a sleep that is virtual makes the test not cacheable, as before).

use crate::level0::{
    clock_advance_rs, clock_is_installed, clock_other_event_rs, clock_read_rel, int_arg, int_obj, ns_to_secs,
    record_from_rust, state_attr, wall_ns, MONO_BASE_NS,
};
use crate::standin::{bind, call_with};
use pyo3::exceptions::{
    PyAttributeError, PyDeprecationWarning, PyException, PyNameError, PyOSError, PyRuntimeError, PyTypeError,
    PyValueError,
};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyCFunction, PyDict, PyFloat, PyInt, PyString, PyTuple};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, MutexGuard};

const NS: i64 = 1_000_000_000;

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// `detpy.clock`'s module globals (`clock_configure`).
static GLOBALS: Mutex<Option<Py<PyDict>>> = Mutex::new(None);

/// `clock._EXTERNAL["started"]`: the running test started another process (subprocess, fork, spawn); until the test
/// ends, sleeps also wait for real.
static EXTERNAL: AtomicBool = AtomicBool::new(false);

pub(crate) fn reset_external() {
    EXTERNAL.store(false, Ordering::Relaxed);
}

/// `clock_configure(globals)`: the module globals of `detpy.clock`, where the stand-ins read the real functions.
#[pyfunction]
pub fn clock_configure(globals: Py<PyDict>) {
    let old = lock(&GLOBALS).replace(globals);
    drop(old);
}

/// A global of `detpy.clock`, read at call time like the Python function read it (None: not defined).
fn g_opt<'py>(py: Python<'py>, name: &Bound<'py, PyString>) -> PyResult<Option<Bound<'py, PyAny>>> {
    let d = lock(&GLOBALS)
        .as_ref()
        .map(|d| d.clone_ref(py))
        .ok_or_else(|| PyRuntimeError::new_err("detpy.clock not configured"))?;
    d.bind(py).get_item(name)
}

/// A global of `detpy.clock`, read at call time like the Python function read it.
fn g<'py>(py: Python<'py>, name: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    g_opt(py, name)?.ok_or_else(|| PyNameError::new_err(format!("name '{name}' is not defined")))
}

/// `getattr(o, name, default)`: only an AttributeError gives the default.
fn getattr_or<'py>(
    o: &Bound<'py, PyAny>,
    name: &Bound<'py, PyString>,
    default: Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    match o.getattr(name) {
        Ok(v) => Ok(v),
        Err(e) if e.is_instance_of::<PyAttributeError>(o.py()) => Ok(default),
        Err(e) => Err(e),
    }
}

/// `int(x)`.
fn int_of<'py>(x: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    x.py().get_type::<PyInt>().call1((x,))
}

/// `int(timeout * NS)` as the clock's integer (saturating, as `CLOCK.advance` does).
fn timeout_ns(timeout: &Bound<'_, PyAny>) -> PyResult<i128> {
    int_arg(&int_of(&timeout.mul(NS)?)?)
}

/// `sys.modules.get(name)` (None when missing).
fn sys_module<'py>(py: Python<'py>, sys: &Bound<'py, PyAny>, name: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    let mods = sys.getattr(intern!(py, "modules"))?;
    match mods.cast_exact::<PyDict>() {
        Ok(d) => Ok(d.get_item(name)?.unwrap_or_else(|| py.None().into_bound(py))),
        Err(_) => mods.call_method1(intern!(py, "get"), (name,)),
    }
}

// ---------------------------------------------------------------------------------------------------------------
// time.sleep

/// `clock._other_threads_alive()`: a thread other than this one and detpy's own (`detpy-*`) is alive.
#[pyfunction]
pub fn clock_other_threads_alive(py: Python<'_>) -> PyResult<bool> {
    let threading = g(py, intern!(py, "threading"))?;
    let all = threading.getattr(intern!(py, "enumerate"))?.call0()?;
    for t in all.try_iter()? {
        let t = t?;
        let current = threading.getattr(intern!(py, "current_thread"))?.call0()?;
        if t.is(&current) {
            continue;
        }
        let name = t.getattr(intern!(py, "name"))?;
        let detpy = match name.cast_exact::<PyString>() {
            Ok(s) => s.to_cow().map(|c| c.starts_with("detpy-")).unwrap_or(false),
            Err(_) => name.call_method1(intern!(py, "startswith"), ("detpy-",))?.is_truthy()?,
        };
        if !detpy {
            return Ok(true);
        }
    }
    Ok(false)
}

/// `clock._in_event_loop()`: an asyncio event loop runs in this thread.
#[pyfunction]
pub fn clock_in_event_loop(py: Python<'_>) -> PyResult<bool> {
    let aio = sys_module(py, &g(py, intern!(py, "sys"))?, intern!(py, "asyncio"))?;
    if aio.is_none() {
        return Ok(false);
    }
    match aio.getattr(intern!(py, "_get_running_loop")).and_then(|f| f.call0()) {
        Ok(loop_) => Ok(!loop_.is_none()),
        Err(e) if e.is_instance_of::<PyException>(py) => Ok(false),
        Err(e) => Err(e),
    }
}

static AUDIT: PyOnceLock<Py<PyAny>> = PyOnceLock::new();
static OPEN_FLAGS: PyOnceLock<Py<PyAny>> = PyOnceLock::new();
static REAL_OPEN: PyOnceLock<Py<PyAny>> = PyOnceLock::new();
static REAL_LISTDIR: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

/// `sys.audit(event, *args)`; an OSError (from an audit hook) is `Ok(false)` (`_children_alive` caught OSError).
fn audit(py: Python<'_>, args: Bound<'_, PyTuple>) -> PyResult<bool> {
    let f = AUDIT.get_or_try_init(py, || -> PyResult<Py<PyAny>> { Ok(py.import("sys")?.getattr("audit")?.unbind()) })?;
    match f.bind(py).call1(args) {
        Ok(_) => Ok(true),
        Err(e) if e.is_instance_of::<PyOSError>(py) => Ok(false),
        Err(e) => Err(e),
    }
}

/// The builtin `name` as a global of `detpy.clock` sees it (module globals, then builtins).
fn builtin<'py>(py: Python<'py>, name: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    match g_opt(py, name)? {
        Some(v) => Ok(v),
        None => py.import(intern!(py, "builtins"))?.getattr(name),
    }
}

/// `with open(path) as f: f.read().strip()` through a replaced `open` (a test's `mock_open`): the same Python calls
/// and `with` protocol. `Ok(None)`: an exception the context manager suppressed.
fn read_through<'py>(py: Python<'py>, open_: &Bound<'py, PyAny>, path: &str) -> PyResult<Option<bool>> {
    let f = open_.call1((path,))?;
    let tp = f.get_type();
    let enter = tp.getattr(intern!(py, "__enter__"))?;
    let exit = tp.getattr(intern!(py, "__exit__"))?;
    let fh = enter.call1((&f,))?;
    let body = fh
        .call_method0(intern!(py, "read"))
        .and_then(|d| d.call_method0(intern!(py, "strip")))
        .and_then(|d| d.is_truthy());
    match body {
        Ok(v) => {
            exit.call1((&f, py.None(), py.None(), py.None()))?;
            Ok(Some(v))
        }
        Err(e) => {
            let (t, v, tb) = (e.get_type(py), e.value(py).clone(), e.traceback(py));
            if exit.call1((&f, t, v, tb))?.is_truthy()? {
                Ok(None)
            } else {
                Err(e)
            }
        }
    }
}

/// `clock._children_alive()`: this process has live child processes (Linux: `/proc/self/task/*/children`).
#[pyfunction]
pub fn clock_children_alive(py: Python<'_>) -> PyResult<bool> {
    const TASKS: &str = "/proc/self/task";
    let real_listdir = REAL_LISTDIR.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
        let m = py.import("posix").or_else(|_| py.import("nt"))?;
        Ok(m.getattr("listdir")?.unbind())
    })?;
    let listdir = g(py, intern!(py, "_real_listdir"))?;
    let names: Vec<String> = if listdir.is(real_listdir.bind(py)) {
        // _real_listdir("/proc/self/task"): the audit event, then the whole listing (an error: False)
        if !audit(py, PyTuple::new(py, ["os.listdir", TASKS])?)? {
            return Ok(false);
        }
        match std::fs::read_dir(TASKS)
            .and_then(|rd| rd.map(|e| e.map(|e| e.file_name().to_string_lossy().into_owned())).collect())
        {
            Ok(n) => n,
            Err(_) => return Ok(false),
        }
    } else {
        let listing = match listdir.call1((TASKS,)) {
            Ok(l) => l,
            Err(e) if e.is_instance_of::<PyOSError>(py) => return Ok(false),
            Err(e) => return Err(e),
        };
        let mut n = Vec::new();
        for tid in listing.try_iter()? {
            n.push(tid?.str()?.to_cow()?.into_owned());
        }
        n
    };
    let real_open =
        REAL_OPEN.get_or_try_init(py, || -> PyResult<Py<PyAny>> { Ok(py.import("_io")?.getattr("open")?.unbind()) })?;
    let flags = OPEN_FLAGS.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
        let os = py.import("os")?;
        let rd = os.getattr("O_RDONLY")?;
        let flags = match os.getattr("O_CLOEXEC") {
            Ok(c) => rd.bitor(c)?,
            Err(_) => rd,
        };
        Ok(flags.unbind())
    })?;
    for tid in names {
        let path = format!("{TASKS}/{tid}/children");
        let open_ = builtin(py, intern!(py, "open"))?;
        if !open_.is(real_open.bind(py)) {
            // open replaced (a test's mock_open): what the Python function did, through it
            match read_through(py, &open_, &path) {
                Ok(Some(true)) => return Ok(true),
                Ok(_) => continue,
                Err(e) if e.is_instance_of::<PyOSError>(py) => return Ok(false),
                Err(e) => return Err(e),
            }
        }
        // open(path): the audit event of FileIO ("open", path, "r", O_RDONLY | O_CLOEXEC), then the read
        let args = PyTuple::new(
            py,
            [PyString::new(py, "open").into_any(), PyString::new(py, &path).into_any(), PyString::new(py, "r").into_any(), flags.bind(py).clone()],
        )?;
        if !audit(py, args)? {
            return Ok(false);
        }
        match std::fs::read(&path) {
            // f.read().strip(): the file holds pids separated by spaces
            Ok(b) => {
                if b.iter().any(|c| !matches!(c, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c | 0x1c..=0x1f)) {
                    return Ok(true);
                }
            }
            Err(_) => return Ok(false),
        }
    }
    Ok(false)
}

/// The decision of `clock.sleep` to wait for real as well: someone observes real time (`--det-sleep=real`, another
/// thread, a running event loop, a process started by the test, a live child process).
fn sleeps_for_real(py: Python<'_>) -> PyResult<bool> {
    let mode = state_attr(py, intern!(py, "config"))?.getattr(intern!(py, "sleep"))?;
    Ok(mode.eq("real")?
        || clock_other_threads_alive(py)?
        || clock_in_event_loop(py)?
        || EXTERNAL.load(Ordering::Relaxed)
        || clock_children_alive(py)?)
}

// Virtual `time.sleep(secs)` (no docstring: the stand-in had none).
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(secs)")]
pub fn sleep<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    let [secs] = bind("sleep", ["secs"], 1, args, kwargs)?;
    let mut secs = secs.expect("required");
    let real_sleep = g(py, intern!(py, "real_sleep"))?;
    if !clock_is_installed() {
        return real_sleep.call1((secs,));
    }
    // Same argument validation as the real function.
    let float_t = py.get_type::<PyFloat>();
    if !(secs.is_instance(&py.get_type::<PyInt>())? || secs.is_instance(&float_t)?) {
        match float_t.call1((&secs,)) {
            Ok(f) => secs = f, // Decimal, Fraction, numpy scalars
            Err(e) if e.is_instance_of::<PyTypeError>(py) || e.is_instance_of::<PyValueError>(py) => {
                let name = secs.get_type().getattr(intern!(py, "__name__"))?.str()?;
                let err = PyTypeError::new_err(format!(
                    "'{}' object cannot be interpreted as an integer or float",
                    name.to_cow()?
                ));
                err.set_context(py, Some(e)); // raised while handling it, as the Python function did
                return Err(err);
            }
            Err(e) => return Err(e),
        }
    }
    if secs.ne(&secs)? {
        return Err(PyValueError::new_err("Invalid value NaN (not a number)"));
    }
    if secs.lt(0)? {
        return Err(PyValueError::new_err("sleep length must be non-negative"));
    }
    let ns = int_of(&secs.mul(NS)?)?;
    clock_other_event_rs(); // a sleep is not a read: it ends a run of reads
    record_from_rust(py, "time", "time.sleep", ns.str()?.to_cow()?.into_owned(), 0)?;
    clock_advance_rs(int_arg(&ns)?);
    if sleeps_for_real(py)? {
        // Someone observes real time: wait for real as well; the virtual clock still advances.
        real_sleep.call1((secs,))?;
    } else {
        real_sleep.call1((0,))?; // still yield the GIL / scheduler
    }
    Ok(py.None().into_bound(py))
}

// ---------------------------------------------------------------------------------------------------------------
// The "a process was started" flag (`_mark_external`)

/// `clock._EXTERNAL["started"]` (for the tests).
#[pyfunction]
pub fn clock_external_started() -> bool {
    EXTERNAL.load(Ordering::Relaxed)
}

/// `_EXTERNAL["started"] = True`.
#[pyfunction]
pub fn clock_mark_external() {
    EXTERNAL.store(true, Ordering::Relaxed);
}

/// Stand-in for a function that starts a process (`os.fork`, `os.system`, ...): sets the flag, calls the real one.
/// Like the builtin it replaces, it does not bind as a method.
#[pyclass(module = "detpy._core", name = "external_stand_in", frozen, dict, weakref)]
pub(crate) struct ExternalStandIn {
    real: Py<PyAny>,
}

#[pymethods]
impl ExternalStandIn {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        EXTERNAL.store(true, Ordering::Relaxed);
        call_with(self.real.bind(py), args, kwargs)
    }

    fn __reduce__(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        Ok(slf.getattr(intern!(slf.py(), "__qualname__"))?.unbind()) // pickled by reference, like the builtin
    }

    fn __repr__(slf: &Bound<'_, Self>) -> PyResult<String> {
        let name = slf.getattr(intern!(slf.py(), "__name__"))?;
        Ok(format!("<built-in function {}>", name.str()?.to_cow()?))
    }
}

/// Stand-in for a Python method that starts a process (`subprocess.Popen.__init__`): binds like the function.
#[pyclass(module = "detpy._core", name = "external_method_stand_in", frozen, dict, weakref)]
pub(crate) struct ExternalMethodStandIn {
    real: Py<PyAny>,
}

static METHOD_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

#[pymethods]
impl ExternalMethodStandIn {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        EXTERNAL.store(true, Ordering::Relaxed);
        call_with(self.real.bind(py), args, kwargs)
    }

    /// Like a function: the object itself through the class, a bound method through an instance.
    fn __get__<'py>(
        slf: &Bound<'py, Self>,
        obj: Option<&Bound<'py, PyAny>>,
        _owner: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match obj {
            Some(o) if !o.is_none() => {
                let py = slf.py();
                let mt = METHOD_TYPE.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
                    Ok(py.import("types")?.getattr("MethodType")?.unbind())
                })?;
                mt.bind(py).call1((slf, o))
            }
            _ => Ok(slf.clone().into_any()),
        }
    }

    fn __repr__(slf: &Bound<'_, Self>) -> PyResult<String> {
        let name = slf.getattr(intern!(slf.py(), "__qualname__"))?;
        Ok(format!("<function {}>", name.str()?.to_cow()?))
    }
}

/// `clock_external_stand_in(real, binds)`: the stand-in of `_mark_external(real)` (attributes set by the caller).
#[pyfunction]
pub fn clock_external_stand_in<'py>(py: Python<'py>, real: Py<PyAny>, binds: bool) -> PyResult<Bound<'py, PyAny>> {
    Ok(if binds {
        Bound::new(py, ExternalMethodStandIn { real })?.into_any()
    } else {
        Bound::new(py, ExternalStandIn { real })?.into_any()
    })
}

// ---------------------------------------------------------------------------------------------------------------
// Wall-derived functions

/// `clock._wall_secs(op)`: read the clock, record `("time", op, rel)` at the caller's site (`skip` frames above the
/// current one), return the wall clock in seconds; `real_time()` with the clock not installed.
fn wall_secs<'py>(py: Python<'py>, op: &str, skip: usize) -> PyResult<Bound<'py, PyAny>> {
    if !clock_is_installed() {
        return g(py, intern!(py, "real_time"))?.call0();
    }
    let (e, rel) = clock_read_rel();
    record_from_rust(py, "time", op, rel.to_string(), skip)?;
    Ok(PyFloat::new(py, ns_to_secs(wall_ns(py, e)?)).into_any())
}

/// `_wall_secs(op)` called from a Python function `skip` frames below the caller whose site is recorded.
#[pyfunction]
pub fn clock_wall_secs<'py>(py: Python<'py>, op: &str, skip: usize) -> PyResult<Bound<'py, PyAny>> {
    wall_secs(py, op, skip)
}

/// `real_<name>(_wall_secs("time.<name>") if secs is None else secs)`.
fn wall_derived<'py>(
    py: Python<'py>,
    name: &str,
    real: &Bound<'py, PyString>,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    let [secs] = bind(name, ["secs"], 0, args, kwargs)?;
    let real = g(py, real)?;
    let arg = match secs {
        Some(s) if !s.is_none() => s,
        _ => wall_secs(py, &format!("time.{name}"), 0)?,
    };
    real.call1((arg,))
}

// Virtual `time.localtime(secs=None)`.
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(secs=None)")]
pub fn localtime<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    wall_derived(py, "localtime", intern!(py, "real_localtime"), args, kwargs)
}

// Virtual `time.gmtime(secs=None)`.
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(secs=None)")]
pub fn gmtime<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    wall_derived(py, "gmtime", intern!(py, "real_gmtime"), args, kwargs)
}

// Virtual `time.ctime(secs=None)`.
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(secs=None)")]
pub fn ctime<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    wall_derived(py, "ctime", intern!(py, "real_ctime"), args, kwargs)
}

/// `real_localtime(_wall_secs(op))`.
fn local_now<'py>(py: Python<'py>, op: &str) -> PyResult<Bound<'py, PyAny>> {
    let real_localtime = g(py, intern!(py, "real_localtime"))?;
    real_localtime.call1((wall_secs(py, op, 0)?,))
}

// Virtual `time.asctime(t=None)`.
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(t=None)")]
pub fn asctime<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    let [t] = bind("asctime", ["t"], 0, args, kwargs)?;
    let real = g(py, intern!(py, "real_asctime"))?;
    let arg = match t {
        Some(t) if !t.is_none() => t,
        _ => local_now(py, "time.asctime")?,
    };
    real.call1((arg,))
}

// Virtual `time.strftime(fmt, t=None)`.
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(fmt, t=None)")]
pub fn strftime<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    let [fmt, t] = bind("strftime", ["fmt", "t"], 1, args, kwargs)?;
    let real = g(py, intern!(py, "real_strftime"))?;
    let arg = match t {
        Some(t) if !t.is_none() => t,
        _ => local_now(py, "time.strftime")?,
    };
    real.call1((fmt.expect("required"), arg))
}

// ---------------------------------------------------------------------------------------------------------------
// clock_gettime

/// `clk_id in clock.<set>`.
fn clock_in(py: Python<'_>, set: &Bound<'_, PyString>, clk: &Bound<'_, PyAny>) -> PyResult<bool> {
    g(py, set)?.contains(clk)
}

// Virtual `time.clock_gettime_ns(clk_id)`.
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(clk_id)")]
pub fn clock_gettime_ns<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    let [clk] = bind("clock_gettime_ns", ["clk_id"], 1, args, kwargs)?;
    let clk = clk.expect("required");
    let real = intern!(py, "real_clock_gettime_ns");
    if !clock_is_installed() {
        return g(py, real)?.call1((clk,));
    }
    let wall = clock_in(py, intern!(py, "_REALTIME"), &clk)?;
    if wall || clock_in(py, intern!(py, "_MONOTONIC"), &clk)? {
        let (e, rel) = clock_read_rel();
        record_from_rust(py, "time", "time.clock_gettime", rel.to_string(), 0)?;
        let ns = if wall { wall_ns(py, e)? } else { MONO_BASE_NS.saturating_add(e) };
        return int_obj(py, ns);
    }
    g(py, real)?.call1((clk,))
}

// Virtual `time.clock_gettime(clk_id)`.
#[pyfunction]
#[pyo3(signature = (*args, **kwargs), text_signature = "(clk_id)")]
pub fn clock_gettime<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    let [clk] = bind("clock_gettime", ["clk_id"], 1, args, kwargs)?;
    let clk = clk.expect("required");
    let real = intern!(py, "real_clock_gettime");
    if !clock_is_installed() {
        return g(py, real)?.call1((clk,));
    }
    let realtime = intern!(py, "_REALTIME");
    if clock_in(py, realtime, &clk)? || clock_in(py, intern!(py, "_MONOTONIC"), &clk)? {
        let (e, rel) = clock_read_rel();
        record_from_rust(py, "time", "time.clock_gettime", rel.to_string(), 0)?;
        // (CLOCK.wall_ns(e) if clk_id in _REALTIME else CLOCK.mono_ns(e)) / NS: the membership is evaluated again
        let ns = if clock_in(py, realtime, &clk)? { wall_ns(py, e)? } else { MONO_BASE_NS.saturating_add(e) };
        return Ok(PyFloat::new(py, ns_to_secs(ns)).into_any());
    }
    g(py, real)?.call1((clk,))
}

// ---------------------------------------------------------------------------------------------------------------
// datetime.now / utcnow (installed as classmethods of the real datetime type)

/// `cls.fromtimestamp`, if it is the C one (no Python frame runs under it); None for a Python override, which the
/// Python helper calls so that it runs under a detpy frame, as it ran under `_dt_now`.
fn c_fromtimestamp<'py>(cls: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyAny>>> {
    let f = cls.getattr(intern!(cls.py(), "fromtimestamp"))?;
    Ok(if f.is_instance_of::<PyCFunction>() { Some(f) } else { None })
}

// `datetime.now(tz=None)` (the classmethod's function).
#[pyfunction]
#[pyo3(name = "_dt_now", signature = (*args, **kwargs), text_signature = "(cls, tz=None)")]
pub fn dt_now<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    let [cls, tz] = bind("_dt_now", ["cls", "tz"], 1, args, kwargs)?;
    let cls = cls.expect("required");
    let tz = tz.unwrap_or_else(|| py.None().into_bound(py));
    match c_fromtimestamp(&cls)? {
        Some(f) => f.call1((wall_secs(py, "datetime.now", 0)?, tz)),
        None => g(py, intern!(py, "_dt_now_py"))?.call1((cls, tz)),
    }
}

const UTCNOW_DEPRECATED: &str = "datetime.datetime.utcnow() is deprecated and scheduled for removal in a future \
version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).";

// `datetime.utcnow()` (the classmethod's function).
#[pyfunction]
#[pyo3(name = "_dt_utcnow", signature = (*args, **kwargs), text_signature = "(cls)")]
pub fn dt_utcnow<'py>(py: Python<'py>, args: &Bound<'py, PyTuple>, kwargs: Option<&Bound<'py, PyDict>>) -> PyResult<Bound<'py, PyAny>> {
    let [cls] = bind("_dt_utcnow", ["cls"], 1, args, kwargs)?;
    let cls = cls.expect("required");
    if py.version_info() >= (3, 12) {
        // stacklevel=2 from the Python function = the caller's frame, which is the current frame here
        let kw = PyDict::new(py);
        kw.set_item(intern!(py, "stacklevel"), 1)?;
        g(py, intern!(py, "warnings"))?
            .getattr(intern!(py, "warn"))?
            .call((UTCNOW_DEPRECATED, py.get_type::<PyDeprecationWarning>()), Some(&kw))?;
    }
    match c_fromtimestamp(&cls)? {
        Some(f) => {
            let secs = wall_secs(py, "datetime.utcnow", 0)?;
            let utc = g(py, intern!(py, "_dt"))?.getattr(intern!(py, "timezone"))?.getattr(intern!(py, "utc"))?;
            let kw = PyDict::new(py);
            kw.set_item(intern!(py, "tzinfo"), py.None())?;
            f.call1((secs, utc))?.call_method(intern!(py, "replace"), (), Some(&kw))
        }
        None => g(py, intern!(py, "_dt_utcnow_py"))?.call1((cls,)),
    }
}

// ---------------------------------------------------------------------------------------------------------------
// Wait primitives: a wait that times out advances the virtual clock by its timeout

/// `not got and timeout is not None and timeout > 0 and CLOCK is not None`.
fn timed_out(got: &Bound<'_, PyAny>, timeout: &Bound<'_, PyAny>) -> PyResult<bool> {
    Ok(!got.is_truthy()? && !timeout.is_none() && timeout.gt(0)? && clock_is_installed())
}

/// `_condition_wait(self, timeout)`: `threading.Condition.wait` (the real one), then the timeout rule.
#[pyfunction]
pub fn clock_condition_wait<'py>(py: Python<'py>, cond: &Bound<'py, PyAny>, timeout: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let got = g(py, intern!(py, "_real_condition_wait"))?.call1((cond, timeout))?;
    if timed_out(&got, timeout)? {
        clock_advance_rs(timeout_ns(timeout)?);
    }
    Ok(got)
}

/// The `select` of `_wrap_selector_select(real)`: `real(self, timeout)`, then the timeout rule rounded up to the
/// millisecond (asyncio asks for "deadline - now", a few microseconds less than the delay the code requested: the
/// virtual clock never shows less than the requested delay).
#[pyfunction]
pub fn clock_selector_select<'py>(
    real: &Bound<'py, PyAny>,
    selector: &Bound<'py, PyAny>,
    timeout: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let ready = real.call1((selector, timeout))?;
    if timed_out(&ready, timeout)? {
        // -(-int(timeout * NS) // 1_000_000) * 1_000_000
        // (beyond the clock's integer the advance saturates, as CLOCK.advance does)
        let n = timeout_ns(timeout)?;
        let up = n
            .checked_add(999_999)
            .map(|x| x.div_euclid(1_000_000))
            .and_then(|m| m.checked_mul(1_000_000))
            .unwrap_or(i128::MAX);
        clock_advance_rs(up);
    }
    Ok(ready)
}

/// `_TimedLock.acquire(blocking, timeout)` on the real lock: `lock.acquire(blocking, timeout)`; a blocking acquire
/// that times out advances the virtual clock by its timeout.
#[pyfunction]
pub fn clock_lock_acquire<'py>(
    py: Python<'py>,
    lock: &Bound<'py, PyAny>,
    blocking: &Bound<'py, PyAny>,
    timeout: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let got = lock.call_method1(intern!(py, "acquire"), (blocking, timeout))?;
    if !got.is_truthy()? && blocking.is_truthy()? && !timeout.is_none() && timeout.gt(0)? && clock_is_installed() {
        clock_advance_rs(timeout_ns(timeout)?);
    }
    Ok(got)
}

// ---------------------------------------------------------------------------------------------------------------
// time_machine

/// `clock._time_machine_ns(e)`: wall time of an active `time_machine` travel, or None. A ticking travel advances
/// with the virtual counter (from the counter at its first read), not with real time.
pub(crate) fn time_machine_ns<'py>(py: Python<'py>, e: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let none = || py.None().into_bound(py);
    let tm = sys_module(py, &g(py, intern!(py, "sys"))?, intern!(py, "time_machine"))?;
    let stack = if tm.is_none() { none() } else { getattr_or(&tm, intern!(py, "traveller_stack"), none())? };
    if !stack.is_truthy()? {
        return Ok(none());
    }
    let t = stack.get_item(-1)?;
    let dest = getattr_or(&t, intern!(py, "_destination_timestamp_ns"), none())?;
    if dest.is_none() {
        return Ok(dest);
    }
    let true_ = pyo3::types::PyBool::new(py, true).to_owned().into_any();
    if !getattr_or(&t, intern!(py, "_tick"), true_)?.is_truthy()? {
        return Ok(dest);
    }
    let start = t
        .getattr(intern!(py, "__dict__"))?
        .call_method1(intern!(py, "setdefault"), (intern!(py, "_detpy_start_elapsed"), e))?;
    let zero = 0i64.into_pyobject(py)?.into_any();
    getattr_or(&tm, intern!(py, "SYSTEM_EPOCH_TIMESTAMP_NS"), zero)?.add(&dest)?.add(e.sub(&start)?)
}

/// `clock._time_machine_ns(e)`.
#[pyfunction]
pub fn clock_time_machine_ns<'py>(py: Python<'py>, e: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    time_machine_ns(py, e)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ExternalStandIn>()?;
    m.add_class::<ExternalMethodStandIn>()?;
    for f in [
        wrap_pyfunction!(clock_configure, m)?,
        wrap_pyfunction!(sleep, m)?,
        wrap_pyfunction!(clock_other_threads_alive, m)?,
        wrap_pyfunction!(clock_in_event_loop, m)?,
        wrap_pyfunction!(clock_children_alive, m)?,
        wrap_pyfunction!(clock_external_started, m)?,
        wrap_pyfunction!(clock_mark_external, m)?,
        wrap_pyfunction!(clock_external_stand_in, m)?,
        wrap_pyfunction!(clock_wall_secs, m)?,
        wrap_pyfunction!(localtime, m)?,
        wrap_pyfunction!(gmtime, m)?,
        wrap_pyfunction!(ctime, m)?,
        wrap_pyfunction!(asctime, m)?,
        wrap_pyfunction!(strftime, m)?,
        wrap_pyfunction!(clock_gettime, m)?,
        wrap_pyfunction!(clock_gettime_ns, m)?,
        wrap_pyfunction!(dt_now, m)?,
        wrap_pyfunction!(dt_utcnow, m)?,
        wrap_pyfunction!(clock_condition_wait, m)?,
        wrap_pyfunction!(clock_selector_select, m)?,
        wrap_pyfunction!(clock_lock_acquire, m)?,
        wrap_pyfunction!(clock_time_machine_ns, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
