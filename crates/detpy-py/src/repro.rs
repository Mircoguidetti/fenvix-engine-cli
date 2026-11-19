//! `detpy repro` / `detpy explore` (`detpy/repro.py`): bindings of `detpy_core::repro`.
//!
//! Python keeps the process orchestration (the `Runner`: pytest command lines, subprocesses, outcome files; the
//! bundle files; argument parsing and printing). Every decision is here or in the core: the search, ddmin, the
//! replay verdicts, the divergence, the bundle dict (in the original's key order: `bundle.json` is the same file),
//! the texts printed, and `explore`'s seed/budget bookkeeping ([`ExploreBook`]).
//!
//! The Python original is kept verbatim in `tests/rust_hotpaths_ref/_ref_repro.py`.

use detpy_core::repro::{self as core, Driver, Repro, ReproError, ReproParams, Verdict, FIXED};
use pyo3::exceptions::{PyException, PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyInt, PyList, PyString};
use std::collections::HashSet;
use std::path::PathBuf;
use std::time::Instant;

pyo3::create_exception!(detpy._core, ReproOutOfRuns, PyException, "The run budget of `detpy repro` ran out.");

/// `isinstance(outcome, str) and ("failed" in outcome or "error" in outcome)`.
fn fails(outcome: &Bound<'_, PyAny>) -> PyResult<bool> {
    match outcome.cast::<PyString>() {
        Ok(s) => Ok(core::is_fail(&s.to_cow()?)),
        Err(_) => Ok(false),
    }
}

fn verdict_of(outcome: &Bound<'_, PyAny>) -> PyResult<Verdict> {
    if fails(outcome)? {
        Ok(Verdict::Fail)
    } else if outcome.eq("passed")? {
        Ok(Verdict::Passed)
    } else {
        Ok(Verdict::Other)
    }
}

#[pyfunction]
fn repro_is_fail(outcome: &Bound<'_, PyAny>) -> PyResult<bool> {
    fails(outcome)
}

/// `Run.outcome`: `outcomes.get(nodeid, "missing")`.
#[pyfunction]
fn repro_outcome<'py>(outcomes: &Bound<'py, PyAny>, nodeid: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    outcomes.call_method1("get", (nodeid, "missing"))
}

fn not_in_list(py: Python<'_>, target: &str) -> PyErr {
    let r = PyString::new(py, target).repr().map(|r| r.to_string()).unwrap_or_else(|_| format!("{target:?}"));
    PyValueError::new_err(format!("{r} is not in list"))
}

#[pyfunction]
fn repro_prefix_through(py: Python<'_>, order: Vec<String>, target: String) -> PyResult<Vec<String>> {
    core::prefix_through(&order, &target).ok_or_else(|| not_in_list(py, &target))
}

/// `order_for`: the collection order for `fixed`, else its shuffle under `int(config)`.
#[pyfunction]
fn repro_order_for(py: Python<'_>, collected: Vec<String>, config: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
    if config.eq(FIXED)? {
        return Ok(core::order_for(&collected, None));
    }
    let seed: u64 = py.get_type::<PyInt>().call1((config,))?.extract()?;
    Ok(core::order_for(&collected, Some(seed)))
}

/// `ddmin(items, still_fails)`: the predicate gets a new list at each call; its exception stops the search.
#[pyfunction]
fn repro_ddmin<'py>(
    py: Python<'py>,
    items: Vec<Bound<'py, PyAny>>,
    still_fails: Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyList>> {
    let got = core::ddmin(items, |sub| still_fails.call1((PyList::new(py, sub)?,))?.is_truthy())?;
    PyList::new(py, got)
}

#[pyfunction]
fn repro_slug(nodeid: &str) -> String {
    core::slug(nodeid)
}

fn json_loads<'py>(py: Python<'py>, s: &str) -> PyResult<Bound<'py, PyAny>> {
    py.import("json")?.getattr("loads")?.call1((s,))
}

