//! Trace format (JSON Lines, versioned).
//!
//! ```text
//! {"type":"header","format":"detpy-trace","version":1,"encoding":1,"meta":{...},"order":[...]}
//! {"type":"test", ...TestRecord...}            one line per executed test
//! {"type":"footer","n_tests":N,"order_digest":"..."}
//! ```
//!
//! The header carries free-form metadata supplied by the producer (seed,
//! hash seed, python version, which controls were active, ...) and the
//! executed order of the tests. Each test line is flushed as soon as the test
//! finishes so a crashed run still leaves a usable partial trace (no footer).

use crate::event::ENCODING_VERSION;
use crate::fingerprint::{digest_bytes, TestRecord};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::path::Path;

pub const TRACE_FORMAT: &str = "detpy-trace";
pub const TRACE_VERSION: u32 = 1;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Header {
    pub format: String,
    pub version: u32,
    pub encoding: u32,
    #[serde(default)]
    pub meta: serde_json::Value,
    #[serde(default)]
    pub order: Vec<String>,
}

impl Header {
    pub fn new(meta: serde_json::Value, order: Vec<String>) -> Self {
        Header { format: TRACE_FORMAT.into(), version: TRACE_VERSION, encoding: ENCODING_VERSION, meta, order }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Footer {
    pub n_tests: u64,
    pub order_digest: String,
    /// Merged trace of a parallel run: tests the plan gave a worker that left no line (the worker died).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub missing: Vec<String>,
    /// Merged trace of a parallel run: digest of the plan (`schedule::plan_digest`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub plan_digest: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
enum Line {
    Header(Header),
    Test(TestRecord),
    Footer(Footer),
}

/// A test line serialized from a borrowed record (byte-identical to `Line::Test`, without copying the events).
#[derive(Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
enum TestLine<'a> {
    Test(&'a TestRecord),
}

/// Digest of an ordered list of test ids.
pub fn order_digest<S: AsRef<str>>(ids: &[S]) -> String {
    let mut buf = Vec::new();
    for id in ids {
        buf.extend_from_slice(&(id.as_ref().len() as u64).to_le_bytes());
        buf.extend_from_slice(id.as_ref().as_bytes());
    }
    digest_bytes(&buf).short()
}

pub struct TraceWriter {
    out: BufWriter<File>,
    executed: Vec<String>,
}

impl TraceWriter {
    pub fn create(path: &Path, header: &Header) -> io::Result<Self> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let mut w = TraceWriter { out: BufWriter::new(File::create(path)?), executed: Vec::new() };
        w.write_line(&Line::Header(header.clone()))?;
        Ok(w)
    }

    fn write_line(&mut self, line: &Line) -> io::Result<()> {
        serde_json::to_writer(&mut self.out, line).map_err(io::Error::other)?;
        self.out.write_all(b"\n")?;
        self.out.flush()
    }

    pub fn write_test(&mut self, rec: &TestRecord) -> io::Result<()> {
        self.executed.push(rec.nodeid.clone());
        serde_json::to_writer(&mut self.out, &TestLine::Test(rec)).map_err(io::Error::other)?;
        self.out.write_all(b"\n")?;
        self.out.flush()
    }

    pub fn finish(self) -> io::Result<Footer> {
        self.finish_with(Vec::new(), None)
    }

    pub fn finish_with(mut self, missing: Vec<String>, plan_digest: Option<String>) -> io::Result<Footer> {
        let footer =
            Footer { n_tests: self.executed.len() as u64, order_digest: order_digest(&self.executed), missing, plan_digest };
        self.write_line(&Line::Footer(footer.clone()))?;
        Ok(footer)
    }
}

/// A fully loaded trace.
#[derive(Clone, Debug)]
pub struct Trace {
    pub header: Header,
    pub tests: Vec<TestRecord>,
    pub footer: Option<Footer>,
}

impl Trace {
    pub fn executed_order(&self) -> Vec<&str> {
        self.tests.iter().map(|t| t.nodeid.as_str()).collect()
    }

    pub fn get(&self, nodeid: &str) -> Option<&TestRecord> {
        // Traces are small enough that a linear scan is fine; the verifier
        // builds its own index.
        self.tests.iter().find(|t| t.nodeid == nodeid)
    }

    pub fn is_complete(&self) -> bool {
        self.footer.is_some()
    }
}

#[derive(Debug)]
pub enum TraceError {
    Io(io::Error),
    Parse { line: usize, msg: String },
    Format(String),
}

impl std::fmt::Display for TraceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TraceError::Io(e) => write!(f, "I/O error: {e}"),
            TraceError::Parse { line, msg } => write!(f, "parse error at line {line}: {msg}"),
            TraceError::Format(m) => write!(f, "invalid trace: {m}"),
        }
    }
}

