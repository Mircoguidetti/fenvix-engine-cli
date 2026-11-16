//! Result cache (design hook, not yet wired into the plugin).
//!
//! Once a test is proven reproducible (same fingerprint across runs) its
//! outcome is a pure function of its inputs. A future version can then skip
//! re-executing it when none of its inputs changed. This module fixes the
//! vocabulary for that feature:
//!
//! * [`CacheKey`]: digest of everything that can influence the outcome and is
//!   *not* captured by Level 0 controls: node id, a digest of the code the test
//!   depends on (supplied by the producer: e.g. hashes of imported modules),
//!   and a digest of the environment (interpreter, dependency lock, seed).
//! * [`CachePolicy::admit`]: only stable tests that touched no uncontrolled
//!   source (live network, OS entropy, threads) are admitted.
//! * [`ResultCache`]: storage backend trait, with an in-memory and a JSON file
//!   implementation.

use crate::event::Source;
use crate::fingerprint::digest_bytes;
use crate::verify::{Status, TestVerdict};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct CacheKey(pub String);

impl CacheKey {
    pub fn compute(nodeid: &str, code_digest: &str, env_digest: &str) -> CacheKey {
        let mut buf = Vec::new();
        for part in [nodeid, code_digest, env_digest] {
            buf.extend_from_slice(&(part.len() as u64).to_le_bytes());
            buf.extend_from_slice(part.as_bytes());
        }
        CacheKey(digest_bytes(&buf).short())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CacheEntry {
    pub nodeid: String,
    pub outcome: String,
    pub fingerprint: String,
}

pub trait ResultCache {
    fn get(&self, key: &CacheKey) -> Option<CacheEntry>;
    fn put(&mut self, key: CacheKey, entry: CacheEntry) -> io::Result<()>;
}

#[derive(Default, Debug)]
pub struct MemoryCache {
    map: BTreeMap<CacheKey, CacheEntry>,
}

impl ResultCache for MemoryCache {
    fn get(&self, key: &CacheKey) -> Option<CacheEntry> {
        self.map.get(key).cloned()
    }
    fn put(&mut self, key: CacheKey, entry: CacheEntry) -> io::Result<()> {
        self.map.insert(key, entry);
        Ok(())
    }
}

/// One JSON file per entry under a directory (safe for concurrent writers).
pub struct JsonFileCache {
    dir: PathBuf,
}

impl JsonFileCache {
    pub fn new(dir: impl Into<PathBuf>) -> io::Result<Self> {
        let dir = dir.into();
        fs::create_dir_all(&dir)?;
        Ok(JsonFileCache { dir })
    }
    fn path(&self, key: &CacheKey) -> PathBuf {
        self.dir.join(format!("{}.json", key.0))
    }
}

impl ResultCache for JsonFileCache {
    fn get(&self, key: &CacheKey) -> Option<CacheEntry> {
        let text = fs::read_to_string(self.path(key)).ok()?;
        serde_json::from_str(&text).ok()
    }
    fn put(&mut self, key: CacheKey, entry: CacheEntry) -> io::Result<()> {
        let path = self.path(&key);
        let tmp = path.with_extension("tmp");
        fs::write(&tmp, serde_json::to_vec(&entry).map_err(io::Error::other)?)?;
        fs::rename(tmp, Path::new(&path))
    }
}

pub struct CachePolicy {
    /// Sources whose presence makes a test non-cacheable even if stable.
    pub forbidden: Vec<Source>,
    pub min_runs: usize,
}

impl Default for CachePolicy {
    fn default() -> Self {
        CachePolicy { forbidden: vec![Source::Net, Source::Entropy, Source::Syscall], min_runs: 2 }
    }
}

impl CachePolicy {
    /// `counts` are the per-source event counts of the test (from its record).
    pub fn admit(&self, verdict: &TestVerdict, counts: &BTreeMap<Source, u64>) -> bool {
        verdict.status == Status::Stable
            && verdict.fingerprints.len() >= self.min_runs
            && self.forbidden.iter().all(|s| counts.get(s).copied().unwrap_or(0) == 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn verdict(status: Status, runs: usize) -> TestVerdict {
        TestVerdict {
            nodeid: "t".into(),
            status,
            fingerprints: vec![Some("f".into()); runs],
            outcomes: vec![Some("passed".into()); runs],
            distinct_fingerprints: 1,
            outcome_stable: true,
            divergence: None,
        }
    }

    #[test]
    fn key_depends_on_all_parts() {
        let k = CacheKey::compute("a", "b", "c");
        assert_eq!(k, CacheKey::compute("a", "b", "c"));
        assert_ne!(k, CacheKey::compute("a", "b", "d"));
        assert_ne!(CacheKey::compute("ab", "", "c"), CacheKey::compute("a", "b", "c"));
    }

    #[test]
    fn caches_roundtrip() {
        let e = CacheEntry { nodeid: "t".into(), outcome: "passed".into(), fingerprint: "ff".into() };
        let k = CacheKey::compute("t", "", "");
        let mut m = MemoryCache::default();
        m.put(k.clone(), e.clone()).unwrap();
        assert_eq!(m.get(&k), Some(e.clone()));
        let dir = tempfile::tempdir().unwrap();
        let mut f = JsonFileCache::new(dir.path().join("cache")).unwrap();
        assert_eq!(f.get(&k), None);
        f.put(k.clone(), e.clone()).unwrap();
        assert_eq!(f.get(&k), Some(e));
    }

    #[test]
    fn policy() {
        let p = CachePolicy::default();
        let mut counts = BTreeMap::new();
        counts.insert(Source::Time, 3);
        assert!(p.admit(&verdict(Status::Stable, 2), &counts));
        assert!(!p.admit(&verdict(Status::Stable, 1), &counts));
        assert!(!p.admit(&verdict(Status::Diverged, 2), &counts));
        counts.insert(Source::Net, 1);
        assert!(!p.admit(&verdict(Status::Stable, 2), &counts));
    }
}
