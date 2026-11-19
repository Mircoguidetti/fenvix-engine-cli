//! Rare events of the cache with proof's capture, in Rust: a socket connect or send (is the peer this very
//! process?), a host name lookup (is the host numeric?), a spawn (which program?).
//!
//! Port of `_own_listener`, `_both_ends_mine`, `_own_socket_inodes`, `_loopback_hex`, `_numeric_host`, `_addr` and
//! `_spawn_detail` of round 2's `detpy/proofcache.py` (kept in `tests/rust_hotpaths_ref/_ref_proofcache.py`; tested
//! against them in `tests/test_sqlcap_rust.py`). The socket's attributes, `str()` / `int()` / `format()` of the
//! address parts and `os.fsdecode` are the interpreter's; `ipaddress.ip_address` is `network::parse_ip` (with the
//! interpreter's flags of an IPv4-mapped address); `/proc/self/fd` and `/proc/self/net/tcp{,6}` are read directly.

use crate::capture::first_user_site;
use crate::fsorder::{from_wtf8, wtf8};
use crate::network::{ip_flags, is_ip_any, Flags};
use pyo3::exceptions::{PyAttributeError, PyIndexError, PyOSError, PyTypeError, PyValueError};
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyBytes, PyInt, PyList, PyModule, PySet, PyString, PyTuple};
use std::collections::HashSet;
use std::os::unix::ffi::OsStrExt;

type W = Vec<u8>;

fn is_any(py: Python<'_>, e: &PyErr, kinds: &[fn(Python<'_>, &PyErr) -> bool]) -> bool {
    kinds.iter().any(|k| k(py, e))
}

fn attr_err(py: Python<'_>, e: &PyErr) -> bool {
    e.is_instance_of::<PyAttributeError>(py)
}
fn index_err(py: Python<'_>, e: &PyErr) -> bool {
    e.is_instance_of::<PyIndexError>(py)
}
fn type_err(py: Python<'_>, e: &PyErr) -> bool {
    e.is_instance_of::<PyTypeError>(py)
}
fn value_err(py: Python<'_>, e: &PyErr) -> bool {
    e.is_instance_of::<PyValueError>(py)
}
fn os_err(py: Python<'_>, e: &PyErr) -> bool {
    e.is_instance_of::<PyOSError>(py)
}

/// `socket.AF_INET`, `socket.AF_INET6`, `socket.SOCK_STREAM`.
fn sock_consts(py: Python<'_>) -> PyResult<&(Py<PyAny>, Py<PyAny>, Py<PyAny>)> {
    static C: PyOnceLock<(Py<PyAny>, Py<PyAny>, Py<PyAny>)> = PyOnceLock::new();
    C.get_or_try_init(py, || {
        let s = py.import("socket")?;
        Ok((s.getattr("AF_INET")?.unbind(), s.getattr("AF_INET6")?.unbind(), s.getattr("SOCK_STREAM")?.unbind()))
    })
}

/// `sock.family in (AF_INET, AF_INET6) and sock.type & 0xF == SOCK_STREAM`.
fn inet_stream(py: Python<'_>, sock: &Bound<'_, PyAny>) -> PyResult<bool> {
    let (a4, a6, stream) = sock_consts(py)?;
    let fam = sock.getattr(intern!(py, "family"))?;
    let in_tuple = |x: &Py<PyAny>| -> PyResult<bool> { Ok(x.bind(py).is(&fam) || x.bind(py).eq(&fam)?) };
    if !(in_tuple(a4)? || in_tuple(a6)?) {
        return Ok(false);
    }
    let t = sock.getattr(intern!(py, "type"))?.bitand(0xF)?;
    Ok(!t.ne(stream.bind(py))?)
}

