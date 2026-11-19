//! C ABI over `detpy-core`, called through cgo by the `fenvix-go` shell
//! (`go/`), so that Go test runs produce the same events, BLAKE3 fingerprints
//! and JSONL traces as the Python (PyO3) and Node (napi-rs) shells, and one
//! verifier reads all three.
//!
//! Conventions (see `include/fenvix_go.h`):
//!
//! * strings in are NUL-terminated UTF-8 (`const char*`); invalid UTF-8 is an
//!   error, never a silent replacement;
//! * strings out are heap-allocated by Rust and must be released with
//!   [`fenvix_string_free`];
//! * functions that can fail return a negative status (or NULL) and leave a
//!   message for [`fenvix_last_error`] (per thread);
//! * a recorder handle is an opaque pointer, released with
//!   [`fenvix_recorder_free`]; one handle must not be used from two threads at
//!   once (the Go side owns one recorder per package run).

use detpy_core::backend::{Backend, EventSink};
use detpy_core::event::{Event, Source, ENCODING_VERSION};
use detpy_core::fingerprint::digest_bytes;
use detpy_core::recorder::{Recorder, RecorderConfig};
use detpy_core::trace::{self, Header};
use detpy_core::{order, verify};
use std::cell::RefCell;
use std::ffi::{c_char, c_int, CStr, CString};
use std::path::PathBuf;
use std::ptr;

pub mod skip;
pub mod strace;

/// Separator between the fields of a packed event.
pub const FIELD_SEP: u8 = 0x1f;
/// Separator between packed events.
pub const EVENT_SEP: u8 = 0x1e;

thread_local! {
    static LAST_ERROR: RefCell<Option<CString>> = const { RefCell::new(None) };
}

fn set_error(msg: impl Into<String>) {
    let msg = msg.into().replace('\0', "?");
    LAST_ERROR.with(|e| *e.borrow_mut() = CString::new(msg).ok());
}

fn clear_error() {
    LAST_ERROR.with(|e| *e.borrow_mut() = None);
}

/// # Safety
/// `p` must be NULL or a valid NUL-terminated string.
unsafe fn arg<'a>(p: *const c_char, name: &str) -> Result<&'a str, String> {
    if p.is_null() {
        return Err(format!("{name} is NULL"));
    }
    CStr::from_ptr(p).to_str().map_err(|e| format!("{name} is not UTF-8: {e}"))
}

fn out_string(s: String) -> *mut c_char {
    match CString::new(s) {
        Ok(c) => c.into_raw(),
        Err(e) => {
            set_error(format!("output contains NUL: {e}"));
            ptr::null_mut()
        }
    }
}

fn parse_json(s: &str, name: &str) -> Result<serde_json::Value, String> {
    serde_json::from_str(s).map_err(|e| format!("{name}: bad JSON: {e}"))
}

fn parse_strings(s: &str, name: &str) -> Result<Vec<String>, String> {
    serde_json::from_str(s).map_err(|e| format!("{name}: expected a JSON array of strings: {e}"))
}

/// Run `f`, turning an `Err` into `fail` plus a last-error message.
fn guard<T>(fail: T, f: impl FnOnce() -> Result<T, String>) -> T {
    clear_error();
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)) {
        Ok(Ok(v)) => v,
        Ok(Err(msg)) => {
            set_error(msg);
            fail
        }
        Err(_) => {
            set_error("internal panic in fenvix-go core");
            fail
        }
    }
}

/// Parse one packed event: `source US op US site US value [US thread]`.
pub fn parse_packed_event(ev: &[u8]) -> Result<Event, String> {
    let text = std::str::from_utf8(ev).map_err(|e| format!("packed event is not UTF-8: {e}"))?;
    let mut f = text.splitn(5, FIELD_SEP as char);
    let (Some(s), Some(o), Some(at), Some(val)) = (f.next(), f.next(), f.next(), f.next()) else {
        return Err(format!("malformed packed event {text:?}"));
    };
    let thread = match f.next() {
        None | Some("") => 0,
        Some(t) => t.parse::<u32>().map_err(|e| format!("bad thread {t:?}: {e}"))?,
    };
    Ok(Event { thread, source: Source::parse(s), op: o.to_owned(), site: at.to_owned(), value: val.to_owned() })
}

