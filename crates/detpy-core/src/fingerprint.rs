//! Execution fingerprints.
//!
//! The fingerprint of a test is the head of a hash chain
//! `h_0 = H("detpy-fp-v1")`, `h_{i+1} = H(h_i || encode(e_i))` over every event
//! the test produced, terminated by an [`Source::Outcome`] event. Two runs of a
//! test with the same fingerprint observed exactly the same sequence of
//! non-deterministic interactions and ended with the same outcome.
//!
//! Storing every event is not always affordable (a test may read the clock a
//! million times), so the [`Fingerprinter`] keeps the first `max_events` events
//! verbatim and, for the whole sequence, a *checkpoint* (the chain head) every
//! `checkpoint_every` events. The verifier uses the stored events to point at
//! the exact diverging event and falls back to the checkpoints to bracket the
//! divergence inside a window when it happens past the stored prefix.

use crate::event::{Event, Source, ENCODING_VERSION};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub const DEFAULT_MAX_EVENTS: usize = 10_000;
pub const DEFAULT_CHECKPOINT_EVERY: u64 = 256;

/// A 32-byte BLAKE3 digest.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Digest(pub [u8; 32]);

impl Digest {
    pub fn to_hex(&self) -> String {
        hex(&self.0)
    }
    /// Short form used in fingerprints and checkpoints (128 bits).
    pub fn short(&self) -> String {
        hex(&self.0[..16])
    }
}

impl std::fmt::Debug for Digest {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Digest({})", self.short())
    }
}

pub fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 15) as usize] as char);
    }
    s
}

/// Hash arbitrary bytes (used to summarise large values such as directory
/// listings or network payloads before putting them in an event).
pub fn digest_bytes(data: &[u8]) -> Digest {
    Digest(*blake3::hash(data).as_bytes())
}

fn chain_seed() -> Digest {
    let mut h = blake3::Hasher::new();
    h.update(b"detpy-fp-v");
    h.update(&ENCODING_VERSION.to_le_bytes());
    Digest(*h.finalize().as_bytes())
}

/// Final, serialisable summary of one test execution.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TestRecord {
    pub nodeid: String,
    /// Position of the test in the executed order.
    pub index: u64,
    pub outcome: String,
    /// Head of the hash chain (including the outcome event), 32 hex chars.
    pub fingerprint: String,
    /// Number of events, outcome event included.
    pub n_events: u64,
    /// True when `events` holds only a prefix of the sequence.
    pub truncated: bool,
    /// Events per source.
    pub counts: BTreeMap<Source, u64>,
    /// `(n, chain head after n events)` every `checkpoint_every` events.
    pub checkpoints: Vec<(u64, String)>,
    pub events: Vec<Event>,
}

/// Incrementally fingerprints the event stream of one test.
#[derive(Clone, Debug)]
pub struct Fingerprinter {
    chain: Digest,
    count: u64,
    max_events: usize,
    checkpoint_every: u64,
    events: Vec<Event>,
    truncated: bool,
    checkpoints: Vec<(u64, String)>,
    counts: BTreeMap<Source, u64>,
    scratch: Vec<u8>,
}

impl Default for Fingerprinter {
    fn default() -> Self {
        Self::new(DEFAULT_MAX_EVENTS, DEFAULT_CHECKPOINT_EVERY)
    }
}

impl Fingerprinter {
    pub fn new(max_events: usize, checkpoint_every: u64) -> Self {
        Fingerprinter {
            chain: chain_seed(),
            count: 0,
            max_events,
            checkpoint_every: checkpoint_every.max(1),
            events: Vec::new(),
            truncated: false,
            checkpoints: Vec::new(),
            counts: BTreeMap::new(),
            scratch: Vec::with_capacity(256),
        }
    }

    pub fn len(&self) -> u64 {
        self.count
    }

    pub fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// Current chain head (fingerprint of the prefix seen so far).
    pub fn head(&self) -> Digest {
        self.chain
    }

