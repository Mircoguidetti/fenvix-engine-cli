//! Python binding of the cache with proof (`detpy._core.ProofCache`).

use detpy_core::proof::{self, Checker, CodeFile, Current, Observed, Store, Unit};
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};

struct Inner {
    store: Store,
    checker: Checker,
    touched: BTreeSet<String>,
}

/// The on-disk store of one cache directory plus the reuse checker of the
/// current session.
#[pyclass(module = "detpy._core", frozen)]
pub struct ProofCache {
    dir: PathBuf,
    inner: Mutex<Inner>,
}

fn lock(m: &Mutex<Inner>) -> MutexGuard<'_, Inner> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

type UnitTuple = (String, u32, u32, String);
type FactsTuple = (String, String, String, String, Vec<UnitTuple>, Vec<String>);

fn facts_tuple(f: &CodeFile) -> FactsTuple {
    (
        f.path.clone(),
        f.content.clone(),
        f.skeleton.clone(),
        f.hooks.clone(),
        f.units.iter().map(|u| (u.q.clone(), u.a, u.b, u.d.clone())).collect(),
        f.imports.clone(),
    )
}

fn code_file(path: String, content: String, skeleton: String, hooks: String, units: Vec<UnitTuple>, imports: Vec<String>) -> CodeFile {
    CodeFile {
        path,
        content,
        skeleton,
        hooks,
        units: units.into_iter().map(|(q, a, b, d)| Unit { q, a, b, d }).collect(),
        imports,
    }
}

#[pymethods]
impl ProofCache {
    /// Load the store of `dir`; the checker compares with the session state
    /// given to `begin` (until then nothing is reusable).
    #[new]
    fn new(dir: PathBuf, root: PathBuf) -> Self {
        let store = Store::load(&dir);
        let checker = Checker::new(Current { root, ..Default::default() });
        ProofCache { dir, inner: Mutex::new(Inner { store, checker, touched: BTreeSet::new() }) }
    }

    /// Set the current session state: configuration and runtime digests, clock
    /// epoch, environment at session start.
    fn begin(&self, config: String, runtime: String, epoch: i64, env: BTreeMap<String, String>) {
        let mut g = lock(&self.inner);
        let root = g.checker.cur.root.clone();
        let startup = g.checker.cur.startup.clone();
        g.checker = Checker::new(Current { root, config, runtime, epoch, env, startup });
    }

    /// Set the digest of what this session's start-up processes gave back (once start-up has ended, before
    /// any check): a recorded entry is reusable only with the same digest.
    fn set_startup(&self, startup: String) {
        lock(&self.inner).checker.cur.startup = startup;
    }

    /// Known code files whose content changed: `[(path, current content digest)]`.
    fn changed_code_files(&self) -> Vec<(String, String)> {
        let mut g = lock(&self.inner);
        let Inner { store, checker, .. } = &mut *g;
        checker.changed_code_files(store)
    }

    /// Facts of the current version of a changed code file.
    fn set_fresh(&self, path: String, content: String, skeleton: String, hooks: String, units: Vec<UnitTuple>, imports: Vec<String>) {
        lock(&self.inner).checker.set_fresh(code_file(path, content, skeleton, hooks, units, imports));
    }

    /// `(True, receipt_json)` when the recorded result of `nodeid` may be
    /// reused, else `(False, "kind: detail")`.
    fn check(&self, nodeid: &str) -> PyResult<(bool, String)> {
        let mut g = lock(&self.inner);
        let Inner { store, checker, .. } = &mut *g;
        Ok(match checker.check(store, nodeid) {
            Ok(r) => (true, serde_json::to_string(&r).map_err(|e| PyValueError::new_err(e.to_string()))?),
            Err(m) => (false, format!("{}: {}", m.kind, m.detail)),
        })
    }

    /// Recorded entry of `nodeid` as JSON.
    fn entry(&self, nodeid: &str) -> PyResult<String> {
        let g = lock(&self.inner);
        let e = g.store.tests.get(nodeid).ok_or_else(|| PyKeyError::new_err(nodeid.to_string()))?;
        serde_json::to_string(e).map_err(|e| PyValueError::new_err(e.to_string()))
    }

