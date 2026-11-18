//! Level 0 hot path of `--det` in Rust: the virtual clock's state and its reads, call-site resolution and event
//! recording.
//!
//! asyncio, threading and logging read the clock on every loop iteration, lock wait or log record; in Python each
//! read ran five detpy frames (`clock.monotonic`, `VirtualClock.read` under an `RLock`, `_rel`, `_state.record`,
//! `_sites.resolve` walking the caller frames). Here the `time.*` stand-ins are builtins: one read advances the
//! counter, walks the caller frames with the classification cache of `detpy._sites` and hands the event to the
//! recorder without entering the interpreter (the cache with proof's listener, when installed, is still called).
//!
//! Port of `detpy/clock.py` (`VirtualClock`, `time`, `time_ns`, `monotonic`, `monotonic_ns`, `perf_counter`,
//! `perf_counter_ns`, `_rel`), `detpy/_sites.py` (`resolve`) and `detpy/_state.py` (`record`, `quiet`), round 1 of
//! the rust-hotpaths session. The Python originals are kept verbatim in `tests/rust_hotpaths_ref/`; traces,
//! fingerprints, cache keys and receipts are tested byte-identical against them (`tests/test_level0_rust.py`).
//!
//! Differences that cannot show in an output: the clock's counters are `i128` (Python ints are unbounded; a run would
//! need to sleep 5e21 years of virtual time to overflow them, which saturates); the clock lock is not re-entrant but
//! nothing that can run Python code (a gc callback) happens while it is held.

use crate::sysmon::LineRecorder;
use crate::Recorder;
use detpy_core::event::{Event, Source};
use pyo3::exceptions::PyRuntimeError;
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyFloat, PyString, PyTuple};
use std::cell::Cell;
use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};

const NS: i128 = 1_000_000_000;
/// `clock._MONO_BASE_NS`: arbitrary, positive, process-independent.
const MONO_BASE_NS: i128 = 1_000 * NS;
/// `clock.MAX_TICK_NS`.
pub const MAX_TICK_NS: i128 = 16_000;

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

// ---------------------------------------------------------------------------------------------------------------
// Clock state (`clock.VirtualClock`)

#[derive(Clone, Copy)]
struct ClockState {
    installed: bool,
    epoch_ns: i128,
    base_tick: i128,
    tick: i128,
    adapt_after: i128,
    streak: i128,
    elapsed: i128,
    wall_offset: i128,
    test_start: i128,
}

impl ClockState {
    const fn empty() -> Self {
        ClockState {
            installed: false,
            epoch_ns: 0,
            base_tick: 0,
            tick: 0,
            adapt_after: 0,
            streak: 0,
            elapsed: 0,
            wall_offset: 0,
            test_start: 0,
        }
    }

    /// `VirtualClock.read`: advance by one tick, return the elapsed counter.
    fn read(&mut self) -> i128 {
        self.elapsed = self.elapsed.saturating_add(self.tick);
        if self.adapt_after != 0 {
            self.streak += 1;
            if self.streak >= self.adapt_after {
                self.tick = (self.tick.max(1).saturating_mul(2)).min(MAX_TICK_NS);
            }
        }
        self.elapsed
    }

    fn other_event(&mut self) {
        if self.streak != 0 || self.tick != self.base_tick {
            self.streak = 0;
            self.tick = self.base_tick;
        }
    }

    fn advance(&mut self, ns: i128) {
        if ns > 0 {
            self.elapsed = self.elapsed.saturating_add(ns);
        }
    }

    fn start_test(&mut self) {
        self.streak = 0;
        self.tick = self.base_tick;
        self.test_start = self.elapsed;
        self.wall_offset = self.epoch_ns.saturating_sub(self.elapsed);
    }
}

static CLOCK: Mutex<ClockState> = Mutex::new(ClockState::empty());

/// Real functions (`clock.real_*`), called by a stand-in when the clock is not installed (a reference kept after
/// uninstall), and `clock._time_machine_ns`.
struct ClockHooks {
    reals: Vec<Py<PyAny>>,
    time_machine_ns: Py<PyAny>,
}

