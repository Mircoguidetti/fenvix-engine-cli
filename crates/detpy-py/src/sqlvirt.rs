//! SQLite's clock and randomness under Level 0 (parallel-proof round 3, item 3).
//!
//! SQLite evaluates `'now'` (`date('now')`, `datetime()`, `strftime('%s')`, `CURRENT_TIMESTAMP`, a column default
//! such as `DEFAULT CURRENT_TIMESTAMP`) on the real clock in C, and `random()` / `randomblob(N)` on its own PRNG,
//! seeded from the OS once per process. Neither goes through Python, so Level 0's virtual clock and seeded streams
//! never saw them: a test whose rows carry such values was not reproducible, and the cache with proof refused every
//! test that touched such a schema (`rclock`, prefect: 2,418 tests).
//!
//! Every connection made through `sqlite3.connect` under Level 0 gets, per connection, application-defined functions
//! that override the built-ins of the same name (`sqlite3_create_function`: an application function replaces the
//! built-in for that connection, column defaults and triggers included, since they are compiled into the statement
//! on that connection):
//!
//! * `date`, `time`, `datetime`, `julianday`, `unixepoch`, `strftime`, `timediff` (any number of arguments) and
//!   `current_date`, `current_time`, `current_timestamp` (no argument: the keywords are calls of these names). A
//!   time-value argument `'now'` (any case, as SQLite compares it), or a missing one, becomes the virtual wall
//!   clock at millisecond precision (SQLite's own precision) in UTC, `YYYY-MM-DD HH:MM:SS.SSS`; the call is then
//!   evaluated by the real built-in on a private in-memory helper connection, so every modifier, format and error
//!   keeps SQLite's exact semantics. As in SQLite, every `'now'` of one statement is the same instant: the clock is
//!   read once per statement (the connection's trace callback starts a statement).
//! * `random()` and `randomblob(N)`: drawn from a SplitMix64 stream seeded per test
//!   (`derive_seed(seed, nodeid + "\0sqlite")`, reset at the start of every test), so a test draws the same values
//!   wherever it runs (serially, in any worker).
//!
//! Each clock read is a Level 0 event `("time", "sqlite.<function>", rel)` at the caller's site (the cache with proof
//! then treats it like any other virtual clock read: the epoch is an input), each draw a `("random", "sqlite.random"
//! | "sqlite.randomblob", value digest)` event. The Python glue (`detpy/sqlvirt.py`) only patches `sqlite3.connect`.

use crate::level0::{clock_is_installed, clock_read_rel, record_from_rust, wall_ns};
use crate::lock;
use detpy_core::fingerprint::digest_bytes;
use detpy_core::order::SplitMix64;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyModule, PyString, PyTuple};
use std::sync::Mutex;

/// The private helper connection (the real built-ins), set by `sqlvirt_configure`.
static HELPER: Mutex<Option<Py<PyAny>>> = Mutex::new(None);
/// The per-test stream of `random()` / `randomblob()`.
static STREAM: Mutex<Option<SplitMix64>> = Mutex::new(None);

/// Date and time functions overridden on every connection.
const DATE_FUNCS: [&str; 7] = ["date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff"];
const NOW_FUNCS: [(&str, &str); 3] = [("current_date", "date"), ("current_time", "time"), ("current_timestamp", "datetime")];

/// `_core.sqlvirt_configure(helper)`: the helper connection whose built-ins evaluate the calls.
#[pyfunction]
fn sqlvirt_configure(helper: Option<Py<PyAny>>) {
    let old = std::mem::replace(&mut *lock(&HELPER), helper);
    drop(old);
}

/// `_core.sqlvirt_start_test(seed)`: the seed of this test's `random()` / `randomblob()` stream.
#[pyfunction]
fn sqlvirt_start_test(seed: u64) {
    *lock(&STREAM) = Some(SplitMix64::new(seed));
}

fn draw() -> u64 {
    let mut g = lock(&STREAM);
    g.get_or_insert_with(|| SplitMix64::new(0)).next_u64()
}

