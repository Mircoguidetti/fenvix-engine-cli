//! The capture of the cache with proof (`detpy/proofcache.py`, class `Capture`), in Rust.
//!
//! What every test, fixture, collection and import read, wrote, executed and flagged is recorded per context while
//! the session runs. The audit hook (every `open`, module `exec`, directory listing, socket and spawn event of the
//! process), environment reads, Level 0 events and context switches used to run Python frames of `Capture`
//! (`_audit`, `_caller_kind`'s frame walk, `_abs`, `read`, `_cur`, ...); here they are one Rust call each. The
//! Python class `proofcache.Capture` subclasses `CaptureCore` and keeps what is interface: registering the
//! `sys.monitoring` callbacks and the audit hook, patching `sqlite3.connect`, the child follower.
//!
//! Port of round 1/2's Python `Capture` (kept verbatim in `tests/rust_hotpaths_ref/_ref_proofcache.py`); stores,
//! receipts and decisions are tested identical against it (`tests/test_capture_rust.py`). Same rules, same order
//! of every check, same frames walked:
//!
//! * strings that Python may hold with lone surrogates (paths decoded with `surrogateescape`, context names) are
//!   kept losslessly as their UTF-8 `surrogatepass` encoding ([`W`]) and given back to Python as the same `str`;
//! * frame walks start at the frame that raised the event: the Python methods started a fixed number of frames
//!   above themselves, which is the same frame once their own frames (gone here) are counted; detpy's own frames
//!   are skipped as before.
//!
//! Python helpers still called from here, for rare events only (a socket connect, a name lookup, a spawn): the
//! loopback-listener checks and the numeric-host test (they use `ipaddress`' parsing rules), the spawn detail and
//! the follower's `announce`.

use crate::level0::{self, Kind};
use crate::sysmon::{LineRecorder, SocketScan};
use detpy_core::proof;
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PySet, PyString, PyTuple};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::sync::{Mutex, MutexGuard};

/// A Python `str` as its UTF-8 encoding with `surrogatepass` (lossless; valid UTF-8 unless it held surrogates).
type W = Vec<u8>;

const SKIP_PARTS: [&[u8]; 6] =
    [b"/__pycache__/", b"/.git/", b"/.pytest_cache", b"/.mypy_cache", b"/.hypothesis/", b"/.detpy/"];
const SKIP_DATA: [&[u8]; 5] = [b"/__pycache__/", b"/.pytest_cache", b"/.mypy_cache", b"/.hypothesis/", b"/.detpy/"];
const WRITE_EVENTS: [(&str, &[usize]); 10] = [
    ("os.remove", &[0]),
    ("os.rename", &[0, 1]),
    ("os.mkdir", &[0]),
    ("os.rmdir", &[0]),
    ("shutil.rmtree", &[0]),
    ("shutil.copyfile", &[1]),
    ("shutil.move", &[0, 1]),
    ("os.symlink", &[1]),
    ("os.link", &[1]),
    ("os.truncate", &[0]),
];
const SPAWN: [&str; 7] = ["subprocess.Popen", "os.posix_spawn", "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn"];
const CO_OPTIMIZED: i64 = 0x1;
const CO_PLAIN_EXCLUDE: i64 = 0x20 | 0x80 | 0x100 | 0x200;

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn contains(hay: &[u8], needle: &[u8]) -> bool {
    needle.is_empty() || hay.windows(needle.len()).any(|w| w == needle)
}

/// The `os` module (attributes such as `os.getcwd` are still looked up at each use: tools patch them).
fn os_mod(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    static OS: pyo3::sync::PyOnceLock<Py<PyModule>> = pyo3::sync::PyOnceLock::new();
    Ok(OS.get_or_try_init(py, || py.import("os").map(|m| m.unbind()))?.bind(py).clone())
}

/// `w_of(s)`: the lossless bytes of a Python `str`.
fn w_of(s: &Bound<'_, PyString>) -> PyResult<W> {
    match s.to_cow() {
        Ok(t) => Ok(t.as_bytes().to_vec()),
        Err(_) => {
            let py = s.py();
            let b = s.call_method1(intern!(py, "encode"), ("utf-8", "surrogatepass"))?;
            Ok(b.cast::<PyBytes>()?.as_bytes().to_vec())
        }
    }
}

/// The Python `str` of `w`.
fn py_of<'py>(py: Python<'py>, w: &[u8]) -> PyResult<Bound<'py, PyAny>> {
    match std::str::from_utf8(w) {
        Ok(s) => Ok(PyString::new(py, s).into_any()),
        Err(_) => PyBytes::new(py, w).call_method1(intern!(py, "decode"), ("utf-8", "surrogatepass")),
    }
}

/// `os.fsencode` of the `str` `w`: valid UTF-8 as is, the escape surrogates U+DC80..U+DCFF back to their byte;
/// None for another surrogate (not encodable).
fn fs_bytes(w: &[u8]) -> Option<std::borrow::Cow<'_, [u8]>> {
    if std::str::from_utf8(w).is_ok() {
        return Some(std::borrow::Cow::Borrowed(w));
    }
    let mut out = Vec::with_capacity(w.len());
    let mut i = 0;
    while i < w.len() {
        // a surrogate's 3-byte sequence: ED A0..BF xx
        if w[i] == 0xED && i + 2 < w.len() && (0xA0..=0xBF).contains(&w[i + 1]) {
            let cp = 0xD000u32 | ((w[i + 1] as u32 & 0x3F) << 6) | (w[i + 2] as u32 & 0x3F);
            if (0xDC80..=0xDCFF).contains(&cp) {
                out.push((cp - 0xDC00) as u8);
                i += 3;
                continue;
            }
            return None;
        }
        out.push(w[i]);
        i += 1;
    }
    Some(std::borrow::Cow::Owned(out))
}

fn os_path(b: &[u8]) -> &std::path::Path {
    std::path::Path::new(std::ffi::OsStr::from_bytes(b))
}

