//! Runtime identity of the cache with proof (`detpy.proofcache`): the installed distributions and their memo
//! (`distributions.json`), the interpreter / platform identity, the time zone and locale identity, the cache's
//! epoch (`epoch.json`) and the startup environment snapshot (`env0`).
//!
//! Python keeps what is interface: `importlib.metadata.distributions()` (its finders are Python's rules) and
//! `importlib.metadata`'s own reading of a distribution Rust cannot read (not a plain `PathDistribution`, or
//! `dist_identity` declined it), plus the interpreter state passed in (`sys.version`, `sysconfig`, `platform`).
//! The Python original is kept verbatim in `tests/rust_hotpaths_ref/_ref_identity.py`.
//!
//! Strings Python may hold with lone surrogates (paths decoded with `surrogateescape`) are kept as their UTF-8
//! `surrogatepass` bytes ([`W`], as in `capture.rs`); `json.dumps` of them is reproduced byte for byte
//! (`ensure_ascii`, default separators). JSON files are parsed with `serde_json` where its reading is certain to
//! match `json.loads` (ASCII text it accepts); anything else goes through Python's `json` itself.
//!
//! One deliberate difference: a memo entry (in `distributions.json`) of a form detpy never writes (not
//! `["dist", str]` / `["project", str | null]`, or a memo that is not an object) counts as absent and is computed
//! again; the original indexed it blindly (a wrong identity part, or an exception).

use crate::capture::normpath;
use crate::fsorder::{from_wtf8, wtf8};
use crate::proofcache::{dist_identity, json_escape};
use detpy_core::fingerprint::digest_bytes;
use detpy_core::proof;
use pyo3::exceptions::{PyAttributeError, PyException};
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyBytes, PyDict, PyInt, PyList, PySlice, PyString, PyTuple};
use pyo3::{intern, IntoPyObjectExt};
use std::collections::HashMap;
use std::ffi::OsStr;
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

/// A Python `str` as its UTF-8 `surrogatepass` bytes.
type W = Vec<u8>;

const LOCALE_VARS: [&str; 17] = [
    "TZ", "TZDIR", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE", "LC_MONETARY",
    "LC_MESSAGES", "LC_PAPER", "LC_NAME", "LC_ADDRESS", "LC_TELEPHONE", "LC_MEASUREMENT", "LC_IDENTIFICATION",
];
const META_FILES: [&str; 4] = ["METADATA", "PKG-INFO", "RECORD", "direct_url.json"];

// ---------------------------------------------------------------------------------------------------------------
// strings, paths and JSON text

fn os_mod(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    static OS: PyOnceLock<Py<PyModule>> = PyOnceLock::new();
    Ok(OS.get_or_try_init(py, || py.import("os").map(|m| m.unbind()))?.bind(py).clone())
}

fn json_mod(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    static JSON: PyOnceLock<Py<PyModule>> = PyOnceLock::new();
    Ok(JSON.get_or_try_init(py, || py.import("json").map(|m| m.unbind()))?.bind(py).clone())
}

/// The file system encoding is UTF-8 with `surrogateescape` (`os.fsdecode` is then [`fsdecode_utf8`]).
fn fs_utf8(py: Python<'_>) -> PyResult<bool> {
    static FS: PyOnceLock<bool> = PyOnceLock::new();
    FS.get_or_try_init(py, || -> PyResult<bool> {
        let sys = py.import("sys")?;
        let enc: String = sys.call_method0("getfilesystemencoding")?.extract()?;
        let err: String = sys.call_method0("getfilesystemencodeerrors")?.extract()?;
        Ok(enc.eq_ignore_ascii_case("utf-8") && err == "surrogateescape")
    })
    .copied()
}

/// The UTF-8 `surrogatepass` bytes of the lone surrogate `cp`.
fn push_surrogate(out: &mut W, cp: u32) {
    out.push(0xE0 | (cp >> 12) as u8);
    out.push(0x80 | ((cp >> 6) & 0x3F) as u8);
    out.push(0x80 | (cp & 0x3F) as u8);
}

/// `bytes.decode("utf-8", "surrogateescape")` as [`W`]: every byte outside a valid sequence becomes U+DC00 + byte
/// (Python's decoder and Rust's agree on which bytes those are: both stop at the maximal valid subpart).
fn fsdecode_utf8(b: &[u8]) -> W {
    let mut out = Vec::with_capacity(b.len());
    let mut rest = b;
    loop {
        match std::str::from_utf8(rest) {
            Ok(s) => {
                out.extend_from_slice(s.as_bytes());
                return out;
            }
            Err(e) => {
                let v = e.valid_up_to();
                out.extend_from_slice(&rest[..v]);
                let n = e.error_len().unwrap_or(rest.len() - v);
                for &x in &rest[v..v + n] {
                    push_surrogate(&mut out, 0xDC00 + x as u32);
                }
                rest = &rest[v + n..];
            }
        }
    }
}

/// `os.fsdecode(b)` as [`W`].
fn fsdecode(py: Python<'_>, b: &[u8]) -> PyResult<W> {
    if fs_utf8(py)? {
        return Ok(fsdecode_utf8(b));
    }
    let s = os_mod(py)?.call_method1(intern!(py, "fsdecode"), (PyBytes::new(py, b),))?;
    Ok(wtf8(s.cast::<PyString>()?)?.into_owned())
}

