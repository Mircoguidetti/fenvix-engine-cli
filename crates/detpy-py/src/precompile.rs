//! The project half of `--det`'s bytecode precompile (`detpy/reexec.py`), in Rust.
//!
//! Every `--det` run checked the whole project tree with `python -m compileall` (home-assistant: ~20,000 files,
//! ~2 s per run, MEASURED) and walked it again in Python to drop the bytecode of freshly modified sources
//! (`_drop_fresh_pycs`). Both walks are here, with the same rules, so compileall is started only for the files it
//! would compile:
//!
//! * `pyc_stale`: `compileall.compile_dir`'s walk (`_walk_dir`: sorted names, `__pycache__` skipped, directories
//!   followed unless they are symbolic links) and `compile_file`'s up-to-date test (a regular `*.py` file is
//!   current when its cached `.pyc` starts with `MAGIC, 0, int(st_mtime) & 0xFFFFFFFF`);
//! * `fresh_sources`: `os.walk(top)` (symbolic links to directories not followed) pruned like
//!   `_drop_fresh_pycs`, the `*.py` files whose `st_mtime` is not older than `limit`.
//!
//! Paths are built as `os.path.join` and `importlib.util.cache_from_source` (with `sys.pycache_prefix`) build
//! them. The exclusions are the names of `reexec._EXCLUDE_NAMES`: `[/\\](name)[/\\]` searched in the path, as the
//! regex does.

use pyo3::prelude::*;
use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::Read;
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::MetadataExt;

/// `os.path.join(a, b)` for a relative `b`.
fn join(a: &[u8], b: &[u8]) -> Vec<u8> {
    let mut out = a.to_vec();
    if !(out.is_empty() || out.ends_with(b"/")) {
        out.push(b'/');
    }
    out.extend_from_slice(b);
    out
}

fn os(b: &[u8]) -> &std::path::Path {
    std::path::Path::new(OsStr::from_bytes(b))
}

/// `st.st_mtime` as Python computes it (`sec + nsec * 1e-9` in double precision).
fn mtime_float(m: &fs::Metadata) -> f64 {
    m.mtime() as f64 + m.mtime_nsec() as f64 * 1e-9
}

/// `[/\\](a|b|...)[/\\]` searched in `path`.
fn excluded(path: &[u8], names: &[Vec<u8>]) -> bool {
    let sep = |c: u8| c == b'/' || c == b'\\';
    for (i, &c) in path.iter().enumerate() {
        if !sep(c) {
            continue;
        }
        let rest = &path[i + 1..];
        for n in names {
            if rest.len() > n.len() && rest.starts_with(n) && sep(rest[n.len()]) {
                return true;
            }
        }
    }
    false
}

/// `importlib.util.cache_from_source(path)` under `sys.pycache_prefix = prefix` (optimization level 0).
fn cache_path(path: &[u8], cwd: &[u8], prefix: &[u8], cache_tag: &[u8]) -> Vec<u8> {
    let (head, tail) = match path.iter().rposition(|&c| c == b'/') {
        Some(i) => (&path[..i], &path[i + 1..]),
        None => (&path[..0], path),
    };
    // base, sep, rest = tail.rpartition('.')
    let (base, sep, rest) = match tail.iter().rposition(|&c| c == b'.') {
        Some(i) => (&tail[..i], &b"."[..], &tail[i + 1..]),
        None => (&tail[..0], &b""[..], tail),
    };
    // ''.join([(base if base else rest), sep, tag])
    let mut filename = if base.is_empty() { rest.to_vec() } else { base.to_vec() };
    filename.extend_from_slice(sep);
    filename.extend_from_slice(cache_tag);
    filename.extend_from_slice(b".pyc");
    let mut head = head.to_vec();
    if !head.starts_with(b"/") {
        head = join(cwd, &head);
    }
    let head: Vec<u8> = head.iter().copied().skip_while(|&c| c == b'/').collect();
    // importlib's _path_join: the non-empty parts, right-stripped of separators, joined by '/'
    let parts: Vec<Vec<u8>> = [prefix.to_vec(), head, filename]
        .into_iter()
        .filter(|p| !p.is_empty())
        .map(|p| {
            let end = p.iter().rposition(|&c| c != b'/').map(|i| i + 1).unwrap_or(0);
            p[..end].to_vec()
        })
        .collect();
    parts.join(&b'/')
}

fn sorted_names(dir: &[u8]) -> Vec<Vec<u8>> {
    let Ok(rd) = fs::read_dir(os(dir)) else { return Vec::new() };
    let mut names: Vec<Vec<u8>> = rd.flatten().map(|e| e.file_name().into_vec()).collect();
    names.sort();
    names
}

struct Stale<'a> {
    cwd: &'a [u8],
    prefix: &'a [u8],
    tag: &'a [u8],
    magic: &'a [u8],
    out: Vec<OsString>,
}