impl std::error::Error for TraceError {}

impl From<io::Error> for TraceError {
    fn from(e: io::Error) -> Self {
        TraceError::Io(e)
    }
}

/// One worker's trace in a parallel run.
#[derive(Clone, Debug)]
pub struct WorkerTrace {
    /// Worker id (`gw0`, ...).
    pub worker: String,
    pub path: std::path::PathBuf,
    /// The test ids the plan gave this worker, in its order.
    pub planned: Vec<String>,
}

/// What [`merge_traces`] wrote.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct MergeSummary {
    pub n_tests: u64,
    /// Planned tests no worker trace has a line for.
    pub missing: Vec<String>,
    /// Workers whose trace could not be read at all.
    pub unreadable: Vec<String>,
    /// Lines for a test already merged from another worker (dropped).
    pub duplicates: u64,
    /// (nodeid, fingerprint, outcome, worker) of every merged test, in merged order.
    pub tests: Vec<(String, String, String, String)>,
}

/// A trace whose last line may be cut (a worker killed while writing): lines are read up to the first one that
/// does not parse.
pub fn read_trace_lenient(path: &Path) -> Result<Trace, TraceError> {
    let reader = BufReader::new(File::open(path)?);
    let mut header = None;
    let mut tests = Vec::new();
    let mut footer = None;
    for line in reader.lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        match serde_json::from_str::<Line>(&line) {
            Ok(Line::Header(h)) => header = Some(h),
            Ok(Line::Test(t)) => tests.push(t),
            Ok(Line::Footer(f)) => footer = Some(f),
            Err(_) => break,
        }
    }
    let header = header.ok_or_else(|| TraceError::Format("missing header".into()))?;
    Ok(Trace { header, tests, footer })
}

/// Merge the traces of a parallel run into one trace at `out`.
///
/// The header carries `meta` (the plan goes there) and `order`, the serial order of the session. Test lines are
/// sorted by their position in `order` (tests absent from `order` follow, by node id), each one with `worker` and
/// `worker_index` (its position in the worker's trace) and `index` = its position among the executed tests, as a
/// serial run of the same tests would number them. The footer's order digest is the digest of the merged test
/// order; planned tests without a line are listed in `missing`. The output is a pure function of the inputs:
/// merging the same worker traces twice gives byte-identical files.
pub fn merge_traces(
    order: &[String],
    workers: &[WorkerTrace],
    meta: serde_json::Value,
    plan_digest: Option<String>,
    out: &Path,
) -> Result<MergeSummary, TraceError> {
    let pos: std::collections::HashMap<&str, usize> = order.iter().enumerate().map(|(i, s)| (s.as_str(), i)).collect();
    let mut summary = MergeSummary::default();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut recs: Vec<TestRecord> = Vec::new();
    for w in workers {
        let t = match read_trace_lenient(&w.path) {
            Ok(t) => t,
            Err(_) => {
                summary.unreadable.push(w.worker.clone());
                continue;
            }
        };
        for (i, mut r) in t.tests.into_iter().enumerate() {
            if !seen.insert(r.nodeid.clone()) {
                summary.duplicates += 1;
                continue;
            }
            r.worker = Some(w.worker.clone());
            r.worker_index = Some(i as u64);
            recs.push(r);
        }
    }
    recs.sort_by(|a, b| {
        let pa = pos.get(a.nodeid.as_str()).copied().unwrap_or(usize::MAX);
        let pb = pos.get(b.nodeid.as_str()).copied().unwrap_or(usize::MAX);
        pa.cmp(&pb).then_with(|| a.nodeid.cmp(&b.nodeid))
    });
    for w in workers {
        for id in &w.planned {
            if !seen.contains(id) {
                summary.missing.push(id.clone());
            }
        }
    }
    summary.missing.sort_by_key(|id| pos.get(id.as_str()).copied().unwrap_or(usize::MAX));
    summary.missing.dedup();
    let mut writer = TraceWriter::create(out, &Header::new(meta, order.to_vec()))?;
    for (i, r) in recs.iter_mut().enumerate() {
        r.index = i as u64;
        writer.write_test(r)?;
        summary.tests.push((
            r.nodeid.clone(),
            r.fingerprint.clone(),
            r.outcome.clone(),
            r.worker.clone().unwrap_or_default(),
        ));
    }
    let footer = writer.finish_with(summary.missing.clone(), plan_digest)?;
    summary.n_tests = footer.n_tests;
    Ok(summary)
}

