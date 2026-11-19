//! `detpy repro` / `detpy explore`: the decisions (the pytest subprocesses stay in Python, `detpy/repro.py`).
//!
//! * [`reproduce`]: search (the fixed order, then seeds), minimisation ([`ddmin`] over the tests before the target,
//!   or over a passing configuration's prefix for a brittle test), replays; driven through a [`Driver`] that runs
//!   pytest (the Python `Runner`).
//! * [`ddmin`]: Zeller's delta debugging keeping the relative order, generic over the item and the predicate.
//! * [`prefix_through`], [`order_for`], [`slug`], [`divergence`], [`is_fail`], [`shell_quote`].
//! * [`ExploreLog`]: `explore`'s seed log, first failing / passing configurations, always-failing vs flaky.
//!
//! The Python originals are kept verbatim in `tests/rust_hotpaths_ref/_ref_repro.py`; `tests/test_repro_rust.py`
//! checks every function against them (same minimal sets and predicate calls, same bundles end to end).

use crate::event::Event;
use crate::order::shuffle_order;
use crate::trace::TraceError;
use crate::verify::{verify_paths, Reason};
use serde::Serialize;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

/// The configuration without a seed (the collection order).
pub const FIXED: &str = "fixed";

/// `is_fail`: a failing outcome (`failed`, `error`, `xfailed`... names that contain them).
pub fn is_fail(outcome: &str) -> bool {
    outcome.contains("failed") || outcome.contains("error")
}

/// The tests up to `target`, plus the next one (its teardown matches the full run); None when `target` is absent.
pub fn prefix_through<T: PartialEq + Clone>(order: &[T], target: &T) -> Option<Vec<T>> {
    let i = order.iter().position(|x| x == target)?;
    Some(order[..(i + 2).min(order.len())].to_vec())
}

/// The shuffle alone of `collected` under `seed` (None: the fixed order).
pub fn order_for<T: AsRef<str> + Clone>(collected: &[T], seed: Option<u64>) -> Vec<T> {
    match seed {
        None => collected.to_vec(),
        Some(s) => shuffle_order(collected, s).into_iter().map(|i| collected[i].clone()).collect(),
    }
}

/// Zeller's ddmin keeping the relative order: a 1-minimal sublist of `items` for which `still_fails` holds
/// (`still_fails(items)` must hold). The predicate is called in the order of the Python original; its error stops
/// the search.
pub fn ddmin<T: Clone, E>(items: Vec<T>, mut still_fails: impl FnMut(&[T]) -> Result<bool, E>) -> Result<Vec<T>, E> {
    let mut items = items;
    let mut n = 2usize;
    while items.len() >= 2 {
        let size = items.len();
        let chunks: Vec<Vec<T>> =
            (0..n).map(|i| items[i * size / n..(i + 1) * size / n].to_vec()).filter(|c| !c.is_empty()).collect();
        let mut reduced = false;
        for c in &chunks {
            if still_fails(c)? {
                items = c.clone();
                n = 2;
                reduced = true;
                break;
            }
        }
        if !reduced {
            for i in 0..chunks.len() {
                let comp: Vec<T> =
                    chunks.iter().enumerate().filter(|(j, _)| *j != i).flat_map(|(_, c)| c.iter().cloned()).collect();
                if still_fails(&comp)? {
                    items = comp;
                    n = (n - 1).max(2);
                    reduced = true;
                    break;
                }
            }
        }
        if !reduced {
            if n >= items.len() {
                break;
            }
            n = items.len().min(2 * n);
        }
    }
    if items.len() == 1 && still_fails(&[])? {
        return Ok(Vec::new());
    }
    Ok(items)
}