    pub fn push(&mut self, event: Event) {
        self.scratch.clear();
        event.encode(&mut self.scratch);
        let mut h = blake3::Hasher::new();
        h.update(&self.chain.0);
        h.update(&self.scratch);
        self.chain = Digest(*h.finalize().as_bytes());
        self.count += 1;
        *self.counts.entry(event.source).or_insert(0) += 1;
        if self.count % self.checkpoint_every == 0 {
            self.checkpoints.push((self.count, self.chain.short()));
        }
        if self.events.len() < self.max_events {
            self.events.push(event);
        } else {
            self.truncated = true;
        }
    }

    /// Terminate the chain with the outcome event and produce the record.
    pub fn finish(mut self, nodeid: &str, index: u64, outcome: &str) -> TestRecord {
        self.push(Event::new(Source::Outcome, "outcome", "", outcome));
        TestRecord {
            nodeid: nodeid.to_string(),
            index,
            outcome: outcome.to_string(),
            fingerprint: self.chain.short(),
            n_events: self.count,
            truncated: self.truncated,
            counts: self.counts,
            checkpoints: self.checkpoints,
            events: self.events,
        }
    }
}

/// Recompute the fingerprint of a complete (non-truncated) event list.
/// Used by the verifier to validate traces and by tests.
pub fn fingerprint_of(events: &[Event]) -> String {
    let mut fp = Fingerprinter::new(0, u64::MAX);
    for e in events {
        fp.push(e.clone());
    }
    fp.head().short()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ev(op: &str, v: &str) -> Event {
        Event::new(Source::Time, op, "t.py:1", v)
    }

    #[test]
    fn same_events_same_fingerprint() {
        let mut a = Fingerprinter::default();
        let mut b = Fingerprinter::default();
        for i in 0..100 {
            a.push(ev("time.time", &i.to_string()));
            b.push(ev("time.time", &i.to_string()));
        }
        let ra = a.finish("t::x", 0, "passed");
        let rb = b.finish("t::x", 0, "passed");
        assert_eq!(ra.fingerprint, rb.fingerprint);
        assert_eq!(ra.n_events, 101);
        assert_eq!(ra.counts[&Source::Time], 100);
        assert_eq!(ra.counts[&Source::Outcome], 1);
    }

    #[test]
    fn order_value_and_outcome_matter() {
        let run = |vals: &[&str], outcome: &str| {
            let mut f = Fingerprinter::default();
            for v in vals {
                f.push(ev("time.time", v));
            }
            f.finish("t", 0, outcome).fingerprint
        };
        let base = run(&["1", "2"], "passed");
        assert_ne!(base, run(&["2", "1"], "passed"));
        assert_ne!(base, run(&["1", "3"], "passed"));
        assert_ne!(base, run(&["1", "2"], "failed"));
        assert_ne!(base, run(&["1"], "passed"));
    }

    #[test]
    fn empty_test_has_stable_fingerprint() {
        let a = Fingerprinter::default().finish("a", 0, "passed");
        let b = Fingerprinter::default().finish("b", 7, "passed");
        // The node id is *not* part of the chain: only behaviour is.
        assert_eq!(a.fingerprint, b.fingerprint);
        assert_eq!(a.n_events, 1);
    }

    #[test]
    fn truncation_and_checkpoints() {
        let mut f = Fingerprinter::new(10, 4);
        for i in 0..20 {
            f.push(ev("x", &i.to_string()));
        }
        let r = f.finish("t", 0, "passed");
        assert!(r.truncated);
        assert_eq!(r.events.len(), 10);
        assert_eq!(r.n_events, 21);
        let ns: Vec<u64> = r.checkpoints.iter().map(|c| c.0).collect();
        assert_eq!(ns, vec![4, 8, 12, 16, 20]);
    }

    #[test]
    fn fingerprint_of_matches_incremental() {
        let events: Vec<Event> = (0..5).map(|i| ev("x", &i.to_string())).collect();
        let mut f = Fingerprinter::default();
        for e in &events {
            f.push(e.clone());
        }
        assert_eq!(fingerprint_of(&events), f.head().short());
    }

    #[test]
    fn hex_encoding() {
        assert_eq!(hex(&[0, 15, 255]), "000fff");
        assert_eq!(digest_bytes(b"abc").to_hex().len(), 64);
    }
}
