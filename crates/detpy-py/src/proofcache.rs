//! Python binding of the cache with proof (`detpy._core.ProofCache`).

use detpy_core::proof::{self, Checker, CodeFile, Current, Observed, Receipt, Store, Unit};
use pyo3::types::{PyDict, PyList, PyString};
use std::collections::HashMap;
use detpy_core::record;
use detpy_core::shared;
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
    /// Receipts of the reusable results found by `check_all` (written by `write_receipts`).
    receipts: HashMap<String, Receipt>,
    /// The last recorded session's written paths (path key -> writer contexts) and the wider-scoped fixture
    /// contexts of its tests: a parallel worker's shard (`save_shard`).
    last_written: BTreeMap<String, Vec<String>>,
    last_fixtures: BTreeMap<String, Vec<String>>,
    /// Shared store (P4): candidates fetched for this session, the documents adopted (nodeid -> address, named in
    /// the receipts), and the tests a parallel controller merged from its workers' shards (pushed after the merge).
    fetched: Option<shared::Fetched>,
    origins: BTreeMap<String, String>,
    merged_ids: Vec<String>,
    /// The last recorded session's per-test reads (`record::Outcome::reads`): a worker's shard.
    last_reads: BTreeMap<String, Vec<String>>,
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
        ProofCache { dir, inner: Mutex::new(Inner { store, checker, touched: BTreeSet::new(), written0, receipts: HashMap::new(), last_written: BTreeMap::new(), last_fixtures: BTreeMap::new(), fetched: None, origins: BTreeMap::new(), merged_ids: Vec::new(), last_reads: BTreeMap::new() }) }
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

    /// Compare recorded dependencies on `path` with `dep`, the state this session's code saw before it created the
    /// path (see `Checker::observed`).
    pub(crate) fn observed(&self, path: &str, dep: &str) {
        lock(&self.inner).checker.observed(path, dep);
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

    /// The decision of every collected test, in order (`ProofCachePlugin._decide`'s loop without its verification
    /// draw): `(True, receipt dict)` when the recorded result may be reused, else `(False, "kind: detail")`. With
    /// `max_age_s`, an entry recorded (`run_time(run id)`, Python's `_run_time`: `time.strptime`'s rules, called
    /// once per distinct run id) more than `max_age_s` before `now` is not reused (review R-009 F4):
    /// `"expired: recorded N.N days ago (--det-cache-max-age)"`.
    #[pyo3(signature = (nodeids, max_age_s, now, run_time))]
    pub(crate) fn check_all<'py>(
        &self,
        py: Python<'py>,
        nodeids: Vec<String>,
        max_age_s: Option<f64>,
        now: f64,
        run_time: Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyList>> {
        let out = PyList::empty(py);
        let mut times: HashMap<String, f64> = HashMap::new();
        let mut g = lock(&self.inner);
        for nid in nodeids {
            let r = {
                let Inner { store, checker, .. } = &mut *g;
                checker.check(store, &nid)
            };
            match r {
                Ok(r) => {
                    if let Some(max) = max_age_s {
                        let t = match times.get(&r.run) {
                            Some(t) => *t,
                            None => {
                                let t: f64 = run_time.call1((&r.run,))?.extract()?;
                                times.insert(r.run.clone(), t);
                                t
                            }
                        };
                        let age = now - t;
                        if age > max {
                            let why = format!("expired: recorded {:.1} days ago (--det-cache-max-age)", age / 86400.0);
                            out.append((false, why))?;
                            continue;
                        }
                    }
                    let d = receipt_dict(py, &r)?;
                    if let Some(o) = g.origins.get(&nid) {
                        d.set_item("origin", format!("shared:{o}"))?;
                    }
                    out.append((true, d))?;
                    g.receipts.insert(nid, r);
                }
                Err(m) => out.append((false, format!("{}: {}", m.kind, m.detail)))?,
            }
        }
        Ok(out)
    }

    /// What a reused result's reports are rebuilt from: `(entry["report"] or {}, entry["fingerprint"])`.
    fn reuse_info<'py>(&self, py: Python<'py>, nodeid: &str) -> PyResult<(Bound<'py, PyAny>, String)> {
        let g = lock(&self.inner);
        let e = g.store.tests.get(nodeid).ok_or_else(|| PyKeyError::new_err(nodeid.to_string()))?;
        let rep = value_to_py(py, &e.report)?;
        let rep = if rep.is_truthy()? { rep } else { PyDict::new(py).into_any() };
        Ok((rep, e.fingerprint.clone()))
    }

    /// Write the receipts file as `ProofCachePlugin._write_receipts` did (`json.dumps` of
    /// `{"nodeid", "reused": true, **receipt}` per hit, then `{"nodeid", "reused": false, "why"}` per miss), the
    /// hits being results `check_all` found reusable. I/O errors are ignored, as they were.
    pub(crate) fn write_receipts(&self, py: Python<'_>, path: PathBuf, hits: Vec<Bound<'_, PyString>>, misses: Vec<(Bound<'_, PyString>, Bound<'_, PyString>)>) -> PyResult<()> {
        let mut text = String::new();
        {
            let g = lock(&self.inner);
            for nid in &hits {
                let id = nid.to_cow().map(|c| c.into_owned()).unwrap_or_default();
                let Some(r) = g.receipts.get(&id) else { continue };
                text.push_str("{\"nodeid\": ");
                json_str(py, nid, &mut text)?;
                text.push_str(", \"reused\": true, ");
                receipt_json(r, &mut text);
                if let Some(o) = g.origins.get(&id) {
                    text.push_str(", \"origin\": ");
                    json_escape(&format!("shared:{o}"), &mut text);
                }
                text.push_str("}\n");
            }
        }
        for (nid, why) in &misses {
            text.push_str("{\"nodeid\": ");
            json_str(py, nid, &mut text)?;
            text.push_str(", \"reused\": false, \"why\": ");
            json_str(py, why, &mut text)?;
            text.push_str("}\n");
        }
        py.detach(|| {
            if let Some(d) = path.parent() {
                let _ = std::fs::create_dir_all(d);
            }
            let _ = std::fs::write(&path, text.as_bytes());
        });
        Ok(())
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
            Observed {
                outcome,
                report,
                fingerprint,
                duration,
                run,
                config,
                runtime,
                epoch,
                env,
                data: data.into_iter().map(|(k, v)| (k.into(), v.into())).collect(),
                content,
                skeleton,
                hooks,
                units,
                fixtures: Vec::new(),
            },
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
        g.last_written = plan.session_written.clone();
        g.last_fixtures = plan.tests.iter().map(|t| (t.nodeid.clone(), t.fixtures.clone())).collect();
        let out = record::record_session(&mut g.store, &plan);
        g.last_reads = out.reads.clone();
        for (n, _) in &out.stale {
            g.touched.insert(n.clone());
        }
        Ok((out.recorded, out.not_cached, out.stale, out.global_ctx))
    }

    /// `record_session` with the capture's part of the plan taken from `cap` (`CaptureCore.fill_plan`); `plan_json`
    /// holds the rest (tests, file indices, folded lines, configuration).
    #[allow(clippy::type_complexity)]
    fn record_captured(
        &self,
        py: Python<'_>,
        plan_json: &str,
        cap: &Bound<'_, crate::capture::CaptureCore>,
    ) -> PyResult<(usize, Vec<(String, String, Vec<u32>)>, Vec<(String, String)>, Vec<u32>)> {
        let mut plan: record::Plan =
            serde_json::from_str(plan_json).map_err(|e| PyValueError::new_err(format!("plan: {e}")))?;
        cap.get().fill_plan(py, &mut plan)?;
        let mut g = lock(&self.inner);
        for t in &plan.tests {
            g.touched.insert(t.nodeid.clone());
        }
        g.last_written = plan.session_written.clone();
        g.last_fixtures = plan.tests.iter().map(|t| (t.nodeid.clone(), t.fixtures.clone())).collect();
        let out = record::record_session(&mut g.store, &plan);
        g.last_reads = out.reads.clone();
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

    /// Together edges of the store: `[(writer test, reader test)]` (`Store::edges`).
    fn edges(&self) -> Vec<(String, String)> {
        lock(&self.inner).store.edges.iter().cloned().collect()
    }

    fn __len__(&self) -> usize {
        lock(&self.inner).store.tests.len()
    }

    // -- parallel sessions (pytest-xdist under --det) ----------------------------------------------------------------
    /// The controller of a parallel (`-n`) session: `begin` with the environment a worker of this run sees (the
    /// session's start environment plus `PYTEST_XDIST_WORKER_COUNT` = `workers` and `PYTEST_XDIST_TESTRUNUID` =
    /// `testrunuid`); results recorded by workers may be reused; `PYTEST_XDIST_WORKER` is compared after the plan
    /// (`worker_check`). Review R-023 R4, F3.
    #[pyo3(signature = (config, runtime, epoch, env, workers, testrunuid))]
    fn begin_controller(&self, config: String, runtime: String, epoch: i64, mut env: BTreeMap<String, String>, workers: usize, testrunuid: Option<String>) {
        env.insert("PYTEST_XDIST_WORKER_COUNT".into(), workers.to_string());
        if let Some(u) = testrunuid {
            env.insert("PYTEST_XDIST_TESTRUNUID".into(), u);
        }
        let mut g = lock(&self.inner);
        let root = g.checker.cur.root.clone();
        g.checker = Checker::new(Current { root, config, runtime, epoch, env });
        g.checker.parallel = true;
        g.checker.defer_worker = true;
    }

    /// A session that runs one worker's list of a parallel plan (`--det-plan-worker`): results recorded by workers
    /// may be reused, and what it records is a parallel result (after `begin`).
    fn set_parallel(&self) {
        lock(&self.inner).checker.parallel = true;
    }

    /// After the plan: the reused results that read `PYTEST_XDIST_WORKER` and that this run's plan (`assign`:
    /// nodeid -> worker of every collected test) places on another worker than the recorded one: `[(nodeid,
    /// reason)]` (`Checker::worker_check`).
    fn worker_check(&self, nodeids: Vec<String>, assign: HashMap<String, String>) -> Vec<(String, String)> {
        lock(&self.inner).checker.worker_check(&nodeids, &assign)
    }

    /// After every worker of a parallel session finished: the reused results whose input a test that comes before
    /// them in `order` (or a fixture they did not use) wrote in this session, from the writers in the workers' shards
    /// at `paths`: `[(nodeid, path key, writer)]` (`detpy_core::proof::hits_with_written_inputs`, review R-023 F2).
    fn hits_written(&self, py: Python<'_>, paths: Vec<PathBuf>, hits: Vec<String>, order: Vec<String>) -> Vec<(String, String, String)> {
        if hits.is_empty() {
            return Vec::new();
        }
        let shards: Vec<proof::Shard> = py.detach(|| paths.iter().filter_map(|p| proof::Shard::load(p).ok()).collect());
        let (written, dirs) = proof::writer_union(&shards);
        let g = lock(&self.inner);
        proof::hits_with_written_inputs(&g.store, &hits, &order, &written, &dirs)
    }

    /// After every worker of a parallel session finished: `detpy_core::proof::racy_readers` over the workers'
    /// shards at `paths`, with this run's plan (`assign`: nodeid -> worker, `waits`). `[(reader, path, [writers
    /// before it])]`.
    fn racy_readers(&self, py: Python<'_>, paths: Vec<PathBuf>, order: Vec<String>, assign: HashMap<String, String>, waits: BTreeMap<String, Vec<String>>) -> Vec<(String, String, Vec<String>, Vec<String>)> {
        let shards: Vec<proof::Shard> = py.detach(|| paths.iter().filter_map(|p| proof::Shard::load(p).ok()).collect());
        proof::racy_readers(&shards, &order, &assign, &waits)
    }

    /// Recorded durations (seconds) of `nodeids` (None: no entry): the plan's costs.
    fn durations(&self, nodeids: Vec<String>) -> Vec<Option<f64>> {
        let g = lock(&self.inner);
        nodeids.iter().map(|n| g.store.tests.get(n).map(|e| e.duration)).collect()
    }

    /// A worker's end of session: write what it recorded (and removed) as a shard at `path` instead of merging into
    /// the store; the controller merges every worker's shard once (`merge_shards`).
    fn save_shard(&self, py: Python<'_>, path: PathBuf, worker: String) -> PyResult<usize> {
        let g = lock(&self.inner);
        let mut sub = Store::new();
        g.store.merge_into(&mut sub, &g.touched);
        // a worker's results are parallel results: a serial session does not reuse them (review R-023 F1)
        for e in sub.tests.values_mut() {
            e.placement = proof::PLACEMENT_PARALLEL.to_string();
        }
        // persisted for the next sessions (as record_session keeps them)
        sub.written = g
            .last_written
            .iter()
            .filter(|(k, _)| proof::persist_written(k))
            .map(|(k, v)| (k.clone(), v.iter().cloned().collect()))
            .collect();
        let n = sub.tests.len();
        let shard = proof::Shard {
            format: proof::SHARD_FORMAT.into(),
            version: proof::SHARD_VERSION,
            worker,
            store: sub,
            touched: g.touched.iter().cloned().collect(),
            fixtures: g.last_fixtures.clone(),
            written: g.last_written.clone(),
            reads: g.last_reads.clone(),
        };
        drop(g);
        py.detach(|| shard.save(&path))?;
        Ok(n)
    }

    /// The controller's end of a parallel session: the cross-worker write rule over the shards at `paths`, then one
    /// merge into the store (`detpy_core::proof::merge_shards`). Returns JSON: `merged`, `dropped` [[nodeid, why]],
    /// `stale` [[nodeid, path]], `unreadable` [path].
    #[pyo3(signature = (paths, hits, edges=Vec::new()))]
    fn merge_shards(&self, py: Python<'_>, paths: Vec<PathBuf>, hits: Vec<String>, edges: Vec<(String, String)>) -> PyResult<String> {
        let dir = self.dir.clone();
        let (merge, unreadable) = py.detach(|| -> std::io::Result<_> {
            let mut shards = Vec::new();
            let mut unreadable = Vec::new();
            for p in &paths {
                match proof::Shard::load(p) {
                    Ok(s) => shards.push(s),
                    Err(_) => unreadable.push(p.display().to_string()),
                }
            }
            let ids: Vec<String> = shards.iter().flat_map(|s| s.touched.iter().cloned()).collect();
            Ok((proof::merge_shards_with(&dir, &mut shards, &hits, &edges)?, unreadable, ids))
        })
        .map(|(m, u, ids)| {
            lock(&self.inner).merged_ids = ids;
            (m, u)
        })?;
        serde_json::to_string(&serde_json::json!({
            "merged": merge.merged, "dropped": merge.dropped, "stale": merge.stale, "unreadable": unreadable,
            "edges": merge.edges, "proven": merge.proven, "diverged": merge.diverged, "unproven": merge.unproven,
        }))
        .map_err(|e| PyValueError::new_err(e.to_string()))
    }

    // -- shared store (P4) -----------------------------------------------------------------------------------------
    /// Fetch up to `limit` candidates per test from the shared store `shared` (`detpy_core::shared::fetch`) and add
    /// their file facts to the store, before the changed code files are listed (so their facts are compared too).
    /// Returns `(tests with candidates, candidates, [(nodeid, document, kind, detail)] rejected, torn log lines)`.
    #[allow(clippy::type_complexity)]
    fn shared_fetch(&self, py: Python<'_>, shared: PathBuf, nodeids: Vec<String>, limit: usize) -> (usize, usize, Vec<(String, String, String, String)>, usize) {
        let mut g = lock(&self.inner);
        let (config, runtime) = (g.checker.cur.config.clone(), g.checker.cur.runtime.clone());
        let dir = shared::SharedDir::new(shared);
        let store = &mut g.store;
        let f = py.detach(|| shared::fetch(&dir, store, &nodeids, &config, &runtime, limit.max(1)));
        let rejected = f.rejected.iter().map(|(n, d, r)| (n.clone(), d.clone(), r.kind().to_string(), r.detail().to_string())).collect();
        let out = (f.candidates.len(), f.candidates.values().map(|v| v.len()).sum(), rejected, f.log.torn);
        g.fetched = Some(f);
        out
    }

    /// Adopt the fetched candidates the checker accepts where the local entry is not accepted
    /// (`detpy_core::shared::adopt`). Returns `{nodeid: document}`. An adopted entry is kept in the local store (the
    /// local mirror), and is not pushed back.
    fn shared_adopt(&self) -> BTreeMap<String, String> {
        let mut g = lock(&self.inner);
        let Some(f) = g.fetched.take() else { return BTreeMap::new() };
        let Inner { store, checker, .. } = &mut *g;
        let adopted = shared::adopt(store, &f, &mut |s, nid| checker.check(s, nid).is_ok());
        // the checker's memo tables hold per set, file and variable results, valid for the decision that follows;
        // the deferred worker reads of the candidates tried are not (check_all records them again for its hits)
        checker.worker_reads.clear();
        for (nid, doc) in &adopted {
            g.touched.insert(nid.clone());
            g.origins.insert(nid.clone(), doc.clone());
        }
        adopted
    }

    /// Push this session's recorded entries to the shared store (`SharedDir::push`): the tests recorded here, or,
    /// in a parallel controller, the tests its workers recorded (after `merge_shards`); adopted results are not
    /// pushed back. Then the receipts file as a document and a run line. Returns `(entries, documents)`.
    #[pyo3(signature = (shared, receipts=None, run="".to_string()))]
    fn shared_push(&self, py: Python<'_>, shared: PathBuf, receipts: Option<PathBuf>, run: String) -> PyResult<(usize, usize)> {
        let (store, ids) = {
            let g = lock(&self.inner);
            if g.merged_ids.is_empty() {
                let ids: Vec<String> =
                    g.touched.iter().filter(|n| !g.origins.contains_key(*n) && g.store.tests.contains_key(*n)).cloned().collect();
                (None, ids)
            } else {
                (Some(()), g.merged_ids.iter().filter(|n| !g.origins.contains_key(*n)).cloned().collect())
            }
        };
        let dir = shared::SharedDir::new(shared);
        let r = if store.is_some() {
            let disk = Store::load(&self.dir);
            py.detach(|| dir.push(&disk, &ids))
        } else {
            let g = lock(&self.inner);
            let store = &g.store;
            py.detach(|| dir.push(store, &ids))
        }?;
        if let Some(p) = receipts {
            if let Ok(b) = std::fs::read(&p) {
                let id = dir.put(&b)?;
                dir.append_run(&run, &id, &serde_json::json!({"entries": r.0}))?;
            }
        }
        Ok(r)
    }

    #[getter]
    fn n_files(&self) -> usize {
        lock(&self.inner).store.files.len()
    }

    /// Merge this session's changes into the store on disk (under a lock) and write it atomically.
    /// Nothing to merge (no entry touched, no new written path) leaves the store on disk as it is: merging
    /// nothing into it and compacting it again would write the same content.
    fn save(&self) -> PyResult<()> {
        let mut g = lock(&self.inner);
        if g.touched.is_empty() && g.store.written == g.written0 {
            return Ok(());
        }
        if g.checker.parallel {
            // one worker's list of a parallel plan (`--det-plan-worker`): parallel results (review R-023 F1)
            let Inner { store, touched, .. } = &mut *g;
            for nid in touched.iter() {
                if let Some(e) = store.tests.get_mut(nid) {
                    e.placement = proof::PLACEMENT_PARALLEL.to_string();
                }
            }
        }
        g.store.save_merged(&self.dir, &g.touched)?;
        Ok(())
    }
}

