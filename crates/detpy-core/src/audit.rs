//! Cache audit: a seeded random share of the results that would be reused with
//! proof is run fresh instead, and the fresh result is compared with the cached
//! one. Shared by every shell (detpy, detjs) so that one seed chooses the same
//! tests and one comparison rule decides everywhere.
//!
//! * [`chosen`]: whether a test is audited. Depends only on the seed, the test
//!   id and the share (not on the order or the number of tests), so a run's
//!   audit is reproduced from the seed in its receipts. The rule, for other
//!   implementations: `h = SHA-256(part("fenvix-audit-1") || part(seed) ||
//!   part(test_id))` with `part(s) = len(s) as u64 little-endian || s` (UTF-8);
//!   `x = (first 8 bytes of h as u64 big-endian) >> 11`; audited iff
//!   `x < share * 2^53` (share clamped to [0, 1]).
//! * [`verdict`]: outcome and set of test ids compared; a mismatch is *wrong*
//!   whenever the second fresh run also differs from the cached result (both
//!   fresh runs contradict it, whether or not they agree with each other); it is
//!   *flaky with evidence* only when the second fresh run reproduces the cached
//!   result.
//! * [`upper_bound_95`]: one-sided 95% upper bound on the wrong-skip rate from
//!   `checked` audits with `wrong` wrong skips (rule of three when none).

use std::collections::BTreeSet;

const DOMAIN: &str = "fenvix-audit-1";

fn part(buf: &mut Vec<u8>, s: &str) {
    buf.extend_from_slice(&(s.len() as u64).to_le_bytes());
    buf.extend_from_slice(s.as_bytes());
}

/// The 53-bit draw of `test_id` under `seed`, in [0, 2^53).
pub fn draw(seed: &str, test_id: &str) -> u64 {
    let mut b = Vec::with_capacity(32 + seed.len() + test_id.len());
    part(&mut b, DOMAIN);
    part(&mut b, seed);
    part(&mut b, test_id);
    let h = sha256(&b);
    let mut x = [0u8; 8];
    x.copy_from_slice(&h[..8]);
    u64::from_be_bytes(x) >> 11
}

/// Whether `test_id` is audited in a run with `seed` at `share` (0..=1).
pub fn chosen(seed: &str, test_id: &str, share: f64) -> bool {
    if share.is_nan() || share <= 0.0 {
        return false;
    }
    if share >= 1.0 {
        return true;
    }
    (draw(seed, test_id) as f64) < share * (1u64 << 53) as f64
}

/// What one run of a test gave: its outcome and the test ids it produced (one
/// id for a pytest item; the tests of a file for a file-level result).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Observation {
    pub outcome: String,
    pub ids: BTreeSet<String>,
}

