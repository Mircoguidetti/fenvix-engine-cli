//! Where the verifier reads test records from, in bounded memory (P0 big trace).
//!
//! The verifier needs, for every test of every run, a handful of scalar fields and a few values derived from the
//! record's events (the [`SlimRecord`]); it needs the events themselves only for a test whose fingerprints differ,
//! and then only for two records at a time. A [`RecordSource`] gives both: `slim(i)` from memory, `full(i)` loaded on
//! demand.
//!
//! * [`MemTrace`] borrows a loaded [`Trace`] (what `verify::verify` is given);
//! * [`FileTrace`] reads a trace file once, keeping the header, the footer and one `SlimRecord` per test, and loads a
//!   record again by its byte offset when the verifier asks for it. A 1.2 GB trace held ~8x its size when loaded
//!   whole; this holds the slim records only.
//!
//! `FileTrace::open` applies `read_trace`'s strict rules: the same `Parse { line }` error with the same line numbers
//! (blank lines counted), the same UTF-8, format and version checks, and the last header/footer line wins.

use crate::event::Event;
use crate::fingerprint::{fingerprint_of, TestRecord, UNCONTROLLED_PREFIX};
use crate::trace::{Footer, Header, Line, Trace, TraceError, TRACE_FORMAT, TRACE_VERSION};
use std::cell::RefCell;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::{self, BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::Path;

/// The environment variables a record's stored events read (`env.get` / `env.has`: the name before `=`), whether it
/// enumerated the environment (`env.list`), and the site of the first of those events.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SlimEnvReads {
    pub names: BTreeSet<String>,
    pub list: bool,
    pub site: Option<String>,
}

/// Every scalar field of a [`TestRecord`] plus what the verifier derives from its events.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlimRecord {
    pub nodeid: String,
    pub index: u64,
    pub outcome: String,
    pub fingerprint: String,
    pub n_events: u64,
    pub truncated: bool,
    pub worker: Option<String>,
    pub worker_index: Option<u64>,
    pub uncontrolled: Vec<String>,
    pub unaccounted: Vec<String>,
    /// `events.len()` (stored events).
    pub events_len: usize,
    /// `fingerprint_of(&events)`; computed only for a record that is not truncated (the only case the general rule
    /// checks it, `provable::judge_slim`), empty otherwise.
    pub events_fingerprint: String,
    /// Index and copy of the first stored event whose op starts with `uncontrolled.`.
    pub first_uncontrolled: Option<(usize, Event)>,
    pub env_reads: SlimEnvReads,
    /// Byte offset and length of the record's line in its file (0, 0 for an in-memory record).
    pub offset: u64,
    pub length: u64,
}

impl SlimRecord {
    pub fn of(r: &TestRecord, offset: u64, length: u64) -> SlimRecord {
        let mut env = SlimEnvReads::default();
        for e in &r.events {
            match e.op.as_str() {
                "env.get" | "env.has" => {
                    let name = e.value.split_once('=').map(|(n, _)| n).unwrap_or(e.value.as_str());
                    env.names.insert(name.to_string());
                    env.site.get_or_insert_with(|| e.site.clone());
                }
                "env.list" => {
                    env.list = true;
                    env.site.get_or_insert_with(|| e.site.clone());
                }
                _ => {}
            }
        }
        let first_uncontrolled =
            r.events.iter().position(|e| e.op.starts_with(UNCONTROLLED_PREFIX)).map(|i| (i, r.events[i].clone()));
        SlimRecord {
            nodeid: r.nodeid.clone(),
            index: r.index,
            outcome: r.outcome.clone(),
            fingerprint: r.fingerprint.clone(),
            n_events: r.n_events,
            truncated: r.truncated,
            worker: r.worker.clone(),
            worker_index: r.worker_index,
            uncontrolled: r.uncontrolled.clone(),
            unaccounted: r.unaccounted.clone(),
            events_len: r.events.len(),
            events_fingerprint: if r.truncated { String::new() } else { fingerprint_of(&r.events) },
            first_uncontrolled,
            env_reads: env,
            offset,
            length,
        }
    }
}

