//! `--det`'s bytecode precompile checks (`detpy/reexec.py`), in Rust.
//!
//! The precompile writes checked-hash pycs (PEP 552, review R-015) through `detpy/_pycompile.py`, which walks every
//! directory it is given, reads and hashes each source and compiles those whose pyc does not hold that hash. On
//! home-assistant that is ~20,000 project files at every `--det` run. The walk and the test are here, on all CPUs:
//!
//! * `pyc_stale_hashed`: `_pycompile.sources`' walk (`os.walk`, sorted, `__pycache__` and the `-x` exclusions
//!   pruned, links to directories not entered) and `_pycompile.check`'s test (the cached pyc starts with
//!   `MAGIC, 3, source_hash(source)`); the driver then runs only for the stale files, not at all when none is;
//! * `source_hash`: `importlib.util.source_hash` (CPython's keyed SipHash);
//! * `dir_stamp`: `reexec.dir_stamp` (the top-level state of a library directory).
//!
//! Paths are built as `os.path.join` and `importlib.util.cache_from_source` (with `sys.pycache_prefix`) build
//! them. The exclusions are the names of `reexec._EXCLUDE_NAMES`: `[/\\](name)[/\\]` searched in the path, as the
//! regex does. The Python originals (`_pycompile.sources`/`check` driving every file, `reexec.dir_stamp`) are kept in
//! `tests/rust_hotpaths_ref/_ref_precompile_r2.py`.

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

/// SipHash-c-d of `data` under the key `(k0, k1)` (the reference algorithm; CPython's `siphash13` / `siphash24`
/// in `Python/pyhash.c`).
pub fn siphash(k0: u64, k1: u64, data: &[u8], c_rounds: u32, d_rounds: u32) -> u64 {
    let mut v0 = 0x736f6d6570736575u64 ^ k0;
    let mut v1 = 0x646f72616e646f6du64 ^ k1;
    let mut v2 = 0x6c7967656e657261u64 ^ k0;
    let mut v3 = 0x7465646279746573u64 ^ k1;
    #[inline(always)]
    fn round(v0: &mut u64, v1: &mut u64, v2: &mut u64, v3: &mut u64) {
        *v0 = v0.wrapping_add(*v1);
        *v1 = v1.rotate_left(13);
        *v1 ^= *v0;
        *v0 = v0.rotate_left(32);
        *v2 = v2.wrapping_add(*v3);
        *v3 = v3.rotate_left(16);
        *v3 ^= *v2;
        *v0 = v0.wrapping_add(*v3);
        *v3 = v3.rotate_left(21);
        *v3 ^= *v0;
        *v2 = v2.wrapping_add(*v1);
        *v1 = v1.rotate_left(17);
        *v1 ^= *v2;
        *v2 = v2.rotate_left(32);
    }
    let chunks = data.chunks_exact(8);
    let tail = chunks.remainder();
    for ch in chunks {
        let m = u64::from_le_bytes(ch.try_into().unwrap());
        v3 ^= m;
        for _ in 0..c_rounds {
            round(&mut v0, &mut v1, &mut v2, &mut v3);
        }
        v0 ^= m;
    }
    let mut last = (data.len() as u64 & 0xff) << 56;
    for (i, &b) in tail.iter().enumerate() {
        last |= (b as u64) << (8 * i);
    }
    v3 ^= last;
    for _ in 0..c_rounds {
        round(&mut v0, &mut v1, &mut v2, &mut v3);
    }
    v0 ^= last;
    v2 ^= 0xff;
    for _ in 0..d_rounds {
        round(&mut v0, &mut v1, &mut v2, &mut v3);
    }
    v0 ^ v1 ^ v2 ^ v3
}

/// `importlib.util.source_hash(data)` for the given variant: `_Py_KeyedHash(key, data)` is SipHash-1-3 (3.11+) or
/// SipHash-2-4 (3.9, 3.10) under `(key, 0)`, stored little-endian. The caller picks the variant by comparing with
/// `importlib.util.source_hash` itself.
#[pyfunction]
#[pyo3(signature = (data, key, c_rounds = 1, d_rounds = 3))]
pub fn source_hash(data: &[u8], key: u64, c_rounds: u32, d_rounds: u32) -> Vec<u8> {
    siphash(key, 0, data, c_rounds, d_rounds).to_le_bytes().to_vec()
}

struct Walk<'a> {
    exclude: &'a [Vec<u8>],
    out: Vec<Vec<u8>>,
}

