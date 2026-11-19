//! The session side of the cache with proof (`detpy._core.CacheSession`): what `ProofCachePlugin` kept in Python
//! dicts and computed from them (round 2 of rust-hotpaths). The plugin's pytest hooks stay Python and hand their
//! objects over: the reuse decisions of the collected tests (`hits`, `verifying`, `misses`, the verification draw),
//! the per-test reports (`pytest_runtest_logreport`), the tests that ran, their durations, fixtures and
//! fingerprints, the final outcome of a test (`_final`), the comparison of verified results, the record plan (built
//! here as a `detpy_core::record::Plan` and recorded without the JSON round trip), the reasons a test was not cached
//! and where (`_where`, `_ctx_label`), the summary dict, the cache's part of the outcomes file and the lines of the
//! terminal summary.
//!
//! The Python original is `tests/rust_hotpaths_ref/_ref_proofcache.py` (`ProofCachePlugin`); the whole-session
//! equivalence tests (`tests/test_capture_rust.py`) compare stores, receipts, outcomes files and summaries.

use crate::capture::CaptureCore;
use crate::proofcache::ProofCache;
use detpy_core::record::{Plan, TestRun};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple};
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::sync::{Mutex, MutexGuard};
use std::time::Instant;

type W = Vec<u8>;

/// SplitMix64: a uniform float in [0, 1) from the state (advanced).
fn splitmix_unit(state: &mut u64) -> f64 {
    *state = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^= z >> 31;
    (z >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// The lossless bytes of a Python `str` (UTF-8, surrogates as `surrogatepass`).
fn w_of(s: &Bound<'_, PyString>) -> PyResult<W> {
    match s.to_cow() {
        Ok(t) => Ok(t.as_bytes().to_vec()),
        Err(_) => {
            let py = s.py();
            let b = s.call_method1(intern!(py, "encode"), ("utf-8", "surrogatepass"))?;
            Ok(b.cast::<PyBytes>()?.as_bytes().to_vec())
        }
    }
}

fn w_any(o: &Bound<'_, PyAny>) -> PyResult<W> {
    w_of(o.cast::<PyString>()?)
}

/// The Python `str` of `w`.
fn py_of<'py>(py: Python<'py>, w: &[u8]) -> PyResult<Bound<'py, PyAny>> {
    match std::str::from_utf8(w) {
        Ok(s) => Ok(PyString::new(py, s).into_any()),
        Err(_) => PyBytes::new(py, w).call_method1(intern!(py, "decode"), ("utf-8", "surrogatepass")),
    }
}

/// A plan string: a `str` with a surrogate made `json.dumps` escape it and the plan's parser refuse it.
fn utf8(w: &[u8]) -> PyResult<String> {
    String::from_utf8(w.to_vec()).map_err(|_| PyValueError::new_err("plan: lone surrogate in a session string"))
}

/// An insertion-ordered map (a Python dict's iteration order; assigning an existing key keeps its place).
struct OMap<V> {
    keys: Vec<W>,
    vals: Vec<V>,
    ix: HashMap<W, usize>,
}

impl<V> Default for OMap<V> {
    fn default() -> Self {
        OMap { keys: Vec::new(), vals: Vec::new(), ix: HashMap::new() }
    }
}

impl<V> OMap<V> {
    fn insert(&mut self, k: W, v: V) {
        match self.ix.get(&k) {
            Some(&i) => self.vals[i] = v,
            None => {
                self.ix.insert(k.clone(), self.keys.len());
                self.keys.push(k);
                self.vals.push(v);
            }
        }
    }
    fn get(&self, k: &[u8]) -> Option<&V> {
        self.ix.get(k).map(|&i| &self.vals[i])
    }
    fn get_mut_or_default(&mut self, k: &[u8]) -> &mut V
    where
        V: Default,
    {
        let i = match self.ix.get(k) {
            Some(&i) => i,
            None => {
                self.insert(k.to_vec(), V::default());
                self.keys.len() - 1
            }
        };
        &mut self.vals[i]
    }
    /// Remove `k` keeping the order of the others (rare: a withdrawn reuse).
    fn remove(&mut self, k: &[u8]) -> Option<V> {
        let i = self.ix.remove(k)?;
        self.keys.remove(i);
        let v = self.vals.remove(i);
        for j in self.ix.values_mut() {
            if *j > i {
                *j -= 1;
            }
        }
        Some(v)
    }
    fn contains(&self, k: &[u8]) -> bool {
        self.ix.contains_key(k)
    }
    fn len(&self) -> usize {
        self.keys.len()
    }
    fn iter(&self) -> impl Iterator<Item = (&W, &V)> {
        self.keys.iter().zip(self.vals.iter())
    }
}

/// One phase report of a test (`{"outcome", "wasxfail"?, "longrepr"?}`), or why `json.dumps` would refuse it.
type Part = Result<Value, String>;

#[derive(Default)]
struct State {
    run_id: W,
    config: W,
    runtime: W,
    epoch: i64,
    receipts_path: W,
    /// nodeid -> receipt dict (reused), in decision order.
    hits: OMap<Py<PyAny>>,
    /// nodeid -> receipt dict of a reusable result re-run for verification.
    verifying: OMap<Py<PyAny>>,
    /// nodeid -> "kind: detail".
    misses: OMap<W>,
    test_index: HashMap<W, i64>,
    fixture_ctx: HashMap<W, Vec<W>>,
    ran: Vec<W>,
    /// nodeid -> {when: part}.
    parts: OMap<OMap<Part>>,
    dur: HashMap<W, f64>,
    fingerprints: HashMap<W, Py<PyAny>>,
    verify_results: Vec<Py<PyDict>>,
    recorded: i64,
    not_cached: OMap<W>,
    not_cached_where: OMap<W>,
    stale_hits: OMap<W>,
    error: Option<W>,
    phases: OMap<f64>,
    t_check: f64,
    t_record: f64,
    /// Paths this session's code created exclusively after finding them missing, with their writers then
    /// (review R-009b R2).
    excl_seeded: Vec<(W, Py<PyAny>)>,
}