impl ProofCache {
    /// The recorded data inputs and fixture contexts of `nodeid`'s entry, with the check `foreign` needs.
    pub(crate) fn with_entry<T>(&self, nodeid: &str, f: impl FnOnce(&proof::Entry) -> T) -> Option<T> {
        let g = lock(&self.inner);
        g.store.tests.get(nodeid).map(f)
    }

    /// Record every test of the session from `plan`, its capture part filled from `cap` (`CaptureCore.fill_plan`);
    /// the store is not saved (`CacheSession.record`).
    pub(crate) fn record_plan(&self, py: Python<'_>, mut plan: record::Plan, cap: &Bound<'_, crate::capture::CaptureCore>) -> PyResult<record::Outcome> {
        cap.get().fill_plan(py, &mut plan)?;
        let mut g = lock(&self.inner);
        for t in &plan.tests {
            g.touched.insert(t.nodeid.clone());
        }
        g.last_written = plan.session_written.clone();
        g.last_fixtures = plan.tests.iter().map(|t| (t.nodeid.clone(), t.fixtures.clone())).collect();
        let out = record::record_session(&mut g.store, &plan);
        g.last_reads = out.reads.clone();
        for (n, _) in &out.stale {
            g.touched.insert(n.clone());
        }
        Ok(out)
    }
}