static HOOKS: Mutex<Option<Arc<ClockHooks>>> = Mutex::new(None);

#[derive(Clone, Copy)]
enum Fake {
    Time,
    TimeNs,
    Monotonic,
    MonotonicNs,
    PerfCounter,
    PerfCounterNs,
}

impl Fake {
    fn op(self) -> &'static str {
        match self {
            Fake::Time => "time.time",
            Fake::TimeNs => "time.time_ns",
            Fake::Monotonic => "time.monotonic",
            Fake::MonotonicNs => "time.monotonic_ns",
            Fake::PerfCounter => "time.perf_counter",
            Fake::PerfCounterNs => "time.perf_counter_ns",
        }
    }
}

/// `n / 10**9` rounded as Python's `int / int` true division rounds it: the correctly rounded (nearest, ties to
/// even) double of the exact quotient.
pub fn ns_to_secs(n: i128) -> f64 {
    let neg = n < 0;
    let a = n.unsigned_abs();
    const D: u128 = 1_000_000_000;
    let q = if a < (1u128 << 53) {
        // both operands exact in a double: one correctly rounded division (CPython's fast path)
        a as f64 / D as f64
    } else {
        // scale so the integer quotient has at least 55 significant bits, fold the remainder into a sticky bit,
        // round once in the integer-to-double conversion, then rescale exactly
        let bits = 128 - a.leading_zeros() as i32; // >= 54
        let k = (55 + 30 - bits).max(0) as u32; // quotient bits ~ bits + k - 30
        let num = a << k;
        let (q, r) = (num / D, num % D);
        let q = q | u128::from(r != 0);
        (q as f64) * f64::powi(2.0, -(k as i32))
    };
    if neg {
        -q
    } else {
        q
    }
}