/// `_divergence` on trace paths: the kept fields of the first diverging event (a dict), `{"error": repr(exc)}` for
/// an unreadable trace, None without a passing trace or when the test ran in neither.
#[pyfunction]
#[pyo3(signature = (pass_trace, fail_trace, nodeid))]
fn repro_divergence<'py>(
    py: Python<'py>,
    pass_trace: Option<PathBuf>,
    fail_trace: PathBuf,
    nodeid: &str,
) -> PyResult<Bound<'py, PyAny>> {
    match core::divergence(pass_trace.as_deref(), &fail_trace, nodeid) {
        Ok(None) => Ok(py.None().into_bound(py)),
        Ok(Some(k)) => {
            let text = serde_json::to_string(&k).map_err(|e| PyValueError::new_err(e.to_string()))?;
            json_loads(py, &text)
        }
        Err(e) => {
            let d = PyDict::new(py);
            d.set_item("error", crate::trace_err(e).value(py).repr()?)?;
            Ok(d.into_any())
        }
    }
}

/// The Python `Runner` as the core's driver.
struct PyDriver<'py> {
    py: Python<'py>,
    runner: Bound<'py, PyAny>,
}

impl<'py> Driver for PyDriver<'py> {
    type Run = Bound<'py, PyAny>;
    type Err = PyErr;

    fn order_of(&mut self, config: &str) -> PyResult<Vec<String>> {
        self.runner.call_method1("order_of", (config,))?.extract()
    }

    fn run(&mut self, config: &str, order: &[String], tag: &str) -> PyResult<Self::Run> {
        self.runner.call_method1("run", (config, PyList::new(self.py, order)?, tag))
    }

    fn verdict(&mut self, run: &Self::Run, nodeid: &str) -> PyResult<Verdict> {
        verdict_of(&run.call_method1("outcome", (nodeid,))?)
    }

    fn fingerprint(&mut self, run: &Self::Run, nodeid: &str) -> PyResult<Option<String>> {
        run.getattr("fingerprints")?.call_method1("get", (nodeid,))?.extract()
    }
}

fn repro_err(py: Python<'_>, e: ReproError<PyErr>) -> PyErr {
    match e {
        ReproError::Driver(e) => e,
        ReproError::OutOfRuns => ReproOutOfRuns::new_err(()),
        ReproError::NotInList(t) => not_in_list(py, &t),
        ReproError::NoReplays => PyIndexError::new_err("list index out of range"),
    }
}

fn elapsed_2(t: Instant) -> f64 {
    core::py_round(t.elapsed().as_secs_f64(), 2)
}

/// (result, first replay's trace, passing run's trace).
type ReproOut<'py> = (Bound<'py, PyDict>, Option<Bound<'py, PyAny>>, Option<Bound<'py, PyAny>>);

