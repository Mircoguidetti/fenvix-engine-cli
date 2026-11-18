//! Per-context line recorder for `sys.monitoring` (Python 3.12+), the
//! dependency capture of the cache with proof.
//!
//! Port of the cache-skip study's C recorder (`harness/cache_skip/_sysmon_rec.c`)
//! with one addition: *import time*. Module code objects are armed with
//! `PY_START` and `PY_RETURN`; while a module body is running (an import, an
//! `exec` of module code) every recorded location is flagged, because what runs
//! there builds module state that every later reader depends on, whichever test
//! happened to trigger the import.
//!
//! Strategy (MEASURED in the study, +10% median overhead on 3 libraries): the
//! first hit of a location in the current context appends one value
//! (`import flag << 63 | file id << 24 | line`) to a flat buffer; the next `hot`
//! hits only count; past that the callback returns `sys.monitoring.DISABLE` and
//! remembers the code object, which the Python side re-arms at the next context
//! switch.

use pyo3::exceptions::PyTypeError;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList, PyTuple};
use std::collections::HashMap;
use std::ffi::{c_char, c_int, c_void, CStr};
use std::sync::atomic::{AtomicBool, AtomicPtr, Ordering};
use std::sync::{Mutex, MutexGuard};

pub const SHIFT: u32 = 24;
pub const IMPORT_FLAG: u64 = 1 << 63;
const LINE_MASK: u64 = (1 << SHIFT) - 1;

/// Multiplicative hasher for the recorder's integer keys (code object addresses, packed locations): the
/// callbacks run for every new line of every context, and SipHash dominated their cost (MEASURED on
/// home-assistant). Keys are not attacker-controlled.
#[derive(Default, Clone, Copy)]
struct IntHasher(u64);

impl std::hash::Hasher for IntHasher {
    fn finish(&self) -> u64 {
        // the product's entropy is in its high bits; hashbrown indexes buckets with the low ones (aligned
        // addresses would otherwise all collide)
        self.0.rotate_left(26)
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.write_u64(b as u64);
        }
    }
    fn write_u64(&mut self, n: u64) {
        self.0 = (self.0.rotate_left(5) ^ n).wrapping_mul(0x517c_c1b7_2722_0a95);
    }
    fn write_usize(&mut self, n: usize) {
        self.write_u64(n as u64);
    }
}

type IntMap<K, V> = HashMap<K, V, std::hash::BuildHasherDefault<IntHasher>>;

struct Slot {
    fid: u64,
    entry: i64,
    module: bool,
    /// code-object level (`add_code(rep=...)`): the code is armed with `PY_START` only and its first start in a
    /// context stands for every line it runs (`rep`, a line of its body); -1 = line level
    rep: i64,
    _code: Py<PyAny>,
}

#[derive(Default)]
struct Inner {
    codes: IntMap<usize, Slot>,
    seen: IntMap<u64, u32>,
    buf: Vec<u64>,
    hot_codes: Vec<Py<PyAny>>,
    hot_ids: IntMap<usize, ()>,
    import_depth: u32,
}

#[pyclass(module = "detpy._core", frozen)]
pub struct LineRecorder {
    inner: Mutex<Inner>,
    disable: Py<PyAny>,
    hot: u32,
}

fn lock(m: &Mutex<Inner>) -> MutexGuard<'_, Inner> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

impl LineRecorder {
    /// Module bodies running (the capture's import time).
    pub(crate) fn depth(&self) -> u32 {
        lock(&self.inner).import_depth
    }

    fn hit(&self, py: Python<'_>, g: &mut Inner, k: u64, code: &Bound<'_, PyAny>) -> Py<PyAny> {
        match g.seen.get_mut(&k) {
            None => {
                g.seen.insert(k, 0);
                g.buf.push(k);
                py.None()
            }
            Some(c) if *c < self.hot => {
                *c += 1;
                py.None()
            }
            Some(_) => {
                let id = code.as_ptr() as usize;
                if g.hot_ids.insert(id, ()).is_none() {
                    g.hot_codes.push(code.clone().unbind());
                }
                self.disable.clone_ref(py)
            }
        }
    }
}

#[pymethods]
impl LineRecorder {
    #[new]
    #[pyo3(signature = (disable, hot = 16))]
    fn new(disable: Py<PyAny>, hot: u32) -> Self {
        LineRecorder { inner: Mutex::new(Inner::default()), disable, hot }
    }