/// The records of one run, as the verifier reads them.
pub trait RecordSource {
    fn header(&self) -> &Header;
    fn footer(&self) -> Option<&Footer>;
    fn len(&self) -> usize;
    fn is_empty(&self) -> bool {
        self.len() == 0
    }
    fn slim(&self, i: usize) -> &SlimRecord;
    /// The whole record `i` (with its events), loaded for the caller; drop it before loading many more.
    fn full(&self, i: usize) -> io::Result<TestRecord>;
}

/// A loaded trace, borrowed (never cloned whole).
pub struct MemTrace<'a> {
    pub trace: &'a Trace,
    pub slims: Vec<SlimRecord>,
}

impl<'a> MemTrace<'a> {
    pub fn new(trace: &'a Trace) -> Self {
        MemTrace { trace, slims: trace.tests.iter().map(|r| SlimRecord::of(r, 0, 0)).collect() }
    }
}

impl RecordSource for MemTrace<'_> {
    fn header(&self) -> &Header {
        &self.trace.header
    }
    fn footer(&self) -> Option<&Footer> {
        self.trace.footer.as_ref()
    }
    fn len(&self) -> usize {
        self.slims.len()
    }
    fn slim(&self, i: usize) -> &SlimRecord {
        &self.slims[i]
    }
    fn full(&self, i: usize) -> io::Result<TestRecord> {
        Ok(self.trace.tests[i].clone())
    }
}

/// A trace file read once; records loaded again by offset.
pub struct FileTrace {
    pub header: Header,
    pub footer: Option<Footer>,
    pub slims: Vec<SlimRecord>,
    file: RefCell<File>,
}

const INVALID_UTF8: &str = "stream did not contain valid UTF-8";

impl FileTrace {
    pub fn open(path: &Path) -> Result<FileTrace, TraceError> {
        let mut reader = BufReader::with_capacity(1 << 20, File::open(path)?);
        let mut header = None;
        let mut footer = None;
        let mut slims = Vec::new();
        let mut buf: Vec<u8> = Vec::new();
        let mut offset = 0u64;
        let mut i = 0usize;
        loop {
            buf.clear();
            let n = reader.read_until(b'\n', &mut buf)?;
            if n == 0 {
                break;
            }
            let start = offset;
            offset += n as u64;
            // BufRead::lines: the line without its "\n" and one "\r" before it
            let mut end = buf.len();
            if end > 0 && buf[end - 1] == b'\n' {
                end -= 1;
                if end > 0 && buf[end - 1] == b'\r' {
                    end -= 1;
                }
            }
            let line = std::str::from_utf8(&buf[..end])
                .map_err(|_| TraceError::Io(io::Error::new(io::ErrorKind::InvalidData, INVALID_UTF8)))?;
            let lineno = i + 1;
            i += 1;
            if line.trim().is_empty() {
                continue;
            }
            let parsed: Line =
                serde_json::from_str(line).map_err(|e| TraceError::Parse { line: lineno, msg: e.to_string() })?;
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
                Line::Test(t) => slims.push(SlimRecord::of(&t, start, end as u64)),
                Line::Footer(f) => footer = Some(f),
            }
        }
        let header = header.ok_or_else(|| TraceError::Format("missing header".into()))?;
        Ok(FileTrace { header, footer, slims, file: RefCell::new(File::open(path)?) })
    }
}

