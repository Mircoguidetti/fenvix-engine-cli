//! End-of-session recording of the cache with proof: turn what the capture
//! observed per *context* (startup, between tests, collection of a file,
//! wider-scoped fixture setup, import of a module, a test) into one
//! [`Observed`] per test that ran, and record it in the [`Store`].
//!
//! The pytest shell gathers the session's capture into one [`Plan`] (plain
//! data, JSON) and calls [`record_session`]; this module holds the rules
//! (which contexts serve which test, what makes a test not cacheable) that
//! used to live in the shell's per-test Python loop. The rules are unchanged;
//! the order of every iteration that decides a reported reason (the first
//! offending path or flag) is the Python one.

use crate::proof::{env_all_digest, env_value_digest, reusable_outcome, Observed, Store};
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

/// One test that ran in the session (in run order).
#[derive(Clone, Debug, Default, Deserialize)]
pub struct TestRun {
    pub nodeid: String,
    /// Final outcome (passed, failed, skipped, xfailed, xpassed, error, unknown).
    pub outcome: String,
    /// Reports needed to rebuild a reused result (setup/call parts).
    #[serde(default)]
    pub report: serde_json::Value,
    #[serde(default)]
    pub fingerprint: String,
    #[serde(default)]
    pub duration: f64,
    /// Position of the test in the collected items (loaded-module bookkeeping).
    pub index: i64,
    /// Context names of the wider-scoped fixtures it used (sorted).
    #[serde(default)]
    pub fixtures: Vec<String>,
    /// The test's own file is a whole-content input (doctests, items without a Python object).
    #[serde(default)]
    pub whole: bool,
}

/// Everything the capture observed in one session, as plain data.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct Plan {
    /// Context names by index ("" startup, "s" between tests, "i" import time, "i|<rel>", "c|<rel>", "f|...", "t|<nodeid>").
    pub ctx_names: Vec<String>,
    /// Index of the import-time pseudo context ("i").
    pub import_ctx: u32,
    /// Repository files by file id (relative paths).
    pub fnames: Vec<String>,
    /// Store index of the facts of the current version of each known file (absent: no facts).
    pub file_ix: BTreeMap<String, u32>,
    /// Folded line buffer: per context (units `fid << 32 | unit`, file ids executed), and the import-time pair.
    pub per: Vec<(Vec<u64>, Vec<u64>)>,
    pub imp: (Vec<u64>, Vec<u64>),
    /// Per context, data reads in insertion order: (path key, dependency).
    #[serde(default)]
    pub data: HashMap<u32, Vec<(String, String)>>,
    /// Per context, environment variables read.
    #[serde(default)]
    pub env: HashMap<u32, Vec<String>>,
    /// Per context, flags ("spawn", "time", "rw:<abs path>", ...).
    #[serde(default)]
    pub flags: HashMap<u32, Vec<String>>,
    /// Absolute paths written in this session -> writer context indices.
    #[serde(default)]
    pub writers: HashMap<String, Vec<u32>>,
    /// Path keys written in this session -> writer context names (UTF-8 paths only).
    #[serde(default)]
    pub session_written: BTreeMap<String, Vec<String>>,
    /// Repository modules loaded, with the index of the test after which each was seen (-1: collection).
    #[serde(default)]
    pub loaded_order: Vec<(String, i64)>,
    /// Files loaded before the recorder started (whole-content inputs).
    #[serde(default)]
    pub preloaded: Vec<String>,
    /// Every executed or loaded repository file.
    #[serde(default)]
    pub needed: Vec<String>,
    /// Test files of every collected item, and their module names (from `sys.modules`).
    #[serde(default)]
    pub test_modules: BTreeMap<String, Option<String>>,
    pub tests: Vec<TestRun>,
    /// Results reused in this session (in reuse order): dropped when this session wrote one of their inputs.
    #[serde(default)]
    pub hits: Vec<String>,
    /// `root + os.sep`: absolute paths under it are keyed relative to the root.
    pub root_sep: String,
    pub control_urandom: bool,
    /// The virtual clock is on ("time" in the Level 0 controls).
    pub time_controlled: bool,
    pub epoch: i64,
    /// (path key, dependency) of the network cassette, when replaying from one.
    #[serde(default)]
    pub cassette: Option<(String, String)>,
    /// Environment at session start (sanitised).
    #[serde(default)]
    pub env0: BTreeMap<String, String>,
    pub config: String,
    pub runtime: String,
    pub run: String,
}