/// UTC civil date of a day count since 1970-01-01 (H. Hinnant's algorithm).
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `YYYY-MM-DD HH:MM:SS.SSS` (UTC) of a wall clock in ns since the Unix epoch, truncated to ms as SQLite's 'now'.
pub(crate) fn sqlite_now_text(wall_ns: i128) -> String {
    let ms = wall_ns.div_euclid(1_000_000) as i64;
    let secs = ms.div_euclid(1000);
    let (days, sod) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
    let (y, m, d) = civil(days);
    format!(
        "{y:04}-{m:02}-{d:02} {:02}:{:02}:{:02}.{:03}",
        sod / 3600,
        (sod % 3600) / 60,
        sod % 60,
        ms.rem_euclid(1000)
    )
}

/// One connection's virtualisation: the instant of the running statement, and the trace callback detpy's cache (or
/// nothing) set behind it.
#[pyclass(module = "detpy._core", frozen)]
pub struct SqlVirt {
    now: Mutex<Option<String>>,
    inner: Mutex<Option<Py<PyAny>>>,
}

impl SqlVirt {
    /// The virtual 'now' of the running statement, read from the clock at its first use (recorded at the caller).
    fn now(&self, py: Python<'_>, func: &str) -> PyResult<String> {
        if let Some(n) = lock(&self.now).as_ref() {
            return Ok(n.clone());
        }
        let wall = if clock_is_installed() {
            let (e, rel) = clock_read_rel();
            record_from_rust(py, "time", &format!("sqlite.{func}"), rel.to_string(), 0)?;
            wall_ns(py, e)?
        } else {
            // Level 0 uninstalled after the connection was made: the real clock, as SQLite would
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as i128).unwrap_or(0)
        };
        let n = sqlite_now_text(wall);
        *lock(&self.now) = Some(n.clone());
        Ok(n)
    }
}

#[pymethods]
impl SqlVirt {
    #[new]
    fn new() -> Self {
        SqlVirt { now: Mutex::new(None), inner: Mutex::new(None) }
    }

    /// Register the functions on `conn` and become its trace callback.
    fn install(slf: &Bound<'_, Self>, conn: &Bound<'_, PyAny>) -> PyResult<()> {
        let py = slf.py();
        let kw = PyDict::new(py);
        kw.set_item("deterministic", false)?;
        let me: Py<SqlVirt> = slf.clone().unbind();
        for name in DATE_FUNCS {
            let f = SqlFn { virt: me.clone_ref(py), name, kind: FnKind::Date };
            conn.call_method("create_function", (name, -1, f), Some(&kw))?;
        }
        for (name, base) in NOW_FUNCS {
            let f = SqlFn { virt: me.clone_ref(py), name: base, kind: FnKind::Now };
            conn.call_method("create_function", (name, 0, f), Some(&kw))?;
        }
        conn.call_method("create_function", ("random", 0, SqlFn { virt: me.clone_ref(py), name: "random", kind: FnKind::Random }), Some(&kw))?;
        conn.call_method("create_function", ("randomblob", 1, SqlFn { virt: me.clone_ref(py), name: "randomblob", kind: FnKind::Blob }), Some(&kw))?;
        conn.call_method1("set_trace_callback", (slf,))?;
        Ok(())
    }

    /// The trace callback set behind this one (the cache's `SqlTrace`), or None.
    fn set_inner(&self, t: Option<Py<PyAny>>) {
        let old = std::mem::replace(&mut *lock(&self.inner), t);
        drop(old);
    }