/// `ipaddress.ip_address(str(host).split("%", 1)[0])` is loopback, or IPv4-mapped loopback; Err(ValueError) if not
/// an address.
fn host_flags(py: Python<'_>, host: &Bound<'_, PyAny>) -> PyResult<Flags> {
    let s = host.str()?;
    let b = wtf8(&s)?;
    let part = match b.iter().position(|&c| c == b'%') {
        Some(i) => &b[..i],
        None => &b[..],
    };
    if let Some(f) = ip_flags(py, part)? {
        return Ok(f);
    }
    if loopback_name(part) {
        return Ok(Flags { loopback: true, unspecified: false, mapped_loopback: false });
    }
    Err(PyValueError::new_err("not an IP address"))
}

/// A name that resolves to the loopback address on every host (RFC 6761 6.3: `localhost` and names under it), plus
/// the loopback aliases of Debian-style `/etc/hosts`. Review R-023 (cacheability).
pub(crate) fn loopback_name(b: &[u8]) -> bool {
    let n = b.strip_suffix(b".").unwrap_or(b).to_ascii_lowercase();
    n == b"localhost"
        || n.ends_with(b".localhost")
        || n == b"localhost.localdomain"
        || n == b"ip6-localhost"
        || n == b"ip6-loopback"
}

/// `f"{port:04X}"`.
fn hex04(py: Python<'_>, port: &Bound<'_, PyAny>) -> PyResult<W> {
    match port.extract::<i64>() {
        Ok(n) if n >= 0 => Ok(format!("{n:04X}").into_bytes()),
        Ok(n) => Ok(format!("-{:03X}", -(n as i128)).into_bytes()),
        Err(_) => {
            let s = py.import("builtins")?.getattr("format")?.call1((port, "04X"))?;
            Ok(wtf8(s.cast::<PyString>()?)?.into_owned())
        }
    }
}

/// `_own_socket_inodes()`: the inodes of the sockets this process holds.
/// The pid of this worker's xdist controller under `--det -n` (0: not a worker). Set by the worker when it restores
/// its controller's environment (`xdist.restore_controller_env`).
static XDIST_CONTROLLER: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);

/// Review R-023 (cacheability): an xdist worker of a `--det` controller. A listener the controller holds is
/// session infrastructure (the controller runs no test code: plugins such as pytest-rerunfailures serve their
/// cross-worker state from it), so a connect to it is treated like a connect to a listener of this process.
#[pyfunction]
pub fn set_xdist_controller_pid(pid: u32) {
    XDIST_CONTROLLER.store(pid, std::sync::atomic::Ordering::Relaxed);
}

fn own_socket_inodes() -> HashSet<W> {
    let mut mine = socket_inodes("/proc/self/fd");
    let ctl = XDIST_CONTROLLER.load(std::sync::atomic::Ordering::Relaxed);
    if ctl != 0 {
        mine.extend(socket_inodes(&format!("/proc/{ctl}/fd")));
    }
    mine
}

fn socket_inodes(dir: &str) -> HashSet<W> {
    let mut mine = HashSet::new();
    let Ok(rd) = std::fs::read_dir(dir) else { return mine };
    for e in rd.flatten() {
        let Ok(link) = std::fs::read_link(e.path()) else { continue };
        let l = link.as_os_str().as_bytes();
        if l.starts_with(b"socket:[") {
            mine.insert(if l.len() > 8 { l[8..l.len() - 1].to_vec() } else { W::new() });
        }
    }
    mine
}

/// `bytes.fromhex(s)` (None: ValueError).
fn fromhex(s: &[u8]) -> Option<W> {
    if !s.is_ascii() {
        return None;
    }
    let ws = |c: u8| matches!(c, b' ' | b'\t' | b'\n' | b'\r' | 0x0B | 0x0C);
    let hex = |c: Option<&u8>| c.and_then(|&c| (c as char).to_digit(16));
    let mut out = Vec::with_capacity(s.len() / 2);
    let mut i = 0;
    while i < s.len() {
        if ws(s[i]) {
            while i < s.len() && ws(s[i]) {
                i += 1;
            }
            if i >= s.len() {
                break;
            }
        }
        let top = hex(s.get(i))?;
        let bot = hex(s.get(i + 1))?;
        out.push((top * 16 + bot) as u8);
        i += 2;
    }
    Some(out)
}