/// SHA-1 of `data` as lowercase hex (`hashlib.sha1(data).hexdigest()`).
pub fn sha1_hex(data: &[u8]) -> String {
    let mut h: [u32; 5] = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0];
    let mut msg = data.to_vec();
    let bits = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bits.to_be_bytes());
    for block in msg.chunks(64) {
        let mut w = [0u32; 80];
        for (i, word) in block.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let [mut a, mut b, mut c, mut d, mut e] = h;
        for (i, wi) in w.iter().enumerate() {
            let (f, k) = match i {
                0..=19 => ((b & c) | (!b & d), 0x5A827999),
                20..=39 => (b ^ c ^ d, 0x6ED9EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1BBCDC),
                _ => (b ^ c ^ d, 0xCA62C1D6),
            };
            let t = a.rotate_left(5).wrapping_add(f).wrapping_add(e).wrapping_add(k).wrapping_add(*wi);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = t;
        }
        for (x, y) in h.iter_mut().zip([a, b, c, d, e]) {
            *x = x.wrapping_add(y);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}

/// The bundle directory name of a test: its last `::` part with runs of other characters than `[A-Za-z0-9_.-]`
/// replaced by `_`, cut to 60 characters, then the first 8 hex digits of the node id's SHA-1.
pub fn slug(nodeid: &str) -> String {
    let last = nodeid.split("::").last().unwrap_or("");
    let mut base = String::new();
    let mut in_run = false;
    for c in last.chars() {
        if c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-') {
            base.push(c);
            in_run = false;
        } else if !in_run {
            base.push('_');
            in_run = true;
        }
    }
    let base: String = base.chars().take(60).collect();
    format!("{base}-{}", &sha1_hex(nodeid.as_bytes())[..8])
}

/// `shlex.quote`.
pub fn shell_quote(s: &str) -> String {
    if s.is_empty() {
        return "''".into();
    }
    let safe = |c: char| c.is_ascii_alphanumeric() || "_@%+=:,./-".contains(c);
    if s.chars().all(safe) {
        return s.into();
    }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

/// `round(x, ndigits)` of a Python float (correctly rounded, ties to even on the exact binary value).
pub fn py_round(x: f64, ndigits: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.ndigits$}").parse().unwrap_or(x)
}

/// The command lines of a bundle: `pytest --det [--det-seed=N] --det-order=<order> <args>` and `detpy replay`.
pub fn bundle_commands(config: &str, order_path: &str, bundle: &str, args: &[String]) -> (String, String) {
    let mut words: Vec<String> = vec!["pytest".into(), "--det".into()];
    if config != FIXED {
        words.push(format!("--det-seed={config}"));
    }
    words.push(format!("--det-order={order_path}"));
    words.extend(args.iter().cloned());
    let command = words.iter().map(|w| shell_quote(w)).collect::<Vec<_>>().join(" ");
    (command, format!("detpy replay {}", shell_quote(bundle)))
}

/// The first diverging event of a test between a passing and a failing trace (the fields a bundle keeps).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct DivergenceKeep {
    pub index: Option<u64>,
    pub reason: Option<Reason>,
    pub description: Option<String>,
    pub event_a: Option<Event>,
    pub event_b: Option<Event>,
    pub fingerprints: Vec<Option<String>>,
}

/// `_divergence`: None without a passing trace, when either trace is missing or the test is in neither.
pub fn divergence(pass_trace: Option<&Path>, fail_trace: &Path, nodeid: &str) -> Result<Option<DivergenceKeep>, TraceError> {
    let Some(pass_trace) = pass_trace else { return Ok(None) };
    if !pass_trace.exists() || !fail_trace.exists() {
        return Ok(None);
    }
    let report = verify_paths(&[pass_trace, fail_trace])?;
    let Some(t) = report.tests.into_iter().find(|t| t.nodeid == nodeid) else { return Ok(None) };
    let d = t.divergence;
    Ok(Some(DivergenceKeep {
        index: d.as_ref().and_then(|d| d.index),
        reason: d.as_ref().map(|d| d.reason),
        description: d.as_ref().map(|d| d.description.clone()),
        event_a: d.as_ref().and_then(|d| d.event_a.clone()),
        event_b: d.as_ref().and_then(|d| d.event_b.clone()),
        fingerprints: t.fingerprints,
    }))
}

/// A test's outcome in a run, as `reproduce` reads it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verdict {
    /// `is_fail`.
    Fail,
    /// `== "passed"`.
    Passed,
    /// Anything else (skipped, missing, ...).
    Other,
}