/// `repr(float)` (Python's shortest round-trip form: fixed notation for decimal exponents -4..16, else `1e-05`).
pub fn py_float_repr(x: f64) -> String {
    if x.is_nan() {
        return "NaN".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity".into() } else { "-Infinity".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    // the fewest digits that round-trip (Rust's shortest form), correctly rounded with ties to even as Python's
    // dtoa does (Rust's shortest form breaks a tie upwards: 942816266129506.25 -> ...506.3, Python ...506.2)
    let short = format!("{x:e}");
    let n = short.split_once('e').unwrap().0.chars().filter(|c| c.is_ascii_digit()).count();
    let exact = format!("{:.*e}", n.saturating_sub(1), x);
    let e = if exact.parse::<f64>().ok() == Some(x) { exact } else { short };
    let (mant, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let neg = mant.starts_with('-');
    let digits: String = mant.chars().filter(|c| c.is_ascii_digit()).collect();
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if (-4..16).contains(&exp) {
        if exp < 0 {
            out.push_str("0.");
            out.push_str(&"0".repeat((-exp - 1) as usize));
            out.push_str(&digits);
        } else {
            let k = exp as usize + 1;
            if digits.len() <= k {
                out.push_str(&digits);
                out.push_str(&"0".repeat(k - digits.len()));
                out.push_str(".0");
            } else {
                out.push_str(&digits[..k]);
                out.push('.');
                out.push_str(&digits[k..]);
            }
        }
    } else {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push_str(&format!("e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs()));
    }
    out
}

/// `json.dumps(s)` (ensure_ascii) of a UTF-8 string, appended to `out`.
pub fn json_escape(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", u));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// `json.dumps` of a Python `str` (lone surrogates included, through Python itself).
fn json_str(py: Python<'_>, s: &Bound<'_, PyString>, out: &mut String) -> PyResult<()> {
    match s.to_cow() {
        Ok(t) => json_escape(&t, out),
        Err(_) => {
            let d = py.import("json")?.getattr("dumps")?.call1((s,))?;
            out.push_str(&d.cast::<PyString>()?.to_cow()?);
        }
    }
    Ok(())
}

/// The receipt's fields as `json.dumps` writes the dict `check_all` returns (without braces).
fn receipt_json(r: &Receipt, out: &mut String) {
    let mut f = |k: &str, v: String| {
        if !out.ends_with(' ') {
            out.push_str(", ");
        }
        out.push('"');
        out.push_str(k);
        out.push_str("\": ");
        out.push_str(&v);
    };
    let s = |x: &str| {
        let mut t = String::new();
        json_escape(x, &mut t);
        t
    };
    f("key", s(&r.key));
    f("run", s(&r.run));
    f("outcome", s(&r.outcome));
    f("fingerprint", s(&r.fingerprint));
    f("duration", py_float_repr(r.duration));
    f("config", s(&r.config));
    f("runtime", s(&r.runtime));
    f("epoch", r.epoch.map(|e| e.to_string()).unwrap_or_else(|| "null".into()));
    f("n_units", r.n_units.to_string());
    f("n_skeleton", r.n_skeleton.to_string());
    f("n_hooks", r.n_hooks.to_string());
    f("n_content", r.n_content.to_string());
    f("n_data", r.n_data.to_string());
    f("n_env", r.n_env.to_string());
    f("n_changed_files_proven", r.n_changed_files_proven.to_string());
}

/// The receipt as the dict `json.loads(serde_json::to_string(receipt))` gave.
fn receipt_dict<'py>(py: Python<'py>, r: &Receipt) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("key", &r.key)?;
    d.set_item("run", &r.run)?;
    d.set_item("outcome", &r.outcome)?;
    d.set_item("fingerprint", &r.fingerprint)?;
    d.set_item("duration", r.duration)?;
    d.set_item("config", &r.config)?;
    d.set_item("runtime", &r.runtime)?;
    d.set_item("epoch", r.epoch)?;
    d.set_item("n_units", r.n_units)?;
    d.set_item("n_skeleton", r.n_skeleton)?;
    d.set_item("n_hooks", r.n_hooks)?;
    d.set_item("n_content", r.n_content)?;
    d.set_item("n_data", r.n_data)?;
    d.set_item("n_env", r.n_env)?;
    d.set_item("n_changed_files_proven", r.n_changed_files_proven)?;
    Ok(d)
}

/// A JSON value as `json.loads` gives it.
pub(crate) fn value_to_py<'py>(py: Python<'py>, v: &serde_json::Value) -> PyResult<Bound<'py, PyAny>> {
    use pyo3::IntoPyObjectExt;
    Ok(match v {
        serde_json::Value::Null => py.None().into_bound(py),
        serde_json::Value::Bool(b) => b.into_bound_py_any(py)?,
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.into_bound_py_any(py)?
            } else if let Some(u) = n.as_u64() {
                u.into_bound_py_any(py)?
            } else {
                n.as_f64().unwrap_or(f64::NAN).into_bound_py_any(py)?
            }
        }
        serde_json::Value::String(s) => PyString::new(py, s).into_any(),
        serde_json::Value::Array(a) => {
            let l = PyList::empty(py);
            for x in a {
                l.append(value_to_py(py, x)?)?;
            }
            l.into_any()
        }
        serde_json::Value::Object(o) => {
            let d = PyDict::new(py);
            for (k, x) in o {
                d.set_item(k, value_to_py(py, x)?)?;
            }
            d.into_any()
        }
    })
}