    /// A statement starts: the next 'now' reads the clock again; the inner trace sees the statement.
    fn __call__(&self, py: Python<'_>, statement: &Bound<'_, PyAny>) -> PyResult<()> {
        *lock(&self.now) = None;
        let inner = lock(&self.inner).as_ref().map(|t| t.clone_ref(py));
        if let Some(t) = inner {
            t.call1(py, (statement,))?;
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
enum FnKind {
    Date,
    Now,
    Random,
    Blob,
}

/// One overriding function of one connection.
#[pyclass(module = "detpy._core", frozen)]
struct SqlFn {
    virt: Py<SqlVirt>,
    name: &'static str,
    kind: FnKind,
}

fn is_now(a: &Bound<'_, PyAny>) -> bool {
    a.is_instance_of::<PyString>() && a.extract::<String>().is_ok_and(|t| t.eq_ignore_ascii_case("now"))
}

/// Evaluate `name(args...)` with the real built-in on the helper connection.
fn builtin<'py>(py: Python<'py>, name: &str, args: Vec<Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyAny>> {
    let helper = lock(&HELPER)
        .as_ref()
        .map(|h| h.clone_ref(py))
        .ok_or_else(|| PyRuntimeError::new_err("detpy sqlvirt: no helper connection"))?;
    let marks = vec!["?"; args.len()].join(", ");
    let cur = helper.bind(py).call_method1("execute", (format!("select {name}({marks})"), PyTuple::new(py, args)?))?;
    cur.call_method0("fetchone")?.get_item(0)
}

#[pymethods]
impl SqlFn {
    #[pyo3(signature = (*args))]
    fn __call__<'py>(&self, py: Python<'py>, args: &Bound<'py, PyTuple>) -> PyResult<Bound<'py, PyAny>> {
        let v = self.virt.get();
        match self.kind {
            FnKind::Random => {
                let x = draw() as i64;
                record_from_rust(py, "random", "sqlite.random", x.to_string(), 0)?;
                Ok(x.into_pyobject(py)?.into_any())
            }
            FnKind::Blob => {
                // SQLite: N < 1 gives one byte
                let n: i64 = args.get_item(0).ok().and_then(|a| a.extract::<f64>().ok()).map(|f| f as i64).unwrap_or(1);
                let n = n.max(1) as usize;
                let mut out = Vec::with_capacity(n + 8);
                while out.len() < n {
                    out.extend_from_slice(&draw().to_le_bytes());
                }
                out.truncate(n);
                record_from_rust(py, "random", "sqlite.randomblob", digest_bytes(&out).short(), 0)?;
                Ok(PyBytes::new(py, &out).into_any())
            }
            FnKind::Now => {
                let now = v.now(py, self.name)?;
                builtin(py, self.name, vec![PyString::new(py, &now).into_any()])
            }
            FnKind::Date => {
                let mut a: Vec<Bound<'py, PyAny>> = args.iter().collect();
                // the time-value positions: strftime(format, time, ...), timediff(a, b), the others (time, ...); a
                // missing time value is 'now' (date(), strftime(format)); timediff and strftime() need theirs
                let (slots, missing_is_now): (&[usize], bool) = match self.name {
                    "strftime" => (&[1], a.len() == 1),
                    "timediff" => (&[0, 1], false),
                    _ => (&[0], a.is_empty()),
                };
                if missing_is_now {
                    let now = v.now(py, self.name)?;
                    a.push(PyString::new(py, &now).into_any());
                } else {
                    for &i in slots {
                        if i < a.len() && is_now(&a[i]) {
                            let now = v.now(py, self.name)?;
                            a[i] = PyString::new(py, &now).into_any();
                        }
                    }
                }
                builtin(py, self.name, a)
            }
        }
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SqlVirt>()?;
    m.add_function(wrap_pyfunction!(sqlvirt_configure, m)?)?;
    m.add_function(wrap_pyfunction!(sqlvirt_start_test, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn now_text_matches_sqlite_format() {
        assert_eq!(sqlite_now_text(0), "1970-01-01 00:00:00.000");
        // 2026-11-19 12:34:56.789 UTC
        let ns: i128 = 1_795_091_696_789_000_000 + 123_456; // 1795091696 = 2026-11-19 12:34:56 UTC
        assert_eq!(sqlite_now_text(ns), "2026-11-19 12:34:56.789");
        assert_eq!(sqlite_now_text(951_782_400_000_000_000), "2000-02-29 00:00:00.000");
        assert_eq!(sqlite_now_text(-1_000_000), "1969-12-31 23:59:59.999");
    }
}
