//! Fixed plan for running a `--det` session across N workers (pytest-xdist under `--det`, `DetScheduling`).
//!
//! The plan is a pure function of (ordered test ids, atom of each test, cost of each test, number of workers,
//! previous assignment): no timing, no arrival order of workers. Every worker receives its whole list before it
//! starts; its list is a subsequence of the serial order, so every in-process predecessor of a test is one of its
//! serial predecessors (docs/PARALLEL-PROOF-DESIGN.md 2.2, 2.3).
//!
//! * **Atoms** are the units of placement: a set of tests that must run in one worker. The customer's `--dist`
//!   mode defines them ([`atom_key`]); the plan never splits an atom.
//! * **Costs** are recorded durations in seconds, summed per atom in integer microseconds so that the sum (and the
//!   plan) does not depend on the order of the input. A test without a recorded duration costs the median of the
//!   known ones (1 s when none is known).
//! * **Assignment**: longest-processing-time-first over atoms, ties broken by the digest of the atom key, then by
//!   the key; a worker's load ties are broken by the lowest worker index.
//! * **Stickiness**: atoms keep the worker they had in the previous plan (`previous`) when the resulting makespan
//!   is at most `(1 + tolerance)` times the LPT makespan; new atoms are then placed longest first on the least
//!   loaded worker. Otherwise the plain LPT plan is used.

use crate::fingerprint::digest_bytes;
use std::collections::{BTreeMap, HashMap};

/// The `--dist` modes the planner understands.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DistMode {
    /// One test per atom (`load`, `worksteal`, `no`).
    Test,
    /// Module, or class for tests in a class (`loadscope`): the node id up to its last `::`.
    Scope,
    /// File (`loadfile`).
    File,
    /// `xdist_group` name, else the test (`loadgroup`).
    Group,
}

impl DistMode {
    pub fn parse(s: &str) -> Option<DistMode> {
        Some(match s {
            "load" | "worksteal" | "no" | "" => DistMode::Test,
            "loadscope" => DistMode::Scope,
            "loadfile" => DistMode::File,
            "loadgroup" => DistMode::Group,
            _ => return None,
        })
    }
}

/// The atom key of a test under `mode`. `group` is the test's `xdist_group` name (several names joined by `_`, as
/// xdist does), only used by [`DistMode::Group`].
pub fn atom_key(nodeid: &str, mode: DistMode, group: Option<&str>) -> String {
    match mode {
        DistMode::Test => format!("t:{nodeid}"),
        DistMode::Scope => match nodeid.rsplit_once("::") {
            Some((scope, _)) => format!("s:{scope}"),
            None => format!("s:{nodeid}"),
        },
        DistMode::File => format!("f:{}", nodeid.split("::").next().unwrap_or(nodeid)),
        DistMode::Group => match group {
            Some(g) if !g.is_empty() => format!("g:{g}"),
            _ => format!("t:{nodeid}"),
        },
    }
}

