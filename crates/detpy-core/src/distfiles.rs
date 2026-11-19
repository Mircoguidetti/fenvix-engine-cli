//! Installed files of the Python distributions, for the per-distribution cache identity
//! (`--det-cache-dists`, prototype).
//!
//! Built from every distribution's `RECORD`, including the paths a wheel installs outside its site directory
//! (`../../../bin/tool`, `../../../lib/libx.so`: scripts and the data scheme). A path can be claimed by more than
//! one distribution (`opencv-python` and `opencv-python-headless`, `pycrypto` and `pycryptodome`): upgrading any
//! one of them rewrites the file, so a lookup returns every claimant (review R-020b N1).
//!
//! A file also belongs to a *claim group*: the top-level entry it sits under in its site directory, or its own
//! directory when it is installed outside the site directory. The group's claim content lists the distributions
//! that install anything in the group and every path of the group claimed more than once. A dependency on the
//! group catches a bump that makes a distribution claim (overwrite) a file it did not claim before: either the
//! distribution is new in the group, or the set of shared paths changes.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Component, Path, PathBuf};

/// Owner name of the files of the project's own (editable) install.
pub const PROJECT: &str = "";

#[derive(Debug, Default)]
pub struct DistFiles {
    names: Vec<String>,
    name_ix: HashMap<String, u32>,
    groups: Vec<String>,
    group_ix: HashMap<String, u32>,
    /// absolute path -> (sorted owner ids, group id; u32::MAX for project files)
    files: HashMap<String, (Vec<u32>, u32)>,
    /// top-level directory under a site directory -> (sole owner, group), None when shared
    dirs: HashMap<String, Option<(u32, u32)>>,
    /// top-level module name -> owners
    tops: BTreeMap<String, BTreeSet<u32>>,
    /// group -> path -> owners
    claims: BTreeMap<u32, BTreeMap<String, BTreeSet<u32>>>,
}

const NO_GROUP: u32 = u32::MAX;

