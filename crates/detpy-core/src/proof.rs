//! Cache with proof: reuse a test's previous result only when every input it
//! depended on is unchanged.
//!
//! The producer (the pytest shell) records, for every test that ran, the
//! inputs the test actually used:
//!
//! * **code**: the functions it executed (one [`Unit`] per outermost function
//!   of a file, hashed as its syntax tree), the module-level structure
//!   (*skeleton*: the module with function bodies removed) of every repository
//!   module it had loaded, the pytest hook surface of every loaded conftest, and
//!   the whole content of files that cannot be reduced to units (doctest
//!   modules, modules loaded before the recorder started, non-Python sources);
//! * **data**: files it opened for reading (content digest; read-write opens
//!   included), paths it found missing, directories it listed;
//! * **environment variables** it read (value digest; `*` = the whole
//!   environment);
//! * **runtime identity** (interpreter, stdlib, platform, installed packages)
//!   and **configuration** (pytest options and ini, plugins, Level 0 controls)
//!   as two digests;
//! * the virtual clock's epoch, only when the test read the clock.
//!
//! [`Entry::key`] folds all of these into one digest: the *receipt*. A later
//! session asks [`Checker::check`] whether every recorded input still has its
//! recorded digest; file contents are hashed once per session and a changed
//! file is compared at the level of its units and skeleton (facts supplied by
//! the producer for changed files only).

use crate::fingerprint::digest_bytes;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

pub const STORE_VERSION: u32 = 1;

/// A shared string: the data dependencies of every test of a session repeat the same global reads (paths and
/// digests), stored once in memory (serialized as plain strings).
pub type Str = std::sync::Arc<str>;
const STORE_FILE: &str = "proof-cache.json";

/// One outermost function of a source file: qualified name, body line range
/// (inclusive) and digest of its syntax tree (decorators and signature are in
/// the skeleton).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Unit {
    pub q: String,
    pub a: u32,
    pub b: u32,
    pub d: String,
}

/// Facts about one version (content digest) of one source file.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CodeFile {
    /// Path relative to the repository root, `/`-separated.
    pub path: String,
    /// Digest of the file's bytes.
    pub content: String,
    /// Digest of the module-level structure. Equal to `content` for a file
    /// that is not valid Python.
    pub skeleton: String,
    /// Digest of the pytest hook surface (top-level `pytest_*` functions and
    /// `pytest_plugins`), used for conftest files.
    pub hooks: String,
    pub units: Vec<Unit>,
    /// Absolute module names this file imports (static, any scope).
    #[serde(default)]
    pub imports: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Entry {
    pub outcome: String,
    /// What the shell needs to rebuild the reports of a reused result.
    #[serde(default)]
    pub report: serde_json::Value,
    pub fingerprint: String,
    pub duration: f64,
    pub run: String,
    pub key: String,
    pub config: String,
    pub runtime: String,
    pub epoch: Option<i64>,
    /// (variable, value digest or "-" when unset); "*" = the whole environment.
    pub env: Vec<(String, String)>,
    /// (absolute path, dependency): "f:<digest>", "missing", "d:<digest>", "s:<kind>".
    pub data: Vec<(Str, Str)>,
    /// Set ids (see [`Store::sets`]) of code files whose whole content, skeleton
    /// or hook surface is a dependency.
    pub content: u32,
    pub skeleton: u32,
    pub hooks: u32,
    /// Flat (file index, unit index) pairs.
    pub units: Vec<u32>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Store {
    pub version: u32,
    pub files: Vec<CodeFile>,
    pub sets: Vec<Vec<u32>>,
    pub tests: BTreeMap<String, Entry>,
    /// Paths that code run by a session wrote (repository-relative or absolute) and the contexts that wrote
    /// them: a test that reads one is cached only if every writer is its own code (test, its fixtures).
    #[serde(default)]
    pub written: BTreeMap<String, BTreeSet<String>>,
    #[serde(skip)]
    file_ix: HashMap<(String, String), u32>,
    #[serde(skip)]
    set_ix: HashMap<Vec<u32>, u32>,
}

/// What a session observed about one test (input of [`Store::record`]).
#[derive(Clone, Debug, Default)]
pub struct Observed {
    pub outcome: String,
    pub report: serde_json::Value,
    pub fingerprint: String,
    pub duration: f64,
    pub run: String,
    pub config: String,
    pub runtime: String,
    pub epoch: Option<i64>,
    pub env: Vec<(String, String)>,
    pub data: Vec<(Str, Str)>,
    pub content: Vec<u32>,
    pub skeleton: Vec<u32>,
    pub hooks: Vec<u32>,
    pub units: Vec<(u32, u32)>,
}

fn push_part(buf: &mut Vec<u8>, part: &str) {
    buf.extend_from_slice(&(part.len() as u64).to_le_bytes());
    buf.extend_from_slice(part.as_bytes());
}

/// Digest of a file's bytes, `None` when it cannot be read (missing, a directory, ...).
pub fn file_digest(path: &Path) -> Option<String> {
    let mut f = fs::File::open(path).ok()?;
    if f.metadata().ok()?.is_dir() {
        return None;
    }
    let mut h = blake3::Hasher::new();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        match f.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => {
                h.update(&buf[..n]);
            }
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return None,
        }
    }
    let hex = h.finalize().to_hex();
    Some(hex.as_str()[..32].to_string())
}