/// `reproduce` up to the bundle files: returns `(result, fail_trace, pass_trace)`, the traces of the first replay and
/// of the passing run (None when the search or the minimisation stopped first).
#[pyfunction]
#[pyo3(signature = (runner, target, collected, seeds, known_fail, known_pass, confirm, max_runs))]
#[allow(clippy::too_many_arguments)]
fn repro_reproduce<'py>(
    py: Python<'py>,
    runner: Bound<'py, PyAny>,
    target: String,
    collected: Option<Vec<String>>,
    seeds: i64,
    known_fail: Option<String>,
    known_pass: Option<Vec<String>>,
    confirm: i64,
    max_runs: i64,
) -> PyResult<ReproOut<'py>> {
    let t_start = Instant::now();
    let runs_at_start: i64 = runner.getattr("runs")?.extract()?;
    let mut d = PyDriver { py, runner: runner.clone() };
    let collected = match collected {
        Some(c) => c,
        None => d.order_of(FIXED)?,
    };
    let known_pass = known_pass.unwrap_or_default();
    let p = ReproParams {
        target: &target,
        collected: &collected,
        seeds,
        known_fail: known_fail.as_deref(),
        known_pass: &known_pass,
        confirm,
        max_runs,
    };
    let out = core::reproduce(&mut d, &p).map_err(|e| repro_err(py, e))?;
    let result = PyDict::new(py);
    result.set_item("test", &target)?;
    let runs_done = || -> PyResult<i64> { Ok(runner.getattr("runs")?.extract::<i64>()? - runs_at_start) };
    let (searched, b) = match out {
        Repro::NotCollected => {
            result.set_item("status", "not-collected")?;
            return Ok((result, None, None));
        }
        Repro::NotFound { searched } => {
            result.set_item("configs_searched", searched)?;
            result.set_item("status", "not-found")?;
            result.set_item("runs", runs_done()?)?;
            result.set_item("seconds", elapsed_2(t_start))?;
            return Ok((result, None, None));
        }
        Repro::NotMinimised { searched, config, prefix_length } => {
            result.set_item("configs_searched", searched)?;
            result.set_item("status", "not-minimised")?;
            result.set_item("config", config)?;
            result.set_item("prefix_length", prefix_length)?;
            result.set_item("runs", runs_done()?)?;
            result.set_item("seconds", elapsed_2(t_start))?;
            return Ok((result, None, None));
        }
        Repro::Bundle { searched, bundle } => (searched, bundle),
    };
    result.set_item("configs_searched", searched)?;
    let first = &b.replays[0];
    let fail_trace = first.getattr("trace")?;
    let pass_trace = match &b.pass_run {
        Some(r) => Some(r.getattr("trace")?),
        None => None,
    };
    let div = repro_divergence(
        py,
        pass_trace.as_ref().map(|t| t.extract::<PathBuf>()).transpose()?,
        fail_trace.extract()?,
        &target,
    )?;
    result.set_item("status", b.status)?;
    result.set_item("config", &b.config)?;
    let seed = if b.config == FIXED { py.None().into_bound(py) } else { py.get_type::<PyInt>().call1((&b.config,))? };
    result.set_item("seed", seed)?;
    result.set_item("kind", b.kind)?;
    result.set_item("prefix_length", b.prefix_length)?;
    result.set_item("minimal_length", b.order.len())?;
    result.set_item("polluters", &b.polluters)?;
    result.set_item("setters", &b.setters)?;
    result.set_item("order", &b.order)?;
    result.set_item("outcome", first.call_method1("outcome", (&target,))?)?;
    result.set_item("exception", first.getattr("exceptions")?.call_method1("get", (&target,))?)?;
    let replay = PyDict::new(py);
    replay.set_item("runs", confirm)?;
    replay.set_item("fails", b.fails)?;
    replay.set_item("fingerprints", &b.fingerprints)?;
    replay.set_item("identical_fingerprint", b.identical)?;
    result.set_item("replay", replay)?;
    result.set_item("divergence", div)?;
    result.set_item("runs", runs_done()?)?;
    result.set_item("seconds", elapsed_2(t_start))?;
    result.set_item("controls", first.getattr("meta")?.call_method1("get", ("controls",))?)?;
    result.set_item("detpy", py.import("detpy")?.getattr("__version__")?)?;
    let sys = py.import("sys")?;
    let python = runner.getattr("python")?;
    let python = if python.eq(sys.getattr("executable")?)? {
        sys.getattr("version")?.call_method0("split")?.get_item(0)?
    } else {
        python
    };
    result.set_item("python", python)?;
    Ok((result, Some(fail_trace), pass_trace))
}

/// The bundle's command lines: `{"command", "replay_command", "pytest_args", "bundle"}`.
#[pyfunction]
fn repro_bundle_commands<'py>(py: Python<'py>, config: &str, bundle: &str, args: Vec<String>) -> PyResult<Bound<'py, PyDict>> {
    let (command, replay_command) = core::bundle_commands(config, &format!("{bundle}/order.txt"), bundle, &args);
    let d = PyDict::new(py);
    d.set_item("command", command)?;
    d.set_item("replay_command", replay_command)?;
    d.set_item("pytest_args", args)?;
    d.set_item("bundle", bundle)?;
    Ok(d)
}