pub fn read_trace(path: &Path) -> Result<Trace, TraceError> {
    read_trace_from(BufReader::new(File::open(path)?))
}

pub fn read_trace_from<R: BufRead>(reader: R) -> Result<Trace, TraceError> {
    let mut header = None;
    let mut tests = Vec::new();
    let mut footer = None;
    for (i, line) in reader.lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let parsed: Line =
            serde_json::from_str(&line).map_err(|e| TraceError::Parse { line: i + 1, msg: e.to_string() })?;
        match parsed {
            Line::Header(h) => {
                if h.format != TRACE_FORMAT {
                    return Err(TraceError::Format(format!("unknown format {:?}", h.format)));
                }
                if h.version > TRACE_VERSION {
                    return Err(TraceError::Format(format!("unsupported version {}", h.version)));
                }
                header = Some(h)
            }
            Line::Test(t) => tests.push(t),
            Line::Footer(f) => footer = Some(f),
        }
    }
    let header = header.ok_or_else(|| TraceError::Format("missing header".into()))?;
    Ok(Trace { header, tests, footer })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::{Event, Source};
    use crate::fingerprint::Fingerprinter;

    fn record(nodeid: &str, idx: u64, n: usize) -> TestRecord {
        let mut f = Fingerprinter::default();
        for i in 0..n {
            f.push(Event::new(Source::Random, "random.random", "t.py:2", i.to_string()));
        }
        f.finish(nodeid, idx, "passed")
    }

    #[test]
    fn roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("sub/run.jsonl");
        let header = Header::new(serde_json::json!({"seed": 3}), vec!["a".into(), "b".into()]);
        let mut w = TraceWriter::create(&path, &header).unwrap();
        w.write_test(&record("a", 0, 3)).unwrap();
        w.write_test(&record("b", 1, 0)).unwrap();
        let footer = w.finish().unwrap();
        assert_eq!(footer.n_tests, 2);
        assert_eq!(footer.order_digest, order_digest(&["a", "b"]));

        let t = read_trace(&path).unwrap();
        assert_eq!(t.header, header);
        assert_eq!(t.tests.len(), 2);
        assert_eq!(t.tests[0], record("a", 0, 3));
        assert!(t.is_complete());
        assert_eq!(t.executed_order(), vec!["a", "b"]);
    }

    #[test]
    fn partial_trace_is_readable() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("run.jsonl");
        let mut w = TraceWriter::create(&path, &Header::new(serde_json::Value::Null, vec![])).unwrap();
        w.write_test(&record("a", 0, 1)).unwrap();
        drop(w); // crash: no footer
        let t = read_trace(&path).unwrap();
        assert!(!t.is_complete());
        assert_eq!(t.tests.len(), 1);
    }

    #[test]
    fn rejects_garbage() {
        let err = read_trace_from(io::Cursor::new("{\"type\":\"test\"}\n")).unwrap_err();
        assert!(matches!(err, TraceError::Parse { line: 1, .. }));
        let err = read_trace_from(io::Cursor::new("")).unwrap_err();
        assert!(matches!(err, TraceError::Format(_)));
        let bad = r#"{"type":"header","format":"other","version":1,"encoding":1}"#;
        assert!(matches!(read_trace_from(io::Cursor::new(bad)).unwrap_err(), TraceError::Format(_)));
    }

    #[test]
    fn order_digest_is_order_sensitive() {
        assert_ne!(order_digest(&["a", "b"]), order_digest(&["b", "a"]));
        assert_ne!(order_digest(&["ab"]), order_digest(&["a", "b"]));
    }
}

#[cfg(test)]
mod merge_tests {
    use super::*;
    use crate::event::{Event, Source};
    use crate::fingerprint::Fingerprinter;

    fn record(nodeid: &str, idx: u64, v: &str) -> TestRecord {
        let mut f = Fingerprinter::default();
        f.push(Event::new(Source::Random, "random.random", "t.py:2", v));
        f.finish(nodeid, idx, "passed")
    }

    fn write(path: &Path, ids: &[&str], footer: bool) {
        let mut w = TraceWriter::create(path, &Header::new(serde_json::json!({"worker": "x"}), vec![])).unwrap();
        for (i, id) in ids.iter().enumerate() {
            w.write_test(&record(id, i as u64, id)).unwrap();
        }
        if footer {
            w.finish().unwrap();
        }
    }

