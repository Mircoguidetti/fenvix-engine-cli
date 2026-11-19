//! Shared cache with proof (P4): one store shared by the workers of a parallel session and by separate CI jobs.
//!
//! Port of `claude/shared-cache`'s client (`remote_cache.py`) onto the Rust store. The model is the same:
//!
//! * **documents** are immutable and content-addressed: the address is the SHA-256 (hex) of the document's exact
//!   bytes. Two kinds: an *entry* document (one test's recorded inputs and result, [`EntryDoc`]) and a *file*
//!   document (the facts of one version of one source file, a [`CodeFile`], shared between entries). A reader
//!   recomputes the address of every document it reads and drops a mismatch (a corrupted, truncated or replaced
//!   blob): a stored document can never be swapped for another;
//! * a **key log** per lookup key (test id, configuration digest, runtime digest: [`lookup_key`]) lists the entry
//!   documents recorded under it, oldest first, one line per push. Each line carries its own checksum: a line torn by
//!   a crash or a concurrent writer on a filesystem without atomic appends is dropped, never half-read. The log is
//!   only appended to; candidates are ordered by their position in it, never by a machine's wall clock (clock skew
//!   between machines cannot reorder or expire anything);
//! * a **run log** lists each run's receipts document.
//!
//! The service supplies *candidates*, never decisions: a candidate whose document or file documents are missing
//! or invalid (a partial upload), whose test id, lookup key, configuration or runtime is not the reader's (a
//! poisoned entry from another runtime), or whose stored receipt key does not match the key of its own inputs, is
//! rejected with a reason; an accepted candidate is checked by [`crate::proof::Checker`] exactly like a local entry
//! (code, data, environment, runtime, configuration, epoch, the placement guard), and adopted only if that check
//! passes ([`adopt`]). The receipts name the adopted document.
//!
//! The transport here is a directory ([`SharedDir`]): a mounted volume, an object store synchronised to a path, or
//! a directory every worker of one machine sees. Writes are atomic (temporary file and rename for documents, one
//! `write` per log line with `O_APPEND`) and idempotent (a document already present is not rewritten), so any
//! number of concurrent writers lose nothing.

use crate::proof::{CodeFile, Entry, Store};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const ENTRY_FORMAT: &str = "detpy-shared-entry";
pub const DOC_VERSION: u32 = 1;