// ---------------------------------------------------------------- versions

#[no_mangle]
pub extern "C" fn fenvix_encoding_version() -> u32 {
    ENCODING_VERSION
}

#[no_mangle]
pub extern "C" fn fenvix_trace_version() -> u32 {
    trace::TRACE_VERSION
}

/// Last error message of this thread, or NULL. Owned by the library: valid
/// until the next call into the library from the same thread; do not free.
#[no_mangle]
pub extern "C" fn fenvix_last_error() -> *const c_char {
    LAST_ERROR.with(|e| e.borrow().as_ref().map(|c| c.as_ptr()).unwrap_or(ptr::null()))
}

/// Release a string returned by this library.
///
/// # Safety
/// `s` must be NULL or a pointer returned by this library, freed once.
#[no_mangle]
pub unsafe extern "C" fn fenvix_string_free(s: *mut c_char) {
    if !s.is_null() {
        drop(CString::from_raw(s));
    }
}

// ---------------------------------------------------------------- recorder

/// Opaque recorder handle.
pub struct FenvixRecorder {
    inner: Recorder,
}

#[no_mangle]
pub extern "C" fn fenvix_recorder_new(max_events: u32, checkpoint_every: u32) -> *mut FenvixRecorder {
    let cfg = RecorderConfig {
        max_events: if max_events == 0 { RecorderConfig::default().max_events } else { max_events as usize },
        checkpoint_every: if checkpoint_every == 0 {
            RecorderConfig::default().checkpoint_every
        } else {
            checkpoint_every as u64
        },
    };
    Box::into_raw(Box::new(FenvixRecorder { inner: Recorder::new(cfg) }))
}

/// # Safety
/// `r` must be NULL or a handle from [`fenvix_recorder_new`], freed once.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_free(r: *mut FenvixRecorder) {
    if !r.is_null() {
        drop(Box::from_raw(r));
    }
}

unsafe fn rec<'a>(r: *mut FenvixRecorder) -> Result<&'a mut Recorder, String> {
    r.as_mut().map(|r| &mut r.inner).ok_or_else(|| "recorder is NULL".to_string())
}

/// Start streaming the trace to `path`. `meta_json` is a JSON object,
/// `order_json` a JSON array of test ids (the planned order). Returns 0 or -1.
///
/// # Safety
/// Pointers must be valid NUL-terminated strings and a live handle.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_open(
    r: *mut FenvixRecorder,
    path: *const c_char,
    meta_json: *const c_char,
    order_json: *const c_char,
) -> c_int {
    guard(-1, || {
        let r = rec(r)?;
        let meta = parse_json(arg(meta_json, "meta_json")?, "meta_json")?;
        let order = parse_strings(arg(order_json, "order_json")?, "order_json")?;
        r.open(&PathBuf::from(arg(path, "path")?), &Header::new(meta, order)).map_err(|e| e.to_string())?;
        Ok(0)
    })
}

/// # Safety
/// Valid handle and string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_begin_test(r: *mut FenvixRecorder, nodeid: *const c_char, index: u64) -> c_int {
    guard(-1, || {
        rec(r)?.begin_test(arg(nodeid, "nodeid")?, index).map_err(|e| e.to_string())?;
        Ok(0)
    })
}

/// Record one event for the current test (ignored outside a test).
///
/// # Safety
/// Valid handle and strings.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_record(
    r: *mut FenvixRecorder,
    thread: u32,
    source: *const c_char,
    op: *const c_char,
    site: *const c_char,
    value: *const c_char,
) -> c_int {
    guard(-1, || {
        let ev = Event {
            thread,
            source: Source::parse(arg(source, "source")?),
            op: arg(op, "op")?.to_owned(),
            site: arg(site, "site")?.to_owned(),
            value: arg(value, "value")?.to_owned(),
        };
        rec(r)?.record(ev);
        Ok(0)
    })
}

