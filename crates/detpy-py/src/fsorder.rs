//! Level 0 filesystem order in Rust: the sorted, recorded `os.listdir` / `os.scandir` stand-ins, the quiet, sorted
//! and recorded listing behind the `glob` / `pathlib` wrappers, the event of an enumeration (`fsorder._event`) and
//! the machine-independent rendering of paths it records (`_sites.norm_path`, `_sites._shorten`).
//!
//! Port of `detpy/fsorder.py` (`listdir`, `scandir`, `SortedScandir`, `_event`, `_quietly` and the bodies of
//! `glob_glob`, `glob_iglob`, `path_iterdir`, `path_glob`, `path_rglob`), `detpy/_sites.py` (`norm_path`,
//! `_shorten`, `_rel`) and `detpy/_state.py` (`digest_names`). The Python originals are kept verbatim in
//! `tests/rust_hotpaths_ref/` (`_ref_l0_fsorder.py`, `_ref_l0_sites_norm.py`; `digest_names`: `_ref_l0_state.py`);
//! traces, stores and receipts are tested byte-identical against them (`tests/test_level0_seeds_fsorder_rust.py`).
//!
//! Paths are handled as bytes: the UTF-8 of the string, or for a string with lone surrogates (an undecodable file
//! name under `surrogateescape`) the "surrogatepass" encoding of it, which maps code points one to one to byte
//! sequences, so prefix tests, `/` splits and slices after a separator give the same strings as Python's.

use crate::level0::{l0_is_busy, l0_set_busy, record_from_rust, record_from_rust_obj, sites_globals, state_attr};
use crate::standin::{bind, call_with, Kind, Target};
use detpy_core::fingerprint::digest_bytes;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyUnboundLocalError};
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyInt, PyList, PyString, PyTuple};
use std::borrow::Cow;

/// `os.sep`.
const SEP: u8 = if cfg!(windows) { b'\\' } else { b'/' };

// ---------------------------------------------------------------------------------------------------------------
// Strings as bytes

/// The bytes of `s` (see the module docs).
fn wtf8<'a>(s: &'a Bound<'_, PyString>) -> PyResult<Cow<'a, [u8]>> {
    match s.to_cow() {
        Ok(Cow::Borrowed(b)) => Ok(Cow::Borrowed(b.as_bytes())),
        Ok(Cow::Owned(o)) => Ok(Cow::Owned(o.into_bytes())),
        Err(_) => {
            let b = unsafe {
                Bound::from_owned_ptr_or_err(
                    s.py(),
                    ffi::PyUnicode_AsEncodedString(s.as_ptr(), c"utf-8".as_ptr(), c"surrogatepass".as_ptr()),
                )?
            };
            Ok(Cow::Owned(b.cast::<PyBytes>()?.as_bytes().to_vec()))
        }
    }
}

fn wtf8_of(o: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    Ok(wtf8(o.cast::<PyString>()?)?.into_owned())
}

/// The string of bytes made by `wtf8`.
fn from_wtf8<'py>(py: Python<'py>, b: &[u8]) -> PyResult<Bound<'py, PyString>> {
    match std::str::from_utf8(b) {
        Ok(s) => Ok(PyString::new(py, s)),
        Err(_) => unsafe {
            Ok(Bound::from_owned_ptr_or_err(
                py,
                ffi::PyUnicode_DecodeUTF8(b.as_ptr().cast(), b.len() as ffi::Py_ssize_t, c"surrogatepass".as_ptr()),
            )?
            .cast_into::<PyString>()?)
        },
    }
}

fn replace_sep(mut b: Vec<u8>) -> Vec<u8> {
    if SEP != b'/' {
        for c in b.iter_mut() {
            if *c == SEP {
                *c = b'/';
            }
        }
    }
    b
}

fn concat(prefix: &[u8], rest: Vec<u8>) -> Vec<u8> {
    let mut out = Vec::with_capacity(prefix.len() + rest.len());
    out.extend_from_slice(prefix);
    out.extend(replace_sep(rest));
    out
}

// ---------------------------------------------------------------------------------------------------------------
// `_sites.norm_path`

