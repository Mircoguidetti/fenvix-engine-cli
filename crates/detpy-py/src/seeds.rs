//! Level 0 seeds in Rust: the recording stand-ins called on every random draw (`random.random`, `random.choice`,
//! ..., `random.randbytes`, `random.seed`, `random.Random.seed`, `os.urandom` / `random._urandom`,
//! `numpy.random.default_rng`) and the per-test counter of the seeds derived for unseeded generators.
//!
//! Port of `detpy/seeds.py` (`_wrap_numeric`, `_wrap_sequence`, `randbytes`, `_module_seed`, `_seed`, `_urandom`,
//! `_numpy_default_rng`, `_key`, `_counter`). A stand-in calls the real function, renders the value as the Python
//! wrapper did (`repr(value)`, `n=<len or -1>`, digests with `_core.digest`, seeds with `derive_seed` and the same keys)
//! and records it through the Rust event path of `_state.record` (`level0::record_impl`), with the caller of the
//! stand-in as the starting frame of the call-site search (no detpy frame to skip). The Python original is kept
//! verbatim in `tests/rust_hotpaths_ref/_ref_l0_seeds.py`; traces, stores and receipts are tested byte-identical
//! against it (`tests/test_level0_seeds_fsorder_rust.py`).

use crate::level0::{record_from_rust, record_from_rust_obj, state_attr};
use crate::standin::{bind, call_with, Kind, Target};
use detpy_core::fingerprint::digest_bytes;
use detpy_core::order;
use pyo3::exceptions::PyRuntimeError;
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyFloat, PyInt, PyString, PyTuple};
use std::sync::atomic::{AtomicU64, Ordering};

/// `seeds._counter["n"]`: seeds derived for unseeded generators so far in this test.
static COUNTER: AtomicU64 = AtomicU64::new(0);

/// `seeds._key(tag)`: `"<nodeid or <session>>\0<tag>\0<counter>"`.
fn key(py: Python<'_>, tag: &str) -> PyResult<String> {
    let nodeid = state_attr(py, intern!(py, "nodeid"))?;
    let n = COUNTER.load(Ordering::Relaxed);
    if nodeid.is_truthy()? {
        let id = nodeid.str()?;
        Ok(format!("{}\0{tag}\0{n}", id.to_cow()?))
    } else {
        Ok(format!("<session>\0{tag}\0{n}"))
    }
}

/// `_core.derive_seed(_state.STATE.config.seed, _key(tag))`, then `_counter["n"] += 1`.
fn derive_next(py: Python<'_>, tag: &str) -> PyResult<u64> {
    let base: u64 = state_attr(py, intern!(py, "config"))?.getattr(intern!(py, "seed"))?.extract()?;
    let s = order::derive_seed(base, &key(py, tag)?);
    COUNTER.fetch_add(1, Ordering::Relaxed);
    Ok(s)
}

fn digest_of(data: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(digest_bytes(data.cast::<PyBytes>()?.as_bytes()).short())
}

fn global<'py>(g: &Bound<'py, PyDict>, k: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    g.get_item(k)?.ok_or_else(|| PyRuntimeError::new_err(format!("detpy.seeds.{k} missing")))
}

/// `f"{x}"`.
fn format_empty<'py>(x: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let spec = PyString::new(x.py(), "");
    unsafe { Bound::from_owned_ptr_or_err(x.py(), ffi::PyObject_Format(x.as_ptr(), spec.as_ptr())) }
}

/// Whether the exact decimal expansion of `x` has at most 18 significant digits: only then can `x` lie exactly
/// halfway between two candidates of its shortest round-trip rendering, the one case where Rust's formatter (ties
/// away from zero) and CPython's `repr` (David Gay's dtoa, ties to even) pick different digits.
fn short_expansion(x: f64) -> bool {
    let bits = x.to_bits();
    let biased = ((bits >> 52) & 0x7ff) as i32;
    let frac = bits & ((1u64 << 52) - 1);
    let (mut m, mut e) = if biased == 0 { (frac, -1074) } else { (frac | (1u64 << 52), biased - 1075) };
    if m == 0 {
        return false; // zero: "0.0" / "-0.0", no tie
    }
    let tz = m.trailing_zeros();
    m >>= tz;
    e += tz as i32; // x = m * 2**e, m odd
    const LIMIT: u128 = 1_000_000_000_000_000_000; // 10**18
    if e < 0 {
        // x = m * 5**n / 10**n: significant digits = digits of m * 5**n (odd: no trailing zero)
        let n = (-e) as u32;
        n <= 26 && (m as u128).checked_mul(5u128.pow(n)).is_some_and(|v| v < LIMIT)
    } else {
        // x = N * 10**j with the largest j (5**j divides m, j <= e): significant digits = digits of N
        let (mut mm, mut j) = (m, 0i32);
        while mm % 5 == 0 && j < e {
            mm /= 5;
            j += 1;
        }
        let sh = (e - j) as u32;
        sh < 64 && ((mm as u128) << sh) < LIMIT
    }
}