    /// Index of known facts for (`path`, `content`), if any.
    fn file_index(&self, path: &str, content: &str) -> Option<u32> {
        lock(&self.inner).store.file_index(path, content)
    }

    fn file_facts(&self, index: u32) -> PyResult<FactsTuple> {
        let g = lock(&self.inner);
        g.store.files.get(index as usize).map(facts_tuple).ok_or_else(|| PyKeyError::new_err(index))
    }

    /// Add the facts of one file version; returns its index.
    fn add_file(&self, path: String, content: String, skeleton: String, hooks: String, units: Vec<UnitTuple>, imports: Vec<String>) -> u32 {
        lock(&self.inner).store.add_file(code_file(path, content, skeleton, hooks, units, imports))
    }

    /// Record the inputs and result of a test that ran; returns its key.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (nodeid, outcome, report_json, fingerprint, duration, run, config, runtime, epoch, env, data, content, skeleton, hooks, units, startup = String::new()))]
    fn record(
        &self,
        nodeid: &str,
        outcome: String,
        report_json: &str,
        fingerprint: String,
        duration: f64,
        run: String,
        config: String,
        runtime: String,
        epoch: Option<i64>,
        env: Vec<(String, String)>,
        data: Vec<(String, String)>,
        content: Vec<u32>,
        skeleton: Vec<u32>,
        hooks: Vec<u32>,
        units: Vec<(u32, u32)>,
        startup: String,
    ) -> PyResult<String> {
        let report = serde_json::from_str(report_json).map_err(|e| PyValueError::new_err(format!("report: {e}")))?;
        let mut g = lock(&self.inner);
        g.touched.insert(nodeid.to_string());
        Ok(g.store.record(
            nodeid,
            Observed { outcome, report, fingerprint, duration, run, config, runtime, epoch, env, data, content, skeleton, hooks, units, startup },
        ))
    }

    fn remove(&self, nodeid: &str) -> bool {
        let mut g = lock(&self.inner);
        g.touched.insert(nodeid.to_string());
        g.store.remove(nodeid)
    }

    /// Paths written by earlier sessions: `{path: [writer contexts]}`.
    fn written(&self) -> BTreeMap<String, Vec<String>> {
        lock(&self.inner).store.written.iter().map(|(k, v)| (k.clone(), v.iter().cloned().collect())).collect()
    }

    /// Note paths this session wrote and their writer contexts.
    fn add_written(&self, written: BTreeMap<String, Vec<String>>) {
        let mut g = lock(&self.inner);
        for (p, w) in written {
            g.store.written.entry(p).or_default().extend(w);
        }
    }

    fn __len__(&self) -> usize {
        lock(&self.inner).store.tests.len()
    }

    #[getter]
    fn n_files(&self) -> usize {
        lock(&self.inner).store.files.len()
    }

    /// Merge this session's changes into the store on disk (under a lock) and write it atomically.
    fn save(&self) -> PyResult<()> {
        let g = lock(&self.inner);
        g.store.save_merged(&self.dir, &g.touched)?;
        Ok(())
    }
}

/// Digest of a file's bytes (None if unreadable).
#[pyfunction]
pub fn file_digest(path: PathBuf) -> Option<String> {
    proof::file_digest(&path)
}

/// Digest of a directory listing (sorted names joined by NUL), None if not a directory.
#[pyfunction]
pub fn listing_digest(path: PathBuf) -> Option<String> {
    proof::listing_digest(&path)
}

/// Digest of an environment variable value ("-" for None) and of a whole environment.
#[pyfunction]
#[pyo3(signature = (value))]
pub fn env_value_digest(value: Option<&str>) -> String {
    proof::env_value_digest(value)
}

#[pyfunction]
pub fn env_all_digest(env: BTreeMap<String, String>) -> String {
    proof::env_all_digest(&env)
}