/// `json.dumps`-able value of a report attribute (`Err`: what `json.dumps` raises for it).
fn to_value(o: &Bound<'_, PyAny>) -> Result<Value, String> {
    if o.is_none() {
        return Ok(Value::Null);
    }
    if let Ok(b) = o.cast::<pyo3::types::PyBool>() {
        return Ok(Value::Bool(b.is_true()));
    }
    if let Ok(s) = o.cast::<PyString>() {
        return match s.to_cow() {
            Ok(t) => Ok(Value::String(t.into_owned())),
            Err(_) => Err("plan: lone surrogate in a report".into()),
        };
    }
    if o.cast::<pyo3::types::PyInt>().is_ok() {
        if let Ok(i) = o.extract::<i64>() {
            return Ok(Value::from(i));
        }
        if let Ok(u) = o.extract::<u64>() {
            return Ok(Value::from(u));
        }
        return Err("plan: integer out of range in a report".into());
    }
    if let Ok(f) = o.cast::<pyo3::types::PyFloat>() {
        return serde_json::Number::from_f64(f.value()).map(Value::Number).ok_or_else(|| "plan: non-finite float in a report".into());
    }
    if let Ok(l) = o.cast::<PyList>() {
        return l.iter().map(|x| to_value(&x)).collect::<Result<Vec<_>, _>>().map(Value::Array);
    }
    if let Ok(t) = o.cast::<PyTuple>() {
        return t.iter().map(|x| to_value(&x)).collect::<Result<Vec<_>, _>>().map(Value::Array);
    }
    let name = o.get_type().name().map(|n| n.to_string()).unwrap_or_else(|_| "?".into());
    Err(format!("TypeError: Object of type {name} is not JSON serializable"))
}

/// The final outcome of a test from its phase reports (`proofcache._final`).
fn final_outcome(parts: Option<&OMap<Part>>) -> String {
    let get = |w: &str| -> Option<&Map<String, Value>> {
        parts.and_then(|p| p.get(w.as_bytes())).and_then(|r| r.as_ref().ok()).and_then(|v| v.as_object())
    };
    let outcome = |m: &Map<String, Value>| m.get("outcome").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if let Some(setup) = get("setup") {
        let so = outcome(setup);
        if !so.is_empty() && so != "passed" {
            if so == "skipped" {
                return if setup.contains_key("wasxfail") { "xfailed" } else { "skipped" }.into();
            }
            return "error".into();
        }
    }
    let Some(call) = get("call") else { return "unknown".into() };
    let co = outcome(call);
    if let Some(td) = get("teardown") {
        if outcome(td) == "failed" {
            return "error".into();
        }
    }
    if co == "skipped" && call.contains_key("wasxfail") {
        return "xfailed".into();
    }
    if co == "passed" && call.contains_key("wasxfail") {
        return "xpassed".into();
    }
    co
}

/// The kind of a not-cached reason that names its cause in a capture flag (`proofcache._FLAG_OF`).
fn flag_of(why: &[u8]) -> Option<&'static str> {
    Some(match why {
        b"real clock read outside the virtual clock" => "rclock",
        b"subprocess" => "spawn",
        b"network connection" => "connect",
        b"host name lookup" => "dns",
        b"network socket opened outside Python (C extension)" => "csock",
        b"reads /proc, /sys or /dev" => "proc",
        b"native code from the repository" => "native",
        _ => return None,
    })
}

/// A context's name as the reports show it (`proofcache._ctx_label`).
fn ctx_label(name: &[u8]) -> W {
    match name {
        b"" => return b"startup".to_vec(),
        b"s" => return b"between tests".to_vec(),
        b"i" => return b"import time".to_vec(),
        _ => {}
    }
    let (kind, rest) = match name.iter().position(|&c| c == b'|') {
        Some(i) => (&name[..i], &name[i + 1..]),
        None => (name, &b""[..]),
    };
    let cat = |a: &[u8], b: &[u8]| [a, b].concat();
    match kind {
        b"i" => cat(b"import of ", rest),
        b"c" => cat(b"collection of ", rest),
        b"f" => cat(b"fixture ", rest.rsplit(|&c| c == b'|').next().unwrap_or(rest)),
        _ => b"test".to_vec(),
    }
}

/// `str.split(sep, 1)[0]`.
fn head(s: &[u8], sep: u8) -> &[u8] {
    match s.iter().position(|&c| c == sep) {
        Some(i) => &s[..i],
        None => s,
    }
}

/// `nodeid.split("::", 1)[0]`.
fn ctx_file(nid: &[u8]) -> &[u8] {
    match nid.windows(2).position(|w| w == b"::") {
        Some(i) => &nid[..i],
        None => nid,
    }
}

#[pyclass(module = "detpy._core", frozen)]
pub struct CacheSession {
    st: Mutex<State>,
}

#[pymethods]
impl CacheSession {
    #[new]
    fn new(run_id: Bound<'_, PyString>, receipts_path: Bound<'_, PyString>) -> PyResult<Self> {
        let st = State { run_id: w_of(&run_id)?, receipts_path: w_of(&receipts_path)?, ..Default::default() };
        Ok(CacheSession { st: Mutex::new(st) })
    }

    /// The session's configuration and runtime digests and epoch (`ProofCachePlugin.configure`).
    fn configure(&self, config: Bound<'_, PyString>, runtime: Bound<'_, PyString>, epoch: i64) -> PyResult<()> {
        let mut st = lock(&self.st);
        st.config = w_of(&config)?;
        st.runtime = w_of(&runtime)?;
        st.epoch = epoch;
        Ok(())
    }

    // -- decisions --------------------------------------------------------------------------------------------------
    /// review R-009b R2: a path this session's code (import time, collection) created with an exclusive create that
    /// found it missing: the recorded "missing" is compared with what that code saw (`ProofCache.observed`), not with
    /// the file it then created; the path and its writers are kept for the plan's `stale_skip`.
    fn seed_exclusive(&self, store: &Bound<'_, ProofCache>, cap: &Bound<'_, CaptureCore>) -> PyResult<()> {
        let py = cap.py();
        let writers = cap.getattr(intern!(py, "writers"))?.cast_into::<PyDict>()?;
        let excl = cap.getattr(intern!(py, "excl_pre"))?.cast_into::<PyDict>()?;
        let mut seeded = Vec::new();
        for (p, present) in excl.iter() {
            if present.is_truthy()? {
                continue;
            }
            let Some(w) = writers.get_item(&p)? else { continue };
            let key: String = cap.call_method1(intern!(py, "_key"), (&p,))?.extract()?;
            store.get().observed(&key, "missing");
            let set = py.import("builtins")?.getattr("set")?.call1((w,))?;
            seeded.push((w_any(&p)?, set.unbind()));
        }
        lock(&self.st).excl_seeded = seeded;
        Ok(())
    }