impl RecordSource for FileTrace {
    fn header(&self) -> &Header {
        &self.header
    }
    fn footer(&self) -> Option<&Footer> {
        self.footer.as_ref()
    }
    fn len(&self) -> usize {
        self.slims.len()
    }
    fn slim(&self, i: usize) -> &SlimRecord {
        &self.slims[i]
    }
    fn full(&self, i: usize) -> io::Result<TestRecord> {
        let s = &self.slims[i];
        let mut f = self.file.borrow_mut();
        f.seek(SeekFrom::Start(s.offset))?;
        let mut buf = vec![0u8; s.length as usize];
        f.read_exact(&mut buf)?;
        match serde_json::from_slice::<Line>(&buf).map_err(io::Error::other)? {
            Line::Test(t) => Ok(t),
            _ => Err(io::Error::new(io::ErrorKind::InvalidData, format!("line at byte {} is not a test record", s.offset))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::trace::read_trace;
    use std::io::Write;

    fn write(dir: &Path, name: &str, text: &str) -> std::path::PathBuf {
        let p = dir.join(name);
        std::fs::File::create(&p).unwrap().write_all(text.as_bytes()).unwrap();
        p
    }

    const H: &str = r#"{"type":"header","format":"detpy-trace","version":1,"encoding":2,"meta":{},"order":[]}"#;
    const T: &str = r#"{"type":"test","nodeid":"a","index":0,"outcome":"passed","fingerprint":"f","n_events":0,"truncated":false,"counts":{},"checkpoints":[],"events":[]}"#;

    /// protects=FileTrace::open reports a bad line exactly as read_trace does (same line number, blank lines and
    /// CRLF counted); fails_when=the streaming reader numbers lines differently or accepts a line read_trace refuses;
    /// no_claim=the text of serde's message beyond equality with read_trace's.
    #[test]
    fn strict_errors_match_read_trace_line_numbers() {
        let d = tempfile::tempdir().unwrap();
        let p = write(d.path(), "bad.jsonl", &format!("{H}\r\n\n{T}\n   \n{{\"type\":\"test\",\"nodeid\":\n"));
        let a = read_trace(&p).unwrap_err();
        let b = FileTrace::open(&p).err().unwrap();
        assert!(matches!(a, TraceError::Parse { line: 5, .. }), "{a}");
        assert_eq!(a.to_string(), b.to_string());
        // invalid UTF-8 is an I/O error in both
        let p = write(d.path(), "utf.jsonl", &format!("{H}\n"));
        std::fs::OpenOptions::new().append(true).open(&p).unwrap().write_all(b"\xff\xfe\n").unwrap();
        assert_eq!(read_trace(&p).unwrap_err().to_string(), FileTrace::open(&p).err().unwrap().to_string());
        // no header
        let p = write(d.path(), "nohead.jsonl", &format!("{T}\n"));
        assert_eq!(read_trace(&p).unwrap_err().to_string(), FileTrace::open(&p).err().unwrap().to_string());
    }

    /// protects=FileTrace::open refuses a format or version read_trace refuses, with the same message;
    /// fails_when=the streaming reader is lenient (reads a newer version or a foreign format);
    /// no_claim=behaviour for versions read_trace accepts (covered by the golden corpus).
    #[test]
    fn strict_errors_match_read_trace_version_and_format() {
        let d = tempfile::tempdir().unwrap();
        for head in [
            H.replace(r#""version":1"#, r#""version":2"#),
            H.replace("detpy-trace", "other-trace"),
        ] {
            let p = write(d.path(), "v.jsonl", &format!("{head}\n{T}\n"));
            let a = read_trace(&p).unwrap_err();
            let b = FileTrace::open(&p).err().unwrap();
            assert!(matches!(a, TraceError::Format(_)), "{a}");
            assert_eq!(a.to_string(), b.to_string());
        }
    }

    /// protects=full(i) returns exactly the record read_trace loads, by offset, CRLF lines and a last line without
    /// a newline included; fails_when=an offset or length is off by one; no_claim=concurrent modification of the file.
    #[test]
    fn full_loads_the_record_by_offset() {
        let d = tempfile::tempdir().unwrap();
        let t2 = T.replace(r#""nodeid":"a""#, r#""nodeid":"é b""#);
        let p = write(d.path(), "ok.jsonl", &format!("{H}\r\n{T}\r\n\n{t2}"));
        let ft = FileTrace::open(&p).unwrap();
        let tr = read_trace(&p).unwrap();
        assert_eq!(ft.len(), 2);
        for i in 0..2 {
            assert_eq!(ft.full(i).unwrap(), tr.tests[i]);
            assert_eq!(ft.slim(i), &SlimRecord { offset: ft.slim(i).offset, length: ft.slim(i).length, ..SlimRecord::of(&tr.tests[i], 0, 0) });
        }
    }
}