/// `repr(x)` / `json.dumps(s)` as Rust computes them (for the tests).
#[pyfunction]
pub fn py_repr_float(x: f64) -> String {
    py_float_repr(x)
}

#[pyfunction]
pub fn json_dumps_str(s: &str) -> String {
    let mut o = String::new();
    json_escape(s, &mut o);
    o
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

/// "file", "dir", "other" or "missing" (`detpy_core::proof::stat_kind`, follows symlinks).
#[pyfunction]
pub fn stat_kind(path: PathBuf) -> &'static str {
    proof::stat_kind(&path)
}

/// Paths the import system probes for module `name` in directory `dir` (`detpy_core::proof::import_candidates`).
#[pyfunction]
pub fn import_candidates(dir: &str, name: &str, suffixes: Vec<String>) -> Vec<String> {
    proof::import_candidates(dir, name, &suffixes)
}

/// `conftest.py` and `__init__.py` paths pytest looks for from the root down to `rel_dir`
/// (`detpy_core::proof::collection_candidates`).
#[pyfunction]
pub fn collection_candidates(rel_dir: &str) -> Vec<String> {
    proof::collection_candidates(rel_dir)
}

/// Installed files of the Python distributions (`--det-cache-dists`): see `detpy_core::distfiles`.
#[pyclass(module = "detpy._core")]
pub struct DistFiles {
    inner: detpy_core::distfiles::DistFiles,
}

