//! Level 0 closed network in Rust: the policy (local names, numeric hosts, local proxies, allowed hosts, the names
//! learnt from lookups, the fake addresses of replayed names, the replay counters), the connect / UDP / DNS
//! decisions, the recorded-stream bookkeeping and the cassette lookups.
//!
//! Port of `detpy/network.py` (`_is_local_name`, `_is_ip`, `_proxy_endpoints`, `_resolves_local`, `_Policy`,
//! `_blocked`, `_target`, `_connect_common`, `_connect`, `_connect_ex`, `_sendto`, `_dns_check`, `_getaddrinfo`,
//! `_gethostbyname[_ex]`, `_append` and the `_rec_*` wrappers, `_setsockopt`, `_getpeername`, the bookkeeping of
//! `_start_replay` and the `_conns` / `_replays` registries). The Python original is kept verbatim in
//! `tests/rust_hotpaths_ref/_ref_l0_network.py`; traces, cassettes, stores and receipts are tested byte-identical
//! against it (`tests/test_network_rust.py`). What stays Python is interface: the replay server thread on a
//! socketpair (`_attach_replay`, `_serve`), `ReplayTLSSocket`, `NetworkBlockedError`, `SSLContext.wrap_socket` (a
//! thin function calling the registries here) and the patching itself.
//!
//! The socket wrappers are real method descriptors of `_socket.socket` / `ssl.SSLSocket` (`PyDescr_NewMethod`): they
//! bind like the C methods they replace and run no Python frame. `getaddrinfo` (a Python function in `socket.py`)
//! is replaced by a callable that binds like a function, `gethostbyname[_ex]` (builtins) by callables that do not.
//!
//! `ipaddress.ip_address` is reproduced for strings (`parse_ip`; tested against the interpreter's on random and edge
//! inputs). The flags of an IPv4-mapped IPv6 address (`::ffff:a.b.c.d`), whose `is_loopback` / `is_unspecified`
//! changed between Python versions, are asked of the interpreter's `ipaddress`; so are a proxy URL's parts
//! (`urllib.parse.urlsplit`, once per session) and the `str.lower` of a non-ASCII string. Strings are handled as
//! bytes (`fsorder::wtf8`: lone surrogates included).

use crate::fsorder::{from_wtf8, wtf8};
use crate::level0::{record_from_rust, record_from_rust_obj, state_attr};
use crate::standin::bind;
use crate::{lock, Cassette};
use detpy_core::cassette::Direction;
use pyo3::exceptions::{PyKeyError, PyRuntimeError, PyTypeError, PyValueError};
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyByteArray, PyBytes, PyDict, PyFrozenSet, PyList, PySet, PyString, PyTuple, PyType,
                  PyWeakrefReference};
use std::borrow::Cow;
use std::collections::HashMap;
use std::ffi::CString;
use std::sync::{Arc, Mutex};

// ---------------------------------------------------------------------------------------------------------------
// `ipaddress.ip_address(str)`

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum Ip {
    V4(u32),
    V6(u128),
}

/// `IPv4Address._parse_octet`.
fn parse_octet(o: &[u8]) -> Option<u32> {
    if o.is_empty() || !o.iter().all(u8::is_ascii_digit) || o.len() > 3 || (o != b"0" && o[0] == b'0') {
        return None;
    }
    let v = o.iter().fold(0u32, |a, d| a * 10 + u32::from(d - b'0'));
    (v <= 255).then_some(v)
}

/// `IPv4Address(s)` (a `/` or any non-digit fails the octets).
fn parse_v4(s: &[u8]) -> Option<u32> {
    if s.is_empty() {
        return None;
    }
    let mut n = 0;
    let mut v = 0u32;
    for o in s.split(|&b| b == b'.') {
        n += 1;
        if n > 4 {
            return None;
        }
        v = (v << 8) | parse_octet(o)?;
    }
    (n == 4).then_some(v)
}

enum Part<'a> {
    Str(&'a [u8]),
    Num(u16),
}

impl Part<'_> {
    fn is_empty(&self) -> bool {
        matches!(self, Part::Str(s) if s.is_empty())
    }

    /// `IPv6Address._parse_hextet` (an empty hextet passes the digit check and fails `int(s, 16)`).
    fn hextet(&self) -> Option<u128> {
        match self {
            Part::Num(n) => Some(u128::from(*n)),
            Part::Str(s) => {
                if s.is_empty() || s.len() > 4 || !s.iter().all(u8::is_ascii_hexdigit) {
                    return None;
                }
                Some(s.iter().fold(0u128, |a, d| (a << 4) | u128::from((*d as char).to_digit(16).unwrap_or(0))))
            }
        }
    }
}

/// `IPv6Address(s)`: scope id split off (`%`, non-empty, no second `%`), then `_ip_int_from_string`.
fn parse_v6(s: &[u8]) -> Option<u128> {
    if s.contains(&b'/') {
        return None;
    }
    let addr = match s.iter().position(|&b| b == b'%') {
        None => s,
        Some(i) => {
            let scope = &s[i + 1..];
            if scope.is_empty() || scope.contains(&b'%') {
                return None;
            }
            &s[..i]
        }
    };
    // `len(ip_str) > 45` counts characters: a non-ASCII address fails the hextets anyway
    if addr.is_empty() || addr.len() > 45 {
        return None;
    }
    const HEXTETS: usize = 8;
    const MAX_PARTS: usize = HEXTETS + 1;
    // ip_str.split(':', maxsplit=9)
    let mut parts: Vec<Part> = Vec::with_capacity(MAX_PARTS + 1);
    let mut rest = addr;
    while parts.len() < MAX_PARTS {
        match rest.iter().position(|&b| b == b':') {
            Some(i) => {
                parts.push(Part::Str(&rest[..i]));
                rest = &rest[i + 1..];
            }
            None => break,
        }
    }
    parts.push(Part::Str(rest));
    if parts.len() < 3 {
        return None;
    }
    if let Some(Part::Str(last)) = parts.last() {
        if last.contains(&b'.') {
            let v4 = parse_v4(last)?;
            parts.pop();
            parts.push(Part::Num((v4 >> 16) as u16));
            parts.push(Part::Num((v4 & 0xFFFF) as u16));
        }
    }
    if parts.len() > MAX_PARTS {
        return None;
    }
    let n = parts.len();
    let mut skip = None;
    for (i, p) in parts.iter().enumerate().take(n - 1).skip(1) {
        if p.is_empty() {
            if skip.is_some() {
                return None;
            }
            skip = Some(i);
        }
    }
    let (hi, lo, skipped) = match skip {
        Some(si) => {
            let mut hi = si as isize;
            let mut lo = (n - si - 1) as isize;
            if parts[0].is_empty() {
                hi -= 1;
                if hi != 0 {
                    return None;
                }
            }
            if parts[n - 1].is_empty() {
                lo -= 1;
                if lo != 0 {
                    return None;
                }
            }
            let skipped = HEXTETS as isize - (hi + lo);
            if skipped < 1 {
                return None;
            }
            (hi as usize, lo as usize, skipped as u32)
        }
        None => {
            if n != HEXTETS || parts[0].is_empty() || parts[n - 1].is_empty() {
                return None;
            }
            (n, 0, 0)
        }
    };
    let mut v: u128 = 0;
    for p in &parts[..hi] {
        v = (v << 16) | p.hextet()?;
    }
    v = v.checked_shl(16 * skipped).unwrap_or(0);
    for p in &parts[n - lo..] {
        v = (v << 16) | p.hextet()?;
    }
    Some(v)
}

/// `ipaddress.ip_address(s)` for a string `s` (as bytes): the address, or None where it raises `ValueError`.
pub(crate) fn parse_ip(s: &[u8]) -> Option<Ip> {
    parse_v4(s).map(Ip::V4).or_else(|| parse_v6(s).map(Ip::V6))
}

/// What the policy asks of an address: `is_loopback`, `is_unspecified`, `ipv4_mapped.is_loopback`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Flags {
    loopback: bool,
    unspecified: bool,
    mapped_loopback: bool,
}

static IP_ADDRESS: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

/// The flags of `ipaddress.ip_address(s)`, None if `s` is not an address.
fn ip_flags(py: Python<'_>, s: &[u8]) -> PyResult<Option<Flags>> {
    Ok(match parse_ip(s) {
        None => None,
        Some(Ip::V4(v)) => Some(Flags { loopback: v >> 24 == 127, unspecified: v == 0, mapped_loopback: false }),
        Some(Ip::V6(v)) if v >> 32 == 0xFFFF => {
            // IPv4-mapped: the interpreter's own answer (3.13 delegates is_loopback / is_unspecified to the
            // mapped IPv4 address, earlier versions do not)
            let f = IP_ADDRESS.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
                Ok(py.import("ipaddress")?.getattr("ip_address")?.unbind())
            })?;
            let ip = f.bind(py).call1((from_wtf8(py, s)?,))?;
            let mapped = ip.getattr(intern!(py, "ipv4_mapped"))?;
            Some(Flags {
                loopback: ip.getattr(intern!(py, "is_loopback"))?.is_truthy()?,
                unspecified: ip.getattr(intern!(py, "is_unspecified"))?.is_truthy()?,
                mapped_loopback: !mapped.is_none() && mapped.getattr(intern!(py, "is_loopback"))?.is_truthy()?,
            })
        }
        Some(Ip::V6(v)) => Some(Flags { loopback: v == 1, unspecified: v == 0, mapped_loopback: false }),
    })
}

fn ip_address_obj<'py>(py: Python<'py>, s: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyAny>>> {
    let f = IP_ADDRESS.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
        Ok(py.import("ipaddress")?.getattr("ip_address")?.unbind())
    })?;
    match f.bind(py).call1((s,)) {
        Ok(ip) => Ok(Some(ip)),
        Err(e) if e.is_instance_of::<PyValueError>(py) => Ok(None),
        Err(e) => Err(e),
    }
}