/// `_loopback_hex(laddr)`: a /proc/net/tcp{,6} local address (hex, host byte order per 32-bit word) that is loopback.
pub(crate) fn loopback_hex(laddr: &[u8]) -> bool {
    let Some(b) = fromhex(laddr) else { return false };
    match b.len() {
        4 => b[3] == 127, // little-endian 127.x.y.z
        16 => {
            let raw: Vec<u8> = b.chunks(4).flat_map(|w| w.iter().rev().copied()).collect();
            if raw[..15].iter().all(|&c| c == 0) && raw[15] == 1 {
                return true;
            }
            raw[..10].iter().all(|&c| c == 0) && raw[10] == 0xFF && raw[11] == 0xFF && raw[12] == 127
        }
        _ => false,
    }
}

/// The lines of `/proc/self/net/tcp` and `tcp6` after their header, as `(laddr, lport, state, inode)`; a file that
/// cannot be read is skipped.
fn tcp_sockets(mut f: impl FnMut(&[u8], &[u8], &[u8], &[u8]) -> PyResult<bool>) -> PyResult<bool> {
    for t in ["tcp", "tcp6"] {
        let Ok(data) = std::fs::read(format!("/proc/self/net/{t}")) else { continue };
        for line in data.split_inclusive(|&c| c == b'\n').skip(1) {
            let parts: Vec<&[u8]> = line.split(|&c| matches!(c, b' ' | b'\t' | b'\n' | b'\r' | 0x0B | 0x0C)).filter(|p| !p.is_empty()).collect();
            if parts.len() < 10 {
                continue;
            }
            let a = std::str::from_utf8(parts[1]).map_err(|e| PyValueError::new_err(e.to_string()))?.as_bytes();
            let (laddr, lport) = match a.iter().rposition(|&c| c == b':') {
                Some(i) => (&a[..i], &a[i + 1..]),
                None => (&b""[..], a),
            };
            if f(laddr, lport, parts[3], parts[9])? {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

/// `_own_listener(args)`: a TCP connect to a numeric loopback address whose port a listening socket of this very
/// process holds.
pub(crate) fn own_listener(py: Python<'_>, args: &Bound<'_, PyAny>) -> PyResult<bool> {
    let r = (|| -> PyResult<Option<(Flags, Bound<'_, PyAny>)>> {
        let sock = args.get_item(0)?;
        let addr = args.get_item(1)?;
        if !inet_stream(py, &sock)? {
            return Ok(None);
        }
        let host = addr.get_item(0)?;
        let port = py.get_type::<PyInt>().call1((addr.get_item(1)?,))?;
        Ok(Some((host_flags(py, &host)?, port)))
    })();
    let (flags, port) = match r {
        Ok(Some(x)) => x,
        Ok(None) => return Ok(false),
        Err(e) if is_any(py, &e, &[attr_err, index_err, type_err, value_err, os_err]) => return Ok(false),
        Err(e) => return Err(e),
    };
    if !(flags.loopback || flags.mapped_loopback) {
        return Ok(false);
    }
    let mine = own_socket_inodes();
    let want = hex04(py, &port)?;
    tcp_sockets(|laddr, lport, state, inode| {
        if state != b"0A" || lport != want.as_slice() || !mine.contains(inode) {
            return Ok(false); // not LISTEN, another port, another process's
        }
        Ok(laddr.iter().all(|&c| c == b'0') || loopback_hex(laddr))
    })
}

/// `_both_ends_mine(sock)`: a connected TCP socket whose peer address is the local address of a socket this process
/// holds.
pub(crate) fn both_ends_mine(py: Python<'_>, sock: &Bound<'_, PyAny>) -> PyResult<bool> {
    let peer = match (|| -> PyResult<Option<Bound<'_, PyAny>>> {
        if !inet_stream(py, sock)? {
            return Ok(None);
        }
        Ok(Some(sock.call_method0(intern!(py, "getpeername"))?))
    })() {
        Ok(Some(p)) => p,
        Ok(None) => return Ok(false),
        Err(e) if is_any(py, &e, &[attr_err, os_err]) => return Ok(false),
        Err(e) => return Err(e),
    };
    let flags = match peer.get_item(0).and_then(|h| host_flags(py, &h)) {
        Ok(f) => f,
        Err(e) if value_err(py, &e) => return Ok(false),
        Err(e) => return Err(e),
    };
    if !(flags.loopback || flags.mapped_loopback) {
        return Ok(false);
    }
    let mine = own_socket_inodes();
    let want = hex04(py, &py.get_type::<PyInt>().call1((peer.get_item(1)?,))?)?;
    tcp_sockets(|laddr, lport, _state, inode| Ok(lport == want.as_slice() && mine.contains(inode) && loopback_hex(laddr)))
}

/// `_numeric_host(host)`.
pub(crate) fn numeric_host(py: Python<'_>, host: &Bound<'_, PyString>) -> PyResult<bool> {
    is_ip_any(py, host.as_any())
}

/// `format(x, "")` (an f-string's `{x}`) as text.
fn formatted(py: Python<'_>, x: &Bound<'_, PyAny>) -> PyResult<W> {
    let empty = PyString::new(py, "");
    let s = unsafe { Bound::from_owned_ptr_or_err(py, ffi::PyObject_Format(x.as_ptr(), empty.as_ptr()))? };
    Ok(wtf8(s.cast::<PyString>()?)?.into_owned())
}

/// `_addr(args)`: the address of a socket event.
pub(crate) fn addr(py: Python<'_>, args: &Bound<'_, PyAny>) -> PyResult<W> {
    let r = (|| -> PyResult<W> {
        let a = args.get_item(1)?;
        if a.is_instance_of::<PyTuple>() {
            let mut w = formatted(py, &a.get_item(0)?)?;
            w.push(b':');
            w.extend_from_slice(&formatted(py, &a.get_item(1)?)?);
            Ok(w)
        } else {
            Ok(wtf8(&a.str()?)?.into_owned())
        }
    })();
    match r {
        Err(e) if is_any(py, &e, &[index_err, type_err]) => Ok(b"?".to_vec()),
        r => r,
    }
}

fn os_mod(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    static OS: PyOnceLock<Py<PyModule>> = PyOnceLock::new();
    Ok(OS.get_or_try_init(py, || py.import("os").map(|m| m.unbind()))?.bind(py).clone())
}

/// The program a spawn event starts (`_spawn_detail` without its call site).
fn spawn_prog(py: Python<'_>, event: &str, args: &Bound<'_, PyAny>) -> PyResult<W> {
    let os = os_mod(py)?;
    let prog = (|| -> PyResult<Option<Bound<'_, PyAny>>> {
        if event == "subprocess.Popen" {
            let a0 = args.get_item(0)?;
            if !a0.is_none() {
                return Ok(Some(a0));
            }
            let a1 = args.get_item(1)?;
            if a1.is_instance_of::<PyString>() || a1.is_instance_of::<PyBytes>() {
                return Ok(Some(a1));
            }
            return Ok(Some(py.get_type::<PyList>().call1((a1,))?.get_item(0)?));
        }
        if event == "os.system" {
            let s = os.getattr(intern!(py, "fsdecode"))?.call1((args.get_item(0)?,))?;
            return Ok(Some(s.call_method0(intern!(py, "split"))?.get_item(0)?));
        }
        if event.starts_with("os.spawn") {
            return Ok(Some(args.get_item(1)?));
        }
        if event == "os.posix_spawn" || event.starts_with("os.exec") {
            return Ok(Some(args.get_item(0)?));
        }
        Ok(None)
    })();
    let prog = match prog {
        Ok(p) => p,
        Err(e) if is_any(py, &e, &[index_err, type_err, value_err]) => None,
        Err(e) => return Err(e),
    };
    let named = match &prog {
        Some(p) => {
            p.is_instance_of::<PyString>()
                || p.is_instance_of::<PyBytes>()
                || p.is_instance(&os.getattr(intern!(py, "PathLike"))?)?
        }
        None => false,
    };
    match prog {
        Some(p) if named => {
            let s = os.getattr(intern!(py, "fsdecode"))?.call1((p,))?;
            let w = wtf8(s.cast::<PyString>()?)?;
            let base = match w.iter().rposition(|&c| c == b'/') {
                Some(i) => &w[i + 1..],
                None => &w[..],
            };
            Ok(base.to_vec())
        }
        _ => Ok(event.as_bytes().to_vec()),
    }
}

/// `_spawn_detail(event, args)`: the program a spawn event starts and where it was called from (the first frame
/// outside `detpy_dir` and the standard library).
pub(crate) fn spawn_detail(py: Python<'_>, detpy_dir: &[u8], event: &str, args: &Bound<'_, PyAny>) -> PyResult<W> {
    let mut d = spawn_prog(py, event, args)?;
    d.extend_from_slice(b" (");
    d.extend_from_slice(event.as_bytes());
    d.extend_from_slice(b") at ");
    d.extend_from_slice(&first_user_site(py, detpy_dir)?);
    Ok(d)
}

// ---------------------------------------------------------------------------------------------------------------
// For the tests

#[pyfunction]
fn cap_own_listener(py: Python<'_>, args: &Bound<'_, PyAny>) -> PyResult<bool> {
    own_listener(py, args)
}

#[pyfunction]
fn cap_both_ends_mine(py: Python<'_>, sock: &Bound<'_, PyAny>) -> PyResult<bool> {
    both_ends_mine(py, sock)
}

#[pyfunction]
fn cap_own_socket_inodes(py: Python<'_>) -> PyResult<Bound<'_, PySet>> {
    let s = PySet::empty(py)?;
    for i in own_socket_inodes() {
        s.add(from_wtf8(py, &i)?)?;
    }
    Ok(s)
}

#[pyfunction]
fn cap_loopback_hex(laddr: &Bound<'_, PyString>) -> PyResult<bool> {
    Ok(loopback_hex(&wtf8(laddr)?))
}

#[pyfunction]
fn cap_numeric_host(py: Python<'_>, host: &Bound<'_, PyString>) -> PyResult<bool> {
    numeric_host(py, host)
}

#[pyfunction]
fn cap_addr<'py>(py: Python<'py>, args: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyString>> {
    from_wtf8(py, &addr(py, args)?)
}

/// `_spawn_detail(event, args)` (`detpy_dir`: `proofcache._DETPY_DIR`); also the follower's, for a child that no
/// audit event announced.
#[pyfunction]
fn cap_spawn_detail<'py>(
    py: Python<'py>,
    detpy_dir: &Bound<'py, PyString>,
    event: &str,
    args: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyString>> {
    from_wtf8(py, &spawn_detail(py, &wtf8(detpy_dir)?, event, args)?)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(cap_own_listener, m)?)?;
    m.add_function(wrap_pyfunction!(cap_both_ends_mine, m)?)?;
    m.add_function(wrap_pyfunction!(cap_own_socket_inodes, m)?)?;
    m.add_function(wrap_pyfunction!(cap_loopback_hex, m)?)?;
    m.add_function(wrap_pyfunction!(cap_numeric_host, m)?)?;
    m.add_function(wrap_pyfunction!(cap_addr, m)?)?;
    m.add_function(wrap_pyfunction!(cap_spawn_detail, m)?)?;
    m.add_function(wrap_pyfunction!(set_xdist_controller_pid, m)?)?;
    Ok(())
}