/// The address of a document: SHA-256 of its bytes, hex.
pub fn address(bytes: &[u8]) -> String {
    let d = Sha256::digest(bytes);
    let mut s = String::with_capacity(64);
    for b in d {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

fn valid_id(id: &str) -> bool {
    id.len() == 64 && id.bytes().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

/// Where a test's entries are filed: test id, configuration digest and runtime digest (computable before the test
/// runs). The clock epoch is not part of it: an entry that read the clock carries its epoch, which the checker
/// compares.
pub fn lookup_key(nodeid: &str, config: &str, runtime: &str) -> String {
    let mut b = Vec::new();
    for part in ["detpy-shared-lookup-1", nodeid, config, runtime] {
        b.extend_from_slice(&(part.len() as u64).to_le_bytes());
        b.extend_from_slice(part.as_bytes());
    }
    address(&b)[..40].to_string()
}

/// One test's entry as a self-contained document: the entry with its code-file sets and units named by file
/// document address instead of store indices.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EntryDoc {
    pub format: String,
    pub version: u32,
    pub nodeid: String,
    pub lookup: String,
    /// The entry; its `content`, `skeleton`, `hooks` and `units` indices are meaningless here (0 / empty).
    pub entry: Entry,
    pub content: Vec<String>,
    pub skeleton: Vec<String>,
    pub hooks: Vec<String>,
    /// (file document, unit index) pairs.
    pub units: Vec<(String, u32)>,
}

/// A line of a key log.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct KeyLine {
    pub doc: String,
    pub run: String,
    /// Where the writer recorded it ("" serial, "parallel").
    #[serde(default)]
    pub placement: String,
}

fn line_checksum(json: &str) -> String {
    address(json.as_bytes())[..16].to_string()
}

/// The documents of one entry: (entry document bytes, [file document bytes]).
pub fn export_entry(store: &Store, nodeid: &str, config_runtime_lookup: Option<&str>) -> Option<(Vec<u8>, Vec<Vec<u8>>)> {
    let e = store.tests.get(nodeid)?;
    let mut files: BTreeMap<u32, (String, Vec<u8>)> = BTreeMap::new();
    let mut file_doc = |i: u32| -> Option<String> {
        if let Some((id, _)) = files.get(&i) {
            return Some(id.clone());
        }
        let f = store.files.get(i as usize)?;
        let bytes = serde_json::to_vec(f).ok()?;
        let id = address(&bytes);
        files.insert(i, (id.clone(), bytes));
        Some(id)
    };
    let mut set_docs = |id: u32| -> Option<Vec<String>> {
        let mut v: Vec<String> = store.set(id).iter().map(|&i| file_doc(i)).collect::<Option<Vec<_>>>()?;
        v.sort();
        v.dedup();
        Some(v)
    };
    let content = set_docs(e.content)?;
    let skeleton = set_docs(e.skeleton)?;
    let hooks = set_docs(e.hooks)?;
    let mut units = Vec::with_capacity(e.units.len() / 2);
    for c in e.units.chunks(2) {
        units.push((file_doc(c[0])?, c[1]));
    }
    units.sort();
    let mut entry = e.clone();
    entry.content = 0;
    entry.skeleton = 0;
    entry.hooks = 0;
    entry.units = Vec::new();
    let lookup = config_runtime_lookup.map(|s| s.to_string()).unwrap_or_else(|| lookup_key(nodeid, &e.config, &e.runtime));
    let doc = EntryDoc {
        format: ENTRY_FORMAT.into(),
        version: DOC_VERSION,
        nodeid: nodeid.to_string(),
        lookup,
        entry,
        content,
        skeleton,
        hooks,
        units,
    };
    let bytes = serde_json::to_vec(&doc).ok()?;
    Some((bytes, files.into_values().map(|(_, b)| b).collect()))
}

/// Why a candidate was not offered to the checker.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Reject {
    /// The entry document or one of its file documents is missing (an upload that did not finish).
    Incomplete(String),
    /// A document whose bytes do not match its address, or that does not parse.
    Corrupt(String),
    /// Test id, lookup key, configuration or runtime is not the reader's.
    Foreign(String),
    /// The stored receipt key is not the key of the entry's own inputs.
    KeyMismatch(String),
}

impl Reject {
    pub fn kind(&self) -> &'static str {
        match self {
            Reject::Incomplete(_) => "incomplete",
            Reject::Corrupt(_) => "corrupt",
            Reject::Foreign(_) => "foreign",
            Reject::KeyMismatch(_) => "key-mismatch",
        }
    }
    pub fn detail(&self) -> &str {
        match self {
            Reject::Incomplete(s) | Reject::Corrupt(s) | Reject::Foreign(s) | Reject::KeyMismatch(s) => s,
        }
    }
}