/// Digest of a directory listing: sorted entry names joined by NUL (the same
/// as `detpy._core.digest(b"\0".join(sorted(os.listdir(path))))` in Python).
pub fn listing_digest(path: &Path) -> Option<String> {
    let mut names: Vec<Vec<u8>> = Vec::new();
    for e in fs::read_dir(path).ok()? {
        let e = e.ok()?;
        names.push(os_bytes(&e.file_name()));
    }
    names.sort();
    Some(digest_bytes(&names.join(&b'\0')).short())
}

#[cfg(unix)]
fn os_bytes(s: &std::ffi::OsStr) -> Vec<u8> {
    use std::os::unix::ffi::OsStrExt;
    s.as_bytes().to_vec()
}

#[cfg(not(unix))]
fn os_bytes(s: &std::ffi::OsStr) -> Vec<u8> {
    s.to_string_lossy().as_bytes().to_vec()
}

/// "file", "dir", "other" or "missing" (follows symlinks).
pub fn stat_kind(path: &Path) -> &'static str {
    match fs::metadata(path) {
        Ok(m) if m.is_file() => "file",
        Ok(m) if m.is_dir() => "dir",
        Ok(_) => "other",
        Err(_) => "missing",
    }
}

/// Current dependency string of a recorded data dependency of the same kind.
pub fn data_now(path: &Path, recorded: &str) -> String {
    if recorded == "missing" || recorded.starts_with("f:") {
        match file_digest(path) {
            Some(d) => format!("f:{d}"),
            None if path.exists() => "unreadable".into(),
            None => "missing".into(),
        }
    } else if recorded.starts_with("d:") {
        listing_digest(path).map(|d| format!("d:{d}")).unwrap_or_else(|| "missing".into())
    } else if recorded.starts_with("s:") {
        format!("s:{}", stat_kind(path))
    } else {
        "unknown".into()
    }
}

/// Digest of an environment variable's value ("-" when unset).
pub fn env_value_digest(value: Option<&str>) -> String {
    match value {
        None => "-".into(),
        Some(v) => digest_bytes(v.as_bytes()).short(),
    }
}

/// Digest of a whole environment (the `*` dependency).
pub fn env_all_digest(env: &BTreeMap<String, String>) -> String {
    let mut buf = Vec::new();
    for (k, v) in env {
        push_part(&mut buf, k);
        push_part(&mut buf, v);
    }
    digest_bytes(&buf).short()
}

impl Store {
    pub fn new() -> Store {
        Store { version: STORE_VERSION, ..Default::default() }
    }

    pub fn path_in(dir: &Path) -> PathBuf {
        dir.join(STORE_FILE)
    }

    /// Load the store of `dir`; an absent, unreadable or older-version store is empty.
    pub fn load(dir: &Path) -> Store {
        let mut s = fs::read(Self::path_in(dir))
            .ok()
            .and_then(|b| serde_json::from_slice::<Store>(&b).ok())
            .filter(|s| s.version == STORE_VERSION)
            .unwrap_or_else(Store::new);
        s.reindex();
        s
    }

    fn reindex(&mut self) {
        self.file_ix =
            self.files.iter().enumerate().map(|(i, f)| ((f.path.clone(), f.content.clone()), i as u32)).collect();
        self.set_ix = self.sets.iter().enumerate().map(|(i, s)| (s.clone(), i as u32)).collect();
    }