/// Record many events: events separated by 0x1E, fields by 0x1F
/// (`source`, `op`, `site`, `value`, optional `thread`). `len` bytes are read
/// from `data` (no NUL needed). Returns the number of events or -1.
///
/// # Safety
/// `data` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_record_packed(r: *mut FenvixRecorder, data: *const u8, len: usize) -> i64 {
    guard(-1, || {
        let r = rec(r)?;
        if len == 0 {
            return Ok(0);
        }
        if data.is_null() {
            return Err("data is NULL".into());
        }
        let bytes = std::slice::from_raw_parts(data, len);
        let mut n = 0i64;
        for ev in bytes.split(|b| *b == EVENT_SEP) {
            if ev.is_empty() {
                continue;
            }
            r.record(parse_packed_event(ev)?);
            n += 1;
        }
        Ok(n)
    })
}

/// Finish the current test. Returns its fingerprint (free it), or NULL when
/// no test was open (last error empty) or on error (last error set).
///
/// # Safety
/// Valid handle and string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_end_test(r: *mut FenvixRecorder, outcome: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let rec = rec(r)?.end_test(arg(outcome, "outcome")?).map_err(|e| e.to_string())?;
        Ok(rec.map(|t| out_string(t.fingerprint)).unwrap_or(ptr::null_mut()))
    })
}

/// Close the trace (writes the footer). Returns the order digest (free it),
/// or NULL if the recorder was never opened / on error.
///
/// # Safety
/// Valid handle.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_close(r: *mut FenvixRecorder) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let f = rec(r)?.close().map_err(|e| e.to_string())?;
        Ok(f.map(|f| out_string(f.order_digest)).unwrap_or(ptr::null_mut()))
    })
}

/// Events received while no test was open.
///
/// # Safety
/// Valid handle.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_dropped(r: *mut FenvixRecorder) -> u64 {
    guard(0, || Ok(rec(r)?.dropped))
}

/// JSON array of `{nodeid, outcome, fingerprint, n_events}` for every finished test.
///
/// # Safety
/// Valid handle.
#[no_mangle]
pub unsafe extern "C" fn fenvix_recorder_finished_json(r: *mut FenvixRecorder) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let all: Vec<serde_json::Value> = rec(r)?
            .finished()
            .iter()
            .map(|f| {
                serde_json::json!({"nodeid": f.nodeid, "outcome": f.outcome,
                                   "fingerprint": f.fingerprint, "n_events": f.n_events})
            })
            .collect();
        Ok(out_string(serde_json::Value::Array(all).to_string()))
    })
}

// ---------------------------------------------------------------- verifier

fn verify_report(paths_json: *const c_char) -> Result<verify::Report, String> {
    let paths = parse_strings(unsafe { arg(paths_json, "paths_json")? }, "paths_json")?;
    verify::verify_paths(&paths).map_err(|e| e.to_string())
}

/// Verify traces of the same suite (JSON array of paths). Returns the report as JSON.
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_verify_json(paths_json: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let report = verify_report(paths_json)?;
        Ok(out_string(serde_json::to_string(&report).map_err(|e| e.to_string())?))
    })
}

/// Verify traces and render the human-readable report.
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_verify_text(paths_json: *const c_char, show_stable: c_int) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let report = verify_report(paths_json)?;
        Ok(out_string(verify::render_text(&report, show_stable != 0)))
    })
}

// ---------------------------------------------------------------- order and seeds

/// Seed for `key` derived from `base` (same function as Python and Node).
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_derive_seed(base: u64, key: *const c_char) -> u64 {
    guard(0, || Ok(order::derive_seed(base, arg(key, "key")?)))
}

/// Permutation of `0..n` for group `key` under `seed`, written to `out`
/// (`n` slots). Seed 0 is not special here: callers keep the natural order
/// for seed 0 themselves, as the Python and Node shells do. Returns 0 or -1.
///
/// # Safety
/// `out` must have room for `n` values.
#[no_mangle]
pub unsafe extern "C" fn fenvix_shuffle_indices(n: u32, seed: u64, key: *const c_char, out: *mut u32) -> c_int {
    guard(-1, || {
        let key = arg(key, "key")?;
        if n > 0 && out.is_null() {
            return Err("out is NULL".into());
        }
        let perm = order::shuffle_indices(n as usize, seed, key);
        for (i, v) in perm.into_iter().enumerate() {
            *out.add(i) = v as u32;
        }
        Ok(0)
    })
}