/// `os.fsdecode(b)` as a Python `str`.
fn fsdecode_py<'py>(py: Python<'py>, b: &[u8]) -> PyResult<Bound<'py, PyAny>> {
    if fs_utf8(py)? {
        if let Ok(s) = std::str::from_utf8(b) {
            return Ok(PyString::new(py, s).into_any());
        }
    }
    os_mod(py)?.call_method1(intern!(py, "fsdecode"), (PyBytes::new(py, b),))
}

/// `os.fsencode` of the `str` `w` (None when Python could not encode it).
fn fsencode(py: Python<'_>, w: &[u8]) -> PyResult<Option<PathBuf>> {
    if std::str::from_utf8(w).is_ok() && fs_utf8(py)? {
        return Ok(Some(PathBuf::from(OsStr::from_bytes(w))));
    }
    Ok(from_wtf8(py, w)?.extract::<PathBuf>().ok())
}

/// Code points of a [`W`] (generalized UTF-8: lone surrogates included).
fn code_points(w: &[u8]) -> impl Iterator<Item = u32> + '_ {
    let mut i = 0;
    std::iter::from_fn(move || {
        let b = *w.get(i)? as u32;
        let (n, init) = match b {
            0..=0x7F => (1, b),
            0xC0..=0xDF => (2, b & 0x1F),
            0xE0..=0xEF => (3, b & 0x0F),
            _ => (4, b & 0x07),
        };
        let mut cp = init;
        for k in 1..n {
            cp = (cp << 6) | (*w.get(i + k).unwrap_or(&0x80) as u32 & 0x3F);
        }
        i += n;
        Some(cp)
    })
}

/// `json.dumps(s)` of the `str` `w`, appended to `out`.
fn json_w(w: &[u8], out: &mut String) {
    if let Ok(s) = std::str::from_utf8(w) {
        return json_escape(s, out);
    }
    out.push('"');
    for cp in code_points(w) {
        match char::from_u32(cp) {
            Some(c) if (0x20..0x7F).contains(&cp) || matches!(c, '\n' | '\r' | '\t' | '\u{8}' | '\u{c}') => {
                // ASCII (quote and backslash included) and the short escapes: as json_escape writes them
                let mut b = [0u8; 4];
                let s = c.encode_utf8(&mut b);
                let mut t = String::new();
                json_escape(s, &mut t);
                out.push_str(&t[1..t.len() - 1]);
            }
            Some(c) => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{u:04x}"));
                }
            }
            None => out.push_str(&format!("\\u{cp:04x}")),
        }
    }
    out.push('"');
}

/// `json.dumps(o)` of a Python object (a `str` or None in practice; anything else through `json` itself).
fn json_py(py: Python<'_>, o: &Bound<'_, PyAny>, out: &mut String) -> PyResult<()> {
    if o.is_none() {
        out.push_str("null");
    } else if let Ok(s) = o.cast::<PyString>() {
        json_w(&wtf8(s)?, out);
    } else {
        let d = json_mod(py)?.call_method1(intern!(py, "dumps"), (o,))?;
        out.push_str(&d.cast::<PyString>()?.to_cow()?);
    }
    Ok(())
}

/// `os.path.join(a, b)` (posix) of two [`W`].
fn join(a: &[u8], b: &[u8]) -> W {
    if b.starts_with(b"/") || a.is_empty() {
        return b.to_vec();
    }
    let mut p = a.to_vec();
    if !a.ends_with(b"/") {
        p.push(b'/');
    }
    p.extend_from_slice(b);
    p
}

/// `posixpath.dirname`.
fn dirname(p: &[u8]) -> &[u8] {
    let i = p.iter().rposition(|&c| c == b'/').map(|i| i + 1).unwrap_or(0);
    let head = &p[..i];
    if !head.is_empty() && head.iter().any(|&c| c != b'/') {
        let end = head.iter().rposition(|&c| c != b'/').map(|e| e + 1).unwrap_or(0);
        &head[..end]
    } else {
        head
    }
}

/// `os.path.realpath(s)` as [`W`]: `realpath(3)` for a path that resolves, else Python's (which also resolves
/// what does not exist, lexically).
fn realpath(py: Python<'_>, s: &Bound<'_, PyAny>) -> PyResult<W> {
    if let Ok(st) = s.cast::<PyString>() {
        if let Ok(p) = st.extract::<PathBuf>() {
            if let Ok(r) = std::fs::canonicalize(&p) {
                return fsdecode(py, r.as_os_str().as_bytes());
            }
        }
    }
    let r = os_mod(py)?.getattr(intern!(py, "path"))?.call_method1(intern!(py, "realpath"), (s,))?;
    Ok(wtf8(r.cast::<PyString>()?)?.into_owned())
}