/// `replay`'s verdict on the runs of a bundle.
#[pyfunction]
fn repro_replay_verdict<'py>(
    py: Python<'py>,
    data: &Bound<'py, PyAny>,
    runs: Vec<Bound<'py, PyAny>>,
    n: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyDict>> {
    let target = data.get_item("test")?;
    let mut fps = std::collections::BTreeSet::new();
    for r in &runs {
        fps.insert(r.getattr("fingerprints")?.call_method1("get", (&target,))?.extract::<Option<String>>()?);
    }
    let mut failed = 0usize;
    for r in &runs {
        if fails(&r.call_method1("outcome", (&target,))?)? {
            failed += 1;
        }
    }
    let empty = PyDict::new(py);
    let bundle: HashSet<Option<String>> = data
        .call_method1("get", ("replay", empty))?
        .call_method1("get", ("fingerprints", PyList::empty(py)))?
        .extract::<Vec<Option<String>>>()?
        .into_iter()
        .collect();
    let has_none = fps.contains(&None);
    let out = PyDict::new(py);
    out.set_item("test", target)?;
    out.set_item("runs", n)?;
    out.set_item("fails", failed)?;
    out.set_item("identical_fingerprint", fps.len() == 1 && !has_none)?;
    out.set_item("matches_bundle", fps.iter().all(|f| bundle.contains(f)) && !has_none)?;
    Ok(out)
}

fn text(x: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(x.str()?.to_cow()?.into_owned())
}

/// `b.get(key)`.
fn get<'py>(b: &Bound<'py, PyAny>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    b.call_method1("get", (key,))
}

fn names(x: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
    if x.is_truthy()? {
        x.try_iter()?.map(|n| n?.extract::<String>()).collect()
    } else {
        Ok(Vec::new())
    }
}

fn bundle_view(b: &Bound<'_, PyAny>) -> PyResult<core::BundleView> {
    let py = b.py();
    let status = get(b, "status")?;
    let mut v = core::BundleView {
        test: text(&b.get_item("test")?)?,
        status: text(&b.get_item("status")?)?,
        ..Default::default()
    };
    if status.eq("reproduced")? || status.eq("replay-unstable")? {
        let config = b.get_item("config")?;
        let fixed = config.eq(FIXED)?;
        let mut d = core::BundleDetail {
            fixed,
            config: if fixed { String::new() } else { text(&config)? },
            prefix_length: text(&b.get_item("prefix_length")?)?,
            minimal_length: text(&b.get_item("minimal_length")?)?,
            polluters: names(&get(b, "polluters")?)?,
            setters: names(&get(b, "setters")?)?,
            fails_alone: get(b, "kind")?.eq("fails-alone")?,
            ..Default::default()
        };
        let rp = b.get_item("replay")?;
        d.replay_fails = text(&rp.get_item("fails")?)?;
        d.replay_runs = text(&rp.get_item("runs")?)?;
        d.identical = text(&rp.get_item("identical_fingerprint")?)?;
        let mut div = get(b, "divergence")?;
        if !div.is_truthy()? {
            div = PyDict::new(py).into_any();
        }
        if get(&div, "description")?.is_truthy()? {
            d.divergence = Some((text(&get(&div, "reason")?)?, text(&get(&div, "description")?)?));
        }
        if get(b, "command")?.is_truthy()? {
            d.command = Some(text(&b.get_item("command")?)?);
        }
        v.detail = Some(d);
    }
    v.runs = text(&get(b, "runs")?)?;
    v.seconds = text(&get(b, "seconds")?)?;
    Ok(v)
}

/// `_print_bundle`'s text.
#[pyfunction]
fn repro_render_bundle(b: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(core::render_bundle(&bundle_view(b)?))
}

/// `main_explore`'s text: the summary line, then each bundle.
#[pyfunction]
fn repro_render_explore(s: &Bound<'_, PyAny>) -> PyResult<String> {
    let bundles: Vec<Bound<'_, PyAny>> = s.get_item("bundles")?.try_iter()?.collect::<PyResult<_>>()?;
    let mut reproduced = 0;
    for b in &bundles {
        if get(b, "status")?.eq("reproduced")? {
            reproduced += 1;
        }
    }
    let mut out = vec![core::render_explore_line(
        &text(&s.get_item("seeds")?)?,
        &text(&s.get_item("seconds")?)?,
        s.get_item("flaky_failing")?.len()?,
        s.get_item("always_failing")?.len()?,
        reproduced,
        s.get_item("families_by_divergence")?.len()?,
        s.get_item("families_by_polluter")?.len()?,
    )];
    for b in &bundles {
        out.push(core::render_bundle(&bundle_view(b)?));
    }
    Ok(out.join("\n"))
}