/// `posixpath.normpath`.
pub(crate) fn normpath(path: &[u8]) -> W {
    if path.is_empty() {
        return b".".to_vec();
    }
    let mut initial = if path.starts_with(b"/") { 1 } else { 0 };
    if initial == 1 && path.starts_with(b"//") && !path.starts_with(b"///") {
        initial = 2;
    }
    let mut new: Vec<&[u8]> = Vec::new();
    for comp in path.split(|&c| c == b'/') {
        if comp.is_empty() || comp == b"." {
            continue;
        }
        if comp != b".." || (initial == 0 && new.is_empty()) || new.last() == Some(&&b".."[..]) {
            new.push(comp);
        } else if !new.is_empty() {
            new.pop();
        }
    }
    let mut out = vec![b'/'; initial];
    out.extend_from_slice(&new.join(&b'/'));
    if out.is_empty() {
        b".".to_vec()
    } else {
        out
    }
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

/// `_stat_key(path)`: `[st_size, st_mtime_ns, st_ctime_ns, st_ino]` of `os.stat`, None when it fails.
type StatKey = Option<(u64, i128, i128, u64)>;

fn stat_key(w: &[u8]) -> StatKey {
    let fsb = fs_bytes(w)?;
    let m = std::fs::metadata(os_path(&fsb)).ok()?;
    Some((
        m.size(),
        m.mtime() as i128 * 1_000_000_000 + m.mtime_nsec() as i128,
        m.ctime() as i128 * 1_000_000_000 + m.ctime_nsec() as i128,
        m.ino(),
    ))
}

fn exists(w: &[u8]) -> bool {
    fs_bytes(w).map(|b| std::fs::metadata(os_path(&b)).is_ok()).unwrap_or(false)
}

fn is_dir(w: &[u8]) -> bool {
    fs_bytes(w).map(|b| std::fs::metadata(os_path(&b)).map(|m| m.is_dir()).unwrap_or(false)).unwrap_or(false)
}

/// Insertion-ordered map (a Python dict of str -> str).
#[derive(Default, Clone)]
struct OrdMap {
    idx: HashMap<W, usize>,
    items: Vec<(W, W)>,
}

impl OrdMap {
    fn set(&mut self, k: W, v: W) {
        match self.idx.get(&k) {
            Some(&i) => self.items[i].1 = v,
            None => {
                self.idx.insert(k.clone(), self.items.len());
                self.items.push((k, v));
            }
        }
    }
}

/// Insertion-ordered set (the plan sorts sets, but the views keep Python's insertion order where it showed).
#[derive(Default, Clone)]
struct OrdSet {
    idx: HashSet<W>,
    items: Vec<W>,
}

impl OrdSet {
    /// True when added.
    fn add(&mut self, k: W) -> bool {
        if self.idx.contains(&k) {
            return false;
        }
        self.idx.insert(k.clone());
        self.items.push(k);
        true
    }
    fn has(&self, k: &[u8]) -> bool {
        self.idx.contains(k)
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Caller {
    Import,
    Infra,
    User,
}

#[derive(Default)]
struct State {
    root_sep: W,
    ctx: W,
    ctx_ix: HashMap<W, usize>,
    ctx_names: Vec<W>,
    segs: Vec<(usize, usize)>,
    wanted: HashMap<W, bool>,
    fid: HashMap<W, usize>,
    fnames: Vec<W>,
    armed: HashSet<usize>,
    events: HashMap<usize, u32>,
    preloaded: OrdSet,
    data: HashMap<usize, OrdMap>,
    data_order: Vec<usize>,
    env: HashMap<usize, OrdSet>,
    env_order: Vec<usize>,
    flags: HashMap<usize, OrdSet>,
    flags_order: Vec<usize>,
    why: HashMap<(usize, W), W>,
    writers: HashMap<W, BTreeSet<usize>>,
    writers_order: Vec<W>,
    hashed: HashMap<W, W>,
    code_stat: HashMap<W, StatKey>,
    code_stat_order: Vec<W>,
    loaded_order: Vec<(W, i64)>,
    seen_mods: HashSet<W>,
    nmods: usize,
    basetemp: Option<W>,
    site_dirs: Vec<W>,
    stdlib_dirs: Vec<W>,
    dist_info_ok: Vec<W>,
    import_ctx: i64,
    active: bool,
    children: i64,
    child_entropy: i64,
    timeline: Vec<(f64, usize)>,
}

impl State {
    fn ctx_index(&mut self, name: &[u8]) -> usize {
        if let Some(&i) = self.ctx_ix.get(name) {
            return i;
        }
        let i = self.ctx_names.len();
        self.ctx_ix.insert(name.to_vec(), i);
        self.ctx_names.push(name.to_vec());
        i
    }

    fn key<'a>(&self, p: &'a [u8]) -> &'a [u8] {
        if p.starts_with(&self.root_sep) {
            &p[self.root_sep.len()..]
        } else {
            p
        }
    }

    fn ignored(&self, p: &[u8]) -> bool {
        if SKIP_DATA.iter().any(|s| contains(p, s)) {
            return true;
        }
        if let Some(bt) = &self.basetemp {
            if p == bt.as_slice() || (p.starts_with(bt) && p.get(bt.len()) == Some(&b'/')) {
                return true;
            }
        }
        for d in &self.site_dirs {
            if p.starts_with(d) {
                return !self.dist_info_ok.iter().any(|x| p.starts_with(x));
            }
        }
        self.stdlib_dirs.iter().any(|d| p.starts_with(d)) || p == b"/dev/null"
    }

    fn flag_set(&mut self, ctx: usize) -> &mut OrdSet {
        if !self.flags.contains_key(&ctx) {
            self.flags_order.push(ctx);
        }
        self.flags.entry(ctx).or_default()
    }

    fn env_set(&mut self, ctx: usize) -> &mut OrdSet {
        if !self.env.contains_key(&ctx) {
            self.env_order.push(ctx);
        }
        self.env.entry(ctx).or_default()
    }

    /// `Capture.read` once the flag detail (if any) is known: returns Some(path) when the read is a "proc" flag
    /// whose detail is the path.
    fn read(&mut self, ctx: usize, p: &[u8], kind: u8) -> Option<W> {
        if std::str::from_utf8(p).is_err() {
            self.flag_set(ctx).add(b"badpath".to_vec());
            return None;
        }
        let mut kind = kind;
        if kind == b'm' {
            kind = b'f';
        } else if (p.starts_with(b"/proc/") || p.starts_with(b"/sys/") || p.starts_with(b"/dev/"))
            && !p.starts_with(b"/dev/shm/")
            && kind != b'd'
            && exists(p)
        {
            return Some(p.to_vec()); // flag "proc" with the path as its detail
        }
        if self.writers.contains_key(p) {
            let mut f = b"rw:".to_vec();
            f.extend_from_slice(p);
            self.flag_set(ctx).add(f);
            return None;
        }
        let mut hk = vec![kind];
        hk.extend_from_slice(p);
        let dep = match self.hashed.get(&hk) {
            Some(d) => d.clone(),
            None => {
                let path = os_path(p);
                let dep = if kind == b'd' {
                    match proof::listing_digest(path) {
                        Some(d) => format!("d:{d}").into_bytes(),
                        None => b"missing".to_vec(),
                    }
                } else {
                    match proof::file_digest(path) {
                        Some(d) => format!("f:{d}").into_bytes(),
                        None => {
                            if !exists(p) {
                                b"missing".to_vec()
                            } else if is_dir(p) {
                                b"s:dir".to_vec()
                            } else {
                                b"s:other".to_vec()
                            }
                        }
                    }
                };
                self.hashed.insert(hk, dep.clone());
                dep
            }
        };
        let k = self.key(p).to_vec();
        if !self.data.contains_key(&ctx) {
            self.data_order.push(ctx);
        }
        self.data.entry(ctx).or_default().set(k, dep);
        None
    }

    fn wrote(&mut self, ctx: usize, p: &[u8]) {
        if std::str::from_utf8(p).is_ok() {
            if !self.writers.contains_key(p) {
                self.writers_order.push(p.to_vec());
            }
            self.writers.entry(p.to_vec()).or_default().insert(ctx);
            for k in [b'f', b'd'] {
                let mut hk = vec![k];
                hk.extend_from_slice(p);
                self.hashed.remove(&hk);
            }
        }
        // a path that is not valid UTF-8 is never read (a bad path) nor recorded as written; its directory's
        // listing changed all the same
        let mut hk = vec![b'd'];
        hk.extend_from_slice(dirname(p));
        self.hashed.remove(&hk);
    }

    fn note_code(&mut self, p: W) {
        if !self.code_stat.contains_key(&p) {
            let k = stat_key(&p);
            self.code_stat_order.push(p.clone());
            self.code_stat.insert(p, k);
        }
    }
}

/// Python objects and constants of the capture.
struct Env {
    detpy_dir: W,
    resume: i64,
    prelude: Vec<u8>,
    code_level: bool,
    o_acc: i64,
    o_rdonly: i64,
    o_wronly: i64,
    o_rdwr: i64,
    o_creat: i64,
    o_excl: i64,
    o_trunc: i64,
    o_tmpfile: i64,
}

#[pyclass(module = "detpy._core", frozen, subclass, dict)]
pub struct CaptureCore {
    st: Mutex<State>,
    env: Env,
    rec: Mutex<Option<Py<LineRecorder>>>,
    tool: Mutex<Option<i64>>,
    socks: Py<SocketScan>,
    env0: Py<PyDict>,
    root: Py<PyString>,
}

/// `_sites._classify` through the Level 0 hub (its classification cache, without a Python frame) or, when the
/// Rust Level 0 path is not configured (the reference Python `_state` of the equivalence tests), through
/// `detpy._sites._classify` itself.
enum Classifier {
    Hub(std::sync::Arc<level0::Hub>),
    Py(Py<PyAny>, Py<PyAny>, Py<PyAny>),
}

impl Classifier {
    fn get(py: Python<'_>) -> PyResult<Self> {
        match level0::hub() {
            Ok(h) => Ok(Classifier::Hub(h)),
            Err(_) => {
                let sites = py.import("detpy._sites")?;
                Ok(Classifier::Py(
                    sites.getattr("_classify")?.unbind(),
                    sites.getattr("_USER")?.unbind(),
                    sites.getattr("_INFRA")?.unbind(),
                ))
            }
        }
    }

    fn classify(&self, py: Python<'_>, fname: &Bound<'_, PyAny>) -> PyResult<(Kind, Result<String, ()>)> {
        match self {
            Classifier::Hub(h) => h.classify(py, fname),
            Classifier::Py(f, user, infra) => {
                let t = f.bind(py).call1((fname,))?;
                let k = t.get_item(0)?;
                let kind = if k.eq(user.bind(py))? {
                    Kind::User
                } else if k.eq(infra.bind(py))? {
                    Kind::Infra
                } else {
                    Kind::Stdlib
                };
                let n = t.get_item(1)?;
                let norm = match n.cast::<PyString>() {
                    Ok(s) => s.to_cow().map(|c| c.into_owned()).map_err(|_| ()),
                    Err(_) => Ok(n.str()?.to_cow()?.into_owned()),
                };
                Ok((kind, norm))
            }
        }
    }
}

/// The current frame (the code that raised the event or called the patched API), if any.
fn current_frame(py: Python<'_>) -> Option<Bound<'_, PyAny>> {
    let p = unsafe { ffi::PyEval_GetFrame() };
    if p.is_null() {
        None
    } else {
        Some(unsafe { Bound::from_borrowed_ptr(py, p.cast()) })
    }
}

fn code_filename<'py>(f: &Bound<'py, PyAny>) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyAny>)> {
    let py = f.py();
    let code = f.getattr(intern!(py, "f_code"))?;
    let fname = code.getattr(intern!(py, "co_filename"))?;
    Ok((code, fname))
}

