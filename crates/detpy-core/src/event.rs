//! Events: the unit of observation.
//!
//! An [`Event`] is one interaction of the code under test with a source of
//! non-determinism (a clock read, a random draw, a directory listing, a network
//! connection, ...). Events are produced by an interception *backend*: today the
//! Python-level hooks of the pytest plugin, in the future a syscall-level tracer
//! (see [`crate::backend`]). The fingerprint of a test is a hash chain over the
//! canonical encoding of its events, so the encoding below is part of the
//! on-disk contract and is versioned by [`ENCODING_VERSION`].

use serde::{Deserialize, Serialize};
use std::fmt;

/// Bump when [`Event::encode`] changes: fingerprints are only comparable
/// between traces produced with the same encoding version.
pub const ENCODING_VERSION: u32 = 1;

/// Category of non-deterministic source an event belongs to.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    /// Clock reads and sleeps (virtualised by Level 0).
    Time,
    /// Pseudo random generators (seeded by Level 0).
    Random,
    /// Filesystem enumeration (ordered by Level 0).
    Fs,
    /// Network access (closed / recorded / replayed by Level 0).
    Net,
    /// OS entropy (`os.urandom`, `uuid4`, `secrets`): observed, NOT controlled.
    Entropy,
    /// Final outcome of the test (always the last event of a test).
    Outcome,
    /// Reserved for a future syscall-level backend (Hermit-style).
    Syscall,
    /// Anything else a backend wants to report.
    Other,
    /// Scheduling choices of the Level 1 runtime (`--det-async`: which ready
    /// external events an asyncio loop iteration delivered, timers fired,
    /// clock jumps). Appended after `Other` so existing tags are unchanged.
    Sched,
}

impl Source {
    pub const ALL: [Source; 9] = [
        Source::Time,
        Source::Random,
        Source::Fs,
        Source::Net,
        Source::Entropy,
        Source::Outcome,
        Source::Syscall,
        Source::Other,
        Source::Sched,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Source::Time => "time",
            Source::Random => "random",
            Source::Fs => "fs",
            Source::Net => "net",
            Source::Entropy => "entropy",
            Source::Outcome => "outcome",
            Source::Syscall => "syscall",
            Source::Other => "other",
            Source::Sched => "sched",
        }
    }

    /// Parse a source name; unknown names map to [`Source::Other`] so that
    /// newer producers never crash older consumers.
    pub fn parse(s: &str) -> Source {
        match s {
            "time" => Source::Time,
            "random" => Source::Random,
            "fs" => Source::Fs,
            "net" => Source::Net,
            "entropy" => Source::Entropy,
            "outcome" => Source::Outcome,
            "syscall" => Source::Syscall,
            "sched" => Source::Sched,
            _ => Source::Other,
        }
    }

    fn tag(self) -> u8 {
        match self {
            Source::Time => 1,
            Source::Random => 2,
            Source::Fs => 3,
            Source::Net => 4,
            Source::Entropy => 5,
            Source::Outcome => 6,
            Source::Syscall => 7,
            Source::Other => 8,
            Source::Sched => 9,
        }
    }
}

impl fmt::Display for Source {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// One observed interaction with a non-deterministic source.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Event {
    /// Logical thread number inside the test (0 = the thread that runs the test,
    /// then 1, 2, ... in order of first appearance).
    #[serde(rename = "t")]
    pub thread: u32,
    #[serde(rename = "s")]
    pub source: Source,
    /// Operation, e.g. `time.monotonic`, `os.listdir`, `socket.connect`.
    #[serde(rename = "o")]
    pub op: String,
    /// Call site (`path:line`) normalised to be machine independent.
    #[serde(rename = "at")]
    pub site: String,
    /// Observed value (normalised, possibly a digest).
    #[serde(rename = "v")]
    pub value: String,
}

impl Event {
    pub fn new(source: Source, op: impl Into<String>, site: impl Into<String>, value: impl Into<String>) -> Self {
        Event { thread: 0, source, op: op.into(), site: site.into(), value: value.into() }
    }

    pub fn with_thread(mut self, thread: u32) -> Self {
        self.thread = thread;
        self
    }

    /// Canonical, unambiguous byte encoding used by the fingerprint chain:
    /// `tag | thread(le u32) | len(op) op | len(site) site | len(value) value`.
    pub fn encode(&self, out: &mut Vec<u8>) {
        out.push(self.source.tag());
        out.extend_from_slice(&self.thread.to_le_bytes());
        for field in [&self.op, &self.site, &self.value] {
            out.extend_from_slice(&(field.len() as u64).to_le_bytes());
            out.extend_from_slice(field.as_bytes());
        }
    }
}

impl fmt::Display for Event {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "[{}] {} @ {} = {}", self.source, self.op, self.site, self.value)?;
        if self.thread != 0 {
            write!(f, " (thread {})", self.thread)?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_roundtrip() {
        for s in Source::ALL {
            assert_eq!(Source::parse(s.as_str()), s);
        }
        assert_eq!(Source::parse("bogus"), Source::Other);
    }

    #[test]
    fn encoding_is_unambiguous() {
        // Moving bytes between fields must change the encoding.
        let a = Event::new(Source::Time, "ab", "c", "");
        let b = Event::new(Source::Time, "a", "bc", "");
        let (mut ea, mut eb) = (Vec::new(), Vec::new());
        a.encode(&mut ea);
        b.encode(&mut eb);
        assert_ne!(ea, eb);
    }

    #[test]
    fn encoding_depends_on_thread_and_source() {
        let a = Event::new(Source::Time, "x", "y", "z");
        let b = a.clone().with_thread(1);
        let c = Event::new(Source::Random, "x", "y", "z");
        let enc = |e: &Event| {
            let mut v = Vec::new();
            e.encode(&mut v);
            v
        };
        assert_ne!(enc(&a), enc(&b));
        assert_ne!(enc(&a), enc(&c));
    }

    #[test]
    fn json_is_compact() {
        let e = Event::new(Source::Fs, "os.listdir", "t.py:3", "2:abcd");
        let j = serde_json::to_string(&e).unwrap();
        assert_eq!(j, r#"{"t":0,"s":"fs","o":"os.listdir","at":"t.py:3","v":"2:abcd"}"#);
        let back: Event = serde_json::from_str(&j).unwrap();
        assert_eq!(back, e);
    }
}