/// What `reproduce` needs from the outside: pytest runs (the Python `Runner`) and their outcomes.
pub trait Driver {
    type Run: Clone;
    type Err;
    /// The order a whole-suite run with this configuration uses (`Runner.order_of`).
    fn order_of(&mut self, config: &str) -> Result<Vec<String>, Self::Err>;
    /// Run exactly `order` under `config` (`Runner.run`).
    fn run(&mut self, config: &str, order: &[String], tag: &str) -> Result<Self::Run, Self::Err>;
    /// The outcome of `nodeid` in `run` (`Run.outcome`).
    fn verdict(&mut self, run: &Self::Run, nodeid: &str) -> Result<Verdict, Self::Err>;
    /// The fingerprint of `nodeid` in `run` (`Run.fingerprints.get`).
    fn fingerprint(&mut self, run: &Self::Run, nodeid: &str) -> Result<Option<String>, Self::Err>;
}

/// Why `reproduce` stopped with an error.
#[derive(Debug)]
pub enum ReproError<E> {
    /// The driver failed (a Python exception).
    Driver(E),
    /// The run budget ran out during the search (`OutOfRuns`, not caught there in the original).
    OutOfRuns,
    /// The target is not in a configuration's order (`list.index`'s ValueError).
    NotInList(String),
    /// `confirm` < 1: there is no replay to read (`replays[0]`'s IndexError).
    NoReplays,
}

/// The parameters of `reproduce` (`collected` resolved by the caller).
#[derive(Clone, Debug)]
pub struct ReproParams<'a> {
    pub target: &'a str,
    pub collected: &'a [String],
    pub seeds: i64,
    pub known_fail: Option<&'a str>,
    pub known_pass: &'a [String],
    pub confirm: i64,
    pub max_runs: i64,
}

/// The minimised and replayed bundle.
#[derive(Clone, Debug)]
pub struct Bundle<R> {
    pub config: String,
    /// `order`, `fails-alone` or `brittle`.
    pub kind: &'static str,
    pub prefix_length: usize,
    pub polluters: Vec<String>,
    pub setters: Vec<String>,
    /// The minimal order (polluters, then the target).
    pub order: Vec<String>,
    pub pass_run: Option<R>,
    pub replays: Vec<R>,
    pub fails: usize,
    pub identical: bool,
    /// Distinct non-empty fingerprints of the replays, sorted.
    pub fingerprints: Vec<String>,
    /// `reproduced` or `replay-unstable`.
    pub status: &'static str,
}

/// The result of `reproduce`.
#[derive(Clone, Debug)]
pub enum Repro<R> {
    NotCollected,
    NotFound { searched: usize },
    NotMinimised { searched: usize, config: String, prefix_length: usize },
    Bundle { searched: usize, bundle: Bundle<R> },
}

/// The configurations of the search: the fixed order, seeds `1..=seeds`; a known failing one first.
pub fn search_configs(seeds: i64, known_fail: Option<&str>) -> Vec<String> {
    let mut configs: Vec<String> = std::iter::once(FIXED.to_string()).chain((1..=seeds.max(0)).map(|s| s.to_string())).collect();
    if let Some(k) = known_fail.filter(|k| !k.is_empty()) {
        configs = std::iter::once(k.to_string()).chain(configs.into_iter().filter(|c| c != k)).collect();
    }
    configs
}

/// The configurations tried for a brittle test's setter: those seen passing, then every other of the search space
/// (review E6), without repeats.
pub fn setter_candidates(passing: &[String], seeds: i64, config: &str) -> Vec<String> {
    let all = std::iter::once(FIXED.to_string()).chain((1..=seeds.max(0)).map(|s| s.to_string()));
    let mut seen = std::collections::HashSet::new();
    passing.iter().cloned().chain(all.filter(|c| c != config)).filter(|c| seen.insert(c.clone())).collect()
}

/// Runs memoised by (configuration, order) under a budget (`run_order`).
struct Budgeted<'d, D: Driver> {
    d: &'d mut D,
    left: i64,
    cache: HashMap<(String, Vec<String>), D::Run>,
}