    /// Register a code object: `fid` is the file id (not shifted), `entry` the
    /// entry line `LINE` never reports (-1 if none), `module` for module bodies; `rep` >= 0 records the code at
    /// code-object level (its starts, as line `rep`) instead of line by line.
    #[pyo3(signature = (code, fid, entry, module = false, rep = -1))]
    fn add_code(&self, code: &Bound<'_, PyAny>, fid: u64, entry: i64, module: bool, rep: i64) {
        let mut g = lock(&self.inner);
        g.codes.insert(
            code.as_ptr() as usize,
            Slot { fid: fid << SHIFT, entry, module, rep, _code: code.clone().unbind() },
        );
    }

    /// `LINE` callback.
    fn line(&self, py: Python<'_>, code: &Bound<'_, PyAny>, lineno: i64) -> Py<PyAny> {
        let mut g = lock(&self.inner);
        let Some(s) = g.codes.get(&(code.as_ptr() as usize)) else { return py.None() };
        if lineno < 0 {
            return py.None();
        }
        let flag = if g.import_depth > 0 { IMPORT_FLAG } else { 0 };
        let k = flag | s.fid | (lineno as u64 & LINE_MASK);
        self.hit(py, &mut g, k, code)
    }

    /// `PY_START` callback.
    fn start(&self, py: Python<'_>, code: &Bound<'_, PyAny>, _offset: i64) -> Py<PyAny> {
        let mut g = lock(&self.inner);
        let Some(s) = g.codes.get(&(code.as_ptr() as usize)) else { return py.None() };
        let (fid, entry, module, rep) = (s.fid, s.entry, s.module, s.rep);
        if rep >= 0 {
            let flag = if g.import_depth > 0 { IMPORT_FLAG } else { 0 };
            return self.hit(py, &mut g, flag | fid | (rep as u64 & LINE_MASK), code);
        }
        if module {
            g.import_depth += 1;
        }
        if entry < 0 {
            return py.None();
        }
        let flag = if g.import_depth > 0 { IMPORT_FLAG } else { 0 };
        let r = self.hit(py, &mut g, flag | fid | (entry as u64 & LINE_MASK), code);
        if module {
            py.None() // a module's start must keep firing: it drives the import depth
        } else {
            r
        }
    }

    /// `PY_RETURN` callback (armed on module code objects only).
    fn ret(&self, py: Python<'_>, code: &Bound<'_, PyAny>, _offset: i64, _value: &Bound<'_, PyAny>) -> Py<PyAny> {
        let mut g = lock(&self.inner);
        if g.codes.get(&(code.as_ptr() as usize)).map(|s| s.module).unwrap_or(false) {
            g.import_depth = g.import_depth.saturating_sub(1);
        }
        py.None()
    }

    /// New context: forget the seen locations and the import depth (an import
    /// that raised never returned); returns the code objects to re-arm.
    fn switch<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let mut g = lock(&self.inner);
        g.seen.clear();
        g.import_depth = 0;
        g.hot_ids.clear();
        let codes: Vec<Py<PyAny>> = std::mem::take(&mut g.hot_codes);
        PyList::new(py, codes)
    }

    #[getter]
    fn import_depth(&self) -> u32 {
        lock(&self.inner).import_depth
    }

    fn __len__(&self) -> usize {
        lock(&self.inner).buf.len()
    }

    fn tobytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        let g = lock(&self.inner);
        let bytes: Vec<u8> = g.buf.iter().flat_map(|v| v.to_ne_bytes()).collect();
        PyBytes::new(py, &bytes)
    }

    /// Fold the buffer into units per context.
    ///
    /// * `segs`: `[(context index, start position in the buffer)]` in order;
    /// * `ranges`: per file id, the sorted `[(first line, last line)]` body
    ///   ranges of the file's units (unit index = position).
    ///
    /// Returns `(per_context, imported)`: for every context index, the sorted
    /// unique `(fid << 32 | unit)` values of its non-flagged locations and the
    /// sorted unique file ids it executed at all; `imported` is the same pair
    /// for the flagged (import-time) locations of every context.
    #[allow(clippy::type_complexity)]
    fn fold(
        &self,
        n_ctx: usize,
        segs: Vec<(usize, usize)>,
        ranges: Vec<Vec<(u32, u32)>>,
    ) -> (Vec<(Vec<u64>, Vec<u64>)>, (Vec<u64>, Vec<u64>)) {
        let g = lock(&self.inner);
        let buf = &g.buf;
        let mut per: Vec<(Vec<u64>, Vec<u64>)> = vec![(Vec::new(), Vec::new()); n_ctx];
        let mut imp: (Vec<u64>, Vec<u64>) = (Vec::new(), Vec::new());
        let unit_of = |fid: usize, line: u32| -> Option<u64> {
            let r = ranges.get(fid)?;
            // last range whose start <= line
            let i = r.partition_point(|&(a, _)| a <= line);
            if i == 0 {
                return None;
            }
            let (a, b) = r[i - 1];
            (a <= line && line <= b).then_some(((fid as u64) << 32) | (i as u64 - 1))
        };
        for (n, &(ctx, start)) in segs.iter().enumerate() {
            let end = segs.get(n + 1).map(|s| s.1).unwrap_or(buf.len()).min(buf.len());
            if ctx >= n_ctx || start >= end {
                continue;
            }
            for &v in &buf[start..end] {
                let flagged = v & IMPORT_FLAG != 0;
                let v = v & !IMPORT_FLAG;
                let fid = (v >> SHIFT) as usize;
                let line = (v & LINE_MASK) as u32;
                let tgt = if flagged { &mut imp } else { &mut per[ctx] };
                tgt.1.push(fid as u64);
                if let Some(u) = unit_of(fid, line) {
                    tgt.0.push(u);
                }
            }
        }
        for p in per.iter_mut().chain(std::iter::once(&mut imp)) {
            p.0.sort_unstable();
            p.0.dedup();
            p.1.sort_unstable();
            p.1.dedup();
        }
        (per, imp)
    }
}