impl Observation {
    pub fn new(outcome: &str, ids: impl IntoIterator<Item = String>) -> Self {
        Observation { outcome: outcome.to_string(), ids: ids.into_iter().collect() }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verdict {
    /// The fresh run gave the cached result.
    Matched,
    /// The fresh run differs: run it once more, then call [`verdict`] again with the second run.
    NeedsSecondRun,
    /// Neither fresh run gives the cached result (they may or may not agree with each other): the skip was
    /// wrong. How the second run is made (same process, new process, alone) can change its result for
    /// order-dependent tests, so agreement between the two fresh runs is not required (review R-013, defect 5).
    Wrong,
    /// The second fresh run reproduced the cached result while the first did not: the test is flaky (with
    /// evidence), the skip is not shown wrong.
    FlakyEvidence,
}

impl Verdict {
    pub fn as_str(&self) -> &'static str {
        match self {
            Verdict::Matched => "matched",
            Verdict::NeedsSecondRun => "needs-second-run",
            Verdict::Wrong => "wrong",
            Verdict::FlakyEvidence => "flaky-evidence",
        }
    }
}

/// Compare a cached result with fresh runs: outcome and the set of test ids.
pub fn verdict(cached: &Observation, first: &Observation, second: Option<&Observation>) -> Verdict {
    if first == cached {
        return Verdict::Matched;
    }
    match second {
        None => Verdict::NeedsSecondRun,
        Some(s) if s == cached => Verdict::FlakyEvidence,
        Some(_) => Verdict::Wrong,
    }
}

/// One-sided 95% upper bound on the wrong-skip rate after `checked` audits found
/// `wrong` wrong skips: 3/n when none (rule of three), else the exact
/// Clopper-Pearson bound (the p at which P[X <= wrong] = 0.05). 1.0 when nothing
/// was checked.
pub fn upper_bound_95(checked: u64, wrong: u64) -> f64 {
    if checked == 0 {
        return 1.0;
    }
    let n = checked as f64;
    if wrong == 0 {
        return (3.0 / n).min(1.0);
    }
    if wrong >= checked {
        return 1.0;
    }
    // binomial CDF decreases in p: bisect for cdf(p) = alpha
    let (mut lo, mut hi) = (wrong as f64 / n, 1.0f64);
    for _ in 0..200 {
        let mid = 0.5 * (lo + hi);
        if binom_cdf(wrong, checked, mid) > 0.05 {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    hi
}

/// P[X <= k] for X ~ Binomial(n, p), summed in log space.
fn binom_cdf(k: u64, n: u64, p: f64) -> f64 {
    if p <= 0.0 {
        return 1.0;
    }
    if p >= 1.0 {
        return if k >= n { 1.0 } else { 0.0 };
    }
    let (lp, lq) = (p.ln(), (1.0 - p).ln());
    let mut log_c = 0.0f64; // ln C(n, 0)
    let mut terms = Vec::with_capacity(k as usize + 1);
    for i in 0..=k {
        if i > 0 {
            log_c += ((n - i + 1) as f64).ln() - (i as f64).ln();
        }
        terms.push(log_c + i as f64 * lp + (n - i) as f64 * lq);
    }
    let m = terms.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    (m + terms.iter().map(|t| (t - m).exp()).sum::<f64>().ln()).exp().min(1.0)
}

// -- SHA-256 (FIPS 180-4), so the draw is reproducible with any standard library (node:crypto, hashlib) ---------
const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
    0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
    0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2,
];

pub fn sha256(data: &[u8]) -> [u8; 32] {
    let mut h: [u32; 8] =
        [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    let mut msg = data.to_vec();
    let bits = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bits.to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([chunk[4 * i], chunk[4 * i + 1], chunk[4 * i + 2], chunk[4 * i + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7].wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v = [t1.wrapping_add(t2), v[0], v[1], v[2], v[3].wrapping_add(t1), v[4], v[5], v[6]];
        }
        for i in 0..8 {
            h[i] = h[i].wrapping_add(v[i]);
        }
    }
    let mut out = [0u8; 32];
    for i in 0..8 {
        out[4 * i..4 * i + 4].copy_from_slice(&h[i].to_be_bytes());
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{x:02x}")).collect()
    }

    #[test]
    fn sha256_known_answers() {
        assert_eq!(hex(&sha256(b"")), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
        assert_eq!(hex(&sha256(b"abc")), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        let long = vec![b'a'; 1000];
        assert_eq!(hex(&sha256(&long)), "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3");
    }

    #[test]
    fn selection_depends_on_seed_and_id_only_and_follows_the_share() {
        let ids: Vec<String> = (0..20_000).map(|i| format!("tests/test_m.py::test_{i}")).collect();
        let a: Vec<bool> = ids.iter().map(|t| chosen("seed-1", t, 0.05)).collect();
        let b: Vec<bool> = ids.iter().rev().map(|t| chosen("seed-1", t, 0.05)).collect::<Vec<_>>().into_iter().rev().collect();
        assert_eq!(a, b, "order does not matter");
        let n = a.iter().filter(|x| **x).count();
        assert!((800..1200).contains(&n), "about 5% of 20,000: {n}");
        let other: Vec<bool> = ids.iter().map(|t| chosen("seed-2", t, 0.05)).collect();
        assert_ne!(a, other, "another seed chooses other tests");
        assert!(ids.iter().all(|t| chosen("s", t, 1.0)) && !ids.iter().any(|t| chosen("s", t, 0.0)));
        // a larger share keeps every test a smaller share chose (draw below a higher threshold)
        assert!(ids.iter().filter(|t| chosen("seed-1", t, 0.05)).all(|t| chosen("seed-1", t, 0.2)));
    }

    #[test]
    fn verdicts() {
        let c = Observation::new("passed", ["t::a".to_string()]);
        let f = Observation::new("failed", ["t::a".to_string()]);
        assert_eq!(verdict(&c, &c, None), Verdict::Matched);
        assert_eq!(verdict(&c, &f, None), Verdict::NeedsSecondRun);
        assert_eq!(verdict(&c, &f, Some(&f)), Verdict::Wrong);
        assert_eq!(verdict(&c, &f, Some(&c)), Verdict::FlakyEvidence);
        let other = Observation::new("error", ["t::a".to_string()]);
        assert_eq!(verdict(&c, &f, Some(&other)), Verdict::Wrong, "both fresh runs contradict the cache: wrong");
        let more = Observation::new("passed", ["t::a".to_string(), "t::b".to_string()]);
        assert_eq!(verdict(&c, &more, Some(&more)), Verdict::Wrong, "another set of test ids is a mismatch");
    }

    #[test]
    fn bounds() {
        assert_eq!(upper_bound_95(0, 0), 1.0);
        assert!((upper_bound_95(300, 0) - 0.01).abs() < 1e-12);
        // exact one-sided Clopper-Pearson: n=100, k=1 -> 0.0466 (tables); n=1000, k=5 -> 0.0105
        assert!((upper_bound_95(100, 1) - 0.0466).abs() < 5e-4, "{}", upper_bound_95(100, 1));
        assert!((upper_bound_95(1000, 5) - 0.0105).abs() < 5e-4, "{}", upper_bound_95(1000, 5));
        assert_eq!(upper_bound_95(3, 3), 1.0);
    }
}