// ---------------------------------------------------------------------------------------------------------------
// Names

const LOCAL_NAMES: [&[u8]; 5] = [b"localhost", b"localhost.localdomain", b"ip6-localhost", b"ip6-loopback", b""];

/// `s.lower()` of a string and its bytes: ASCII here, otherwise the interpreter's (full Unicode case mapping).
fn lower<'a>(py: Python<'_>, s: &Bound<'_, PyString>, b: &'a [u8]) -> PyResult<Cow<'a, [u8]>> {
    if b.is_ascii() {
        if b.iter().any(u8::is_ascii_uppercase) {
            return Ok(Cow::Owned(b.to_ascii_lowercase()));
        }
        return Ok(Cow::Borrowed(b));
    }
    let l = s.call_method0(intern!(py, "lower"))?;
    Ok(Cow::Owned(wtf8(l.cast::<PyString>()?)?.into_owned()))
}

fn lower_bytes(py: Python<'_>, b: &[u8]) -> PyResult<Vec<u8>> {
    if b.is_ascii() {
        return Ok(b.to_ascii_lowercase());
    }
    let s = from_wtf8(py, b)?;
    Ok(lower(py, &s, b)?.into_owned())
}

fn rstrip_dots(b: &[u8]) -> &[u8] {
    let mut e = b.len();
    while e > 0 && b[e - 1] == b'.' {
        e -= 1;
    }
    &b[..e]
}

fn before_percent(b: &[u8]) -> &[u8] {
    match b.iter().position(|&c| c == b'%') {
        Some(i) => &b[..i],
        None => b,
    }
}

/// `_is_local_name` on `h = host.lower().rstrip(".")`.
fn local_lowered(py: Python<'_>, h: &[u8]) -> PyResult<bool> {
    if LOCAL_NAMES.contains(&h) || h.ends_with(b".localhost") {
        return Ok(true);
    }
    Ok(ip_flags(py, before_percent(h))?.is_some_and(|f| f.loopback || f.unspecified))
}

/// `_is_local_name(host)` for a string.
fn is_local_str(py: Python<'_>, host: &Bound<'_, PyString>, b: &[u8]) -> PyResult<bool> {
    let l = lower(py, host, b)?;
    local_lowered(py, rstrip_dots(&l))
}

static LOCAL_SET: PyOnceLock<Py<PyFrozenSet>> = PyOnceLock::new();

/// `_is_local_name(host)` for any object: the original's operations, done by the interpreter for a host that is not a
/// string (an `int`: the same AttributeError; an object whose `lower()` returns something else: its own semantics).
fn is_local_any(py: Python<'_>, host: &Bound<'_, PyAny>) -> PyResult<bool> {
    if let Ok(s) = host.cast::<PyString>() {
        return is_local_str(py, s, &wtf8(s)?);
    }
    let h = host.call_method0(intern!(py, "lower"))?.call_method1(intern!(py, "rstrip"), (".",))?;
    if let Ok(s) = h.cast::<PyString>() {
        return local_lowered(py, &wtf8(s)?);
    }
    let names = LOCAL_SET.get_or_try_init(py, || -> PyResult<Py<PyFrozenSet>> {
        let names: Vec<&str> = LOCAL_NAMES.iter().map(|n| std::str::from_utf8(n).unwrap_or("")).collect();
        Ok(PyFrozenSet::new(py, names)?.unbind())
    })?;
    if names.bind(py).contains(&h)? || h.call_method1(intern!(py, "endswith"), (".localhost",))?.is_truthy()? {
        return Ok(true);
    }
    let part = h.call_method1(intern!(py, "split"), ("%", 1))?.get_item(0)?;
    match ip_address_obj(py, &part)? {
        Some(ip) => Ok(ip.getattr(intern!(py, "is_loopback"))?.is_truthy()?
            || ip.getattr(intern!(py, "is_unspecified"))?.is_truthy()?),
        None => Ok(false),
    }
}

/// `_is_ip(host)` for any object.
fn is_ip_any(py: Python<'_>, host: &Bound<'_, PyAny>) -> PyResult<bool> {
    if let Ok(s) = host.cast::<PyString>() {
        return Ok(parse_ip(before_percent(&wtf8(s)?)).is_some());
    }
    let part = host.call_method1(intern!(py, "split"), ("%", 1))?.get_item(0)?;
    Ok(ip_address_obj(py, &part)?.is_some())
}

/// `host.decode("ascii", "replace")`.
fn decode_ascii_replace(b: &[u8]) -> String {
    b.iter().map(|&c| if c < 0x80 { c as char } else { '\u{FFFD}' }).collect()
}

/// `f"{x}"` as bytes (an exact int written here).
fn fmt_bytes(py: Python<'_>, x: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    if let Some(i) = exact_int(x) {
        return Ok(i.to_string().into_bytes());
    }
    if let Ok(s) = x.cast::<PyString>() {
        if s.is_exact_instance_of::<PyString>() {
            return Ok(wtf8(s)?.into_owned());
        }
    }
    let empty = PyString::new(py, "");
    let f = unsafe { Bound::from_owned_ptr_or_err(py, ffi::PyObject_Format(x.as_ptr(), empty.as_ptr()))? };
    Ok(wtf8(f.cast::<PyString>()?)?.into_owned())
}

/// The value of an exact `int` that fits an i64.
fn exact_int(x: &Bound<'_, PyAny>) -> Option<i64> {
    if unsafe { ffi::PyLong_CheckExact(x.as_ptr()) } != 0 {
        x.extract::<i64>().ok()
    } else {
        None
    }
}

/// `int(x)`.
fn to_int<'py>(x: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    if unsafe { ffi::PyLong_CheckExact(x.as_ptr()) } != 0 {
        return Ok(x.clone());
    }
    unsafe { Bound::from_owned_ptr_or_err(x.py(), ffi::PyNumber_Long(x.as_ptr())) }
}

/// `"{a}:{b}{tail}"`.
fn join3(a: &[u8], b: &[u8], tail: &str) -> Vec<u8> {
    let mut v = Vec::with_capacity(a.len() + b.len() + tail.len() + 1);
    v.extend_from_slice(a);
    v.push(b':');
    v.extend_from_slice(b);
    v.extend_from_slice(tail.as_bytes());
    v
}

/// `_state.record("net", op, value)` for an event of the caller of a Rust wrapper.
fn record(py: Python<'_>, op: &str, value: Vec<u8>) -> PyResult<()> {
    match String::from_utf8(value) {
        Ok(s) => record_from_rust(py, "net", op, s, 0),
        Err(e) => record_from_rust_obj(py, "net", op, from_wtf8(py, e.as_bytes())?.as_any(), 0),
    }
}

// ---------------------------------------------------------------------------------------------------------------
// Module wiring

/// What the wrappers read: `detpy.network`'s globals (`POLICY`, `_real_*`, `socket`, `NetworkBlockedError`, ... read
/// at every call, as the Python functions read them) and the parts of a socket's `family` check.
struct Net {
    globals: Py<PyDict>,
    af_inet: Py<PyAny>,
    af_inet6: Py<PyAny>,
    af_inet_v: i64,
    af_inet6_v: i64,
    /// `socket.socket.family` (the property) and `_socket.socket.family` (the C member it converts)
    family_prop: Py<PyAny>,
    family_member: Py<PyAny>,
}

static NET: Mutex<Option<Arc<Net>>> = Mutex::new(None);

fn net() -> PyResult<Arc<Net>> {
    lock(&NET).clone().ok_or_else(|| PyRuntimeError::new_err("detpy.network not configured"))
}

impl Net {
    fn g<'py>(&self, py: Python<'py>, k: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
        self.globals
            .bind(py)
            .get_item(k)?
            .ok_or_else(|| pyo3::exceptions::PyNameError::new_err(format!("name '{k}' is not defined")))
    }

    fn policy<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, NetPolicy>>> {
        let p = self.g(py, intern!(py, "POLICY"))?;
        if p.is_none() {
            return Ok(None);
        }
        Ok(Some(p.cast_into::<NetPolicy>().map_err(|e| PyTypeError::new_err(e.to_string()))?))
    }

    /// `sock.family in (AF_INET, AF_INET6)`: the C member when the class keeps `socket.socket`'s property.
    fn is_inet(&self, py: Python<'_>, sock: &Bound<'_, PyAny>) -> PyResult<bool> {
        let fp = sock.get_type().getattr(intern!(py, "family"));
        if matches!(&fp, Ok(p) if p.is(self.family_prop.bind(py))) {
            let v = self.family_member.bind(py).call_method1(intern!(py, "__get__"), (sock,))?;
            if let Some(i) = exact_int(&v) {
                return Ok(i == self.af_inet_v || i == self.af_inet6_v);
            }
        }
        let fam = sock.getattr(intern!(py, "family"))?;
        Ok(fam.is(self.af_inet.bind(py))
            || fam.eq(self.af_inet.bind(py))?
            || fam.is(self.af_inet6.bind(py))
            || fam.eq(self.af_inet6.bind(py))?)
    }

    /// `_blocked(what)`.
    fn blocked(&self, py: Python<'_>, what: &[u8]) -> PyResult<PyErr> {
        let replay = matches!(self.policy(py)?, Some(p) if p.get().mode == Mode::Replay);
        let hint = if replay {
            "no recording for it in this test: re-run with --det-record"
        } else {
            "use --det-record to record real responses, or --det-allow-host to allow it"
        };
        let mut msg = b"detpy: network access to ".to_vec();
        msg.extend_from_slice(what);
        msg.extend_from_slice(b" blocked (Level 0 closes the network; localhost is allowed); ");
        msg.extend_from_slice(hint.as_bytes());
        let exc = self.g(py, intern!(py, "NetworkBlockedError"))?.call1((from_wtf8(py, &msg)?,))?;
        Ok(PyErr::from_value(exc))
    }
}