fn starts_with_str(o: &Bound<'_, PyAny>, prefix: &[u8]) -> bool {
    match o.cast::<PyString>() {
        Ok(s) => match s.to_cow() {
            Ok(t) => t.as_bytes().starts_with(prefix),
            Err(_) => w_of(s).map(|w| w.starts_with(prefix)).unwrap_or(false),
        },
        Err(_) => false,
    }
}

fn ends_with_str(o: &Bound<'_, PyAny>, suffix: &[u8]) -> bool {
    match o.cast::<PyString>() {
        Ok(s) => w_of(s).map(|w| w.ends_with(suffix)).unwrap_or(false),
        Err(_) => false,
    }
}

fn int_of(o: &Bound<'_, PyAny>) -> i64 {
    if o.is_none() {
        return 0;
    }
    o.extract::<i64>().unwrap_or(0)
}

fn now() -> f64 {
    let d = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
    d.as_secs() as f64 + d.subsec_nanos() as f64 * 1e-9
}

impl CaptureCore {
    fn recorder(&self, py: Python<'_>) -> Option<Py<LineRecorder>> {
        lock(&self.rec).as_ref().map(|r| r.clone_ref(py))
    }

    fn import_depth(&self, py: Python<'_>) -> u32 {
        self.recorder(py).map(|r| r.bind(py).get().depth()).unwrap_or(0)
    }

    /// `Capture._want(filename)`.
    fn want(&self, py: Python<'_>, filename: &Bound<'_, PyAny>) -> PyResult<bool> {
        let Ok(fs) = filename.cast::<PyString>() else { return Ok(false) };
        let k = w_of(fs)?;
        if let Some(&w) = lock(&self.st).wanted.get(&k) {
            return Ok(w);
        }
        let mut w = false;
        let mut rel = None;
        if !k.is_empty() && !k.starts_with(b"<") {
            let os = os_mod(py)?;
            let path = os.getattr(intern!(py, "path"))?;
            let p = match path
                .getattr(intern!(py, "abspath"))?
                .call1((fs,))
                .and_then(|a| path.getattr(intern!(py, "realpath"))?.call1((a,)))
            {
                Ok(p) => w_of(p.cast::<PyString>()?)?,
                Err(e) if e.is_instance_of::<pyo3::exceptions::PyOSError>(py)
                    || e.is_instance_of::<pyo3::exceptions::PyValueError>(py) =>
                {
                    Vec::new()
                }
                Err(e) => return Err(e),
            };
            let st = lock(&self.st);
            w = p.starts_with(&st.root_sep) && !SKIP_PARTS.iter().any(|s| contains(&p, s));
            if w {
                rel = Some(p[st.root_sep.len()..].to_vec());
            }
        }
        let mut st = lock(&self.st);
        if let Some(&w0) = st.wanted.get(&k) {
            return Ok(w0); // decided meanwhile (a nested call)
        }
        if let Some(r) = rel {
            let n = st.fnames.len();
            st.fid.insert(k.clone(), n);
            st.fnames.push(r);
        }
        st.wanted.insert(k, w);
        Ok(w)
    }

    /// `Capture._caller_kind()` from the frame that raised the event.
    fn caller_kind(&self, py: Python<'_>) -> PyResult<Caller> {
        let hub = Classifier::get(py)?;
        let mut f = current_frame(py);
        while let Some(fr) = f {
            let (_code, fname) = code_filename(&fr)?;
            if starts_with_str(&fname, b"<frozen importlib") || starts_with_str(&fname, b"<frozen zipimport") {
                return Ok(Caller::Import);
            }
            if starts_with_str(&fname, &self.env.detpy_dir) {
                f = level0::back(&fr)?;
                continue;
            }
            match hub.classify(py, &fname)?.0 {
                Kind::User => return Ok(Caller::User),
                Kind::Infra => return Ok(Caller::Infra),
                Kind::Stdlib => {}
            }
            f = level0::back(&fr)?;
        }
        Ok(Caller::User)
    }

    /// `Capture._cur()`.
    fn cur(&self, py: Python<'_>) -> PyResult<usize> {
        if self.import_depth(py) > 0 {
            return self.import_ctx_of_frames(py);
        }
        let mut st = lock(&self.st);
        let c = st.ctx.clone();
        Ok(st.ctx_index(&c))
    }

    /// `Capture._import_ctx()`: the innermost repository module body running.
    fn import_ctx_of_frames(&self, py: Python<'_>) -> PyResult<usize> {
        let mut f = current_frame(py);
        while let Some(fr) = f {
            let (code, fname) = code_filename(&fr)?;
            let name = code.getattr(intern!(py, "co_name"))?;
            if name.eq("<module>")? && self.want(py, &fname)? {
                let k = w_of(fname.cast::<PyString>()?)?;
                let mut st = lock(&self.st);
                let fid = st.fid[&k];
                let mut c = b"i|".to_vec();
                c.extend_from_slice(&st.fnames[fid]);
                return Ok(st.ctx_index(&c));
            }
            f = level0::back(&fr)?;
        }
        let st = lock(&self.st);
        Ok(st.import_ctx.max(0) as usize)
    }

    /// `_first_user_site()`: `file:line` of the innermost frame outside detpy and the standard library.
    fn first_user_site(&self, py: Python<'_>) -> PyResult<W> {
        let hub = Classifier::get(py)?;
        let mut f = current_frame(py);
        let mut first: Option<W> = None;
        while let Some(fr) = f {
            let (_code, fname) = code_filename(&fr)?;
            if !starts_with_str(&fname, &self.env.detpy_dir) {
                let (kind, norm) = hub.classify(py, &fname)?;
                let site = match norm {
                    Ok(n) => level0::site_of(&fr, &n)?.into_bytes(),
                    Err(()) => {
                        // a path with surrogates: as Python formats it
                        let norm = py.import("detpy._sites")?.getattr("_classify")?.call1((&fname,))?.get_item(1)?;
                        let line = fr.getattr(intern!(py, "f_lineno"))?;
                        let s = PyString::new(py, "{}:{}").call_method1("format", (norm, line))?;
                        w_of(s.cast::<PyString>()?)?
                    }
                };
                if first.is_none() {
                    first = Some(site.clone());
                }
                if kind == Kind::User {
                    return Ok(site);
                }
            }
            f = level0::back(&fr)?;
        }
        Ok(first.unwrap_or_else(|| b"?".to_vec()))
    }

    /// `_called_from(suffix)` from the frame that raised the event.
    fn called_from(&self, py: Python<'_>, suffix: &[u8]) -> PyResult<bool> {
        let hub = Classifier::get(py)?;
        let mut f = current_frame(py);
        while let Some(fr) = f {
            let (_code, fname) = code_filename(&fr)?;
            if ends_with_str(&fname, suffix) && hub.classify(py, &fname)?.0 != Kind::User {
                return Ok(true);
            }
            f = level0::back(&fr)?;
        }
        Ok(false)
    }

