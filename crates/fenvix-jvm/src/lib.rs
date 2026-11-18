//! JVM bindings (JNI) for detpy-core, loaded by the fenvix Java agent (`jvm/`).
//!
//! The API mirrors the Node (`crates/detpy-node`) and Python (`crates/detpy-py`)
//! bindings so that the three shells produce the same trace and cassette formats
//! and one verifier reads all of them. Every function is a static native method of
//! `dev.fenvix.rt.Native` (loaded by the bootstrap class loader). Recorders cross
//! the boundary as opaque `long` handles. Seeds are Java `long`s reinterpreted as
//! unsigned 64-bit integers.

use detpy_core::backend::EventSink;
use detpy_core::event::{Event, Source};
use detpy_core::fingerprint::digest_bytes;
use detpy_core::recorder::{Recorder, RecorderConfig};
use detpy_core::trace::Header;
use detpy_core::{order, trace, verify as v};
use jni::objects::{JByteArray, JClass, JObjectArray, JString};
use jni::sys::{jboolean, jint, jintArray, jlong, jstring};
use jni::JNIEnv;
use std::io::Read;
use std::path::PathBuf;
use std::sync::Mutex;

/// Separator between the fields of a packed event.
pub const FIELD_SEP: char = '\u{1f}';
/// Separator between packed events.
pub const EVENT_SEP: char = '\u{1e}';

type Handle = Mutex<Recorder>;

fn throw(env: &mut JNIEnv, msg: impl AsRef<str>) {
    let _ = env.throw_new("java/lang/IllegalStateException", msg.as_ref());
}

fn jstr(env: &mut JNIEnv, s: &JString) -> Option<String> {
    if s.is_null() {
        return None;
    }
    env.get_string(s).ok().map(|s| s.into())
}

fn jstrings(env: &mut JNIEnv, arr: &JObjectArray) -> Vec<String> {
    let mut out = Vec::new();
    if arr.is_null() {
        return out;
    }
    let n = env.get_array_length(arr).unwrap_or(0);
    for i in 0..n {
        if let Ok(o) = env.get_object_array_element(arr, i) {
            let s = JString::from(o);
            if let Some(v) = jstr(env, &s) {
                out.push(v);
            }
            let _ = env.delete_local_ref(s);
        }
    }
    out
}

fn new_jstring(env: &mut JNIEnv, s: &str) -> jstring {
    env.new_string(s).map(|s| s.into_raw()).unwrap_or(std::ptr::null_mut())
}

fn handle<'a>(h: jlong) -> Option<&'a Handle> {
    if h == 0 {
        None
    } else {
        // SAFETY: handles are produced by `recorderNew` (Box::into_raw) and freed
        // only by `recorderFree`; the Java side never uses a freed handle.
        Some(unsafe { &*(h as *const Handle) })
    }
}

fn lock(h: &Handle) -> std::sync::MutexGuard<'_, Recorder> {
    h.lock().unwrap_or_else(|e| e.into_inner())
}

