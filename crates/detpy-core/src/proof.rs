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
    /// Contexts of the wider-scoped fixtures the test used when it was recorded (`f|scope|baseid|name`): a path one
    /// of them wrote is the test's own write (a reused result is not invalidated by it). Not part of the key.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub fixtures: Vec<String>,
    /// Where the result was recorded: "" (a serial session) or [`PLACEMENT_PARALLEL`] (a worker of a parallel
    /// session). Until the proof of docs/PARALLEL-PROOF-DESIGN.md 3.3 (P5) exists, a serial session does not reuse a
    /// parallel result (2.5: its in-process predecessors were not its serial ones). Not part of the key.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub placement: String,
}

/// [`Entry::placement`] of a result recorded by a worker of a parallel (`-n`) session.
pub const PLACEMENT_PARALLEL: &str = "parallel";

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
    /// Together edges (writer test, reader test): the reader read a file the writer wrote in the same session
    /// (review R-023 F2). A parallel plan runs the two in one worker, in the serial order, so the reader sees what
    /// a serial session gives it (not the race of two processes).
    #[serde(default, skip_serializing_if = "BTreeSet::is_empty")]
    pub edges: BTreeSet<(String, String)>,
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
    pub fixtures: Vec<String>,
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

/// Paths the import system probes for module `name` in directory `dir` (`FileFinder`): the package directory, its
/// `__init__` with every suffix, and the module with every suffix (`importlib.machinery.all_suffixes()`). Ported from
/// `claude/dep-verdict-abjcfw` (d972a3e) onto the Rust store.
pub fn import_candidates(dir: &str, name: &str, suffixes: &[String]) -> Vec<String> {
    let d = dir.trim_end_matches('/');
    let mut out = Vec::with_capacity(2 * suffixes.len() + 1);
    out.push(format!("{d}/{name}"));
    for s in suffixes {
        out.push(format!("{d}/{name}/__init__{s}"));
    }
    for s in suffixes {
        out.push(format!("{d}/{name}{s}"));
    }
    out
}

