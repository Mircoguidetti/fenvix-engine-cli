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

/// Locality for one-test atoms (`load`, `worksteal`): consecutive tests of the same file are merged into chunk atoms
/// of at most `total cost / (workers * div)` (a test above that is a chunk of its own). A plan over single tests
/// scatters every module over every worker: each worker then sets up every module-scoped fixture, and a test loses
/// more of its serial in-process predecessors (placement). Merging atoms never splits one: atoms that are not
/// one-test atoms (`t:` keys) are left as they are. Returns the new atom keys (`c:<first test id>`).
pub fn chunk_test_atoms(ids: &[String], atoms: &[String], costs: &[Option<f64>], workers: usize, div: usize) -> Vec<String> {
    if div == 0 || workers == 0 || ids.is_empty() {
        return atoms.to_vec();
    }
    let known: Vec<u64> = costs.iter().flatten().map(|&c| micros(c)).collect();
    let default = median(known).unwrap_or(1_000_000).max(1);
    let cost: Vec<u64> = costs.iter().map(|c| c.map(micros).unwrap_or(default).max(1)).collect();
    let cap = (cost.iter().sum::<u64>() / (workers as u64 * div as u64)).max(1);
    let file = |id: &str| id.split("::").next().unwrap_or(id).to_string();
    let mut out = Vec::with_capacity(ids.len());
    let mut cur: Option<(String, String, u64)> = None; // (chunk key, file, cost so far)
    for (i, id) in ids.iter().enumerate() {
        if !atoms[i].starts_with("t:") {
            cur = None;
            out.push(atoms[i].clone());
            continue;
        }
        let f = file(id);
        match &mut cur {
            Some((key, cf, c)) if *cf == f && *c + cost[i] <= cap => {
                *c += cost[i];
                out.push(key.clone());
            }
            _ => {
                let key = format!("c:{id}");
                cur = Some((key.clone(), f, cost[i]));
                out.push(key);
            }
        }
    }
    out
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
    }
}