    /// The decision of every collected test (`ProofCachePlugin._decide`'s loop): `ProofCache.check_all`, then a
    /// reusable result is re-run for verification when `rng_random() < verify` (the draw made only for reusable
    /// results, in collection order, as before).
    #[pyo3(signature = (store, nodeids, max_age_s, now, run_time, verify, rng_random))]
    #[allow(clippy::too_many_arguments)]
    fn decide(
        &self,
        py: Python<'_>,
        store: &Bound<'_, ProofCache>,
        nodeids: Vec<Bound<'_, PyString>>,
        max_age_s: Option<f64>,
        now: f64,
        run_time: Bound<'_, PyAny>,
        verify: Option<f64>,
        rng_random: Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let nids: Vec<String> = nodeids.iter().map(|n| n.extract()).collect::<PyResult<_>>()?;
        let decided = store.get().check_all(py, nids, max_age_s, now, run_time)?;
        let verify = verify.unwrap_or(0.0);
        // the draw: a Python callable (serial sessions: Mersenne Twister seeded per run), or an integer seed (the
        // controller of a parallel session: SplitMix64 from `derive_seed`, review R-023 R4)
        let mut rust_rng: Option<u64> = rng_random.extract::<u64>().ok();
        let mut st = lock(&self.st);
        for (i, (nid, d)) in nodeids.iter().zip(decided.iter()).enumerate() {
            let w = w_of(nid)?;
            st.test_index.insert(w.clone(), i as i64);
            let d = d.cast_into::<PyTuple>()?;
            let ok: bool = d.get_item(0)?.extract()?;
            let info = d.get_item(1)?;
            if ok {
                let draw = verify != 0.0 && {
                    let x: f64 = match rust_rng.as_mut() {
                        Some(state) => splitmix_unit(state),
                        None => rng_random.call0()?.extract()?,
                    };
                    x < verify
                };
                if draw {
                    st.verifying.insert(w, info.unbind());
                } else {
                    st.hits.insert(w, info.unbind());
                }
            } else {
                st.misses.insert(w, w_any(&info)?);
            }
        }
        Ok(())
    }

    /// The seed of the verification draw of a parallel session's controller: `derive_seed(seed,
    /// "detpy-cache-verify:<order digest>:<configuration digest>")`, so two runs on the same inputs verify the same
    /// tests (docs/PARALLEL-PROOF-DESIGN.md 2.5; review R-023 R4).
    #[staticmethod]
    fn controller_verify_seed(seed: u64, nodeids: Vec<String>, config: &str) -> u64 {
        let od = detpy_core::trace::order_digest(&nodeids);
        detpy_core::order::derive_seed(seed, &format!("detpy-cache-verify:{od}:{config}"))
    }

    /// A decided reuse is withdrawn: the test runs (and is recorded) instead; `reason` goes to its receipt.
    fn demote(&self, nodeid: Bound<'_, PyString>, reason: Bound<'_, PyString>) -> PyResult<bool> {
        let w = w_of(&nodeid)?;
        let mut st = lock(&self.st);
        if st.hits.get(&w).is_none() {
            return Ok(false);
        }
        st.hits.remove(&w);
        st.misses.insert(w, w_of(&reason)?);
        Ok(true)
    }

    /// Serial session, at the test's turn: a reused result whose input code of this session already wrote (another
    /// test, which ran before it, or a fixture it did not use when it was recorded) is withdrawn and the test runs
    /// (review R-023 F2: the decision was made before that writer ran; a fresh serial session gives the test the
    /// written file). Returns the reason when withdrawn.
    fn recheck_hit(&self, store: &Bound<'_, ProofCache>, cap: &Bound<'_, CaptureCore>, nodeid: Bound<'_, PyString>) -> PyResult<Option<String>> {
        let nid: String = nodeid.extract()?;
        if !lock(&self.st).hits.contains(nid.as_bytes()) {
            return Ok(None);
        }
        let Some(found) = store.get().with_entry(&nid, |e| {
            let data: Vec<(String, String)> = e.data.iter().map(|(k, d)| (k.to_string(), d.to_string())).collect();
            cap.get().written_input(&data, |w| detpy_core::proof::foreign_to_entry(w, &nid, e, None))
        }) else {
            return Ok(None);
        };
        let Some((key, writer)) = found else { return Ok(None) };
        let reason = format!("written: {key} was written by {writer} earlier in this session");
        let w = nid.as_bytes().to_vec();
        let mut st = lock(&self.st);
        st.hits.remove(&w);
        st.misses.insert(w, reason.clone().into_bytes());
        Ok(Some(reason))
    }

    /// The receipt of a result reused in this session (None: not reused).
    fn hit(&self, py: Python<'_>, nodeid: Bound<'_, PyString>) -> PyResult<Option<Py<PyAny>>> {
        let w = w_of(&nodeid)?;
        Ok(lock(&self.st).hits.get(&w).map(|r| r.clone_ref(py)))
    }

    fn is_hit(&self, nodeid: Bound<'_, PyString>) -> PyResult<bool> {
        let w = w_of(&nodeid)?;
        Ok(lock(&self.st).hits.contains(&w))
    }

    #[getter]
    fn n_hits(&self) -> usize {
        lock(&self.st).hits.len()
    }

    /// Node ids reused in this session, in decision order.
    #[getter]
    fn hit_ids<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyAny>>> {
        lock(&self.st).hits.keys.iter().map(|k| py_of(py, k)).collect()
    }

    // -- tests --------------------------------------------------------------------------------------------------------
    /// A test that runs (not reused) starts, with the contexts of the wider-scoped fixtures it uses.
    fn start_test(&self, nodeid: Bound<'_, PyString>, fixtures: Vec<Bound<'_, PyString>>) -> PyResult<()> {
        let mut fx = fixtures.iter().map(w_of).collect::<PyResult<Vec<_>>>()?;
        fx.sort();
        fx.dedup();
        lock(&self.st).fixture_ctx.insert(w_of(&nodeid)?, fx);
        Ok(())
    }

    /// A test that ran ends: its duration is kept, it joins the tests that ran; returns the test's index for the
    /// loaded-module scan (`test_index.get(nid, len(ran))`, before it joins).
    fn end_test(&self, nodeid: Bound<'_, PyString>, duration: f64) -> PyResult<i64> {
        let w = w_of(&nodeid)?;
        let mut st = lock(&self.st);
        st.dur.insert(w.clone(), duration);
        let ix = st.test_index.get(&w).copied().unwrap_or(st.ran.len() as i64);
        st.ran.push(w);
        Ok(ix)
    }