/// `net_configure(globals)`: wire the wrappers to `detpy.network`'s globals.
#[pyfunction]
fn net_configure(py: Python<'_>, globals: Bound<'_, PyDict>) -> PyResult<()> {
    let socket = py.import("socket")?;
    let csock = py.import("_socket")?.getattr("socket")?;
    let af_inet = socket.getattr("AF_INET")?;
    let af_inet6 = socket.getattr("AF_INET6")?;
    let get = |o: &Bound<'_, PyAny>, k: &str| -> PyResult<Py<PyAny>> {
        let d = o.getattr("__dict__")?;
        Ok(d.get_item(k)?.unbind())
    };
    let net = Net {
        globals: globals.unbind(),
        af_inet_v: af_inet.extract()?,
        af_inet6_v: af_inet6.extract()?,
        af_inet: af_inet.unbind(),
        af_inet6: af_inet6.unbind(),
        family_prop: get(&socket.getattr("socket")?, "family")?,
        family_member: get(&csock, "family")?,
    };
    *lock(&NET) = Some(Arc::new(net));
    Ok(())
}

// ---------------------------------------------------------------------------------------------------------------
// Registries (`_conns`, `_replays`): weak, by identity, like the WeakKeyDictionaries of the original

struct Weak<V> {
    map: HashMap<usize, (Py<PyWeakrefReference>, V)>,
}

impl<V> Weak<V> {
    fn new() -> Self {
        Weak { map: HashMap::new() }
    }
}

fn weak_get<V: Clone>(reg: &Mutex<Option<Weak<V>>>, obj: &Bound<'_, PyAny>) -> Option<V> {
    let mut g = lock(reg);
    let w = g.as_mut()?;
    let k = obj.as_ptr() as usize;
    let (r, v) = w.map.get(&k)?;
    if r.bind(obj.py()).upgrade().is_some_and(|o| o.is(obj)) {
        return Some(v.clone());
    }
    w.map.remove(&k);
    None
}

fn weak_set<V>(reg: &Mutex<Option<Weak<V>>>, obj: &Bound<'_, PyAny>, v: V) -> PyResult<()> {
    let r = PyWeakrefReference::new(obj)?.unbind();
    let py = obj.py();
    let mut g = lock(reg);
    let w = g.get_or_insert_with(Weak::new);
    if w.map.len() >= 64 && w.map.len().is_power_of_two() {
        w.map.retain(|_, (r, _)| r.bind(py).upgrade().is_some());
    }
    w.map.insert(obj.as_ptr() as usize, (r, v));
    Ok(())
}

/// A recorded connection: `(nodeid, idx)`.
#[derive(Clone)]
struct Conn {
    nodeid: Arc<Py<PyAny>>,
    nodeid_s: Option<Arc<str>>,
    idx: usize,
}

static CONNS: Mutex<Option<Weak<Conn>>> = Mutex::new(None);
/// replayed socket -> label `host:port#idx` (as bytes)
static REPLAYS: Mutex<Option<Weak<Arc<[u8]>>>> = Mutex::new(None);

fn conn_tuple<'py>(py: Python<'py>, c: &Conn) -> PyResult<Bound<'py, PyTuple>> {
    PyTuple::new(py, [c.nodeid.bind(py).clone(), c.idx.into_pyobject(py)?.into_any()])
}

/// `_conns.get(sock)` as the tuple `(nodeid, idx)`.
#[pyfunction]
fn net_conn_of<'py>(py: Python<'py>, sock: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyTuple>>> {
    match weak_get(&CONNS, sock) {
        Some(c) => Ok(Some(conn_tuple(py, &c)?)),
        None => {
            // like WeakKeyDictionary.get: a key that cannot be weakly referenced is a TypeError
            PyWeakrefReference::new(sock)?;
            Ok(None)
        }
    }
}

/// `_conns[ssl_sock] = entry; POLICY.cassette.set_tls(*entry)`.
#[pyfunction]
fn net_conn_tls(py: Python<'_>, ssl_sock: &Bound<'_, PyAny>, entry: &Bound<'_, PyTuple>) -> PyResult<()> {
    let nodeid = entry.get_item(0)?;
    let idx_o = entry.get_item(1)?;
    let idx: usize = idx_o.extract()?;
    let nodeid_s = nodeid.cast::<PyString>().ok().and_then(|s| s.to_cow().ok().map(|c| Arc::from(c.as_ref())));
    weak_set(&CONNS, ssl_sock, Conn { nodeid: Arc::new(nodeid.clone().unbind()), nodeid_s, idx })?;
    let n = net()?;
    match n.policy(py)? {
        Some(p) => p.get().cassette_obj(py).call_method1(intern!(py, "set_tls"), (nodeid, idx_o))?,
        None => py.None().into_bound(py).getattr("cassette")?,
    };
    Ok(())
}

/// `_replays[sock] = label`.
#[pyfunction]
fn net_set_replay(sock: &Bound<'_, PyAny>, label: &Bound<'_, PyString>) -> PyResult<()> {
    weak_set(&REPLAYS, sock, Arc::from(wtf8(label)?.as_ref()))
}

/// `sock in _replays`.
#[pyfunction]
fn net_is_replayed(sock: &Bound<'_, PyAny>) -> bool {
    weak_get(&REPLAYS, sock).is_some()
}

// ---------------------------------------------------------------------------------------------------------------
// The policy

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Mode {
    Block,
    Record,
    Replay,
    Other,
}

#[derive(Default)]
struct Maps {
    host_of_ip: HashMap<Vec<u8>, Vec<u8>>,
    fake_ip_of: HashMap<Vec<u8>, String>,
    /// the keys of `fake_ip_of` in insertion order (the dict view)
    fake_order: Vec<Vec<u8>>,
    host_of_fake: HashMap<String, Vec<u8>>,
    counters: HashMap<(Vec<u8>, u16), usize>,
    /// the keys of `counters` in insertion order
    counter_order: Vec<(Vec<u8>, u16)>,
}

/// `network._Policy(mode, cassette, allow_hosts)`.
#[pyclass(module = "detpy._core", name = "NetPolicy", frozen)]
pub(crate) struct NetPolicy {
    mode: Mode,
    mode_obj: Py<PyAny>,
    cassette: Option<Py<Cassette>>,
    allow: Vec<Vec<u8>>,
    allow_obj: Py<PySet>,
    /// `(host or "*", port)`; `proxies_plain` false when an entry is not `(str, int)`: the set itself then decides
    proxies: Vec<(Vec<u8>, i64)>,
    proxies_plain: bool,
    proxies_obj: Py<PySet>,
    maps: Mutex<Maps>,
    mismatches: Mutex<Py<PyList>>,
}

impl NetPolicy {
    fn cassette_obj<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        match &self.cassette {
            Some(c) => c.bind(py).clone().into_any(),
            None => py.None().into_bound(py),
        }
    }

    /// `self.hostname(host)` as bytes.
    fn hostname_b(&self, host: &[u8]) -> Vec<u8> {
        let m = lock(&self.maps);
        if let Ok(s) = std::str::from_utf8(host) {
            if let Some(h) = m.host_of_fake.get(s).filter(|h| !h.is_empty()) {
                return h.clone();
            }
        }
        if let Some(h) = m.host_of_ip.get(host).filter(|h| !h.is_empty()) {
            return h.clone();
        }
        host.to_vec()
    }

    /// `self.external(host, port)`.
    fn external_b(
        &self,
        py: Python<'_>,
        host: &Bound<'_, PyString>,
        hb: &[u8],
        port: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        let mut local: Option<bool> = None;
        let pint = exact_int(port);
        if !self.proxies_plain || pint.is_none() {
            // the set's own hashing and equality (a port that is not an int: float, bool, unhashable...)
            let set = self.proxies_obj.bind(py);
            let hl = host.call_method0(intern!(py, "lower"))?;
            if set.contains((hl, port))? {
                return Ok(true);
            }
            if set.contains(("*", port))? {
                let l = is_local_str(py, host, hb)?;
                local = Some(l);
                if l {
                    return Ok(true);
                }
            }
        } else if !self.proxies.is_empty() {
            let p = pint.unwrap_or(-1);
            let hl = lower(py, host, hb)?;
            if self.proxies.iter().any(|(h, pp)| *pp == p && h.as_slice() == hl.as_ref()) {
                return Ok(true);
            }
            if self.proxies.iter().any(|(h, pp)| *pp == p && h == b"*") {
                let l = is_local_str(py, host, hb)?;
                local = Some(l);
                if l {
                    return Ok(true);
                }
            }
        }
        let l = match local {
            Some(l) => l,
            None => is_local_str(py, host, hb)?,
        };
        if l {
            return Ok(false);
        }
        let name = self.hostname_b(hb);
        let low = lower_bytes(py, &name)?;
        Ok(!self.allow.iter().any(|a| a == &low))
    }

    /// `self.fake_ip(host)`.
    fn fake_ip_b(&self, host: &[u8]) -> String {
        let mut m = lock(&self.maps);
        if let Some(ip) = m.fake_ip_of.get(host) {
            return ip.clone();
        }
        let n = m.fake_ip_of.len() + 1;
        let ip = format!("198.18.{}.{}", n / 250, n % 250 + 1);
        m.fake_ip_of.insert(host.to_vec(), ip.clone());
        m.fake_order.push(host.to_vec());
        m.host_of_fake.insert(ip.clone(), host.to_vec());
        ip
    }

    /// `self.has_recording(host)` for a string host.
    fn has_recording_b(&self, py: Python<'_>, host: &Bound<'_, PyAny>) -> PyResult<bool> {
        let Some(c) = &self.cassette else { return Ok(false) };
        let nodeid = state_attr(py, intern!(py, "nodeid"))?;
        if nodeid.is_none() {
            return Ok(false);
        }
        let hs = host.cast::<PyString>().ok();
        if let (Ok(n), Some(h)) = (nodeid.cast::<PyString>(), hs) {
            if let Ok(n) = n.to_cow() {
                let n: &str = &n;
                let hb = wtf8(h)?;
                let r = c.bind(py).borrow();
                let cas = lock(&r.inner);
                return Ok(cas.tests.get(n).is_some_and(|v| v.iter().any(|conn| conn.host.as_bytes() == hb.as_ref())));
            }
        }
        // the interpreter's comparisons (and the cassette's own errors for a node id it cannot take)
        let c = c.bind(py);
        let mut i = 0usize;
        loop {
            match c.call_method1(intern!(py, "info"), (&nodeid, i)) {
                Ok(info) => {
                    if info.get_item(0)?.eq(host)? {
                        return Ok(true);
                    }
                }
                Err(e) if e.is_instance_of::<PyKeyError>(py) => return Ok(false),
                Err(e) => return Err(e),
            }
            i += 1;
        }
    }
}

