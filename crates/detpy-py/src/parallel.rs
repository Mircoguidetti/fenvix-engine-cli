//! Parallel `--det` (pytest-xdist under a fixed plan): bindings of `detpy_core::schedule` (the plan) and
//! `detpy_core::trace::merge_traces` (the controller's merge of the workers' traces). The xdist glue that calls
//! them is `python/detpy/xdist.py`.

use detpy_core::schedule::{self, DistMode, PlanInput};
use detpy_core::trace::{self, WorkerTrace};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use std::collections::BTreeMap;
use std::path::PathBuf;

fn json_err(e: serde_json::Error) -> PyErr {
    PyRuntimeError::new_err(e.to_string())
}

/// Atom key of a test under the `--dist` mode `mode` (None: a mode the planner does not support, e.g. `each`).
#[pyfunction]
#[pyo3(signature = (nodeid, mode, group = None))]
fn sched_atom_key(nodeid: &str, mode: &str, group: Option<&str>) -> Option<String> {
    DistMode::parse(mode).map(|m| schedule::atom_key(nodeid, m, group))
}

/// Cost of a test from its recorded durations (median of the last 3), None when there is none.
#[pyfunction]
fn sched_cost_of(history: Vec<f64>) -> Option<f64> {
    schedule::cost_of(&history)
}

/// The fixed plan (`detpy_core::schedule::plan`) as JSON: `lists` (positions per worker, serial order),
/// `atom_worker`, `loads`, `makespan`, `lpt_makespan`, `sticky`, `kept`, `digest`.
#[pyfunction]
#[pyo3(signature = (ids, atoms, costs, workers, previous, tolerance = 0.10, slack = 1.0))]
fn sched_plan(
    py: Python<'_>,
    ids: Vec<String>,
    atoms: Vec<String>,
    costs: Vec<Option<f64>>,
    workers: usize,
    previous: BTreeMap<String, usize>,
    tolerance: f64,
    slack: f64,
) -> PyResult<String> {
    let input = PlanInput { ids, atoms, costs, workers, previous, tolerance, slack };
    let p = py.detach(|| schedule::plan(&input)).map_err(PyValueError::new_err)?;
    serde_json::to_string(&serde_json::json!({
        "lists": p.lists,
        "atom_worker": p.atom_worker,
        "loads": p.loads,
        "makespan": p.makespan,
        "lpt_makespan": p.lpt_makespan,
        "sticky": p.sticky,
        "kept": p.kept,
        "digest": p.digest,
    }))
    .map_err(json_err)
}

/// Digest of a plan given as per-worker id lists.
#[pyfunction]
fn sched_plan_digest(lists: Vec<Vec<String>>) -> String {
    schedule::plan_digest(&lists)
}

/// Merge the workers' traces into `out` (`detpy_core::trace::merge_traces`); returns the summary as JSON:
/// `n_tests`, `missing`, `unreadable`, `duplicates`, `tests` = [[nodeid, fingerprint, outcome, worker], ...].
#[pyfunction]
#[pyo3(signature = (order, workers, meta_json, plan_digest, out))]
fn merge_traces(
    py: Python<'_>,
    order: Vec<String>,
    workers: Vec<(String, PathBuf, Vec<String>)>,
    meta_json: &str,
    plan_digest: Option<String>,
    out: PathBuf,
) -> PyResult<String> {
    let meta: serde_json::Value = serde_json::from_str(meta_json).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let ws: Vec<WorkerTrace> =
        workers.into_iter().map(|(worker, path, planned)| WorkerTrace { worker, path, planned }).collect();
    let s = py.detach(|| trace::merge_traces(&order, &ws, meta, plan_digest, &out)).map_err(crate::trace_err)?;
    serde_json::to_string(&serde_json::json!({
        "n_tests": s.n_tests,
        "missing": s.missing,
        "unreadable": s.unreadable,
        "duplicates": s.duplicates,
        "tests": s.tests,
    }))
    .map_err(json_err)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sched_atom_key, m)?)?;
    m.add_function(wrap_pyfunction!(sched_cost_of, m)?)?;
    m.add_function(wrap_pyfunction!(sched_plan, m)?)?;
    m.add_function(wrap_pyfunction!(sched_plan_digest, m)?)?;
    m.add_function(wrap_pyfunction!(merge_traces, m)?)?;
    Ok(())
}