/// `repr(x)` of a finite float whose expansion is long (`short_expansion` false), as CPython renders it
/// (`float_repr`: the shortest digits that round-trip, fixed notation for a decimal point position in (-4, 16],
/// `.0` added to integral values, a signed exponent of at least two digits otherwise). The digits are Rust's
/// shortest round-trip digits (`{:e}`), the closest of the shortest as in Gay's mode 0 (`test_float_repr_matches_python`).
fn float_repr_long(x: f64) -> String {
    let sci = format!("{x:e}"); // "-1.2345e-5", "1e16"
    let (mant, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let (neg, mant) = match mant.strip_prefix('-') {
        Some(m) => (true, m),
        None => (false, mant),
    };
    let ds: String = mant.chars().filter(|c| *c != '.').collect();
    let nd = ds.len() as i32;
    let decpt = exp + 1; // x = 0.<ds> * 10**decpt
    let mut out = String::with_capacity(ds.len() + 8);
    if neg {
        out.push('-');
    }
    if -4 < decpt && decpt <= 16 {
        if decpt <= 0 {
            out.push_str("0.");
            out.extend(std::iter::repeat_n('0', (-decpt) as usize));
            out.push_str(&ds);
        } else if decpt >= nd {
            out.push_str(&ds);
            out.extend(std::iter::repeat_n('0', (decpt - nd) as usize));
            out.push_str(".0");
        } else {
            out.push_str(&ds[..decpt as usize]);
            out.push('.');
            out.push_str(&ds[decpt as usize..]);
        }
    } else {
        out.push_str(&ds[..1]);
        if nd > 1 {
            out.push('.');
            out.push_str(&ds[1..]);
        }
        let e = decpt - 1;
        out.push('e');
        out.push(if e < 0 { '-' } else { '+' });
        let a = e.unsigned_abs();
        if a < 10 {
            out.push('0');
        }
        out.push_str(&a.to_string());
    }
    out
}

/// `repr(x)` of a float when Rust renders it exactly as CPython does (finite, long expansion); None otherwise.
fn float_repr(x: f64) -> Option<String> {
    if !x.is_finite() || x == 0.0 || short_expansion(x) {
        return None;
    }
    Some(float_repr_long(x))
}

/// `repr(value)`: computed here for an exact `float` with a long expansion (a draw from a continuous distribution:
/// CPython's dtoa needs ~300 ns for its 17 digits) or an exact `int` that fits 64 bits, else by the interpreter.
fn value_repr<'py>(value: &Bound<'py, PyAny>) -> PyResult<Result<String, Bound<'py, PyAny>>> {
    if value.is_exact_instance_of::<PyFloat>() {
        if let Some(s) = float_repr(value.cast::<PyFloat>()?.value()) {
            return Ok(Ok(s));
        }
    } else if value.is_exact_instance_of::<PyInt>() {
        if let Ok(i) = value.extract::<i64>() {
            return Ok(Ok(i.to_string()));
        }
    }
    Ok(Err(value.repr()?.into_any()))
}

/// `repr(x)` of a float as the numeric stand-ins render it (for the tests).
#[pyfunction]
pub fn seeds_float_repr(py: Python<'_>, x: f64) -> PyResult<String> {
    match float_repr(x) {
        Some(s) => Ok(s),
        None => Ok(PyFloat::new(py, x).repr()?.to_cow()?.into_owned()),
    }
}

/// Whether `seeds_float_repr(x)` is computed in Rust (for the tests).
#[pyfunction]
pub fn seeds_float_repr_is_rust(x: f64) -> bool {
    float_repr(x).is_some()
}