    /// Index of the facts of `path` at `content`, if known.
    pub fn file_index(&self, path: &str, content: &str) -> Option<u32> {
        self.file_ix.get(&(path.to_string(), content.to_string())).copied()
    }

    /// Add (or find) the facts of one file version; returns its index.
    pub fn add_file(&mut self, f: CodeFile) -> u32 {
        let k = (f.path.clone(), f.content.clone());
        if let Some(&i) = self.file_ix.get(&k) {
            return i;
        }
        let i = self.files.len() as u32;
        self.files.push(f);
        self.file_ix.insert(k, i);
        i
    }

    fn intern(&mut self, mut set: Vec<u32>) -> u32 {
        set.sort_unstable();
        set.dedup();
        if let Some(&i) = self.set_ix.get(&set) {
            return i;
        }
        let i = self.sets.len() as u32;
        self.sets.push(set.clone());
        self.set_ix.insert(set, i);
        i
    }

    pub fn set(&self, id: u32) -> &[u32] {
        self.sets.get(id as usize).map(|v| v.as_slice()).unwrap_or(&[])
    }

    /// Record (replace) the entry of `nodeid`; returns its key.
    pub fn record(&mut self, nodeid: &str, mut o: Observed) -> String {
        o.env.sort();
        o.env.dedup();
        o.data.sort();
        o.data.dedup();
        o.units.sort_unstable();
        o.units.dedup();
        let content = self.intern(o.content);
        let skeleton = self.intern(o.skeleton);
        let hooks = self.intern(o.hooks);
        let mut e = Entry {
            outcome: o.outcome,
            report: o.report,
            fingerprint: o.fingerprint,
            duration: o.duration,
            run: o.run,
            key: String::new(),
            config: o.config,
            runtime: o.runtime,
            epoch: o.epoch,
            env: o.env,
            data: o.data,
            content,
            skeleton,
            hooks,
            units: o.units.into_iter().flat_map(|(f, u)| [f, u]).collect(),
        };
        e.key = self.key_of(nodeid, &e);
        let k = e.key.clone();
        self.tests.insert(nodeid.to_string(), e);
        k
    }

    pub fn remove(&mut self, nodeid: &str) -> bool {
        self.tests.remove(nodeid).is_some()
    }

    /// The receipt digest of an entry: every recorded input at the level it is
    /// compared (skeleton, unit and hook digests, not raw file bytes, so a
    /// reformatted but equivalent file keeps the key).
    pub fn key_of(&self, nodeid: &str, e: &Entry) -> String {
        let mut b = Vec::new();
        push_part(&mut b, "detpy-proof-1");
        push_part(&mut b, nodeid);
        push_part(&mut b, &e.config);
        push_part(&mut b, &e.runtime);
        push_part(&mut b, &e.epoch.map(|x| x.to_string()).unwrap_or_default());
        for (k, v) in &e.env {
            push_part(&mut b, k);
            push_part(&mut b, v);
        }
        push_part(&mut b, "|data");
        for (k, v) in &e.data {
            push_part(&mut b, k);
            push_part(&mut b, v);
        }
        let file = |i: u32| self.files.get(i as usize);
        for (tag, id) in [("|content", e.content), ("|skeleton", e.skeleton), ("|hooks", e.hooks)] {
            push_part(&mut b, tag);
            let mut parts: Vec<(&str, &str)> = self
                .set(id)
                .iter()
                .filter_map(|&i| file(i))
                .map(|f| {
                    (
                        f.path.as_str(),
                        match tag {
                            "|content" => f.content.as_str(),
                            "|skeleton" => f.skeleton.as_str(),
                            _ => f.hooks.as_str(),
                        },
                    )
                })
                .collect();
            parts.sort();
            for (p, d) in parts {
                push_part(&mut b, p);
                push_part(&mut b, d);
            }
        }
        push_part(&mut b, "|units");
        let mut units: Vec<(&str, &str, &str)> = e
            .units
            .chunks(2)
            .filter_map(|c| {
                let f = file(c[0])?;
                let u = f.units.get(c[1] as usize)?;
                Some((f.path.as_str(), u.q.as_str(), u.d.as_str()))
            })
            .collect();
        units.sort();
        for (p, q, d) in units {
            push_part(&mut b, p);
            push_part(&mut b, q);
            push_part(&mut b, d);
        }
        digest_bytes(&b).short()
    }