    /// `pytest_runtest_logreport` of a test that is not reused: its phase report and fingerprint.
    fn report(&self, report: &Bound<'_, PyAny>) -> PyResult<()> {
        let py = report.py();
        let nid = w_any(&report.getattr(intern!(py, "nodeid"))?)?;
        if lock(&self.st).hits.contains(&nid) {
            return Ok(());
        }
        let when = w_any(&report.getattr(intern!(py, "when"))?)?;
        let outcome = report.getattr(intern!(py, "outcome"))?;
        let mut info = Map::new();
        let mut err: Option<String> = None;
        match to_value(&outcome) {
            Ok(v) => {
                info.insert("outcome".into(), v);
            }
            Err(e) => err = Some(e),
        }
        if report.hasattr(intern!(py, "wasxfail"))? {
            match to_value(&report.getattr(intern!(py, "wasxfail"))?) {
                Ok(v) => {
                    info.insert("wasxfail".into(), v);
                }
                Err(e) => err = err.or(Some(e)),
            }
        }
        if report.getattr(intern!(py, "skipped"))?.is_truthy()? {
            let lr = report.getattr(intern!(py, "longrepr"))?;
            if let Ok(t) = lr.cast::<PyTuple>() {
                if t.len() == 3 {
                    let a = t.get_item(0)?.str()?;
                    let c = t.get_item(2)?.str()?;
                    match (to_value(a.as_any()), to_value(&t.get_item(1)?), to_value(c.as_any())) {
                        (Ok(a), Ok(b), Ok(c)) => {
                            info.insert("longrepr".into(), Value::Array(vec![a, b, c]));
                        }
                        (a, b, c) => err = err.or(a.err()).or(b.err()).or(c.err()),
                    }
                }
            }
        }
        let props = report.getattr(intern!(py, "user_properties"))?;
        let mut fp: Option<Bound<'_, PyAny>> = None;
        for kv in props.try_iter()? {
            let kv = kv?;
            let (k, v): (Bound<'_, PyAny>, Bound<'_, PyAny>) = kv.extract()?;
            if k.eq("detpy_fingerprint")? {
                fp = Some(v);
            }
        }
        let mut st = lock(&self.st);
        st.parts.get_mut_or_default(&nid).insert(when, match err {
            None => Ok(Value::Object(info)),
            Some(e) => Err(e),
        });
        if let Some(v) = fp {
            st.fingerprints.insert(nid, v.unbind());
        }
        Ok(())
    }

    /// The Level 0 fingerprints of the tests that ran (the plugin's recorder), for those not reused.
    fn add_fingerprints(&self, fps: &Bound<'_, PyDict>) -> PyResult<()> {
        let mut st = lock(&self.st);
        for (k, v) in fps.iter() {
            let w = w_any(&k)?;
            if !st.hits.contains(&w) {
                st.fingerprints.insert(w, v.unbind());
            }
        }
        Ok(())
    }