/// Digest of an ordered list of test ids (JSON array).
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_order_digest(ids_json: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let ids = parse_strings(arg(ids_json, "ids_json")?, "ids_json")?;
        Ok(out_string(trace::order_digest(&ids)))
    })
}

/// Short (128-bit) BLAKE3 hex digest of `len` bytes.
///
/// # Safety
/// `data` must point to `len` readable bytes (or be NULL with len 0).
#[no_mangle]
pub unsafe extern "C" fn fenvix_digest(data: *const u8, len: usize) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let bytes: &[u8] = if len == 0 {
            &[]
        } else if data.is_null() {
            return Err("data is NULL".into());
        } else {
            std::slice::from_raw_parts(data, len)
        };
        Ok(out_string(digest_bytes(bytes).short()))
    })
}

/// Full (256-bit) BLAKE3 hex digest of a file's content (the skip key uses it
/// for test binaries, files read and runtime identity).
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_digest_file(path: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let p = arg(path, "path")?;
        let data = std::fs::read(p).map_err(|e| format!("{p}: {e}"))?;
        Ok(out_string(digest_bytes(&data).to_hex()))
    })
}

/// Concatenate partial traces (JSON array of paths, in execution order) into
/// one trace. Returns `{"n_tests":N,"order_digest":"...","skipped":[...]}`.
///
/// # Safety
/// Valid strings.
#[no_mangle]
pub unsafe extern "C" fn fenvix_merge_traces(
    parts_json: *const c_char,
    out: *const c_char,
    meta_json: *const c_char,
    order_json: *const c_char,
) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let parts = parse_strings(arg(parts_json, "parts_json")?, "parts_json")?;
        let meta = parse_json(arg(meta_json, "meta_json")?, "meta_json")?;
        let order = parse_strings(arg(order_json, "order_json")?, "order_json")?;
        let (footer, skipped) = trace::merge_traces(&parts, &PathBuf::from(arg(out, "out")?), &Header::new(meta, order))
            .map_err(|e| e.to_string())?;
        Ok(out_string(
            serde_json::json!({"n_tests": footer.n_tests, "order_digest": footer.order_digest, "skipped": skipped})
                .to_string(),
        ))
    })
}

// ---------------------------------------------------------------- skip with proof

/// Opaque skip session (one package run).
pub struct FenvixSkip {
    s: skip::Session,
}

/// The strace command prefix (JSON array) that writes its log to `log`.
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_skip_strace_args(log: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || Ok(out_string(serde_json::to_string(&strace::args(arg(log, "log")?)).unwrap())))
}

/// Open a skip session: load the package's cache and take the pre-run values
/// of its recorded inputs. Call before the test binary starts. NULL on error.
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_skip_open(config_json: *const c_char) -> *mut FenvixSkip {
    guard(ptr::null_mut(), || {
        let cfg: skip::Config = serde_json::from_str(arg(config_json, "config_json")?)
            .map_err(|e| format!("config_json: {e}"))?;
        Ok(Box::into_raw(Box::new(FenvixSkip { s: skip::Session::open(cfg) })))
    })
}

/// Decide for the tests (JSON array of names, execution order). Returns
/// `{"reuse":[names],"why":{name:reason}}`.
///
/// # Safety
/// Handle from `fenvix_skip_open`, valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_skip_decide(h: *mut FenvixSkip, names_json: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let h = h.as_mut().ok_or("skip handle is NULL")?;
        let names = parse_strings(arg(names_json, "names_json")?, "names_json")?;
        let reuse = h.s.decide(&names);
        Ok(out_string(serde_json::json!({"reuse": reuse, "static": h.s.static_}).to_string()))
    })
}

/// Record the run (see `skip::Run`): append the decisions, save new entries.
///
/// # Safety
/// Handle from `fenvix_skip_open`, valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_skip_record(h: *mut FenvixSkip, run_json: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || {
        let h = h.as_mut().ok_or("skip handle is NULL")?;
        let run: skip::Run = serde_json::from_str(arg(run_json, "run_json")?).map_err(|e| format!("run_json: {e}"))?;
        Ok(out_string(h.s.record(run)?.to_string()))
    })
}