fn int_obj(py: Python<'_>, v: i128) -> PyResult<Bound<'_, PyAny>> {
    match i64::try_from(v) {
        Ok(x) => Ok(x.into_pyobject(py)?.into_any()),
        Err(_) => Ok(v.into_pyobject(py)?.into_any()),
    }
}

fn int_arg(v: &Bound<'_, PyAny>) -> PyResult<i128> {
    match v.extract::<i64>() {
        Ok(x) => Ok(x as i128),
        Err(_) => match v.extract::<i128>() {
            Ok(x) => Ok(x),
            Err(e) => {
                // beyond i128 (a sleep of more than 5e21 years): saturate, like the counters
                let big: bool = v.gt(0)?;
                if v.is_instance_of::<pyo3::types::PyInt>() {
                    Ok(if big { i128::MAX } else { i128::MIN })
                } else {
                    Err(e)
                }
            }
        },
    }
}

/// Wall clock at counter `e` (`VirtualClock.wall_ns`): an active `time_machine` travel, else epoch-relative.
fn wall_ns(py: Python<'_>, e: i128) -> PyResult<i128> {
    if time_machine_loaded(py) {
        let hooks = lock(&HOOKS).clone();
        if let Some(h) = hooks {
            let travel = h.time_machine_ns.bind(py).call1((int_obj(py, e)?,))?;
            if !travel.is_none() {
                return int_arg(&travel);
            }
        }
    }
    Ok(lock(&CLOCK).wall_offset.saturating_add(e))
}

/// `sys.modules.get("time_machine") is not None` (`_time_machine_ns` only acts then).
fn time_machine_loaded(py: Python<'_>) -> bool {
    unsafe {
        let mods = ffi::PySys_GetObject(c"modules".as_ptr()); // borrowed
        if mods.is_null() || ffi::PyDict_Check(mods) == 0 {
            return true; // unusual sys.modules: let the Python helper decide
        }
        let key = intern!(py, "time_machine");
        let v = ffi::PyDict_GetItemWithError(mods, key.as_ptr()); // borrowed
        if v.is_null() {
            ffi::PyErr_Clear();
            return false;
        }
        v != ffi::Py_None()
    }
}

fn call_real(py: Python<'_>, which: Fake) -> PyResult<Py<PyAny>> {
    let hooks = lock(&HOOKS).clone().ok_or_else(|| PyRuntimeError::new_err("detpy clock: real functions not set"))?;
    Ok(hooks.reals[which as usize].bind(py).call0()?.unbind())
}

fn clock_read_fake(py: Python<'_>, which: Fake) -> PyResult<Py<PyAny>> {
    let (e, rel) = {
        let mut g = lock(&CLOCK);
        if !g.installed {
            drop(g);
            return call_real(py, which);
        }
        let e = g.read();
        (e, e - g.test_start)
    };
    record_from_rust(py, "time", which.op(), rel.to_string(), 0)?;
    let ns = match which {
        Fake::Time | Fake::TimeNs => wall_ns(py, e)?,
        _ => MONO_BASE_NS.saturating_add(e),
    };
    Ok(match which {
        Fake::Time | Fake::Monotonic | Fake::PerfCounter => PyFloat::new(py, ns_to_secs(ns)).into_any().unbind(),
        _ => int_obj(py, ns)?.unbind(),
    })
}

// Virtual `time.time()` (no docstring: the stand-ins had none).
#[pyfunction]
pub fn time(py: Python<'_>) -> PyResult<Py<PyAny>> {
    clock_read_fake(py, Fake::Time)
}

// Virtual `time.time_ns()` (no docstring: the stand-ins had none).
#[pyfunction]
pub fn time_ns(py: Python<'_>) -> PyResult<Py<PyAny>> {
    clock_read_fake(py, Fake::TimeNs)
}

// Virtual `time.monotonic()` (no docstring: the stand-ins had none).
#[pyfunction]
pub fn monotonic(py: Python<'_>) -> PyResult<Py<PyAny>> {
    clock_read_fake(py, Fake::Monotonic)
}

// Virtual `time.monotonic_ns()` (no docstring: the stand-ins had none).
#[pyfunction]
pub fn monotonic_ns(py: Python<'_>) -> PyResult<Py<PyAny>> {
    clock_read_fake(py, Fake::MonotonicNs)
}

// Virtual `time.perf_counter()` (no docstring: the stand-ins had none).
#[pyfunction]
pub fn perf_counter(py: Python<'_>) -> PyResult<Py<PyAny>> {
    clock_read_fake(py, Fake::PerfCounter)
}

// Virtual `time.perf_counter_ns()` (no docstring: the stand-ins had none).
#[pyfunction]
pub fn perf_counter_ns(py: Python<'_>) -> PyResult<Py<PyAny>> {
    clock_read_fake(py, Fake::PerfCounterNs)
}

/// `clock_set_hooks(reals, time_machine_ns)`: the real `time`, `time_ns`, `monotonic`, `monotonic_ns`,
/// `perf_counter`, `perf_counter_ns` (in that order) and `clock._time_machine_ns`.
#[pyfunction]
pub fn clock_set_hooks(reals: Vec<Py<PyAny>>, time_machine_ns: Py<PyAny>) -> PyResult<()> {
    if reals.len() != 6 {
        return Err(PyRuntimeError::new_err("clock_set_hooks: 6 real functions expected"));
    }
    *lock(&HOOKS) = Some(Arc::new(ClockHooks { reals, time_machine_ns }));
    Ok(())
}

/// A fresh clock (`VirtualClock(epoch_ns, tick_ns, adapt_after)`); the stand-ins use it once activated
/// (`clock_activate`, i.e. `clock.CLOCK` set).
#[pyfunction]
pub fn clock_install(epoch_ns: &Bound<'_, PyAny>, tick_ns: &Bound<'_, PyAny>, adapt_after: &Bound<'_, PyAny>) -> PyResult<()> {
    let (epoch, tick, adapt) = (int_arg(epoch_ns)?, int_arg(tick_ns)?, int_arg(adapt_after)?);
    let mut g = lock(&CLOCK);
    *g = ClockState {
        installed: g.installed,
        epoch_ns: epoch,
        base_tick: tick,
        tick,
        adapt_after: adapt,
        streak: 0,
        elapsed: 0,
        wall_offset: epoch,
        test_start: 0,
    };
    Ok(())
}

/// `clock.CLOCK` set (True) or cleared: whether the stand-ins read the virtual clock or call the real functions.
#[pyfunction]
pub fn clock_activate(on: bool) {
    lock(&CLOCK).installed = on;
}

#[pyfunction]
pub fn clock_installed() -> bool {
    lock(&CLOCK).installed
}

/// `VirtualClock.read()`.
#[pyfunction]
pub fn clock_read(py: Python<'_>) -> PyResult<Bound<'_, PyAny>> {
    let e = lock(&CLOCK).read();
    int_obj(py, e)
}

/// `VirtualClock.other_event()`.
#[pyfunction]
pub fn clock_other_event() {
    lock(&CLOCK).other_event()
}

/// `VirtualClock.advance(ns)`.
#[pyfunction]
pub fn clock_advance(ns: &Bound<'_, PyAny>) -> PyResult<()> {
    let ns = int_arg(ns)?;
    lock(&CLOCK).advance(ns);
    Ok(())
}

/// `VirtualClock.start_test()` (the Python facade also resets `_EXTERNAL`).
#[pyfunction]
pub fn clock_start_test() {
    lock(&CLOCK).start_test()
}

/// `VirtualClock.wall_ns(e)`.
#[pyfunction]
pub fn clock_wall_ns<'py>(py: Python<'py>, e: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let w = wall_ns(py, int_arg(e)?)?;
    int_obj(py, w)
}

/// `clock._rel(e)`: the counter relative to the start of the test, as recorded in events.
#[pyfunction]
pub fn clock_rel(e: &Bound<'_, PyAny>) -> PyResult<String> {
    let e = int_arg(e)?;
    Ok((e - lock(&CLOCK).test_start).to_string())
}

/// `n / 10**9` as Python rounds it (exposed for the tests).
#[pyfunction]
pub fn clock_ns_to_secs(n: &Bound<'_, PyAny>) -> PyResult<f64> {
    Ok(ns_to_secs(int_arg(n)?))
}

/// The clock's fields, for introspection: `{epoch_ns, base_tick_ns, tick_ns, adapt_after, streak, elapsed,
/// wall_offset, test_start, installed}`.
#[pyfunction]
pub fn clock_state(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let g = *lock(&CLOCK);
    let d = PyDict::new(py);
    d.set_item("epoch_ns", int_obj(py, g.epoch_ns)?)?;
    d.set_item("base_tick_ns", int_obj(py, g.base_tick)?)?;
    d.set_item("tick_ns", int_obj(py, g.tick)?)?;
    d.set_item("adapt_after", int_obj(py, g.adapt_after)?)?;
    d.set_item("streak", int_obj(py, g.streak)?)?;
    d.set_item("elapsed", int_obj(py, g.elapsed)?)?;
    d.set_item("wall_offset", int_obj(py, g.wall_offset)?)?;
    d.set_item("test_start", int_obj(py, g.test_start)?)?;
    d.set_item("installed", g.installed)?;
    Ok(d)
}

// ---------------------------------------------------------------------------------------------------------------
// Event recording (`_state.record`) and call sites (`_sites.resolve`)

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Stdlib,
    Infra,
    User,
}