/// Validate an entry document against the reader (`nodeid`, `config`, `runtime`) and import it into `store`
/// (file facts added, sets interned): the entry with store indices, not inserted. `get` returns a document's bytes
/// by address (None: absent). The store is changed only by additions of file facts and sets.
pub fn import_entry(
    store: &mut Store,
    doc_id: &str,
    nodeid: &str,
    config: &str,
    runtime: &str,
    get: &mut dyn FnMut(&str) -> Option<Vec<u8>>,
) -> Result<Entry, Reject> {
    if !valid_id(doc_id) {
        return Err(Reject::Corrupt(format!("invalid document address {doc_id:?}")));
    }
    let bytes = get(doc_id).ok_or_else(|| Reject::Incomplete(format!("entry document {doc_id} absent")))?;
    if address(&bytes) != doc_id {
        return Err(Reject::Corrupt(format!("entry document {doc_id}: content does not match its address")));
    }
    let doc: EntryDoc = serde_json::from_slice(&bytes).map_err(|e| Reject::Corrupt(format!("entry document {doc_id}: {e}")))?;
    if doc.format != ENTRY_FORMAT || doc.version != DOC_VERSION {
        return Err(Reject::Corrupt(format!("entry document {doc_id}: format {} {}", doc.format, doc.version)));
    }
    if doc.nodeid != nodeid {
        return Err(Reject::Foreign(format!("filed for {nodeid} but records {}", doc.nodeid)));
    }
    if doc.entry.config != config || doc.entry.runtime != runtime {
        return Err(Reject::Foreign(format!(
            "recorded under configuration {} runtime {} (this session: {config} {runtime})",
            doc.entry.config, doc.entry.runtime
        )));
    }
    if doc.lookup != lookup_key(nodeid, config, runtime) {
        return Err(Reject::Foreign("lookup key does not match the entry".into()));
    }
    // every file document first: nothing is added to the store unless the whole entry is present and valid
    let mut wanted: BTreeSet<&str> = BTreeSet::new();
    wanted.extend(doc.content.iter().map(|s| s.as_str()));
    wanted.extend(doc.skeleton.iter().map(|s| s.as_str()));
    wanted.extend(doc.hooks.iter().map(|s| s.as_str()));
    wanted.extend(doc.units.iter().map(|(s, _)| s.as_str()));
    let mut facts: HashMap<&str, CodeFile> = HashMap::new();
    for id in wanted {
        if !valid_id(id) {
            return Err(Reject::Corrupt(format!("invalid file document address {id:?}")));
        }
        let b = get(id).ok_or_else(|| Reject::Incomplete(format!("file document {id} absent")))?;
        if address(&b) != id {
            return Err(Reject::Corrupt(format!("file document {id}: content does not match its address")));
        }
        let f: CodeFile = serde_json::from_slice(&b).map_err(|e| Reject::Corrupt(format!("file document {id}: {e}")))?;
        facts.insert(id, f);
    }
    for (id, u) in &doc.units {
        if facts.get(id.as_str()).map(|f| (*u as usize) >= f.units.len()).unwrap_or(true) {
            return Err(Reject::Corrupt(format!("unit {u} of file document {id} does not exist")));
        }
    }
    let mut ix: HashMap<&str, u32> = HashMap::new();
    for (id, f) in &facts {
        ix.insert(id, store.add_file(f.clone()));
    }
    let set = |ids: &[String]| -> Vec<u32> { ids.iter().map(|i| ix[i.as_str()]).collect() };
    let mut e = doc.entry.clone();
    e.content = store.intern_set(set(&doc.content));
    e.skeleton = store.intern_set(set(&doc.skeleton));
    e.hooks = store.intern_set(set(&doc.hooks));
    e.units = doc.units.iter().flat_map(|(id, u)| [ix[id.as_str()], *u]).collect();
    let key = store.key_of(nodeid, &e);
    if key != e.key {
        return Err(Reject::KeyMismatch(format!("stored key {} but its inputs give {key}", e.key)));
    }
    Ok(e)
}

// ---------------------------------------------------------------------------------------------------------------
// The directory transport

/// A shared store in a directory: `blobs/<aa>/<address>`, `keys/<aa>/<lookup>.log`, `runs.log`.
#[derive(Clone, Debug)]
pub struct SharedDir {
    pub root: PathBuf,
}

/// What a read of key logs found besides the lines.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct LogStats {
    pub lines: usize,
    pub torn: usize,
}

impl SharedDir {
    pub fn new(root: impl Into<PathBuf>) -> SharedDir {
        SharedDir { root: root.into() }
    }

    fn blob_path(&self, id: &str) -> PathBuf {
        self.root.join("blobs").join(&id[..2.min(id.len())]).join(id)
    }

    fn key_path(&self, lookup: &str) -> PathBuf {
        self.root.join("keys").join(&lookup[..2.min(lookup.len())]).join(format!("{lookup}.log"))
    }