fn parse_mode(m: &Bound<'_, PyAny>) -> Mode {
    match m.cast::<PyString>().ok().and_then(|s| s.to_cow().ok()).as_deref() {
        Some("block") => Mode::Block,
        Some("record") => Mode::Record,
        Some("replay") => Mode::Replay,
        _ => Mode::Other,
    }
}

#[pymethods]
impl NetPolicy {
    #[new]
    fn new(
        py: Python<'_>,
        mode: Bound<'_, PyAny>,
        cassette: Option<Py<Cassette>>,
        allow_hosts: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        let allow_obj = PySet::empty(py)?;
        let mut allow = Vec::new();
        for h in allow_hosts.try_iter()? {
            let l = h?.call_method0(intern!(py, "lower"))?;
            if let Ok(s) = l.cast::<PyString>() {
                allow.push(wtf8(s)?.into_owned());
            }
            allow_obj.add(l)?;
        }
        let n = net()?;
        let proxies_obj = n.g(py, intern!(py, "_proxy_endpoints"))?.call0()?;
        let proxies_obj = match proxies_obj.cast_into::<PySet>() {
            Ok(s) => s,
            Err(e) => PySet::new(py, e.into_inner().try_iter()?.collect::<PyResult<Vec<_>>>()?)?,
        };
        let mut proxies = Vec::new();
        let mut plain = true;
        for e in proxies_obj.iter() {
            let ok = (|| -> PyResult<Option<(Vec<u8>, i64)>> {
                let t = e.cast::<PyTuple>()?;
                if t.len() != 2 {
                    return Ok(None);
                }
                let (h, p) = (t.get_item(0)?, t.get_item(1)?);
                let (Ok(h), Some(p)) = (h.cast::<PyString>(), exact_int(&p)) else { return Ok(None) };
                Ok(Some((wtf8(h)?.into_owned(), p)))
            })();
            match ok {
                Ok(Some(x)) => proxies.push(x),
                _ => plain = false,
            }
        }
        Ok(NetPolicy {
            mode: parse_mode(&mode),
            mode_obj: mode.unbind(),
            cassette,
            allow,
            allow_obj: allow_obj.unbind(),
            proxies,
            proxies_plain: plain,
            proxies_obj: proxies_obj.unbind(),
            maps: Mutex::new(Maps::default()),
            mismatches: Mutex::new(PyList::empty(py).unbind()),
        })
    }

    #[getter]
    fn mode(&self, py: Python<'_>) -> Py<PyAny> {
        self.mode_obj.clone_ref(py)
    }

    #[getter]
    fn cassette(&self, py: Python<'_>) -> Py<PyAny> {
        self.cassette_obj(py).unbind()
    }

    #[getter]
    fn allow(&self, py: Python<'_>) -> Py<PySet> {
        self.allow_obj.clone_ref(py)
    }

    #[getter]
    fn proxies(&self, py: Python<'_>) -> Py<PySet> {
        self.proxies_obj.clone_ref(py)
    }

    #[getter]
    fn mismatches(&self, py: Python<'_>) -> Py<PyList> {
        lock(&self.mismatches).clone_ref(py)
    }

    /// A copy of `host_of_ip`.
    #[getter]
    fn host_of_ip<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        for (k, v) in lock(&self.maps).host_of_ip.iter() {
            d.set_item(from_wtf8(py, k)?, from_wtf8(py, v)?)?;
        }
        Ok(d)
    }

    /// A copy of `fake_ip_of` (in insertion order).
    #[getter]
    fn fake_ip_of<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        let m = lock(&self.maps);
        for k in &m.fake_order {
            d.set_item(from_wtf8(py, k)?, &m.fake_ip_of[k])?;
        }
        Ok(d)
    }

    /// A copy of `counters` (in insertion order).
    #[getter]
    fn counters<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        let m = lock(&self.maps);
        for k in &m.counter_order {
            d.set_item((from_wtf8(py, &k.0)?, k.1), m.counters[k])?;
        }
        Ok(d)
    }

    fn start_test(&self, py: Python<'_>) {
        {
            let mut m = lock(&self.maps);
            m.counters.clear();
            m.counter_order.clear();
        }
        let old = std::mem::replace(&mut *lock(&self.mismatches), PyList::empty(py).unbind());
        drop(old);
    }

    fn hostname<'py>(&self, py: Python<'py>, host: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyString>> {
        let hb = wtf8(host)?;
        from_wtf8(py, &self.hostname_b(&hb))
    }

    fn external(&self, py: Python<'_>, host: &Bound<'_, PyString>, port: &Bound<'_, PyAny>) -> PyResult<bool> {
        let hb = wtf8(host)?;
        self.external_b(py, host, &hb, port)
    }

    fn has_recording(&self, py: Python<'_>, host: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.has_recording_b(py, host)
    }

    fn fake_ip(&self, host: &Bound<'_, PyString>) -> PyResult<String> {
        Ok(self.fake_ip_b(&wtf8(host)?))
    }
}

// ---------------------------------------------------------------------------------------------------------------
// Pure helpers (`_is_local_name`, `_is_ip`, `_resolves_local`, `_proxy_endpoints`, `_blocked`)

/// `_is_local_name(host)`.
#[pyfunction]
fn net_is_local_name(py: Python<'_>, host: &Bound<'_, PyAny>) -> PyResult<bool> {
    is_local_any(py, host)
}

/// `_is_ip(host)`.
#[pyfunction]
fn net_is_ip(py: Python<'_>, host: &Bound<'_, PyAny>) -> PyResult<bool> {
    is_ip_any(py, host)
}

/// `ipaddress.ip_address(s)` for a string: `(4 or 6, int)` or None (for the tests).
#[pyfunction]
fn net_ip_address(s: &Bound<'_, PyString>) -> PyResult<Option<(u8, u128)>> {
    Ok(match parse_ip(&wtf8(s)?) {
        Some(Ip::V4(v)) => Some((4, u128::from(v))),
        Some(Ip::V6(v)) => Some((6, v)),
        None => None,
    })
}

/// `(is_loopback, is_unspecified, ipv4_mapped is not None and ipv4_mapped.is_loopback)` of `ip_address(s)`, None if
/// not an address (for the tests).
#[pyfunction]
fn net_ip_flags(py: Python<'_>, s: &Bound<'_, PyString>) -> PyResult<Option<(bool, bool, bool)>> {
    Ok(ip_flags(py, &wtf8(s)?)?.map(|f| (f.loopback, f.unspecified, f.mapped_loopback)))
}

/// `_resolves_local(host, port)`: a proxy name other than localhost that maps to loopback, or that cannot be resolved
/// here (conservatively local). The lookup is a real one, through `network._real_getaddrinfo` read at call time.
#[pyfunction]
fn net_resolves_local(py: Python<'_>, host: &Bound<'_, PyAny>, port: &Bound<'_, PyAny>) -> PyResult<bool> {
    if is_ip_any(py, host)? {
        return Ok(false);
    }
    let n = net()?;
    let socket = n.g(py, intern!(py, "socket"))?;
    let kw = PyDict::new(py);
    kw.set_item("proto", socket.getattr(intern!(py, "IPPROTO_TCP"))?)?;
    let infos = match n.g(py, intern!(py, "_real_getaddrinfo"))?.call((host, port), Some(&kw)) {
        Ok(i) => i,
        Err(e) if e.is_instance_of::<pyo3::exceptions::PyOSError>(py)
            || e.is_instance_of::<pyo3::exceptions::PyUnicodeError>(py) =>
        {
            return Ok(true)
        }
        Err(e) => return Err(e),
    };
    for info in infos.try_iter()? {
        let a = info?.get_item(4)?.get_item(0)?.str()?;
        let Some(f) = ip_flags(py, before_percent(&wtf8(&a)?))? else { continue };
        if f.loopback || f.unspecified || f.mapped_loopback {
            return Ok(true);
        }
    }
    Ok(!infos.is_truthy()?)
}

const PROXY_VARS: [&str; 6] = ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"];