/// Release a skip session.
///
/// # Safety
/// Handle from `fenvix_skip_open` (or NULL), not used afterwards.
#[no_mangle]
pub unsafe extern "C" fn fenvix_skip_free(h: *mut FenvixSkip) {
    if !h.is_null() {
        drop(Box::from_raw(h));
    }
}

/// Virtual content for a process-state file (`/proc/<pid>/stat`), or NULL
/// with an error when it does not parse.
///
/// # Safety
/// Valid string.
#[no_mangle]
pub unsafe extern "C" fn fenvix_virtual_proc_stat(real: *const c_char) -> *mut c_char {
    guard(ptr::null_mut(), || {
        skip::virtual_proc_stat(arg(real, "real")?).map(out_string).ok_or_else(|| "not a /proc stat line".to_owned())
    })
}

/// JSON description of the interception backends known to the core.
#[no_mangle]
pub extern "C" fn fenvix_backends() -> *mut c_char {
    let all: Vec<serde_json::Value> = [Backend::PythonHooks, Backend::Syscall]
        .iter()
        .map(|b| serde_json::json!({"name": b.name(), "implemented": b.implemented(), "capabilities": b.capabilities()}))
        .collect();
    out_string(serde_json::Value::Array(all).to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CString;

    fn c(s: &str) -> CString {
        CString::new(s).unwrap()
    }

    unsafe fn take(p: *mut c_char) -> String {
        assert!(!p.is_null(), "unexpected NULL, last error: {:?}", last_error());
        let s = CStr::from_ptr(p).to_str().unwrap().to_owned();
        fenvix_string_free(p);
        s
    }

    fn last_error() -> Option<String> {
        let p = fenvix_last_error();
        if p.is_null() {
            None
        } else {
            Some(unsafe { CStr::from_ptr(p) }.to_string_lossy().into_owned())
        }
    }

    /// Record one test through the C ABI and return its fingerprint.
    unsafe fn run_one(path: &std::path::Path, packed: &[u8]) -> String {
        let r = fenvix_recorder_new(0, 0);
        let p = c(path.to_str().unwrap());
        assert_eq!(fenvix_recorder_open(r, p.as_ptr(), c(r#"{"runtime":"go"}"#).as_ptr(), c(r#"["pkg::TestA"]"#).as_ptr()), 0);
        assert_eq!(fenvix_recorder_begin_test(r, c("pkg::TestA").as_ptr(), 0), 0);
        assert_eq!(fenvix_recorder_record_packed(r, packed.as_ptr(), packed.len()), 2);
        let fp = take(fenvix_recorder_end_test(r, c("passed").as_ptr()));
        let od = take(fenvix_recorder_close(r));
        assert_eq!(od.len(), 32);
        fenvix_recorder_free(r);
        fp
    }

    #[test]
    fn packed_events_match_the_core_fingerprint() {
        let dir = tempfile::tempdir().unwrap();
        let packed = b"time\x1ftime.Now\x1fa_test.go:3\x1f1\x1erandom\x1fmath/rand.Intn\x1fa_test.go:4\x1f7\x1f2\x1e";
        let fp = unsafe { run_one(&dir.path().join("a.jsonl"), packed) };
        // Same events through the Rust API directly.
        let mut f = detpy_core::Fingerprinter::default();
        f.push(Event::new(Source::Time, "time.Now", "a_test.go:3", "1"));
        f.push(Event::new(Source::Random, "math/rand.Intn", "a_test.go:4", "7").with_thread(2));
        assert_eq!(f.finish("pkg::TestA", 0, "passed").fingerprint, fp);
        // Trace on disk is readable by the core and verifies as stable against itself.
        let t = trace::read_trace(&dir.path().join("a.jsonl")).unwrap();
        assert_eq!(t.tests[0].events[1].thread, 2);
        assert_eq!(t.header.meta["runtime"], "go");
    }

    #[test]
    fn verifier_names_the_first_diverging_event() {
        let dir = tempfile::tempdir().unwrap();
        let a = dir.path().join("a.jsonl");
        let b = dir.path().join("b.jsonl");
        unsafe {
            run_one(&a, b"time\x1ftime.Now\x1fx_test.go:3\x1f1\x1erandom\x1fmath/rand.Intn\x1fx_test.go:4\x1f7");
            run_one(&b, b"time\x1ftime.Now\x1fx_test.go:3\x1f1\x1erandom\x1fmath/rand.Intn\x1fx_test.go:4\x1f9");
            let paths = c(&serde_json::json!([a, b]).to_string());
            let json = take(fenvix_verify_json(paths.as_ptr()));
            assert!(json.contains("math/rand.Intn"), "{json}");
            let text = take(fenvix_verify_text(paths.as_ptr(), 0));
            assert!(text.contains("x_test.go:4"), "{text}");
        }
    }

    #[test]
    fn seeds_and_shuffle_match_the_core() {
        unsafe {
            assert_eq!(fenvix_derive_seed(7, c("pkg::TestA").as_ptr()), order::derive_seed(7, "pkg::TestA"));
            let mut out = vec![0u32; 5];
            assert_eq!(fenvix_shuffle_indices(5, 3, c("k").as_ptr(), out.as_mut_ptr()), 0);
            let want: Vec<u32> = order::shuffle_indices(5, 3, "k").into_iter().map(|i| i as u32).collect();
            assert_eq!(out, want);
            assert_eq!(take(fenvix_digest(b"abc".as_ptr(), 3)), digest_bytes(b"abc").short());
            assert_eq!(take(fenvix_order_digest(c(r#"["a","b"]"#).as_ptr())), trace::order_digest(&["a", "b"]));
        }
    }

    #[test]
    fn errors_are_reported_not_panicked() {
        unsafe {
            let r = fenvix_recorder_new(0, 0);
            assert_eq!(fenvix_recorder_open(r, c("/x").as_ptr(), c("not json").as_ptr(), c("[]").as_ptr()), -1);
            assert!(last_error().unwrap().contains("meta_json"));
            let bad = b"time\x1fonly-two";
            assert_eq!(fenvix_recorder_record_packed(r, bad.as_ptr(), bad.len()), -1);
            assert!(last_error().unwrap().contains("malformed"));
            assert!(fenvix_recorder_end_test(r, c("passed").as_ptr()).is_null());
            assert!(last_error().is_none());
            fenvix_recorder_free(r);
            assert_eq!(fenvix_recorder_begin_test(ptr::null_mut(), c("x").as_ptr(), 0), -1);
        }
    }

    #[test]
    fn merge_reindexes_parts() {
        let dir = tempfile::tempdir().unwrap();
        let a = dir.path().join("a.jsonl");
        let b = dir.path().join("b.jsonl");
        unsafe {
            run_one(&a, b"time\x1fx\x1fy\x1f1\x1etime\x1fx\x1fy\x1f2");
            run_one(&b, b"time\x1fx\x1fy\x1f1\x1etime\x1fx\x1fy\x1f2");
            let out = dir.path().join("all.jsonl");
            let res = take(fenvix_merge_traces(
                c(&serde_json::json!([a, b]).to_string()).as_ptr(),
                c(out.to_str().unwrap()).as_ptr(),
                c(r#"{"runtime":"go"}"#).as_ptr(),
                c("[]").as_ptr(),
            ));
            assert!(res.contains(r#""n_tests":2"#), "{res}");
            let t = trace::read_trace(&out).unwrap();
            assert_eq!(t.tests[1].index, 1);
        }
    }

    #[test]
    fn file_digest_is_content_based() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("f");
        std::fs::write(&p, b"one").unwrap();
        let cp = c(p.to_str().unwrap());
        unsafe {
            let d1 = take(fenvix_digest_file(cp.as_ptr()));
            std::fs::write(&p, b"two").unwrap();
            let d2 = take(fenvix_digest_file(cp.as_ptr()));
            assert_ne!(d1, d2);
            assert_eq!(d1.len(), 64);
            assert!(fenvix_digest_file(c("/does/not/exist").as_ptr()).is_null());
        }
    }
}