/// [`realpath`] of a distribution's path, `<parent>/<name>` (the dist-info dirs of one `sys.path` entry share the
/// parent): `realpath(parent)/name` when `name` is no symlink (realpath resolves component by component, so that
/// is its result), the parent resolved once per call (`parents`); anything else as [`realpath`].
fn realpath_dist(py: Python<'_>, s: &Bound<'_, PyString>, parents: &mut HashMap<Vec<u8>, Option<Vec<u8>>>) -> PyResult<W> {
    if let Ok(p) = s.extract::<PathBuf>() {
        let b = p.as_os_str().as_bytes();
        if let Some(i) = b.iter().rposition(|&c| c == b'/') {
            let (parent, name) = (&b[..i.max(1)], &b[i + 1..]);
            if !name.is_empty() && name != b"." && name != b".." {
                let rp = parents
                    .entry(parent.to_vec())
                    .or_insert_with(|| std::fs::canonicalize(OsStr::from_bytes(parent)).ok().map(|r| r.into_os_string().into_vec()));
                if let Some(rp) = rp {
                    let full = join(rp, name);
                    if std::fs::symlink_metadata(OsStr::from_bytes(&full)).is_ok_and(|m| !m.file_type().is_symlink()) {
                        return fsdecode(py, &full);
                    }
                }
            }
        }
    }
    realpath(py, s.as_any())
}

/// `os.stat(path)` as `[st_size, st_mtime_ns, st_ctime_ns, st_ino]` JSON, `null` when it fails.
fn stat_key_json(path: &Path, out: &mut String) {
    match std::fs::metadata(path) {
        Ok(m) => out.push_str(&format!(
            "[{}, {}, {}, {}]",
            m.size(),
            m.mtime() as i128 * 1_000_000_000 + m.mtime_nsec() as i128,
            m.ctime() as i128 * 1_000_000_000 + m.ctime_nsec() as i128,
            m.ino()
        )),
        Err(_) => out.push_str("null"),
    }
}

/// `pathlib.Path.read_text(encoding="utf-8")` (universal newlines): None when unreadable or not UTF-8.
fn read_text(path: &Path) -> Option<String> {
    let s = String::from_utf8(std::fs::read(path).ok()?).ok()?;
    Some(if s.contains('\r') { s.replace("\r\n", "\n").replace('\r', "\n") } else { s })
}

/// Text of a file `open(path)` (locale encoding) would give, for ASCII content (the same in every locale
/// encoding Python accepts here); `Err(())` for other content (read through Python), `Ok(None)` when unreadable.
fn read_ascii(path: &Path) -> Result<Option<String>, ()> {
    match std::fs::read(path) {
        Err(_) => Ok(None),
        Ok(b) if b.is_ascii() => {
            let s = String::from_utf8(b).map_err(|_| ())?;
            Ok(Some(if s.contains('\r') { s.replace("\r\n", "\n").replace('\r', "\n") } else { s }))
        }
        Ok(_) => Err(()),
    }
}

/// `with open(path) as fh: return json.load(fh)` through Python; `Ok(None)` when it raises one of `catch`.
fn py_json_load<'py>(py: Python<'py>, path: &Path, catch: &dyn Fn(&PyErr) -> bool) -> PyResult<Option<Bound<'py, PyAny>>> {
    let r = (|| -> PyResult<Bound<'py, PyAny>> {
        let fh = py.import("builtins")?.call_method1(intern!(py, "open"), (path,))?;
        let r = json_mod(py)?.call_method1(intern!(py, "load"), (&fh,));
        fh.call_method0(intern!(py, "close"))?;
        r
    })();
    match r {
        Ok(v) => Ok(Some(v)),
        Err(e) if catch(&e) => Ok(None),
        Err(e) => Err(e),
    }
}

fn is_os_or_value_error(py: Python<'_>, e: &PyErr) -> bool {
    e.is_instance_of::<pyo3::exceptions::PyOSError>(py) || e.is_instance_of::<pyo3::exceptions::PyValueError>(py)
}

/// `getattr(o, name, None)`.
fn getattr_or_none<'py>(o: &Bound<'py, PyAny>, name: &Bound<'py, PyString>) -> PyResult<Option<Bound<'py, PyAny>>> {
    match o.getattr(name) {
        Ok(v) if v.is_none() => Ok(None),
        Ok(v) => Ok(Some(v)),
        Err(e) if e.is_instance_of::<PyAttributeError>(o.py()) => Ok(None),
        Err(e) => Err(e),
    }
}

/// The tmp file + `os.replace` write of the original (errors ignored).
fn write_replace(path: &Path, text: &str) {
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(format!(".{}.tmp", std::process::id()));
    if std::fs::write(&tmp, text).is_ok() {
        let _ = std::fs::rename(&tmp, path);
    }
}

// ---------------------------------------------------------------------------------------------------------------
// installed distributions

/// A memo entry (`hit` of the original).
#[derive(Clone, PartialEq)]
enum Hit {
    Dist(W),
    Project(Option<W>),
}

impl Hit {
    fn json(&self, out: &mut String) {
        match self {
            Hit::Dist(s) => {
                out.push_str("[\"dist\", ");
                json_w(s, out);
            }
            Hit::Project(p) => {
                out.push_str("[\"project\", ");
                match p {
                    Some(s) => json_w(s, out),
                    None => out.push_str("null"),
                }
            }
        }
        out.push(']');
    }

