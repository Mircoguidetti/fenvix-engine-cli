//! Content digest of directory trees (runtime identity of installed packages).
//!
//! Every regular file is keyed by its path relative to the tree root and its bytes; every symbolic link by its
//! target text. A link whose target resolves outside `inside` (the project root) is followed and its content is
//! keyed under the link's path (a package linked in from elsewhere: `npm link`, a global store); links that stay
//! inside are keyed by their text only (their targets are walked where they live, or are project files that are
//! per-test inputs). Directories and files whose name is in `exclude` are skipped (installer bookkeeping written
//! per machine). File digests are memoised by (device, inode, size, mtime, ctime) in an optional memo file.
//! Roots are walked and files hashed in parallel; a directory is identified by device and inode (cycles and
//! directories reached twice through followed links).

use crate::fingerprint::digest_bytes;
use crate::proof::file_digest;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

#[derive(Clone, Debug, Default, Serialize)]
pub struct TreeDigest {
    pub digest: String,
    pub files: u64,
    pub links: u64,
    pub bytes: u64,
    pub hashed: u64,
    pub followed: u64,
    /// Trees cut at `max_files` (never reusable: the caller makes the digest unique).
    pub truncated: bool,
    /// Per-root digests (root label -> digest).
    pub roots: BTreeMap<String, String>,
}

type Stamp = (u64, u64, u64, i64, i64);

/// File digests memoised by stamp, keyed by absolute path. Stored in a compact binary file (`FXMEMO2`); the JSON
/// form of earlier versions (`{"v":1,"files":{...}}`) is still read.
#[derive(Clone, Debug, Default)]
struct Memo {
    files: HashMap<String, (Stamp, String)>,
    /// read from the JSON form: written again in the binary one
    legacy: bool,
}

const MEMO_MAGIC: &[u8] = b"FXMEMO2\n";

#[derive(Deserialize)]
struct MemoV1 {
    v: u32,
    files: BTreeMap<String, (u64, u64, u64, i64, i64, String)>,
}

fn rd_u64(b: &[u8], i: &mut usize) -> Option<u64> {
    let x = b.get(*i..*i + 8)?;
    *i += 8;
    Some(u64::from_le_bytes(x.try_into().ok()?))
}

fn rd_str(b: &[u8], i: &mut usize) -> Option<String> {
    let n = rd_u64(b, i)? as usize;
    let x = b.get(*i..*i + n)?;
    *i += n;
    String::from_utf8(x.to_vec()).ok()
}

impl Memo {
    fn load(p: &Path) -> Memo {
        let Ok(b) = fs::read(p) else {
            return Memo::default();
        };
        if let Some(body) = b.strip_prefix(MEMO_MAGIC) {
            let mut files = HashMap::new();
            let mut i = 0;
            let Some(n) = rd_u64(body, &mut i) else {
                return Memo::default();
            };
            files.reserve(n as usize);
            for _ in 0..n {
                let (Some(k), Some(a), Some(b2), Some(c), Some(d), Some(e), Some(dg)) = (
                    rd_str(body, &mut i),
                    rd_u64(body, &mut i),
                    rd_u64(body, &mut i),
                    rd_u64(body, &mut i),
                    rd_u64(body, &mut i),
                    rd_u64(body, &mut i),
                    rd_str(body, &mut i),
                ) else {
                    return Memo::default();
                };
                files.insert(k, ((a, b2, c, d as i64, e as i64), dg));
            }
            return Memo { files, legacy: false };
        }
        match serde_json::from_slice::<MemoV1>(&b) {
            Ok(m) if m.v == 1 => Memo {
                files: m.files.into_iter().map(|(k, (a, b2, c, d, e, dg))| (k, ((a, b2, c, d, e), dg))).collect(),
                legacy: true,
            },
            _ => Memo::default(),
        }
    }

    fn save(&self, p: &Path) {
        let mut keys: Vec<&String> = self.files.keys().collect();
        keys.sort();
        let mut buf = Vec::with_capacity(MEMO_MAGIC.len() + self.files.len() * 120);
        buf.extend_from_slice(MEMO_MAGIC);
        buf.extend_from_slice(&(keys.len() as u64).to_le_bytes());
        let put_str = |buf: &mut Vec<u8>, s: &str| {
            buf.extend_from_slice(&(s.len() as u64).to_le_bytes());
            buf.extend_from_slice(s.as_bytes());
        };
        for k in keys {
            let (st, dg) = &self.files[k];
            put_str(&mut buf, k);
            for x in [st.0, st.1, st.2, st.3 as u64, st.4 as u64] {
                buf.extend_from_slice(&x.to_le_bytes());
            }
            put_str(&mut buf, dg);
        }
        if let Some(parent) = p.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let tmp = p.with_extension(format!("tmp{}", std::process::id()));
        if fs::write(&tmp, buf).is_ok() {
            let _ = fs::rename(&tmp, p);
        }
    }
}