impl Walk<'_> {
    /// `_pycompile.sources` for one top directory: `os.walk(top)` (links to directories listed, not entered), the
    /// subdirectories sorted, `__pycache__` and excluded ones (`exclude` searched in `join(root, s) + os.sep`)
    /// pruned, the `*.py` names of each directory sorted and kept unless their path is excluded.
    fn walk(&mut self, top: &[u8]) {
        let Ok(rd) = fs::read_dir(os(top)) else { return };
        let mut dirs = Vec::new();
        let mut files = Vec::new();
        for e in rd.flatten() {
            let name = e.file_name().into_vec();
            let full = join(top, &name);
            // os.scandir's DirEntry.is_dir(): follows a symbolic link; an error is False
            let is_dir = match e.file_type() {
                Ok(t) if t.is_symlink() => os(&full).is_dir(),
                Ok(t) => t.is_dir(),
                Err(_) => false,
            };
            if is_dir {
                dirs.push(name);
            } else {
                files.push(name);
            }
        }
        files.sort_by(|a, b| py_order(a, b));
        for f in files {
            if f.ends_with(b".py") {
                let p = join(top, &f);
                if !excluded(&p, self.exclude) {
                    self.out.push(p);
                }
            }
        }
        let mut keep: Vec<Vec<u8>> = dirs
            .into_iter()
            .filter(|s| {
                if s == b"__pycache__" {
                    return false;
                }
                let mut probe = join(top, s);
                probe.push(b'/');
                !excluded(&probe, self.exclude)
            })
            .collect();
        keep.sort_by(|a, b| py_order(a, b));
        for s in keep {
            let full = join(top, &s);
            // os.walk(followlinks=False): a link to a directory is not entered
            if !os(&full).is_symlink() {
                self.walk(&full);
            }
        }
    }
}

/// Code points of `os.fsdecode(name)` (UTF-8, an undecodable byte `b` as the lone surrogate `U+DC00 + b`).
fn code_points(b: &[u8]) -> Vec<u32> {
    let mut out = Vec::with_capacity(b.len());
    let mut rest = b;
    while !rest.is_empty() {
        match std::str::from_utf8(rest) {
            Ok(s) => {
                out.extend(s.chars().map(|c| c as u32));
                break;
            }
            Err(e) => {
                let (ok, bad) = rest.split_at(e.valid_up_to());
                out.extend(std::str::from_utf8(ok).unwrap().chars().map(|c| c as u32));
                let n = e.error_len().unwrap_or(bad.len());
                out.extend(bad[..n].iter().map(|&x| 0xDC00 + x as u32));
                rest = &bad[n..];
            }
        }
    }
    out
}

/// Python's `sorted()` order of the decoded names (code points; equal to byte order for valid UTF-8).
fn py_order(a: &[u8], b: &[u8]) -> std::cmp::Ordering {
    if std::str::from_utf8(a).is_ok() && std::str::from_utf8(b).is_ok() {
        a.cmp(b)
    } else {
        code_points(a).cmp(&code_points(b))
    }
}

/// `_pycompile.check`'s test: the source is readable and its cached pyc does not start with
/// `MAGIC + flags(3: checked hash) + source_hash(source)`.
fn stale_one(path: &[u8], cfile: &[u8], magic: &[u8], key: u64, c: u32, d: u32) -> bool {
    let Ok(src) = fs::read(os(path)) else { return false };
    let mut want = magic.to_vec();
    want.extend_from_slice(&3u32.to_le_bytes());
    want.extend_from_slice(&siphash(key, 0, &src, c, d).to_le_bytes());
    let mut actual = [0u8; 16];
    let n = fs::File::open(os(cfile))
        .and_then(|mut f| {
            let mut n = 0;
            while n < 16 {
                let k = f.read(&mut actual[n..])?;
                if k == 0 {
                    break;
                }
                n += k;
            }
            Ok(n)
        })
        .unwrap_or(0);
    actual[..n] != want[..]
}