/// A classification tuple of `_sites._cache` (kept alive), its kind and its path as UTF-8 (`Err` for a path with
/// surrogates).
type Norm = (Py<PyAny>, Kind, Result<String, ()>);

/// What `_state.record` reads: the `STATE` object, `_state`'s and `_sites`' module globals (`_event_listener`,
/// `_on_other_event`; `_cache`, `_classify`) and the kind constants of `_sites`.
struct Hub {
    state: Py<PyAny>,
    state_globals: Py<PyDict>,
    sites_globals: Py<PyDict>,
    user: Py<PyAny>,
    infra: Py<PyAny>,
    /// classification tuples of `_sites._cache` seen so far -> (kind, normalised path as UTF-8); the tuple is kept
    /// alive so its address is not reused while it is a key
    norms: Mutex<HashMap<usize, Norm>>,
}

static HUB: Mutex<Option<Arc<Hub>>> = Mutex::new(None);

thread_local! {
    /// `_state._tls.busy`: patched APIs called inside `_state.quiet()` do not record events.
    static BUSY: Cell<bool> = const { Cell::new(false) };
}

/// The cache with proof's listener (`Capture.event`) flags the context with the event's source; once it said so
/// (returned True: a source flagged in a context that is not import time), calling it again for the same source
/// changes nothing until the context changes (`Capture.switch` -> `l0_listener_reset`). Import time (the line
/// recorder's module depth > 0) always calls it: its context depends on the frames.
struct Memo {
    listener: Py<PyAny>,
    lines: Py<LineRecorder>,
    sources: Vec<String>,
}