/// Paths pytest looks for between the project root and a test file's directory (`rel_dir`, relative, "" for the
/// root): `conftest.py` (plugins, fixtures) and `__init__.py` (the test module's package and import name).
pub fn collection_candidates(rel_dir: &str) -> Vec<String> {
    let mut out = vec!["conftest.py".to_string(), "__init__.py".to_string()];
    let mut cur = String::new();
    for part in rel_dir.split('/').filter(|p| !p.is_empty()) {
        if !cur.is_empty() {
            cur.push('/');
        }
        cur.push_str(part);
        out.push(format!("{cur}/conftest.py"));
        out.push(format!("{cur}/__init__.py"));
    }
    out
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

/// Variables left out of the whole-environment digest: `_` (the shell's last command path, which changes with the
/// way pytest is started) and the variables pytest-xdist sets per worker and per run. A test that reads one of them
/// by name still depends on its value (docs/PARALLEL-PROOF-DESIGN.md 2.5).
pub const ENV_ALL_EXCLUDED: [&str; 4] = ["_", "PYTEST_XDIST_TESTRUNUID", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"];

/// Digest of a whole environment (the `*` dependency).
pub fn env_all_digest(env: &BTreeMap<String, String>) -> String {
    let mut buf = Vec::new();
    for (k, v) in env {
        if ENV_ALL_EXCLUDED.contains(&k.as_str()) {
            continue;
        }
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
            fixtures: {
                let mut f = o.fixtures;
                f.sort();
                f.dedup();
                f
            },
            placement: String::new(),
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
        self.key_of_with(nodeid, e, &mut FxMap::default())
    }

    /// The bytes of one (content | skeleton | hooks) part of a key: the set's sorted (path, digest) pairs.
    fn key_part(&self, tag: &str, id: u32) -> Vec<u8> {
        let mut b = Vec::new();
        let file = |i: u32| self.files.get(i as usize);
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
        b
    }

    /// `key_of` with the set parts memoised in `parts` (they are shared by many entries of one session).
    pub fn key_of_with(&self, nodeid: &str, e: &Entry, parts_memo: &mut FxMap<(u8, u32), Vec<u8>>) -> String {
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
        for (t, (tag, id)) in [("|content", e.content), ("|skeleton", e.skeleton), ("|hooks", e.hooks)].into_iter().enumerate() {
            push_part(&mut b, tag);
            let part = parts_memo.entry((t as u8, id)).or_insert_with(|| self.key_part(tag, id));
            b.extend_from_slice(part);
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
        disk.edges.extend(self.edges.iter().cloned());
    }

    /// Note that `reader` read a path writer context `writer` wrote (a together edge when the writer is a test).
    pub fn add_edge(&mut self, writer: &str, reader: &str) {
        if let Some(x) = writer.strip_prefix("t|") {
            if x != reader {
                self.edges.insert((x.to_string(), reader.to_string()));
            }
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
        self.written.retain(|k, _| persist_written(k));
        fs::create_dir_all(dir)?;
        let path = Self::path_in(dir);
        let tmp = path.with_extension(format!("tmp{}", std::process::id()));
        fs::write(&tmp, serde_json::to_vec(self).map_err(io::Error::other)?)?;
        fs::rename(tmp, path)
    }
}

// -------------------------------------------------------------------------------------------------------------
// Parallel sessions (pytest-xdist under --det): workers record shards, the controller merges them once.

pub const SHARD_FORMAT: &str = "detpy-cache-shard";
pub const SHARD_VERSION: u32 = 1;

/// What one worker recorded: its entries (a store holding only the tests it touched), the touched ids (an id
/// touched but absent is a removal), the wider-scoped fixture contexts of each test that ran, and every path key
/// code of the worker wrote with its writer contexts.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Shard {
    pub format: String,
    pub version: u32,
    pub worker: String,
    pub store: Store,
    pub touched: Vec<String>,
    #[serde(default)]
    pub fixtures: BTreeMap<String, Vec<String>>,
    #[serde(default)]
    pub written: BTreeMap<String, Vec<String>>,
}

impl Shard {
    pub fn load(path: &Path) -> io::Result<Shard> {
        let s: Shard = serde_json::from_slice(&fs::read(path)?).map_err(io::Error::other)?;
        if s.format != SHARD_FORMAT || s.version != SHARD_VERSION {
            return Err(io::Error::other(format!("not a detpy cache shard: {}", path.display())));
        }
        Ok(s)
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        if let Some(d) = path.parent() {
            fs::create_dir_all(d)?;
        }
        let tmp = path.with_extension(format!("tmp{}", std::process::id()));
        fs::write(&tmp, serde_json::to_vec(self).map_err(io::Error::other)?)?;
        fs::rename(tmp, path)
    }
}

fn parent_key(key: &str) -> Option<&str> {
    key.rfind('/').map(|i| if i == 0 { "/" } else { &key[..i] })
}

/// A writer context that is not the test's own code: another test, or a wider-scoped fixture the test does not use.
/// Startup, between-tests, import-time and collection contexts run in every worker (every worker imports and
/// collects the whole suite): the worker's own rule already covers them.
fn foreign(w: &str, own: &str, fixtures: &[String]) -> bool {
    (w.starts_with("t|") && w != own) || (w.starts_with("f|") && !fixtures.iter().any(|f| f == w))
}

/// The cross-worker write rule: the first input of a test (path key, writer) that a foreign context of the session
/// wrote, in any worker. `written`: path key -> writer contexts of every worker; `dirs`: parent key -> writer
/// contexts of the paths written in it (a listing whose directory another test wrote into). Same rule as a serial
/// session's (`record::record_session`: "reads a file another test or fixture wrote"), extended across processes;
/// it does not depend on which worker ran first.
pub fn foreign_write(
    nodeid: &str,
    fixtures: &[String],
    data: &[(Str, Str)],
    written: &BTreeMap<String, BTreeSet<String>>,
    dirs: &BTreeMap<String, BTreeSet<String>>,
) -> Option<(String, String)> {
    let own = format!("t|{nodeid}");
    for (key, dep) in data {
        if let Some(ws) = written.get(&**key) {
            if let Some(w) = ws.iter().find(|w| foreign(w, &own, fixtures)) {
                return Some((key.to_string(), w.clone()));
            }
        }
        if dep.starts_with("d:") {
            if let Some(ws) = dirs.get(&**key) {
                if let Some(w) = ws.iter().find(|w| foreign(w, &own, fixtures)) {
                    return Some((key.to_string(), w.clone()));
                }
            }
        }
    }
    None
}

/// Whether a path key a session wrote is kept in the store for later sessions ([`Store::written`]): a path in the
/// repository always; a path outside it (absolute key) while it exists. Review R-023 F2: a file outside the
/// repository that one test writes and another reads survives the session, and a later session in which the writer is
/// reused (it does not run, so it writes nothing) must still know who wrote it; temporary files that are gone again
/// are not kept (their names are fresh in every session).
pub fn persist_written(key: &str) -> bool {
    !key.starts_with('/') || fs::symlink_metadata(key).is_ok()
}

/// A writer context that is not a reused result's own code (review R-023 F2): another test (with `rank`, only one
/// that comes before it in the serial order; a test the order does not know counts), or a wider-scoped fixture the
/// test did not use when it was recorded. Startup, between-tests, import-time and collection contexts run in every
/// session alike: not foreign.
pub fn foreign_to_entry(w: &str, nodeid: &str, e: &Entry, rank: Option<&HashMap<String, usize>>) -> bool {
    if let Some(x) = w.strip_prefix("t|") {
        if x == nodeid {
            return false;
        }
        match rank {
            None => true,
            Some(r) => match (r.get(x), r.get(nodeid)) {
                (Some(a), Some(b)) => a < b,
                _ => true,
            },
        }
    } else if w.starts_with("f|") {
        !e.fixtures.iter().any(|f| f == w)
    } else {
        false
    }
}

/// The reused results of a parallel session whose input a test of the same session that comes before them in the
/// serial order (or a fixture they did not use) wrote: `(nodeid, path key, writer)`, in `order`. The controller
/// decided them before any worker ran; a serial session would have run the writer first, so their recorded result is
/// not the serial result. The controller runs them again (review R-023 F2).
pub fn hits_with_written_inputs(
    store: &Store,
    hits: &[String],
    order: &[String],
    written: &BTreeMap<String, BTreeSet<String>>,
    dirs: &BTreeMap<String, BTreeSet<String>>,
) -> Vec<(String, String, String)> {
    let rank: HashMap<String, usize> = order.iter().enumerate().map(|(i, n)| (n.clone(), i)).collect();
    let hit_set: BTreeSet<&str> = hits.iter().map(|s| s.as_str()).collect();
    let mut out = Vec::new();
    for nid in order.iter().filter(|n| hit_set.contains(n.as_str())) {
        let Some(e) = store.tests.get(nid) else { continue };
        let found = e.data.iter().find_map(|(key, dep)| {
            let mut ws: Vec<&String> = written.get(&**key).map(|w| w.iter().collect()).unwrap_or_default();
            if dep.starts_with("d:") {
                ws.extend(dirs.get(&**key).into_iter().flatten());
            }
            ws.into_iter().find(|w| foreign_to_entry(w, nid, e, Some(&rank))).map(|w| (key.to_string(), w.clone()))
        });
        if let Some((k, w)) = found {
            out.push((nid.clone(), k, w));
        }
    }
    out
}

/// What [`merge_shards`] did.
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct ShardMerge {
    pub merged: usize,
    /// (nodeid, reason) of entries the cross-worker rule dropped.
    pub dropped: Vec<(String, String)>,
    /// (nodeid, path key) of results reused in this session whose inputs the session wrote: dropped from the store.
    pub stale: Vec<(String, String)>,
    /// Together edges noted by this merge (writer test, reader test).
    pub edges: usize,
}

/// The writer union of a session's shards: path key -> contexts, and parent key -> contexts.
pub fn writer_union(shards: &[Shard]) -> (BTreeMap<String, BTreeSet<String>>, BTreeMap<String, BTreeSet<String>>) {
    let mut written: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut dirs: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for s in shards {
        for (k, ws) in &s.written {
            written.entry(k.clone()).or_default().extend(ws.iter().cloned());
            if let Some(p) = parent_key(k) {
                dirs.entry(p.to_string()).or_default().extend(ws.iter().cloned());
            }
        }
    }
    (written, dirs)
}

/// Apply the cross-worker rule to the shards (in place: a dropped entry stays touched, so it is removed from the
/// store), then merge them into the store of `dir` under the directory lock, once. `hits`: results the controller
/// reused in this session; one whose input any code of the session wrote is dropped from the store (as a serial
/// session drops it).
pub fn merge_shards(dir: &Path, shards: &mut [Shard], hits: &[String]) -> io::Result<ShardMerge> {
    shards.sort_by(|a, b| a.worker.cmp(&b.worker));
    let (written, dirs) = writer_union(shards);
    let mut out = ShardMerge::default();
    let mut edges: BTreeSet<(String, String)> = BTreeSet::new();
    for s in shards.iter_mut() {
        let mut drop = Vec::new();
        for (nid, e) in &s.store.tests {
            let fx = s.fixtures.get(nid).map(|v| v.as_slice()).unwrap_or(&[]);
            if let Some((key, w)) = foreign_write(nid, fx, &e.data, &written, &dirs) {
                drop.push((nid.clone(), format!("reads a file another test or fixture wrote in another worker: {key} ({w})")));
                for ws in written.get(&*key).into_iter().chain(dirs.get(&*key)) {
                    edges.extend(ws.iter().filter_map(|x| x.strip_prefix("t|")).filter(|x| *x != nid).map(|x| (x.to_string(), nid.clone())));
                }
            }
        }
        for (nid, why) in drop {
            s.store.tests.remove(&nid);
            out.dropped.push((nid, why));
        }
        out.merged += s.store.tests.len();
    }
    fs::create_dir_all(dir)?;
    let _lock = DirLock::acquire(dir)?;
    let mut disk = Store::load(dir);
    for s in shards.iter() {
        let touched: BTreeSet<String> = s.touched.iter().cloned().collect();
        s.store.merge_into(&mut disk, &touched);
    }
    for nid in hits {
        let Some(e) = disk.tests.get(nid) else { continue };
        let own = format!("t|{nid}");
        let stale = e.data.iter().find_map(|(k, _)| {
            written
                .get(&**k)
                .filter(|w| !w.iter().all(|x| *x == own || e.fixtures.iter().any(|f| f == x)))
                .map(|_| k.to_string())
        });
        if let Some(k) = stale {
            for w in written.get(&k).into_iter().flatten() {
                if let Some(x) = w.strip_prefix("t|") {
                    if x != nid {
                        edges.insert((x.to_string(), nid.clone()));
                    }
                }
            }
            disk.tests.remove(nid);
            out.stale.push((nid.clone(), k));
        }
    }
    out.edges = edges.len();
    disk.edges.extend(edges);
    disk.save(dir)?;
    Ok(out)
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

/// FxHash (rustc's hasher) for the checker's memo tables: string keys looked up for every dependency of every
/// entry; SipHash was ~10 % of a warm session's check (MEASURED, py-spy --native). Keys are not adversarial.
#[derive(Default, Clone, Copy)]
pub struct FxHasher(u64);

impl std::hash::Hasher for FxHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        const K: u64 = 0x51_7c_c1_b7_27_22_0a_95;
        let mut h = self.0;
        let mut chunks = bytes.chunks_exact(8);
        for c in &mut chunks {
            h = (h.rotate_left(5) ^ u64::from_le_bytes(c.try_into().unwrap())).wrapping_mul(K);
        }
        for &b in chunks.remainder() {
            h = (h.rotate_left(5) ^ b as u64).wrapping_mul(K);
        }
        self.0 = h;
    }
    fn write_u8(&mut self, i: u8) {
        self.0 = (self.0.rotate_left(5) ^ i as u64).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
    fn write_u32(&mut self, i: u32) {
        self.0 = (self.0.rotate_left(5) ^ i as u64).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
    fn write_u64(&mut self, i: u64) {
        self.0 = (self.0.rotate_left(5) ^ i).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
    fn write_usize(&mut self, i: usize) {
        self.write_u64(i as u64);
    }
}

pub type FxMap<K, V> = HashMap<K, V, std::hash::BuildHasherDefault<FxHasher>>;

#[derive(Default)]
pub struct Checker {
    pub cur: Current,
    content_now: FxMap<String, Option<String>>,
    data_now: FxMap<char, FxMap<String, String>>,
    /// Outcome of checking each (content | skeleton | hooks, set id): the same for every entry of the session
    /// (Ok: the files proven unchanged in their used parts).
    set_checks: FxMap<(u8, u32), Result<Vec<String>, Miss>>,
    /// Digests of the current environment: the whole of it, and per variable (the same for every test).
    env_all_now: Option<String>,
    env_now: FxMap<String, String>,
    /// Key bytes of each (content | skeleton | hooks, set id) part (sets are shared by many tests).
    key_parts: FxMap<(u8, u32), Vec<u8>>,
    /// Facts of the current version of code files whose content changed.
    pub fresh: HashMap<String, CodeFile>,
    /// Parallel session (the controller of `-n`, or one worker's list replayed with `--det-plan-worker`): a result
    /// recorded by a worker of a parallel session ([`PLACEMENT_PARALLEL`]) may be reused. A serial session does not
    /// reuse one (docs/PARALLEL-PROOF-DESIGN.md 2.5, review R-023 F1).
    pub parallel: bool,
    /// The controller of `-n`: the worker a test runs on is decided by the plan, after the reuse decision. A
    /// recorded `PYTEST_XDIST_WORKER` is not compared here: it is kept in [`Checker::worker_reads`] and compared with
    /// the test's worker in this run's plan by [`Checker::worker_check`] (review R-023 F3).
    pub defer_worker: bool,
    /// nodeid -> recorded digest of `PYTEST_XDIST_WORKER`, for the reusable results that read it (`defer_worker`).
    pub worker_reads: HashMap<String, String>,
}

/// Outcomes whose results may be reused: never a failure.
pub fn reusable_outcome(outcome: &str) -> bool {
    matches!(outcome, "passed" | "skipped" | "xfailed")
}

impl Checker {
    pub fn new(cur: Current) -> Self {
        Checker {
            cur,
            content_now: FxMap::default(),
            data_now: FxMap::default(),
            env_all_now: None,
            set_checks: FxMap::default(),
            env_now: FxMap::default(),
            key_parts: FxMap::default(),
            fresh: HashMap::new(),
            parallel: false,
            defer_worker: false,
            worker_reads: HashMap::new(),
        }
    }

    /// The reusable results whose recorded `PYTEST_XDIST_WORKER` differs from the worker `assign` gives them in this
    /// run's plan (or that have no worker there): `(nodeid, reason)`, in `nodeids` order. Their result depends on
    /// the worker they run on, and this run places them elsewhere.
    pub fn worker_check(&self, nodeids: &[String], assign: &HashMap<String, String>) -> Vec<(String, String)> {
        let mut out = Vec::new();
        for nid in nodeids {
            let Some(rec) = self.worker_reads.get(nid) else { continue };
            let now = assign.get(nid).map(|w| env_value_digest(Some(w)));
            if now.as_deref() != Some(rec.as_str()) {
                let w = assign.get(nid).map(|w| w.as_str()).unwrap_or("none");
                out.push((
                    nid.clone(),
                    format!("env: environment variable PYTEST_XDIST_WORKER (this run's plan places the test on {w})"),
                ));
            }
        }
        out
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

    /// The state of a data dependency as this session's code saw it before creating the path itself (an exclusive
    /// create that found it missing, before the reuse decision): recorded dependencies on `path` are compared with
    /// `dep` instead of the file the session then created (review R-009b R2).
    pub fn observed(&mut self, path: &str, dep: &str) {
        let kind = if dep == "missing" { 'f' } else { dep.chars().next().unwrap_or('?') };
        self.data_now.entry(kind).or_default().insert(path.to_string(), dep.to_string());
    }

    fn data(&mut self, path: &str, recorded: &str) -> &str {
        let kind = recorded.chars().next().unwrap_or('?');
        let kind = if recorded == "missing" { 'f' } else { kind };
        let m = self.data_now.entry(kind).or_default();
        if !m.contains_key(path) {
            let v = data_now(&self.cur.root.join(path), recorded);
            m.insert(path.to_string(), v);
        }
        &m[path]
    }

    /// `content(rel) == Some(digest)` without copying the memoised digest.
    fn content_is(&mut self, rel: &str, digest: &str) -> bool {
        if !self.content_now.contains_key(rel) {
            let d = file_digest(&self.cur.root.join(rel));
            self.content_now.insert(rel.to_string(), d);
        }
        self.content_now[rel].as_deref() == Some(digest)
    }

    /// Check one dependency set: `t` 0 = whole contents, 1 = skeletons, 2 = hook surfaces (in this order, the first
    /// changed file of the set decides, as the per-entry loops did).
    fn check_set(&mut self, store: &Store, t: u8, id: u32) -> Result<Vec<String>, Miss> {
        let mut proven = Vec::new();
        for &i in store.set(id) {
            let Some(f) = store.files.get(i as usize) else { continue };
            if self.content_is(&f.path, &f.content) {
                continue;
            }
            if t == 0 {
                return Err(Miss { kind: "code", detail: format!("{} (content)", f.path) });
            }
            let path = f.path.clone();
            let ok = match self.now_facts(store, &path) {
                None => false,
                Some(n) => {
                    if t == 1 {
                        n.skeleton == f.skeleton
                    } else {
                        n.hooks == f.hooks
                    }
                }
            };
            if !ok {
                let what = if t == 1 { "module level" } else { "pytest hooks" };
                return Err(Miss { kind: "code", detail: format!("{path} ({what})") });
            }
            proven.push(path);
        }
        Ok(proven)
    }

    /// Reuse decision for `nodeid`.
    pub fn check(&mut self, store: &Store, nodeid: &str) -> Result<Receipt, Miss> {
        let Some(e) = store.tests.get(nodeid) else {
            return Err(Miss { kind: "new", detail: "no recorded result".into() });
        };
        if !reusable_outcome(&e.outcome) {
            return Err(Miss { kind: "failed-before", detail: format!("recorded outcome {}", e.outcome) });
        }
        if e.placement == PLACEMENT_PARALLEL && !self.parallel {
            return Err(Miss {
                kind: "placement",
                detail: "recorded in a worker of a parallel (-n) session: not offered to a serial session until the \
                         parallel-vs-serial proof (P5)"
                    .into(),
            });
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
            if k == "PYTEST_XDIST_WORKER" && self.defer_worker {
                self.worker_reads.insert(nodeid.to_string(), v.clone());
                continue;
            }
            let now: &str = if k == "*" {
                if self.env_all_now.is_none() {
                    self.env_all_now = Some(env_all_digest(&self.cur.env));
                }
                self.env_all_now.as_deref().unwrap()
            } else {
                if !self.env_now.contains_key(k) {
                    let d = env_value_digest(self.cur.env.get(k).map(|s| s.as_str()));
                    self.env_now.insert(k.clone(), d);
                }
                &self.env_now[k]
            };
            if now != v {
                return Err(Miss { kind: "env", detail: format!("environment variable {k}") });
            }
        }
        for (p, dep) in &e.data {
            if self.data(p, dep) != &**dep {
                return Err(Miss { kind: "data", detail: format!("{p} ({})", dep.split(':').next().unwrap_or("")) });
            }
        }
        let mut proven = std::collections::BTreeSet::new();
        // whole-content, skeleton and hook dependencies: per set, memoised (sets are shared across entries)
        for (t, id) in [(0u8, e.content), (1, e.skeleton), (2, e.hooks)] {
            if !self.set_checks.contains_key(&(t, id)) {
                let r = self.check_set(store, t, id);
                self.set_checks.insert((t, id), r);
            }
            match &self.set_checks[&(t, id)] {
                Ok(p) => proven.extend(p.iter().cloned()),
                Err(m) => return Err(m.clone()),
            }
        }
        for c in e.units.chunks(2) {
            let Some(f) = store.files.get(c[0] as usize) else { continue };
            let Some(u) = f.units.get(c[1] as usize) else { continue };
            if self.content_is(&f.path, &f.content) {
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
            key: store.key_of_with(nodeid, e, &mut self.key_parts),
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
    fn memoised_checks_and_keys_match_the_unmemoised_ones() {
        // one checker over every entry (memo shared) vs a fresh checker per entry; and key_of_with vs key_of
        let (d, mut s, cur) = setup();
        for i in 0..5 {
            let mut o = Observed { outcome: "passed".into(), config: "C".into(), runtime: "R".into(), ..Default::default() };
            o.env = vec![("*".into(), env_all_digest(&cur.env)), ("HOME".into(), env_value_digest(None))];
            if i % 2 == 0 {
                o.env.pop();
            }
            s.record(&format!("t::g{i}"), o);
        }
        fs::write(d.path().join("m.py"), "def f():\n    return 3\n").unwrap();
        let ids: Vec<String> = s.tests.keys().cloned().collect();
        let mut shared = Checker::new(cur.clone());
        for id in &ids {
            let a = shared.check(&s, id);
            let b = Checker::new(cur.clone()).check(&s, id);
            assert_eq!(a, b, "{id}");
            if let Ok(r) = a {
                assert_eq!(r.key, s.key_of(id, &s.tests[id]));
            }
        }
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

    // -- parallel sessions ------------------------------------------------------------------------------------------
    fn entry_reading(store: &mut Store, nid: &str, data: &[(&str, &str)]) {
        let o = Observed {
            outcome: "passed".into(),
            data: data.iter().map(|(k, d)| (Str::from(*k), Str::from(*d))).collect(),
            ..Default::default()
        };
        store.record(nid, o);
    }

    fn shard(worker: &str, entries: &[(&str, &[(&str, &str)])], written: &[(&str, &[&str])]) -> Shard {
        let mut st = Store::new();
        for (nid, data) in entries {
            entry_reading(&mut st, nid, data);
        }
        Shard {
            format: SHARD_FORMAT.into(),
            version: SHARD_VERSION,
            worker: worker.into(),
            touched: entries.iter().map(|(n, _)| n.to_string()).collect(),
            store: st,
            fixtures: BTreeMap::new(),
            written: written.iter().map(|(k, w)| (k.to_string(), w.iter().map(|s| s.to_string()).collect())).collect(),
        }
    }

    #[test]
    fn cross_worker_write_drops_the_reader() {
        let d = tempfile::tempdir().unwrap();
        // test_a (worker 0) writes /tmp/x; test_b (worker 1) reads it: b is not cached; c reads only its own file
        let mut shards = vec![
            shard("gw1", &[("t.py::b", &[("/tmp/x", "f:1")]), ("t.py::c", &[("data/c.txt", "f:2")])], &[]),
            shard("gw0", &[("t.py::a", &[("tests/value.txt", "f:3")])], &[("/tmp/x", &["t|t.py::a"])]),
        ];
        let m = merge_shards(d.path(), &mut shards, &[]).unwrap();
        assert_eq!(m.merged, 2);
        assert_eq!(m.dropped.len(), 1);
        assert_eq!(m.dropped[0].0, "t.py::b");
        let disk = Store::load(d.path());
        assert!(disk.tests.contains_key("t.py::a") && disk.tests.contains_key("t.py::c"));
        assert!(!disk.tests.contains_key("t.py::b"));
    }

    #[test]
    fn own_writes_and_shared_fixtures_are_credited() {
        let mut written = BTreeMap::new();
        written.insert("/tmp/own".to_string(), BTreeSet::from(["t|t.py::a".to_string()]));
        written.insert("/tmp/fx".to_string(), BTreeSet::from(["f|session||db".to_string()]));
        written.insert("/tmp/imp".to_string(), BTreeSet::from(["i".to_string(), "c|t.py".to_string(), "s".to_string()]));
        let dirs = BTreeMap::new();
        let data = |k: &str| vec![(Str::from(k), Str::from("f:1"))];
        assert_eq!(foreign_write("t.py::a", &[], &data("/tmp/own"), &written, &dirs), None);
        assert_eq!(foreign_write("t.py::a", &["f|session||db".into()], &data("/tmp/fx"), &written, &dirs), None);
        assert!(foreign_write("t.py::a", &[], &data("/tmp/fx"), &written, &dirs).is_some());
        assert_eq!(foreign_write("t.py::a", &[], &data("/tmp/imp"), &written, &dirs), None);
        assert!(foreign_write("t.py::b", &[], &data("/tmp/own"), &written, &dirs).is_some());
    }

    #[test]
    fn listing_of_a_directory_another_test_wrote_into() {
        let shards = vec![shard("gw0", &[], &[("/tmp/d/new", &["t|t.py::w"])])];
        let (written, dirs) = writer_union(&shards);
        let listing = vec![(Str::from("/tmp/d"), Str::from("d:abc"))];
        assert!(foreign_write("t.py::r", &[], &listing, &written, &dirs).is_some());
        let file = vec![(Str::from("/tmp/d"), Str::from("missing"))];
        assert!(foreign_write("t.py::r", &[], &file, &written, &dirs).is_none());
    }

    #[test]
    fn merge_is_independent_of_shard_order_and_removes_touched_absent() {
        let a = tempfile::tempdir().unwrap();
        let b = tempfile::tempdir().unwrap();
        // an old entry for t.py::gone exists; this session touched it without recording (a failure)
        for d in [a.path(), b.path()] {
            let mut st = Store::new();
            entry_reading(&mut st, "t.py::gone", &[]);
            st.save(d).unwrap();
        }
        let mk = || {
            let mut s0 = shard("gw0", &[("t.py::a", &[])], &[("/tmp/x", &["t|t.py::a"])]);
            s0.touched.push("t.py::gone".into());
            let s1 = shard("gw1", &[("t.py::b", &[("/tmp/x", "f:1")])], &[]);
            (s0, s1)
        };
        let (s0, s1) = mk();
        let m1 = merge_shards(a.path(), &mut [s0, s1], &[]).unwrap();
        let (s0, s1) = mk();
        let m2 = merge_shards(b.path(), &mut [s1, s0], &[]).unwrap();
        assert_eq!(m1, m2);
        assert_eq!(fs::read(Store::path_in(a.path())).unwrap(), fs::read(Store::path_in(b.path())).unwrap());
        assert!(!Store::load(a.path()).tests.contains_key("t.py::gone"));
    }

    #[test]
    fn reused_result_whose_input_the_session_wrote_is_dropped() {
        let d = tempfile::tempdir().unwrap();
        let mut st = Store::new();
        entry_reading(&mut st, "t.py::hit", &[("/tmp/x", "f:1")]);
        entry_reading(&mut st, "t.py::ok", &[("/tmp/y", "f:1")]);
        st.save(d.path()).unwrap();
        let mut shards = vec![shard("gw0", &[], &[("/tmp/x", &["t|t.py::w"])])];
        let m = merge_shards(d.path(), &mut shards, &["t.py::hit".into(), "t.py::ok".into()]).unwrap();
        assert_eq!(m.stale, vec![("t.py::hit".to_string(), "/tmp/x".to_string())]);
        let disk = Store::load(d.path());
        assert!(!disk.tests.contains_key("t.py::hit") && disk.tests.contains_key("t.py::ok"));
    }

    #[test]
    fn whole_environment_digest_leaves_out_shell_and_xdist_variables() {
        let mut a = BTreeMap::new();
        a.insert("HOME".to_string(), "/root".to_string());
        let mut b = a.clone();
        b.insert("_".to_string(), "/usr/bin/python".to_string());
        b.insert("PYTEST_XDIST_WORKER".to_string(), "gw1".to_string());
        b.insert("PYTEST_XDIST_TESTRUNUID".to_string(), "abc".to_string());
        b.insert("PYTEST_XDIST_WORKER_COUNT".to_string(), "4".to_string());
        assert_eq!(env_all_digest(&a), env_all_digest(&b));
        b.insert("OTHER".to_string(), "1".to_string());
        assert_ne!(env_all_digest(&a), env_all_digest(&b));
    }
    // -- review R-023 ------------------------------------------------------------------------------------------------
    #[test]
    fn r023_f1_a_serial_session_does_not_reuse_a_parallel_entry() {
        let (_d, mut s, cur) = setup();
        s.tests.get_mut("t::a").unwrap().placement = PLACEMENT_PARALLEL.into();
        let mut c = Checker::new(cur.clone());
        assert_eq!(c.check(&s, "t::a").unwrap_err().kind, "placement");
        let mut c = Checker::new(cur);
        c.parallel = true;
        assert!(c.check(&s, "t::a").is_ok());
        // the placement is not part of the key: a serial entry keeps its key when it is recorded again in a worker
        let k = s.tests["t::a"].key.clone();
        assert_eq!(s.key_of("t::a", &s.tests["t::a"]), k);
    }

    #[test]
    fn r023_f3_worker_reads_are_checked_against_this_runs_plan() {
        let (_d, mut s, cur) = setup();
        s.tests.get_mut("t::a").unwrap().env.push(("PYTEST_XDIST_WORKER".into(), env_value_digest(Some("gw0"))));
        let mut c = Checker::new(cur);
        c.parallel = true;
        c.defer_worker = true;
        assert!(c.check(&s, "t::a").is_ok()); // deferred: decided after the plan
        let on = |w: &str| HashMap::from([("t::a".to_string(), w.to_string())]);
        assert!(c.worker_check(&["t::a".into()], &on("gw0")).is_empty());
        let out = c.worker_check(&["t::a".into()], &on("gw1"));
        assert_eq!(out.len(), 1);
        assert!(out[0].1.contains("gw1"));
        assert_eq!(c.worker_check(&["t::a".into()], &HashMap::new()).len(), 1);
    }

    #[test]
    fn r023_f2_written_paths_outside_the_repository_persist_while_they_exist() {
        let d = tempfile::tempdir().unwrap();
        let kept = d.path().join("shared.txt");
        fs::write(&kept, "x").unwrap();
        let gone = d.path().join("gone.txt");
        assert!(persist_written("rel/in/repo.txt"));
        assert!(persist_written(kept.to_str().unwrap()));
        assert!(!persist_written(gone.to_str().unwrap()));
        let mut st = Store::new();
        st.written.insert(kept.to_str().unwrap().into(), BTreeSet::from(["t|a".to_string()]));
        st.written.insert(gone.to_str().unwrap().into(), BTreeSet::from(["t|a".to_string()]));
        let dir = tempfile::tempdir().unwrap();
        st.save(dir.path()).unwrap();
        let back = Store::load(dir.path());
        assert!(back.written.contains_key(kept.to_str().unwrap()));
        assert!(!back.written.contains_key(gone.to_str().unwrap()));
    }

    #[test]
    fn r023_f2_hits_whose_input_an_earlier_test_wrote() {
        let mut st = Store::new();
        entry_reading(&mut st, "t.py::b", &[("/tmp/x", "f:1")]);
        entry_reading(&mut st, "t.py::c", &[("/tmp/y", "f:1")]);
        entry_reading(&mut st, "t.py::f", &[("/tmp/z", "f:1")]);
        st.tests.get_mut("t.py::f").unwrap().fixtures = vec!["f|session||db".into()];
        let order: Vec<String> = ["t.py::a", "t.py::b", "t.py::c", "t.py::d", "t.py::f"].iter().map(|s| s.to_string()).collect();
        let shards = vec![shard("gw0", &[], &[("/tmp/x", &["t|t.py::a"]), ("/tmp/y", &["t|t.py::d"]),
                                              ("/tmp/z", &["f|session||db"])])];
        let (written, dirs) = writer_union(&shards);
        let hits: Vec<String> = ["t.py::b", "t.py::c", "t.py::f"].iter().map(|s| s.to_string()).collect();
        let out = hits_with_written_inputs(&st, &hits, &order, &written, &dirs);
        // b: written by a, which comes first; c: written by d, which comes after it (a serial run reads it before);
        // f: written by a fixture f used when it was recorded
        assert_eq!(out, vec![("t.py::b".to_string(), "/tmp/x".to_string(), "t|t.py::a".to_string())]);
    }

    #[test]
    fn r023_merge_notes_data_edges() {
        let d = tempfile::tempdir().unwrap();
        let mut shards = vec![
            shard("gw1", &[("t.py::b", &[("/tmp/x", "f:1")])], &[]),
            shard("gw0", &[("t.py::a", &[])], &[("/tmp/x", &["t|t.py::a"])]),
        ];
        let m = merge_shards(d.path(), &mut shards, &[]).unwrap();
        assert_eq!(m.edges, 1);
        assert!(Store::load(d.path()).edges.contains(&("t.py::a".to_string(), "t.py::b".to_string())));
    }
}