    /// Drop facts and sets no entry refers to; remap indices.
    pub fn compact(&mut self) {
        let mut used_sets = vec![false; self.sets.len()];
        let mut used_files = vec![false; self.files.len()];
        for e in self.tests.values() {
            for id in [e.content, e.skeleton, e.hooks] {
                if let Some(u) = used_sets.get_mut(id as usize) {
                    *u = true;
                }
            }
            for c in e.units.chunks(2) {
                if let Some(u) = used_files.get_mut(c[0] as usize) {
                    *u = true;
                }
            }
        }
        for (i, s) in self.sets.iter().enumerate() {
            if used_sets[i] {
                for &f in s {
                    if let Some(u) = used_files.get_mut(f as usize) {
                        *u = true;
                    }
                }
            }
        }
        let mut fmap = vec![u32::MAX; self.files.len()];
        let mut files = Vec::new();
        for (i, f) in self.files.drain(..).enumerate() {
            if used_files[i] {
                fmap[i] = files.len() as u32;
                files.push(f);
            }
        }
        let mut smap = vec![u32::MAX; self.sets.len()];
        let mut sets = Vec::new();
        for (i, s) in self.sets.drain(..).enumerate() {
            if used_sets[i] {
                smap[i] = sets.len() as u32;
                sets.push(s.into_iter().map(|f| fmap[f as usize]).collect());
            }
        }
        for e in self.tests.values_mut() {
            e.content = smap[e.content as usize];
            e.skeleton = smap[e.skeleton as usize];
            e.hooks = smap[e.hooks as usize];
            for c in e.units.chunks_mut(2) {
                c[0] = fmap[c[0] as usize];
            }
        }
        self.files = files;
        self.sets = sets;
        self.reindex();
    }

    /// Copy the entries of `touched` (or their removal) into `disk`, remapping
    /// file and set indices; merge the written paths.
    pub fn merge_into(&self, disk: &mut Store, touched: &BTreeSet<String>) {
        // file index here -> file index on disk, each file looked up (and copied) once
        let mut fmap: Vec<Option<u32>> = vec![None; self.files.len()];
        let mut remap_file = |i: u32, disk: &mut Store| -> u32 {
            match fmap.get_mut(i as usize) {
                Some(Some(j)) => *j,
                Some(slot) => {
                    let j = disk.add_file(self.files[i as usize].clone());
                    *slot = Some(j);
                    j
                }
                None => u32::MAX,
            }
        };
        let mut smap: BTreeMap<u32, u32> = BTreeMap::new();
        for nid in touched {
            match self.tests.get(nid) {
                None => {
                    disk.tests.remove(nid);
                }
                Some(e) => {
                    let mut e = e.clone();
                    for id in [&mut e.content, &mut e.skeleton, &mut e.hooks] {
                        if let Some(&j) = smap.get(id) {
                            *id = j;
                            continue;
                        }
                        let set: Vec<u32> = self.set(*id).iter().map(|&f| remap_file(f, disk)).collect();
                        let j = disk.intern(set);
                        smap.insert(*id, j);
                        *id = j;
                    }
                    for c in e.units.chunks_mut(2) {
                        c[0] = remap_file(c[0], disk);
                    }
                    disk.tests.insert(nid.clone(), e);
                }
            }
        }
        for (p, w) in &self.written {
            disk.written.entry(p.clone()).or_default().extend(w.iter().cloned());
        }
    }

    /// Merge this session's changes (`touched` entries, written paths) into the
    /// store on disk under a lock, so that concurrent sessions (one process per
    /// test file, pytest-xdist workers) sharing a directory lose nothing.
    pub fn save_merged(&self, dir: &Path, touched: &BTreeSet<String>) -> io::Result<()> {
        fs::create_dir_all(dir)?;
        let _lock = DirLock::acquire(dir)?;
        let mut disk = Store::load(dir);
        self.merge_into(&mut disk, touched);
        disk.save(dir)
    }

    /// Compact and write atomically to `dir`.
    pub fn save(&mut self, dir: &Path) -> io::Result<()> {
        self.compact();
        fs::create_dir_all(dir)?;
        let path = Self::path_in(dir);
        let tmp = path.with_extension(format!("tmp{}", std::process::id()));
        fs::write(&tmp, serde_json::to_vec(self).map_err(io::Error::other)?)?;
        fs::rename(tmp, path)
    }
}

struct DirLock(PathBuf);