// ---------------------------------------------------------------------------
// Audit hook filtered in Rust: only the listed events reach the Python callable
// (a Python audit hook is called for every event, e.g. the frequent
// "builtins.id" and "object.__getattr__"). Audit hooks cannot be removed, so
// one hook is installed per process and dispatches to the current filter,
// which `set_audit_hook` replaces (None turns it off). Replaced filters are
// leaked on purpose: another thread may still be reading one.

static INSTALLED: AtomicBool = AtomicBool::new(false);
static CURRENT: AtomicPtr<AuditFilter> = AtomicPtr::new(std::ptr::null_mut());

struct AuditFilter {
    callable: *mut ffi::PyObject,
    names: Vec<Vec<u8>>,
}

extern "C" {
    fn PySys_AddAuditHook(
        hook: Option<unsafe extern "C" fn(*const c_char, *mut ffi::PyObject, *mut c_void) -> c_int>,
        user_data: *mut c_void,
    ) -> c_int;
}

unsafe extern "C" fn audit_hook(event: *const c_char, args: *mut ffi::PyObject, _data: *mut c_void) -> c_int {
    let f = CURRENT.load(Ordering::Acquire);
    if f.is_null() || event.is_null() {
        return 0;
    }
    let f = &*f;
    let ev = CStr::from_ptr(event).to_bytes();
    if !f.names.iter().any(|n| n.as_slice() == ev) {
        return 0;
    }
    let py_ev = ffi::PyUnicode_FromStringAndSize(event, ev.len() as ffi::Py_ssize_t);
    if py_ev.is_null() {
        return -1;
    }
    let r = ffi::PyObject_CallFunctionObjArgs(f.callable, py_ev, args, std::ptr::null_mut::<ffi::PyObject>());
    ffi::Py_DECREF(py_ev);
    if r.is_null() {
        return -1;
    }
    ffi::Py_DECREF(r);
    0
}