    fn of_json(v: &serde_json::Value) -> Option<Hit> {
        let a = v.as_array().filter(|a| a.len() == 2)?;
        match (a[0].as_str()?, &a[1]) {
            ("dist", serde_json::Value::String(s)) => Some(Hit::Dist(s.as_bytes().to_vec())),
            ("project", serde_json::Value::String(s)) => Some(Hit::Project(Some(s.as_bytes().to_vec()))),
            ("project", serde_json::Value::Null) => Some(Hit::Project(None)),
            _ => None,
        }
    }

    fn of_py(v: &Bound<'_, PyAny>) -> PyResult<Option<Hit>> {
        let Ok(l) = v.cast::<PyList>() else { return Ok(None) };
        if l.len() != 2 {
            return Ok(None);
        }
        let (a, b) = (l.get_item(0)?, l.get_item(1)?);
        let Ok(a) = a.cast::<PyString>() else { return Ok(None) };
        let tag = wtf8(a)?;
        let s = match b.cast::<PyString>() {
            Ok(s) => Some(wtf8(s)?.into_owned()),
            Err(_) if b.is_none() => None,
            Err(_) => return Ok(None),
        };
        Ok(match (&tag[..], s) {
            (b"dist", Some(s)) => Some(Hit::Dist(s)),
            (b"project", s) => Some(Hit::Project(s)),
            _ => None,
        })
    }
}

/// The memo as loaded: key -> entry (None for a form detpy never writes); `odd` when it was not an object.
#[derive(Default)]
struct Memo {
    map: HashMap<W, Option<Hit>>,
    odd: bool,
}

fn load_memo(py: Python<'_>, path: &Path) -> PyResult<Memo> {
    let mut m = Memo::default();
    match read_ascii(path) {
        Ok(None) => return Ok(m),
        Ok(Some(text)) => {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
                match v {
                    serde_json::Value::Object(o) => {
                        for (k, v) in o {
                            m.map.insert(k.into_bytes(), Hit::of_json(&v));
                        }
                    }
                    _ => m.odd = true,
                }
                return Ok(m);
            }
        }
        Err(()) => {}
    }
    // not ASCII, or JSON serde_json does not take (lone surrogates of undecodable paths, NaN, ...): Python's json
    let Some(v) = py_json_load(py, path, &|e| is_os_or_value_error(py, e))? else { return Ok(m) };
    match v.cast::<PyDict>() {
        Ok(d) => {
            for (k, v) in d.iter() {
                let Ok(k) = k.cast::<PyString>() else { continue };
                m.map.insert(wtf8(k)?.into_owned(), Hit::of_py(&v)?);
            }
        }
        Err(_) => m.odd = true,
    }
    Ok(m)
}

/// The text of `direct_url.json` as read: in Rust for a `PathDistribution` (`read_text` of the file under its
/// path), through the distribution's own `read_text` otherwise.
enum DirectUrl<'py> {
    Text(Option<String>),
    Dist(&'py Bound<'py, PyAny>),
}

/// `url.startswith("file://") and (os.path.realpath(url[7:]) + os.sep).startswith(root_sep)` on the parsed
/// `direct_url.json` (any exception: False).
fn project_of_info(py: Python<'_>, info: &Bound<'_, PyAny>, root_sep: &Bound<'_, PyString>) -> PyResult<bool> {
    let url = info.call_method1(intern!(py, "get"), ("url", ""))?;
    if !url.call_method1(intern!(py, "startswith"), ("file://",))?.is_truthy()? {
        return Ok(false);
    }
    let rest = url.get_item(PySlice::new(py, 7, isize::MAX, 1))?;
    let rp = os_mod(py)?.getattr(intern!(py, "path"))?.call_method1(intern!(py, "realpath"), (rest,))?;
    rp.add(os_mod(py)?.getattr(intern!(py, "sep"))?)?
        .call_method1(intern!(py, "startswith"), (root_sep,))?
        .is_truthy()
}

/// The original's `try: du = d.read_text("direct_url.json") ... except Exception: pass` as a bool.
fn is_project(py: Python<'_>, du: DirectUrl<'_>, root_sep: &Bound<'_, PyString>, root_sep_w: &[u8]) -> PyResult<bool> {
    let r = (|| -> PyResult<bool> {
        let info = match du {
            DirectUrl::Text(None) => return Ok(false),
            DirectUrl::Text(Some(t)) => {
                if t.is_empty() {
                    return Ok(false);
                }
                match serde_json::from_str::<serde_json::Value>(&t) {
                    Ok(serde_json::Value::Object(o)) => {
                        return match o.get("url") {
                            Some(serde_json::Value::String(u)) if u.starts_with("file://") => {
                                let rp = os_mod(py)?
                                    .getattr(intern!(py, "path"))?
                                    .call_method1(intern!(py, "realpath"), (&u[7..],))?;
                                let mut w = wtf8(rp.cast::<PyString>()?)?.into_owned();
                                w.push(b'/');
                                Ok(w.starts_with(root_sep_w))
                            }
                            _ => Ok(false), // missing (""), or no startswith (AttributeError)
                        };
                    }
                    Ok(_) => return Ok(false), // no .get (AttributeError)
                    Err(_) => json_mod(py)?.call_method1(intern!(py, "loads"), (t,))?,
                }
            }
            DirectUrl::Dist(d) => {
                let t = d.call_method1(intern!(py, "read_text"), ("direct_url.json",))?;
                if !t.is_truthy()? {
                    return Ok(false);
                }
                json_mod(py)?.call_method1(intern!(py, "loads"), (t,))?
            }
        };
        project_of_info(py, &info, root_sep)
    })();
    match r {
        Ok(b) => Ok(b),
        Err(e) if e.is_instance_of::<PyException>(py) => Ok(false),
        Err(e) => Err(e),
    }
}