    /// Store a document; returns its address. A document already present with valid content is not rewritten; one
    /// present with invalid content (a crashed earlier writer on a filesystem without atomic rename) is replaced.
    pub fn put(&self, bytes: &[u8]) -> io::Result<String> {
        let id = address(bytes);
        let p = self.blob_path(&id);
        if let Ok(old) = fs::read(&p) {
            if address(&old) == id {
                return Ok(id);
            }
        }
        if let Some(d) = p.parent() {
            fs::create_dir_all(d)?;
        }
        let tmp = p.with_extension(format!("tmp{}-{}", std::process::id(), unique()));
        fs::write(&tmp, bytes)?;
        fs::rename(&tmp, &p)?;
        Ok(id)
    }

    /// A document's bytes, None when absent (validation is the caller's: [`import_entry`]).
    pub fn get(&self, id: &str) -> Option<Vec<u8>> {
        if !valid_id(id) {
            return None;
        }
        fs::read(self.blob_path(id)).ok()
    }

    fn append_line(path: &Path, json: &str) -> io::Result<()> {
        if let Some(d) = path.parent() {
            fs::create_dir_all(d)?;
        }
        let line = format!("{json}\t{}\n", line_checksum(json));
        let mut f = fs::OpenOptions::new().create(true).append(true).open(path)?;
        // one write: O_APPEND appends of one buffer do not interleave on a local filesystem; elsewhere the checksum
        // drops a torn line
        f.write_all(line.as_bytes())?;
        Ok(())
    }

    fn read_lines(path: &Path, stats: &mut LogStats) -> Vec<String> {
        let Ok(text) = fs::read(path) else { return Vec::new() };
        let mut out = Vec::new();
        for raw in text.split(|&b| b == b'\n') {
            if raw.is_empty() {
                continue;
            }
            let Ok(s) = std::str::from_utf8(raw) else {
                stats.torn += 1;
                continue;
            };
            match s.rsplit_once('\t') {
                Some((json, sum)) if line_checksum(json) == sum => {
                    stats.lines += 1;
                    out.push(json.to_string());
                }
                _ => stats.torn += 1,
            }
        }
        out
    }

    /// Append a key line for `lookup`.
    pub fn append_key(&self, lookup: &str, line: &KeyLine) -> io::Result<()> {
        Self::append_line(&self.key_path(lookup), &serde_json::to_string(line).map_err(io::Error::other)?)
    }

    /// The valid key lines of `lookup`, newest first.
    pub fn keys(&self, lookup: &str, stats: &mut LogStats) -> Vec<KeyLine> {
        let mut v: Vec<KeyLine> = Self::read_lines(&self.key_path(lookup), stats)
            .into_iter()
            .filter_map(|j| match serde_json::from_str(&j) {
                Ok(l) => Some(l),
                Err(_) => {
                    stats.torn += 1;
                    None
                }
            })
            .collect();
        v.reverse();
        v
    }

    /// Append a run line (`{"run", "receipts", "summary"}`).
    pub fn append_run(&self, run: &str, receipts: &str, summary: &serde_json::Value) -> io::Result<()> {
        let j = serde_json::json!({"run": run, "receipts": receipts, "summary": summary});
        Self::append_line(&self.root.join("runs.log"), &j.to_string())
    }

    /// The valid run lines, oldest first.
    pub fn runs(&self) -> Vec<serde_json::Value> {
        let mut st = LogStats::default();
        Self::read_lines(&self.root.join("runs.log"), &mut st)
            .into_iter()
            .filter_map(|j| serde_json::from_str(&j).ok())
            .collect()
    }