    /// The final outcome of every test with reports (`{nodeid: _final(parts)}`).
    fn outcomes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let d = PyDict::new(py);
        for (k, p) in st.parts.iter() {
            d.set_item(py_of(py, k)?, final_outcome(Some(p)))?;
        }
        Ok(d)
    }

    /// Compare each result re-run for verification with its recorded outcome and fingerprint.
    fn compare_verified(&self, py: Python<'_>) -> PyResult<()> {
        let mut st = lock(&self.st);
        let mut out = Vec::new();
        for (nid, r) in st.verifying.iter() {
            let r = r.bind(py);
            let o = st.parts.get(nid).map(|p| final_outcome(Some(p)));
            let cached = r.get_item("outcome")?;
            let same = match &o {
                Some(o) => cached.eq(o.as_str())?,
                None => cached.is_none(),
            };
            let fp = st.fingerprints.get(nid).map(|f| f.bind(py).clone());
            let same_fp = match fp {
                Some(f) => f.eq(r.get_item("fingerprint")?)?,
                None => r.get_item("fingerprint")?.is_none(),
            };
            let d = PyDict::new(py);
            d.set_item("nodeid", py_of(py, nid)?)?;
            d.set_item("cached", cached)?;
            d.set_item("fresh", o)?;
            d.set_item("same", same)?;
            d.set_item("same_fingerprint", same_fp)?;
            out.push(d.unbind());
        }
        st.verify_results.extend(out);
        Ok(())
    }

    // -- recording ------------------------------------------------------------------------------------------------
    /// The repository files whose facts the record needs: every executed or loaded file (sorted), then the own files
    /// of the tests that ran whose whole content is their input (doctests, items without a Python object), in run
    /// order. Returns `(needed, whole files)`.
    fn files_needed<'py>(
        &self,
        py: Python<'py>,
        cap: &Bound<'py, CaptureCore>,
        items: &Bound<'py, PyDict>,
    ) -> PyResult<(Vec<Bound<'py, PyAny>>, Vec<Bound<'py, PyAny>>)> {
        let mut needed: Vec<W> = Vec::new();
        for r in cap.getattr(intern!(py, "fnames"))?.try_iter()? {
            needed.push(w_any(&r?)?);
        }
        for e in cap.getattr(intern!(py, "loaded_order"))?.try_iter()? {
            needed.push(w_any(&e?.get_item(0)?)?);
        }
        for r in cap.getattr(intern!(py, "preloaded"))?.try_iter()? {
            needed.push(w_any(&r?)?);
        }
        needed.sort();
        needed.dedup();
        let st = lock(&self.st);
        let mut whole: Vec<W> = Vec::new();
        for nid in &st.ran {
            let Some(item) = items.get_item(py_of(py, nid)?)? else { continue };
            if is_whole(&item)? {
                let own = ctx_file(nid).to_vec();
                if !whole.contains(&own) {
                    whole.push(own);
                }
            }
        }
        Ok((
            needed.iter().map(|w| py_of(py, w)).collect::<PyResult<_>>()?,
            whole.iter().map(|w| py_of(py, w)).collect::<PyResult<_>>()?,
        ))
    }

    /// Record every test that ran (`ProofCachePlugin._record_captured` with `_plan`): the plan is built here from
    /// the session's state, the capture (`CaptureCore.fill_plan`) and the facts the shell computed (`fcache`:
    /// `{rel: store index or None}`, `needed`, the folded lines `per` / `imp`), then recorded in the store. The
    /// reasons a test is not cached and where are kept. Returns the seconds spent recording (the "assemble" phase).
    #[pyo3(signature = (store, cap, items, fcache, needed, per, imp, module_of, control_urandom, time_controlled, cassette_path))]
    #[allow(clippy::too_many_arguments)]
    fn record<'py>(
        &self,
        py: Python<'py>,
        store: &Bound<'py, ProofCache>,
        cap: &Bound<'py, CaptureCore>,
        items: &Bound<'py, PyDict>,
        fcache: &Bound<'py, PyDict>,
        needed: Vec<String>,
        per: Vec<(Vec<u64>, Vec<u64>)>,
        imp: (Vec<u64>, Vec<u64>),
        module_of: &Bound<'py, PyAny>,
        control_urandom: bool,
        time_controlled: bool,
        cassette_path: Option<Bound<'py, PyAny>>,
    ) -> PyResult<f64> {
        let os = py.import("os")?;
        let ospath = os.getattr("path")?;
        let mut plan = Plan::default();
        let (root, root_sep): (Bound<'py, PyAny>, String) = {
            let rs = cap.getattr(intern!(py, "root_sep"))?;
            (cap.getattr(intern!(py, "root"))?, rs.extract()?)
        };
        for (k, v) in fcache.iter() {
            if !v.is_none() {
                plan.file_ix.insert(k.extract()?, v.extract()?);
            }
        }
        plan.per = per;
        plan.imp = imp;
        plan.needed = needed;
        // test files of every collected item and their module names
        for nid in items.keys() {
            let tf = ctx_file(&w_any(&nid)?).to_vec();
            let tfs = utf8(&tf)?;
            if !plan.test_modules.contains_key(&tfs) {
                let p = ospath.call_method1("join", (&root, py_of(py, &tf)?))?;
                let m = module_of.call1((p,))?.get_item(0)?;
                plan.test_modules.insert(tfs, if m.is_none() { None } else { Some(m.extract()?) });
            }
        }
        {
            let st = lock(&self.st);
            for nid in &st.ran {
                let Some(item) = items.get_item(py_of(py, nid)?)? else { continue };
                let parts = st.parts.get(nid);
                let mut report = Map::new();
                if let Some(p) = parts {
                    for w in ["setup", "call"] {
                        if let Some(r) = p.get(w.as_bytes()) {
                            match r {
                                Ok(v) => {
                                    report.insert(w.into(), v.clone());
                                }
                                Err(e) => return Err(PyTypeError::new_err(e.clone())),
                            }
                        }
                    }
                }
                let fingerprint = match st.fingerprints.get(nid) {
                    Some(f) => f.bind(py).extract::<String>()?,
                    None => String::new(),
                };
                plan.tests.push(TestRun {
                    nodeid: utf8(nid)?,
                    outcome: final_outcome(parts),
                    report: Value::Object(report),
                    fingerprint,
                    duration: st.dur.get(nid).copied().unwrap_or(0.0),
                    index: st.test_index.get(nid).copied().unwrap_or(0),
                    fixtures: st.fixture_ctx.get(nid).map(|f| f.iter().map(|x| utf8(x)).collect::<PyResult<_>>()).transpose()?.unwrap_or_default(),
                    whole: is_whole(&item)?,
                });
            }
            plan.hits = st.hits.keys.iter().map(|k| utf8(k)).collect::<PyResult<_>>()?;
            // the stale check leaves out a path whose recorded absence was compared with what this session's code
            // saw before it created it, when nothing wrote it after the decision (review R-009b R2)
            if !st.excl_seeded.is_empty() {
                let writers = cap.getattr(intern!(py, "writers"))?.cast_into::<PyDict>()?;
                let mut skip = Vec::new();
                for (p, w0) in &st.excl_seeded {
                    let pp = py_of(py, p)?;
                    if let Some(now) = writers.get_item(&pp)? {
                        if now.eq(w0.bind(py))? {
                            skip.push(cap.call_method1(intern!(py, "_key"), (pp,))?.extract::<String>()?);
                        }
                    }
                }
                skip.sort();
                plan.stale_skip = skip;
            }
            plan.config = utf8(&st.config)?;
            plan.runtime = utf8(&st.runtime)?;
            plan.run = utf8(&st.run_id)?;
            plan.epoch = st.epoch;
        }
        plan.root_sep = root_sep;
        plan.control_urandom = control_urandom;
        plan.time_controlled = time_controlled;
        if let Some(cp) = cassette_path.filter(|c| c.is_truthy().unwrap_or(false)) {
            let path: std::path::PathBuf = cp.extract()?;
            let d = py.detach(|| detpy_core::proof::file_digest(&path));
            let key: String = cap.call_method1(intern!(py, "_key"), (ospath.call_method1("realpath", (&cp,))?,))?.extract()?;
            plan.cassette = Some((key, match d {
                Some(d) => format!("f:{d}"),
                None => "missing".into(),
            }));
        }
        plan.env0 = cap.getattr(intern!(py, "env0"))?.extract()?;
        let t = Instant::now();
        let out = store.get().record_plan(py, plan, cap)?;
        let assemble = t.elapsed().as_secs_f64();
        let mut st = lock(&self.st);
        st.recorded += out.recorded as i64;
        for (nid, path) in out.stale {
            st.stale_hits.insert(nid.into_bytes(), path.into_bytes());
        }
        if out.not_cached.iter().any(|(_, _, c)| !c.is_empty()) {
            let names = cap.getattr(intern!(py, "ctx_names"))?.cast_into::<PyList>()?;
            for (nid, why, ctxs) in &out.not_cached {
                if !ctxs.is_empty() {
                    let w = where_(cap, &names, why.as_bytes(), ctxs)?;
                    st.not_cached_where.insert(nid.as_bytes().to_vec(), w);
                }
            }
        }
        for (nid, why, _) in out.not_cached {
            st.not_cached.insert(nid.into_bytes(), why.into_bytes());
        }
        Ok(assemble)
    }

    // -- parallel sessions (pytest-xdist under --det) -----------------------------------------------------------------
    /// A worker's positions of the collected tests (the serial order; a worker runs a subsequence of it), as the
    /// decision loop sets them in a serial session: the loaded-module bookkeeping depends on them.
    fn set_test_index(&self, nodeids: Vec<String>) {
        let mut st = lock(&self.st);
        for (i, n) in nodeids.into_iter().enumerate() {
            st.test_index.insert(n.into_bytes(), i as i64);
        }
    }

    /// A worker's part of the summary for the controller: (tests that ran, entries recorded, {nodeid: why not
    /// cached}).
    #[allow(clippy::type_complexity)]
    fn worker_summary(&self) -> PyResult<(Vec<String>, i64, Vec<(String, String)>, Vec<(String, String)>)> {
        let st = lock(&self.st);
        let ran = st.ran.iter().map(|k| utf8(k)).collect::<PyResult<Vec<_>>>()?;
        let nc = st.not_cached.iter().map(|(k, v)| Ok((utf8(k)?, utf8(v)?))).collect::<PyResult<Vec<_>>>()?;
        // where each reason was found (the summary's "not cacheable" detail), so a parallel run reports it too
        let wh = st
            .not_cached_where
            .iter()
            .map(|(k, v)| Ok((utf8(k)?, String::from_utf8_lossy(v).into_owned())))
            .collect::<PyResult<Vec<_>>>()?;
        Ok((ran, st.recorded, nc, wh))
    }

    /// The controller adds a worker's summary (`worker_summary`) to the session's.
    #[pyo3(signature = (ran, recorded, not_cached, where_ = None))]
    fn merge_worker(&self, ran: Vec<String>, recorded: i64, not_cached: Vec<(String, String)>,
                    where_: Option<Vec<(String, String)>>) {
        let mut st = lock(&self.st);
        st.ran.extend(ran.into_iter().map(String::into_bytes));
        st.recorded += recorded;
        for (k, v) in not_cached {
            st.not_cached.insert(k.into_bytes(), v.into_bytes());
        }
        for (k, v) in where_.unwrap_or_default() {
            st.not_cached_where.insert(k.into_bytes(), v.into_bytes());
        }
    }

    /// The controller's merge of the shards: entries the cross-worker rule dropped (not cached, with the reason) and
    /// reused results whose inputs the session wrote.
    fn apply_merge(&self, dropped: Vec<(String, String)>, stale: Vec<(String, String)>) {
        let mut st = lock(&self.st);
        for (k, v) in dropped {
            st.recorded -= 1;
            st.not_cached.insert(k.into_bytes(), v.into_bytes());
        }
        for (k, v) in stale {
            st.stale_hits.insert(k.into_bytes(), v.into_bytes());
        }
    }

    // -- timings and errors ----------------------------------------------------------------------------------------
    fn set_phase(&self, name: Bound<'_, PyString>, seconds: f64) -> PyResult<()> {
        lock(&self.st).phases.insert(w_of(&name)?, seconds);
        Ok(())
    }

    fn phase(&self, name: Bound<'_, PyString>) -> PyResult<f64> {
        Ok(lock(&self.st).phases.get(&w_of(&name)?).copied().unwrap_or(0.0))
    }

    #[setter]
    fn set_t_check(&self, v: f64) {
        lock(&self.st).t_check = v;
    }

    #[setter]
    fn set_t_record(&self, v: f64) {
        lock(&self.st).t_record = v;
    }

    #[setter]
    fn set_error(&self, v: Option<Bound<'_, PyString>>) -> PyResult<()> {
        lock(&self.st).error = v.map(|s| w_of(&s)).transpose()?;
        Ok(())
    }

    /// Write the receipts file (`ProofCache.write_receipts` with this session's hits and misses).
    fn write_receipts(&self, py: Python<'_>, store: &Bound<'_, ProofCache>) -> PyResult<()> {
        let (path, hits, misses) = {
            let st = lock(&self.st);
            let path: std::path::PathBuf = py_of(py, &st.receipts_path)?.extract()?;
            let hits = st.hits.keys.iter().map(|k| Ok(py_of(py, k)?.cast_into::<PyString>()?)).collect::<PyResult<Vec<_>>>()?;
            let misses = st
                .misses
                .iter()
                .map(|(k, v)| Ok((py_of(py, k)?.cast_into::<PyString>()?, py_of(py, v)?.cast_into::<PyString>()?)))
                .collect::<PyResult<Vec<_>>>()?;
            (path, hits, misses)
        };
        store.get().write_receipts(py, path, hits, misses)
    }

    // -- reporting --------------------------------------------------------------------------------------------------
    /// `ProofCachePlugin.summary_data()`.
    fn summary_data<'py>(&self, py: Python<'py>, cap: &Bound<'py, CaptureCore>) -> PyResult<Bound<'py, PyDict>> {
        let round = py.import("builtins")?.getattr("round")?;
        let st = lock(&self.st);
        let mut kinds: OMap<i64> = OMap::default();
        for (_, why) in st.misses.iter() {
            *kinds.get_mut_or_default(head(why, b':')) += 1;
        }
        let mut nc: OMap<i64> = OMap::default();
        let mut detail: OMap<i64> = OMap::default();
        for (nid, why) in st.not_cached.iter() {
            let outcome = why.starts_with(b"outcome");
            let k = if outcome { head(why, b' ') } else { head(why, b':') };
            *nc.get_mut_or_default(k) += 1;
            if !outcome {
                let full = match st.not_cached_where.get(nid) {
                    Some(w) if !w.is_empty() => [why.as_slice(), b": ", w.as_slice()].concat(),
                    _ => why.clone(),
                };
                *detail.get_mut_or_default(&full) += 1;
            }
        }
        let mut top: Vec<(&W, &i64)> = detail.iter().collect();
        top.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
        top.truncate(40);
        let counts = |m: &mut dyn Iterator<Item = (&W, &i64)>| -> PyResult<Bound<'py, PyDict>> {
            let d = PyDict::new(py);
            for (k, v) in m {
                d.set_item(py_of(py, k)?, *v)?;
            }
            Ok(d)
        };
        let strmap = |m: &OMap<W>| -> PyResult<Bound<'py, PyDict>> {
            let d = PyDict::new(py);
            for (k, v) in m.iter() {
                d.set_item(py_of(py, k)?, py_of(py, v)?)?;
            }
            Ok(d)
        };
        let mut reused_s = 0i64.into_bound_py_any(py)?;
        for (_, r) in st.hits.iter() {
            let d = r.bind(py).call_method1(intern!(py, "get"), ("duration", 0.0))?;
            let d = if d.is_truthy()? { d } else { 0.0f64.into_pyobject(py)?.into_any() };
            let f = py.import("builtins")?.getattr("float")?.call1((d,))?;
            reused_s = reused_s.add(f)?;
        }
        let out = PyDict::new(py);
        out.set_item("reused", st.hits.len())?;
        out.set_item("verified", st.verifying.len())?;
        out.set_item("ran", st.ran.len())?;
        out.set_item("recorded", st.recorded)?;
        out.set_item("miss_reasons", counts(&mut kinds.iter())?)?;
        out.set_item("not_cached", counts(&mut nc.iter())?)?;
        out.set_item("not_cached_detail", counts(&mut top.into_iter())?)?;
        out.set_item("children", cap.getattr(intern!(py, "children"))?)?;
        let follower = cap.getattr(intern!(py, "follower"))?;
        out.set_item(
            "children_not_followed",
            if follower.is_none() { py.None().into_bound(py) } else { follower.getattr(intern!(py, "why_not"))? },
        )?;
        out.set_item("child_entropy_draws", cap.getattr(intern!(py, "child_entropy"))?)?;
        out.set_item("reused_recorded_seconds", round.call1((reused_s, 3))?)?;
        out.set_item("check_seconds", round.call1((st.t_check, 3))?)?;
        out.set_item("record_seconds", round.call1((st.t_record, 3))?)?;
        let ph = PyDict::new(py);
        for (k, v) in st.phases.iter() {
            ph.set_item(py_of(py, k)?, round.call1((*v, 3))?)?;
        }
        out.set_item("phase_seconds", ph)?;
        out.set_item("config", py_of(py, &st.config)?)?;
        out.set_item("runtime", py_of(py, &st.runtime)?)?;
        out.set_item("epoch_ns", st.epoch)?;
        let bad = PyList::empty(py);
        for v in &st.verify_results {
            let v = v.bind(py);
            if !v.get_item("same")?.map(|s| s.is_truthy()).transpose()?.unwrap_or(false) {
                bad.append(v)?;
            }
        }
        out.set_item("verify_mismatches", bad)?;
        out.set_item("stale_reuses", strmap(&st.stale_hits)?)?;
        out.set_item("error", st.error.as_ref().map(|e| py_of(py, e)).transpose()?)?;
        out.set_item("receipts", py_of(py, &st.receipts_path)?)?;
        Ok(out)
    }

    /// The cache's part of the outcomes file (`{**summary_data(), "reused_ids", "verified_ids", "not_cached_ids",
    /// "not_cached_where", "miss_ids"}`).
    fn outcomes_data<'py>(&self, py: Python<'py>, cap: &Bound<'py, CaptureCore>) -> PyResult<Bound<'py, PyDict>> {
        let out = self.summary_data(py, cap)?;
        let st = lock(&self.st);
        let sorted = |m: &[W]| -> PyResult<Bound<'py, PyList>> {
            let mut v: Vec<&W> = m.iter().collect();
            v.sort();
            PyList::new(py, v.into_iter().map(|k| py_of(py, k)).collect::<PyResult<Vec<_>>>()?)
        };
        let strmap = |m: &OMap<W>| -> PyResult<Bound<'py, PyDict>> {
            let d = PyDict::new(py);
            for (k, v) in m.iter() {
                d.set_item(py_of(py, k)?, py_of(py, v)?)?;
            }
            Ok(d)
        };
        out.set_item("reused_ids", sorted(&st.hits.keys)?)?;
        out.set_item("verified_ids", sorted(&st.verifying.keys)?)?;
        out.set_item("not_cached_ids", strmap(&st.not_cached)?)?;
        out.set_item("not_cached_where", strmap(&st.not_cached_where)?)?;
        out.set_item("miss_ids", strmap(&st.misses)?)?;
        Ok(out)
    }

    /// The lines of the terminal summary after its section title: `[(text, markup or None)]` (`markup`: "yellow"
    /// or "red", passed as `write_line(text, **{markup: True})`).
    fn summary_lines<'py>(&self, py: Python<'py>, cap: &Bound<'py, CaptureCore>, verbose: i64) -> PyResult<Vec<(Bound<'py, PyAny>, Option<&'static str>)>> {
        let s = self.summary_data(py, cap)?;
        let g = |k: &str| -> PyResult<String> { Ok(s.get_item(k)?.map(|v| v.str().map(|x| x.to_string())).transpose()?.unwrap_or_default()) };
        let mut out: Vec<(Bound<'py, PyAny>, Option<&'static str>)> = Vec::new();
        let mut line = |t: String, m: Option<&'static str>| out.push((PyString::new(py, &t).into_any(), m));
        line(
            format!(
                "reused {} result(s) with proof, ran {}, recorded {} (check {}s, record {}s); config {}, runtime {}",
                g("reused")?, g("ran")?, g("recorded")?, g("check_seconds")?, g("record_seconds")?, g("config")?, g("runtime")?
            ),
            None,
        );
        let sorted_counts = |k: &str| -> PyResult<Vec<String>> {
            let d = s.get_item(k)?.unwrap().cast_into::<PyDict>()?;
            let mut v: Vec<(W, String)> = d.iter().map(|(a, b)| Ok((w_any(&a)?, format!("{} {}", a.str()?, b.str()?)))).collect::<PyResult<_>>()?;
            v.sort_by(|a, b| a.0.cmp(&b.0));
            Ok(v.into_iter().map(|x| x.1).collect())
        };
        let mr = sorted_counts("miss_reasons")?;
        if !mr.is_empty() {
            line(format!("not reused: {}", mr.join(", ")), None);
        }
        let nc = sorted_counts("not_cached")?;
        if !nc.is_empty() {
            line(format!("not cacheable: {}", nc.join(", ")), None);
        }
        let st = lock(&self.st);
        let mut texts: Vec<(Bound<'py, PyAny>, Option<&'static str>)> = Vec::new();
        for (nid, path) in st.stale_hits.iter() {
            texts.push((
                PyString::new(py, "WARNING reused ").into_any().add(py_of(py, nid)?)?.add(", but this session then wrote its input ")?.add(py_of(py, path)?)?.add(": entry dropped")?,
                Some("yellow"),
            ));
        }
        drop(line);
        out.extend(texts);
        if !st.verify_results.is_empty() {
            let bad = s.get_item("verify_mismatches")?.unwrap().cast_into::<PyList>()?;
            out.push((
                PyString::new(py, &format!("verified {} reusable result(s) by running them: {} mismatch(es)", st.verify_results.len(), bad.len())).into_any(),
                if bad.is_empty() { None } else { Some("red") },
            ));
            for b in bad.iter() {
                let t = format!(
                    "  MISMATCH {}: cached {}, fresh {}",
                    b.get_item("nodeid")?.str()?, b.get_item("cached")?.str()?, b.get_item("fresh")?.str()?
                );
                let t = PyString::new(py, &t).into_any();
                out.push((t, Some("red")));
            }
        }
        if verbose > 0 {
            for (nid, r) in st.hits.iter() {
                let r = r.bind(py);
                let gi = |k: &str| -> PyResult<String> { Ok(r.get_item(k)?.str()?.to_string()) };
                let epoch = r.get_item("epoch")?;
                let ep = if epoch.is_none() { String::new() } else { format!(", epoch {}", epoch.str()?) };
                let t = PyString::new(py, "REUSED ").into_any().add(py_of(py, nid)?)?.add(format!(
                    " key={} run={} outcome={}: checked {} functions, {} modules, {} conftest hook sets, {} whole files, {} data paths, {} env vars; runtime {}, config {}{}",
                    gi("key")?, gi("run")?, gi("outcome")?, gi("n_units")?, gi("n_skeleton")?, gi("n_hooks")?, gi("n_content")?, gi("n_data")?, gi("n_env")?, gi("runtime")?, gi("config")?, ep
                ))?;
                out.push((t, None));
            }
        }
        out.push((PyString::new(py, &format!("receipts: {}", g("receipts")?)).into_any(), None));
        Ok(out)
    }

    /// The session's bookkeeping as the dicts `ProofCachePlugin` kept (`parts`, `ran`, `test_index`,
    /// `fixture_ctx`, `dur`, `fingerprints`, `hits`, `verifying`, `misses`), for the equivalence harnesses that run
    /// a Python reference loop on them.
    fn state<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let out = PyDict::new(py);
        let parts = PyDict::new(py);
        for (nid, p) in st.parts.iter() {
            let d = PyDict::new(py);
            for (w, r) in p.iter() {
                if let Ok(v) = r {
                    d.set_item(py_of(py, w)?, crate::proofcache::value_to_py(py, v)?)?;
                }
            }
            parts.set_item(py_of(py, nid)?, d)?;
        }
        out.set_item("parts", parts)?;
        out.set_item("ran", st.ran.iter().map(|k| py_of(py, k)).collect::<PyResult<Vec<_>>>()?)?;
        let ti = PyDict::new(py);
        let fx = PyDict::new(py);
        let du = PyDict::new(py);
        let fp = PyDict::new(py);
        for (k, v) in &st.test_index {
            ti.set_item(py_of(py, k)?, *v)?;
        }
        for (k, v) in &st.fixture_ctx {
            fx.set_item(py_of(py, k)?, v.iter().map(|x| py_of(py, x)).collect::<PyResult<Vec<_>>>()?)?;
        }
        for (k, v) in &st.dur {
            du.set_item(py_of(py, k)?, *v)?;
        }
        for (k, v) in &st.fingerprints {
            fp.set_item(py_of(py, k)?, v.bind(py))?;
        }
        out.set_item("test_index", ti)?;
        out.set_item("fixture_ctx", fx)?;
        out.set_item("dur", du)?;
        out.set_item("fingerprints", fp)?;
        for (name, m) in [("hits", &st.hits), ("verifying", &st.verifying)] {
            let d = PyDict::new(py);
            for (k, v) in m.iter() {
                d.set_item(py_of(py, k)?, v.bind(py))?;
            }
            out.set_item(name, d)?;
        }
        let mi = PyDict::new(py);
        for (k, v) in st.misses.iter() {
            mi.set_item(py_of(py, k)?, py_of(py, v)?)?;
        }
        out.set_item("misses", mi)?;
        Ok(out)
    }

    /// The final outcome of one test's phase reports dict (`proofcache._final`, for the tests).
    #[staticmethod]
    fn final_of(parts: &Bound<'_, PyDict>) -> PyResult<String> {
        let mut m: OMap<Part> = OMap::default();
        for (k, v) in parts.iter() {
            let mut info = Map::new();
            for (a, b) in v.cast_into::<PyDict>()?.iter() {
                info.insert(a.extract()?, to_value(&b).unwrap_or(Value::Null));
            }
            m.insert(w_any(&k)?, Ok(Value::Object(info)));
        }
        Ok(final_outcome(Some(&m)))
    }

    /// `_ctx_label(name)` (for the tests).
    #[staticmethod]
    fn ctx_label_of<'py>(py: Python<'py>, name: Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
        py_of(py, &ctx_label(&w_of(&name)?))
    }
}