impl<D: Driver> Budgeted<'_, D> {
    fn run(&mut self, config: &str, order: Vec<String>, tag: &str) -> Result<D::Run, ReproError<D::Err>> {
        let key = (config.to_string(), order);
        if let Some(r) = self.cache.get(&key) {
            return Ok(r.clone());
        }
        if self.left <= 0 {
            return Err(ReproError::OutOfRuns);
        }
        self.left -= 1;
        let r = self.d.run(config, &key.1, tag).map_err(ReproError::Driver)?;
        self.cache.insert(key, r.clone());
        Ok(r)
    }

    fn verdict(&mut self, run: &D::Run, nodeid: &str) -> Result<Verdict, ReproError<D::Err>> {
        self.d.verdict(run, nodeid).map_err(ReproError::Driver)
    }

    fn prefix(&mut self, config: &str, target: &str) -> Result<Vec<String>, ReproError<D::Err>> {
        let order = self.d.order_of(config).map_err(ReproError::Driver)?;
        prefix_through(&order, &target.to_string()).ok_or_else(|| ReproError::NotInList(target.to_string()))
    }
}

/// Search, minimise and replay one failing test (`reproduce` without the bundle files).
pub fn reproduce<D: Driver>(d: &mut D, p: &ReproParams<'_>) -> Result<Repro<D::Run>, ReproError<D::Err>> {
    let target = p.target;
    if !p.collected.iter().any(|c| c == target) {
        return Ok(Repro::NotCollected);
    }
    let mut b = Budgeted { d, left: p.max_runs, cache: HashMap::new() };

    // 1. search
    let mut passing: Vec<String> = p.known_pass.to_vec();
    let mut found = None;
    let mut searched = 0usize;
    for config in search_configs(p.seeds, p.known_fail) {
        let order = b.prefix(&config, target)?;
        let r = b.run(&config, order.clone(), &format!("search-{config}"))?;
        searched += 1;
        match b.verdict(&r, target)? {
            Verdict::Fail => {
                found = Some((config, order));
                break;
            }
            Verdict::Passed => passing.push(config),
            Verdict::Other => {}
        }
    }
    let Some((config, order)) = found else { return Ok(Repro::NotFound { searched }) };
    let before: Vec<String> = order[..order.iter().position(|x| x == target).unwrap()].to_vec();
    let prefix_length = before.len() + 1;

    // 2. minimise
    let mut tests_run = 0u64;
    let mut kind = "order";
    let (mut polluters, mut setters, mut pass_run) = (Vec::new(), Vec::new(), None);
    let minimised: Result<Vec<String>, ReproError<D::Err>> = (|| {
        let alone = b.run(&config, vec![target.to_string()], &format!("alone-{config}"))?;
        if b.verdict(&alone, target)? == Verdict::Fail {
            kind = "fails-alone";
            // Brittle test: name what makes it pass, from a passing configuration.
            for pconf in setter_candidates(&passing, p.seeds, &config) {
                let porder = b.prefix(&pconf, target)?;
                let pbefore: Vec<String> = porder[..porder.iter().position(|x| x == target).unwrap()].to_vec();
                if pbefore.is_empty() {
                    continue;
                }
                let mut passes_with = |sub: &[String]| -> Result<bool, ReproError<D::Err>> {
                    tests_run += 1;
                    let order: Vec<String> = sub.iter().cloned().chain(std::iter::once(target.to_string())).collect();
                    let r = b.run(&config, order, &format!("set-{pconf}-{tests_run}"))?;
                    Ok(b.verdict(&r, target)? == Verdict::Passed)
                };
                if passes_with(&pbefore)? {
                    setters = ddmin(pbefore, &mut passes_with)?;
                    if !setters.is_empty() {
                        kind = "brittle";
                        let order: Vec<String> = setters.iter().cloned().chain(std::iter::once(target.to_string())).collect();
                        pass_run = Some(b.run(&config, order, "setter-pass")?);
                    }
                    break;
                }
            }
            Ok(Vec::new())
        } else {
            pass_run = Some(alone);
            let minimal = ddmin(before.clone(), |sub: &[String]| {
                tests_run += 1;
                let order: Vec<String> = sub.iter().cloned().chain(std::iter::once(target.to_string())).collect();
                let r = b.run(&config, order, &format!("min-{config}-{tests_run}"))?;
                Ok(b.verdict(&r, target)? == Verdict::Fail)
            })?;
            polluters = minimal.clone();
            Ok(minimal)
        }
    })();
    let minimal = match minimised {
        Ok(m) => m,
        Err(ReproError::OutOfRuns) => return Ok(Repro::NotMinimised { searched, config, prefix_length }),
        Err(e) => return Err(e),
    };
    let bundle_order: Vec<String> = minimal.into_iter().chain(std::iter::once(target.to_string())).collect();

    // 3. replay
    let d = b.d;
    let mut replays = Vec::new();
    for i in 0..p.confirm.max(0) {
        replays.push(d.run(&config, &bundle_order, &format!("replay-{i}")).map_err(ReproError::Driver)?);
    }
    let mut fails = 0usize;
    let mut fps = Vec::new();
    for r in &replays {
        if d.verdict(r, target).map_err(ReproError::Driver)? == Verdict::Fail {
            fails += 1;
        }
    }
    for r in &replays {
        fps.push(d.fingerprint(r, target).map_err(ReproError::Driver)?);
    }
    if replays.is_empty() {
        return Err(ReproError::NoReplays);
    }
    let (identical, fingerprints) = fingerprint_summary(&fps);
    let status = if fails as i64 == p.confirm && identical { "reproduced" } else { "replay-unstable" };
    Ok(Repro::Bundle {
        searched,
        bundle: Bundle {
            config,
            kind,
            prefix_length,
            polluters,
            setters,
            order: bundle_order,
            pass_run,
            replays,
            fails,
            identical,
            fingerprints,
            status,
        },
    })
}