impl DirLock {
    fn acquire(dir: &Path) -> io::Result<DirLock> {
        let path = dir.join(".lock");
        let start = std::time::Instant::now();
        loop {
            match fs::OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(_) => return Ok(DirLock(path)),
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                    let stale = fs::metadata(&path)
                        .and_then(|m| m.modified())
                        .ok()
                        .and_then(|t| t.elapsed().ok())
                        .map(|age| age.as_secs() > 300)
                        .unwrap_or(false);
                    if stale {
                        let _ = fs::remove_file(&path);
                        continue;
                    }
                    if start.elapsed().as_secs() > 600 {
                        return Err(io::Error::new(io::ErrorKind::TimedOut, "cache directory lock"));
                    }
                    std::thread::sleep(std::time::Duration::from_millis(20));
                }
                Err(e) => return Err(e),
            }
        }
    }
}

impl Drop for DirLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

/// The state of the current session that recorded inputs are compared with.
#[derive(Clone, Debug, Default)]
pub struct Current {
    pub root: PathBuf,
    pub config: String,
    pub runtime: String,
    pub epoch: i64,
    pub env: BTreeMap<String, String>,
}

/// Why a test cannot reuse its result.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Miss {
    pub kind: &'static str,
    pub detail: String,
}

/// What was checked for a reused result.
#[derive(Clone, Debug, PartialEq, Default, Serialize)]
pub struct Receipt {
    pub key: String,
    pub run: String,
    pub outcome: String,
    pub fingerprint: String,
    pub duration: f64,
    pub config: String,
    pub runtime: String,
    pub epoch: Option<i64>,
    pub n_units: usize,
    pub n_skeleton: usize,
    pub n_hooks: usize,
    pub n_content: usize,
    pub n_data: usize,
    pub n_env: usize,
    /// Code files whose bytes changed but whose units and skeleton used by the test did not.
    pub n_changed_files_proven: usize,
}

#[derive(Default)]
pub struct Checker {
    pub cur: Current,
    content_now: HashMap<String, Option<String>>,
    data_now: HashMap<(String, char), String>,
    /// Facts of the current version of code files whose content changed.
    pub fresh: HashMap<String, CodeFile>,
}

/// Outcomes whose results may be reused: never a failure.
pub fn reusable_outcome(outcome: &str) -> bool {
    matches!(outcome, "passed" | "skipped" | "xfailed")
}

impl Checker {
    pub fn new(cur: Current) -> Self {
        Checker { cur, content_now: HashMap::new(), data_now: HashMap::new(), fresh: HashMap::new() }
    }

    /// Current content digest of a code file (memoised for the session).
    pub fn content(&mut self, rel: &str) -> Option<String> {
        if let Some(d) = self.content_now.get(rel) {
            return d.clone();
        }
        let d = file_digest(&self.cur.root.join(rel));
        self.content_now.insert(rel.to_string(), d.clone());
        d
    }

    /// Paths of known code files whose content changed and still exist: the
    /// producer must supply their current facts with [`Checker::set_fresh`].
    pub fn changed_code_files(&mut self, store: &Store) -> Vec<(String, String)> {
        let mut seen = std::collections::BTreeMap::new();
        let mut paths: Vec<String> = store.files.iter().map(|f| f.path.clone()).collect();
        paths.sort();
        paths.dedup();
        for p in paths {
            if let Some(d) = self.content(&p) {
                let known = store.file_index(&p, &d).is_some();
                if !known {
                    seen.insert(p, d);
                }
            }
        }
        seen.into_iter().collect()
    }

    pub fn set_fresh(&mut self, f: CodeFile) {
        self.fresh.insert(f.path.clone(), f);
    }

    /// Facts of the current version of `rel`: from the store when the content
    /// is known, else from [`Checker::fresh`].
    fn now_facts<'s>(&'s mut self, store: &'s Store, rel: &str) -> Option<&'s CodeFile> {
        let d = self.content(rel)?;
        if let Some(i) = store.file_index(rel, &d) {
            return store.files.get(i as usize);
        }
        self.fresh.get(rel).filter(|f| f.content == d)
    }

    fn data(&mut self, path: &str, recorded: &str) -> String {
        let kind = recorded.chars().next().unwrap_or('?');
        let kind = if recorded == "missing" { 'f' } else { kind };
        let k = (path.to_string(), kind);
        if let Some(v) = self.data_now.get(&k) {
            return v.clone();
        }
        let v = data_now(&self.cur.root.join(path), recorded);
        self.data_now.insert(k, v.clone());
        v
    }