#[cfg(unix)]
fn stamp(m: &fs::Metadata) -> Stamp {
    use std::os::unix::fs::MetadataExt;
    (m.dev(), m.ino(), m.size(), m.mtime() * 1_000_000_000 + m.mtime_nsec(), m.ctime() * 1_000_000_000 + m.ctime_nsec())
}

#[cfg(not(unix))]
fn stamp(m: &fs::Metadata) -> Stamp {
    let t = m
        .modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_nanos() as i64)
        .unwrap_or(0);
    (0, 0, m.len(), t, t)
}

#[cfg(unix)]
fn is_exec(m: &fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    m.permissions().mode() & 0o111 != 0
}

#[cfg(not(unix))]
fn is_exec(_m: &fs::Metadata) -> bool {
    false
}

/// Identity of a directory (the directory a canonical path names): device and inode, without resolving the path.
#[cfg(unix)]
type DirKey = (u64, u64);
#[cfg(unix)]
fn dir_key(_p: &Path, m: &fs::Metadata) -> Option<DirKey> {
    use std::os::unix::fs::MetadataExt;
    Some((m.dev(), m.ino()))
}
#[cfg(not(unix))]
type DirKey = PathBuf;
#[cfg(not(unix))]
fn dir_key(p: &Path, _m: &fs::Metadata) -> Option<DirKey> {
    fs::canonicalize(p).ok()
}

enum Rec {
    File { rel: String, abs: PathBuf, exec: bool, st: Stamp },
    Link { rel: String, target: String },
}

struct Walk<'a> {
    inside: PathBuf,
    exclude: &'a HashSet<String>,
    suffixes: &'a [String],
    max_files: usize,
    recs: Vec<Rec>,
    visited: HashSet<DirKey>,
    followed: u64,
    truncated: bool,
}

impl Walk<'_> {
    fn walk(&mut self, dir: &Path, rel: &str) {
        if self.recs.len() > self.max_files {
            self.truncated = true;
            return;
        }
        let Ok(rd) = fs::read_dir(dir) else { return };
        // the entry type comes with the listing (no system call per entry for it)
        let mut names: Vec<(String, PathBuf, Option<fs::FileType>)> = rd
            .filter_map(|e| e.ok())
            .map(|e| (e.file_name().to_string_lossy().into_owned(), e.path(), e.file_type().ok()))
            .collect();
        names.sort_by(|a, b| a.0.cmp(&b.0));
        for (name, p, ft) in names {
            if self.exclude.contains(&name) || self.suffixes.iter().any(|x| name.ends_with(x.as_str())) {
                continue;
            }
            let r = if rel.is_empty() { name.clone() } else { format!("{rel}/{name}") };
            let Some(ft) = ft else { continue };
            if ft.is_symlink() {
                let target = fs::read_link(&p).map(|t| t.to_string_lossy().into_owned()).unwrap_or_default();
                self.recs.push(Rec::Link { rel: r.clone(), target });
                let Ok(real) = fs::canonicalize(&p) else {
                    continue;
                };
                if real.starts_with(&self.inside) {
                    continue;
                }
                let Ok(m) = fs::metadata(&real) else { continue };
                self.followed += 1;
                if m.is_dir() {
                    if let Some(k) = dir_key(&real, &m) {
                        if self.visited.insert(k) {
                            self.walk(&real, &format!("{r}/->"));
                        }
                    }
                } else if m.is_file() {
                    self.recs.push(Rec::File { rel: format!("{r}/->"), abs: real, exec: is_exec(&m), st: stamp(&m) });
                }
            } else if ft.is_dir() {
                if let Ok(m) = fs::symlink_metadata(&p) {
                    if let Some(k) = dir_key(&p, &m) {
                        if !self.visited.insert(k) {
                            continue;
                        }
                    }
                }
                self.walk(&p, &r);
            } else if ft.is_file() {
                let Ok(lm) = fs::symlink_metadata(&p) else {
                    continue;
                };
                self.recs.push(Rec::File { rel: r, abs: p, exec: is_exec(&lm), st: stamp(&lm) });
            }
        }
    }
}