/// (`len(set(fps)) == 1 and fps[0] is not None`, `sorted(set(f for f in fps if f))`).
pub fn fingerprint_summary(fps: &[Option<String>]) -> (bool, Vec<String>) {
    let distinct: std::collections::BTreeSet<&Option<String>> = fps.iter().collect();
    let identical = distinct.len() == 1 && fps[0].is_some();
    let mut nonempty: Vec<String> = fps.iter().flatten().filter(|f| !f.is_empty()).cloned().collect();
    nonempty.sort();
    nonempty.dedup();
    (identical, nonempty)
}

/// One whole-suite seed run of `explore`.
#[derive(Clone, Debug, PartialEq)]
pub struct SeedRun {
    pub seed: i64,
    /// `(nodeid, verdict)` in the outcomes file's order.
    pub outcomes: Vec<(String, Verdict)>,
}

/// `explore`'s bookkeeping: per test the first failing configuration and the passing ones, per seed the failing
/// tests.
#[derive(Clone, Debug, Default)]
pub struct ExploreLog {
    /// Failing tests of each seed run, sorted.
    pub failing: Vec<Vec<String>>,
    fail_cfg: Vec<(String, String)>,
    fail_idx: HashMap<String, usize>,
    pass_cfg: BTreeMap<String, Vec<String>>,
}

impl ExploreLog {
    /// Record a seed run; returns its failing tests, sorted.
    pub fn add(&mut self, run: &SeedRun) -> Vec<String> {
        let mut failing: Vec<String> =
            run.outcomes.iter().filter(|(_, v)| *v == Verdict::Fail).map(|(n, _)| n.clone()).collect();
        failing.sort();
        for (n, v) in &run.outcomes {
            match v {
                Verdict::Fail => {
                    if !self.fail_idx.contains_key(n) {
                        self.fail_idx.insert(n.clone(), self.fail_cfg.len());
                        self.fail_cfg.push((n.clone(), run.seed.to_string()));
                    }
                }
                Verdict::Passed => self.pass_cfg.entry(n.clone()).or_default().push(run.seed.to_string()),
                Verdict::Other => {}
            }
        }
        self.failing.push(failing.clone());
        failing
    }

    pub fn seeds(&self) -> usize {
        self.failing.len()
    }

    /// Tests that failed under some seed.
    pub fn failing_tests(&self) -> usize {
        self.fail_cfg.len()
    }

    /// The first configuration a test failed under.
    pub fn fail_config(&self, nodeid: &str) -> Option<&str> {
        self.fail_idx.get(nodeid).map(|&i| self.fail_cfg[i].1.as_str())
    }

    /// The configurations a test passed under.
    pub fn pass_configs(&self, nodeid: &str) -> &[String] {
        self.pass_cfg.get(nodeid).map(|v| v.as_slice()).unwrap_or(&[])
    }