impl Stale<'_> {
    /// `compileall._walk_dir` + `compile_file`'s test.
    fn walk(&mut self, dir: &[u8], maxlevels: i64) {
        for name in sorted_names(dir) {
            if name == b"__pycache__" {
                continue;
            }
            let full = join(dir, &name);
            let p = os(&full);
            if !p.is_dir() {
                self.file(&full, &name);
            } else if maxlevels > 0 && !p.is_symlink() {
                self.walk(&full, maxlevels - 1);
            }
        }
    }

    fn file(&mut self, full: &[u8], name: &[u8]) {
        if !name.ends_with(b".py") {
            return;
        }
        let Ok(m) = fs::metadata(os(full)) else { return };
        if !m.is_file() {
            return;
        }
        let mtime = mtime_float(&m).trunc() as i64;
        let mut expect = self.magic.to_vec();
        expect.extend_from_slice(&0u32.to_le_bytes());
        expect.extend_from_slice(&((mtime & 0xFFFF_FFFF) as u32).to_le_bytes());
        let cfile = cache_path(full, self.cwd, self.prefix, self.tag);
        let mut actual = [0u8; 12];
        let current = fs::File::open(os(&cfile))
            .and_then(|mut f| {
                let mut n = 0;
                while n < 12 {
                    let k = f.read(&mut actual[n..])?;
                    if k == 0 {
                        break;
                    }
                    n += k;
                }
                Ok(n)
            })
            .map(|n| actual[..n] == expect[..])
            .unwrap_or(false);
        if !current {
            self.out.push(OsString::from_vec(full.to_vec()));
        }
    }
}

/// The `*.py` files under `root` that `compileall -qq <root>` would compile (missing or out-of-date bytecode in
/// `prefix`), before its `-x` exclusions (the caller applies them). `cwd` absolutizes a relative `root` as
/// `cache_from_source` does; `magic` is `importlib.util.MAGIC_NUMBER`.
#[pyfunction]
#[pyo3(signature = (root, prefix, cache_tag, magic, cwd, maxlevels = 1000))]
pub fn pyc_stale(
    py: Python<'_>,
    root: OsString,
    prefix: OsString,
    cache_tag: &str,
    magic: &[u8],
    cwd: OsString,
    maxlevels: i64,
) -> Vec<OsString> {
    let (root, prefix, cwd, magic) = (root.into_vec(), prefix.into_vec(), cwd.into_vec(), magic.to_vec());
    py.detach(|| {
        let mut s = Stale { cwd: &cwd, prefix: &prefix, tag: cache_tag.as_bytes(), magic: &magic, out: Vec::new() };
        s.walk(&root, maxlevels);
        s.out
    })
}

fn fresh_walk(top: &[u8], names: &[Vec<u8>], limit: f64, out: &mut Vec<OsString>) {
    // os.walk(top): scandir; entries split by is_dir() (following links); prune; recurse unless a link
    let Ok(rd) = fs::read_dir(os(top)) else { return };
    let mut dirs = Vec::new();
    for e in rd.flatten() {
        let name = e.file_name().into_vec();
        let full = join(top, &name);
        let is_dir = match e.file_type() {
            Ok(t) if t.is_symlink() => os(&full).is_dir(),
            Ok(t) => t.is_dir(),
            Err(_) => false,
        };
        if is_dir {
            dirs.push((name, full));
        } else if name.ends_with(b".py") {
            if let Ok(m) = fs::metadata(os(&full)) {
                if mtime_float(&m) >= limit {
                    out.push(OsString::from_vec(full));
                }
            }
        }
    }
    for (_, full) in dirs {
        let mut probe = full.clone();
        probe.push(b'/');
        if excluded(&probe, names) || os(&full).is_symlink() {
            continue;
        }
        fresh_walk(&full, names, limit, out);
    }
}

/// `*.py` files under `root` (walked as `_drop_fresh_pycs` walks it) whose `st_mtime` is not older than `limit`.
#[pyfunction]
pub fn fresh_sources(py: Python<'_>, root: OsString, exclude_names: Vec<String>, limit: f64) -> Vec<OsString> {
    let names: Vec<Vec<u8>> = exclude_names.into_iter().map(|n| n.into_bytes()).collect();
    let root = root.into_vec();
    py.detach(|| {
        let mut out = Vec::new();
        fresh_walk(&root, &names, limit, &mut out);
        out
    })
}

/// `[/\\](names)[/\\]` searched in `path` (the regex `reexec._EXCLUDE`; exposed for the tests).
#[pyfunction]
pub fn path_excluded(path: OsString, exclude_names: Vec<String>) -> bool {
    let names: Vec<Vec<u8>> = exclude_names.into_iter().map(|n| n.into_bytes()).collect();
    excluded(&path.into_vec(), &names)
}

/// `cache_from_source` as `pyc_stale` computes it (exposed for the tests).
#[pyfunction]
pub fn pyc_cache_path(path: OsString, cwd: OsString, prefix: OsString, cache_tag: &str) -> OsString {
    OsString::from_vec(cache_path(&path.into_vec(), &cwd.into_vec(), &prefix.into_vec(), cache_tag.as_bytes()))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(pyc_stale, m)?)?;
    m.add_function(wrap_pyfunction!(fresh_sources, m)?)?;
    m.add_function(wrap_pyfunction!(path_excluded, m)?)?;
    m.add_function(wrap_pyfunction!(pyc_cache_path, m)?)?;
    Ok(())
}