/// `name.lower()`: ASCII here, anything else by Python's `str.lower` (its Unicode tables).
fn lower(py: Python<'_>, s: &str) -> PyResult<W> {
    if s.is_ascii() {
        return Ok(s.to_ascii_lowercase().into_bytes());
    }
    let l = PyString::new(py, s).call_method0(intern!(py, "lower"))?;
    Ok(wtf8(l.cast::<PyString>()?)?.into_owned())
}

/// `_dist_infos(root, memo_path)` of the original: (sorted identity parts, editable project dist-info dirs).
#[allow(clippy::too_many_arguments)]
fn dist_infos_w(
    py: Python<'_>,
    root: &Bound<'_, PyAny>,
    memo_path: Option<&Bound<'_, PyAny>>,
    dists: &Bound<'_, PyAny>,
    path_dist: &Bound<'_, PyAny>,
    name_of: &Bound<'_, PyAny>,
    part_of: &Bound<'_, PyAny>,
) -> PyResult<(Vec<W>, Vec<W>)> {
    let memo_path: Option<PathBuf> = match memo_path {
        Some(p) if p.is_truthy()? => Some(p.extract()?),
        _ => None,
    };
    let memo = match &memo_path {
        Some(p) => load_memo(py, p)?,
        None => Memo::default(),
    };
    let mut root_sep_w = realpath(py, root)?;
    root_sep_w.push(b'/');
    let root_sep = from_wtf8(py, &root_sep_w)?;
    let mut root_sep_json = String::new();
    json_w(&root_sep_w, &mut root_sep_json);

    let mut fresh: Vec<(W, Hit)> = Vec::new();
    let mut fresh_at: HashMap<W, usize> = HashMap::new();
    let (mut parts, mut editable) = (Vec::new(), Vec::new());
    let path_attr = intern!(py, "_path");
    let mut parents: HashMap<Vec<u8>, Option<Vec<u8>>> = HashMap::new();
    for d in dists.try_iter()? {
        let d = d?;
        let path = getattr_or_none(&d, path_attr)?;
        // key: json.dumps([base, root_sep, *stat keys of the metadata files])
        let mut base: Option<W> = None;
        let mut key: Option<W> = None;
        if let Some(p) = &path {
            let b = realpath_dist(py, &p.str()?, &mut parents)?;
            let mut k = String::from("[");
            json_w(&b, &mut k);
            k.push_str(", ");
            k.push_str(&root_sep_json);
            match fsencode(py, &b)? {
                Some(bp) => {
                    for f in META_FILES {
                        k.push_str(", ");
                        stat_key_json(&bp.join(f), &mut k);
                    }
                }
                None => k.push_str(", null, null, null, null"),
            }
            k.push(']');
            base = Some(b);
            key = Some(k.into_bytes());
        }
        let memo_hit = key.as_ref().and_then(|k| memo.map.get(k)).and_then(|h| h.clone());
        let hit = match memo_hit {
            Some(h) => h,
            None => {
                let fast_path = match &path {
                    Some(p) if d.get_type().is(path_dist) => Some(p.extract::<PathBuf>()?),
                    _ => None,
                };
                let fast = match &fast_path {
                    Some(p) => dist_identity(py, p.clone()),
                    None => None,
                };
                // importlib's name first (an exception there propagates before anything else is read)
                let name = match &fast {
                    Some(_) => None,
                    None => Some(name_of.call1((&d,))?),
                };
                let du = match &fast_path {
                    Some(p) => DirectUrl::Text(read_text(&p.join("direct_url.json"))),
                    None => DirectUrl::Dist(&d),
                };
                if is_project(py, du, &root_sep, &root_sep_w)? {
                    Hit::Project(base.as_ref().map(|b| {
                        let mut s = b.clone();
                        s.push(b'/');
                        s
                    }))
                } else if let Some((n, version, rec)) = &fast {
                    let mut s = lower(py, n)?;
                    s.extend_from_slice(format!("=={version}:{rec}").as_bytes());
                    Hit::Dist(s)
                } else {
                    let p = part_of.call1((&d, name.unwrap()))?;
                    Hit::Dist(wtf8(p.cast::<PyString>()?)?.into_owned())
                }
            }
        };
        if let Some(k) = key {
            match fresh_at.get(&k) {
                Some(&i) => fresh[i].1 = hit.clone(),
                None => {
                    fresh_at.insert(k.clone(), fresh.len());
                    fresh.push((k, hit.clone()));
                }
            }
        }
        match hit {
            Hit::Project(Some(p)) => editable.push(p),
            Hit::Project(None) => {}
            Hit::Dist(s) => parts.push(s),
        }
    }
    // fresh != memo
    let changed = memo.odd
        || fresh.len() != memo.map.len()
        || fresh.iter().any(|(k, h)| memo.map.get(k).and_then(|m| m.as_ref()) != Some(h));
    if let (Some(p), true) = (&memo_path, changed) {
        let mut out = String::from("{");
        for (i, (k, h)) in fresh.iter().enumerate() {
            if i > 0 {
                out.push_str(", ");
            }
            json_w(k, &mut out);
            out.push_str(": ");
            h.json(&mut out);
        }
        out.push('}');
        write_replace(p, &out);
    }
    parts.sort();
    // a distribution found through several sys.path entries naming the same directory (pytest-xdist's workers put
    // the rootdir on sys.path once more than their controller) is one installed distribution
    parts.dedup();
    editable.sort();
    editable.dedup();
    Ok((parts, editable))
}