/// Lexical normalisation (`.` and `..` removed), as `os.path.normpath` on an absolute path.
fn normalise(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// `os.path.realpath`: symlinks resolved for the part of the path that exists.
pub fn realpath(p: &str) -> String {
    let n = normalise(Path::new(p));
    if let Ok(r) = std::fs::canonicalize(&n) {
        return r.to_string_lossy().into_owned();
    }
    let mut tail = Vec::new();
    let mut head = n.clone();
    while let Some(name) = head.file_name().map(|s| s.to_os_string()) {
        head.pop();
        tail.push(name);
        if let Ok(mut r) = std::fs::canonicalize(&head) {
            for t in tail.iter().rev() {
                r.push(t);
            }
            return r.to_string_lossy().into_owned();
        }
    }
    n.to_string_lossy().into_owned()
}

fn is_identifier(s: &str) -> bool {
    let mut cs = s.chars();
    match cs.next() {
        Some(c) if c == '_' || c.is_alphabetic() => {}
        _ => return false,
    }
    cs.all(|c| c == '_' || c.is_alphanumeric())
}

/// Top-level module name a RECORD path provides (None for metadata, scripts, data).
pub fn top_of(rel: &str) -> Option<String> {
    if rel.starts_with("..") || rel.starts_with('/') {
        return None;
    }
    let first = rel.split('/').next().unwrap_or("");
    if first.ends_with(".dist-info") || first.ends_with(".egg-info") || first.ends_with(".data") || first == "__pycache__" {
        return None;
    }
    if rel.contains('/') {
        return is_identifier(first).then(|| first.to_string());
    }
    if let Some(n) = first.strip_suffix(".py") {
        return is_identifier(n).then(|| n.to_string());
    }
    if first.ends_with(".so") || first.ends_with(".pyd") {
        let n = first.split('.').next().unwrap_or("");
        return is_identifier(n).then(|| n.to_string());
    }
    None
}

/// The path of one RECORD line (`path,hash,size`; a path may contain commas).
fn record_path(line: &str) -> &str {
    if line.matches(',').count() >= 2 {
        line.rsplitn(3, ',').last().unwrap_or("")
    } else {
        line.split(',').next().unwrap_or("")
    }
}

fn join(base: &str, rel: &str) -> String {
    if rel.starts_with('/') {
        rel.to_string()
    } else if base.ends_with('/') {
        format!("{base}{rel}")
    } else {
        format!("{base}/{rel}")
    }
}

fn parent(p: &str) -> &str {
    match p.rfind('/') {
        Some(0) => "/",
        Some(i) => &p[..i],
        None => "",
    }
}

impl DistFiles {
    pub fn new() -> Self {
        Self::default()
    }

    fn name(&mut self, n: &str) -> u32 {
        if let Some(&i) = self.name_ix.get(n) {
            return i;
        }
        let i = self.names.len() as u32;
        self.names.push(n.to_string());
        self.name_ix.insert(n.to_string(), i);
        i
    }

    fn group(&mut self, g: String) -> u32 {
        if let Some(&i) = self.group_ix.get(&g) {
            return i;
        }
        let i = self.groups.len() as u32;
        self.groups.push(g.clone());
        self.group_ix.insert(g, i);
        i
    }

    /// The project's own editable install: `path` (its metadata directory) belongs to the project.
    pub fn add_project_path(&mut self, path: &str) {
        let p = realpath(path);
        let o = self.name(PROJECT);
        self.files.insert(p.clone(), (vec![o], NO_GROUP));
        self.dirs.insert(p, Some((o, NO_GROUP)));
    }

    /// Add the RECORD of distribution `owner` installed under `base` (its site directory, real path).
    pub fn add(&mut self, owner: &str, base: &str, record: &str, project: bool) {
        let o = self.name(if project { PROJECT } else { owner });
        for line in record.lines() {
            let rel = record_path(line);
            if rel.is_empty() {
                continue;
            }
            let outside = rel.starts_with("..") || rel.starts_with('/') || rel.contains("/../");
            let ap = if rel.contains("..") { realpath(&join(base, rel)) } else { join(base, rel) };
            if project {
                self.files.insert(ap, (vec![o], NO_GROUP));
                continue;
            }
            let g = if outside {
                parent(&ap).to_string()
            } else {
                join(base, rel.split('/').next().unwrap_or(rel))
            };
            let gi = self.group(g.clone());
            let e = self.files.entry(ap.clone()).or_insert_with(|| (Vec::new(), gi));
            if !e.0.contains(&o) {
                e.0.push(o);
                e.0.sort_unstable();
            }
            self.claims.entry(gi).or_default().entry(ap).or_default().insert(o);
            if !outside && rel.contains('/') {
                let prev = self.dirs.get(&g).copied();
                let v = match prev {
                    None => Some((o, gi)),
                    Some(Some((p, _))) if p == o => Some((o, gi)),
                    _ => None,
                };
                self.dirs.insert(g, v);
            }
            if let Some(t) = top_of(rel) {
                self.tops.entry(t).or_default().insert(o);
            }
        }
    }

    fn found(&self, owners: &[u32], g: u32) -> (Vec<String>, Option<String>) {
        (
            owners.iter().map(|&i| self.names[i as usize].clone()).collect(),
            (g != NO_GROUP).then(|| self.groups[g as usize].clone()),
        )
    }

    /// Owners of `path` (absolute) and its claim group; None when no RECORD explains it (or it sits under a
    /// top-level directory several distributions install into without listing it).
    pub fn lookup(&self, path: &str) -> Option<(Vec<String>, Option<String>)> {
        if let Some((o, g)) = self.files.get(path) {
            return Some(self.found(o, *g));
        }
        let rp = realpath(path);
        if let Some((o, g)) = self.files.get(&rp) {
            return Some(self.found(o, *g));
        }
        // bytecode caches of a recorded source file
        let d = parent(&rp);
        if d.rsplit('/').next() == Some("__pycache__") {
            let f = &rp[d.len() + 1..];
            let src = format!("{}/{}.py", parent(d), f.split('.').next().unwrap_or(""));
            if let Some((o, g)) = self.files.get(&src) {
                return Some(self.found(o, *g));
            }
        }
        // a file under a top-level directory that only one distribution installs
        let mut p: &str = &rp;
        loop {
            if let Some(v) = self.dirs.get(p) {
                return v.map(|(o, g)| self.found(&[o], g));
            }
            let up = parent(p);
            if up == p || up.is_empty() {
                return None;
            }
            p = up;
        }
    }

    /// Top-level module name -> owners (sorted).
    pub fn tops(&self) -> Vec<(String, Vec<String>)> {
        self.tops
            .iter()
            .map(|(t, os)| {
                let mut v: Vec<String> = os.iter().map(|&i| self.names[i as usize].clone()).collect();
                v.sort();
                (t.clone(), v)
            })
            .collect()
    }

    /// Claim content of every group: its claimants, then every path of it that more than one distribution
    /// claims, with its claimants.
    pub fn claims(&self) -> Vec<(String, String)> {
        let mut out = Vec::with_capacity(self.claims.len());
        for (&g, paths) in &self.claims {
            let mut all = BTreeSet::new();
            let mut shared = String::new();
            for (p, os) in paths {
                let names: BTreeSet<&str> = os.iter().map(|&i| self.names[i as usize].as_str()).collect();
                all.extend(names.iter().copied());
                if names.len() > 1 {
                    shared.push_str(p);
                    for n in &names {
                        shared.push(' ');
                        shared.push_str(n);
                    }
                    shared.push('\n');
                }
            }
            let g = &self.groups[g as usize];
            let mut s = format!("{g}\n");
            for n in &all {
                s.push_str(n);
                s.push(' ');
            }
            s.push('\n');
            s.push_str(&shared);
            out.push((g.clone(), s));
        }
        out
    }
}

/// Dependency string of an existence check (`os.stat`, `os.path.exists`, `shutil.which`...) of `path`:
/// "s:<kind>" with kind "file", "dir", "other" or "missing". Any change of kind invalidates; a change of content
/// does not (a content read of the same path records its digest instead).
pub fn stat_dep(path: &Path) -> String {
    format!("s:{}", crate::proof::stat_kind(path))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shared_file_has_every_owner() {
        let mut d = DistFiles::new();
        d.add("a", "/s", "pkg/__init__.py,,\npkg/t.txt,sha256=x,1\n", false);
        d.add("b", "/s", "pkg/__init__.py,,\npkg/t.txt,sha256=y,1\n", false);
        let (o, g) = d.lookup("/s/pkg/t.txt").unwrap();
        assert_eq!(o, vec!["a", "b"]);
        assert_eq!(g.as_deref(), Some("/s/pkg"));
        // the shared top directory itself has no sole owner
        assert!(d.lookup("/s/pkg/generated.bin").is_none());
        let c = d.claims();
        assert_eq!(c.len(), 1);
        assert!(c[0].1.contains("/s/pkg/t.txt a b\n"), "{}", c[0].1);
    }

    #[test]
    fn new_claimant_changes_the_group() {
        let mut one = DistFiles::new();
        one.add("a", "/s", "pkg/t.txt,,\n", false);
        one.add("b", "/s", "pkg/u.txt,,\n", false);
        let mut two = DistFiles::new();
        two.add("a", "/s", "pkg/t.txt,,\n", false);
        two.add("b", "/s", "pkg/u.txt,,\npkg/t.txt,,\n", false);
        assert_ne!(one.claims(), two.claims());
    }

    #[test]
    fn paths_outside_the_site_directory() {
        let mut d = DistFiles::new();
        d.add("mkl", "/p/lib/python3/site-packages", "../../../lib/libmkl.so,,\n../../../bin/mkl-tool,,\nmkl/__init__.py,,\n", false);
        let (o, g) = d.lookup("/p/lib/libmkl.so").unwrap();
        assert_eq!(o, vec!["mkl"]);
        assert_eq!(g.as_deref(), Some("/p/lib"));
        assert_eq!(d.lookup("/p/bin/mkl-tool").unwrap().1.as_deref(), Some("/p/bin"));
        // outside paths provide no top-level module and no top directory
        assert!(d.lookup("/p/lib/other.so").is_none());
        assert_eq!(d.tops(), vec![("mkl".to_string(), vec!["mkl".to_string()])]);
    }

    #[test]
    fn bytecode_and_sole_owner_directory() {
        let mut d = DistFiles::new();
        d.add("a", "/s", "pkg/m.py,,\n", false);
        assert_eq!(d.lookup("/s/pkg/__pycache__/m.cpython-313.pyc").unwrap().0, vec!["a"]);
        assert_eq!(d.lookup("/s/pkg/sub/x.dat").unwrap().0, vec!["a"]);
    }

    #[test]
    fn project_files() {
        let mut d = DistFiles::new();
        d.add("proj", "/s", "proj.pth,,\n", true);
        let (o, g) = d.lookup("/s/proj.pth").unwrap();
        assert_eq!(o, vec![PROJECT]);
        assert!(g.is_none());
        assert!(d.claims().is_empty());
    }

    #[test]
    fn stat_dependency() {
        let t = tempfile::tempdir().unwrap();
        assert_eq!(stat_dep(&t.path().join("x")), "s:missing");
        assert_eq!(stat_dep(t.path()), "s:dir");
        std::fs::write(t.path().join("x"), b"1").unwrap();
        assert_eq!(stat_dep(&t.path().join("x")), "s:file");
    }
}