#[pymethods]
impl DistFiles {
    #[new]
    fn new() -> Self {
        DistFiles { inner: detpy_core::distfiles::DistFiles::new() }
    }

    fn add(&mut self, owner: &str, base: &str, record: &str, project: bool) {
        self.inner.add(owner, base, record, project)
    }

    fn add_project_path(&mut self, path: &str) {
        self.inner.add_project_path(path)
    }

    /// (owners, claim group or None) of `path`, None when no RECORD explains it.
    fn lookup(&self, path: &str) -> Option<(Vec<String>, Option<String>)> {
        self.inner.lookup(path)
    }

    fn tops(&self) -> Vec<(String, Vec<String>)> {
        self.inner.tops()
    }

    fn claims(&self) -> Vec<(String, String)> {
        self.inner.claims()
    }
}

/// Top-level module name a RECORD path provides (None for metadata, scripts, data).
#[pyfunction]
pub fn dist_top_of(rel: &str) -> Option<String> {
    detpy_core::distfiles::top_of(rel)
}

/// Dependency string of an existence check of `path`: "s:<kind>" (kind "missing" included).
#[pyfunction]
pub fn stat_dep(path: PathBuf) -> String {
    detpy_core::distfiles::stat_dep(&path)
}

/// Existence checks of at least `min` entries of one directory replaced by the directory's listing with kinds, many
/// under one directory tree by the tree with kinds (`proof::compact_stats`; what `record_session` does to each
/// test's data, exposed for the equivalence tests' reference).
#[pyfunction]
pub fn compact_stats(data: Vec<(String, String)>, root: PathBuf, min: usize) -> Vec<(String, String)> {
    proof::compact_stats(data, &root, min)
}

/// Kind of `path` without following a final symlink ("link", or `stat_kind`'s kinds).
#[pyfunction]
pub fn lstat_kind(path: PathBuf) -> &'static str {
    proof::lstat_kind(&path)
}

/// Dependency on the importable entries of `dir` ("i:<digest>" or "i:missing").
#[pyfunction]
pub fn importable_dep(dir: PathBuf) -> String {
    proof::importable_digest(&dir).map(|d| format!("i:{d}")).unwrap_or_else(|| "i:missing".into())
}

/// (a regular module or package found, the package directory exists) for module `name` in `dir`.
#[pyfunction]
pub fn import_probe(dir: &str, name: &str, suffixes: Vec<String>) -> (bool, bool) {
    proof::import_probe(dir, name, &suffixes)
}