    /// Reuse decision for `nodeid`.
    pub fn check(&mut self, store: &Store, nodeid: &str) -> Result<Receipt, Miss> {
        let Some(e) = store.tests.get(nodeid) else {
            return Err(Miss { kind: "new", detail: "no recorded result".into() });
        };
        if !reusable_outcome(&e.outcome) {
            return Err(Miss { kind: "failed-before", detail: format!("recorded outcome {}", e.outcome) });
        }
        if e.config != self.cur.config {
            return Err(Miss { kind: "config", detail: "pytest/detpy configuration or plugins changed".into() });
        }
        if e.runtime != self.cur.runtime {
            return Err(Miss { kind: "runtime", detail: "interpreter, platform or installed packages changed".into() });
        }
        if let Some(ep) = e.epoch {
            if ep != self.cur.epoch {
                return Err(Miss { kind: "clock", detail: "the test read the clock and the epoch changed".into() });
            }
        }
        for (k, v) in &e.env {
            let now = if k == "*" {
                env_all_digest(&self.cur.env)
            } else {
                env_value_digest(self.cur.env.get(k).map(|s| s.as_str()))
            };
            if &now != v {
                return Err(Miss { kind: "env", detail: format!("environment variable {k}") });
            }
        }
        for (p, dep) in &e.data {
            if *self.data(p, dep) != **dep {
                return Err(Miss { kind: "data", detail: format!("{p} ({})", dep.split(':').next().unwrap_or("")) });
            }
        }
        let mut proven = std::collections::BTreeSet::new();
        // whole-content dependencies
        for &i in store.set(e.content) {
            let Some(f) = store.files.get(i as usize) else { continue };
            if self.content(&f.path).as_deref() != Some(f.content.as_str()) {
                return Err(Miss { kind: "code", detail: format!("{} (content)", f.path) });
            }
        }
        for (tag, id) in [("skeleton", e.skeleton), ("hooks", e.hooks)] {
            for &i in store.set(id) {
                let Some(f) = store.files.get(i as usize) else { continue };
                let now = self.content(&f.path);
                if now.as_deref() == Some(f.content.as_str()) {
                    continue;
                }
                let path = f.path.clone();
                let ok = match self.now_facts(store, &path) {
                    None => false,
                    Some(n) => {
                        if tag == "skeleton" {
                            n.skeleton == f.skeleton
                        } else {
                            n.hooks == f.hooks
                        }
                    }
                };
                if !ok {
                    let what = if tag == "skeleton" { "module level" } else { "pytest hooks" };
                    return Err(Miss { kind: "code", detail: format!("{path} ({what})") });
                }
                proven.insert(path);
            }
        }
        for c in e.units.chunks(2) {
            let Some(f) = store.files.get(c[0] as usize) else { continue };
            let Some(u) = f.units.get(c[1] as usize) else { continue };
            if self.content(&f.path).as_deref() == Some(f.content.as_str()) {
                continue;
            }
            let path = f.path.clone();
            let ok = self
                .now_facts(store, &path)
                .map(|n| n.units.iter().any(|x| x.q == u.q && x.d == u.d))
                .unwrap_or(false);
            if !ok {
                return Err(Miss { kind: "code", detail: format!("{path}::{}", u.q) });
            }
            proven.insert(path);
        }
        Ok(Receipt {
            key: store.key_of(nodeid, e),
            run: e.run.clone(),
            outcome: e.outcome.clone(),
            fingerprint: e.fingerprint.clone(),
            duration: e.duration,
            config: e.config.clone(),
            runtime: e.runtime.clone(),
            epoch: e.epoch,
            n_units: e.units.len() / 2,
            n_skeleton: store.set(e.skeleton).len(),
            n_hooks: store.set(e.hooks).len(),
            n_content: store.set(e.content).len(),
            n_data: e.data.len(),
            n_env: e.env.len(),
            n_changed_files_proven: proven.len(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unit(q: &str, d: &str) -> Unit {
        Unit { q: q.into(), a: 1, b: 2, d: d.into() }
    }

    fn setup() -> (tempfile::TempDir, Store, Current) {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().to_path_buf();
        fs::write(root.join("m.py"), "def f():\n    return 1\n").unwrap();
        fs::write(root.join("data.txt"), "x").unwrap();
        let mut s = Store::new();
        let content = file_digest(&root.join("m.py")).unwrap();
        let fi = s.add_file(CodeFile {
            path: "m.py".into(),
            content,
            skeleton: "S1".into(),
            hooks: "H1".into(),
            units: vec![unit("f", "F1"), unit("g", "G1")],
            imports: vec![],
        });
        let mut env = BTreeMap::new();
        env.insert("HOME".to_string(), "/root".to_string());
        let cur = Current { root: root.clone(), config: "C".into(), runtime: "R".into(), epoch: 5, env };
        s.record(
            "t::a",
            Observed {
                outcome: "passed".into(),
                config: "C".into(),
                runtime: "R".into(),
                env: vec![("HOME".into(), env_value_digest(Some("/root")))],
                data: vec![("data.txt".into(), format!("f:{}", file_digest(&root.join("data.txt")).unwrap()).into())],
                skeleton: vec![fi],
                units: vec![(fi, 0)],
                ..Default::default()
            },
        );
        (dir, s, cur)
    }

    #[test]
    fn hit_when_nothing_changed_and_key_is_stable() {
        let (_d, s, cur) = setup();
        let mut c = Checker::new(cur);
        let r = c.check(&s, "t::a").unwrap();
        assert_eq!(r.key, s.tests["t::a"].key);
        assert_eq!((r.n_units, r.n_skeleton, r.n_data, r.n_env), (1, 1, 1, 1));
        assert_eq!(c.check(&s, "t::new").unwrap_err().kind, "new");
    }

    #[test]
    fn changed_unit_used_by_the_test_misses_other_unit_hits() {
        let (d, s, cur) = setup();
        fs::write(d.path().join("m.py"), "def f():\n    return 2\n").unwrap();
        let mut c = Checker::new(cur.clone());
        let changed = c.changed_code_files(&s);
        assert_eq!(changed.len(), 1);
        let content = changed[0].1.clone();
        // f changed
        c.set_fresh(CodeFile {
            path: "m.py".into(),
            content: content.clone(),
            skeleton: "S1".into(),
            hooks: "H1".into(),
            units: vec![unit("f", "F2"), unit("g", "G1")],
            imports: vec![],
        });
        let m = c.check(&s, "t::a").unwrap_err();
        assert_eq!((m.kind, m.detail.as_str()), ("code", "m.py::f"));
        // only g changed: proven unchanged for the test
        let mut c = Checker::new(cur.clone());
        c.set_fresh(CodeFile {
            path: "m.py".into(),
            content: content.clone(),
            skeleton: "S1".into(),
            hooks: "H1".into(),
            units: vec![unit("f", "F1"), unit("g", "G2")],
            imports: vec![],
        });
        let r = c.check(&s, "t::a").unwrap();
        assert_eq!(r.n_changed_files_proven, 1);
        assert_eq!(r.key, s.tests["t::a"].key);
        // module level changed
        let mut c = Checker::new(cur);
        c.set_fresh(CodeFile {
            path: "m.py".into(),
            content,
            skeleton: "S2".into(),
            hooks: "H1".into(),
            units: vec![unit("f", "F1"), unit("g", "G1")],
            imports: vec![],
        });
        assert_eq!(c.check(&s, "t::a").unwrap_err().detail, "m.py (module level)");
    }

    #[test]
    fn data_env_runtime_config_clock() {
        let (d, s, cur) = setup();
        fs::write(d.path().join("data.txt"), "y").unwrap();
        assert_eq!(Checker::new(cur.clone()).check(&s, "t::a").unwrap_err().kind, "data");
        fs::write(d.path().join("data.txt"), "x").unwrap();
        let mut c2 = cur.clone();
        c2.env.insert("HOME".into(), "/home/u".into());
        assert_eq!(Checker::new(c2).check(&s, "t::a").unwrap_err().kind, "env");
        let mut c3 = cur.clone();
        c3.env.remove("HOME");
        assert_eq!(Checker::new(c3).check(&s, "t::a").unwrap_err().kind, "env");
        let mut c4 = cur.clone();
        c4.runtime = "R2".into();
        assert_eq!(Checker::new(c4).check(&s, "t::a").unwrap_err().kind, "runtime");
        let mut c5 = cur.clone();
        c5.config = "C2".into();
        assert_eq!(Checker::new(c5).check(&s, "t::a").unwrap_err().kind, "config");
        // the epoch matters only to tests that read the clock
        let mut c6 = cur.clone();
        c6.epoch = 6;
        assert!(Checker::new(c6.clone()).check(&s, "t::a").is_ok());
        let mut s2 = s.clone();
        let mut e = s2.tests["t::a"].clone();
        e.epoch = Some(5);
        s2.tests.insert("t::a".into(), e);
        assert_eq!(Checker::new(c6).check(&s2, "t::a").unwrap_err().kind, "clock");
        assert!(Checker::new(cur).check(&s2, "t::a").is_ok());
    }

    #[test]
    fn failure_is_never_reused() {
        let (_d, mut s, cur) = setup();
        s.record("t::f", Observed { outcome: "failed".into(), config: "C".into(), runtime: "R".into(), ..Default::default() });
        assert_eq!(Checker::new(cur).check(&s, "t::f").unwrap_err().kind, "failed-before");
    }

    #[test]
    fn missing_file_and_listing_dependencies() {
        let (d, mut s, cur) = setup();
        let root = d.path();
        fs::create_dir(root.join("dir")).unwrap();
        fs::write(root.join("dir/a"), "").unwrap();
        s.record(
            "t::b",
            Observed {
                outcome: "passed".into(),
                config: "C".into(),
                runtime: "R".into(),
                data: vec![
                    ("nope.txt".into(), "missing".into()),
                    ("dir".into(), format!("d:{}", listing_digest(&root.join("dir")).unwrap()).into()),
                ],
                ..Default::default()
            },
        );
        assert!(Checker::new(cur.clone()).check(&s, "t::b").is_ok());
        fs::write(root.join("dir/b"), "").unwrap();
        assert_eq!(Checker::new(cur.clone()).check(&s, "t::b").unwrap_err().detail, "dir (d)");
        fs::remove_file(root.join("dir/b")).unwrap();
        fs::write(root.join("nope.txt"), "").unwrap();
        assert_eq!(Checker::new(cur).check(&s, "t::b").unwrap_err().kind, "data");
    }

    #[test]
    fn listing_digest_matches_python_convention() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join("b"), "").unwrap();
        fs::write(d.path().join("a"), "").unwrap();
        assert_eq!(listing_digest(d.path()).unwrap(), digest_bytes(b"a\0b").short());
    }

    #[test]
    fn concurrent_sessions_merge() {
        let (d, s, cur) = setup();
        let dir = d.path().join("cache");
        s.clone().save(&dir).unwrap();
        // session 2 records t::x, session 3 removes t::a; both start from the same store
        let mut s2 = Store::load(&dir);
        let fi = s2.add_file(CodeFile {
            path: "n.py".into(),
            content: "c".into(),
            skeleton: "s".into(),
            hooks: "h".into(),
            units: vec![unit("u", "U")],
            imports: vec![],
        });
        s2.record("t::x", Observed { outcome: "passed".into(), skeleton: vec![fi], units: vec![(fi, 0)], ..Default::default() });
        s2.written.entry("out.txt".into()).or_default().insert("t|t::x".into());
        let mut s3 = Store::load(&dir);
        s3.remove("t::a");
        s2.save_merged(&dir, &["t::x".to_string()].into_iter().collect()).unwrap();
        s3.save_merged(&dir, &["t::a".to_string()].into_iter().collect()).unwrap();
        let m = Store::load(&dir);
        assert_eq!(m.tests.keys().collect::<Vec<_>>(), vec!["t::x"]);
        assert_eq!(m.key_of("t::x", &m.tests["t::x"]), s2.tests["t::x"].key);
        assert!(m.written["out.txt"].contains("t|t::x"));
        let _ = cur;
    }

    #[test]
    fn save_load_compact_roundtrip() {
        let (d, mut s, cur) = setup();
        s.add_file(CodeFile {
            path: "unused.py".into(),
            content: "x".into(),
            skeleton: "x".into(),
            hooks: "x".into(),
            units: vec![],
            imports: vec![],
        });
        let key = s.tests["t::a"].key.clone();
        let dir = d.path().join("cache");
        s.save(&dir).unwrap();
        let l = Store::load(&dir);
        assert_eq!(l.files.len(), 1);
        assert_eq!(l.key_of("t::a", &l.tests["t::a"]), key);
        assert_eq!(Checker::new(cur).check(&l, "t::a").unwrap().key, key);
    }
}