pub(crate) fn call<'py>(
    py: Python<'py>,
    t: &Target,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    match t.kind {
        Kind::Numeric => {
            let value = call_with(t.real.bind(py), args, kwargs)?;
            match value_repr(&value)? {
                Ok(text) => record_from_rust(py, "random", &t.op, text, 0)?,
                Err(text) => record_from_rust_obj(py, "random", &t.op, &text, 0)?,
            }
            Ok(value)
        }
        Kind::Sequence => {
            let value = call_with(t.real.bind(py), args, kwargs)?;
            let n: i64 = match args.iter().next() {
                Some(a) if a.hasattr(intern!(py, "__len__"))? => a.len()? as i64,
                _ => -1,
            };
            record_from_rust(py, "random", &t.op, format!("n={n}"), 0)?;
            Ok(value)
        }
        Kind::RandBytes => {
            let data = call_with(t.real.bind(py), args, kwargs)?;
            record_from_rust(py, "random", &t.op, digest_of(&data)?, 0)?;
            Ok(data)
        }
        Kind::ModuleSeed => {
            let [a, version] = bind(&t.fname, ["a", "version"], 0, args, kwargs)?;
            let a = match a {
                Some(a) if !a.is_none() => a,
                _ => derive_next(py, "random.seed")?.into_pyobject(py)?.into_any(),
            };
            let text = if a.is_instance_of::<PyInt>() || a.is_instance_of::<PyString>() {
                a.repr()?.into_any()
            } else {
                a.get_type().getattr(intern!(py, "__name__"))?
            };
            record_from_rust_obj(py, "random", &t.op, &text, 0)?;
            let version = match version {
                Some(v) => v,
                None => 2i64.into_pyobject(py)?.into_any(),
            };
            t.real.bind(py).call1((a, version))
        }
        Kind::RandomSeed => {
            let [slf, a, version] = bind(&t.fname, ["self", "a", "version"], 1, args, kwargs)?;
            let slf = slf.expect("bound: required");
            let g = t.real.bind(py).cast::<PyDict>()?;
            let a = match a {
                Some(a) if !a.is_none() => a,
                a => {
                    let sysrandom = global(g, intern!(py, "random"))?.getattr(intern!(py, "SystemRandom"))?;
                    if slf.is_instance(&sysrandom)? {
                        a.unwrap_or_else(|| py.None().into_bound(py))
                    } else {
                        let s = derive_next(py, "Random")?;
                        record_from_rust(py, "random", &t.op, s.to_string(), 0)?;
                        s.into_pyobject(py)?.into_any()
                    }
                }
            };
            let version = match version {
                Some(v) => v,
                None => 2i64.into_pyobject(py)?.into_any(),
            };
            global(g, intern!(py, "_real_seed"))?.call1((slf, a, version))
        }
        Kind::Urandom => {
            let [n] = bind(&t.fname, ["n"], 1, args, kwargs)?;
            let n = n.expect("bound: required");
            let g = t.real.bind(py).cast::<PyDict>()?;
            let rng = global(g, intern!(py, "_urandom_rng"))?;
            let data = if rng.is_none() {
                global(g, intern!(py, "_real_urandom"))?.call1((&n,))?
            } else {
                rng.call_method1(intern!(py, "randbytes"), (&n,))?
            };
            let shown = format_empty(&n)?;
            let text = format!("{}:{}", shown.cast::<PyString>()?.to_cow()?, digest_of(&data)?);
            record_from_rust(py, "entropy", &t.op, text, 0)?;
            Ok(data)
        }
        Kind::DefaultRng => {
            let [seed] = bind(&t.fname, ["seed"], 0, args, kwargs)?;
            let seed = match seed {
                Some(s) if !s.is_none() => s,
                _ => {
                    let s = derive_next(py, "default_rng")?;
                    record_from_rust(py, "random", &t.op, s.to_string(), 0)?;
                    s.into_pyobject(py)?.into_any()
                }
            };
            t.real.bind(py).call1((seed,))
        }
    }
}

/// The start of a test (`seeds.start_test`): `_counter["n"] = 0`.
#[pyfunction]
pub fn seeds_reset_counter() {
    COUNTER.store(0, Ordering::Relaxed);
}

/// `_counter["n"]` (for the tests).
#[pyfunction]
pub fn seeds_counter() -> u64 {
    COUNTER.load(Ordering::Relaxed)
}

/// `seeds._key(tag)` (for the tests).
#[pyfunction]
pub fn seeds_key(py: Python<'_>, tag: &str) -> PyResult<String> {
    key(py, tag)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(seeds_reset_counter, m)?)?;
    m.add_function(wrap_pyfunction!(seeds_counter, m)?)?;
    m.add_function(wrap_pyfunction!(seeds_key, m)?)?;
    m.add_function(wrap_pyfunction!(seeds_float_repr, m)?)?;
    m.add_function(wrap_pyfunction!(seeds_float_repr_is_rust, m)?)?;
    Ok(())
}