static MEMO: Mutex<Option<Memo>> = Mutex::new(None);
static MEMO_SKIPPED: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Listener calls the memo saved so far in this process (for the tests).
#[pyfunction]
pub fn l0_listener_skipped() -> u64 {
    MEMO_SKIPPED.load(std::sync::atomic::Ordering::Relaxed)
}

/// `l0_listener_memo(listener, line_recorder)`: remember what `listener` flagged (None: stop).
#[pyfunction]
#[pyo3(signature = (listener, lines = None))]
pub fn l0_listener_memo(listener: Option<Py<PyAny>>, lines: Option<Py<LineRecorder>>) {
    let new = match (listener, lines) {
        (Some(l), Some(r)) => Some(Memo { listener: l, lines: r, sources: Vec::new() }),
        _ => None,
    };
    let old = std::mem::replace(&mut *lock(&MEMO), new);
    drop(old);
}

/// The capture's context changed: every source must be flagged again.
#[pyfunction]
pub fn l0_listener_reset() {
    if let Some(m) = lock(&MEMO).as_mut() {
        m.sources.clear();
    }
}

/// Whether calling `listener` for `source` now would change nothing (see `Memo`).
fn memo_covers(py: Python<'_>, listener: &Bound<'_, PyAny>, source: &str) -> bool {
    let g = lock(&MEMO);
    match g.as_ref() {
        Some(m) => {
            m.listener.bind(py).is(listener)
                && m.sources.iter().any(|s| s == source)
                && m.lines.bind(py).get().depth() == 0
        }
        None => false,
    }
}

fn memo_note(py: Python<'_>, listener: &Bound<'_, PyAny>, source: &str) {
    let mut g = lock(&MEMO);
    if let Some(m) = g.as_mut() {
        if m.listener.bind(py).is(listener) && !m.sources.iter().any(|s| s == source) {
            m.sources.push(source.to_string());
        }
    }
}

/// `l0_configure(state, state_globals, sites_globals)`: wire the record path to `detpy._state` and `detpy._sites`.
#[pyfunction]
pub fn l0_configure(
    state: Py<PyAny>,
    state_globals: Py<PyDict>,
    sites_globals: Bound<'_, PyDict>,
) -> PyResult<()> {
    let get = |k: &str| -> PyResult<Py<PyAny>> {
        sites_globals
            .get_item(k)?
            .map(|v| v.unbind())
            .ok_or_else(|| PyRuntimeError::new_err(format!("detpy._sites.{k} missing")))
    };
    let hub = Hub {
        state,
        state_globals,
        user: get("_USER")?,
        infra: get("_INFRA")?,
        sites_globals: sites_globals.clone().unbind(),
        norms: Mutex::new(HashMap::new()),
    };
    *lock(&HUB) = Some(Arc::new(hub));
    Ok(())
}

