//! sqlite statements of the cache with proof (review R-009 F4 / R-009b R1), in Rust.
//!
//! sqlite evaluates 'now' (`date('now')`, `CURRENT_TIMESTAMP`, `date()` without a time value) on the real clock in
//! C. Every connection made through the patched `sqlite3.connect` traces its statements with a [`SqlTrace`] (a Rust
//! callable: no Python frame per statement); one that may read the real clock flags its context `rclock`. The schema
//! evaluates such expressions too (a column default, a trigger, a view) while the statement says nothing about
//! time: a statement that may evaluate the schema on a connection whose databases' schema may read the clock is
//! flagged in the same way.
//!
//! Port of `Capture._sql_trace`, `_sql_schema_clock` (but its read-only query, `Capture._sql_schema_read` in
//! Python: it needs the real `sqlite3.connect`), `_SqlConn`, `_sqlite_file` and the regular expressions
//! `_SQL_REAL_CLOCK`, `_SQL_NO_SCHEMA`, `_SQL_DDL`, `_SQL_ATTACH` of round 2's `detpy/proofcache.py` (kept in
//! `tests/rust_hotpaths_ref/_ref_proofcache.py`). The expressions are hand-written matchers with Python `re`'s
//! semantics for a `str` pattern with `re.I`: `\s` is `str.isspace`, `\b` is a change of `str.isalnum() or "_"`
//! (both asked of the interpreter for a non-ASCII character, once per character), and a letter matches its case
//! variants as `re` folds them (ASCII, plus U+0130 and U+0131 for `i`, U+017F for `s`, U+212A for `k`). Tested
//! against `re` on generated statements (`tests/test_sqlcap_rust.py`).

use crate::capture::{normpath, CaptureCore};
use crate::fsorder::{from_wtf8, wtf8};
use crate::lock;
use pyo3::exceptions::{PyOSError, PyTypeError, PyValueError};
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyBytes, PyModule, PyString};
use std::borrow::Cow;
use std::collections::HashMap;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::sync::Mutex;

type W = Vec<u8>;

// ---------------------------------------------------------------------------------------------------------------
// Characters (the text is a Python `str` as UTF-8, lone surrogates as their 3-byte form)

/// The code point at `i` and its length.
fn cp_at(b: &[u8], i: usize) -> (u32, usize) {
    let c = b[i];
    let (n, init) = match c {
        0..=0x7F => return (u32::from(c), 1),
        0xC0..=0xDF => (2, u32::from(c & 0x1F)),
        0xE0..=0xEF => (3, u32::from(c & 0x0F)),
        _ => (4, u32::from(c & 0x07)),
    };
    let n = n.min(b.len() - i);
    let cp = b[i + 1..i + n].iter().fold(init, |a, &x| (a << 6) | u32::from(x & 0x3F));
    (cp, n)
}

/// The code point before `i` (None at the start).
fn cp_before(b: &[u8], i: usize) -> Option<u32> {
    if i == 0 {
        return None;
    }
    let mut j = i - 1;
    while j > 0 && b[j] & 0xC0 == 0x80 {
        j -= 1;
    }
    Some(cp_at(b, j).0)
}

/// `str.isalnum()` / `str.isspace()` of non-ASCII characters, asked of the interpreter once each.
static UNI: Mutex<Option<HashMap<u32, (bool, bool)>>> = Mutex::new(None);

fn uni(py: Python<'_>, cp: u32) -> PyResult<(bool, bool)> {
    if let Some(v) = lock(&UNI).as_ref().and_then(|m| m.get(&cp)) {
        return Ok(*v);
    }
    let s = py.import("builtins")?.getattr("chr")?.call1((cp,))?;
    let v = (s.call_method0("isalnum")?.is_truthy()?, s.call_method0("isspace")?.is_truthy()?);
    lock(&UNI).get_or_insert_with(HashMap::new).insert(cp, v);
    Ok(v)
}

/// `re`'s `\w` for a `str` pattern: `str.isalnum()` or `_`.
fn is_word(py: Python<'_>, cp: u32) -> PyResult<bool> {
    if cp < 0x80 {
        let c = cp as u8;
        return Ok(c.is_ascii_alphanumeric() || c == b'_');
    }
    Ok(uni(py, cp)?.0)
}

