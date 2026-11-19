//! detpy core: deterministic execution of Python tests (Level 0).
//!
//! * [`event`]: what is observed.
//! * [`fingerprint`]: hash chain over events, per test.
//! * [`recorder`]: per-test recording + streaming trace output.
//! * [`trace`]: on-disk trace format (JSONL).
//! * [`verify`]: cross-run comparison, divergence location and classification.
//! * [`order`]: reproducible hierarchical shuffle and seed derivation.
//! * [`cassette`]: recorded network conversations for record/replay.
//! * [`cache`]: result-cache vocabulary (key, policy, storage).
//! * [`proof`]: cache with proof: per-test recorded inputs, reuse check, receipt.
//! * [`backend`]: interception backends (Python hooks today, syscalls later).

pub mod backend;
pub mod cache;
pub mod cassette;
pub mod deps;
pub mod event;
pub mod fingerprint;
pub mod order;
pub mod proof;
pub mod recorder;
pub mod trace;
pub mod treehash;
pub mod verify;

pub use event::{Event, Source};
pub use fingerprint::{Fingerprinter, TestRecord};
pub use recorder::{Recorder, RecorderConfig};