    /// (always failing, flaky failing), sorted: a test is always failing when it never passed and failed under every
    /// seed (a test outside `collected` counts as failing everywhere, as in the original).
    pub fn classify(&self, collected: &dyn Fn(&str) -> bool) -> (Vec<String>, Vec<String>) {
        let mut always = Vec::new();
        let mut flaky = Vec::new();
        for (n, _) in &self.fail_cfg {
            let never_passed = self.pass_configs(n).is_empty();
            let everywhere = !collected(n) || self.failing.iter().all(|f| f.binary_search(n).is_ok());
            if never_passed && everywhere {
                always.push(n.clone());
            } else {
                flaky.push(n.clone());
            }
        }
        always.sort();
        flaky.sort();
        (always, flaky)
    }

    /// The tests to reproduce: the flaky ones, or with `targets` every failing test that is a target.
    pub fn todo(&self, flaky: &[String], targets: Option<&dyn Fn(&str) -> bool>) -> Vec<String> {
        match targets {
            None => flaky.to_vec(),
            Some(t) => {
                let mut all: Vec<String> = self.fail_cfg.iter().map(|(n, _)| n.clone()).collect();
                all.sort();
                all.into_iter().filter(|n| t(n)).collect()
            }
        }
    }
}

/// What `_print_bundle` shows of a bundle (each value as the f-string formats it).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct BundleView {
    pub test: String,
    pub status: String,
    /// For a `reproduced` or `replay-unstable` bundle.
    pub detail: Option<BundleDetail>,
    pub runs: String,
    pub seconds: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BundleDetail {
    pub config: String,
    pub fixed: bool,
    pub prefix_length: String,
    pub minimal_length: String,
    pub polluters: Vec<String>,
    pub setters: Vec<String>,
    pub fails_alone: bool,
    pub replay_fails: String,
    pub replay_runs: String,
    pub identical: String,
    /// (reason, description) of the first diverging event, when it has a description.
    pub divergence: Option<(String, String)>,
    pub command: Option<String>,
}

/// `_print_bundle`'s text (without the final newline).
pub fn render_bundle(v: &BundleView) -> String {
    let mut lines = vec![format!("detpy repro: {}: {}", v.test, v.status)];
    if let Some(d) = &v.detail {
        let place = if d.fixed { "fixed order".to_string() } else { format!("--det-seed={}", d.config) };
        lines.push(format!(
            "  found with {place}; order minimised from {} to {} test(s)",
            d.prefix_length, d.minimal_length
        ));
        if !d.polluters.is_empty() {
            lines.push(format!("  polluter(s): {}", d.polluters.join(", ")));
        }
        if !d.setters.is_empty() {
            lines.push(format!("  fails without (state setter): {}", d.setters.join(", ")));
        }
        if d.fails_alone {
            lines.push("  fails when run alone (no polluter)".into());
        }
        lines.push(format!(
            "  replay: {}/{} failed, identical fingerprint: {}",
            d.replay_fails, d.replay_runs, d.identical
        ));
        if let Some((reason, description)) = &d.divergence {
            lines.push(format!("  first diverging event vs a passing run: {reason}: {description}"));
        }
        if let Some(c) = &d.command {
            lines.push(format!("  replay: {c}"));
        }
    }
    lines.push(format!("  {} pytest runs, {} s", v.runs, v.seconds));
    lines.join("\n")
}