/// `explore`'s bookkeeping: the seed loop's budget, the seed log, per test the first failing and the passing
/// configurations, always failing vs flaky, the tests to reproduce, the bundles and their families, the summary.
#[pyclass(module = "detpy._core", unsendable)]
struct ExploreBook {
    start: Instant,
    budget_s: f64,
    max_seeds: i64,
    next: i64,
    log: core::ExploreLog,
    seeds_log: Py<PyList>,
    bundles: Py<PyList>,
    skipped: Vec<String>,
    always: Vec<String>,
    flaky: Vec<String>,
}

#[pymethods]
impl ExploreBook {
    #[new]
    fn new(py: Python<'_>, budget_s: f64, max_seeds: i64) -> Self {
        ExploreBook {
            start: Instant::now(),
            budget_s,
            max_seeds,
            next: 1,
            log: core::ExploreLog::default(),
            seeds_log: PyList::empty(py).unbind(),
            bundles: PyList::empty(py).unbind(),
            skipped: Vec::new(),
            always: Vec::new(),
            flaky: Vec::new(),
        }
    }

    /// `time.monotonic() - t0 > budget_s`.
    fn over_budget(&self) -> bool {
        self.start.elapsed().as_secs_f64() > self.budget_s
    }

    /// The next seed to run, None once `max_seeds` ran or the budget is spent.
    fn next_seed(&mut self) -> Option<i64> {
        if self.next > self.max_seeds || self.over_budget() {
            self.next = self.max_seeds.saturating_add(1);
            return None;
        }
        self.next += 1;
        Some(self.next - 1)
    }