    #[test]
    fn merge_sorts_by_serial_order_and_marks_workers() {
        let d = tempfile::tempdir().unwrap();
        let order: Vec<String> = ["a", "b", "c", "d", "e"].iter().map(|s| s.to_string()).collect();
        write(&d.path().join("gw0.jsonl"), &["a", "d"], true);
        write(&d.path().join("gw1.jsonl"), &["b", "c", "e"], true);
        let ws = vec![
            WorkerTrace { worker: "gw0".into(), path: d.path().join("gw0.jsonl"), planned: vec!["a".into(), "d".into()] },
            WorkerTrace {
                worker: "gw1".into(),
                path: d.path().join("gw1.jsonl"),
                planned: vec!["b".into(), "c".into(), "e".into()],
            },
        ];
        let out = d.path().join("m.jsonl");
        let s = merge_traces(&order, &ws, serde_json::json!({"plan": 1}), Some("pd".into()), &out).unwrap();
        assert_eq!(s.n_tests, 5);
        assert!(s.missing.is_empty());
        let t = read_trace(&out).unwrap();
        assert_eq!(t.executed_order(), vec!["a", "b", "c", "d", "e"]);
        assert_eq!(t.header.order, order);
        assert_eq!(t.tests[3].worker.as_deref(), Some("gw0"));
        assert_eq!(t.tests[3].worker_index, Some(1));
        assert_eq!(t.tests[3].index, 3);
        let f = t.footer.unwrap();
        assert_eq!(f.order_digest, order_digest(&order));
        assert_eq!(f.plan_digest.as_deref(), Some("pd"));
        // byte-identical when merged again from the same worker traces
        let out2 = d.path().join("m2.jsonl");
        merge_traces(&order, &ws, serde_json::json!({"plan": 1}), Some("pd".into()), &out2).unwrap();
        assert_eq!(std::fs::read(&out).unwrap(), std::fs::read(&out2).unwrap());
        // the fingerprints are the workers' own
        let w0 = read_trace(&d.path().join("gw0.jsonl")).unwrap();
        assert_eq!(t.tests[0].fingerprint, w0.tests[0].fingerprint);
    }

    #[test]
    fn a_dead_worker_leaves_missing_tests() {
        let d = tempfile::tempdir().unwrap();
        let order: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        write(&d.path().join("gw0.jsonl"), &["a"], false); // killed: no footer
        // a cut last line
        let mut raw = std::fs::read_to_string(d.path().join("gw0.jsonl")).unwrap();
        raw.push_str("{\"type\":\"test\",\"nodeid\":\"b\"");
        std::fs::write(d.path().join("gw0.jsonl"), raw).unwrap();
        let ws = vec![
            WorkerTrace {
                worker: "gw0".into(),
                path: d.path().join("gw0.jsonl"),
                planned: vec!["a".into(), "b".into(), "c".into()],
            },
            WorkerTrace { worker: "gw1".into(), path: d.path().join("absent.jsonl"), planned: vec![] },
        ];
        let s = merge_traces(&order, &ws, serde_json::Value::Null, None, &d.path().join("m.jsonl")).unwrap();
        assert_eq!(s.missing, vec!["b".to_string(), "c".to_string()]);
        assert_eq!(s.unreadable, vec!["gw1".to_string()]);
        let t = read_trace(&d.path().join("m.jsonl")).unwrap();
        assert_eq!(t.footer.unwrap().missing, vec!["b".to_string(), "c".to_string()]);
    }

    #[test]
    fn serial_trace_lines_have_no_worker_fields() {
        let rec = record("a", 0, "1");
        let line = serde_json::to_string(&TestLine::Test(&rec)).unwrap();
        assert!(!line.contains("worker"));
        let f = Footer { n_tests: 0, order_digest: "x".into(), missing: vec![], plan_digest: None };
        assert_eq!(serde_json::to_string(&f).unwrap(), r#"{"n_tests":0,"order_digest":"x"}"#);
    }
}

#[cfg(test)]
mod borrowed_line_tests {
    use super::*;
    use crate::event::{Event, Source};
    use crate::fingerprint::Fingerprinter;

    #[test]
    fn borrowed_test_line_is_byte_identical() {
        let mut fp = Fingerprinter::new(10, 2);
        for i in 0..25 {
            fp.push(Event::new(Source::Time, "time.time", "a.py:1", &i.to_string()));
        }
        let rec = fp.finish("t::x \"q\"", 3, "passed");
        let a = serde_json::to_string(&Line::Test(rec.clone())).unwrap();
        let b = serde_json::to_string(&TestLine::Test(&rec)).unwrap();
        assert_eq!(a, b);
    }
}
