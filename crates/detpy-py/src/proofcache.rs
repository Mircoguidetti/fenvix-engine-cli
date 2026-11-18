//! Python binding of the cache with proof (`detpy._core.ProofCache`).

use detpy_core::proof::{self, Checker, CodeFile, Current, Observed, Store, Unit};
use detpy_core::record;
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};

struct Inner {
    store: Store,
    checker: Checker,
    touched: BTreeSet<String>,
    /// `store.written` as loaded: unchanged and nothing touched, saving would rewrite the same store.
    written0: BTreeMap<String, BTreeSet<String>>,
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
        let written0 = store.written.clone();
        ProofCache { dir, inner: Mutex::new(Inner { store, checker, touched: BTreeSet::new(), written0 }) }
    }

    /// Set the current session state: configuration and runtime digests, clock
    /// epoch, environment at session start.
    fn begin(&self, config: String, runtime: String, epoch: i64, env: BTreeMap<String, String>) {
        let mut g = lock(&self.inner);
        let root = g.checker.cur.root.clone();
        g.checker = Checker::new(Current { root, config, runtime, epoch, env });
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
    #[pyo3(signature = (nodeid, outcome, report_json, fingerprint, duration, run, config, runtime, epoch, env, data, content, skeleton, hooks, units))]
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
    ) -> PyResult<String> {
        let report = serde_json::from_str(report_json).map_err(|e| PyValueError::new_err(format!("report: {e}")))?;
        let mut g = lock(&self.inner);
        g.touched.insert(nodeid.to_string());
        Ok(g.store.record(
            nodeid,
            Observed { outcome, report, fingerprint, duration, run, config, runtime, epoch, env, data, content, skeleton, hooks, units },
        ))
    }

    /// Body line ranges `[(first, last)]` of the units of each file index (`None`: no facts, empty).
    fn unit_ranges(&self, indices: Vec<Option<u32>>) -> Vec<Vec<(u32, u32)>> {
        let g = lock(&self.inner);
        indices
            .into_iter()
            .map(|ix| {
                ix.and_then(|i| g.store.files.get(i as usize))
                    .map(|f| f.units.iter().map(|u| (u.a, u.b)).collect())
                    .unwrap_or_default()
            })
            .collect()
    }

    /// Record every test of the session from its capture (`plan_json`, see `detpy_core::record::Plan`).
    /// Returns `(recorded, [(nodeid, why, contexts)], [(stale nodeid, path)], global contexts)`; the store is
    /// not saved.
    #[allow(clippy::type_complexity)]
    fn record_session(
        &self,
        plan_json: &str,
    ) -> PyResult<(usize, Vec<(String, String, Vec<u32>)>, Vec<(String, String)>, Vec<u32>)> {
        let plan: record::Plan =
            serde_json::from_str(plan_json).map_err(|e| PyValueError::new_err(format!("plan: {e}")))?;
        let mut g = lock(&self.inner);
        for t in &plan.tests {
            g.touched.insert(t.nodeid.clone());
        }
        let out = record::record_session(&mut g.store, &plan);
        for (n, _) in &out.stale {
            g.touched.insert(n.clone());
        }
        Ok((out.recorded, out.not_cached, out.stale, out.global_ctx))
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
    /// Nothing to merge (no entry touched, no new written path) leaves the store on disk as it is: merging
    /// nothing into it and compacting it again would write the same content.
    fn save(&self) -> PyResult<()> {
        let g = lock(&self.inner);
        if g.touched.is_empty() && g.store.written == g.written0 {
            return Ok(());
        }
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

/// Text of a file as `pathlib.Path.read_text(encoding="utf-8")` returns it (universal newlines), `Err` when that
/// raises a decoding error, `Ok(None)` when the file cannot be read.
fn read_text_universal(path: &std::path::Path) -> Result<Option<String>, ()> {
    let Ok(raw) = std::fs::read(path) else { return Ok(None) };
    let s = String::from_utf8(raw).map_err(|_| ())?;
    if !s.contains('\r') {
        return Ok(Some(s));
    }
    Ok(Some(s.replace("\r\n", "\n").replace('\r', "\n")))
}

/// First `Name` and `Version` header values of a core-metadata text, as `email.message_from_string(...).get()`
/// gives them through `importlib.metadata`; `None` whenever the header block is not plain (folded or unusual
/// lines, a byte-order mark, a missing version): the caller then uses `importlib.metadata` itself.
fn name_version(text: &str) -> Option<(Option<String>, String)> {
    if text.starts_with('\u{feff}') || text.starts_with("From ") {
        return None;
    }
    let mut name: Option<String> = None;
    let mut version: Option<String> = None;
    let mut last: Option<String> = None;
    for line in text.split('\n') {
        if line.is_empty() {
            break;
        }
        if line.starts_with(' ') || line.starts_with('\t') {
            // continuation of the previous header: only harmless for headers we do not read
            match last.as_deref() {
                Some("name") | Some("version") | None => return None,
                _ => continue,
            }
        }
        let (h, v) = line.split_once(':')?;
        if !h.bytes().all(|b| (0x21..=0x7e).contains(&b) && b != b':') {
            return None;
        }
        let key = h.to_ascii_lowercase();
        let val = v.trim_start_matches([' ', '\t']).trim_end_matches(['\r', '\n']).to_string();
        if key == "name" && name.is_none() {
            name = Some(val);
        } else if key == "version" && version.is_none() {
            version = Some(val);
        }
        last = Some(key);
    }
    Some((name, version?))
}

/// `(name or "?", version, digest of RECORD's text)` of a `*.dist-info` / `*.egg-info` directory, read as
/// `importlib.metadata` reads it; `None` when the plain reading is not certain to match it (the caller falls
/// back to `importlib.metadata`).
#[pyfunction]
pub fn dist_identity(py: Python<'_>, path: PathBuf) -> Option<(String, String, String)> {
    py.detach(|| {
        if !path.is_dir() {
            return None;
        }
        let mut meta = None;
        for f in ["METADATA", "PKG-INFO"] {
            match read_text_universal(&path.join(f)) {
                Err(()) => return None,
                Ok(Some(t)) if !t.is_empty() => {
                    meta = Some(t);
                    break;
                }
                Ok(_) => {}
            }
        }
        let (name, version) = name_version(&meta?)?;
        let rec = read_text_universal(&path.join("RECORD")).unwrap_or(None).unwrap_or_default();
        Some((name.unwrap_or_else(|| "?".into()), version, detpy_core::fingerprint::digest_bytes(rec.as_bytes()).short()))
    })
}
