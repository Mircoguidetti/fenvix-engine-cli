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

    pub fn finish(mut self) -> io::Result<Footer> {
        let footer = Footer { n_tests: self.executed.len() as u64, order_digest: order_digest(&self.executed) };
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
