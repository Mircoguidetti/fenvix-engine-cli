//! Recorder: per-test fingerprinting plus streaming trace output.

use crate::backend::EventSink;
use crate::event::Event;
use crate::fingerprint::{Fingerprinter, TestRecord, DEFAULT_CHECKPOINT_EVERY, DEFAULT_MAX_EVENTS};
use crate::trace::{Footer, Header, TraceWriter};
use std::io;
use std::path::Path;

#[derive(Clone, Copy, Debug)]
pub struct RecorderConfig {
    pub max_events: usize,
    pub checkpoint_every: u64,
}

impl Default for RecorderConfig {
    fn default() -> Self {
        RecorderConfig { max_events: DEFAULT_MAX_EVENTS, checkpoint_every: DEFAULT_CHECKPOINT_EVERY }
    }
}

struct Current {
    nodeid: String,
    index: u64,
    fp: Fingerprinter,
}

/// Lightweight summary kept in memory for every finished test.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Finished {
    pub nodeid: String,
    pub outcome: String,
    pub fingerprint: String,
    pub n_events: u64,
}

pub struct Recorder {
    cfg: RecorderConfig,
    writer: Option<TraceWriter>,
    current: Option<Current>,
    finished: Vec<Finished>,
    /// Events received while no test was active (collection, session teardown).
    pub dropped: u64,
}

impl Recorder {
    pub fn new(cfg: RecorderConfig) -> Self {
        Recorder { cfg, writer: None, current: None, finished: Vec::new(), dropped: 0 }
    }

    /// Start streaming the trace to `path`.
    pub fn open(&mut self, path: &Path, header: &Header) -> io::Result<()> {
        self.writer = Some(TraceWriter::create(path, header)?);
        Ok(())
    }

    pub fn in_test(&self) -> bool {
        self.current.is_some()
    }

    pub fn current_events(&self) -> u64 {
        self.current.as_ref().map(|c| c.fp.len()).unwrap_or(0)
    }

    /// Begin a test. A test left open (e.g. the process was interrupted
    /// inside a hook) is closed with outcome `interrupted`.
    pub fn begin_test(&mut self, nodeid: &str, index: u64) -> io::Result<()> {
        if self.current.is_some() {
            self.end_test("interrupted")?;
        }
        self.current = Some(Current {
            nodeid: nodeid.to_string(),
            index,
            fp: Fingerprinter::new(self.cfg.max_events, self.cfg.checkpoint_every),
        });
        Ok(())
    }

    pub fn end_test(&mut self, outcome: &str) -> io::Result<Option<TestRecord>> {
        let Some(cur) = self.current.take() else { return Ok(None) };
        let rec = cur.fp.finish(&cur.nodeid, cur.index, outcome);
        if let Some(w) = self.writer.as_mut() {
            w.write_test(&rec)?;
        }
        self.finished.push(Finished {
            nodeid: rec.nodeid.clone(),
            outcome: rec.outcome.clone(),
            fingerprint: rec.fingerprint.clone(),
            n_events: rec.n_events,
        });
        Ok(Some(rec))
    }

    pub fn finished(&self) -> &[Finished] {
        &self.finished
    }

    pub fn close(&mut self) -> io::Result<Option<Footer>> {
        if self.current.is_some() {
            self.end_test("interrupted")?;
        }
        match self.writer.take() {
            Some(w) => w.finish().map(Some),
            None => Ok(None),
        }
    }
}

impl EventSink for Recorder {
    fn record(&mut self, event: Event) {
        match self.current.as_mut() {
            Some(cur) => cur.fp.push(event),
            None => self.dropped += 1,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::Source;
    use crate::trace::read_trace;

    #[test]
    fn records_and_streams() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("t.jsonl");
        let mut r = Recorder::new(RecorderConfig::default());
        r.open(&path, &Header::new(serde_json::json!({}), vec!["a".into(), "b".into()])).unwrap();
        r.record(Event::new(Source::Time, "time.time", "", "0")); // outside any test
        r.begin_test("a", 0).unwrap();
        r.record(Event::new(Source::Time, "time.time", "x.py:1", "1"));
        assert_eq!(r.current_events(), 1);
        let rec = r.end_test("passed").unwrap().unwrap();
        assert_eq!(rec.n_events, 2);
        r.begin_test("b", 1).unwrap();
        let footer = r.close().unwrap().unwrap();
        assert_eq!(footer.n_tests, 2);
        assert_eq!(r.dropped, 1);
        assert_eq!(r.finished()[1].outcome, "interrupted");
        let t = read_trace(&path).unwrap();
        assert_eq!(t.tests.len(), 2);
        assert_eq!(t.tests[0].fingerprint, rec.fingerprint);
    }

    #[test]
    fn end_without_begin_is_noop() {
        let mut r = Recorder::new(RecorderConfig::default());
        assert!(r.end_test("passed").unwrap().is_none());
        assert!(r.close().unwrap().is_none());
    }
}