    /// Record the whole-suite run of `seed` (a `Run`).
    fn add_seed(&mut self, py: Python<'_>, seed: i64, run: &Bound<'_, PyAny>) -> PyResult<()> {
        let outcomes = run.getattr("outcomes")?;
        let mut items = Vec::new();
        for kv in outcomes.call_method0("items")?.try_iter()? {
            let (n, o): (String, Bound<'_, PyAny>) = kv?.extract()?;
            items.push((n, verdict_of(&o)?));
        }
        let failing = self.log.add(&core::SeedRun { seed, outcomes: items });
        let e = PyDict::new(py);
        e.set_item("seed", seed)?;
        e.set_item("seconds", core::py_round(run.getattr("duration")?.extract()?, 3))?;
        e.set_item("tests", outcomes.len()?)?;
        e.set_item("failing", failing)?;
        e.set_item("exit", run.getattr("exit_code")?)?;
        e.set_item("timed_out", run.getattr("timed_out")?)?;
        self.seeds_log.bind(py).append(e)
    }

    #[getter]
    fn seeds_log<'py>(&self, py: Python<'py>) -> Bound<'py, PyList> {
        self.seeds_log.bind(py).clone()
    }

    /// Split the failing tests into always failing and flaky (after the seed loop).
    fn classify(&mut self, collected: Vec<String>) {
        let collected: HashSet<String> = collected.into_iter().collect();
        (self.always, self.flaky) = self.log.classify(&|n: &str| collected.contains(n));
    }

    /// The tests to reproduce: the flaky ones, or with `targets` every failing test in `targets`.
    #[pyo3(signature = (targets, repro))]
    fn todo(&self, targets: Option<&Bound<'_, PyAny>>, repro: bool) -> PyResult<Vec<String>> {
        if !repro {
            return Ok(Vec::new());
        }
        match targets {
            None => Ok(self.log.todo(&self.flaky, None)),
            Some(t) => {
                let mut inside = HashSet::new();
                for n in self.always.iter().chain(&self.flaky) {
                    if t.contains(n)? {
                        inside.insert(n.clone());
                    }
                }
                Ok(self.log.todo(&self.flaky, Some(&|n: &str| inside.contains(n))))
            }
        }
    }

    fn skip(&mut self, nodeid: String) {
        self.skipped.push(nodeid);
    }

    /// (first failing configuration, passing configurations) of a failing test.
    fn known(&self, nodeid: &str) -> PyResult<(String, Vec<String>)> {
        let fail = self.log.fail_config(nodeid).ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(nodeid.to_string()))?;
        Ok((fail.to_string(), self.log.pass_configs(nodeid).to_vec()))
    }

    /// Keep the bundle of `nodeid` (with its first failing seed).
    fn add_bundle(&mut self, py: Python<'_>, nodeid: &str, bundle: &Bound<'_, PyAny>) -> PyResult<()> {
        let (fail, _) = self.known(nodeid)?;
        bundle.set_item("first_failing_seed", py.get_type::<PyInt>().call1((fail,))?)?;
        self.bundles.bind(py).append(bundle)
    }

    /// The summary `explore` writes and returns.
    fn summary<'py>(
        &self,
        py: Python<'py>,
        runs: &Bound<'py, PyAny>,
        collected: usize,
        run_log: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyDict>> {
        // families of the reproduced bundles: by first diverging event and by polluter (or setter) set
        let fam_div = PyDict::new(py);
        let fam_pol = PyDict::new(py);
        let add = |fam: &Bound<'py, PyDict>, key: String, test: Bound<'py, PyAny>| -> PyResult<()> {
            match fam.get_item(&key)? {
                Some(l) => l.cast::<PyList>()?.append(test),
                None => fam.set_item(key, PyList::new(py, [test])?),
            }
        };
        for b in self.bundles.bind(py).iter() {
            if !get(&b, "status")?.eq("reproduced")? {
                continue;
            }
            let mut d = get(&b, "divergence")?;
            if !d.is_truthy()? {
                d = PyDict::new(py).into_any();
            }
            let mut ev = get(&d, "event_b")?;
            if !ev.is_truthy()? {
                ev = PyDict::new(py).into_any();
            }
            let key = format!("{}|{}|{}", text(&get(&d, "reason")?)?, text(&get(&ev, "s")?)?, text(&get(&ev, "at")?)?);
            add(&fam_div, key, b.get_item("test")?)?;
            let mut members = get(&b, "polluters")?;
            if !members.is_truthy()? {
                members = get(&b, "setters")?;
            }
            let members = if members.is_truthy()? { names(&members)? } else { vec!["<none>".to_string()] };
            add(&fam_pol, members.join(" + "), b.get_item("test")?)?;
        }
        let s = PyDict::new(py);
        s.set_item("seeds", self.log.seeds())?;
        s.set_item("seconds", core::py_round(self.start.elapsed().as_secs_f64(), 2))?;
        s.set_item("runs", runs)?;
        s.set_item("collected", collected)?;
        s.set_item("failing_tests", self.log.failing_tests())?;
        s.set_item("always_failing", &self.always)?;
        s.set_item("flaky_failing", &self.flaky)?;
        s.set_item("bundles", self.bundles.bind(py))?;
        s.set_item("not_reproduced_budget", &self.skipped)?;
        s.set_item("families_by_divergence", fam_div)?;
        s.set_item("families_by_polluter", fam_pol)?;
        s.set_item("seeds_log", self.seeds_log.bind(py))?;
        s.set_item("run_log", run_log)?;
        Ok(s)
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("ReproOutOfRuns", m.py().get_type::<ReproOutOfRuns>())?;
    m.add_function(wrap_pyfunction!(repro_is_fail, m)?)?;
    m.add_function(wrap_pyfunction!(repro_outcome, m)?)?;
    m.add_function(wrap_pyfunction!(repro_prefix_through, m)?)?;
    m.add_function(wrap_pyfunction!(repro_order_for, m)?)?;
    m.add_function(wrap_pyfunction!(repro_ddmin, m)?)?;
    m.add_function(wrap_pyfunction!(repro_slug, m)?)?;
    m.add_function(wrap_pyfunction!(repro_divergence, m)?)?;
    m.add_function(wrap_pyfunction!(repro_reproduce, m)?)?;
    m.add_function(wrap_pyfunction!(repro_bundle_commands, m)?)?;
    m.add_function(wrap_pyfunction!(repro_replay_verdict, m)?)?;
    m.add_function(wrap_pyfunction!(repro_render_bundle, m)?)?;
    m.add_function(wrap_pyfunction!(repro_render_explore, m)?)?;
    m.add_class::<ExploreBook>()?;
    Ok(())
}