/// What [`record_session`] did.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Outcome {
    pub recorded: usize,
    /// (nodeid, reason, contexts searched for the first occurrence of the reason's cause) in run order.
    pub not_cached: Vec<(String, String, Vec<u32>)>,
    /// Reused results whose inputs this session then wrote: (nodeid, path), dropped from the store.
    pub stale: Vec<(String, String)>,
    /// The global contexts (inputs of every test).
    pub global_ctx: Vec<u32>,
}

/// The reason a set of flags makes a test not cacheable (`None`: cacheable as far as flags go).
pub fn uncacheable(flags: &BTreeSet<&str>, control_urandom: bool) -> Option<&'static str> {
    let has = |f: &str| flags.contains(f);
    if has("badpath") {
        return Some("reads a path that is not valid UTF-8");
    }
    if has("rclock") {
        return Some("real clock read outside the virtual clock");
    }
    if has("spawn") {
        return Some("subprocess");
    }
    if has("connect") {
        return Some("network connection");
    }
    if has("csock") {
        return Some("network socket opened outside Python (C extension)");
    }
    if has("dns") {
        return Some("host name lookup");
    }
    if has("net-record") {
        return Some("network recording (--det-record)");
    }
    if has("entropy") && !control_urandom {
        return Some("os entropy (not controlled; use --det-urandom)");
    }
    if has("proc") {
        return Some("reads /proc, /sys or /dev");
    }
    None
}

/// An insertion-ordered map with Python `dict.update` semantics (an existing key keeps its position).
#[derive(Clone, Default)]
struct OrderedData {
    items: Vec<(String, String)>,
    pos: HashMap<String, usize>,
}

impl OrderedData {
    fn update(&mut self, kv: &[(String, String)]) {
        for (k, v) in kv {
            match self.pos.get(k) {
                Some(&i) => self.items[i].1 = v.clone(),
                None => {
                    self.pos.insert(k.clone(), self.items.len());
                    self.items.push((k.clone(), v.clone()));
                }
            }
        }
    }
    fn set(&mut self, k: String, v: String) {
        self.update(&[(k, v)]);
    }
}

fn ctx_file(nodeid: &str) -> &str {
    nodeid.split("::").next().unwrap_or(nodeid)
}

fn basename(rel: &str) -> &str {
    rel.rsplit('/').next().unwrap_or(rel)
}