/// `set_audit_hook(callable, names)`: call `callable(event, args)` for the listed
/// audit events only; `set_audit_hook(None, ())` stops calling it.
#[pyfunction]
pub fn set_audit_hook(callable: &Bound<'_, PyAny>, names: &Bound<'_, PyTuple>) -> PyResult<()> {
    let new = if callable.is_none() {
        std::ptr::null_mut()
    } else {
        if !callable.is_callable() {
            return Err(PyTypeError::new_err("callable or None expected"));
        }
        let mut v = Vec::new();
        for n in names.iter() {
            let s: String = n.extract()?;
            v.push(s.into_bytes());
        }
        Box::into_raw(Box::new(AuditFilter { callable: callable.clone().into_ptr(), names: v }))
    };
    CURRENT.store(new, Ordering::Release);
    if !INSTALLED.swap(true, Ordering::AcqRel) {
        let rc = unsafe { PySys_AddAuditHook(Some(audit_hook), std::ptr::null_mut()) };
        if rc != 0 {
            INSTALLED.store(false, Ordering::Release);
            return Err(PyErr::take(callable.py())
                .unwrap_or_else(|| PyTypeError::new_err("PySys_AddAuditHook failed")));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Internet sockets opened in C (libpq, grpc, libcurl, ...) raise no audit event. At every context switch the
// capture compares this process's socket descriptors with the previous scan; a new one that is an internet
// socket (listed in /proc/self/net/{tcp,tcp6,udp,udp6}) makes the context that is ending uncacheable.

fn socket_fds() -> Option<HashMap<String, String>> {
    use std::os::unix::fs::{FileTypeExt, MetadataExt};
    use std::os::unix::io::FromRawFd;
    let rd = std::fs::read_dir("/proc/self/fd").ok()?;
    let mut cur = HashMap::new();
    for e in rd.flatten() {
        let name = e.file_name();
        let Some(fd) = name.to_str() else { continue };
        let Ok(n) = fd.parse::<i32>() else { continue };
        // fstat of the descriptor itself: a socket's inode is the one /proc shows as "socket:[inode]" (one cheap
        // system call instead of a readlink through procfs); the File is never dropped, so nothing is closed
        let f = std::mem::ManuallyDrop::new(unsafe { std::fs::File::from_raw_fd(n) });
        let Ok(m) = f.metadata() else { continue };
        if m.file_type().is_socket() {
            cur.insert(fd.to_string(), m.ino().to_string());
        }
    }
    Some(cur)
}

/// Inodes of this process's internet sockets (column 10 of /proc/self/net/{tcp,tcp6,udp,udp6}).
fn inet_inodes() -> std::collections::HashSet<String> {
    let mut out = std::collections::HashSet::new();
    for t in ["tcp", "tcp6", "udp", "udp6"] {
        let Ok(b) = std::fs::read(format!("/proc/self/net/{t}")) else { continue };
        for line in b.split(|&c| c == b'\n').skip(1) {
            let parts: Vec<&[u8]> = line.split(|c| c.is_ascii_whitespace()).filter(|p| !p.is_empty()).collect();
            if parts.len() > 9 {
                out.insert(String::from_utf8_lossy(parts[9]).into_owned());
            }
        }
    }
    out
}

/// Socket descriptors of this process between context switches.
#[pyclass(module = "detpy._core", frozen)]
pub struct SocketScan {
    prev: Mutex<Option<HashMap<String, String>>>,
}

#[pymethods]
impl SocketScan {
    #[new]
    fn new() -> Self {
        SocketScan { prev: Mutex::new(None) }
    }

    /// Scan the descriptors; True when an internet socket appeared since the last scan (False at the first scan,
    /// which is the baseline, and when /proc is unavailable).
    fn scan(&self, py: Python<'_>) -> bool {
        py.detach(|| {
            let Some(cur) = socket_fds() else { return false };
            let mut g = self.prev.lock().unwrap_or_else(|e| e.into_inner());
            let prev = g.replace(cur);
            let Some(prev) = prev else { return false };
            let cur = g.as_ref().expect("just set");
            let new: Vec<&String> = cur.iter().filter(|(fd, ino)| prev.get(*fd) != Some(*ino)).map(|(_, i)| i).collect();
            if new.is_empty() {
                return false;
            }
            let inet = inet_inodes();
            new.iter().any(|i| inet.contains(*i))
        })
    }
}

/// `-o` arguments under `logdir` of every live process (strace tracers of followed children, or strace itself
/// before it forks its tracer). A child's trace log is written only by its tracer: when no live process holds
/// the log's prefix, nothing more will be written to it. `None` when that cannot be known (no /proc, an
/// undecodable argument).
#[pyfunction]
pub fn tracer_prefixes(py: Python<'_>, logdir: &str) -> Option<Vec<String>> {
    py.detach(|| {
        let mut out = Vec::new();
        let rd = std::fs::read_dir("/proc").ok()?;
        for e in rd.flatten() {
            let name = e.file_name();
            let Some(n) = name.to_str() else { continue };
            if n.is_empty() || !n.bytes().all(|b| b.is_ascii_digit()) {
                continue;
            }
            let Ok(cmd) = std::fs::read(e.path().join("cmdline")) else { continue };
            let args: Vec<&[u8]> = cmd.split(|&b| b == 0).collect();
            for w in args.windows(2) {
                if w[0] == b"-o" && w[1].starts_with(logdir.as_bytes()) {
                    out.push(std::str::from_utf8(w[1]).ok()?.to_string());
                }
            }
        }
        out.sort();
        out.dedup();
        Some(out)
    })
}