#[derive(Clone, Debug, Default)]
pub struct PlanInput {
    /// Test ids in the serial order (only the tests to place).
    pub ids: Vec<String>,
    /// Atom key of each test (same length as `ids`).
    pub atoms: Vec<String>,
    /// Recorded duration of each test in seconds (`None`: unknown).
    pub costs: Vec<Option<f64>>,
    pub workers: usize,
    /// Atom key -> worker of the previous plan (same number of workers).
    pub previous: BTreeMap<String, usize>,
    /// Stickiness tolerance: 0.10 keeps the previous placement while the makespan is at most 10 % above LPT's...
    pub tolerance: f64,
    /// ... plus this many seconds (a worker's start-up is about a second: below that, a reshuffle buys nothing and
    /// makes the per-worker inputs churn).
    pub slack: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Plan {
    /// Per worker, the positions (into `PlanInput::ids`) it runs, in serial order.
    pub lists: Vec<Vec<usize>>,
    /// Atom key -> worker.
    pub atom_worker: BTreeMap<String, usize>,
    /// Planned load per worker (seconds).
    pub loads: Vec<f64>,
    pub makespan: f64,
    pub lpt_makespan: f64,
    /// True when the previous placement was kept (stickiness).
    pub sticky: bool,
    /// Atoms that kept their previous worker.
    pub kept: usize,
    /// Digest of (number of workers, every worker's id list).
    pub digest: String,
}

struct Atom {
    key: String,
    tie: [u8; 32],
    cost: u64,
    members: Vec<usize>,
}

fn micros(x: f64) -> u64 {
    if x.is_finite() && x > 0.0 {
        (x * 1e6).round() as u64
    } else {
        0
    }
}

fn median(mut v: Vec<u64>) -> Option<u64> {
    if v.is_empty() {
        return None;
    }
    v.sort_unstable();
    let n = v.len();
    Some(if n % 2 == 1 { v[n / 2] } else { (v[n / 2 - 1] + v[n / 2]) / 2 })
}

/// Median of the last (up to) 3 recorded durations of a test.
pub fn cost_of(history: &[f64]) -> Option<f64> {
    let tail: Vec<u64> = history.iter().rev().take(3).map(|&d| micros(d)).collect();
    median(tail).map(|m| m as f64 / 1e6)
}

fn least_loaded(loads: &[u64]) -> usize {
    let mut best = 0;
    for (i, &l) in loads.iter().enumerate() {
        if l < loads[best] {
            best = i;
        }
    }
    best
}

/// Longest first (cost descending), then the atom key's digest, then the key.
fn lpt_order(atoms: &[Atom]) -> Vec<usize> {
    let mut idx: Vec<usize> = (0..atoms.len()).collect();
    idx.sort_by(|&a, &b| {
        let (x, y) = (&atoms[a], &atoms[b]);
        y.cost.cmp(&x.cost).then_with(|| x.tie.cmp(&y.tie)).then_with(|| x.key.cmp(&y.key))
    });
    idx
}

fn lpt(atoms: &[Atom], order: &[usize], loads: &mut [u64], place: &mut [usize], skip: &[bool]) {
    for &a in order {
        if skip[a] {
            continue;
        }
        let w = least_loaded(loads);
        place[a] = w;
        loads[w] += atoms[a].cost;
    }
}

/// Locality for one-test atoms (`load`, `worksteal`): consecutive tests of the same file are merged into chunk atoms.
/// A plan over single tests scatters every module over every worker: each worker then sets up every module-scoped
/// fixture, and a test loses more of its serial in-process predecessors (placement). Merging atoms never splits one:
/// atoms that are not one-test atoms (`t:` keys) are left as they are. Returns the new atom keys (`c:<first test
/// id>`).
///
/// The boundaries must not move when tests are added or removed elsewhere (review R-023 F4: a cap of `tests /
/// (workers x div)` tests per chunk moved every boundary after one added test, and with them half of the tests'
/// workers). So:
/// * the target size is `tests / (workers x div)` rounded **up to a power of two**: it changes only when the suite
///   doubles or halves, or the number of workers changes;
/// * a same-file run of at most the target size is one chunk;
/// * a longer run is cut **by content**: before a test whose id digest is 0 modulo the target (expected chunk size =
///   the target), and before a test that would make the chunk twice the target. A cut depends on the test's own id,
///   so adding or removing a test changes at most the chunk it is in (and, through the forced cut, the chunks up to
///   the next content cut of that file).
///
/// Durations are never used (`costs` is accepted for the binding's signature).
pub fn chunk_test_atoms(ids: &[String], atoms: &[String], costs: &[Option<f64>], workers: usize, div: usize) -> Vec<String> {
    if div == 0 || workers == 0 || ids.is_empty() {
        return atoms.to_vec();
    }
    let _ = costs;
    let target = chunk_target(ids.len(), workers, div);
    let file = |id: &str| id.split("::").next().unwrap_or(id).to_string();
    let mut out = atoms.to_vec();
    let mut i = 0;
    while i < ids.len() {
        if !atoms[i].starts_with("t:") {
            i += 1;
            continue;
        }
        // the same-file run of one-test atoms starting at i
        let f = file(&ids[i]);
        let mut j = i + 1;
        while j < ids.len() && atoms[j].starts_with("t:") && file(&ids[j]) == f {
            j += 1;
        }
        let whole = (j - i) as u64 <= target;
        let mut key = format!("c:{}", ids[i]);
        let mut size = 0u64;
        for k in i..j {
            let cut = k > i && !whole && (content_cut(&ids[k], target) || size >= 2 * target);
            if cut {
                key = format!("c:{}", ids[k]);
                size = 0;
            }
            out[k] = key.clone();
            size += 1;
        }
        i = j;
    }
    out
}

/// The chunk target size: `ceil(tests / (workers x div))` rounded up to a power of two.
pub fn chunk_target(tests: usize, workers: usize, div: usize) -> u64 {
    (tests.div_ceil((workers * div).max(1)).max(1) as u64).next_power_of_two()
}

fn content_cut(id: &str, target: u64) -> bool {
    let d = digest_bytes(id.as_bytes()).0;
    u64::from_le_bytes(d[..8].try_into().unwrap()) % target.max(1) == 0
}

/// Digest of a plan: the number of workers and every worker's ordered id list.
pub fn plan_digest<S: AsRef<str>>(lists: &[Vec<S>]) -> String {
    let mut buf = Vec::new();
    buf.extend_from_slice(&(lists.len() as u64).to_le_bytes());
    for l in lists {
        buf.extend_from_slice(&(l.len() as u64).to_le_bytes());
        for id in l {
            buf.extend_from_slice(&(id.as_ref().len() as u64).to_le_bytes());
            buf.extend_from_slice(id.as_ref().as_bytes());
        }
    }
    digest_bytes(&buf).short()
}

pub fn plan(input: &PlanInput) -> Result<Plan, String> {
    let n = input.workers;
    if n == 0 {
        return Err("a plan needs at least one worker".into());
    }
    if input.atoms.len() != input.ids.len() || input.costs.len() != input.ids.len() {
        return Err("ids, atoms and costs must have the same length".into());
    }
    let known: Vec<u64> = input.costs.iter().flatten().map(|&c| micros(c)).collect();
    let default = median(known).unwrap_or(1_000_000).max(1);
    // atoms in first-appearance order (only for building; the assignment does not depend on it)
    let mut by_key: HashMap<&str, usize> = HashMap::new();
    let mut atoms: Vec<Atom> = Vec::new();
    for (i, key) in input.atoms.iter().enumerate() {
        let c = input.costs[i].map(micros).unwrap_or(default).max(1);
        let a = *by_key.entry(key.as_str()).or_insert_with(|| {
            atoms.push(Atom { key: key.clone(), tie: digest_bytes(key.as_bytes()).0, cost: 0, members: Vec::new() });
            atoms.len() - 1
        });
        atoms[a].cost += c;
        atoms[a].members.push(i);
    }
    let order = lpt_order(&atoms);
    // plain LPT
    let mut lpt_loads = vec![0u64; n];
    let mut lpt_place = vec![0usize; atoms.len()];
    lpt(&atoms, &order, &mut lpt_loads, &mut lpt_place, &vec![false; atoms.len()]);
    let lpt_span = lpt_loads.iter().copied().max().unwrap_or(0);
    // sticky: previous placement kept, new atoms by LPT
    let mut s_loads = vec![0u64; n];
    let mut s_place = vec![0usize; atoms.len()];
    let mut fixed = vec![false; atoms.len()];
    let mut kept = 0;
    for (a, atom) in atoms.iter().enumerate() {
        if let Some(&w) = input.previous.get(&atom.key) {
            if w < n {
                s_place[a] = w;
                s_loads[w] += atom.cost;
                fixed[a] = true;
                kept += 1;
            }
        }
    }
    let use_sticky = kept > 0 && {
        lpt(&atoms, &order, &mut s_loads, &mut s_place, &fixed);
        let span = s_loads.iter().copied().max().unwrap_or(0) as f64;
        span <= lpt_span as f64 * (1.0 + input.tolerance.max(0.0)) + micros(input.slack) as f64
    };
    let (place, loads) = if use_sticky { (s_place, s_loads) } else { (lpt_place, lpt_loads) };
    let mut lists: Vec<Vec<usize>> = vec![Vec::new(); n];
    let mut atom_worker = BTreeMap::new();
    for (a, atom) in atoms.iter().enumerate() {
        lists[place[a]].extend(atom.members.iter().copied());
        atom_worker.insert(atom.key.clone(), place[a]);
    }
    for l in &mut lists {
        l.sort_unstable();
    }
    let named: Vec<Vec<&str>> = lists.iter().map(|l| l.iter().map(|&i| input.ids[i].as_str()).collect()).collect();
    let digest = plan_digest(&named);
    Ok(Plan {
        makespan: loads.iter().copied().max().unwrap_or(0) as f64 / 1e6,
        loads: loads.iter().map(|&l| l as f64 / 1e6).collect(),
        lpt_makespan: lpt_span as f64 / 1e6,
        sticky: use_sticky,
        kept: if use_sticky { kept } else { 0 },
        lists,
        atom_worker,
        digest,
    })
}

// -------------------------------------------------------------------------------------------------------------
// The controller's plan (review R-023 R1-R3: every decision of `DetScheduling` in Rust; `xdist.py` is the glue).

/// What the controller of a `--det -n N` session plans with.
#[derive(Clone, Debug, Default, serde::Deserialize)]
pub struct ControllerInput {
    /// Every collected test, in the serial order.
    pub ids: Vec<String>,
    /// The tests whose recorded result is reused (not sent to a worker; they still get a worker in the plan, at
    /// cost 0, so that the plan, its chunks and every test's worker are a function of the collection, not of the
    /// cache's hits: review R-023 F3, F4).
    #[serde(default)]
    pub hits: Vec<String>,
    /// The customer's `--dist` mode.
    pub dist: String,
    /// `xdist_group` of the tests that have one (`loadgroup`).
    #[serde(default)]
    pub groups: BTreeMap<String, String>,
    /// Worker ids (`gw0`, `gw1`, ...), in worker order.
    pub workers: Vec<String>,
    /// One-test atoms merged into same-file chunks (`chunk_test_atoms`, 0: off).
    pub chunk_div: usize,
    pub tolerance: f64,
    pub slack: f64,
    /// Recorded durations per test (`.detpy/durations.json`).
    #[serde(default)]
    pub history: BTreeMap<String, Vec<f64>>,
    /// The cache entry's duration per test.
    #[serde(default)]
    pub cached: BTreeMap<String, f64>,
    /// The previous plan (`.detpy/plan.json`), when there is one.
    #[serde(default)]
    pub previous: Option<serde_json::Value>,
    /// `--det-plan`: the plan to replay exactly.
    #[serde(default)]
    pub replay: Option<serde_json::Value>,
    /// Data edges (writer test, reader test) from the cache store: the reader read a file the writer wrote in an
    /// earlier session. When both run in this session on different workers and the writer comes first in the serial
    /// order, the reader waits for the writer to finish ([`ControllerPlan::waits`]), so it reads what a serial session
    /// gives it, not the outcome of a race between two processes (review R-023 F2).
    #[serde(default)]
    pub edges: Vec<(String, String)>,
}

/// The controller's plan.
#[derive(Clone, Debug, serde::Serialize)]
pub struct ControllerPlan {
    /// Per worker, the positions (into `ids`) it runs: the plan's list without the reused tests.
    pub send: Vec<Vec<usize>>,
    /// Per worker id, every test the plan gives it (reused ones included), in serial order.
    pub lists: BTreeMap<String, Vec<String>>,
    /// Every collected test's worker in this run.
    pub assign: BTreeMap<String, String>,
    /// Atom key -> worker index (the next run's `previous`).
    pub atoms: BTreeMap<String, usize>,
    pub mode: String,
    pub digest: String,
    pub makespan: f64,
    pub lpt_makespan: f64,
    pub loads: Vec<f64>,
    pub sticky: bool,
    pub kept: usize,
    pub replayed: bool,
    /// Why the previous plan was not used for stickiness ("" when it was, or there was none).
    pub previous_ignored: String,
    /// Reader test -> the writer tests it waits for: both sent this run, on different workers, the writer first in
    /// the serial order. A wait never deadlocks: every worker runs its list in the serial order and only waits for
    /// tests that come earlier in that order.
    pub waits: BTreeMap<String, Vec<String>>,
}

pub const PLAN_FORMAT: &str = "detpy-plan";

/// A test's cost (review R-023 R3): the median of its last 3 recorded durations, else the duration of its cache
/// entry, else unknown (the plan then uses the median of the known costs).
pub fn cost_precedence(history: Option<&[f64]>, cached: Option<f64>) -> Option<f64> {
    history.and_then(cost_of).or(cached)
}

/// `gwK` -> K.
pub fn worker_number(wid: &str) -> Option<usize> {
    wid.strip_prefix("gw").and_then(|k| k.parse().ok())
}

/// The assignment of a plan file to replay (`--det-plan`): `r:<nodeid>` -> worker index (review R-023 R2).
pub fn replay_assignment(plan: &serde_json::Value, workers: usize) -> Result<BTreeMap<String, usize>, String> {
    if plan.get("format").and_then(|f| f.as_str()) != Some(PLAN_FORMAT) {
        return Err("is not a detpy plan".into());
    }
    let mut assign: BTreeMap<String, String> = BTreeMap::new();
    if let Some(a) = plan.get("assign").and_then(|a| a.as_object()) {
        for (k, v) in a {
            if let Some(w) = v.as_str() {
                assign.insert(k.clone(), w.to_string());
            }
        }
    }
    if let Some(l) = plan.get("lists").and_then(|l| l.as_object()) {
        for (w, ids) in l {
            for id in ids.as_array().into_iter().flatten().filter_map(|x| x.as_str()) {
                assign.insert(id.to_string(), w.clone());
            }
        }
    }
    let mut out = BTreeMap::new();
    for (nid, wid) in assign {
        let Some(k) = worker_number(&wid) else { continue };
        if k >= workers {
            return Err(format!("the plan has worker {wid}, this run has {workers} workers"));
        }
        out.insert(format!("r:{nid}"), k);
    }
    Ok(out)
}

/// Whether the previous plan's placement is kept (stickiness), and its atom map (review R-023 R1, R2): only a plan
/// of the same number of workers and the same `--dist`, and not a replay (its atoms are pinned tests, not this
/// mode's atoms).
pub fn previous_atoms(prev: &serde_json::Value, workers: usize, dist: &str) -> Result<BTreeMap<String, usize>, String> {
    if prev.get("format").and_then(|f| f.as_str()) != Some(PLAN_FORMAT) {
        return Err("not a detpy plan".into());
    }
    if prev.get("workers").and_then(|w| w.as_u64()) != Some(workers as u64) {
        return Err("another number of workers".into());
    }
    if prev.get("dist").and_then(|d| d.as_str()) != Some(dist) {
        return Err("another --dist".into());
    }
    if prev.get("replayed").and_then(|r| r.as_bool()) == Some(true) {
        return Err("a replayed plan".into());
    }
    let mut out = BTreeMap::new();
    if let Some(a) = prev.get("atoms").and_then(|a| a.as_object()) {
        for (k, v) in a {
            if let Some(w) = v.as_u64() {
                out.insert(k.clone(), w as usize);
            }
        }
    }
    Ok(out)
}

/// The controller's plan: atoms from `--dist` (chunks for one-test atoms), costs (`cost_precedence`; reused tests
/// cost 0), stickiness to the previous plan or the exact replay of `--det-plan`, then the lists to send (without the
/// reused tests). The plan covers every collected test.
pub fn controller_plan(input: &ControllerInput) -> Result<ControllerPlan, String> {
    let n = input.workers.len();
    if n == 0 {
        return Err("a plan needs at least one worker".into());
    }
    let parsed = DistMode::parse(&input.dist);
    let mode = parsed.unwrap_or(DistMode::Test);
    let mode_name = if parsed.is_some() { input.dist.clone() } else { "load".to_string() };
    let hits: std::collections::HashSet<&str> = input.hits.iter().map(|s| s.as_str()).collect();
    let ids = &input.ids;
    // costs: reused tests 0; the others by precedence, unknown ones the median of the known ones
    let mut costs: Vec<Option<f64>> = ids
        .iter()
        .map(|id| {
            if hits.contains(id.as_str()) {
                Some(0.0)
            } else {
                cost_precedence(input.history.get(id).map(|v| v.as_slice()), input.cached.get(id).copied())
            }
        })
        .collect();
    let known: Vec<u64> = ids
        .iter()
        .zip(&costs)
        .filter(|(id, _)| !hits.contains(id.as_str()))
        .filter_map(|(_, c)| c.map(micros))
        .collect();
    let default = median(known).unwrap_or(1_000_000).max(1) as f64 / 1e6;
    for c in costs.iter_mut() {
        if c.is_none() {
            *c = Some(default);
        }
    }
    let replay = match &input.replay {
        Some(r) => Some(replay_assignment(r, n)?),
        None => None,
    };
    let atoms: Vec<String> = if replay.is_some() {
        // exact replay: every test is its own atom, pinned to its recorded worker
        ids.iter().map(|id| format!("r:{id}")).collect()
    } else {
        let a: Vec<String> =
            ids.iter().map(|id| atom_key(id, mode, input.groups.get(id).map(|g| g.as_str()))).collect();
        if mode == DistMode::Test && input.chunk_div > 0 {
            chunk_test_atoms(ids, &a, &costs, n, input.chunk_div)
        } else {
            a
        }
    };
    let mut previous_ignored = String::new();
    let (previous, tolerance) = match (&replay, &input.previous) {
        (Some(r), _) => (r.clone(), f64::INFINITY),
        (None, Some(p)) => match previous_atoms(p, n, &input.dist) {
            Ok(m) => (m, input.tolerance),
            Err(e) => {
                previous_ignored = e;
                (BTreeMap::new(), input.tolerance)
            }
        },
        (None, None) => (BTreeMap::new(), input.tolerance),
    };
    let p = plan(&PlanInput {
        ids: ids.clone(),
        atoms,
        costs,
        workers: n,
        previous,
        tolerance,
        slack: input.slack,
    })?;
    let mut lists = BTreeMap::new();
    let mut assign = BTreeMap::new();
    let mut send = Vec::with_capacity(n);
    for (w, l) in p.lists.iter().enumerate() {
        let wid = &input.workers[w];
        lists.insert(wid.clone(), l.iter().map(|&i| ids[i].clone()).collect());
        for &i in l {
            assign.insert(ids[i].clone(), wid.clone());
        }
        send.push(l.iter().copied().filter(|&i| !hits.contains(ids[i].as_str())).collect());
    }
    let pos: HashMap<&str, usize> = ids.iter().enumerate().map(|(i, id)| (id.as_str(), i)).collect();
    let mut waits: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (w, r) in &input.edges {
        let (Some(&pw), Some(&pr)) = (pos.get(w.as_str()), pos.get(r.as_str())) else { continue };
        if pw == pr || hits.contains(w.as_str()) || hits.contains(r.as_str()) || assign.get(w) == assign.get(r) {
            continue;
        }
        // the later of the two in the serial order waits for the earlier one: a reader after its writer reads what
        // the writer wrote; a writer after its reader (parallel-proof round 3) does not overwrite the file before
        // the reader read it. Every wait is for an earlier test: no deadlock.
        let (later, earlier) = if pw < pr { (r, w) } else { (w, r) };
        let v = waits.entry(later.clone()).or_default();
        if !v.contains(earlier) {
            v.push(earlier.clone());
            v.sort();
        }
    }
    Ok(ControllerPlan {
        send,
        lists,
        assign,
        atoms: p.atom_worker,
        mode: mode_name,
        digest: p.digest,
        makespan: p.makespan,
        lpt_makespan: p.lpt_makespan,
        loads: p.loads,
        sticky: p.sticky,
        kept: p.kept,
        replayed: replay.is_some(),
        previous_ignored,
        waits,
    })
}

/// A worker went down with `pending` tests of its list not finished (review R-023 R4: crash policy): the first is
/// the test it crashed in, the rest go to its replacement, in order (never a rebalance).
pub fn crash_split(pending: &[usize]) -> (Option<usize>, Vec<usize>) {
    match pending.split_first() {
        None => (None, Vec::new()),
        Some((c, rest)) => (Some(*c), rest.to_vec()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Deterministic pseudo-random numbers for the property tests (SplitMix64).
    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
            let mut z = self.0;
            z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
            z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
            z ^ (z >> 31)
        }
        fn below(&mut self, n: u64) -> u64 {
            self.next() % n
        }
    }

    fn random_input(rng: &mut Rng, n_tests: usize, workers: usize, mode: DistMode) -> PlanInput {
        let mut ids = Vec::new();
        let mut atoms = Vec::new();
        let mut costs = Vec::new();
        for i in 0..n_tests {
            let file = rng.below(5);
            let class = rng.below(3);
            let id = format!("tests/test_{file}.py::C{class}::test_{i}");
            let group = if rng.below(4) == 0 { Some(format!("grp{}", rng.below(3))) } else { None };
            atoms.push(atom_key(&id, mode, group.as_deref()));
            ids.push(id);
            costs.push(if rng.below(5) == 0 { None } else { Some(rng.below(5000) as f64 / 1000.0) });
        }
        PlanInput { ids, atoms, costs, workers, previous: BTreeMap::new(), tolerance: 0.1, slack: 0.0 }
    }

    fn assignment(input: &PlanInput, p: &Plan) -> BTreeMap<String, usize> {
        let mut m = BTreeMap::new();
        for (w, l) in p.lists.iter().enumerate() {
            for &i in l {
                m.insert(input.ids[i].clone(), w);
            }
        }
        m
    }

    #[test]
    fn same_input_same_plan() {
        let mut rng = Rng(7);
        for mode in [DistMode::Test, DistMode::Scope, DistMode::File, DistMode::Group] {
            for _ in 0..50 {
                let input = random_input(&mut rng, 60, 4, mode);
                assert_eq!(plan(&input).unwrap(), plan(&input).unwrap());
            }
        }
    }

    #[test]
    fn permutation_of_the_input_never_changes_the_assignment() {
        let mut rng = Rng(11);
        for mode in [DistMode::Test, DistMode::Scope, DistMode::File, DistMode::Group] {
            for _ in 0..50 {
                let input = random_input(&mut rng, 40, 3, mode);
                let base = plan(&input).unwrap();
                // a permutation of the collection (Fisher-Yates)
                let mut perm: Vec<usize> = (0..input.ids.len()).collect();
                for i in (1..perm.len()).rev() {
                    let j = rng.below(i as u64 + 1) as usize;
                    perm.swap(i, j);
                }
                let shuffled = PlanInput {
                    ids: perm.iter().map(|&i| input.ids[i].clone()).collect(),
                    atoms: perm.iter().map(|&i| input.atoms[i].clone()).collect(),
                    costs: perm.iter().map(|&i| input.costs[i]).collect(),
                    ..input.clone()
                };
                let other = plan(&shuffled).unwrap();
                assert_eq!(assignment(&input, &base), assignment(&shuffled, &other));
                assert_eq!(base.atom_worker, other.atom_worker);
            }
        }
    }

    #[test]
    fn lists_are_subsequences_of_the_serial_order_and_cover_every_test_once() {
        let mut rng = Rng(3);
        let input = random_input(&mut rng, 200, 4, DistMode::Group);
        let p = plan(&input).unwrap();
        let mut seen = vec![0; input.ids.len()];
        for l in &p.lists {
            assert!(l.windows(2).all(|w| w[0] < w[1]), "worker list not in serial order");
            for &i in l {
                seen[i] += 1;
            }
        }
        assert!(seen.iter().all(|&c| c == 1));
    }

    #[test]
    fn atoms_are_never_split() {
        let mut rng = Rng(5);
        for mode in [DistMode::Scope, DistMode::File, DistMode::Group] {
            let input = random_input(&mut rng, 120, 4, mode);
            let p = plan(&input).unwrap();
            let mut atom_of_worker: BTreeMap<&str, usize> = BTreeMap::new();
            for (w, l) in p.lists.iter().enumerate() {
                for &i in l {
                    let prev = atom_of_worker.insert(input.atoms[i].as_str(), w);
                    assert!(prev.is_none() || prev == Some(w), "atom {} split", input.atoms[i]);
                }
            }
        }
    }

    fn opt_makespan(costs: &[u64], workers: usize) -> u64 {
        // exhaustive search (small instances only)
        fn go(i: usize, costs: &[u64], loads: &mut Vec<u64>, best: &mut u64) {
            let cur = *loads.iter().max().unwrap();
            if cur >= *best {
                return;
            }
            if i == costs.len() {
                *best = cur;
                return;
            }
            for w in 0..loads.len() {
                loads[w] += costs[i];
                go(i + 1, costs, loads, best);
                loads[w] -= costs[i];
            }
        }
        let mut best = u64::MAX;
        go(0, costs, &mut vec![0; workers], &mut best);
        best
    }

    #[test]
    fn makespan_within_lpt_bound() {
        let mut rng = Rng(13);
        for _ in 0..200 {
            let n = 2 + rng.below(7) as usize;
            let workers = 2 + rng.below(2) as usize;
            let ids: Vec<String> = (0..n).map(|i| format!("t{i}")).collect();
            let costs: Vec<Option<f64>> = (0..n).map(|_| Some((1 + rng.below(1000)) as f64 / 100.0)).collect();
            let input = PlanInput {
                atoms: ids.iter().map(|i| atom_key(i, DistMode::Test, None)).collect(),
                ids,
                costs: costs.clone(),
                workers,
                previous: BTreeMap::new(),
                tolerance: 0.1,
                slack: 0.0,
            };
            let p = plan(&input).unwrap();
            let c: Vec<u64> = costs.iter().map(|c| micros(c.unwrap())).collect();
            let opt = opt_makespan(&c, workers) as f64 / 1e6;
            let max_atom = *c.iter().max().unwrap() as f64 / 1e6;
            assert!(p.makespan <= 4.0 / 3.0 * opt + max_atom + 1e-9, "{} vs opt {}", p.makespan, opt);
            assert!(p.makespan <= (4.0 / 3.0 - 1.0 / (3.0 * workers as f64)) * opt + 1e-6, "LPT bound violated");
        }
    }

    #[test]
    fn stickiness_keeps_previous_workers_within_tolerance() {
        let mut rng = Rng(17);
        let input = random_input(&mut rng, 100, 4, DistMode::File);
        let first = plan(&input).unwrap();
        // costs move a little: the previous placement is kept
        let mut moved = input.clone();
        moved.previous = first.atom_worker.clone();
        for c in moved.costs.iter_mut().flatten() {
            *c *= 1.0 + (rng.below(10) as f64) / 100.0;
        }
        let second = plan(&moved).unwrap();
        assert!(second.sticky);
        assert_eq!(second.atom_worker, first.atom_worker);
        assert!(second.makespan <= second.lpt_makespan * 1.1 + 1e-9);
        // tiny suites: within the absolute slack the previous placement stays
        let mut tiny = input.clone();
        tiny.previous = first.atom_worker.clone();
        for c in tiny.costs.iter_mut().flatten() {
            *c /= 1000.0;
        }
        tiny.slack = 1.0;
        let t = plan(&tiny).unwrap();
        assert!(t.sticky && t.atom_worker == first.atom_worker);
        // a previous placement that is far from balanced is dropped
        let mut skewed = input.clone();
        skewed.previous = first.atom_worker.keys().map(|k| (k.clone(), 0)).collect();
        let third = plan(&skewed).unwrap();
        assert!(!third.sticky);
        assert_eq!(third.makespan, third.lpt_makespan);
    }

    #[test]
    fn previous_plan_for_more_workers_is_ignored_for_unknown_slots() {
        let ids: Vec<String> = (0..8).map(|i| format!("t{i}")).collect();
        let mut previous = BTreeMap::new();
        for (i, id) in ids.iter().enumerate() {
            previous.insert(atom_key(id, DistMode::Test, None), i % 8);
        }
        let input = PlanInput {
            atoms: ids.iter().map(|i| atom_key(i, DistMode::Test, None)).collect(),
            costs: vec![Some(1.0); 8],
            ids,
            workers: 2,
            previous,
            tolerance: 0.1,
            slack: 0.0,
        };
        let p = plan(&input).unwrap();
        assert_eq!(p.lists.iter().map(|l| l.len()).sum::<usize>(), 8);
        assert!(p.makespan <= p.lpt_makespan * 1.1 + 1e-9);
    }

    #[test]
    fn atom_keys() {
        assert_eq!(atom_key("a/b.py::C::t[1]", DistMode::Scope, None), "s:a/b.py::C");
        assert_eq!(atom_key("a/b.py::t", DistMode::Scope, None), "s:a/b.py");
        assert_eq!(atom_key("a/b.py::C::t", DistMode::File, None), "f:a/b.py");
        assert_eq!(atom_key("a/b.py::t", DistMode::Group, Some("db")), "g:db");
        assert_eq!(atom_key("a/b.py::t", DistMode::Group, None), "t:a/b.py::t");
        assert_eq!(DistMode::parse("worksteal"), Some(DistMode::Test));
        assert_eq!(DistMode::parse("each"), None);
    }

    #[test]
    fn unknown_costs_use_the_median_and_empty_inputs_work() {
        let p = plan(&PlanInput { workers: 3, tolerance: 0.1, ..Default::default() }).unwrap();
        assert_eq!(p.lists, vec![Vec::<usize>::new(); 3]);
        assert!(plan(&PlanInput { workers: 0, ..Default::default() }).is_err());
        assert_eq!(cost_of(&[1.0, 5.0, 2.0, 3.0]), Some(3.0));
        assert_eq!(cost_of(&[]), None);
    }

    #[test]
    fn chunks_are_consecutive_same_file_and_bounded() {
        let mut rng = Rng(23);
        let mut input = random_input(&mut rng, 300, 4, DistMode::Group);
        // serial order: sort by id so files are contiguous
        let mut idx: Vec<usize> = (0..input.ids.len()).collect();
        idx.sort_by(|&a, &b| input.ids[a].cmp(&input.ids[b]));
        input.ids = idx.iter().map(|&i| input.ids[i].clone()).collect();
        input.atoms = idx.iter().map(|&i| input.atoms[i].clone()).collect();
        input.costs = idx.iter().map(|&i| input.costs[i]).collect();
        let chunked = chunk_test_atoms(&input.ids, &input.atoms, &input.costs, 4, 8);
        for (i, a) in input.atoms.iter().enumerate() {
            if !a.starts_with("t:") {
                assert_eq!(&chunked[i], a, "a group atom changed");
            } else {
                let first = chunked[i].strip_prefix("c:").unwrap();
                assert_eq!(first.split("::").next(), input.ids[i].split("::").next());
            }
        }
        // members of a chunk are consecutive
        let mut seen: BTreeMap<&str, usize> = BTreeMap::new();
        for (i, c) in chunked.iter().enumerate() {
            if let Some(&last) = seen.get(c.as_str()) {
                assert!(c.starts_with("g:") || last + 1 == i, "chunk {c} not consecutive");
            }
            seen.insert(c, i);
        }
        let n_chunks = chunked.iter().filter(|c| c.starts_with("c:")).collect::<std::collections::BTreeSet<_>>().len();
        assert!(n_chunks >= 4 * 8 / 2 && n_chunks < 300);
        input.atoms = chunked;
        let p = plan(&input).unwrap();
        assert!(p.makespan <= p.lpt_makespan + 1e-9);
        assert_eq!(chunk_test_atoms(&input.ids, &input.atoms, &input.costs, 4, 0), input.atoms);
        // durations never move a boundary
        let other: Vec<Option<f64>> = input.costs.iter().map(|c| c.map(|x| x * 7.0 + 1.0)).collect();
        let a = chunk_test_atoms(&input.ids, &input.atoms, &input.costs, 4, 8);
        let b = chunk_test_atoms(&input.ids, &input.atoms, &other, 4, 8);
        assert_eq!(a, b);
    }
    // -- review R-023 ------------------------------------------------------------------------------------------------
    fn files(n_files: usize, per: usize) -> Vec<String> {
        (0..n_files).flat_map(|f| (0..per).map(move |i| format!("tests/test_{f}.py::test_{i}"))).collect()
    }

    fn worker_of(ids: &[String], div: usize, n: usize, prev: &BTreeMap<String, usize>) -> (BTreeMap<String, usize>, Plan) {
        let atoms0: Vec<String> = ids.iter().map(|i| atom_key(i, DistMode::Test, None)).collect();
        let costs = vec![Some(1.0); ids.len()];
        let atoms = chunk_test_atoms(ids, &atoms0, &costs, n, div);
        let input = PlanInput { ids: ids.to_vec(), atoms, costs, workers: n, previous: prev.clone(), tolerance: 0.1, slack: 0.0 };
        let p = plan(&input).unwrap();
        (assignment(&input, &p), p)
    }

    #[test]
    fn r023_f4_chunks_do_not_move_when_tests_are_added_or_removed() {
        let mut rng = Rng(23);
        for _ in 0..40 {
            let n_files = 2 + rng.below(10) as usize;
            let per = 5 + rng.below(80) as usize;
            let ids = files(n_files, per);
            let atoms0: Vec<String> = ids.iter().map(|i| atom_key(i, DistMode::Test, None)).collect();
            let costs = vec![None; ids.len()];
            let a = chunk_test_atoms(&ids, &atoms0, &costs, 4, 8);
            // add one test at a random place, or remove one
            let k = rng.below(ids.len() as u64) as usize;
            let mut ids2 = ids.clone();
            let add = rng.below(2) == 0;
            if add {
                ids2.insert(k, format!("{}_new", ids[k]));
            } else {
                ids2.remove(k);
            }
            if chunk_target(ids.len(), 4, 8) != chunk_target(ids2.len(), 4, 8) {
                continue; // the suite crossed a power of two: every boundary may move (documented)
            }
            let atoms2: Vec<String> = ids2.iter().map(|i| atom_key(i, DistMode::Test, None)).collect();
            let b = chunk_test_atoms(&ids2, &atoms2, &vec![None; ids2.len()], 4, 8);
            let old: BTreeMap<&str, &str> = ids.iter().zip(&a).map(|(i, c)| (i.as_str(), c.as_str())).collect();
            let file_of = |id: &str| id.split("::").next().unwrap().to_string();
            let changed_file = file_of(&ids[k]);
            for (id, c) in ids2.iter().zip(&b) {
                if let Some(o) = old.get(id.as_str()) {
                    if file_of(id) != changed_file {
                        assert_eq!(o, c, "a chunk of another file moved");
                    }
                }
            }
        }
    }

    #[test]
    fn r023_f4_adding_one_test_keeps_every_other_test_on_its_worker() {
        let ids = files(8, 48);
        let (w1, p1) = worker_of(&ids, 8, 4, &BTreeMap::new());
        let mut ids2 = ids.clone();
        ids2.push("tests/test_7.py::test_new".into());
        let (w2, p2) = worker_of(&ids2, 8, 4, &p1.atom_worker);
        assert!(p2.sticky);
        assert_eq!(ids.iter().filter(|i| w1[*i] != w2[*i]).count(), 0);
        // and in the middle of a file
        let mut ids3 = ids.clone();
        ids3.insert(100, "tests/test_2.py::test_inserted".into());
        let (w3, _) = worker_of(&ids3, 8, 4, &p1.atom_worker);
        assert!(ids.iter().filter(|i| w1[*i] != w3[*i]).count() <= ids.len() / 20);
    }

    fn cinput(ids: &[String], hits: &[&str]) -> ControllerInput {
        ControllerInput {
            ids: ids.to_vec(),
            hits: hits.iter().map(|s| s.to_string()).collect(),
            dist: "load".into(),
            workers: vec!["gw0".into(), "gw1".into()],
            chunk_div: 8,
            tolerance: 0.1,
            slack: 1.0,
            ..Default::default()
        }
    }

    #[test]
    fn r023_controller_plan_places_every_test_and_sends_only_misses() {
        let ids = files(4, 10);
        let p = controller_plan(&cinput(&ids, &["tests/test_0.py::test_3"])).unwrap();
        assert_eq!(p.assign.len(), ids.len()); // the reused test has a worker too
        let sent: usize = p.send.iter().map(|l| l.len()).sum();
        assert_eq!(sent, ids.len() - 1);
        assert!(!p.send.iter().flatten().any(|&i| ids[i] == "tests/test_0.py::test_3"));
        // the plan's chunks and workers do not depend on which tests are reused (with the previous plan kept)
        let mut inp = cinput(&ids, &[]);
        let p0 = controller_plan(&inp).unwrap();
        inp.previous = Some(serde_json::json!({"format": PLAN_FORMAT, "workers": 2, "dist": "load", "atoms": p0.atoms}));
        inp.hits = ids.iter().step_by(2).cloned().collect(); // half of every chunk reused: loads stay balanced
        let p1 = controller_plan(&inp).unwrap();
        assert!(p1.sticky);
        assert_eq!(p0.assign, p1.assign);
        assert_eq!(p0.atoms.keys().collect::<Vec<_>>(), p1.atoms.keys().collect::<Vec<_>>());
    }

    #[test]
    fn r023_previous_plan_counts_only_for_the_same_workers_and_dist() {
        let ids = files(2, 5);
        let prev = |w: u64, d: &str, rep: bool| {
            serde_json::json!({"format": PLAN_FORMAT, "workers": w, "dist": d, "replayed": rep, "atoms": {}})
        };
        assert!(previous_atoms(&prev(2, "load", false), 2, "load").is_ok());
        assert_eq!(previous_atoms(&prev(3, "load", false), 2, "load").unwrap_err(), "another number of workers");
        assert_eq!(previous_atoms(&prev(2, "loadfile", false), 2, "load").unwrap_err(), "another --dist");
        assert_eq!(previous_atoms(&prev(2, "load", true), 2, "load").unwrap_err(), "a replayed plan");
        let mut inp = cinput(&ids, &[]);
        inp.previous = Some(prev(2, "loadfile", false));
        assert_eq!(controller_plan(&inp).unwrap().previous_ignored, "another --dist");
    }

    #[test]
    fn r023_replay_maps_workers_and_refuses_a_bigger_plan() {
        let ids = files(1, 3);
        let mut inp = cinput(&ids, &[]);
        inp.replay = Some(serde_json::json!({"format": PLAN_FORMAT, "lists": {"gw1": [ids[0]], "gw0": [ids[1], ids[2]]}}));
        let p = controller_plan(&inp).unwrap();
        assert!(p.replayed);
        assert_eq!(p.assign[&ids[0]], "gw1");
        assert_eq!(p.assign[&ids[1]], "gw0");
        inp.replay = Some(serde_json::json!({"format": PLAN_FORMAT, "lists": {"gw2": [ids[0]]}}));
        assert!(controller_plan(&inp).unwrap_err().contains("gw2"));
        inp.replay = Some(serde_json::json!({"lists": {}}));
        assert!(controller_plan(&inp).is_err());
    }

    #[test]
    fn r023_cost_precedence_history_then_cache_then_unknown() {
        assert_eq!(cost_precedence(Some(&[1.0, 5.0, 3.0]), Some(9.0)), Some(3.0));
        assert_eq!(cost_precedence(Some(&[]), Some(9.0)), Some(9.0));
        assert_eq!(cost_precedence(None, None), None);
    }

    #[test]
    fn round3_a_writer_after_its_reader_waits_for_the_reader_across_workers() {
        let ids: Vec<String> = vec!["tests/test_a.py::r".into(), "tests/test_b.py::w".into()];
        let mut inp = cinput(&ids, &[]);
        inp.dist = "loadfile".into();
        inp.edges = vec![("tests/test_b.py::w".into(), "tests/test_a.py::r".into())];
        let p = controller_plan(&inp).unwrap();
        let cross = p.assign["tests/test_a.py::r"] != p.assign["tests/test_b.py::w"];
        assert!(cross, "two files under loadfile with two workers");
        assert_eq!(p.waits.get("tests/test_b.py::w"), Some(&vec!["tests/test_a.py::r".to_string()]));
        assert!(!p.waits.contains_key("tests/test_a.py::r"));
    }

    #[test]
    fn r023_waits_only_across_workers_for_an_earlier_writer() {
        let ids: Vec<String> = vec!["tests/test_a.py::w".into(), "tests/test_b.py::r".into(), "tests/test_c.py::x".into()];
        let mut inp = cinput(&ids, &[]);
        inp.dist = "loadfile".into();
        inp.edges = vec![
            ("tests/test_a.py::w".into(), "tests/test_b.py::r".into()),
            ("tests/test_c.py::x".into(), "tests/test_a.py::w".into()), // writer after the reader: no wait
        ];
        let p = controller_plan(&inp).unwrap();
        let cross = p.assign["tests/test_a.py::w"] != p.assign["tests/test_b.py::r"];
        assert_eq!(p.waits.contains_key("tests/test_b.py::r"), cross);
        assert!(!p.waits.contains_key("tests/test_a.py::w"));
        // a reused writer does not run: nothing to wait for
        inp.hits = vec!["tests/test_a.py::w".into()];
        assert!(controller_plan(&inp).unwrap().waits.is_empty());
    }

    #[test]
    fn r023_crash_split() {
        assert_eq!(crash_split(&[]), (None, vec![]));
        assert_eq!(crash_split(&[4, 7, 9]), (Some(4), vec![7, 9]));
    }
}