/// `_sites.refresh` cleared the classification cache: forget the tuples of the old one.
#[pyfunction]
pub fn l0_sites_cleared(_py: Python<'_>) {
    let hub = lock(&HUB).clone();
    if let Some(h) = hub {
        let old = std::mem::take(&mut *lock(&h.norms));
        drop(old); // decrefs while the GIL is held (`_py`)
    }
}

/// Set this thread's quiet flag; returns the previous one (`_state.quiet`).
#[pyfunction]
pub fn l0_set_busy(v: bool) -> bool {
    BUSY.with(|b| b.replace(v))
}

/// `_state.is_quiet()`.
#[pyfunction]
pub fn l0_is_busy() -> bool {
    BUSY.with(|b| b.get())
}

fn hub() -> PyResult<Arc<Hub>> {
    lock(&HUB).clone().ok_or_else(|| PyRuntimeError::new_err("detpy._state not configured"))
}

fn global<'py>(py: Python<'py>, d: &Py<PyDict>, k: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    d.bind(py)
        .get_item(k)?
        .ok_or_else(|| pyo3::exceptions::PyNameError::new_err(format!("name '{k}' is not defined")))
}

fn back<'py>(f: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyAny>>> {
    let b = f.getattr(intern!(f.py(), "f_back"))?;
    Ok(if b.is_none() { None } else { Some(b) })
}

/// `"{norm}:{f.f_lineno}"`.
fn site_of(f: &Bound<'_, PyAny>, norm: &str) -> PyResult<String> {
    let n = unsafe { ffi::PyFrame_GetLineNumber(f.as_ptr().cast()) };
    if n >= 0 {
        return Ok(format!("{norm}:{n}"));
    }
    let l = f.getattr(intern!(f.py(), "f_lineno"))?.str()?;
    Ok(format!("{norm}:{}", l.to_cow()?))
}

impl Hub {
    /// `_sites._classify(filename)` through `_sites._cache` (the same cache the Python callers use).
    fn classify(&self, py: Python<'_>, filename: &Bound<'_, PyAny>) -> PyResult<(Kind, Result<String, ()>)> {
        let g = self.sites_globals.bind(py);
        let cache = g.get_item(intern!(py, "_cache"))?;
        let mut hit = None;
        if let Some(c) = &cache {
            if let Ok(d) = c.cast::<PyDict>() {
                hit = d.get_item(filename)?;
            }
        }
        let tup = match hit {
            Some(t) => t,
            None => global(py, &self.sites_globals, intern!(py, "_classify"))?.call1((filename,))?,
        };
        let key = tup.as_ptr() as usize;
        if let Some((_, k, n)) = lock(&self.norms).get(&key) {
            return Ok((*k, n.clone()));
        }
        let t = tup.cast::<PyTuple>()?;
        let kind_o = t.get_item(0)?;
        let kind = if kind_o.is(self.user.bind(py)) || kind_o.eq(self.user.bind(py))? {
            Kind::User
        } else if kind_o.is(self.infra.bind(py)) || kind_o.eq(self.infra.bind(py))? {
            Kind::Infra
        } else {
            Kind::Stdlib
        };
        let norm_o = t.get_item(1)?;
        // a path that is not valid UTF-8 (surrogates) cannot be recorded: the error surfaces where the Python
        // path raised it (the recorder's string conversion), only if the site is used
        let norm = match norm_o.cast::<PyString>() {
            Ok(s) => s.to_cow().map(|c| c.into_owned()).map_err(|_| ()),
            Err(_) => Ok(norm_o.str()?.to_cow()?.into_owned()),
        };
        lock(&self.norms).insert(key, (tup.clone().unbind(), kind, norm.clone()));
        Ok((kind, norm))
    }