/// The sources `_pycompile.py [-x EXCLUDE] <dirs>` would compile into `prefix` (in its order): the `*.py` files of
/// its walk whose cached `.pyc` is not a checked-hash pyc of their current content. `exclude_names` are the names of
/// `reexec._EXCLUDE` (empty: no `-x`); `cwd` absolutizes relative paths as `cache_from_source` does; `magic` is
/// `importlib.util.MAGIC_NUMBER`, `key` `_RAW_MAGIC_NUMBER`, `(c_rounds, d_rounds)` the SipHash variant of
/// `importlib.util.source_hash`. Sources are read and hashed on all CPUs, without the GIL.
#[pyfunction]
#[pyo3(signature = (dirs, prefix, cache_tag, magic, cwd, exclude_names, key, c_rounds = 1, d_rounds = 3))]
#[allow(clippy::too_many_arguments)]
pub fn pyc_stale_hashed(
    py: Python<'_>,
    dirs: Vec<OsString>,
    prefix: OsString,
    cache_tag: &str,
    magic: &[u8],
    cwd: OsString,
    exclude_names: Vec<String>,
    key: u64,
    c_rounds: u32,
    d_rounds: u32,
) -> Vec<OsString> {
    let names: Vec<Vec<u8>> = exclude_names.into_iter().map(|n| n.into_bytes()).collect();
    let (prefix, cwd, magic) = (prefix.into_vec(), cwd.into_vec(), magic.to_vec());
    let tag = cache_tag.as_bytes().to_vec();
    py.detach(|| {
        let mut w = Walk { exclude: &names, out: Vec::new() };
        for d in dirs {
            w.walk(&d.into_vec());
        }
        let files = w.out;
        let n = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1).min(16);
        let chunk = files.len().div_ceil(n.max(1)).max(256);
        let mut flags = vec![false; files.len()];
        std::thread::scope(|s| {
            for (fs_, out) in files.chunks(chunk).zip(flags.chunks_mut(chunk)) {
                let (prefix, cwd, tag, magic) = (&prefix, &cwd, &tag, &magic);
                s.spawn(move || {
                    for (f, o) in fs_.iter().zip(out.iter_mut()) {
                        let cfile = cache_path(f, cwd, prefix, tag);
                        *o = stale_one(f, &cfile, magic, key, c_rounds, d_rounds);
                    }
                });
            }
        });
        files.into_iter().zip(flags).filter(|(_, s)| *s).map(|(f, _)| OsString::from_vec(f)).collect()
    })
}

/// `reexec.dir_stamp`: sha256 (hex) of a library directory's entries, sorted by name: `name\0st_mtime_ns\0st_ino\n`
/// (`lstat`), and for a `*.dist-info` its `RECORD`'s `R<mtime_ns>\0<size>\0<ino>\n` (`stat`); `name\0?\n` for an
/// entry that cannot be stat-ed; `"missing"` when the directory cannot be listed.
#[pyfunction]
pub fn dir_stamp(py: Python<'_>, d: OsString) -> String {
    use sha2::{Digest, Sha256};
    let d = d.into_vec();
    py.detach(|| {
        let Ok(rd) = fs::read_dir(os(&d)) else { return "missing".to_string() };
        let mut names: Vec<Vec<u8>> = rd.flatten().map(|e| e.file_name().into_vec()).collect();
        names.sort_by(|a, b| py_order(a, b));
        let mut h = Sha256::new();
        for name in names {
            let full = join(&d, &name);
            let mut line = name.clone();
            let ok = (|| -> std::io::Result<Vec<u8>> {
                let st = fs::symlink_metadata(os(&full))?;
                let mut l = Vec::new();
                l.extend_from_slice(&name);
                l.extend_from_slice(format!("\0{}\0{}\n", mtime_ns(&st), st.ino()).as_bytes());
                if name.ends_with(b".dist-info") {
                    let r = fs::metadata(os(&join(&full, b"RECORD")))?;
                    l.extend_from_slice(format!("R{}\0{}\0{}\n", mtime_ns(&r), r.size(), r.ino()).as_bytes());
                }
                Ok(l)
            })();
            match ok {
                Ok(l) => h.update(&l),
                Err(_) => {
                    // the Python loop updates the entry line before it stats RECORD: a failing RECORD keeps it
                    if name.ends_with(b".dist-info") {
                        if let Ok(st) = fs::symlink_metadata(os(&full)) {
                            let mut l = name.clone();
                            l.extend_from_slice(format!("\0{}\0{}\n", mtime_ns(&st), st.ino()).as_bytes());
                            h.update(&l);
                        }
                    }
                    line.extend_from_slice(b"\0?\n");
                    h.update(&line);
                }
            }
        }
        h.finalize().iter().map(|b| format!("{b:02x}")).collect()
    })
}

fn mtime_ns(m: &fs::Metadata) -> i128 {
    m.mtime() as i128 * 1_000_000_000 + m.mtime_nsec() as i128
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
    m.add_function(wrap_pyfunction!(pyc_stale_hashed, m)?)?;
    m.add_function(wrap_pyfunction!(source_hash, m)?)?;
    m.add_function(wrap_pyfunction!(dir_stamp, m)?)?;
    m.add_function(wrap_pyfunction!(path_excluded, m)?)?;
    m.add_function(wrap_pyfunction!(pyc_cache_path, m)?)?;
    Ok(())
}