    /// `_is_find_library_ldconfig(args)`.
    fn is_find_library_ldconfig(&self, py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<bool> {
        let argv = if args.len() > 1 {
            let a1 = args.get_item(1)?;
            if a1.is_instance_of::<PyString>() || a1.is_instance_of::<PyBytes>() {
                None
            } else {
                match py.import("builtins")?.getattr("list")?.call1((a1,)) {
                    Ok(l) => Some(l),
                    Err(e) if e.is_instance_of::<pyo3::exceptions::PyTypeError>(py) => return Ok(false),
                    Err(e) => return Err(e),
                }
            }
        } else {
            None
        };
        let Some(argv) = argv else { return Ok(false) };
        let argv = argv.cast::<PyList>()?;
        if argv.len() != 2 {
            return Ok(false);
        }
        let os = os_mod(py)?;
        let a0 = os.getattr("fsdecode")?.call1((argv.get_item(0)?,))?;
        let base = os.getattr("path")?.getattr("basename")?.call1((a0,))?;
        if !base.eq("ldconfig")? || !argv.get_item(1)?.eq("-p")? {
            return Ok(false);
        }
        let mut f = current_frame(py);
        while let Some(fr) = f {
            let (_code, fname) = code_filename(&fr)?;
            if ends_with_str(&fname, b"/ctypes/util.py") {
                return Ok(true);
            }
            f = level0::back(&fr)?;
        }
        Ok(false)
    }

    /// `Capture._abs(p)`.
    fn abs(&self, py: Python<'_>, p: &Bound<'_, PyAny>) -> PyResult<Option<W>> {
        if p.is_none() || p.is_instance_of::<pyo3::types::PyInt>() {
            return Ok(None);
        }
        let os = os_mod(py)?;
        // os.fsdecode(os.fspath(p)): a str is itself (no call)
        let s = match if p.is_exact_instance_of::<PyString>() { Ok(p.clone()) } else { os.getattr(intern!(py, "fspath"))?.call1((p,)).and_then(|x| os.getattr(intern!(py, "fsdecode"))?.call1((x,))) } {
            Ok(s) => s,
            Err(e) if e.is_instance_of::<pyo3::exceptions::PyTypeError>(py)
                || e.is_instance_of::<pyo3::exceptions::PyValueError>(py) =>
            {
                return Ok(None)
            }
            Err(e) => return Err(e),
        };
        let Ok(s) = s.cast::<PyString>() else { return Ok(None) };
        let mut w = w_of(s)?;
        if w.is_empty() {
            return Ok(None);
        }
        if !w.starts_with(b"/") {
            let cwd = match os.getattr(intern!(py, "getcwd"))?.call0() {
                Ok(c) => w_of(c.cast::<PyString>()?)?,
                Err(e) if e.is_instance_of::<pyo3::exceptions::PyOSError>(py) => return Ok(None),
                Err(e) => return Err(e),
            };
            // posixpath.join(cwd, s)
            let mut j = cwd;
            if !(j.is_empty() || j.ends_with(b"/")) {
                j.push(b'/');
            }
            j.extend_from_slice(&w);
            w = j;
        }
        Ok(Some(normpath(&w)))
    }

    /// `Capture.flag(ctx, flag, detail)`; `detail` None: the first user site.
    fn flag_impl(&self, py: Python<'_>, ctx: usize, flag: &[u8], detail: Option<W>) -> PyResult<()> {
        let new = {
            let st = lock(&self.st);
            !st.flags.get(&ctx).map(|f| f.has(flag)).unwrap_or(false)
        };
        if !new {
            return Ok(());
        }
        let detail = match detail {
            Some(d) => d,
            None => self.first_user_site(py)?,
        };
        let mut st = lock(&self.st);
        if st.flag_set(ctx).add(flag.to_vec()) {
            st.why.insert((ctx, flag.to_vec()), detail);
        }
        Ok(())
    }

    fn read_impl(&self, py: Python<'_>, ctx: usize, p: &[u8], kind: u8) -> PyResult<()> {
        let proc = lock(&self.st).read(ctx, p, kind);
        if let Some(detail) = proc {
            self.flag_impl(py, ctx, b"proc", Some(detail))?;
        }
        Ok(())
    }

    fn wrote_impl(&self, ctx: usize, p: &[u8]) {
        lock(&self.st).wrote(ctx, p);
    }

    fn ignored(&self, p: &[u8]) -> bool {
        lock(&self.st).ignored(p)
    }

    fn active(&self) -> bool {
        lock(&self.st).active
    }

    fn set_active(&self, v: bool) {
        lock(&self.st).active = v;
    }

    /// Call a Python helper of `detpy.proofcache` with the capture inactive (its own reads are not inputs).
    fn helper_inactive(&self, py: Python<'_>, name: &str, arg: &Bound<'_, PyAny>) -> PyResult<bool> {
        let f = py.import("detpy.proofcache")?.getattr(name)?;
        let was = self.active();
        self.set_active(false);
        let r = f.call1((arg,));
        self.set_active(was);
        r?.is_truthy()
    }

    fn audit_impl(&self, py: Python<'_>, slf: &Bound<'_, PyAny>, event: &str, args: &Bound<'_, PyTuple>) -> PyResult<()> {
        if !self.active() {
            return Ok(());
        }
        let arg = |i: usize| -> Option<Bound<'_, PyAny>> { args.get_item(i).ok() };
        match event {
            "exec" => {
                let Some(code) = arg(0) else { return Ok(()) };
                if !code.is_instance_of::<pyo3::types::PyCode>() {
                    return Ok(());
                }
                let name = code.getattr(intern!(py, "co_name"))?;
                let fname = code.getattr(intern!(py, "co_filename"))?;
                if name.eq("<module>")? && self.want(py, &fname)? {
                    if let Some(p) = self.abs(py, &fname)? {
                        lock(&self.st).note_code(p);
                    }
                }
                let armed = lock(&self.st).armed.contains(&(code.as_ptr() as usize));
                if !armed && lock(&self.tool).is_some() {
                    self.arm_impl(py, &code)?;
                }
                Ok(())
            }
            "open" => {
                let Some(p) = self.abs(py, &arg(0).unwrap_or_else(|| py.None().into_bound(py)))? else { return Ok(()) };
                let mode = arg(1).filter(|m| !m.is_none());
                let flags_o = arg(2);
                let mode_s: Option<String> =
                    mode.as_ref().and_then(|m| m.cast::<PyString>().ok().map(|s| s.to_string_lossy().into_owned()));
                let flags_int = flags_o.as_ref().filter(|f| f.is_instance_of::<pyo3::types::PyInt>()).map(int_of);
                {
                    let mut st = lock(&self.st);
                    if p.ends_with(b".py") && p.starts_with(&st.root_sep) && !st.code_stat.contains_key(&p) {
                        let ro = match &mode_s {
                            Some(m) => m.contains('r') && !m.contains('+'),
                            None => flags_int.map(|f| f & self.env.o_acc == self.env.o_rdonly).unwrap_or(false),
                        };
                        if ro {
                            // before the read: the source the import system (or pytest's rewrite, runpy...) reads
                            st.note_code(p.clone());
                        }
                    }
                    if st.ignored(&p) {
                        return Ok(());
                    }
                }
                let fl = flags_int.unwrap_or(0);
                if self.env.o_tmpfile != 0 && flags_int.is_some() && fl & self.env.o_tmpfile == self.env.o_tmpfile {
                    return Ok(());
                }
                let (reads, writes, trunc) = match &mode_s {
                    Some(m) => (
                        m.contains('r') || m.contains('+'),
                        m.chars().any(|c| "wax+".contains(c)),
                        m.contains('w') || m.contains('x'),
                    ),
                    None => {
                        let f = flags_o.as_ref().map(int_of).unwrap_or(0);
                        let e = &self.env;
                        let acc = f & e.o_acc;
                        (
                            acc == e.o_rdonly || acc == e.o_rdwr,
                            acc == e.o_wronly || acc == e.o_rdwr || f & e.o_creat != 0,
                            f & e.o_trunc != 0 || f & (e.o_creat | e.o_excl) == (e.o_creat | e.o_excl),
                        )
                    }
                };
                let kind = self.caller_kind(py)?;
                if kind != Caller::User {
                    return Ok(());
                }
                let ctx = self.cur(py)?;
                if reads && !trunc {
                    self.read_impl(py, ctx, &p, b'f')?;
                }
                if writes {
                    self.wrote_impl(ctx, &p);
                }
                Ok(())
            }
            "sqlite3.connect" => {
                let Some(db) = arg(0) else { return Ok(()) };
                let os = os_mod(py)?;
                let pathlike = os.getattr("PathLike")?;
                if !(db.is_instance_of::<PyString>() || db.is_instance_of::<PyBytes>() || db.is_instance(&pathlike)?) {
                    return Ok(());
                }
                let dec = os.getattr("fsdecode")?.call1((&db,))?;
                if dec.eq("")? || dec.eq(":memory:")? || dec.call_method1("startswith", ("file:",))?.is_truthy()? {
                    return Ok(());
                }
                let Some(p) = self.abs(py, &db)? else { return Ok(()) };
                if self.ignored(&p) || self.caller_kind(py)? != Caller::User {
                    return Ok(());
                }
                let ctx = self.cur(py)?;
                self.read_impl(py, ctx, &p, b'f')?;
                self.wrote_impl(ctx, &p);
                Ok(())
            }
            "os.listdir" | "os.scandir" => {
                if self.caller_kind(py)? != Caller::User {
                    return Ok(());
                }
                let a0 = match arg(0) {
                    Some(a) if !a.is_none() => a,
                    _ => PyString::new(py, ".").into_any(),
                };
                let Some(p) = self.abs(py, &a0)? else { return Ok(()) };
                if self.ignored(&p) {
                    return Ok(());
                }
                let ctx = self.cur(py)?;
                self.read_impl(py, ctx, &p, b'd')
            }
            "socket.connect" | "socket.sendto" | "socket.sendmsg" => {
                if self.caller_kind(py)? == Caller::Infra {
                    return Ok(());
                }
                if event == "socket.sendmsg"
                    && args.len() > 1
                    && args.get_item(1)?.is_none()
                    && self.helper_inactive(py, "_both_ends_mine", &args.get_item(0)?)?
                {
                    return Ok(());
                }
                if event == "socket.connect" && self.helper_inactive(py, "_own_listener", args.as_any())? {
                    return Ok(());
                }
                let addr = py.import("detpy.proofcache")?.getattr("_addr")?.call1((args,))?;
                let site = self.first_user_site(py)?;
                let mut d = format!("{event} ").into_bytes();
                d.extend_from_slice(&w_of(addr.str()?.as_any().cast::<PyString>()?)?);
                d.extend_from_slice(b" at ");
                d.extend_from_slice(&site);
                let ctx = self.cur(py)?;
                self.flag_impl(py, ctx, b"connect", Some(d))
            }
            "socket.getaddrinfo" | "socket.gethostbyname" | "socket.gethostbyaddr" => {
                let Some(mut host) = arg(0) else { return Ok(()) };
                if let Ok(b) = host.cast::<PyBytes>() {
                    host = b.call_method1("decode", ("ascii", "replace"))?;
                }
                let Ok(hs) = host.cast::<PyString>() else { return Ok(()) };
                if hs.len()? == 0
                    || py.import("detpy.proofcache")?.getattr("_numeric_host")?.call1((hs,))?.is_truthy()?
                    || self.caller_kind(py)? == Caller::Infra
                {
                    return Ok(());
                }
                let site = self.first_user_site(py)?;
                let mut d = format!("{event} ").into_bytes();
                d.extend_from_slice(&w_of(hs)?);
                d.extend_from_slice(b" at ");
                d.extend_from_slice(&site);
                let ctx = self.cur(py)?;
                self.flag_impl(py, ctx, b"dns", Some(d))
            }
            _ if SPAWN.contains(&event) || event.starts_with("os.spawn") || event.starts_with("os.exec") => {
                if self.caller_kind(py)? == Caller::Infra {
                    return Ok(());
                }
                let fo = slf.getattr(intern!(py, "follower"))?;
                let fo = if fo.is_none() { None } else { Some(fo) };
                let pc = py.import("detpy.proofcache")?;
                if event == "subprocess.Popen" && self.is_find_library_ldconfig(py, args)? {
                    let ctx = self.cur(py)?;
                    self.read_impl(py, ctx, b"/etc/ld.so.cache", b'f')?;
                    if let Some(fo) = &fo {
                        let ctx = self.cur(py)?;
                        fo.call_method1("announce", (ctx, py.None(), false))?;
                    }
                    return Ok(());
                }
                if event == "subprocess.Popen" && self.called_from(py, b"/uuid.py")? {
                    let ctx = self.cur(py)?;
                    self.read_impl(py, ctx, b"/sys/class/net", b'd')?;
                    if let Ok(rd) = std::fs::read_dir("/sys/class/net") {
                        let mut names: Vec<W> = rd.flatten().map(|e| e.file_name().as_bytes().to_vec()).collect();
                        names.sort();
                        for n in names {
                            let mut p = b"/sys/class/net/".to_vec();
                            p.extend_from_slice(&n);
                            p.extend_from_slice(b"/address");
                            self.read_impl(py, ctx, &p, b'm')?;
                        }
                    }
                    if let Some(fo) = &fo {
                        fo.call_method1("announce", (ctx, py.None(), false))?;
                    }
                    return Ok(());
                }
                if event == "subprocess.Popen" {
                    if let Some(fo) = &fo {
                        let ctx = self.cur(py)?;
                        let detail = pc.getattr("_spawn_detail")?.call1((event, args))?;
                        let exempt = self.called_from(py, b"/ctypes/util.py")?;
                        fo.call_method1("announce", (ctx, detail, true, exempt))?;
                        return Ok(());
                    }
                }
                let ctx = self.cur(py)?;
                let detail = pc.getattr("_spawn_detail")?.call1((event, args))?;
                self.flag_impl(py, ctx, b"spawn", Some(w_of(detail.cast::<PyString>()?)?))
            }
            _ => {
                let Some((_, idx)) = WRITE_EVENTS.iter().find(|(e, _)| *e == event) else { return Ok(()) };
                if self.caller_kind(py)? == Caller::Infra {
                    return Ok(());
                }
                let ctx = self.cur(py)?;
                for &i in idx.iter() {
                    let a = arg(i).unwrap_or_else(|| py.None().into_bound(py));
                    if let Some(p) = self.abs(py, &a)? {
                        if !self.ignored(&p) {
                            self.wrote_impl(ctx, &p);
                        }
                    }
                }
                Ok(())
            }
        }
    }

    /// `entry_line(code)`: the line `LINE` alone never reports on entry.
    fn entry_line(&self, py: Python<'_>, code: &Bound<'_, PyAny>) -> PyResult<Option<i64>> {
        let co = code.getattr(intern!(py, "co_code"))?;
        let co = co.cast::<PyBytes>()?.as_bytes();
        let mut r = 0usize;
        while r < co.len() && self.env.prelude.contains(&co[r]) {
            r += 2;
        }
        if r + 2 >= co.len() || co[r] as i64 != self.env.resume {
            return Ok(None);
        }
        let (mut lr, mut ln): (Option<Option<i64>>, Option<Option<i64>>) = (None, None);
        for item in code.call_method0(intern!(py, "co_lines"))?.try_iter()? {
            let t = item?;
            let t = t.cast::<PyTuple>()?;
            let start: usize = t.get_item(0)?.extract()?;
            let end: usize = t.get_item(1)?.extract()?;
            let line: Option<i64> = t.get_item(2)?.extract()?;
            if start <= r && r < end {
                lr = Some(line);
            }
            if start <= r + 2 && r + 2 < end {
                ln = Some(line);
                break;
            }
        }
        // `ln if ln is not None and ln == lr else None` (lr/ln: the line of the matching range, None when no range)
        let ln = ln.flatten();
        let lr = lr.flatten();
        Ok(match ln {
            Some(l) if Some(l) == lr => Some(l),
            _ => None,
        })
    }

    /// `rep_line(code)`: code-object level capture's line (the function's last line).
    fn rep_line(&self, py: Python<'_>, code: &Bound<'_, PyAny>) -> PyResult<Option<i64>> {
        let co = code.getattr(intern!(py, "co_code"))?;
        let co = co.cast::<PyBytes>()?.as_bytes();
        let mut r = 0usize;
        while r < co.len() && self.env.prelude.contains(&co[r]) {
            r += 2;
        }
        if r >= co.len() || co[r] as i64 != self.env.resume {
            return Ok(None);
        }
        let mut best: Option<i64> = None;
        for item in code.call_method0(intern!(py, "co_lines"))?.try_iter()? {
            let t = item?;
            let t = t.cast::<PyTuple>()?;
            let start: usize = t.get_item(0)?.extract()?;
            let line: Option<i64> = t.get_item(2)?.extract()?;
            if start > r {
                if let Some(l) = line {
                    best = Some(best.map_or(l, |b| b.max(l)));
                }
            }
        }
        Ok(best)
    }

    /// `Capture.arm(code)`.
    fn arm_impl(&self, py: Python<'_>, code: &Bound<'_, PyAny>) -> PyResult<()> {
        let Some(tool) = *lock(&self.tool) else { return Ok(()) };
        let Some(rec) = self.recorder(py) else { return Ok(()) };
        let rec = rec.bind(py);
        let mon = py.import("sys")?.getattr("monitoring")?;
        let set_local = mon.getattr("set_local_events")?;
        let events = mon.getattr("events")?;
        let line_ev: u32 = events.getattr("LINE")?.extract()?;
        let start_ev: u32 = events.getattr("PY_START")?.extract()?;
        let ret_ev: u32 = events.getattr("PY_RETURN")?.extract()?;
        let mut stack = vec![code.clone()];
        while let Some(c) = stack.pop() {
            let id = c.as_ptr() as usize;
            if lock(&self.st).armed.contains(&id) {
                continue;
            }
            let fname = c.getattr(intern!(py, "co_filename"))?;
            if !self.want(py, &fname)? {
                continue;
            }
            lock(&self.st).armed.insert(id);
            let e = self.entry_line(py, &c)?;
            let module = c.getattr(intern!(py, "co_name"))?.eq("<module>")?;
            let fid = {
                let k = w_of(fname.cast::<PyString>()?)?;
                lock(&self.st).fid[&k]
            };
            let nested = || -> PyResult<Vec<Bound<'_, PyAny>>> {
                let consts = c.getattr(intern!(py, "co_consts"))?;
                let mut out = Vec::new();
                for k in consts.try_iter()? {
                    let k = k?;
                    if k.is_instance_of::<pyo3::types::PyCode>() {
                        out.push(k);
                    }
                }
                Ok(out)
            };
            let flags: i64 = c.getattr(intern!(py, "co_flags"))?.extract()?;
            if self.env.code_level && !module && flags & CO_OPTIMIZED != 0 && flags & CO_PLAIN_EXCLUDE == 0 {
                if let Some(rep) = self.rep_line(py, &c)? {
                    lock(&self.st).events.insert(id, start_ev);
                    rec.call_method1("add_code", (&c, fid, -1i64, false, rep))?;
                    set_local.call1((tool, &c, start_ev))?;
                    stack.extend(nested()?);
                    continue;
                }
            }
            let mut ev = line_ev;
            if e.is_some() || module {
                ev |= start_ev;
            }
            if module {
                ev |= ret_ev;
            }
            lock(&self.st).events.insert(id, ev);
            rec.call_method1("add_code", (&c, fid, e.unwrap_or(-1), module))?;
            set_local.call1((tool, &c, ev))?;
            stack.extend(nested()?);
        }
        Ok(())
    }