/// `_proxy_endpoints()`: `{(host, port), ("*", port)}` of the local HTTP(S) proxies of the `*_PROXY` variables. The URL
/// is split by the interpreter's `urlsplit` (`network.urlsplit`); `_resolves_local` is read from the module.
#[pyfunction]
fn net_proxy_endpoints(py: Python<'_>) -> PyResult<Bound<'_, PySet>> {
    let n = net()?;
    let out = PySet::empty(py)?;
    let environ = n.g(py, intern!(py, "os"))?.getattr(intern!(py, "environ"))?;
    let urlsplit = n.g(py, intern!(py, "urlsplit"))?;
    for var in PROXY_VARS {
        let val = environ.call_method1(intern!(py, "get"), (var,))?;
        if !val.is_truthy()? {
            continue;
        }
        let parsed = (|| -> PyResult<(Bound<'_, PyAny>, Bound<'_, PyAny>)> {
            let has = val.call_method1(intern!(py, "__contains__"), ("://",))?.is_truthy()?;
            let url = if has { val.clone() } else { PyString::new(py, "http://").add(&val)? };
            let parts = urlsplit.call1((url,))?;
            let port = parts.getattr(intern!(py, "port"))?;
            let port = if port.is_truthy()? {
                port
            } else {
                let scheme = parts.getattr(intern!(py, "scheme"))?;
                let d: i32 = match scheme.cast::<PyString>().ok().and_then(|s| s.to_cow().ok()).as_deref() {
                    Some("https") => 443,
                    Some("socks5") | Some("socks5h") => 1080,
                    _ => 80,
                };
                d.into_pyobject(py)?.into_any()
            };
            Ok((parts, port))
        })();
        let (parts, port) = match parsed {
            Ok(x) => x,
            Err(e) if e.is_instance_of::<PyValueError>(py) => continue,
            Err(e) => return Err(e),
        };
        let hn = parts.getattr(intern!(py, "hostname"))?;
        let hn = if hn.is_truthy()? { hn } else { PyString::new(py, "").into_any() };
        let host = hn.call_method0(intern!(py, "lower"))?;
        if host.is_truthy()?
            && (is_local_any(py, &host)?
                || n.g(py, intern!(py, "_resolves_local"))?.call1((&host, &port))?.is_truthy()?)
        {
            out.add(("*", &port))?;
            out.add((&host, &port))?;
        }
    }
    Ok(out)
}

/// `_blocked(what)`: the `NetworkBlockedError` for an access to `what`.
#[pyfunction]
fn net_blocked<'py>(py: Python<'py>, what: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let n = net()?;
    let e = n.blocked(py, &fmt_bytes(py, what)?)?;
    Ok(e.into_value(py).into_bound(py).into_any())
}

// ---------------------------------------------------------------------------------------------------------------
// Connections

/// `_target(sock, address)`: `(hostname, port)` of an external endpoint, else None (host as bytes).
fn target<'py>(
    py: Python<'py>,
    n: &Net,
    pol: &NetPolicy,
    sock: &Bound<'py, PyAny>,
    address: &Bound<'py, PyAny>,
) -> PyResult<Option<(Vec<u8>, Bound<'py, PyAny>)>> {
    if !n.is_inet(py, sock)? {
        return Ok(None);
    }
    let Ok(t) = address.cast::<PyTuple>() else { return Ok(None) };
    let (host, port) = if t.is_exact_instance_of::<PyTuple>() {
        if t.len() < 2 {
            return Ok(None);
        }
        (t.get_item(0)?, t.get_item(1)?)
    } else {
        if address.len()? < 2 {
            return Ok(None);
        }
        (address.get_item(0)?, address.get_item(1)?)
    };
    let host = if let Ok(b) = host.cast::<PyBytes>() {
        PyString::new(py, &decode_ascii_replace(b.as_bytes())).into_any()
    } else {
        host
    };
    let Ok(hs) = host.cast::<PyString>() else { return Ok(None) };
    let hb = wtf8(hs)?;
    if !pol.external_b(py, hs, &hb, &port)? {
        return Ok(None);
    }
    Ok(Some((pol.hostname_b(&hb), port)))
}

/// `_target(sock, address)` (for the tests).
#[pyfunction]
fn net_target<'py>(
    py: Python<'py>,
    sock: &Bound<'py, PyAny>,
    address: &Bound<'py, PyAny>,
) -> PyResult<Option<(Bound<'py, PyString>, Bound<'py, PyAny>)>> {
    let n = net()?;
    let Some(pol) = n.policy(py)? else { return Ok(None) };
    Ok(match target(py, &n, pol.get(), sock, address)? {
        Some((h, p)) => Some((from_wtf8(py, &h)?, p)),
        None => None,
    })
}

fn cassette_open(
    py: Python<'_>,
    pol: &NetPolicy,
    nodeid: &Bound<'_, PyAny>,
    host: &[u8],
    port: &Bound<'_, PyAny>,
) -> PyResult<Conn> {
    if let (Some(c), Ok(Ok(ns)), Ok(h), Ok(p)) = (
        &pol.cassette,
        nodeid.cast::<PyString>().map(|s| s.to_cow()),
        std::str::from_utf8(host),
        port.extract::<u16>(),
    ) {
        let idx = lock(&c.bind(py).borrow().inner).open(&ns, h, p);
        return Ok(Conn { nodeid: Arc::new(nodeid.clone().unbind()), nodeid_s: Some(Arc::from(ns.as_ref())), idx });
    }
    let idx = pol.cassette_obj(py).call_method1(
        intern!(py, "open_connection"),
        (nodeid, from_wtf8(py, host)?, port),
    )?;
    let nodeid_s = nodeid.cast::<PyString>().ok().and_then(|s| s.to_cow().ok().map(|c| Arc::from(c.as_ref())));
    Ok(Conn { nodeid: Arc::new(nodeid.clone().unbind()), nodeid_s, idx: idx.extract()? })
}

/// The replay of `_start_replay`: the next recorded connection of this test to `host:port`, attached by
/// `network._attach_replay` (socketpair, server thread). False if there is none.
fn start_replay(
    py: Python<'_>,
    n: &Net,
    pol: &NetPolicy,
    sock: &Bound<'_, PyAny>,
    host: &[u8],
    port: &Bound<'_, PyAny>,
    nodeid: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let fast = match (&pol.cassette, nodeid.cast::<PyString>(), std::str::from_utf8(host), port.extract::<u16>()) {
        (Some(c), Ok(ns), Ok(h), Ok(p)) => ns.to_cow().ok().map(|ns| (c, ns, h, p)),
        _ => None,
    };
    let (idx, segments) = match fast {
        Some((c, ns, h, p)) => {
            let key = (host.to_vec(), p);
            let nth = lock(&pol.maps).counters.get(&key).copied().unwrap_or(0);
            let r = c.bind(py).borrow();
            let cas = lock(&r.inner);
            let Some((idx, conn)) = cas.find(&ns, h, p, nth) else { return Ok(false) };
            {
                let mut m = lock(&pol.maps);
                if m.counters.insert(key.clone(), nth + 1).is_none() {
                    m.counter_order.push(key);
                }
            }
            let segs: Vec<(&str, Bound<'_, PyBytes>)> =
                conn.segments.iter().map(|s| (s.dir.as_str(), PyBytes::new(py, &s.data))).collect();
            (idx, PyList::new(py, segs)?)
        }
        None => {
            // what the cassette methods say about arguments they cannot take (or a missing cassette)
            let c = pol.cassette_obj(py);
            let h = from_wtf8(py, host)?;
            let idx = c.call_method1(intern!(py, "find"), (nodeid, &h, port, 0))?;
            if idx.is_none() {
                return Ok(false);
            }
            let segs = c.call_method1(intern!(py, "segments"), (nodeid, &idx))?;
            (idx.extract()?, segs.cast_into::<PyList>().map_err(|e| PyTypeError::new_err(e.to_string()))?)
        }
    };
    let pb = fmt_bytes(py, port)?;
    let label = join3(host, &pb, &format!("#{idx}"));
    let mismatches = lock(&pol.mismatches).clone_ref(py);
    n.g(py, intern!(py, "_attach_replay"))?.call1((sock, segments, from_wtf8(py, &label)?, mismatches))?;
    record(py, "socket.connect", join3(host, &pb, &format!(" replay#{idx}")))?;
    Ok(true)
}

/// `_connect_common(sock, address, real)`.
fn connect_common<'py>(
    py: Python<'py>,
    sock: &Bound<'py, PyAny>,
    address: &Bound<'py, PyAny>,
    ex: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let n = net()?;
    let real_key = if ex { intern!(py, "_real_connect_ex") } else { intern!(py, "_real_connect") };
    let real = n.g(py, real_key)?;
    let Some(pol) = n.policy(py)? else { return real.call1((sock, address)) };
    let pol = pol.get();
    let Some((host, port)) = target(py, &n, pol, sock, address)? else { return real.call1((sock, address)) };
    let mode = pol.mode;
    let nodeid = state_attr(py, intern!(py, "nodeid"))?;
    if mode == Mode::Record {
        if nodeid.is_none() {
            return real.call1((sock, address));
        }
        let result = real.call1((sock, address))?;
        let p = to_int(&port)?;
        let conn = cassette_open(py, pol, &nodeid, &host, &p)?;
        let idx = conn.idx;
        weak_set(&CONNS, sock, conn)?;
        record(py, "socket.connect", join3(&host, &fmt_bytes(py, &port)?, &format!(" record#{idx}")))?;
        return Ok(result);
    }
    if mode == Mode::Replay && !nodeid.is_none() && start_replay(py, &n, pol, sock, &host, &to_int(&port)?, &nodeid)? {
        return Ok(if real.is(&n.g(py, intern!(py, "_real_connect_ex"))?) {
            0i32.into_pyobject(py)?.into_any()
        } else {
            py.None().into_bound(py)
        });
    }
    let pb = fmt_bytes(py, &port)?;
    record(py, "socket.connect", join3(&host, &pb, " blocked"))?;
    Err(n.blocked(py, &join3(&host, &pb, ""))?)
}

// ---------------------------------------------------------------------------------------------------------------
// Recording (`_append` and the `_rec_*` wrappers)