/// `re`'s `\s` for a `str` pattern: `str.isspace()` (ASCII: `\t\n\v\f\r`, `\x1c`-`\x1f`, space).
fn is_space(py: Python<'_>, cp: u32) -> PyResult<bool> {
    if cp < 0x80 {
        return Ok(matches!(cp, 0x09..=0x0D | 0x1C..=0x20));
    }
    Ok(uni(py, cp)?.1)
}

/// A pattern byte (ASCII, letters lowercase) against a code point, with `re.I`.
fn ci_eq(cp: u32, p: u8) -> bool {
    if cp < 0x80 {
        let c = cp as u8;
        return c == p || (p.is_ascii_lowercase() && c.to_ascii_lowercase() == p);
    }
    match p {
        b'i' => cp == 0x130 || cp == 0x131,
        b's' => cp == 0x17F,
        b'k' => cp == 0x212A,
        _ => false,
    }
}

/// `kw` (lowercase ASCII) at `i` with `re.I`: the index after it.
fn lit(b: &[u8], mut i: usize, kw: &[u8]) -> Option<usize> {
    for &p in kw {
        if i >= b.len() {
            return None;
        }
        let (cp, n) = cp_at(b, i);
        if !ci_eq(cp, p) {
            return None;
        }
        i += n;
    }
    Some(i)
}

/// `\b` at `i`.
fn boundary(py: Python<'_>, b: &[u8], i: usize) -> PyResult<bool> {
    let before = match cp_before(b, i) {
        Some(c) => is_word(py, c)?,
        None => false,
    };
    let after = if i < b.len() { is_word(py, cp_at(b, i).0)? } else { false };
    Ok(before != after)
}

/// `\s*` from `i`.
fn spaces(py: Python<'_>, b: &[u8], mut i: usize) -> PyResult<usize> {
    while i < b.len() {
        let (cp, n) = cp_at(b, i);
        if !is_space(py, cp)? {
            break;
        }
        i += n;
    }
    Ok(i)
}

fn byte_at(b: &[u8], i: usize, c: u8) -> bool {
    b.get(i) == Some(&c)
}