/// A test whose own file's whole content is its input: a doctest, an item without a Python object.
fn is_whole(item: &Bound<'_, PyAny>) -> PyResult<bool> {
    let py = item.py();
    Ok(item.get_type().name()?.to_cow()? == "DoctestItem" || !item.hasattr(intern!(py, "obj"))?)
}

/// `why` with the first occurrence of its cause: what (command, address...) and in which context
/// (`ProofCachePlugin._where`).
fn where_(cap: &Bound<'_, CaptureCore>, names: &Bound<'_, PyList>, why: &[u8], ctxs: &[u32]) -> PyResult<W> {
    let py = cap.py();
    // a refusal carried from an earlier context (prefix rule): its cause is looked up in those contexts
    let why = why.strip_prefix(b"after an earlier test or fixture of this process: ".as_slice()).unwrap_or(why);
    let Some(flag) = flag_of(why) else { return Ok(why.to_vec()) };
    for &c in ctxs {
        let d = cap.call_method1(intern!(py, "why_of"), (c, flag))?;
        if !d.is_none() {
            let name = w_any(&names.get_item(c as usize)?)?;
            let mut out = w_any(&d)?;
            out.extend_from_slice(b" (");
            out.extend_from_slice(&ctx_label(&name));
            out.push(b')');
            return Ok(out);
        }
    }
    Ok(Vec::new())
}

use pyo3::IntoPyObjectExt;

/// The `--det-outcomes` outcome of a test from its phase outcomes (`plugin._final_outcome`): a setup that did not
/// pass decides (skipped / xfailed, else "error"), else the call; a teardown that did not pass or skip appends
/// "+teardown-error". `None`: the phase did not report.
#[pyfunction]
#[pyo3(signature = (setup, call, teardown))]
pub fn det_outcome(setup: Option<&str>, call: Option<&str>, teardown: Option<&str>) -> String {
    let mut main = match (setup, call) {
        (Some(s), _) if s != "passed" => if s == "skipped" || s == "xfailed" { s } else { "error" }.to_string(),
        (_, Some(c)) => c.to_string(),
        _ => "unknown".to_string(),
    };
    if !matches!(teardown, None | Some("passed") | Some("skipped")) {
        main.push_str("+teardown-error");
    }
    main
}