/// What a wrapper appends: `data` itself, or `memoryview(data)[:n]`.
enum Payload<'a, 'py> {
    Whole(&'a Bound<'py, PyAny>),
    Prefix(&'a Bound<'py, PyAny>, &'a Bound<'py, PyAny>),
}

/// `bytes(data)` if `data` is truthy, else None.
fn payload_bytes(py: Python<'_>, p: Payload<'_, '_>) -> PyResult<Option<Vec<u8>>> {
    let (obj, n) = match p {
        Payload::Whole(o) => (o, None),
        Payload::Prefix(o, n) => (o, Some(n)),
    };
    let raw: Option<Vec<u8>> = if let Ok(b) = obj.cast::<PyBytes>() {
        Some(b.as_bytes().to_vec())
    } else if let Ok(b) = obj.cast::<PyByteArray>() {
        Some(b.to_vec())
    } else {
        None
    };
    match (raw, n) {
        (Some(mut v), None) => Ok((!v.is_empty()).then(|| std::mem::take(&mut v))),
        (Some(mut v), Some(n)) if exact_int(n).is_some_and(|k| k >= 0) => {
            let k = exact_int(n).unwrap_or(0) as usize;
            v.truncate(k);
            Ok((!v.is_empty()).then_some(v))
        }
        _ => {
            // the interpreter's buffer views (formats with items wider than a byte, negative ends...)
            let view = match n {
                None => obj.clone(),
                Some(n) => {
                    let b = py.import("builtins")?;
                    let mv = b.getattr("memoryview")?.call1((obj,))?;
                    mv.get_item(b.getattr("slice")?.call1((py.None(), n))?)?
                }
            };
            if !view.is_truthy()? {
                return Ok(None);
            }
            let b = py.import("builtins")?.getattr("bytes")?.call1((view,))?;
            Ok(Some(b.cast::<PyBytes>()?.as_bytes().to_vec()))
        }
    }
}

/// `_append(sock, direction, data)`.
fn append(py: Python<'_>, n: &Net, sock: &Bound<'_, PyAny>, dir: Direction, p: Payload<'_, '_>) -> PyResult<()> {
    let Some(conn) = weak_get(&CONNS, sock) else { return Ok(()) };
    let Some(data) = payload_bytes(py, p)? else { return Ok(()) };
    let pol = n.policy(py)?;
    let Some(pol) = pol else {
        py.None().into_bound(py).getattr("cassette")?;
        return Ok(());
    };
    let pol = pol.get();
    if let (Some(c), Some(ns)) = (&pol.cassette, &conn.nodeid_s) {
        let r = c.bind(py).borrow();
        let mut cas = lock(&r.inner);
        let k = cas.connection_mut(ns, conn.idx).ok_or_else(|| PyKeyError::new_err(format!("{ns}#{}", conn.idx)))?;
        k.append(dir, &data);
        return Ok(());
    }
    pol.cassette_obj(py).call_method1(
        intern!(py, "append"),
        (conn.nodeid.bind(py), conn.idx, dir.as_str(), PyBytes::new(py, &data)),
    )?;
    Ok(())
}

// ---------------------------------------------------------------------------------------------------------------
// The socket methods: method descriptors whose C function is one of these

type Args<'a, 'py> = (&'a Bound<'py, PyAny>, &'a Bound<'py, PyTuple>, Option<&'a Bound<'py, PyDict>>);

/// The parameters of a wrapper `def f(self, ...)`: `(self, *args)` with `**kwargs` bound to `names` (the first is
/// `self`), the interpreter's errors under the original function's name.
fn params<'py, const N: usize>(
    fname: &str,
    names: [&str; N],
    required: usize,
    (slf, args, kwargs): Args<'_, 'py>,
) -> PyResult<[Option<Bound<'py, PyAny>>; N]> {
    let given = args.len() + 1;
    if kwargs.is_none_or(|k| k.is_empty()) && given <= N && given >= required {
        let mut out: [Option<Bound<'py, PyAny>>; N] = std::array::from_fn(|_| None);
        out[0] = Some(slf.clone());
        for (i, a) in args.iter().enumerate() {
            out[i + 1] = Some(a);
        }
        return Ok(out);
    }
    let full: Vec<Bound<'py, PyAny>> = std::iter::once(slf.clone()).chain(args.iter()).collect();
    let full = PyTuple::new(slf.py(), full)?;
    bind(fname, names, required, &full, kwargs)
}

/// `(data, args)` of a `def f(self, data, *args)`.
type Star<'py> = (Option<Bound<'py, PyAny>>, Vec<Bound<'py, PyAny>>);

/// `def f(self, *args)` / `def f(self, data, *args)`: keywords are errors (except a `data` not given positionally).
fn star_params<'py>(fname: &str, with_data: bool, (_, args, kwargs): Args<'_, 'py>) -> PyResult<Star<'py>> {
    let mut rest: Vec<Bound<'py, PyAny>> = args.iter().collect();
    let mut data = None;
    if with_data && !rest.is_empty() {
        data = Some(rest.remove(0));
    }
    if let Some(kw) = kwargs {
        for (k, v) in kw.iter() {
            let key =
                k.cast::<PyString>().map_err(|_| PyTypeError::new_err(format!("{fname}() keywords must be strings")))?;
            let key = key.to_cow()?;
            if key == "self" || (with_data && key == "data" && data.is_some()) {
                return Err(PyTypeError::new_err(format!("{fname}() got multiple values for argument '{key}'")));
            }
            if with_data && key == "data" {
                data = Some(v);
                continue;
            }
            return Err(PyTypeError::new_err(format!("{fname}() got an unexpected keyword argument '{key}'")));
        }
    }
    if with_data && data.is_none() {
        return Err(PyTypeError::new_err(format!("{fname}() missing 1 required positional argument: 'data'")));
    }
    Ok((data, rest))
}

fn zero(py: Python<'_>) -> Bound<'_, PyAny> {
    0i32.into_pyobject(py).map(|o| o.into_any()).unwrap_or_else(|_| py.None().into_bound(py))
}

fn m_connect<'py>(py: Python<'py>, a: Args<'_, 'py>, ex: bool) -> PyResult<Bound<'py, PyAny>> {
    let fname = if ex { "_connect_ex" } else { "_connect" };
    let [slf, address] = params(fname, ["self", "address"], 2, a)?;
    let (slf, address) = (slf.unwrap_or_else(|| a.0.clone()), address.unwrap_or_else(|| py.None().into_bound(py)));
    connect_common(py, &slf, &address, ex)
}

fn m_sendto<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let (data, rest) = star_params("_sendto", true, a)?;
    let slf = a.0;
    let data = data.unwrap_or_else(|| py.None().into_bound(py));
    let n = net()?;
    if let Some(address) = rest.last().filter(|a| !a.is_none()) {
        if let Some(pol) = n.policy(py)? {
            let pol = pol.get();
            if let Some((host, port)) = target(py, &n, pol, slf, address)? {
                if pol.mode != Mode::Record {
                    let pb = fmt_bytes(py, &port)?;
                    record(py, "socket.sendto", join3(&host, &pb, " blocked"))?;
                    return Err(n.blocked(py, &join3(&host, &pb, " (udp)"))?);
                }
            }
        }
    }
    let real = n.g(py, intern!(py, "_real_sendto"))?;
    let all: Vec<Bound<'py, PyAny>> = [slf.clone(), data].into_iter().chain(rest).collect();
    let all = PyTuple::new(py, all)?;
    real.call1(all)
}

fn m_send<'py>(
    py: Python<'py>,
    a: Args<'_, 'py>,
    fname: &str,
    key: &Bound<'py, PyString>,
) -> PyResult<Bound<'py, PyAny>> {
    let [slf, data, flags] = params(fname, ["self", "data", "flags"], 2, a)?;
    let (slf, data) = (slf.unwrap_or_else(|| a.0.clone()), data.unwrap_or_else(|| py.None().into_bound(py)));
    let flags = flags.unwrap_or_else(|| zero(py));
    let n = net()?;
    let r = n.g(py, key)?.call1((&slf, &data, flags))?;
    append(py, &n, &slf, Direction::Send, Payload::Prefix(&data, &r))?;
    Ok(r)
}

fn m_sendall<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let [slf, data, flags] = params("_rec_sendall", ["self", "data", "flags"], 2, a)?;
    let (slf, data) = (slf.unwrap_or_else(|| a.0.clone()), data.unwrap_or_else(|| py.None().into_bound(py)));
    let flags = flags.unwrap_or_else(|| zero(py));
    let n = net()?;
    let r = n.g(py, intern!(py, "_real_sendall"))?.call1((&slf, &data, flags))?;
    append(py, &n, &slf, Direction::Send, Payload::Whole(&data))?;
    Ok(r)
}

fn m_recv<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let [slf, bufsize, flags] = params("_rec_recv", ["self", "bufsize", "flags"], 2, a)?;
    let (slf, bufsize) = (slf.unwrap_or_else(|| a.0.clone()), bufsize.unwrap_or_else(|| py.None().into_bound(py)));
    let flags = flags.unwrap_or_else(|| zero(py));
    let n = net()?;
    let data = n.g(py, intern!(py, "_real_recv"))?.call1((&slf, bufsize, flags))?;
    append(py, &n, &slf, Direction::Recv, Payload::Whole(&data))?;
    Ok(data)
}

fn m_recv_into<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let [slf, buffer, nbytes, flags] = params("_rec_recv_into", ["self", "buffer", "nbytes", "flags"], 2, a)?;
    let (slf, buffer) = (slf.unwrap_or_else(|| a.0.clone()), buffer.unwrap_or_else(|| py.None().into_bound(py)));
    let nbytes = nbytes.unwrap_or_else(|| zero(py));
    let flags = flags.unwrap_or_else(|| zero(py));
    let n = net()?;
    let r = n.g(py, intern!(py, "_real_recv_into"))?.call1((&slf, &buffer, nbytes, flags))?;
    append(py, &n, &slf, Direction::Recv, Payload::Prefix(&buffer, &r))?;
    Ok(r)
}