/// `kw\b` at `i` for one of `kws` (`\s*(kw|...)\b` once the spaces are skipped).
fn keyword(py: Python<'_>, b: &[u8], i: usize, kws: &[&[u8]]) -> PyResult<bool> {
    for kw in kws {
        if let Some(j) = lit(b, i, kw) {
            if boundary(py, b, j)? {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

const CLOCK_FUNCS: [&[u8]; 5] = [b"date", b"time", b"datetime", b"julianday", b"unixepoch"];

/// The alternatives of `_SQL_REAL_CLOCK` at `i`.
fn real_clock_at(py: Python<'_>, b: &[u8], i: usize) -> PyResult<bool> {
    if lit(b, i, b"'now'").is_some() || lit(b, i, b"\"now\"").is_some() {
        return Ok(true);
    }
    // the other alternatives start with \b and a letter
    let (cp, _) = cp_at(b, i);
    if !(matches!(cp | 0x20, 0x63 | 0x64 | 0x74 | 0x6A | 0x75 | 0x73) || cp == 0x17F) || !boundary(py, b, i)? {
        return Ok(false);
    }
    // \bcurrent_(timestamp|date|time)\b
    if let Some(j) = lit(b, i, b"current_") {
        for alt in [&b"timestamp"[..], b"date", b"time"] {
            if let Some(k) = lit(b, j, alt) {
                if boundary(py, b, k)? {
                    return Ok(true);
                }
            }
        }
    }
    // \b(date|time|datetime|julianday|unixepoch)\s*\(\s*\)
    for f in CLOCK_FUNCS {
        if let Some(j) = lit(b, i, f) {
            let j = spaces(py, b, j)?;
            if byte_at(b, j, b'(') {
                let k = spaces(py, b, j + 1)?;
                if byte_at(b, k, b')') {
                    return Ok(true);
                }
            }
        }
    }
    // \bstrftime\s*\(\s*('[^']*'|"[^"]*")\s*\)
    if let Some(j) = lit(b, i, b"strftime") {
        let j = spaces(py, b, j)?;
        if byte_at(b, j, b'(') {
            let k = spaces(py, b, j + 1)?;
            if let Some(&q) = b.get(k).filter(|&&q| q == b'\'' || q == b'"') {
                if let Some(e) = b[k + 1..].iter().position(|&c| c == q) {
                    let m = spaces(py, b, k + 1 + e + 1)?;
                    if byte_at(b, m, b')') {
                        return Ok(true);
                    }
                }
            }
        }
    }
    Ok(false)
}

/// `_SQL_REAL_CLOCK.search(s)`: 'now', CURRENT_TIMESTAMP/DATE/TIME, a date function called without a time value.
pub(crate) fn real_clock(py: Python<'_>, b: &[u8]) -> PyResult<bool> {
    // every alternative has one of these (uncased) characters
    if !b.iter().any(|&c| matches!(c, b'(' | b'\'' | b'"' | b'_')) {
        return Ok(false);
    }
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        // a possible first character: a quote, c d t j u s (any case), U+017F (C5 BF)
        if (matches!(c | 0x20, b'c' | b'd' | b't' | b'j' | b'u' | b's') || c == b'\'' || c == b'"' || c == 0xC5)
            && real_clock_at(py, b, i)?
        {
            return Ok(true);
        }
        i += 1;
        while i < b.len() && b[i] & 0xC0 == 0x80 {
            i += 1;
        }
    }
    Ok(false)
}

const NO_SCHEMA: [&[u8]; 13] = [
    b"begin", b"commit", b"end", b"rollback", b"savepoint", b"release", b"pragma", b"attach", b"detach", b"drop",
    b"vacuum", b"analyze", b"reindex",
];

/// `_SQL_NO_SCHEMA.match(s)`: statements that evaluate no column default, trigger or view.
pub(crate) fn no_schema(py: Python<'_>, b: &[u8]) -> PyResult<bool> {
    let i = spaces(py, b, 0)?;
    keyword(py, b, i, &NO_SCHEMA)
}

/// `_SQL_DDL.match(s)`.
pub(crate) fn ddl(py: Python<'_>, b: &[u8]) -> PyResult<bool> {
    let i = spaces(py, b, 0)?;
    keyword(py, b, i, &[b"create", b"alter"])
}

/// `'(?:[^']|'')*'` at `q`: the end of the match (the star backtracks to its last `''` at the end of the text).
fn sql_string(b: &[u8], q: usize) -> Option<usize> {
    if !byte_at(b, q, b'\'') {
        return None;
    }
    let mut i = q + 1;
    let mut last_pair = None;
    loop {
        if i >= b.len() {
            return last_pair.map(|e| e + 1);
        }
        if b[i] != b'\'' {
            i += 1;
        } else if byte_at(b, i + 1, b'\'') {
            last_pair = Some(i);
            i += 2;
        } else {
            return Some(i + 1);
        }
    }
}

/// `_SQL_ATTACH.match(s)`: the span of its group 1 (the quoted file name).
pub(crate) fn attach(py: Python<'_>, b: &[u8]) -> PyResult<Option<(usize, usize)>> {
    let i = spaces(py, b, 0)?;
    let Some(j) = lit(b, i, b"attach") else { return Ok(None) };
    let k = spaces(py, b, j)?;
    if k == j {
        return Ok(None);
    }
    if let Some(d) = lit(b, k, b"database") {
        let q = spaces(py, b, d)?;
        if q > d {
            if let Some(e) = sql_string(b, q) {
                return Ok(Some((q, e)));
            }
        }
    }
    Ok(sql_string(b, k).map(|e| (k, e)))
}

// ---------------------------------------------------------------------------------------------------------------
// `_sqlite_file`

/// `urllib.parse.unquote(s)` (utf-8, errors "replace"): runs of ASCII are unquoted to bytes and decoded, other
/// characters are kept.
fn unquote(s: &[u8]) -> W {
    if !s.contains(&b'%') {
        return s.to_vec();
    }
    let mut out = Vec::with_capacity(s.len());
    let mut i = 0;
    while i < s.len() {
        let start = i;
        while i < s.len() && s[i] < 0x80 {
            i += 1;
        }
        if i > start {
            let run = &s[start..i];
            let mut bytes = Vec::with_capacity(run.len());
            let mut bits = run.split(|&c| c == b'%');
            bytes.extend_from_slice(bits.next().unwrap_or(b""));
            for item in bits {
                let hex = |c: u8| (c as char).to_digit(16);
                match (item.first().and_then(|&c| hex(c)), item.get(1).and_then(|&c| hex(c))) {
                    (Some(h), Some(l)) => {
                        bytes.push((h * 16 + l) as u8);
                        bytes.extend_from_slice(&item[2..]);
                    }
                    _ => {
                        bytes.push(b'%');
                        bytes.extend_from_slice(item);
                    }
                }
            }
            out.extend_from_slice(String::from_utf8_lossy(&bytes).as_bytes());
        }
        let start = i;
        while i < s.len() && s[i] >= 0x80 {
            i += 1;
        }
        out.extend_from_slice(&s[start..i]);
    }
    out
}

fn split_once(s: &[u8], c: u8) -> (&[u8], &[u8]) {
    match s.iter().position(|&x| x == c) {
        Some(i) => (&s[..i], &s[i + 1..]),
        None => (s, b""),
    }
}

fn os_mod(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    static OS: PyOnceLock<Py<PyModule>> = PyOnceLock::new();
    Ok(OS.get_or_try_init(py, || py.import("os").map(|m| m.unbind()))?.bind(py).clone())
}

/// `os.path.abspath(s)` (`os.getcwd` looked up at each use); None where it raises OSError or ValueError.
fn abspath(py: Python<'_>, s: &[u8]) -> PyResult<Option<W>> {
    if s.starts_with(b"/") {
        return Ok(Some(normpath(s)));
    }
    let cwd = match os_mod(py)?.getattr(intern!(py, "getcwd"))?.call0() {
        Ok(c) => c,
        Err(e) if e.is_instance_of::<PyOSError>(py) || e.is_instance_of::<PyValueError>(py) => return Ok(None),
        Err(e) => return Err(e),
    };
    let mut j = wtf8(cwd.cast::<PyString>()?)?.into_owned();
    if !(j.is_empty() || j.ends_with(b"/")) {
        j.push(b'/');
    }
    j.extend_from_slice(s);
    Ok(Some(normpath(&j)))
}

/// `_sqlite_file(s, uri)` for a string `s`.
fn sqlite_file_str(py: Python<'_>, s: &[u8], uri: bool) -> PyResult<Option<W>> {
    let owned;
    let mut s = s;
    if uri && s.starts_with(b"file:") {
        let (path, query) = split_once(&s[5..], b'?');
        if split_once(query, b'#').0.split(|&c| c == b'&').any(|p| p == b"mode=memory") {
            return Ok(None);
        }
        let path: W = if path.starts_with(b"//") {
            let (host, rest) = split_once(&path[2..], b'/');
            if host.is_empty() || host == b"localhost" { [&b"/"[..], rest].concat() } else { W::new() }
        } else {
            path.to_vec()
        };
        owned = unquote(split_once(&path, b'#').0);
        s = &owned;
    }
    if s.is_empty() || s == b":memory:" {
        return Ok(None);
    }
    abspath(py, s)
}

/// `_sqlite_file(db, uri)`: the absolute path of the database file sqlite opens for `db` (None: in memory or not a
/// file name).
pub(crate) fn sqlite_file(py: Python<'_>, db: &Bound<'_, PyAny>, uri: bool) -> PyResult<Option<W>> {
    if let Ok(s) = db.cast::<PyString>() {
        return sqlite_file_str(py, &wtf8(s)?, uri);
    }
    let os = os_mod(py)?;
    if !(db.is_instance_of::<PyBytes>() || db.is_instance(&os.getattr(intern!(py, "PathLike"))?)?) {
        return Ok(None);
    }
    let s = match os.getattr(intern!(py, "fsdecode"))?.call1((db,)) {
        Ok(s) => s,
        Err(e) if e.is_instance_of::<PyTypeError>(py) || e.is_instance_of::<PyValueError>(py) => return Ok(None),
        Err(e) => return Err(e),
    };
    sqlite_file_str(py, &wtf8(s.cast::<PyString>()?)?, uri)
}

// ---------------------------------------------------------------------------------------------------------------
// The trace

/// The identity of a database file and its write-ahead log (`(st_ino, st_size, st_mtime_ns)` or None each).
pub(crate) type SqlSig = [Option<(u64, u64, i64, i64)>; 2];

fn stat_sig(path: &[u8]) -> PyResult<Option<(u64, u64, i64, i64)>> {
    // os.stat: a NUL or a surrogate that is not an escaped byte raises ValueError
    let Some(b) = crate::capture::fs_bytes(path) else {
        return Err(PyValueError::new_err("surrogates not allowed"));
    };
    if b.contains(&0) {
        return Err(PyValueError::new_err("embedded null byte"));
    }
    Ok(std::fs::metadata(std::ffi::OsStr::from_bytes(&b))
        .ok()
        .map(|m| (m.ino(), m.size(), m.mtime(), m.mtime_nsec())))
}

/// `Capture._sql_schema_clock(path)`: what in the schema of database file `path` may read the real clock (None:
/// nothing), memoised on the file's and its write-ahead log's identity; on a miss, `Capture._sql_schema_read`.
fn schema_clock(py: Python<'_>, cap: &Bound<'_, CaptureCore>, path: &[u8]) -> PyResult<Option<W>> {
    let mut wal = path.to_vec();
    wal.extend_from_slice(b"-wal");
    let sig: SqlSig = [stat_sig(path)?, stat_sig(&wal)?];
    if sig[0].is_none() {
        return Ok(None); // not created yet: no schema
    }
    if let Some((s, why)) = lock(&cap.get().sql_schema).get(path) {
        if *s == sig {
            return Ok(why.clone());
        }
    }
    let r = cap.call_method1(intern!(py, "_sql_schema_read"), (from_wtf8(py, path)?,))?;
    let why = if r.is_none() { None } else { Some(wtf8(r.cast::<PyString>()?)?.into_owned()) };
    lock(&cap.get().sql_schema).insert(path.to_vec(), (sig, why.clone()));
    Ok(why)
}

extern "C" {
    // in every CPython 3 (in the limited API from 3.10); the capture runs on 3.12+ (sys.monitoring)
    fn PyUnicode_AsUTF8AndSize(unicode: *mut ffi::PyObject, size: *mut ffi::Py_ssize_t) -> *const std::ffi::c_char;
}

/// The text of a statement: its UTF-8 as the interpreter caches it (no copy), or its `surrogatepass` encoding.
fn text<'a>(s: &'a Bound<'_, PyString>) -> PyResult<Cow<'a, [u8]>> {
    let mut n: ffi::Py_ssize_t = 0;
    let p = unsafe { PyUnicode_AsUTF8AndSize(s.as_ptr(), &mut n) };
    if p.is_null() {
        drop(PyErr::take(s.py()));
        return wtf8(s);
    }
    Ok(Cow::Borrowed(unsafe { std::slice::from_raw_parts(p.cast::<u8>(), n as usize) }))
}

/// `statement.strip()[:n]`.
fn stripped(py: Python<'_>, s: &Bound<'_, PyString>, n: isize) -> PyResult<W> {
    let t = s.call_method0(intern!(py, "strip"))?.get_item(pyo3::types::PySlice::new(py, 0, n, 1))?;
    Ok(wtf8(t.cast::<PyString>()?)?.into_owned())
}

#[derive(Default)]
struct SqlConn {
    /// its database files (main, attached)
    dbs: Vec<W>,
    /// a definition it ran reads the real clock (a temporary or uncommitted one included)
    own: bool,
}

/// The trace callback of one sqlite connection (`conn.set_trace_callback(SqlTrace(cap, database, uri))`): what
/// detpy knows of the connection (`_SqlConn`) and `Capture._sql_trace`. It holds no reference to the connection (a
/// cycle would delay closing it).
#[pyclass(module = "detpy._core", frozen)]
pub struct SqlTrace {
    cap: Py<CaptureCore>,
    conn: Mutex<SqlConn>,
}

#[pymethods]
impl SqlTrace {
    #[new]
    fn new(py: Python<'_>, cap: Py<CaptureCore>, database: &Bound<'_, PyAny>, uri: &Bound<'_, PyAny>) -> PyResult<Self> {
        let uri = uri.is_truthy()?;
        let main = sqlite_file(py, database, uri)?;
        Ok(SqlTrace { cap, conn: Mutex::new(SqlConn { dbs: main.into_iter().collect(), own: false }) })
    }

    /// The connection's database files.
    #[getter]
    fn dbs<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyString>>> {
        let dbs = lock(&self.conn).dbs.clone();
        dbs.iter().map(|d| from_wtf8(py, d)).collect()
    }

    fn __call__(&self, py: Python<'_>, statement: &Bound<'_, PyAny>) -> PyResult<()> {
        let cap = self.cap.bind(py);
        let core = cap.get();
        if !core.active() {
            return Ok(());
        }
        let Ok(s) = statement.cast::<PyString>() else { return Ok(()) };
        let b = text(s)?;
        if real_clock(py, &b)? {
            let ctx = core.cur(py)?;
            core.flag_with(py, ctx, b"rclock", || {
                let mut d = b"sqlite: ".to_vec();
                d.extend_from_slice(&stripped(py, s, 80)?);
                d.extend_from_slice(b" at ");
                d.extend_from_slice(&core.first_user_site(py)?);
                Ok(d)
            })?;
            if ddl(py, &b)? {
                lock(&self.conn).own = true;
            }
        }
        if let Some((q, e)) = attach(py, &b)? {
            let mut name = Vec::with_capacity(e - q);
            let inner = &b[q + 1..e - 1];
            let mut i = 0;
            while i < inner.len() {
                name.push(inner[i]);
                i += if inner[i] == b'\'' && inner.get(i + 1) == Some(&b'\'') { 2 } else { 1 };
            }
            if let Some(f) = sqlite_file_str(py, &name, true)? {
                lock(&self.conn).dbs.push(f);
            }
            return Ok(());
        }
        if no_schema(py, &b)? {
            return Ok(());
        }
        let (own, dbs) = {
            let c = lock(&self.conn);
            (c.own, if c.own { Vec::new() } else { c.dbs.clone() })
        };
        let why = if own {
            Some(b"this connection's schema".to_vec())
        } else {
            let mut why = None;
            for f in &dbs {
                why = schema_clock(py, cap, f)?;
                if why.is_some() {
                    break;
                }
            }
            why
        };
        if let Some(why) = why {
            let ctx = core.cur(py)?;
            core.flag_with(py, ctx, b"rclock", || {
                let mut d = b"sqlite: ".to_vec();
                d.extend_from_slice(&why);
                d.extend_from_slice(b" may read the real clock (");
                d.extend_from_slice(&stripped(py, s, 60)?);
                d.extend_from_slice(b") at ");
                d.extend_from_slice(&core.first_user_site(py)?);
                Ok(d)
            })?;
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------------------------------------------
// For the schema query and the tests

/// `_SQL_REAL_CLOCK.search(s) is not None`.
#[pyfunction]
fn sql_real_clock(py: Python<'_>, s: &Bound<'_, PyString>) -> PyResult<bool> {
    real_clock(py, &text(s)?)
}

/// `_SQL_NO_SCHEMA.match(s) is not None`, `_SQL_DDL.match(s) is not None`, `_SQL_ATTACH.match(s).group(1)` (for the
/// tests).
#[pyfunction]
fn sql_statement_kind<'py>(
    py: Python<'py>,
    s: &Bound<'py, PyString>,
) -> PyResult<(bool, bool, Option<Bound<'py, PyString>>)> {
    let b = wtf8(s)?;
    let a = match attach(py, &b)? {
        Some((q, e)) => Some(from_wtf8(py, &b[q..e])?),
        None => None,
    };
    Ok((no_schema(py, &b)?, ddl(py, &b)?, a))
}

/// `_sqlite_file(db, uri)` (for the tests).
#[pyfunction]
fn sqlite_file_of<'py>(py: Python<'py>, db: &Bound<'py, PyAny>, uri: bool) -> PyResult<Option<Bound<'py, PyString>>> {
    sqlite_file(py, db, uri)?.map(|w| from_wtf8(py, &w)).transpose()
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SqlTrace>()?;
    m.add_function(wrap_pyfunction!(sql_real_clock, m)?)?;
    m.add_function(wrap_pyfunction!(sql_statement_kind, m)?)?;
    m.add_function(wrap_pyfunction!(sqlite_file_of, m)?)?;
    Ok(())
}