    /// `_sites.resolve`: site of the first user frame at or above `frame`; `None` for infrastructure;
    /// `"<unknown>"` when the stack is not deep enough.
    fn resolve(&self, py: Python<'_>, skip: usize) -> PyResult<Option<Result<String, PyErr>>> {
        let p = unsafe { ffi::PyEval_GetFrame() };
        if p.is_null() {
            return Ok(Some(Ok("<unknown>".to_string())));
        }
        let mut f = unsafe { Bound::from_borrowed_ptr(py, p.cast()) };
        for _ in 0..skip {
            match back(&f)? {
                Some(b) => f = b,
                None => return Ok(Some(Ok("<unknown>".to_string()))),
            }
        }
        let mut first: Option<Result<String, PyErr>> = None;
        loop {
            let code = f.getattr(intern!(py, "f_code"))?;
            let fname = code.getattr(intern!(py, "co_filename"))?;
            let (kind, norm) = self.classify(py, &fname)?;
            match kind {
                Kind::User => return Ok(Some(self.site(&f, norm))),
                Kind::Infra => return Ok(None),
                Kind::Stdlib => {
                    if first.is_none() {
                        first = Some(self.site(&f, norm));
                    }
                }
            }
            match back(&f)? {
                Some(b) => f = b,
                None => break,
            }
        }
        Ok(Some(first.unwrap_or_else(|| Ok("<unknown>".to_string()))))
    }

    fn site(&self, f: &Bound<'_, PyAny>, norm: Result<String, ()>) -> Result<String, PyErr> {
        match norm {
            Ok(n) => site_of(f, &n),
            Err(()) => Err(pyo3::exceptions::PyUnicodeEncodeError::new_err(
                "'utf-8' codec can't encode characters: surrogates not allowed",
            )),
        }
    }

    fn get<'py>(&self, py: Python<'py>, name: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
        self.state.bind(py).getattr(name)
    }
}

/// The value of an event, as Python passed it (`l0_record`) or as Rust made it (a clock read).
enum Text<'a, 'py> {
    Py(&'a Bound<'py, PyAny>),
    Rust(&'a str),
}

impl<'py> Text<'_, 'py> {
    fn obj(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self {
            Text::Py(o) => (*o).clone(),
            Text::Rust(s) => PyString::new(py, s).into_any(),
        }
    }

    fn string(&self) -> PyResult<String> {
        match self {
            Text::Py(o) => Ok(o.cast::<PyString>()?.to_cow()?.into_owned()),
            Text::Rust(s) => Ok((*s).to_string()),
        }
    }
}

/// `_state.record(source, op, value, depth)`; `skip` frames above the calling frame are skipped before the site
/// search (the Python stand-ins' own frames; 0 for a Rust stand-in, whose caller is the current frame).
fn record_impl(py: Python<'_>, source: Text<'_, '_>, op: Text<'_, '_>, value: Text<'_, '_>, skip: usize) -> PyResult<()> {
    let hub = hub()?;
    let is_time = match &source {
        Text::Rust(s) => *s == "time",
        Text::Py(o) => o.eq("time")?,
    };
    if !is_time {
        let other = global(py, &hub.state_globals, intern!(py, "_on_other_event"))?;
        if !other.is_none() {
            other.call0()?;
        }
    }
    let rec = hub.get(py, intern!(py, "recorder"))?;
    let listener = global(py, &hub.state_globals, intern!(py, "_event_listener"))?;
    let listening = !listener.is_none();
    if ((rec.is_none() || hub.get(py, intern!(py, "nodeid"))?.is_none()) && !listening) || l0_is_busy() {
        return Ok(());
    }
    let Some(site) = hub.resolve(py, skip)? else { return Ok(()) };
    if listening {
        let src = source.string()?;
        if memo_covers(py, &listener, &src) {
            MEMO_SKIPPED.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        } else {
            let r = listener.call1((source.obj(py), value.obj(py)))?;
            if r.is_truthy()? {
                memo_note(py, &listener, &src);
            }
        }
        if rec.is_none() || hub.get(py, intern!(py, "nodeid"))?.is_none() {
            return Ok(());
        }
    }
    let tid = unsafe { ffi::PyThread_get_thread_ident() };
    let tid = tid.into_pyobject(py)?;
    let threads = hub.get(py, intern!(py, "threads"))?;
    let t = match threads.cast::<PyDict>() {
        Ok(d) => match d.get_item(&tid)? {
            Some(t) => t,
            None => {
                let n = d.len().into_pyobject(py)?.into_any();
                d.set_item(&tid, &n)?;
                n
            }
        },
        Err(_) => {
            let t = threads.call_method1(intern!(py, "get"), (&tid,))?;
            if t.is_none() {
                let n = threads.len()?.into_pyobject(py)?.into_any();
                threads.set_item(&tid, &n)?;
                n
            } else {
                t
            }
        }
    };
    match rec.cast::<Recorder>() {
        Ok(r) => {
            let src = source.string()?;
            let thread: u32 = t.extract()?;
            let site = site?;
            r.get().push(Event {
                thread,
                source: Source::parse(&src),
                op: op.string()?,
                site,
                value: value.string()?,
            });
        }
        Err(_) => {
            let site = site?;
            rec.call_method1(intern!(py, "record"), (source.obj(py), op.obj(py), site, value.obj(py), t))?;
        }
    }
    Ok(())
}