fn m_ssl_write<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let [slf, data] = params("_rec_ssl_write", ["self", "data"], 2, a)?;
    let (slf, data) = (slf.unwrap_or_else(|| a.0.clone()), data.unwrap_or_else(|| py.None().into_bound(py)));
    let n = net()?;
    let r = n.g(py, intern!(py, "_real_ssl_write"))?.call1((&slf, &data))?;
    append(py, &n, &slf, Direction::Send, Payload::Prefix(&data, &r))?;
    Ok(r)
}

fn m_ssl_read<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let [slf, len, buffer] = params("_rec_ssl_read", ["self", "len", "buffer"], 1, a)?;
    let slf = slf.unwrap_or_else(|| a.0.clone());
    let len = match len {
        Some(l) => l,
        None => 1024i32.into_pyobject(py)?.into_any(),
    };
    let buffer = buffer.unwrap_or_else(|| py.None().into_bound(py));
    let n = net()?;
    let r = n.g(py, intern!(py, "_real_ssl_read"))?.call1((&slf, len, &buffer))?;
    if buffer.is_none() {
        append(py, &n, &slf, Direction::Recv, Payload::Whole(&r))?;
    } else {
        append(py, &n, &slf, Direction::Recv, Payload::Prefix(&buffer, &r))?;
    }
    Ok(r)
}

fn m_setsockopt<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let (_, rest) = star_params("_setsockopt", false, a)?;
    let slf = a.0;
    if weak_get(&REPLAYS, slf).is_some() {
        return Ok(py.None().into_bound(py));
    }
    let all: Vec<Bound<'py, PyAny>> = std::iter::once(slf.clone()).chain(rest).collect();
    let all = PyTuple::new(py, all)?;
    net()?.g(py, intern!(py, "_real_setsockopt"))?.call1(all)
}

fn m_getpeername<'py>(py: Python<'py>, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    let [slf] = params("_getpeername", ["self"], 1, a)?;
    let slf = slf.unwrap_or_else(|| a.0.clone());
    let n = net()?;
    if let Some(label) = weak_get(&REPLAYS, &slf) {
        // host, _, rest = label.rpartition(":"); int(rest.split("#")[0])
        let (host, rest): (&[u8], &[u8]) = match label.iter().rposition(|&c| c == b':') {
            Some(i) => (&label[..i], &label[i + 1..]),
            None => (b"", &label[..]),
        };
        let port_s = &rest[..rest.iter().position(|&c| c == b'#').unwrap_or(rest.len())];
        let port = py.import("builtins")?.getattr("int")?.call1((from_wtf8(py, port_s)?,))?;
        let h = match n.policy(py)? {
            Some(p) => PyString::new(py, &p.get().fake_ip_b(host)).into_any(),
            None => from_wtf8(py, host)?.into_any(),
        };
        return Ok(PyTuple::new(py, [h, port])?.into_any());
    }
    n.g(py, intern!(py, "_real_getpeername"))?.call1((slf,))
}

#[derive(Clone, Copy)]
enum Method {
    Connect,
    ConnectEx,
    Sendto,
    Send,
    Sendall,
    Recv,
    RecvInto,
    SslSend,
    SslWrite,
    SslRead,
    Setsockopt,
    Getpeername,
}

fn dispatch<'py>(py: Python<'py>, m: Method, a: Args<'_, 'py>) -> PyResult<Bound<'py, PyAny>> {
    match m {
        Method::Connect => m_connect(py, a, false),
        Method::ConnectEx => m_connect(py, a, true),
        Method::Sendto => m_sendto(py, a),
        Method::Send => m_send(py, a, "_rec_send", intern!(py, "_real_send")),
        Method::Sendall => m_sendall(py, a),
        Method::Recv => m_recv(py, a),
        Method::RecvInto => m_recv_into(py, a),
        Method::SslSend => m_send(py, a, "_rec_ssl_send", intern!(py, "_real_ssl_send")),
        Method::SslWrite => m_ssl_write(py, a),
        Method::SslRead => m_ssl_read(py, a),
        Method::Setsockopt => m_setsockopt(py, a),
        Method::Getpeername => m_getpeername(py, a),
    }
}

/// The C entry point of a method descriptor (`METH_VARARGS | METH_KEYWORDS`): `slf` is the instance.
unsafe fn trampoline(
    m: Method,
    slf: *mut ffi::PyObject,
    args: *mut ffi::PyObject,
    kwargs: *mut ffi::PyObject,
) -> *mut ffi::PyObject {
    let py = unsafe { Python::assume_attached() };
    let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> PyResult<*mut ffi::PyObject> {
        let slf = unsafe { Bound::from_borrowed_ptr(py, slf) };
        let args = unsafe { Bound::from_borrowed_ptr(py, args).cast_into_unchecked::<PyTuple>() };
        let kw = if kwargs.is_null() {
            None
        } else {
            Some(unsafe { Bound::from_borrowed_ptr(py, kwargs).cast_into_unchecked::<PyDict>() })
        };
        Ok(dispatch(py, m, (&slf, &args, kw.as_ref()))?.into_ptr())
    }));
    match r {
        Ok(Ok(p)) => p,
        Ok(Err(e)) => {
            e.restore(py);
            std::ptr::null_mut()
        }
        Err(_) => {
            PyRuntimeError::new_err("detpy: panic in a network wrapper").restore(py);
            std::ptr::null_mut()
        }
    }
}

macro_rules! entry {
    ($name:ident, $m:expr) => {
        unsafe extern "C" fn $name(
            slf: *mut ffi::PyObject,
            args: *mut ffi::PyObject,
            kwargs: *mut ffi::PyObject,
        ) -> *mut ffi::PyObject {
            unsafe { trampoline($m, slf, args, kwargs) }
        }
    };
}

entry!(c_connect, Method::Connect);
entry!(c_connect_ex, Method::ConnectEx);
entry!(c_sendto, Method::Sendto);
entry!(c_send, Method::Send);
entry!(c_sendall, Method::Sendall);
entry!(c_recv, Method::Recv);
entry!(c_recv_into, Method::RecvInto);
entry!(c_ssl_send, Method::SslSend);
entry!(c_ssl_write, Method::SslWrite);
entry!(c_ssl_read, Method::SslRead);
entry!(c_setsockopt, Method::Setsockopt);
entry!(c_getpeername, Method::Getpeername);

/// `net_method(kind, name, owner, doc=None)`: the wrapper `kind` as a method descriptor of `owner` named `name` (it
/// binds like the C methods it replaces; calling it on an object that is not an `owner` is the interpreter's
/// TypeError).
#[pyfunction]
#[pyo3(signature = (kind, name, owner, doc = None))]
fn net_method<'py>(
    py: Python<'py>,
    kind: &str,
    name: &str,
    owner: &Bound<'py, PyType>,
    doc: Option<&str>,
) -> PyResult<Bound<'py, PyAny>> {
    let f: ffi::PyCFunctionWithKeywords = match kind {
        "connect" => c_connect,
        "connect_ex" => c_connect_ex,
        "sendto" => c_sendto,
        "send" => c_send,
        "sendall" => c_sendall,
        "recv" => c_recv,
        "recv_into" => c_recv_into,
        "ssl_send" => c_ssl_send,
        "ssl_write" => c_ssl_write,
        "ssl_read" => c_ssl_read,
        "setsockopt" => c_setsockopt,
        "getpeername" => c_getpeername,
        _ => return Err(PyValueError::new_err(format!("unknown network wrapper {kind:?}"))),
    };
    let cname = CString::new(name).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let cdoc = match doc {
        Some(d) => Some(CString::new(d).map_err(|e| PyValueError::new_err(e.to_string()))?),
        None => None,
    };
    // the definition lives as long as the descriptor (for the process: a few per session)
    let def: &'static mut ffi::PyMethodDef = Box::leak(Box::new(ffi::PyMethodDef {
        ml_name: cname.into_raw(),
        ml_meth: ffi::PyMethodDefPointer { PyCFunctionWithKeywords: f },
        ml_flags: ffi::METH_VARARGS | ffi::METH_KEYWORDS,
        ml_doc: cdoc.map_or(std::ptr::null(), |d| d.into_raw()),
    }));
    unsafe { Bound::from_owned_ptr_or_err(py, ffi::PyDescr_NewMethod(owner.as_ptr().cast(), def)) }
}

// ---------------------------------------------------------------------------------------------------------------
// DNS

/// `_dns_check(host)`: None to resolve for real, a fake address for replay, or raise.
fn dns_check<'py>(py: Python<'py>, n: &Net, host: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyString>>> {
    let Some(pol) = n.policy(py)? else { return Ok(None) };
    let pol = pol.get();
    if host.is_none() {
        return Ok(None);
    }
    let host = if let Ok(b) = host.cast::<PyBytes>() {
        PyString::new(py, &decode_ascii_replace(b.as_bytes())).into_any()
    } else {
        host.clone()
    };
    let hs = host.cast::<PyString>().ok();
    let hb = match hs {
        Some(s) => Some(wtf8(s)?.into_owned()),
        None => None,
    };
    let local = match (hs, &hb) {
        (Some(s), Some(b)) => is_local_str(py, s, b)?,
        _ => is_local_any(py, &host)?,
    };
    if local || is_ip_any(py, &host)? {
        return Ok(None);
    }
    let allowed = match (hs, &hb) {
        (Some(s), Some(b)) => {
            let l = lower(py, s, b)?;
            let l = rstrip_dots(&l);
            pol.allow.iter().any(|a| a.as_slice() == l)
        }
        _ => {
            let l = host.call_method0(intern!(py, "lower"))?.call_method1(intern!(py, "rstrip"), (".",))?;
            pol.allow_obj.bind(py).contains(l)?
        }
    };
    if allowed || pol.mode == Mode::Record {
        return Ok(None);
    }
    let text = match &hb {
        Some(b) => b.clone(),
        None => fmt_bytes(py, &host)?,
    };
    if pol.mode == Mode::Replay && pol.has_recording_b(py, &host)? {
        let mut v = text.clone();
        v.extend_from_slice(b" replay");
        record(py, "dns", v)?;
        return Ok(Some(PyString::new(py, &pol.fake_ip_b(&text))));
    }
    let mut v = text;
    v.extend_from_slice(b" blocked");
    record(py, "dns", v)?;
    let socket = n.g(py, intern!(py, "socket"))?;
    let msg = format!("detpy: DNS lookup of {} blocked (Level 0 closes the network)", host.repr()?.to_cow()?);
    let exc = socket.getattr(intern!(py, "gaierror"))?.call1((socket.getattr(intern!(py, "EAI_NONAME"))?, msg))?;
    Err(PyErr::from_value(exc))
}