fn str_list<'py>(py: Python<'py>, v: &[W]) -> PyResult<Bound<'py, PyList>> {
    let l = PyList::empty(py);
    for s in v {
        l.append(from_wtf8(py, s)?)?;
    }
    Ok(l)
}

/// `_dist_infos(root, memo_path)`: `(sorted(parts), editable)`. `dists` is `importlib.metadata.distributions()`,
/// `path_dist` its `PathDistribution`; `name_of(d)` and `part_of(d, name)` are importlib's reading of a
/// distribution Rust does not read.
#[pyfunction]
#[pyo3(signature = (root, memo_path, dists, path_dist, name_of, part_of))]
fn dist_infos<'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    memo_path: Option<&Bound<'py, PyAny>>,
    dists: &Bound<'py, PyAny>,
    path_dist: &Bound<'py, PyAny>,
    name_of: &Bound<'py, PyAny>,
    part_of: &Bound<'py, PyAny>,
) -> PyResult<(Bound<'py, PyList>, Bound<'py, PyList>)> {
    let (parts, editable) = dist_infos_w(py, root, memo_path, dists, path_dist, name_of, part_of)?;
    Ok((str_list(py, &parts)?, str_list(py, &editable)?))
}

// ---------------------------------------------------------------------------------------------------------------
// runtime identity

/// `runtime_identity(root, memo_path)`: `(digest, dict, editable)`. `discovery` is `(dists, path_dist, name_of,
/// part_of)` as for [`dist_infos`]; `state` is `(sys.version, sys.implementation.cache_tag, sys.executable,
/// LIBDIR, LDLIBRARY, platform.system(), platform.machine(), platform.libc_ver(), os.__file__)`.
#[pyfunction]
fn runtime_identity<'py>(
    py: Python<'py>,
    root: &Bound<'py, PyAny>,
    memo_path: Option<&Bound<'py, PyAny>>,
    discovery: (Bound<'py, PyAny>, Bound<'py, PyAny>, Bound<'py, PyAny>, Bound<'py, PyAny>),
    state: &Bound<'py, PyTuple>,
) -> PyResult<(String, Bound<'py, PyDict>, Bound<'py, PyList>)> {
    let [version, cache_tag, executable, libdir, ldlib, system, machine, libc_ver, os_file]: [Bound<'py, PyAny>; 9] =
        state.extract()?;
    let exe = realpath(py, &executable)?;
    let mut lib: Option<W> = None;
    if libdir.is_truthy()? && ldlib.is_truthy()? {
        let l = join(&wtf8(libdir.cast::<PyString>()?)?, &wtf8(ldlib.cast::<PyString>()?)?);
        if fsencode(py, &l)?.is_some_and(|p| std::fs::metadata(p).is_ok()) {
            lib = Some(l);
        }
    }
    let (d0, d1, d2, d3) = &discovery;
    let (dists, editable) = dist_infos_w(py, root, memo_path, d0, d1, d2, d3)?;
    let digest_of = |w: &W| -> PyResult<Option<String>> { Ok(fsencode(py, w)?.and_then(|p| proof::file_digest(&p))) };
    let executable_digest = digest_of(&exe)?;
    let libpython = match &lib {
        Some(l) => digest_of(l)?,
        None => None,
    };
    let libc = PyString::new(py, "-").call_method1(intern!(py, "join"), (libc_ver,))?;
    let stdlib_dir = dirname(&wtf8(os_file.cast::<PyString>()?)?).to_vec();
    let stdlib = fsencode(py, &stdlib_dir)?.and_then(|p| proof::listing_digest(&p));
    let joined = dists.join(&b'\n');
    let distributions = match std::str::from_utf8(&joined) {
        Ok(s) => digest_bytes(s.as_bytes()).short(),
        // "\n".join(dists).encode(): raises on a lone surrogate as the original did
        Err(_) => {
            from_wtf8(py, &joined)?.call_method0(intern!(py, "encode"))?;
            unreachable!("encode of a str with surrogates succeeded")
        }
    };
    let n = dists.len();
    let opt = |s: &Option<String>| -> Bound<'py, PyAny> {
        match s {
            Some(s) => PyString::new(py, s).into_any(),
            None => py.None().into_bound(py),
        }
    };
    let d = PyDict::new(py);
    d.set_item("python", &version)?;
    d.set_item("cache_tag", &cache_tag)?;
    d.set_item("executable", opt(&executable_digest))?;
    d.set_item("libpython", opt(&libpython))?;
    d.set_item("system", &system)?;
    d.set_item("machine", &machine)?;
    d.set_item("libc", &libc)?;
    d.set_item("stdlib", opt(&stdlib))?;
    d.set_item("distributions", &distributions)?;
    d.set_item("n_distributions", n)?;
    // json.dumps(d, sort_keys=True)
    let mut j = String::from("{\"cache_tag\": ");
    json_py(py, &cache_tag, &mut j)?;
    j.push_str(", \"distributions\": ");
    json_escape(&distributions, &mut j);
    j.push_str(", \"executable\": ");
    json_py(py, &opt(&executable_digest), &mut j)?;
    j.push_str(", \"libc\": ");
    json_py(py, &libc, &mut j)?;
    j.push_str(", \"libpython\": ");
    json_py(py, &opt(&libpython), &mut j)?;
    j.push_str(", \"machine\": ");
    json_py(py, &machine, &mut j)?;
    j.push_str(&format!(", \"n_distributions\": {n}, \"python\": "));
    json_py(py, &version, &mut j)?;
    j.push_str(", \"stdlib\": ");
    json_py(py, &opt(&stdlib), &mut j)?;
    j.push_str(", \"system\": ");
    json_py(py, &system, &mut j)?;
    j.push('}');
    Ok((digest_bytes(j.as_bytes()).short(), d, str_list(py, &editable)?))
}