/// `posixpath.normpath` (the C `_path_normpath` of CPython 3.12+).
fn normpath_posix(p: &[u8]) -> Vec<u8> {
    if p.is_empty() {
        return b".".to_vec();
    }
    let mut initial = usize::from(p[0] == b'/');
    if initial == 1 && p.starts_with(b"//") && !p.starts_with(b"///") {
        initial = 2;
    }
    let mut comps: Vec<&[u8]> = Vec::new();
    for c in p.split(|&b| b == b'/') {
        if c.is_empty() || c == b"." {
            continue;
        }
        if c != b".." || (initial == 0 && comps.is_empty()) || comps.last() == Some(&&b".."[..]) {
            comps.push(c);
        } else if !comps.is_empty() {
            comps.pop();
        }
    }
    let mut out = vec![b'/'; initial];
    out.extend(comps.join(&b'/'));
    if out.is_empty() {
        b".".to_vec()
    } else {
        out
    }
}

/// `os.path.normpath(os.path.join(cwd, s))` for a relative `s` (`join` = `cwd + sep + s` unless `cwd` is empty or
/// ends with the separator), or `os.path.normpath(s)` (`cwd` None).
fn abs_norm(py: Python<'_>, cwd: Option<&[u8]>, s: &[u8]) -> PyResult<Vec<u8>> {
    if SEP == b'/' {
        let joined;
        let p = match cwd {
            None => s,
            Some(c) => {
                let mut j = c.to_vec();
                if !j.is_empty() && !j.ends_with(b"/") {
                    j.push(b'/');
                }
                j.extend_from_slice(s);
                joined = j;
                &joined
            }
        };
        return Ok(normpath_posix(p));
    }
    // other separators (Windows): the interpreter's ntpath
    let osp = py.import("os.path")?;
    let s = from_wtf8(py, s)?;
    let p = match cwd {
        None => s.into_any(),
        Some(c) => osp.getattr("join")?.call1((from_wtf8(py, c)?, s))?,
    };
    wtf8_of(&osp.getattr("normpath")?.call1((p,))?)
}

fn isabs(py: Python<'_>, s: &[u8]) -> PyResult<bool> {
    if SEP == b'/' {
        return Ok(s.starts_with(b"/"));
    }
    py.import("os.path")?.getattr("isabs")?.call1((from_wtf8(py, s)?,))?.is_truthy()
}

/// `_under(s, base)` and `_rel(s, base)`: the part of `s` under `base`, if it is under it (`"."` for `base` itself).
fn rel_under(py: Python<'_>, s: &[u8], base: &Bound<'_, PyAny>) -> PyResult<Option<Vec<u8>>> {
    if let Ok(b) = base.cast::<PyString>() {
        let b = wtf8(b)?;
        if s == &b[..] {
            return Ok(Some(b".".to_vec()));
        }
        if s.len() > b.len() && s.starts_with(&b) && s[b.len()] == SEP {
            return Ok(Some(s[b.len() + 1..].to_vec()));
        }
        return Ok(None);
    }
    // not a str (a provider returning something else): Python's own operations
    let so = from_wtf8(py, s)?;
    if so.as_any().eq(base)? {
        return Ok(Some(b".".to_vec()));
    }
    let sep = PyString::new(py, std::str::from_utf8(&[SEP]).unwrap_or("/"));
    let pre = base.add(sep)?;
    if !so.call_method1(intern!(py, "startswith"), (pre,))?.is_truthy()? {
        return Ok(None);
    }
    let start = base.len()? + 1;
    let rest = so.get_item(pyo3::types::PySlice::new(py, start as isize, isize::MAX, 1))?;
    Ok(Some(wtf8_of(&rest)?))
}

fn sites_get<'py>(g: &Bound<'py, PyDict>, k: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    g.get_item(k)?.ok_or_else(|| PyRuntimeError::new_err(format!("detpy._sites.{k} missing")))
}