fn getaddrinfo<'py>(
    py: Python<'py>,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    let [host, port, family, type_, proto, flags] =
        bind("_getaddrinfo", ["host", "port", "family", "type", "proto", "flags"], 2, args, kwargs)?;
    let none = || py.None().into_bound(py);
    let (host, port) = (host.unwrap_or_else(none), port.unwrap_or_else(none));
    let [family, type_, proto, flags] = [family, type_, proto, flags].map(|x| x.unwrap_or_else(|| zero(py)));
    let n = net()?;
    if let Some(fake) = dns_check(py, &n, &host)? {
        let socket = n.g(py, intern!(py, "socket"))?;
        let p = if port.is_none() {
            zero(py)
        } else {
            match to_int(&port) {
                Ok(p) => p,
                Err(e) if e.is_instance_of::<PyValueError>(py) => {
                    socket.getattr(intern!(py, "getservbyname"))?.call1((&port,))?
                }
                Err(e) => return Err(e),
            }
        };
        let typ = if type_.is_truthy()? { type_ } else { socket.getattr(intern!(py, "SOCK_STREAM"))? };
        let pr = if proto.is_truthy()? { proto } else { socket.getattr(intern!(py, "IPPROTO_TCP"))? };
        let sa = PyTuple::new(py, [fake.into_any(), p])?;
        let item = PyTuple::new(
            py,
            [socket.getattr(intern!(py, "AF_INET"))?, typ, pr, PyString::new(py, "").into_any(), sa.into_any()],
        )?;
        return Ok(PyList::new(py, [item])?.into_any());
    }
    let res = n.g(py, intern!(py, "_real_getaddrinfo"))?.call1((&host, &port, family, type_, proto, flags))?;
    if let Some(pol) = n.policy(py)? {
        let pol = pol.get();
        if pol.mode == Mode::Record {
            if let Ok(hs) = host.cast::<PyString>() {
                let hb = wtf8(hs)?;
                if parse_ip(before_percent(&hb)).is_none() {
                    for item in res.try_iter()? {
                        let item = item?;
                        let sa = match item.cast::<PyTuple>() {
                            Ok(t) if t.is_exact_instance_of::<PyTuple>() && !t.is_empty() => t.get_item(t.len() - 1)?,
                            _ => {
                                let l = PyList::new(py, item.try_iter()?.collect::<PyResult<Vec<_>>>()?)?;
                                if l.is_empty() {
                                    return Err(PyValueError::new_err(
                                        "not enough values to unpack (expected at least 1, got 0)",
                                    ));
                                }
                                l.get_item(l.len() - 1)?
                            }
                        };
                        let key = sa.get_item(0)?;
                        match key.cast::<PyString>() {
                            Ok(k) => {
                                let k = wtf8(k)?.into_owned();
                                lock(&pol.maps).host_of_ip.insert(k, hb.to_vec());
                            }
                            Err(_) => {
                                key.hash()?; // a dict key: unhashable is the same TypeError
                            }
                        }
                    }
                }
            }
        }
    }
    Ok(res)
}

fn gethostbyname<'py>(
    py: Python<'py>,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
    ex: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let fname = if ex { "_gethostbyname_ex" } else { "_gethostbyname" };
    let [host] = bind(fname, ["host"], 1, args, kwargs)?;
    let host = host.unwrap_or_else(|| py.None().into_bound(py));
    let n = net()?;
    match dns_check(py, &n, &host)? {
        Some(fake) if ex => Ok(PyTuple::new(
            py,
            [host, PyList::empty(py).into_any(), PyList::new(py, [fake])?.into_any()],
        )?
        .into_any()),
        Some(fake) => Ok(fake.into_any()),
        None => {
            let key = if ex { intern!(py, "_real_gethostbyname_ex") } else { intern!(py, "_real_gethostbyname") };
            n.g(py, key)?.call1((host,))
        }
    }
}

#[derive(Clone, Copy)]
enum Dns {
    Getaddrinfo,
    Gethostbyname,
    GethostbynameEx,
}

impl Dns {
    fn call<'py>(
        self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match self {
            Dns::Getaddrinfo => getaddrinfo(py, args, kwargs),
            Dns::Gethostbyname => gethostbyname(py, args, kwargs, false),
            Dns::GethostbynameEx => gethostbyname(py, args, kwargs, true),
        }
    }
}

/// A DNS stand-in that does not bind as a method (`gethostbyname[_ex]` replace builtins).
#[pyclass(module = "detpy._core", name = "net_stand_in", frozen, dict, weakref)]
struct NetStandIn {
    kind: Dns,
}

#[pymethods]
impl NetStandIn {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.kind.call(py, args, kwargs)
    }

    fn __reduce__(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        Ok(slf.getattr(intern!(slf.py(), "__qualname__"))?.unbind())
    }

    fn __repr__(slf: &Bound<'_, Self>) -> PyResult<String> {
        Ok(format!("<built-in function {}>", slf.getattr(intern!(slf.py(), "__name__"))?.str()?.to_cow()?))
    }
}

/// A DNS stand-in that binds like a function (`getaddrinfo` replaces a Python function).
#[pyclass(module = "detpy._core", name = "net_function_stand_in", frozen, dict, weakref)]
struct NetFunctionStandIn {
    kind: Dns,
}

static METHOD_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

#[pymethods]
impl NetFunctionStandIn {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.kind.call(py, args, kwargs)
    }

    fn __get__<'py>(
        slf: &Bound<'py, Self>,
        obj: Option<&Bound<'py, PyAny>>,
        _owner: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match obj {
            Some(o) if !o.is_none() => {
                let py = slf.py();
                let mt = METHOD_TYPE.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
                    Ok(py.import("types")?.getattr("MethodType")?.unbind())
                })?;
                mt.bind(py).call1((slf, o))
            }
            _ => Ok(slf.clone().into_any()),
        }
    }

    fn __reduce__(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        Ok(slf.getattr(intern!(slf.py(), "__qualname__"))?.unbind())
    }

    fn __repr__(slf: &Bound<'_, Self>) -> PyResult<String> {
        Ok(format!("<function {}>", slf.getattr(intern!(slf.py(), "__qualname__"))?.str()?.to_cow()?))
    }
}

/// `net_stand_in(kind, module, name, wrapped)`: the DNS stand-in `kind` (`getaddrinfo`, `gethostbyname`,
/// `gethostbyname_ex`) disguised as `module.name`, with `__wrapped__` (and `__doc__`) of the real callable.
#[pyfunction]
fn net_stand_in<'py>(
    py: Python<'py>,
    kind: &str,
    module: &Bound<'py, PyAny>,
    name: &Bound<'py, PyString>,
    wrapped: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let obj = match kind {
        "getaddrinfo" => Bound::new(py, NetFunctionStandIn { kind: Dns::Getaddrinfo })?.into_any(),
        "gethostbyname" => Bound::new(py, NetStandIn { kind: Dns::Gethostbyname })?.into_any(),
        "gethostbyname_ex" => Bound::new(py, NetStandIn { kind: Dns::GethostbynameEx })?.into_any(),
        _ => return Err(PyValueError::new_err(format!("unknown network stand-in {kind:?}"))),
    };
    obj.setattr(intern!(py, "__name__"), name)?;
    obj.setattr(intern!(py, "__qualname__"), name)?;
    obj.setattr(intern!(py, "__module__"), module)?;
    obj.setattr(intern!(py, "__doc__"), wrapped.getattr(intern!(py, "__doc__"))?)?;
    obj.setattr(intern!(py, "__wrapped__"), wrapped)?;
    Ok(obj)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NetPolicy>()?;
    m.add_class::<NetStandIn>()?;
    m.add_class::<NetFunctionStandIn>()?;
    for f in [
        wrap_pyfunction!(net_configure, m)?,
        wrap_pyfunction!(net_conn_of, m)?,
        wrap_pyfunction!(net_conn_tls, m)?,
        wrap_pyfunction!(net_set_replay, m)?,
        wrap_pyfunction!(net_is_replayed, m)?,
        wrap_pyfunction!(net_is_local_name, m)?,
        wrap_pyfunction!(net_is_ip, m)?,
        wrap_pyfunction!(net_ip_address, m)?,
        wrap_pyfunction!(net_ip_flags, m)?,
        wrap_pyfunction!(net_resolves_local, m)?,
        wrap_pyfunction!(net_proxy_endpoints, m)?,
        wrap_pyfunction!(net_blocked, m)?,
        wrap_pyfunction!(net_target, m)?,
        wrap_pyfunction!(net_method, m)?,
        wrap_pyfunction!(net_stand_in, m)?,
    ] {
        m.add_function(f)?;
    }
    Ok(())
}