// ---------------------------------------------------------------------------------------------------------------
// time zone and locale

/// `tz_locale_identity()`: the locale variables of `environ._data` (read without the recorded `os.environ`'s
/// hooks; `dict(environ)` when it has none), `/etc/localtime`'s digest and the digest of the zone file TZ names.
#[pyfunction]
fn tz_locale_identity<'py>(py: Python<'py>, environ: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let data = match environ.getattr(intern!(py, "_data")) {
        Ok(d) => d,
        Err(e) if e.is_instance_of::<PyAttributeError>(py) => environ.clone(),
        Err(e) => return Err(e),
    };
    let env = py.import("builtins")?.getattr(intern!(py, "dict"))?.call1((data,))?;
    let env = env.cast::<PyDict>()?;
    let mut vals: [Option<Bound<'py, PyAny>>; 17] = Default::default();
    for (k, v) in env.iter() {
        let kw: W = match k.cast::<PyBytes>() {
            Ok(b) if b.as_bytes().is_ascii() => b.as_bytes().to_vec(),
            Ok(b) => fsdecode(py, b.as_bytes())?,
            Err(_) => match k.cast::<PyString>() {
                Ok(s) => wtf8(s)?.into_owned(),
                Err(_) => continue,
            },
        };
        if let Some(i) = LOCALE_VARS.iter().position(|n| n.as_bytes() == kw.as_slice()) {
            vals[i] = Some(match v.cast::<PyBytes>() {
                Ok(b) => fsdecode_py(py, b.as_bytes())?,
                Err(_) => v,
            });
        }
    }
    let d = PyDict::new(py);
    for (name, v) in LOCALE_VARS.iter().zip(vals.iter()) {
        d.set_item(name, v)?;
    }
    d.set_item("/etc/localtime", proof::file_digest(Path::new("/etc/localtime")))?;
    if let Some(tz) = &vals[0] {
        if tz.is_truthy()? {
            let tz = wtf8(tz.cast::<PyString>()?)?;
            let name = tz.strip_prefix(b":").unwrap_or(&tz);
            let zdir = match &vals[1] {
                Some(z) if z.is_truthy()? => wtf8(z.cast::<PyString>()?)?.into_owned(),
                _ => b"/usr/share/zoneinfo".to_vec(),
            };
            let path = join(&zdir, name);
            let digest = match fsencode(py, &path)? {
                Some(p) if std::fs::metadata(&p).is_ok_and(|m| m.is_file()) => proof::file_digest(&p),
                _ => None,
            };
            d.set_item("tzfile", digest)?;
        }
    }
    Ok(d)
}

// ---------------------------------------------------------------------------------------------------------------
// cache epoch