    /// Push the entries of `nodeids` from `store`: file documents, then the entry document, then the key line (a
    /// reader never sees a key line before its documents). Returns (entries pushed, documents written).
    pub fn push(&self, store: &Store, nodeids: &[String]) -> io::Result<(usize, usize)> {
        let mut n = 0;
        let mut docs = 0;
        for nid in nodeids {
            let Some(e) = store.tests.get(nid) else { continue };
            let Some((entry, files)) = export_entry(store, nid, None) else { continue };
            for f in &files {
                self.put(f)?;
                docs += 1;
            }
            let id = self.put(&entry)?;
            docs += 1;
            let lookup = lookup_key(nid, &e.config, &e.runtime);
            self.append_key(&lookup, &KeyLine { doc: id, run: e.run.clone(), placement: e.placement.clone() })?;
            n += 1;
        }
        Ok((n, docs))
    }
}

fn unique() -> u64 {
    use std::sync::atomic::{AtomicU64, Ordering};
    static N: AtomicU64 = AtomicU64::new(0);
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(0);
    t ^ N.fetch_add(1, Ordering::Relaxed).wrapping_mul(0x9E37_79B9_7F4A_7C15)
}

/// Candidates fetched for a session: per test, the valid imported entries (newest first) and their documents; the
/// rejections with their reasons.
#[derive(Default, Debug)]
pub struct Fetched {
    pub candidates: BTreeMap<String, Vec<(String, Entry)>>,
    pub rejected: Vec<(String, String, Reject)>,
    pub log: LogStats,
}

/// Fetch up to `limit` valid candidates per test from `dir` (newest first, duplicates once) and import their facts
/// into `store`. Nothing is adopted: see [`adopt`].
pub fn fetch(dir: &SharedDir, store: &mut Store, nodeids: &[String], config: &str, runtime: &str, limit: usize) -> Fetched {
    let mut out = Fetched::default();
    let mut get = |id: &str| dir.get(id);
    for nid in nodeids {
        let lookup = lookup_key(nid, config, runtime);
        let lines = dir.keys(&lookup, &mut out.log);
        let mut seen: BTreeSet<String> = BTreeSet::new();
        for l in lines {
            if !seen.insert(l.doc.clone()) {
                continue;
            }
            if let Some(local) = store.tests.get(nid) {
                // the same result is already in the local store: nothing to offer
                if local.key_matches_doc(&l) {
                    continue;
                }
            }
            match import_entry(store, &l.doc, nid, config, runtime, &mut get) {
                Ok(e) => {
                    let v = out.candidates.entry(nid.clone()).or_default();
                    if !v.iter().any(|(_, x)| x.key == e.key && x.run == e.run) {
                        v.push((l.doc.clone(), e));
                    }
                    if v.len() >= limit {
                        break;
                    }
                }
                Err(r) => out.rejected.push((nid.clone(), l.doc.clone(), r)),
            }
        }
    }
    out
}

impl Entry {
    /// Whether a key line names this very result (same run): the local store already has it.
    fn key_matches_doc(&self, l: &KeyLine) -> bool {
        l.run == self.run && !self.run.is_empty()
    }
}