/// Parse one packed event: `thread FS source FS op FS site FS value`.
pub fn parse_packed(ev: &str) -> Option<Event> {
    let mut f = ev.splitn(5, FIELD_SEP);
    let (t, s, o, at, val) = (f.next()?, f.next()?, f.next()?, f.next()?, f.next()?);
    Some(Event {
        thread: t.parse().ok()?,
        source: Source::parse(s),
        op: o.to_owned(),
        site: at.to_owned(),
        value: val.to_owned(),
    })
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_encodingVersion(_env: JNIEnv, _c: JClass) -> jint {
    detpy_core::event::ENCODING_VERSION as jint
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_traceVersion(_env: JNIEnv, _c: JClass) -> jint {
    trace::TRACE_VERSION as jint
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_recorderNew(
    _env: JNIEnv,
    _c: JClass,
    max_events: jint,
    checkpoint_every: jint,
) -> jlong {
    let cfg = RecorderConfig {
        max_events: if max_events > 0 { max_events as usize } else { 10_000 },
        checkpoint_every: if checkpoint_every > 0 { checkpoint_every as u64 } else { 256 },
    };
    Box::into_raw(Box::new(Mutex::new(Recorder::new(cfg)))) as jlong
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_recorderFree(_env: JNIEnv, _c: JClass, h: jlong) {
    if h != 0 {
        // SAFETY: see `handle`.
        drop(unsafe { Box::from_raw(h as *mut Handle) });
    }
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_recorderOpen(
    mut env: JNIEnv,
    _c: JClass,
    h: jlong,
    path: JString,
    meta_json: JString,
    order: JObjectArray,
) {
    let Some(r) = handle(h) else { return throw(&mut env, "null recorder") };
    let path = jstr(&mut env, &path).unwrap_or_default();
    let meta = jstr(&mut env, &meta_json).unwrap_or_else(|| "{}".into());
    let order = jstrings(&mut env, &order);
    let meta: serde_json::Value = match serde_json::from_str(&meta) {
        Ok(m) => m,
        Err(e) => return throw(&mut env, format!("bad meta json: {e}")),
    };
    if let Err(e) = lock(r).open(&PathBuf::from(path), &Header::new(meta, order)) {
        throw(&mut env, e.to_string());
    }
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_recorderBegin(
    mut env: JNIEnv,
    _c: JClass,
    h: jlong,
    nodeid: JString,
    index: jint,
) {
    let Some(r) = handle(h) else { return throw(&mut env, "null recorder") };
    let id = jstr(&mut env, &nodeid).unwrap_or_default();
    if let Err(e) = lock(r).begin_test(&id, index.max(0) as u64) {
        throw(&mut env, e.to_string());
    }
}

/// Record many events in one call (see [`parse_packed`]); returns how many.
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_recorderRecordPacked(
    mut env: JNIEnv,
    _c: JClass,
    h: jlong,
    packed: JString,
) -> jint {
    let Some(r) = handle(h) else {
        throw(&mut env, "null recorder");
        return 0;
    };
    let Some(packed) = jstr(&mut env, &packed) else { return 0 };
    let mut rec = lock(r);
    let mut n = 0;
    for ev in packed.split(EVENT_SEP) {
        if ev.is_empty() {
            continue;
        }
        match parse_packed(ev) {
            Some(e) => {
                rec.record(e);
                n += 1;
            }
            None => {
                drop(rec);
                throw(&mut env, format!("malformed packed event {ev:?}"));
                return n;
            }
        }
    }
    n
}

/// Finish the current test; returns its fingerprint (null if no test was open).
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_recorderEnd(
    mut env: JNIEnv,
    _c: JClass,
    h: jlong,
    outcome: JString,
) -> jstring {
    let Some(r) = handle(h) else {
        throw(&mut env, "null recorder");
        return std::ptr::null_mut();
    };
    let outcome = jstr(&mut env, &outcome).unwrap_or_else(|| "passed".into());
    let res = lock(r).end_test(&outcome);
    match res {
        Ok(Some(rec)) => new_jstring(&mut env, &rec.fingerprint),
        Ok(None) => std::ptr::null_mut(),
        Err(e) => {
            throw(&mut env, e.to_string());
            std::ptr::null_mut()
        }
    }
}

/// Close the trace; returns the digest of the executed order.
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_recorderClose(mut env: JNIEnv, _c: JClass, h: jlong) -> jstring {
    let Some(r) = handle(h) else { return std::ptr::null_mut() };
    let res = lock(r).close();
    match res {
        Ok(Some(f)) => new_jstring(&mut env, &f.order_digest),
        Ok(None) => std::ptr::null_mut(),
        Err(e) => {
            throw(&mut env, e.to_string());
            std::ptr::null_mut()
        }
    }
}

fn trace_err(e: trace::TraceError) -> String {
    e.to_string()
}

/// Verify traces of the same suite; returns the report as JSON.
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_verify(mut env: JNIEnv, _c: JClass, paths: JObjectArray) -> jstring {
    let paths = jstrings(&mut env, &paths);
    match v::verify_paths(&paths).map_err(trace_err) {
        Ok(report) => {
            let s = serde_json::to_string(&report).unwrap_or_else(|_| "{}".into());
            new_jstring(&mut env, &s)
        }
        Err(e) => {
            throw(&mut env, e);
            std::ptr::null_mut()
        }
    }
}

/// Verify traces and render the human-readable report.
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_verifyText(
    mut env: JNIEnv,
    _c: JClass,
    paths: JObjectArray,
    show_stable: jboolean,
) -> jstring {
    let paths = jstrings(&mut env, &paths);
    match v::verify_paths(&paths).map_err(trace_err) {
        Ok(report) => {
            let s = v::render_text(&report, show_stable != 0);
            new_jstring(&mut env, &s)
        }
        Err(e) => {
            throw(&mut env, e);
            std::ptr::null_mut()
        }
    }
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_deriveSeed(
    mut env: JNIEnv,
    _c: JClass,
    base: jlong,
    key: JString,
) -> jlong {
    let key = jstr(&mut env, &key).unwrap_or_default();
    order::derive_seed(base as u64, &key) as jlong
}

/// Permutation of one group of the hierarchical shuffle (`key` = group id).
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_shuffleIndices(
    mut env: JNIEnv,
    _c: JClass,
    n: jint,
    seed: jlong,
    key: JString,
) -> jintArray {
    let key = jstr(&mut env, &key).unwrap_or_default();
    let perm: Vec<jint> = order::shuffle_indices(n.max(0) as usize, seed as u64, &key).into_iter().map(|i| i as jint).collect();
    match env.new_int_array(perm.len() as i32) {
        Ok(arr) => {
            let _ = env.set_int_array_region(&arr, 0, &perm);
            arr.into_raw()
        }
        Err(_) => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_orderDigest(mut env: JNIEnv, _c: JClass, ids: JObjectArray) -> jstring {
    let ids = jstrings(&mut env, &ids);
    let d = trace::order_digest(&ids);
    new_jstring(&mut env, &d)
}

/// Short (128-bit) BLAKE3 hex digest of a byte array.
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_digest(mut env: JNIEnv, _c: JClass, data: JByteArray) -> jstring {
    let bytes = env.convert_byte_array(&data).unwrap_or_default();
    let d = digest_bytes(&bytes).short();
    new_jstring(&mut env, &d)
}

/// Short BLAKE3 digest of a file's content, streamed (null if unreadable).
pub fn digest_file(path: &str) -> Option<String> {
    let mut f = std::fs::File::open(path).ok()?;
    let mut h = blake3::Hasher::new();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        let n = f.read(&mut buf).ok()?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Some(detpy_core::fingerprint::hex(&h.finalize().as_bytes()[..16]))
}

#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_digestFile(mut env: JNIEnv, _c: JClass, path: JString) -> jstring {
    let p = jstr(&mut env, &path).unwrap_or_default();
    match digest_file(&p) {
        Some(d) => new_jstring(&mut env, &d),
        None => std::ptr::null_mut(),
    }
}

/// Concatenate partial traces (one per test JVM, in execution order) into one
/// trace; returns `{"n_tests":..,"order_digest":..,"skipped":[..]}`.
#[no_mangle]
pub extern "system" fn Java_dev_fenvix_rt_Native_mergeTraces(
    mut env: JNIEnv,
    _c: JClass,
    parts: JObjectArray,
    out: JString,
    meta_json: JString,
    order: JObjectArray,
) -> jstring {
    let parts = jstrings(&mut env, &parts);
    let out = jstr(&mut env, &out).unwrap_or_default();
    let meta = jstr(&mut env, &meta_json).unwrap_or_else(|| "{}".into());
    let order = jstrings(&mut env, &order);
    let meta: serde_json::Value = match serde_json::from_str(&meta) {
        Ok(m) => m,
        Err(e) => {
            throw(&mut env, format!("bad meta json: {e}"));
            return std::ptr::null_mut();
        }
    };
    match trace::merge_traces(&parts, &PathBuf::from(out), &Header::new(meta, order)) {
        Ok((footer, skipped)) => {
            let j = serde_json::json!({"n_tests": footer.n_tests, "order_digest": footer.order_digest, "skipped": skipped});
            new_jstring(&mut env, &j.to_string())
        }
        Err(e) => {
            throw(&mut env, e.to_string());
            std::ptr::null_mut()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn packed_roundtrip() {
        let s = format!("2{FIELD_SEP}time{FIELD_SEP}System.nanoTime{FIELD_SEP}src/test/java/A.java:3{FIELD_SEP}v{FIELD_SEP}x");
        let e = parse_packed(&s).unwrap();
        assert_eq!(e.thread, 2);
        assert_eq!(e.source, Source::Time);
        assert_eq!(e.value, format!("v{FIELD_SEP}x"));
        assert!(parse_packed("bad").is_none());
    }

    #[test]
    fn digest_file_matches_digest_bytes() {
        let dir = std::env::temp_dir().join(format!("fenvix-jvm-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("f.bin");
        let data: Vec<u8> = (0..200_000u32).map(|i| (i % 251) as u8).collect();
        std::fs::write(&p, &data).unwrap();
        assert_eq!(digest_file(p.to_str().unwrap()).unwrap(), digest_bytes(&data).short());
        assert!(digest_file("/nonexistent/x").is_none());
    }
}