/// `int(json.load(open(path))["epoch_ns"])`, None on OSError / ValueError / KeyError / TypeError.
fn kept_epoch<'py>(py: Python<'py>, path: &Path) -> PyResult<Option<Bound<'py, PyAny>>> {
    use serde_json::Value;
    match read_ascii(path) {
        Ok(None) => return Ok(None),
        Ok(Some(text)) => match serde_json::from_str::<Value>(&text) {
            Ok(Value::Object(o)) => match o.get("epoch_ns") {
                None | Some(Value::Null | Value::Array(_) | Value::Object(_)) => return Ok(None),
                Some(Value::Bool(b)) => return Ok(Some((*b as i64).into_bound_py_any(py)?)),
                Some(Value::Number(n)) if n.as_i64().is_some() => {
                    return Ok(Some(n.as_i64().unwrap().into_bound_py_any(py)?));
                }
                _ => {} // a float, a big or a string number: int() of Python
            },
            Ok(_) => return Ok(None), // not subscriptable by a str: TypeError
            Err(_) => {}
        },
        Err(()) => {}
    }
    let caught = |e: &PyErr| {
        is_os_or_value_error(py, e)
            || e.is_instance_of::<pyo3::exceptions::PyKeyError>(py)
            || e.is_instance_of::<pyo3::exceptions::PyTypeError>(py)
    };
    let Some(v) = py_json_load(py, path, &caught)? else { return Ok(None) };
    let r = v
        .get_item("epoch_ns")
        .and_then(|x| py.import("builtins")?.getattr(intern!(py, "int"))?.call1((x,)));
    match r {
        Ok(k) => Ok(Some(k)),
        Err(e) if caught(&e) => Ok(None),
        Err(e) => Err(e),
    }
}

/// `cache_epoch(cache_dir, head_ns, window_ns)`: the epoch kept in `<cache_dir>/epoch.json` while `head_ns` is at
/// most `window_ns` later, else `head_ns` (written there as `json.dump` writes it).
#[pyfunction]
fn cache_epoch<'py>(
    py: Python<'py>,
    cache_dir: PathBuf,
    head_ns: &Bound<'py, PyAny>,
    window_ns: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    // os.path.join(os.path.abspath(cache_dir), "epoch.json")
    let raw = cache_dir.as_os_str().as_bytes();
    let abs = if raw.starts_with(b"/") {
        normpath(raw)
    } else {
        let cwd = std::env::current_dir()?;
        normpath(&join(cwd.as_os_str().as_bytes(), raw))
    };
    let path = PathBuf::from(OsStr::from_bytes(&join(&abs, b"epoch.json")));
    if let Some(kept) = kept_epoch(py, &path)? {
        if head_ns.sub(&kept)?.le(window_ns)? {
            return Ok(kept);
        }
    }
    if std::fs::create_dir_all(OsStr::from_bytes(&abs)).is_ok() {
        let head = if head_ns.is_exact_instance_of::<PyInt>() {
            head_ns.str()?.to_cow()?.into_owned()
        } else {
            json_mod(py)?.call_method1(intern!(py, "dumps"), (head_ns,))?.cast::<PyString>()?.to_cow()?.into_owned()
        };
        write_replace(&path, &format!("{{\"epoch_ns\": {head}, \"taken_from\": \"git HEAD commit time\"}}"));
    }
    Ok(head_ns.clone())
}

// ---------------------------------------------------------------------------------------------------------------
// env0

/// `_safe(s)`: `s` when it encodes to UTF-8, else `s.encode("utf-8", "surrogateescape").decode("utf-8",
/// "backslashreplace")` (raising as that does for a surrogate outside U+DC80..U+DCFF).
fn safe<'py>(py: Python<'py>, s: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let st = s.cast::<PyString>()?;
    if st.to_cow().is_ok() {
        return Ok(s.clone());
    }
    let b = st.call_method1(intern!(py, "encode"), ("utf-8", "surrogateescape"))?;
    let b = b.cast::<PyBytes>()?.as_bytes();
    let mut out = String::with_capacity(b.len() + 8);
    let mut rest = b;
    loop {
        match std::str::from_utf8(rest) {
            Ok(t) => {
                out.push_str(t);
                break;
            }
            Err(e) => {
                let v = e.valid_up_to();
                out.push_str(std::str::from_utf8(&rest[..v]).unwrap());
                let n = e.error_len().unwrap_or(rest.len() - v);
                for &x in &rest[v..v + n] {
                    out.push_str(&format!("\\x{x:02x}"));
                }
                rest = &rest[v + n..];
            }
        }
    }
    Ok(PyString::new(py, &out).into_any())
}

/// `{_safe(k): _safe(v) for k, v in items if k not in exclude}` (start()'s `env0`).
#[pyfunction]
fn safe_env<'py>(py: Python<'py>, items: &Bound<'py, PyAny>, exclude: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    for kv in items.try_iter()? {
        let kv = kv?;
        let (k, v) = match kv.cast::<PyTuple>() {
            Ok(t) if t.len() == 2 => (t.get_item(0)?, t.get_item(1)?),
            _ => kv.extract()?,
        };
        if exclude.contains(&k)? {
            continue;
        }
        d.set_item(safe(py, &k)?, safe(py, &v)?)?;
    }
    Ok(d)
}

/// `_safe(s)` (for the equivalence tests).
#[pyfunction]
#[pyo3(name = "safe_str")]
fn safe_str<'py>(py: Python<'py>, s: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    safe(py, s)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(dist_infos, m)?)?;
    m.add_function(wrap_pyfunction!(runtime_identity, m)?)?;
    m.add_function(wrap_pyfunction!(tz_locale_identity, m)?)?;
    m.add_function(wrap_pyfunction!(cache_epoch, m)?)?;
    m.add_function(wrap_pyfunction!(safe_env, m)?)?;
    m.add_function(wrap_pyfunction!(safe_str, m)?)?;
    Ok(())
}