/// `_sites._shorten(s)` on the globals of `detpy._sites` (basetemp provider, `_rootdir`, `_site_dirs`,
/// `_stdlib_dirs`, `_PYTEST_TMP`, `_TMP`, `_HOME`, read at every call as the Python function read them).
fn shorten(py: Python<'_>, g: &Bound<'_, PyDict>, s: Vec<u8>) -> PyResult<Vec<u8>> {
    let provider = sites_get(g, intern!(py, "_basetemp_provider"))?;
    if !provider.is_none() {
        let bt = provider.call0()?;
        if bt.is_truthy()? {
            if let Some(r) = rel_under(py, &s, &bt)? {
                return Ok(concat(b"<basetemp>/", r));
            }
        }
    }
    let root = sites_get(g, intern!(py, "_rootdir"))?;
    if root.is_truthy()? {
        if let Some(r) = rel_under(py, &s, &root)? {
            return Ok(replace_sep(r));
        }
    }
    for d in sites_get(g, intern!(py, "_site_dirs"))?.try_iter()? {
        if let Some(r) = rel_under(py, &s, &d?)? {
            return Ok(concat(b"<site>/", r));
        }
    }
    for d in sites_get(g, intern!(py, "_stdlib_dirs"))?.try_iter()? {
        if let Some(r) = rel_under(py, &s, &d?)? {
            return Ok(concat(b"<stdlib>/", r));
        }
    }
    let mut s = s;
    if s.windows(10).any(|w| w == b"pytest-of-") {
        // the regex needs the literal: only then can it change anything
        let rx = sites_get(g, intern!(py, "_PYTEST_TMP"))?;
        let out = rx.call_method1(intern!(py, "sub"), ("pytest-of-U/pytest-N", from_wtf8(py, &s)?))?;
        s = wtf8_of(&out)?;
    }
    if let Some(r) = rel_under(py, &s, &sites_get(g, intern!(py, "_TMP"))?)? {
        return Ok(concat(b"<tmp>/", r));
    }
    let home = sites_get(g, intern!(py, "_HOME"))?;
    if home.is_truthy()? && home.ne("/")? {
        if let Some(r) = rel_under(py, &s, &home)? {
            return Ok(concat(b"~/", r));
        }
    }
    Ok(replace_sep(s))
}

/// `_sites.norm_path(path)` as bytes (see the module docs).
pub(crate) fn norm_path(py: Python<'_>, path: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    if path.is_instance_of::<PyInt>() {
        return Ok(b"<fd>".to_vec());
    }
    if path.is_none() {
        return Ok(b".".to_vec());
    }
    // os.fsdecode(os.fspath(path))
    let fs = match unsafe { Bound::from_owned_ptr_or_err(py, ffi::PyOS_FSPath(path.as_ptr())) } {
        Ok(f) => f,
        Err(e) if e.is_instance_of::<PyTypeError>(py) => {
            let name = path.get_type().getattr(intern!(py, "__name__"))?;
            return Ok(format!("<{}>", name.str()?.to_cow()?).into_bytes());
        }
        Err(e) => return Err(e),
    };
    let s = if let Ok(b) = fs.cast::<PyBytes>() {
        let raw = b.as_bytes();
        unsafe {
            Bound::from_owned_ptr_or_err(
                py,
                ffi::PyUnicode_DecodeFSDefaultAndSize(raw.as_ptr().cast(), raw.len() as ffi::Py_ssize_t),
            )?
            .cast_into::<PyString>()?
        }
    } else {
        fs.cast_into::<PyString>()?
    };
    let g = sites_globals(py)?;
    let b = wtf8(&s)?;
    let full = if b.is_empty() {
        wtf8_of(&sites_get(&g, intern!(py, "_real_getcwd"))?.call0()?)?
    } else if !isabs(py, &b)? {
        let cwd = wtf8_of(&sites_get(&g, intern!(py, "_real_getcwd"))?.call0()?)?;
        abs_norm(py, Some(&cwd), &b)?
    } else {
        abs_norm(py, None, &b)?
    };
    shorten(py, &g, full)
}

/// `_sites.norm_path(path)`: machine independent rendering of a filesystem path argument.
#[pyfunction]
pub fn l0_norm_path<'py>(py: Python<'py>, path: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyString>> {
    from_wtf8(py, &norm_path(py, path)?)
}

/// `_sites._shorten(s)` of a normalised absolute path.
#[pyfunction]
pub fn l0_shorten<'py>(py: Python<'py>, s: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyString>> {
    let g = sites_globals(py)?;
    let b = wtf8(s)?.into_owned();
    from_wtf8(py, &shorten(py, &g, b)?)
}

// ---------------------------------------------------------------------------------------------------------------
// `_state.digest_names`, `fsorder._event`

/// `_state.digest_names(names)`: digest of the names (bytes as they are, others as
/// `str(n).encode("utf-8", "surrogateescape")`) joined by NUL.
pub(crate) fn digest_names(names: &Bound<'_, PyAny>) -> PyResult<String> {
    let py = names.py();
    let mut buf: Vec<u8> = Vec::new();
    for (i, n) in names.try_iter()?.enumerate() {
        let n = n?;
        if i > 0 {
            buf.push(0);
        }
        if let Ok(b) = n.cast::<PyBytes>() {
            buf.extend_from_slice(b.as_bytes());
            continue;
        }
        let s = n.str()?;
        match s.to_cow() {
            Ok(c) => buf.extend_from_slice(c.as_bytes()),
            Err(_) => {
                let e = unsafe {
                    Bound::from_owned_ptr_or_err(
                        py,
                        ffi::PyUnicode_AsEncodedString(s.as_ptr(), c"utf-8".as_ptr(), c"surrogateescape".as_ptr()),
                    )?
                };
                buf.extend_from_slice(e.cast::<PyBytes>()?.as_bytes());
            }
        }
    }
    Ok(digest_bytes(&buf).short())
}