fn push_part(buf: &mut Vec<u8>, part: &str) {
    buf.extend_from_slice(&(part.len() as u64).to_le_bytes());
    buf.extend_from_slice(part.as_bytes());
}

/// Run `f(i)` for `i` in `0..n` on up to `threads` threads; results in index order.
fn par_map<T: Send, F: Fn(usize) -> T + Sync>(n: usize, threads: usize, f: F) -> Vec<T> {
    let next = AtomicUsize::new(0);
    let out: Mutex<Vec<(usize, T)>> = Mutex::new(Vec::with_capacity(n));
    std::thread::scope(|s| {
        for _ in 0..threads.clamp(1, n.max(1)) {
            s.spawn(|| {
                let mut local = Vec::new();
                loop {
                    let j = next.fetch_add(1, Ordering::Relaxed);
                    if j >= n {
                        break;
                    }
                    local.push((j, f(j)));
                }
                out.lock().unwrap_or_else(|e| e.into_inner()).extend(local);
            });
        }
    });
    let mut v = out.into_inner().unwrap_or_else(|e| e.into_inner());
    v.sort_by_key(|x| x.0);
    v.into_iter().map(|x| x.1).collect()
}

/// Digest of the trees `roots` (label, absolute directory). Missing roots count as empty with their label.
/// Roots are walked in parallel, files hashed in parallel (memo first); the digest does not depend on the order.
pub fn tree_digest(
    roots: &[(String, PathBuf)],
    inside: &Path,
    exclude: &[String],
    memo_path: Option<&Path>,
    max_files: usize,
    threads: usize,
) -> TreeDigest {
    // "*.ext" entries exclude by suffix, others by exact name
    let suffixes: Vec<String> = exclude.iter().filter_map(|e| e.strip_prefix('*').map(str::to_string)).collect();
    let exclude: HashSet<String> = exclude.iter().filter(|e| !e.starts_with('*')).cloned().collect();
    let mut memo = memo_path.map(Memo::load).unwrap_or_default();
    let inside = fs::canonicalize(inside).unwrap_or_else(|_| inside.to_path_buf());
    let mut out = TreeDigest::default();
    // walk every root (in parallel)
    let walks: Vec<(Vec<Rec>, u64, bool)> = par_map(roots.len(), threads, |ri| {
        let dir = &roots[ri].1;
        let mut w = Walk {
            inside: inside.clone(),
            exclude: &exclude,
            suffixes: &suffixes,
            max_files,
            recs: Vec::new(),
            visited: HashSet::new(),
            followed: 0,
            truncated: false,
        };
        if let Ok(m) = fs::metadata(dir) {
            if let Some(k) = dir_key(dir, &m) {
                w.visited.insert(k);
            }
        }
        w.walk(dir, "");
        (w.recs, w.followed, w.truncated)
    });
    // hash the files the memo does not know (in parallel, across roots)
    let mut todo: Vec<(usize, usize)> = Vec::new();
    let mut digests: Vec<Vec<Option<String>>> = Vec::with_capacity(walks.len());
    for (wi, (recs, followed, truncated)) in walks.iter().enumerate() {
        out.followed += followed;
        out.truncated |= truncated;
        let mut d: Vec<Option<String>> = vec![None; recs.len()];
        for (i, r) in recs.iter().enumerate() {
            if let Rec::File { abs, st, .. } = r {
                match memo.files.get(abs.to_string_lossy().as_ref()) {
                    Some((m, dg)) if m == st => d[i] = Some(dg.clone()),
                    _ => todo.push((wi, i)),
                }
            }
        }
        digests.push(d);
    }
    out.hashed += todo.len() as u64;
    let hashed = par_map(todo.len(), threads, |j| {
        let (wi, i) = todo[j];
        match &walks[wi].0[i] {
            Rec::File { abs, .. } => file_digest(abs),
            Rec::Link { .. } => None,
        }
    });
    let mut dirty = false;
    for ((wi, i), d) in todo.iter().zip(hashed) {
        if let (Some(dg), Rec::File { abs, st, .. }) = (&d, &walks[*wi].0[*i]) {
            memo.files.insert(abs.to_string_lossy().into_owned(), (*st, dg.clone()));
            dirty = true;
        }
        digests[*wi][*i] = d;
    }
    let mut all = Vec::new();
    for (ri, (label, _)) in roots.iter().enumerate() {
        let recs = &walks[ri].0;
        let mut buf = Vec::new();
        push_part(&mut buf, "fenvix-tree-1");
        push_part(&mut buf, label);
        for (i, r) in recs.iter().enumerate() {
            match r {
                Rec::File { rel, exec, st, .. } => {
                    let d = digests[ri][i].as_deref().unwrap_or("unreadable");
                    out.files += 1;
                    out.bytes += st.2;
                    push_part(&mut buf, "F");
                    push_part(&mut buf, rel);
                    push_part(&mut buf, if *exec { "x" } else { "-" });
                    push_part(&mut buf, d);
                }
                Rec::Link { rel, target } => {
                    out.links += 1;
                    push_part(&mut buf, "L");
                    push_part(&mut buf, rel);
                    push_part(&mut buf, target);
                }
            }
        }
        let d = digest_bytes(&buf).short();
        out.roots.insert(label.clone(), d.clone());
        all.push((label.clone(), d));
    }
    all.sort();
    let mut buf = Vec::new();
    push_part(&mut buf, "fenvix-trees-1");
    for (l, d) in &all {
        push_part(&mut buf, l);
        push_part(&mut buf, d);
    }
    out.digest = digest_bytes(&buf).short();
    // the memo keeps entries of other trees (other projects share it); it is written only when it learned something
    if let Some(p) = memo_path {
        if dirty || memo.legacy || !p.exists() {
            memo.save(p);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn content_not_location() {
        let a = tempfile::tempdir().unwrap();
        let b = tempfile::tempdir().unwrap();
        for d in [a.path(), b.path()] {
            fs::create_dir_all(d.join("nm/pkg")).unwrap();
            fs::write(d.join("nm/pkg/index.js"), "x").unwrap();
        }
        let ex = vec![".cache".to_string()];
        let da = tree_digest(&[("nm".into(), a.path().join("nm"))], a.path(), &ex, None, 1000, 2);
        let db = tree_digest(&[("nm".into(), b.path().join("nm"))], b.path(), &ex, None, 1000, 2);
        assert_eq!(da.digest, db.digest);
        fs::write(b.path().join("nm/pkg/index.js"), "y").unwrap();
        let db2 = tree_digest(&[("nm".into(), b.path().join("nm"))], b.path(), &ex, None, 1000, 2);
        assert_ne!(da.digest, db2.digest);
        fs::create_dir_all(b.path().join("nm/.cache")).unwrap();
        fs::write(b.path().join("nm/.cache/junk"), "z").unwrap();
        let db3 = tree_digest(&[("nm".into(), b.path().join("nm"))], b.path(), &ex, None, 1000, 2);
        assert_eq!(db2.digest, db3.digest);
        let ex2 = vec![".cache".to_string(), "*.tsbuildinfo".to_string()];
        let d4 = tree_digest(&[("nm".into(), b.path().join("nm"))], b.path(), &ex2, None, 1000, 2);
        fs::write(b.path().join("nm/pkg/x.tsbuildinfo"), "state").unwrap();
        let d5 = tree_digest(&[("nm".into(), b.path().join("nm"))], b.path(), &ex2, None, 1000, 2);
        assert_eq!(d4.digest, d5.digest, "suffix exclusion");
    }

    #[test]
    fn memo_and_external_links() {
        let root = tempfile::tempdir().unwrap();
        let ext = tempfile::tempdir().unwrap();
        fs::create_dir_all(root.path().join("nm")).unwrap();
        fs::create_dir_all(ext.path().join("lib")).unwrap();
        fs::write(ext.path().join("lib/a.js"), "1").unwrap();
        #[cfg(unix)]
        std::os::unix::fs::symlink(ext.path().join("lib"), root.path().join("nm/linked")).unwrap();
        let memo = root.path().join("memo.json");
        let r = [("nm".to_string(), root.path().join("nm"))];
        let d1 = tree_digest(&r, root.path(), &[], Some(&memo), 1000, 2);
        let d2 = tree_digest(&r, root.path(), &[], Some(&memo), 1000, 2);
        assert_eq!(d1.digest, d2.digest);
        assert_eq!(d2.hashed, 0);
        #[cfg(unix)]
        {
            assert_eq!(d1.followed, 1);
            fs::write(ext.path().join("lib/a.js"), "2").unwrap();
            let d3 = tree_digest(&r, root.path(), &[], Some(&memo), 1000, 2);
            assert_ne!(d1.digest, d3.digest);
        }
    }
}