fn record_from_rust(py: Python<'_>, source: &str, op: &str, value: String, skip: usize) -> PyResult<()> {
    record_impl(py, Text::Rust(source), Text::Rust(op), Text::Rust(&value), skip)
}

/// `_state.record(source, op, value, depth=1)`: record one event for the running test. `depth` is the number of
/// frames between the caller of this function and the frame that called the patched API (1 = the stand-in
/// called us directly).
#[pyfunction]
#[pyo3(signature = (source, op, value, depth = 1))]
pub fn l0_record(
    py: Python<'_>,
    source: &Bound<'_, PyAny>,
    op: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
    depth: usize,
) -> PyResult<()> {
    record_impl(py, Text::Py(source), Text::Py(op), Text::Py(value), depth)
}

/// `_sites.resolve(depth)`: site of the first user frame `depth` frames above the caller; None if infrastructure.
#[pyfunction]
pub fn l0_resolve(py: Python<'_>, depth: usize) -> PyResult<Option<String>> {
    match hub()?.resolve(py, depth)? {
        None => Ok(None),
        Some(s) => s.map(Some),
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("CLOCK_MAX_TICK_NS", MAX_TICK_NS as i64)?;
    for f in [
        wrap_pyfunction!(time, m)?,
        wrap_pyfunction!(time_ns, m)?,
        wrap_pyfunction!(monotonic, m)?,
        wrap_pyfunction!(monotonic_ns, m)?,
        wrap_pyfunction!(perf_counter, m)?,
        wrap_pyfunction!(perf_counter_ns, m)?,
        wrap_pyfunction!(clock_set_hooks, m)?,
        wrap_pyfunction!(clock_install, m)?,
        wrap_pyfunction!(clock_activate, m)?,
        wrap_pyfunction!(clock_installed, m)?,
        wrap_pyfunction!(clock_read, m)?,
        wrap_pyfunction!(clock_other_event, m)?,
        wrap_pyfunction!(clock_advance, m)?,
        wrap_pyfunction!(clock_start_test, m)?,
        wrap_pyfunction!(clock_wall_ns, m)?,
        wrap_pyfunction!(clock_rel, m)?,
        wrap_pyfunction!(clock_ns_to_secs, m)?,
        wrap_pyfunction!(clock_state, m)?,
        wrap_pyfunction!(l0_configure, m)?,
        wrap_pyfunction!(l0_sites_cleared, m)?,
        wrap_pyfunction!(l0_set_busy, m)?,
        wrap_pyfunction!(l0_is_busy, m)?,
        wrap_pyfunction!(l0_record, m)?,
        wrap_pyfunction!(l0_resolve, m)?,
        wrap_pyfunction!(l0_listener_memo, m)?,
        wrap_pyfunction!(l0_listener_reset, m)?,
        wrap_pyfunction!(l0_listener_skipped, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