#[pyfunction]
pub fn l0_digest_names(names: &Bound<'_, PyAny>) -> PyResult<String> {
    digest_names(names)
}

/// `fsorder._event` before computing anything: no test running, or quiet.
fn silent(py: Python<'_>) -> PyResult<bool> {
    Ok(state_attr(py, intern!(py, "nodeid"))?.is_none() || l0_is_busy())
}

/// `fsorder._event(op, where, names)`: record `"<norm_path(where)>|<len(names)>|<digest_names(names)>"`, `skip`
/// frames above the calling frame (0: the caller of a Rust stand-in).
fn event(py: Python<'_>, op: &str, where_: &Bound<'_, PyAny>, names: &Bound<'_, PyAny>, skip: usize) -> PyResult<()> {
    if silent(py)? {
        return Ok(());
    }
    let norm = norm_path(py, where_)?;
    let n = names.len()?;
    let dg = digest_names(names)?;
    match String::from_utf8(norm) {
        Ok(norm) => record_from_rust(py, "fs", op, format!("{norm}|{n}|{dg}"), skip),
        Err(e) => {
            // a path with surrogates: the value is the Python string (whose recording fails as it did)
            let v = from_wtf8(py, e.as_bytes())?.add(format!("|{n}|{dg}"))?;
            record_from_rust_obj(py, "fs", op, &v, skip)
        }
    }
}

/// `fs_event(op, where, names, depth=1)`: `fsorder._event` for a Python caller (`depth`: frames to skip above it).
#[pyfunction]
#[pyo3(signature = (op, r#where, names, depth = 1))]
pub fn fs_event(py: Python<'_>, op: &str, r#where: &Bound<'_, PyAny>, names: &Bound<'_, PyAny>, depth: usize) -> PyResult<()> {
    event(py, op, r#where, names, depth)
}

// ---------------------------------------------------------------------------------------------------------------
// The stand-ins and the sorted listings

/// The iterator `os.scandir` returns, sorted by name (`fsorder.SortedScandir`).
#[pyclass(module = "detpy.fsorder", name = "SortedScandir")]
pub(crate) struct SortedScandir {
    entries: Py<PyList>,
    pos: usize,
    closed: bool,
}

#[pymethods]
impl SortedScandir {
    #[new]
    fn new(entries: Bound<'_, PyList>) -> Self {
        SortedScandir { entries: entries.unbind(), pos: 0, closed: false }
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> Option<Py<PyAny>> {
        if self.closed {
            return None;
        }
        let e = self.entries.bind(py);
        if self.pos < e.len() {
            let item = e.get_item(self.pos).ok()?;
            self.pos += 1;
            Some(item.unbind())
        } else {
            self.closed = true;
            None
        }
    }

    fn close(&mut self) {
        self.closed = true;
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    #[pyo3(signature = (*_exc))]
    fn __exit__(&mut self, _exc: &Bound<'_, PyTuple>) {
        self.closed = true;
    }
}

fn fs_global<'py>(g: &Bound<'py, PyDict>, k: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    g.get_item(k)?.ok_or_else(|| PyRuntimeError::new_err(format!("detpy.fsorder.{k} missing")))
}

fn listing<'py>(real: &Bound<'py, PyAny>, path: &Option<Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyAny>> {
    match path {
        Some(p) if !p.is_none() => real.call1((p,)),
        _ => real.call0(),
    }
}

/// `sorted(it, key=key)` / `list.sort(key=key)` (`key` None: natural order).
fn sort_list(list: &Bound<'_, PyList>, key: &Bound<'_, PyAny>) -> PyResult<()> {
    if key.is_none() {
        return list.sort();
    }
    let kw = PyDict::new(list.py());
    kw.set_item(intern!(list.py(), "key"), key)?;
    list.call_method(intern!(list.py(), "sort"), (), Some(&kw))?;
    Ok(())
}

/// `os.listdir(path=None)` / `os.scandir(path=None)`: the real one (`fsorder._real_listdir` / `_real_scandir`, read
/// at every call), sorted by name, recorded.
pub(crate) fn call<'py>(
    py: Python<'py>,
    t: &Target,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    let [path] = bind(&t.fname, ["path"], 0, args, kwargs)?;
    let g = t.real.bind(py).cast::<PyDict>()?;
    let none = py.None().into_bound(py);
    let where_ = path.as_ref().unwrap_or(&none);
    match t.kind {
        Kind::Listdir => {
            let names = listing(&fs_global(g, intern!(py, "_real_listdir"))?, &path)?;
            match names.cast::<PyList>() {
                Ok(l) => l.sort()?,
                Err(_) => {
                    names.call_method0(intern!(py, "sort"))?;
                }
            }
            event(py, &t.op, where_, &names, 0)?;
            Ok(names)
        }
        Kind::Scandir => {
            let it = listing(&fs_global(g, intern!(py, "_real_scandir"))?, &path)?;
            // with it: entries = sorted(it, key=lambda e: e.name)
            it.call_method0(intern!(py, "__enter__"))?;
            let body = || -> PyResult<Bound<'py, PyList>> {
                let entries = unsafe { Bound::from_owned_ptr_or_err(py, ffi::PySequence_List(it.as_ptr()))? };
                let entries = entries.cast_into::<PyList>()?;
                sort_list(&entries, &fs_global(g, intern!(py, "_BY_NAME"))?)?;
                Ok(entries)
            };
            let entries = match body() {
                Ok(e) => {
                    it.call_method1(intern!(py, "__exit__"), (&none, &none, &none))?;
                    e
                }
                Err(err) => {
                    let suppressed = it
                        .call_method1(intern!(py, "__exit__"), (err.get_type(py), err.value(py), err.traceback(py)))?
                        .is_truthy()?;
                    if suppressed {
                        return Err(PyUnboundLocalError::new_err(
                            "cannot access local variable 'entries' where it is not associated with a value",
                        ));
                    }
                    return Err(err);
                }
            };
            if !silent(py)? {
                let names = PyList::empty(py);
                for e in entries.iter() {
                    names.append(e.getattr(intern!(py, "name"))?)?;
                }
                event(py, &t.op, where_, names.as_any(), 0)?;
            }
            Ok(Bound::new(py, SortedScandir::new(entries))?.into_any())
        }
        _ => unreachable!("fsorder::call: not a filesystem stand-in"),
    }
}