/// Record every test of the plan in `store` (and drop the stale reuses and the
/// not-cacheable tests' previous entries). The store is not saved.
pub fn record_session(store: &mut Store, plan: &Plan) -> Outcome {
    let mut out = Outcome::default();
    let names = &plan.ctx_names;
    let ctx_of: HashMap<&str, u32> = names.iter().enumerate().map(|(i, n)| (n.as_str(), i as u32)).collect();
    let fix: Vec<Option<u32>> = plan.fnames.iter().map(|r| plan.file_ix.get(r).copied()).collect();
    let file_of_ix: HashMap<u32, &str> = plan.file_ix.iter().map(|(r, &ix)| (ix, r.as_str())).collect();

    let units_of = |vals: &[u64], out: &mut BTreeSet<(u32, u32)>| {
        for &v in vals {
            let fid = (v >> 32) as usize;
            let u = (v & 0xFFFF_FFFF) as u32;
            if let Some(Some(ix)) = fix.get(fid) {
                out.insert((*ix, u));
            }
        }
    };
    // executed files that cannot be reduced to units and are not Python (skeleton == content): whole content
    let whole_ix: HashSet<u32> = fix
        .iter()
        .flatten()
        .copied()
        .filter(|&ix| store.files.get(ix as usize).is_some_and(|f| f.units.is_empty() && f.skeleton == f.content))
        .collect();
    let unparsable = |fids: &[u64], out: &mut BTreeSet<u32>| {
        for &fid in fids {
            if let Some(Some(ix)) = fix.get(fid as usize) {
                if whole_ix.contains(ix) {
                    out.insert(*ix);
                }
            }
        }
    };
    let empty_pair: (Vec<u64>, Vec<u64>) = (Vec::new(), Vec::new());
    let per = |c: u32| plan.per.get(c as usize).unwrap_or(&empty_pair);

    let needed: BTreeSet<&str> = plan.needed.iter().map(|s| s.as_str()).collect();
    let conftests: HashSet<&str> = needed.iter().copied().filter(|r| basename(r) == "conftest.py").collect();
    let test_files: BTreeSet<&str> = plan.test_modules.keys().map(|s| s.as_str()).collect();
    // import graph: test modules imported by any loaded module are shared, others only serve their own tests
    let mut imported: HashSet<String> = HashSet::new();
    for rel in &needed {
        if let Some(&ix) = plan.file_ix.get(*rel) {
            if let Some(f) = store.files.get(ix as usize) {
                imported.extend(f.imports.iter().cloned());
            }
        }
    }
    let mut shared: HashSet<&str> = HashSet::new();
    for (tf, m) in &plan.test_modules {
        if let Some(m) = m.as_deref() {
            if m.is_empty() {
                continue;
            }
            let last = m.rsplit('.').next().unwrap_or(m);
            if imported.contains(m) || imported.contains(last) {
                shared.insert(tf.as_str());
            }
        }
    }

    // global contexts: startup, between tests, import time
    let g_ctx: Vec<u32> = ["", "s"].iter().filter_map(|c| ctx_of.get(c).copied()).collect();
    let mut g_units = BTreeSet::new();
    units_of(&plan.imp.0, &mut g_units);
    let mut g_unparsable = BTreeSet::new();
    unparsable(&plan.imp.1, &mut g_unparsable);
    for &c in &g_ctx {
        units_of(&per(c).0, &mut g_units);
        unparsable(&per(c).1, &mut g_unparsable);
    }
    // import-time reads of a test module that no other module imports serve only its own tests
    let mut own_import: HashMap<&str, u32> = HashMap::new();
    for tf in &test_files {
        if !shared.contains(tf) {
            if let Some(&i) = ctx_of.get(format!("i|{tf}").as_str()) {
                own_import.insert(tf, i);
            }
        }
    }
    let own_import_ix: HashSet<u32> = own_import.values().copied().collect();
    let mut g_ctx_all: Vec<u32> = g_ctx.clone();
    g_ctx_all.push(plan.import_ctx);
    for (i, n) in names.iter().enumerate() {
        let i = i as u32;
        if n.starts_with("i|") && !own_import_ix.contains(&i) {
            g_ctx_all.push(i);
        }
    }
    let mut g_data = OrderedData::default();
    let mut g_env: BTreeSet<&str> = BTreeSet::new();
    let mut g_flags: BTreeSet<&str> = BTreeSet::new();
    for c in &g_ctx_all {
        if let Some(d) = plan.data.get(c) {
            g_data.update(d);
        }
        if let Some(e) = plan.env.get(c) {
            g_env.extend(e.iter().map(|s| s.as_str()));
        }
        if let Some(f) = plan.flags.get(c) {
            g_flags.extend(f.iter().map(|s| s.as_str()).filter(|f| *f != "proc"));
        }
    }
    out.global_ctx = g_ctx_all.clone();

    let pre_ix: BTreeSet<u32> = plan.preloaded.iter().filter_map(|r| plan.file_ix.get(r).copied()).collect();
    // written: by earlier sessions (store) and by this one
    let mut written: HashMap<String, BTreeSet<String>> =
        store.written.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
    for (p, w) in &plan.session_written {
        written.entry(p.clone()).or_default().extend(w.iter().cloned());
    }
    // persisted for the next sessions: paths in the repository only (temporary files have fresh names)
    for (p, w) in &plan.session_written {
        if !p.starts_with('/') {
            store.written.entry(p.clone()).or_default().extend(w.iter().cloned());
        }
    }
    // results reused in this session whose input files code of this session then wrote: drop them
    if !plan.session_written.is_empty() {
        for nid in &plan.hits {
            let Some(e) = store.tests.get(nid) else { continue };
            let own = format!("t|{nid}");
            let mut stale = None;
            for (path, _) in &e.data {
                if let Some(w) = plan.session_written.get(path) {
                    if !w.iter().all(|x| *x == own) {
                        stale = Some(path.clone());
                        break;
                    }
                }
            }
            if let Some(p) = stale {
                store.remove(nid);
                out.stale.push((nid.clone(), p));
            }
        }
    }
    let key = |p: &str| -> String {
        p.strip_prefix(plan.root_sep.as_str()).unwrap_or(p).to_string()
    };
    let in_scope = |rel: &str, own: &str| -> bool {
        if test_files.contains(rel) {
            return rel == own || shared.contains(rel);
        }
        if conftests.contains(rel) {
            let d = match rel.rfind('/') {
                Some(i) => &rel[..i],
                None => "",
            };
            return d.is_empty() || own == d || (own.starts_with(d) && own[d.len()..].starts_with('/'));
        }
        true
    };
    let env_all = env_all_digest(&plan.env0);

    for t in &plan.tests {
        let nid = t.nodeid.as_str();
        if !reusable_outcome(&t.outcome) {
            store.remove(nid);
            out.not_cached.push((nid.to_string(), format!("outcome {}", t.outcome), Vec::new()));
            continue;
        }
        let own = ctx_file(nid);
        let mut ctxs: Vec<u32> = Vec::new();
        let tname = format!("t|{nid}");
        let cname = format!("c|{own}");
        for n in [tname.as_str(), cname.as_str()].into_iter().chain(t.fixtures.iter().map(|s| s.as_str())) {
            if let Some(&i) = ctx_of.get(n) {
                ctxs.push(i);
            }
        }
        if let Some(&i) = own_import.get(own) {
            ctxs.push(i);
        }
        let mut flags = g_flags.clone();
        let mut data = g_data.clone();
        let mut env = g_env.clone();
        let mut units: BTreeSet<(u32, u32)> = BTreeSet::new();
        let mut content: BTreeSet<u32> = pre_ix.clone();
        content.extend(g_unparsable.iter().copied());
        for &c in &ctxs {
            if let Some(f) = plan.flags.get(&c) {
                flags.extend(f.iter().map(|s| s.as_str()));
            }
            if let Some(d) = plan.data.get(&c) {
                data.update(d);
            }
            if let Some(e) = plan.env.get(&c) {
                env.extend(e.iter().map(|s| s.as_str()));
            }
            units_of(&per(c).0, &mut units);
            unparsable(&per(c).1, &mut content);
        }
        let mut why: Option<String> = uncacheable(&flags, plan.control_urandom).map(|s| s.to_string());
        let mut where_ctx: Vec<u32> = Vec::new();
        if why.is_some() {
            where_ctx = g_ctx_all.iter().chain(ctxs.iter()).copied().collect();
        } else {
            // writers credited to the test: its own contexts and the global ones (startup, between tests,
            // import time), whose code is an input of every test
            let credited: HashSet<u32> = ctxs.iter().chain(g_ctx_all.iter()).copied().collect();
            let cnames: HashSet<&str> = credited.iter().filter_map(|&c| names.get(c as usize)).map(|s| s.as_str()).collect();
            for f in &flags {
                if let Some(p) = f.strip_prefix("rw:") {
                    let ok = plan.writers.get(p).map(|w| w.iter().all(|c| credited.contains(c))).unwrap_or(true);
                    if !ok {
                        why = Some(format!("reads a file another test or fixture wrote: {}", key(p)));
                        break;
                    }
                }
            }
            if why.is_none() {
                for (path, _) in &data.items {
                    if let Some(w) = written.get(path) {
                        if !w.is_empty() && !w.iter().all(|x| cnames.contains(x.as_str())) {
                            why = Some(format!("reads a file another test or fixture wrote: {path}"));
                            break;
                        }
                    }
                }
            }
        }
        if why.is_none() && flags.contains("net-replay") {
            if let Some((k, d)) = &plan.cassette {
                data.set(k.clone(), d.clone());
            }
        }
        if let Some(w) = why {
            store.remove(nid);
            out.not_cached.push((nid.to_string(), w, where_ctx));
            continue;
        }
        let idx = t.index;
        let mut skeleton: BTreeSet<u32> = BTreeSet::new();
        let mut hooks: BTreeSet<u32> = BTreeSet::new();
        for (rel, seen_at) in &plan.loaded_order {
            if *seen_at > idx {
                continue;
            }
            let Some(&ix) = plan.file_ix.get(rel) else { continue };
            if conftests.contains(rel.as_str()) {
                hooks.insert(ix);
            }
            if in_scope(rel, own) {
                skeleton.insert(ix);
            }
        }
        for &(ix, u) in &g_units {
            if let Some(rel) = file_of_ix.get(&ix) {
                if conftests.contains(rel) || in_scope(rel, own) {
                    units.insert((ix, u));
                }
            }
        }
        if t.whole {
            if let Some(&ix) = plan.file_ix.get(own) {
                content.insert(ix);
            }
        }
        let clock = flags.contains("time");
        if clock && !plan.time_controlled {
            store.remove(nid);
            out.not_cached.push((nid.to_string(), "real clock".to_string(), Vec::new()));
            continue;
        }
        let epoch = if clock { Some(plan.epoch) } else { None };
        let env_deps: Vec<(String, String)> = env
            .iter()
            .map(|&n| {
                if n == "*" {
                    ("*".to_string(), env_all.clone())
                } else {
                    (n.to_string(), env_value_digest(plan.env0.get(n).map(|s| s.as_str())))
                }
            })
            .collect();
        store.record(
            nid,
            Observed {
                outcome: t.outcome.clone(),
                report: t.report.clone(),
                fingerprint: t.fingerprint.clone(),
                duration: t.duration,
                run: plan.run.clone(),
                config: plan.config.clone(),
                runtime: plan.runtime.clone(),
                epoch,
                env: env_deps,
                data: data.items,
                content: content.into_iter().collect(),
                skeleton: skeleton.into_iter().collect(),
                hooks: hooks.into_iter().collect(),
                units: units.into_iter().collect(),
            },
        );
        out.recorded += 1;
    }
    out
}
