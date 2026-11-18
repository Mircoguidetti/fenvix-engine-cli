//! Content digest of directory trees (runtime identity of installed packages).
//!
//! Every regular file is keyed by its path relative to the tree root and its bytes; every symbolic link by its
//! target text. A link whose target resolves outside `inside` (the project root) is followed and its content is
//! keyed under the link's path (a package linked in from elsewhere: `npm link`, a global store); links that stay
//! inside are keyed by their text only (their targets are walked where they live, or are project files that are
//! per-test inputs). Directories and files whose name is in `exclude` are skipped (installer bookkeeping written
//! per machine). File digests are memoised by (device, inode, size, mtime, ctime) in an optional memo file.

use crate::fingerprint::digest_bytes;
use crate::proof::file_digest;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
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

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct Memo {
    v: u32,
    files: BTreeMap<String, (u64, u64, u64, i64, i64, String)>,
}

#[cfg(unix)]
fn stamp(m: &fs::Metadata) -> (u64, u64, u64, i64, i64) {
    use std::os::unix::fs::MetadataExt;
    (m.dev(), m.ino(), m.size(), m.mtime() * 1_000_000_000 + m.mtime_nsec(), m.ctime() * 1_000_000_000 + m.ctime_nsec())
}

#[cfg(not(unix))]
fn stamp(m: &fs::Metadata) -> (u64, u64, u64, i64, i64) {
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

enum Rec {
    File { rel: String, abs: PathBuf, exec: bool, st: (u64, u64, u64, i64, i64) },
    Link { rel: String, target: String },
}

struct Walk<'a> {
    inside: PathBuf,
    exclude: &'a HashSet<String>,
    max_files: usize,
    recs: Vec<Rec>,
    visited: HashSet<PathBuf>,
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
        let mut names: Vec<(String, PathBuf)> =
            rd.filter_map(|e| e.ok()).map(|e| (e.file_name().to_string_lossy().into_owned(), e.path())).collect();
        names.sort();
        for (name, p) in names {
            if self.exclude.contains(&name) {
                continue;
            }
            let r = if rel.is_empty() { name.clone() } else { format!("{rel}/{name}") };
            let Ok(lm) = fs::symlink_metadata(&p) else { continue };
            if lm.file_type().is_symlink() {
                let target = fs::read_link(&p).map(|t| t.to_string_lossy().into_owned()).unwrap_or_default();
                self.recs.push(Rec::Link { rel: r.clone(), target });
                let Ok(real) = fs::canonicalize(&p) else { continue };
                if real.starts_with(&self.inside) {
                    continue;
                }
                let Ok(m) = fs::metadata(&real) else { continue };
                self.followed += 1;
                if m.is_dir() {
                    if self.visited.insert(real.clone()) {
                        self.walk(&real, &format!("{r}/->"));
                    }
                } else if m.is_file() {
                    self.recs.push(Rec::File { rel: format!("{r}/->"), abs: real, exec: is_exec(&m), st: stamp(&m) });
                }
            } else if lm.is_dir() {
                if let Ok(real) = fs::canonicalize(&p) {
                    if !self.visited.insert(real) {
                        continue;
                    }
                }
                self.walk(&p, &r);
            } else if lm.is_file() {
                self.recs.push(Rec::File { rel: r, abs: p, exec: is_exec(&lm), st: stamp(&lm) });
            }
        }
    }
}

fn push_part(buf: &mut Vec<u8>, part: &str) {
    buf.extend_from_slice(&(part.len() as u64).to_le_bytes());
    buf.extend_from_slice(part.as_bytes());
}

/// Digest of the trees `roots` (label, absolute directory). Missing roots count as empty with their label.
pub fn tree_digest(
    roots: &[(String, PathBuf)],
    inside: &Path,
    exclude: &[String],
    memo_path: Option<&Path>,
    max_files: usize,
    threads: usize,
) -> TreeDigest {
    let exclude: HashSet<String> = exclude.iter().cloned().collect();
    let mut memo: Memo = memo_path
        .and_then(|p| fs::read(p).ok())
        .and_then(|b| serde_json::from_slice(&b).ok())
        .filter(|m: &Memo| m.v == 1)
        .unwrap_or(Memo { v: 1, ..Default::default() });
    let inside = fs::canonicalize(inside).unwrap_or_else(|_| inside.to_path_buf());
    let mut out = TreeDigest::default();
    let mut all = Vec::new();
    let mut new_memo: BTreeMap<String, (u64, u64, u64, i64, i64, String)> = BTreeMap::new();
    for (label, dir) in roots {
        let mut w = Walk {
            inside: inside.clone(),
            exclude: &exclude,
            max_files,
            recs: Vec::new(),
            visited: HashSet::new(),
            followed: 0,
            truncated: false,
        };
        if let Ok(real) = fs::canonicalize(dir) {
            w.visited.insert(real);
        }
        w.walk(dir, "");
        out.followed += w.followed;
        out.truncated |= w.truncated;
        // hash files (memo first, then in parallel)
        let recs = w.recs;
        let mut digests: Vec<Option<String>> = vec![None; recs.len()];
        let mut todo = Vec::new();
        for (i, r) in recs.iter().enumerate() {
            if let Rec::File { abs, st, .. } = r {
                let k = abs.to_string_lossy().into_owned();
                match memo.files.get(&k) {
                    Some(m) if (m.0, m.1, m.2, m.3, m.4) == *st => digests[i] = Some(m.5.clone()),
                    _ => todo.push(i),
                }
            }
        }
        out.hashed += todo.len() as u64;
        let results: Mutex<Vec<(usize, Option<String>)>> = Mutex::new(Vec::with_capacity(todo.len()));
        let next = AtomicUsize::new(0);
        std::thread::scope(|s| {
            for _ in 0..threads.max(1) {
                s.spawn(|| {
                    let mut local = Vec::new();
                    loop {
                        let j = next.fetch_add(1, Ordering::Relaxed);
                        if j >= todo.len() {
                            break;
                        }
                        let i = todo[j];
                        if let Rec::File { abs, .. } = &recs[i] {
                            local.push((i, file_digest(abs)));
                        }
                    }
                    results.lock().unwrap_or_else(|e| e.into_inner()).extend(local);
                });
            }
        });
        for (i, d) in results.into_inner().unwrap_or_else(|e| e.into_inner()) {
            digests[i] = d;
        }
        let mut buf = Vec::new();
        push_part(&mut buf, "fenvix-tree-1");
        push_part(&mut buf, label);
        for (i, r) in recs.iter().enumerate() {
            match r {
                Rec::File { rel, abs, exec, st } => {
                    let d = digests[i].clone().unwrap_or_else(|| "unreadable".into());
                    out.files += 1;
                    out.bytes += st.2;
                    push_part(&mut buf, "F");
                    push_part(&mut buf, rel);
                    push_part(&mut buf, if *exec { "x" } else { "-" });
                    push_part(&mut buf, &d);
                    if d != "unreadable" {
                        new_memo.insert(abs.to_string_lossy().into_owned(), (st.0, st.1, st.2, st.3, st.4, d));
                    }
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
    if let Some(p) = memo_path {
        // keep entries of other trees (other projects share the memo); refresh the ones walked now
        memo.files.extend(new_memo);
        if let Some(parent) = p.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let tmp = p.with_extension(format!("tmp{}", std::process::id()));
        if let Ok(b) = serde_json::to_vec(&memo) {
            if fs::write(&tmp, b).is_ok() {
                let _ = fs::rename(&tmp, p);
            }
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