/// `fs_sorted(op, where, real, args, kwargs, key, by_name, depth=1)`: the body of the `glob` / `pathlib` wrappers:
/// `res = sorted(quietly(list(real(*args, **kwargs))), key=key)`, then the event of `op` on `where` with the names
/// `[p.name for p in res]` (`by_name`) or `[_sites.norm_path(p) for p in res]`, `depth` frames above the caller.
#[pyfunction]
#[pyo3(signature = (op, r#where, real, args, kwargs, key, by_name, depth = 1))]
#[allow(clippy::too_many_arguments)]
pub fn fs_sorted<'py>(
    py: Python<'py>,
    op: &str,
    r#where: &Bound<'py, PyAny>,
    real: &Bound<'py, PyAny>,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
    key: &Bound<'py, PyAny>,
    by_name: bool,
    depth: usize,
) -> PyResult<Bound<'py, PyList>> {
    let prev = l0_set_busy(true);
    let res = call_with(real, args, kwargs)
        .and_then(|r| unsafe { Bound::from_owned_ptr_or_err(py, ffi::PySequence_List(r.as_ptr())) });
    l0_set_busy(prev);
    let res = res?.cast_into::<PyList>()?;
    sort_list(&res, key)?;
    // the names are computed whether or not the event is recorded, as the wrappers' arguments were
    let names = PyList::empty(py);
    for p in res.iter() {
        if by_name {
            names.append(p.getattr(intern!(py, "name"))?)?;
        } else {
            names.append(from_wtf8(py, &norm_path(py, &p)?)?)?;
        }
    }
    event(py, op, r#where, names.as_any(), depth)?;
    Ok(res)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SortedScandir>()?;
    for f in [
        wrap_pyfunction!(l0_norm_path, m)?,
        wrap_pyfunction!(l0_shorten, m)?,
        wrap_pyfunction!(l0_digest_names, m)?,
        wrap_pyfunction!(fs_event, m)?,
        wrap_pyfunction!(fs_sorted, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