/// `main_explore`'s summary line.
pub fn render_explore_line(
    seeds: &str,
    seconds: &str,
    flaky: usize,
    always: usize,
    bundles: usize,
    families_div: usize,
    families_pol: usize,
) -> String {
    format!(
        "detpy explore: {seeds} seeds in {seconds} s; {flaky} flaky failing tests ({always} always failing, not \
         flaky); {bundles} replay bundles; {families_div} distinct first diverging events, {families_pol} distinct \
         polluter sets"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha1_known_vectors() {
        assert_eq!(sha1_hex(b""), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        assert_eq!(sha1_hex(b"abc"), "a9993e364706816aba3e25717850c26c9cd0d89d");
        let long = vec![b'a'; 1_000];
        assert_eq!(sha1_hex(&long), "291e9a6c66994949b57ba5e650361e98fc36b1ba");
    }

    #[test]
    fn slug_shape() {
        let s = slug("tests/test_x.py::TestA::test_b[1-x y]");
        assert!(s.starts_with("test_b_1-x_y_-"), "{s}");
        assert_eq!(s.len(), "test_b_1-x_y_-".len() + 8);
        assert_eq!(slug("a:::b").split('-').next(), Some("_b"));
    }

    #[test]
    fn ddmin_is_minimal_and_keeps_order() {
        let got: Result<Vec<u32>, ()> = ddmin((0..10).collect(), |s| Ok(s.contains(&3) && s.contains(&7)));
        assert_eq!(got.unwrap(), vec![3, 7]);
        let got: Result<Vec<u32>, ()> = ddmin((0..10).collect(), |_| Ok(true));
        assert_eq!(got.unwrap(), Vec::<u32>::new());
        let got: Result<Vec<u32>, &str> = ddmin((0..10).collect(), |_| Err("stop"));
        assert_eq!(got.unwrap_err(), "stop");
    }

    #[test]
    fn prefix_and_configs() {
        let o: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        assert_eq!(prefix_through(&o, &"a".to_string()).unwrap(), vec!["a", "b"]);
        assert_eq!(prefix_through(&o, &"c".to_string()).unwrap(), vec!["a", "b", "c"]);
        assert!(prefix_through(&o, &"z".to_string()).is_none());
        assert_eq!(search_configs(2, Some("2")), vec!["2", "fixed", "1"]);
        assert_eq!(search_configs(2, Some("")), vec!["fixed", "1", "2"]);
        assert_eq!(setter_candidates(&["2".into(), "2".into()], 3, "1"), vec!["2", "fixed", "3"]);
    }

    #[test]
    fn quoting_and_rounding() {
        assert_eq!(shell_quote(""), "''");
        assert_eq!(shell_quote("a/b-c.d"), "a/b-c.d");
        assert_eq!(shell_quote("it's"), "'it'\"'\"'s'");
        assert_eq!(py_round(0.125, 2), 0.12);
        assert_eq!(py_round(2.675, 2), 2.67);
        assert_eq!(py_round(1.0005, 3), 1.0);
    }

    struct Fake {
        // the target fails when "w" runs before it
        log: Vec<String>,
    }

    impl Driver for Fake {
        type Run = Vec<String>;
        type Err = ();
        fn order_of(&mut self, config: &str) -> Result<Vec<String>, ()> {
            let mut o: Vec<String> = ["a", "w", "b", "v", "c"].iter().map(|s| s.to_string()).collect();
            if config != FIXED {
                o.reverse();
            }
            Ok(o)
        }
        fn run(&mut self, config: &str, order: &[String], tag: &str) -> Result<Vec<String>, ()> {
            self.log.push(format!("{config} {tag} {}", order.join(",")));
            Ok(order.to_vec())
        }
        fn verdict(&mut self, run: &Vec<String>, nodeid: &str) -> Result<Verdict, ()> {
            let i = run.iter().position(|x| x == nodeid).unwrap();
            Ok(if run[..i].iter().any(|x| x == "w") { Verdict::Fail } else { Verdict::Passed })
        }
        fn fingerprint(&mut self, _run: &Vec<String>, _nodeid: &str) -> Result<Option<String>, ()> {
            Ok(Some("fp".into()))
        }
    }

    #[test]
    fn reproduce_names_the_polluter() {
        let mut f = Fake { log: vec![] };
        let collected: Vec<String> = ["a", "w", "b", "v", "c"].iter().map(|s| s.to_string()).collect();
        let p = ReproParams {
            target: "v",
            collected: &collected,
            seeds: 3,
            known_fail: None,
            known_pass: &[],
            confirm: 2,
            max_runs: 100,
        };
        let Repro::Bundle { searched, bundle } = reproduce(&mut f, &p).unwrap() else { panic!() };
        assert_eq!(searched, 1);
        assert_eq!(bundle.polluters, vec!["w"]);
        assert_eq!(bundle.order, vec!["w", "v"]);
        assert_eq!(bundle.status, "reproduced");
        assert_eq!(f.log.first().unwrap(), "fixed search-fixed a,w,b,v,c");
        let p = ReproParams { max_runs: 2, ..p };
        assert!(matches!(reproduce(&mut Fake { log: vec![] }, &p).unwrap(), Repro::NotMinimised { .. }));
    }
}