    fn view_set<'py>(py: Python<'py>, s: &OrdSet) -> PyResult<Bound<'py, PySet>> {
        let out = PySet::empty(py)?;
        for k in &s.items {
            out.add(py_of(py, k)?)?;
        }
        Ok(out)
    }
}

#[pymethods]
impl CaptureCore {
    #[new]
    #[pyo3(signature = (root, env0, hot, detpy_dir, resume, prelude, code_level, o_flags))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        root: Bound<'_, PyString>,
        env0: Py<PyDict>,
        hot: u32,
        detpy_dir: Bound<'_, PyString>,
        resume: i64,
        prelude: Vec<u8>,
        code_level: bool,
        o_flags: (i64, i64, i64, i64, i64, i64, i64),
    ) -> PyResult<Self> {
        let _ = hot;
        let mut root_sep = w_of(&root)?;
        root_sep.push(b'/');
        let st = State {
            root_sep,
            ctx: Vec::new(),
            ctx_ix: HashMap::from([(Vec::new(), 0usize)]),
            ctx_names: vec![Vec::new()],
            segs: vec![(0, 0)],
            import_ctx: -1,
            timeline: vec![(now(), 0)],
            ..Default::default()
        };
        let (o_rdonly, o_wronly, o_rdwr, o_creat, o_excl, o_trunc, o_tmpfile) = o_flags;
        Ok(CaptureCore {
            st: Mutex::new(st),
            env: Env {
                detpy_dir: w_of(&detpy_dir)?,
                resume,
                prelude,
                code_level,
                o_acc: o_rdonly | o_wronly | o_rdwr,
                o_rdonly,
                o_wronly,
                o_rdwr,
                o_creat,
                o_excl,
                o_trunc,
                o_tmpfile,
            },
            rec: Mutex::new(None),
            tool: Mutex::new(None),
            socks: Py::new(py, SocketScan::create())?,
            env0,
            root: root.unbind(),
        })
    }

    // -- attributes ---------------------------------------------------------------------------------------------
    #[getter]
    fn root(&self, py: Python<'_>) -> Py<PyString> {
        self.root.clone_ref(py)
    }
    #[getter]
    fn root_sep<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        py_of(py, &lock(&self.st).root_sep)
    }
    #[getter]
    fn env0(&self, py: Python<'_>) -> Py<PyDict> {
        self.env0.clone_ref(py)
    }
    #[getter]
    fn ctx<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        py_of(py, &lock(&self.st).ctx)
    }
    #[getter(active)]
    fn get_active(&self) -> bool {
        self.active()
    }
    #[setter(active)]
    fn put_active(&self, v: bool) {
        self.set_active(v);
    }
    #[getter]
    fn rec(&self, py: Python<'_>) -> Option<Py<LineRecorder>> {
        self.recorder(py)
    }
    #[setter(rec)]
    fn put_rec(&self, r: Option<Py<LineRecorder>>) {
        *lock(&self.rec) = r;
    }
    #[getter]
    fn tool(&self) -> Option<i64> {
        *lock(&self.tool)
    }
    #[setter(tool)]
    fn put_tool(&self, t: Option<i64>) {
        *lock(&self.tool) = t;
    }
    #[getter]
    fn import_ctx(&self) -> i64 {
        lock(&self.st).import_ctx
    }
    #[setter(import_ctx)]
    fn put_import_ctx(&self, v: i64) {
        lock(&self.st).import_ctx = v;
    }
    #[getter]
    fn basetemp<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        lock(&self.st).basetemp.as_ref().map(|b| py_of(py, b)).transpose()
    }
    #[setter(basetemp)]
    fn put_basetemp(&self, v: Option<Bound<'_, PyString>>) -> PyResult<()> {
        lock(&self.st).basetemp = v.map(|s| w_of(&s)).transpose()?;
        Ok(())
    }
    #[getter]
    fn site_dirs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let v: Vec<Bound<'py, PyAny>> = lock(&self.st).site_dirs.iter().map(|d| py_of(py, d)).collect::<PyResult<_>>()?;
        PyTuple::new(py, v)
    }
    #[setter(site_dirs)]
    fn put_site_dirs(&self, v: Vec<Bound<'_, PyString>>) -> PyResult<()> {
        lock(&self.st).site_dirs = v.iter().map(w_of).collect::<PyResult<_>>()?;
        Ok(())
    }
    #[getter]
    fn stdlib_dirs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let v: Vec<Bound<'py, PyAny>> = lock(&self.st).stdlib_dirs.iter().map(|d| py_of(py, d)).collect::<PyResult<_>>()?;
        PyTuple::new(py, v)
    }
    #[setter(stdlib_dirs)]
    fn put_stdlib_dirs(&self, v: Vec<Bound<'_, PyString>>) -> PyResult<()> {
        lock(&self.st).stdlib_dirs = v.iter().map(w_of).collect::<PyResult<_>>()?;
        Ok(())
    }
    #[getter]
    fn dist_info_ok<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let v: Vec<Bound<'py, PyAny>> = lock(&self.st).dist_info_ok.iter().map(|d| py_of(py, d)).collect::<PyResult<_>>()?;
        PyTuple::new(py, v)
    }
    #[setter(dist_info_ok)]
    fn put_dist_info_ok(&self, v: Vec<Bound<'_, PyString>>) -> PyResult<()> {
        lock(&self.st).dist_info_ok = v.iter().map(w_of).collect::<PyResult<_>>()?;
        Ok(())
    }
    #[getter]
    fn children(&self) -> i64 {
        lock(&self.st).children
    }
    #[setter(children)]
    fn put_children(&self, v: i64) {
        lock(&self.st).children = v;
    }
    #[getter]
    fn child_entropy(&self) -> i64 {
        lock(&self.st).child_entropy
    }
    #[setter(child_entropy)]
    fn put_child_entropy(&self, v: i64) {
        lock(&self.st).child_entropy = v;
    }
    #[getter]
    fn ctx_names<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let st = lock(&self.st);
        let v: Vec<Bound<'py, PyAny>> = st.ctx_names.iter().map(|n| py_of(py, n)).collect::<PyResult<_>>()?;
        PyList::new(py, v)
    }
    #[getter]
    fn ctx_ix<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let d = PyDict::new(py);
        for (i, n) in st.ctx_names.iter().enumerate() {
            d.set_item(py_of(py, n)?, i)?;
        }
        Ok(d)
    }
    #[getter]
    fn segs(&self) -> Vec<(usize, usize)> {
        lock(&self.st).segs.clone()
    }
    #[getter]
    fn fnames<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let st = lock(&self.st);
        let v: Vec<Bound<'py, PyAny>> = st.fnames.iter().map(|n| py_of(py, n)).collect::<PyResult<_>>()?;
        PyList::new(py, v)
    }
    #[getter]
    fn preloaded<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PySet>> {
        Self::view_set(py, &lock(&self.st).preloaded)
    }
    #[getter]
    fn loaded_order<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let st = lock(&self.st);
        let v: Vec<Bound<'py, PyTuple>> = st
            .loaded_order
            .iter()
            .map(|(r, i)| PyTuple::new(py, [py_of(py, r)?, i.into_pyobject(py)?.into_any()]))
            .collect::<PyResult<_>>()?;
        PyList::new(py, v)
    }
    /// `{ctx: {path key: dep}}` (insertion order).
    #[getter]
    fn data<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let out = PyDict::new(py);
        for c in &st.data_order {
            let d = PyDict::new(py);
            for (k, v) in &st.data[c].items {
                d.set_item(py_of(py, k)?, py_of(py, v)?)?;
            }
            out.set_item(c, d)?;
        }
        Ok(out)
    }
    /// `{ctx: {names}}`.
    #[getter]
    fn env<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let out = PyDict::new(py);
        for c in &st.env_order {
            out.set_item(c, Self::view_set(py, &st.env[c])?)?;
        }
        Ok(out)
    }
    /// `{ctx: {flags}}`.
    #[getter]
    fn flags<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let out = PyDict::new(py);
        for c in &st.flags_order {
            out.set_item(c, Self::view_set(py, &st.flags[c])?)?;
        }
        Ok(out)
    }
    /// `{(ctx, flag): detail}`.
    #[getter]
    fn why<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let out = PyDict::new(py);
        for ((c, f), d) in &st.why {
            out.set_item((c, py_of(py, f)?), py_of(py, d)?)?;
        }
        Ok(out)
    }
    /// `{abs path: {writer contexts}}` (UTF-8 paths: the only ones the record uses).
    #[getter]
    fn writers<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let st = lock(&self.st);
        let out = PyDict::new(py);
        for p in &st.writers_order {
            let s = PySet::empty(py)?;
            for c in &st.writers[p] {
                s.add(c)?;
            }
            out.set_item(py_of(py, p)?, s)?;
        }
        Ok(out)
    }

    // -- contexts -------------------------------------------------------------------------------------------------
    fn ctx_index(&self, name: Bound<'_, PyString>) -> PyResult<usize> {
        let w = w_of(&name)?;
        Ok(lock(&self.st).ctx_index(&w))
    }

    /// `Capture.switch(name)`.
    fn switch(&self, py: Python<'_>, name: Bound<'_, PyString>) -> PyResult<()> {
        let w = w_of(&name)?;
        let (same, active, old) = {
            let st = lock(&self.st);
            (st.ctx == w, st.active, st.ctx.clone())
        };
        if same {
            return Ok(());
        }
        if active {
            // startup sockets (pytest, plugins, the runner) are the baseline; the scan's own reads are not inputs
            self.set_active(false);
            let ctx = if old.is_empty() { None } else { Some(lock(&self.st).ctx_index(&old)) };
            let r = (|| -> PyResult<()> {
                if self.socks.bind(py).get().scan_now(py) {
                    if let Some(c) = ctx {
                        self.flag_impl(py, c, b"csock", Some(b"an internet socket left open".to_vec()))?;
                    }
                }
                Ok(())
            })();
            self.set_active(true);
            r?;
        }
        level0::l0_listener_reset();
        let i = {
            let mut st = lock(&self.st);
            st.ctx = w.clone();
            let i = st.ctx_index(&w);
            st.timeline.push((now(), i));
            i
        };
        let Some(rec) = self.recorder(py) else { return Ok(()) };
        let rec = rec.bind(py);
        let n = rec.len()?;
        {
            let mut st = lock(&self.st);
            if st.segs.last().map(|s| s.1) == Some(n) {
                *st.segs.last_mut().unwrap() = (i, n);
            } else {
                st.segs.push((i, n));
            }
        }
        let hot = rec.call_method0(intern!(py, "switch"))?;
        let hot = hot.cast::<PyList>()?;
        if !hot.is_empty() {
            let tool = *lock(&self.tool);
            let set_local = py.import("sys")?.getattr("monitoring")?.getattr("set_local_events")?;
            for code in hot.iter() {
                let ev = lock(&self.st).events.get(&(code.as_ptr() as usize)).copied().unwrap_or(0);
                set_local.call1((tool, &code, 0))?;
                set_local.call1((tool, &code, ev))?;
            }
        }
        Ok(())
    }

    fn _cur(&self, py: Python<'_>) -> PyResult<usize> {
        self.cur(py)
    }

    fn _import_ctx(&self, py: Python<'_>) -> PyResult<usize> {
        self.import_ctx_of_frames(py)
    }

    fn _want(&self, py: Python<'_>, filename: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.want(py, filename)
    }

    /// The file id of a wanted file name (`fid[filename]`).
    fn file_id(&self, filename: Bound<'_, PyString>) -> PyResult<Option<usize>> {
        Ok(lock(&self.st).fid.get(&w_of(&filename)?).copied())
    }

    fn arm(&self, py: Python<'_>, code: &Bound<'_, PyAny>) -> PyResult<()> {
        self.arm_impl(py, code)
    }

    fn _caller_kind(&self, py: Python<'_>) -> PyResult<&'static str> {
        Ok(match self.caller_kind(py)? {
            Caller::Import => "import",
            Caller::Infra => "infra",
            Caller::User => "user",
        })
    }

    fn _abs<'py>(&self, py: Python<'py>, p: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyAny>>> {
        self.abs(py, p)?.map(|w| py_of(py, &w)).transpose()
    }

    fn _ignored(&self, p: Bound<'_, PyString>) -> PyResult<bool> {
        Ok(self.ignored(&w_of(&p)?))
    }

    fn _note_code(&self, py: Python<'_>, filename: &Bound<'_, PyAny>) -> PyResult<()> {
        if let Some(p) = self.abs(py, filename)? {
            lock(&self.st).note_code(p);
        }
        Ok(())
    }

    /// Mark a file loaded before the start (`preloaded`) and note its code.
    fn note_preloaded(&self, py: Python<'_>, filename: &Bound<'_, PyAny>) -> PyResult<bool> {
        if !self.want(py, filename)? {
            return Ok(false);
        }
        let k = w_of(filename.cast::<PyString>()?)?;
        {
            let mut st = lock(&self.st);
            let rel = st.fnames[st.fid[&k]].clone();
            st.preloaded.add(rel);
        }
        self._note_code(py, filename)?;
        Ok(true)
    }

    /// Repository code files (relative paths) changed since their source was first read or their module body
    /// first ran in this session.
    fn changed_code<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let items: Vec<(W, StatKey)> = {
            let st = lock(&self.st);
            st.code_stat_order.iter().map(|p| (p.clone(), st.code_stat[p])).collect()
        };
        let root_sep = lock(&self.st).root_sep.clone();
        let realpath = os_mod(py)?.getattr("path")?.getattr("realpath")?;
        let mut out = BTreeSet::new();
        for (p, k) in items {
            if stat_key(&p) == k {
                continue;
            }
            let r = match realpath.call1((py_of(py, &p)?,)) {
                Ok(r) => w_of(r.cast::<PyString>()?)?,
                Err(e) if e.is_instance_of::<pyo3::exceptions::PyOSError>(py)
                    || e.is_instance_of::<pyo3::exceptions::PyValueError>(py) =>
                {
                    continue
                }
                Err(e) => return Err(e),
            };
            if r.starts_with(&root_sep) {
                out.insert(r[root_sep.len()..].to_vec());
            }
        }
        let v: Vec<Bound<'py, PyAny>> = out.iter().map(|w| py_of(py, w)).collect::<PyResult<_>>()?;
        PyList::new(py, v)
    }

    fn _key<'py>(&self, py: Python<'py>, p: Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
        let w = w_of(&p)?;
        let st = lock(&self.st);
        py_of(py, st.key(&w))
    }

    /// A read of `p` (kind f = file content, d = listing, m = a machine identity file) in context `ctx`.
    fn read(&self, py: Python<'_>, ctx: usize, p: Bound<'_, PyString>, kind: &str) -> PyResult<()> {
        let k = kind.as_bytes().first().copied().unwrap_or(b'f');
        self.read_impl(py, ctx, &w_of(&p)?, k)
    }

    fn wrote(&self, ctx: usize, p: Bound<'_, PyString>) -> PyResult<()> {
        self.wrote_impl(ctx, &w_of(&p)?);
        Ok(())
    }

    /// The audit hook (`_core.set_audit_hook(cap.audit, ...)`).
    fn audit(slf: &Bound<'_, Self>, event: &str, args: &Bound<'_, PyTuple>) -> PyResult<()> {
        let py = slf.py();
        slf.get().audit_impl(py, slf.as_any(), event, args)
    }

    #[pyo3(signature = (ctx, flag, detail = None))]
    fn flag(&self, py: Python<'_>, ctx: usize, flag: Bound<'_, PyString>, detail: Option<Bound<'_, PyString>>) -> PyResult<()> {
        let d = detail.map(|d| w_of(&d)).transpose()?;
        self.flag_impl(py, ctx, &w_of(&flag)?, d)
    }

    fn env_read_ctx(&self, ctx: usize, name: Bound<'_, PyString>) -> PyResult<()> {
        let w = w_of(&name)?;
        lock(&self.st).env_set(ctx).add(w);
        Ok(())
    }

    fn env_read(&self, py: Python<'_>, name: Bound<'_, PyString>) -> PyResult<()> {
        if self.active() {
            let c = self.cur(py)?;
            let w = w_of(&name)?;
            lock(&self.st).env_set(c).add(w);
        }
        Ok(())
    }

    /// `_note_env(key)`: an `os.environ` read (`__getitem__`, `__contains__`; `"*"` for iteration).
    fn note_env(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        if !self.active() {
            return Ok(());
        }
        let name = if key.is_exact_instance_of::<PyString>() {
            key.clone()
        } else if key.is_instance_of::<PyString>() || key.is_instance_of::<PyBytes>() {
            os_mod(py)?.getattr(intern!(py, "fsdecode"))?.call1((key,))?
        } else {
            key.repr()?.into_any()
        };
        let name = w_of(name.cast::<PyString>()?)?;
        // a variable the current context already read: recording it again changes nothing, whoever reads it, so
        // the walk over the calling frames is skipped (during an import the context is found by a frame walk)
        if self.recorder(py).is_some() && self.import_depth(py) == 0 {
            let st = lock(&self.st);
            if let Some(&c) = st.ctx_ix.get(&st.ctx) {
                if st.env.get(&c).map(|s| s.has(&name)).unwrap_or(false) {
                    return Ok(());
                }
            }
        }
        // _env_caller_is_user: the first frame outside detpy decides (user: yes, infrastructure: no)
        let hub = Classifier::get(py)?;
        let mut f = current_frame(py);
        let mut user = true;
        while let Some(fr) = f {
            let (_code, fname) = code_filename(&fr)?;
            if starts_with_str(&fname, &self.env.detpy_dir) {
                f = level0::back(&fr)?;
                continue;
            }
            match hub.classify(py, &fname)?.0 {
                Kind::User => break,
                Kind::Infra => {
                    user = false;
                    break;
                }
                Kind::Stdlib => {}
            }
            f = level0::back(&fr)?;
        }
        if !user {
            return Ok(());
        }
        if self.active() {
            let c = self.cur(py)?;
            lock(&self.st).env_set(c).add(name);
        }
        Ok(())
    }

    /// A Level 0 event by user code (`_state.record` -> the event listener). True when calling again for
    /// `source` changes nothing until the next switch: the source is flagged in a context that is not import time.
    fn event(&self, py: Python<'_>, source: Bound<'_, PyString>, value: Bound<'_, PyString>) -> PyResult<bool> {
        if !self.active() {
            return Ok(false);
        }
        let c = self.cur(py)?;
        let src = w_of(&source)?;
        let mut st = lock(&self.st);
        let fl = st.flag_set(c);
        if src == b"net" {
            let v = w_of(&value)?;
            if contains(&v, b"record#") {
                fl.add(b"net-record".to_vec());
            } else if contains(&v, b"replay") {
                fl.add(b"net-replay".to_vec());
            }
            return Ok(false);
        }
        fl.add(src);
        drop(st);
        Ok(self.import_depth(py) == 0)
    }

    /// Note the repository modules loaded so far (``sys.modules`` and conftest plugins, which pytest keeps out of
    /// ``sys.modules``) as loaded after the test at ``index`` (-1 = collection).
    #[pyo3(signature = (index, plugins = None))]
    fn scan_modules(&self, py: Python<'_>, index: i64, plugins: Option<Bound<'_, PyAny>>) -> PyResult<()> {
        let note = |f: &Bound<'_, PyAny>| -> PyResult<()> {
            if f.is_instance_of::<PyString>() && self.want(py, f)? {
                let k = w_of(f.cast::<PyString>()?)?;
                let mut st = lock(&self.st);
                let rel = st.fnames[st.fid[&k]].clone();
                if st.seen_mods.insert(rel.clone()) {
                    st.loaded_order.push((rel, index));
                }
            }
            Ok(())
        };
        if let Some(pl) = plugins {
            for m in pl.try_iter()? {
                let m = m?;
                let f = match m.getattr(intern!(py, "__file__")) {
                    Ok(f) => f,
                    Err(e) if e.is_instance_of::<pyo3::exceptions::PyAttributeError>(py) => continue,
                    Err(e) => return Err(e),
                };
                note(&f)?;
            }
        }
        let mods = py.import("sys")?.getattr("modules")?.cast_into::<PyDict>()?;
        let n = mods.len();
        {
            let mut st = lock(&self.st);
            if n == st.nmods {
                return Ok(());
            }
            st.nmods = n;
        }
        let values = PyList::new(py, mods.values())?;
        for m in values.iter() {
            let f = match m.getattr(intern!(py, "__file__")) {
                Ok(f) => f,
                Err(e) if e.is_instance_of::<pyo3::exceptions::PyAttributeError>(py) => continue,
                Err(e) => return Err(e),
            };
            if f.is_none() || !f.is_truthy()? {
                continue;
            }
            if let Ok(fs) = f.cast::<PyString>() {
                let k = w_of(fs)?;
                if lock(&self.st).wanted.get(&k) == Some(&false) {
                    continue;
                }
            }
            if self.want(py, &f)? {
                note(&f)?;
            }
        }
        Ok(())
    }

    /// Non-global contexts (tests, fixtures, collection of a file) active at some time in `[t0, t1]`.
    fn _contexts_during(&self, t0: Option<f64>, t1: Option<f64>) -> HashSet<usize> {
        let (Some(t0), Some(t1)) = (t0, t1) else { return HashSet::new() };
        let st = lock(&self.st);
        let glob: HashSet<Option<usize>> =
            [b"".as_slice(), b"s".as_slice()].iter().map(|n| st.ctx_ix.get(*n).copied()).collect();
        let tl = &st.timeline;
        let mut out = HashSet::new();
        for (k, &(tk, ck)) in tl.iter().enumerate() {
            let nxt = tl.get(k + 1).map(|x| x.0).unwrap_or(f64::INFINITY);
            if tk <= t1 && nxt > t0 && !glob.contains(&Some(ck)) {
                out.insert(ck);
            }
        }
        out
    }

    /// Whether `ctx` already has `flag` (for the Python callers that build a detail).
    fn has_flag(&self, ctx: usize, flag: Bound<'_, PyString>) -> PyResult<bool> {
        let f = w_of(&flag)?;
        Ok(lock(&self.st).flags.get(&ctx).map(|s| s.has(&f)).unwrap_or(false))
    }

    /// `why.get((ctx, flag))`.
    fn why_of<'py>(&self, py: Python<'py>, ctx: usize, flag: Bound<'py, PyString>) -> PyResult<Option<Bound<'py, PyAny>>> {
        let f = w_of(&flag)?;
        lock(&self.st).why.get(&(ctx, f)).map(|d| py_of(py, d)).transpose()
    }
}

/// The capture whose environment reads are recorded (`proofcache._ENV_CAPTURE`).
static ENV_CAPTURE: Mutex<Option<Py<CaptureCore>>> = Mutex::new(None);

#[pyfunction]
pub fn cap_set_env_capture(cap: Option<Py<CaptureCore>>) {
    let old = std::mem::replace(&mut *lock(&ENV_CAPTURE), cap);
    drop(old);
}

/// `_note_env(key)` (called by the recorded `os.environ` / `os.environb`).
#[pyfunction]
pub fn cap_note_env(py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
    let cap = lock(&ENV_CAPTURE).as_ref().map(|c| c.clone_ref(py));
    match cap {
        Some(c) => c.bind(py).get().note_env(py, key),
        None => Ok(()),
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CaptureCore>()?;
    m.add_function(wrap_pyfunction!(cap_set_env_capture, m)?)?;
    m.add_function(wrap_pyfunction!(cap_note_env, m)?)?;
    Ok(())
}