/// Adopt candidates: for each test whose local entry the checker does not accept, the first candidate (newest
/// first) it accepts replaces it; otherwise the local entry stays. Returns `{nodeid: adopted document}`.
pub fn adopt(
    store: &mut Store,
    fetched: &Fetched,
    check: &mut dyn FnMut(&Store, &str) -> bool,
) -> BTreeMap<String, String> {
    let mut adopted = BTreeMap::new();
    for (nid, cands) in &fetched.candidates {
        if store.tests.contains_key(nid) && check(store, nid) {
            continue;
        }
        let local = store.tests.remove(nid);
        let mut ok = false;
        for (doc, e) in cands {
            store.tests.insert(nid.clone(), e.clone());
            if check(store, nid) {
                adopted.insert(nid.clone(), doc.clone());
                ok = true;
                break;
            }
        }
        if !ok {
            match local {
                Some(l) => {
                    store.tests.insert(nid.clone(), l);
                }
                None => {
                    store.tests.remove(nid);
                }
            }
        }
    }
    adopted
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::proof::{Observed, Unit};

    fn store_with(nid: &str, runtime: &str) -> Store {
        let mut s = Store::new();
        let f = s.add_file(CodeFile {
            path: "m.py".into(),
            content: "c1".into(),
            skeleton: "s1".into(),
            hooks: "h".into(),
            units: vec![Unit { q: "f".into(), a: 1, b: 2, d: "u1".into() }],
            imports: vec![],
        });
        s.record(
            nid,
            Observed {
                outcome: "passed".into(),
                fingerprint: "fp".into(),
                duration: 0.5,
                run: "20261119T000000-1".into(),
                config: "cfg".into(),
                runtime: runtime.into(),
                skeleton: vec![f],
                units: vec![(f, 0)],
                data: vec![("data.txt".into(), "f:abc".into())],
                ..Default::default()
            },
        );
        s
    }

    #[test]
    fn roundtrip_through_a_directory() {
        let d = tempfile::tempdir().unwrap();
        let dir = SharedDir::new(d.path());
        let a = store_with("t.py::a", "rt");
        assert_eq!(dir.push(&a, &["t.py::a".into()]).unwrap().0, 1);
        let mut b = Store::new();
        let f = fetch(&dir, &mut b, &["t.py::a".into()], "cfg", "rt", 3);
        assert!(f.rejected.is_empty(), "{:?}", f.rejected);
        let (_, e) = &f.candidates["t.py::a"][0];
        assert_eq!(e.key, a.tests["t.py::a"].key);
        let adopted = adopt(&mut b, &f, &mut |_, _| true);
        assert_eq!(adopted.len(), 1);
        assert_eq!(b.key_of("t.py::a", &b.tests["t.py::a"]), a.tests["t.py::a"].key);
    }

    #[test]
    fn another_runtime_is_foreign_and_never_offered() {
        let d = tempfile::tempdir().unwrap();
        let dir = SharedDir::new(d.path());
        let a = store_with("t.py::a", "other-runtime");
        dir.push(&a, &["t.py::a".into()]).unwrap();
        // a poisoned key line filed under the reader's lookup key, naming the other runtime's document
        let (bytes, _) = export_entry(&a, "t.py::a", None).unwrap();
        let id = address(&bytes);
        dir.append_key(&lookup_key("t.py::a", "cfg", "rt"), &KeyLine { doc: id, run: "x".into(), placement: String::new() })
            .unwrap();
        let mut b = Store::new();
        let f = fetch(&dir, &mut b, &["t.py::a".into()], "cfg", "rt", 3);
        assert!(f.candidates.is_empty());
        assert_eq!(f.rejected.len(), 1);
        assert_eq!(f.rejected[0].2.kind(), "foreign");
    }

    #[test]
    fn partial_uploads_and_corrupt_documents_are_rejected() {
        let d = tempfile::tempdir().unwrap();
        let dir = SharedDir::new(d.path());
        let a = store_with("t.py::a", "rt");
        let (entry, files) = export_entry(&a, "t.py::a", None).unwrap();
        // the entry document and its key line arrive, a file document does not
        let id = dir.put(&entry).unwrap();
        let lookup = lookup_key("t.py::a", "cfg", "rt");
        dir.append_key(&lookup, &KeyLine { doc: id.clone(), run: "r".into(), placement: String::new() }).unwrap();
        let mut b = Store::new();
        let f = fetch(&dir, &mut b, &["t.py::a".into()], "cfg", "rt", 3);
        assert_eq!(f.rejected[0].2.kind(), "incomplete");
        assert!(b.files.is_empty(), "nothing imported from an incomplete entry");
        // the file document arrives truncated
        let fid = address(&files[0]);
        let p = dir.blob_path(&fid);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(&p, &files[0][..files[0].len() / 2]).unwrap();
        let f = fetch(&dir, &mut b, &["t.py::a".into()], "cfg", "rt", 3);
        assert_eq!(f.rejected[0].2.kind(), "corrupt");
        // a torn key line (a crashed writer) is dropped, the log stays readable
        let kp = dir.key_path(&lookup);
        let mut fh = fs::OpenOptions::new().append(true).open(&kp).unwrap();
        fh.write_all(b"{\"doc\":\"abc").unwrap();
        drop(fh);
        dir.put(&files[0]).unwrap(); // repaired: the valid document replaces the truncated one
        let mut st = LogStats::default();
        assert_eq!(dir.keys(&lookup, &mut st).len(), 1);
        assert_eq!(st.torn, 1);
        let mut c = Store::new();
        let f = fetch(&dir, &mut c, &["t.py::a".into()], "cfg", "rt", 3);
        assert!(f.rejected.is_empty(), "{:?}", f.rejected);
        assert_eq!(f.candidates["t.py::a"].len(), 1);
    }

    #[test]
    fn a_tampered_entry_whose_key_does_not_match_its_inputs_is_rejected() {
        let d = tempfile::tempdir().unwrap();
        let dir = SharedDir::new(d.path());
        let mut a = store_with("t.py::a", "rt");
        // claims the old key but its data input was changed (a forged pass)
        a.tests.get_mut("t.py::a").unwrap().data = vec![("data.txt".into(), "f:zzz".into())];
        dir.push(&a, &["t.py::a".into()]).unwrap();
        let mut b = Store::new();
        let f = fetch(&dir, &mut b, &["t.py::a".into()], "cfg", "rt", 3);
        assert_eq!(f.rejected[0].2.kind(), "key-mismatch");
    }

    #[test]
    fn concurrent_writers_lose_nothing() {
        let d = tempfile::tempdir().unwrap();
        let root = d.path().to_path_buf();
        let threads: Vec<_> = (0..8)
            .map(|i| {
                let root = root.clone();
                std::thread::spawn(move || {
                    let dir = SharedDir::new(root);
                    for j in 0..25 {
                        let s = store_with(&format!("t.py::w{i}_{j}"), "rt");
                        dir.push(&s, &[format!("t.py::w{i}_{j}")]).unwrap();
                        // and every writer pushes the same shared test too
                        let s = store_with("t.py::shared", "rt");
                        dir.push(&s, &["t.py::shared".into()]).unwrap();
                    }
                })
            })
            .collect();
        for t in threads {
            t.join().unwrap();
        }
        let dir = SharedDir::new(&root);
        let mut st = LogStats::default();
        assert_eq!(dir.keys(&lookup_key("t.py::shared", "cfg", "rt"), &mut st).len(), 200);
        assert_eq!(st.torn, 0);
        let ids: Vec<String> = (0..8).flat_map(|i| (0..25).map(move |j| format!("t.py::w{i}_{j}"))).collect();
        let mut b = Store::new();
        let f = fetch(&dir, &mut b, &ids, "cfg", "rt", 1);
        assert!(f.rejected.is_empty());
        assert_eq!(f.candidates.len(), 200);
    }

    #[test]
    fn order_is_the_log_order_not_the_recorded_clock() {
        let d = tempfile::tempdir().unwrap();
        let dir = SharedDir::new(d.path());
        // machine A's clock is a year ahead: its run id says 2027; machine B pushes later with a correct clock
        let mut a = store_with("t.py::a", "rt");
        a.tests.get_mut("t.py::a").unwrap().run = "20271119T000000-1".into();
        dir.push(&a, &["t.py::a".into()]).unwrap();
        let mut b = store_with("t.py::a", "rt");
        b.tests.get_mut("t.py::a").unwrap().fingerprint = "fp-b".into();
        let k = b.key_of("t.py::a", &b.tests["t.py::a"]);
        b.tests.get_mut("t.py::a").unwrap().key = k;
        dir.push(&b, &["t.py::a".into()]).unwrap();
        let mut c = Store::new();
        let f = fetch(&dir, &mut c, &["t.py::a".into()], "cfg", "rt", 3);
        let c0 = &f.candidates["t.py::a"];
        assert_eq!(c0.len(), 2);
        assert_eq!(c0[0].1.fingerprint, "fp-b", "the later push comes first, whatever its clock said");
    }
}
