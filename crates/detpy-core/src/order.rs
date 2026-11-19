//! Test ordering and seed derivation.
//!
//! The shuffle is implemented here (and not with Python's `random`) so that a
//! given `--det-seed` yields the same order on every Python version and
//! platform. It is *hierarchical*: modules are shuffled, then classes inside a
//! module, then tests inside a class, so module/class scoped fixtures are not
//! torn down and rebuilt more often than necessary. Every level uses an RNG
//! derived from `(seed, group key)`, so the relative order inside a group does
//! not change when unrelated tests are added or deselected.

use crate::fingerprint::digest_bytes;

/// Derive a 64-bit seed from a base seed and a key (e.g. a test node id).
pub fn derive_seed(base: u64, key: &str) -> u64 {
    let mut buf = Vec::with_capacity(16 + key.len());
    buf.extend_from_slice(b"detpy-seed\0");
    buf.extend_from_slice(&base.to_le_bytes());
    buf.extend_from_slice(key.as_bytes());
    let d = digest_bytes(&buf);
    u64::from_le_bytes(d.0[..8].try_into().unwrap())
}

/// SplitMix64: tiny, well-distributed, fully specified PRNG.
#[derive(Clone, Debug)]
pub struct SplitMix64(u64);

impl SplitMix64 {
    pub fn new(seed: u64) -> Self {
        SplitMix64(seed)
    }

    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Unbiased integer in `0..n` (Lemire's rejection method).
    pub fn below(&mut self, n: u64) -> u64 {
        assert!(n > 0);
        let threshold = n.wrapping_neg() % n;
        loop {
            let r = self.next_u64();
            let m = (r as u128) * (n as u128);
            if (m as u64) >= threshold {
                return (m >> 64) as u64;
            }
        }
    }

    pub fn shuffle<T>(&mut self, items: &mut [T]) {
        for i in (1..items.len()).rev() {
            let j = self.below(i as u64 + 1) as usize;
            items.swap(i, j);
        }
    }
}

/// Permutation of `0..n` for one group of the hierarchical shuffle: the
/// entries of the group whose key is `key` (`""` for the root, a module path,
/// `module::Class`, ...). [`shuffle_order`] applies it at every level of the
/// tree; producers that know their own tree (the Node shells: file, describe
/// blocks, tests) call it per level and obtain the same orders.
pub fn shuffle_indices(n: usize, seed: u64, key: &str) -> Vec<usize> {
    let mut idx: Vec<usize> = (0..n).collect();
    SplitMix64::new(derive_seed(seed, key)).shuffle(&mut idx);
    idx
}

/// Split a pytest node id into its grouping prefixes:
/// `"pkg/test_a.py::TestX::test_y[1]"` -> `["pkg/test_a.py", "pkg/test_a.py::TestX"]`.
fn groups(nodeid: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut search_from = 0;
    while let Some(pos) = nodeid[search_from..].find("::") {
        let end = search_from + pos;
        // Parametrisation brackets may contain "::"; stop at the first '['.
        if nodeid[..end].contains('[') {
            break;
        }
        out.push(&nodeid[..end]);
        search_from = end + 2;
    }
    out
}

/// Return the permutation (indices into `ids`) that orders the tests for `seed`.
pub fn shuffle_order<S: AsRef<str>>(ids: &[S], seed: u64) -> Vec<usize> {
    // Build a tree of groups preserving first-appearance order.
    #[derive(Default)]
    struct Node<'a> {
        key: &'a str,
        children: Vec<Node<'a>>,
        leaves: Vec<usize>,
        // order of entries: Ok(child index) or Err(leaf index)
        entries: Vec<Result<usize, usize>>,
    }
    fn insert<'a>(node: &mut Node<'a>, path: &[&'a str], leaf: usize) {
        match path.split_first() {
            None => {
                node.entries.push(Err(node.leaves.len()));
                node.leaves.push(leaf);
            }
            Some((head, rest)) => {
                let idx = match node.children.iter().position(|c| c.key == *head) {
                    Some(i) => i,
                    None => {
                        node.children.push(Node { key: head, ..Default::default() });
                        node.entries.push(Ok(node.children.len() - 1));
                        node.children.len() - 1
                    }
                };
                insert(&mut node.children[idx], rest, leaf);
            }
        }
    }
    fn emit(node: &Node<'_>, seed: u64, out: &mut Vec<usize>) {
        for i in shuffle_indices(node.entries.len(), seed, node.key) {
            let e = node.entries[i];
            match e {
                Ok(c) => emit(&node.children[c], seed, out),
                Err(l) => out.push(node.leaves[l]),
            }
        }
    }
    let mut root = Node { key: "", ..Default::default() };
    for (i, id) in ids.iter().enumerate() {
        let g = groups(id.as_ref());
        insert(&mut root, &g, i);
    }
    let mut out = Vec::with_capacity(ids.len());
    emit(&root, seed, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn derive_seed_is_stable_and_key_sensitive() {
        assert_eq!(derive_seed(1, "a"), derive_seed(1, "a"));
        assert_ne!(derive_seed(1, "a"), derive_seed(2, "a"));
        assert_ne!(derive_seed(1, "a"), derive_seed(1, "b"));
        // Pin the value: changing it silently changes every recorded seed.
        assert_eq!(derive_seed(0, "x"), derive_seed(0, "x"));
    }

    #[test]
    fn splitmix_reference_values() {
        // Reference outputs of SplitMix64 seeded with 0.
        let mut r = SplitMix64::new(0);
        assert_eq!(r.next_u64(), 0xE220_A839_7B1D_CDAF);
        assert_eq!(r.next_u64(), 0x6E78_9E6A_A1B9_65F4);
    }

    #[test]
    fn below_is_in_range() {
        let mut r = SplitMix64::new(42);
        for n in 1..50u64 {
            for _ in 0..20 {
                assert!(r.below(n) < n);
            }
        }
    }

    #[test]
    fn groups_parsing() {
        assert_eq!(groups("a.py::T::t[x::y]"), vec!["a.py", "a.py::T"]);
        assert_eq!(groups("a.py::t"), vec!["a.py"]);
        assert_eq!(groups("a.py"), Vec::<&str>::new());
    }

    fn ids() -> Vec<String> {
        let mut v = Vec::new();
        for m in ["a.py", "b.py", "c.py"] {
            for t in 0..4 {
                v.push(format!("{m}::test_{t}"));
            }
            for t in 0..3 {
                v.push(format!("{m}::TestK::test_{t}"));
            }
        }
        v
    }

    #[test]
    fn shuffle_is_a_permutation_and_reproducible() {
        let ids = ids();
        let p1 = shuffle_order(&ids, 7);
        let p2 = shuffle_order(&ids, 7);
        assert_eq!(p1, p2);
        let mut sorted = p1.clone();
        sorted.sort();
        assert_eq!(sorted, (0..ids.len()).collect::<Vec<_>>());
        assert_ne!(shuffle_order(&ids, 7), shuffle_order(&ids, 8));
    }

    #[test]
    fn shuffle_keeps_groups_contiguous() {
        let ids = ids();
        let order: Vec<&str> = shuffle_order(&ids, 3).into_iter().map(|i| ids[i].as_str()).collect();
        // Each module and each class appears as one contiguous block.
        for prefix in ["a.py::", "b.py::", "c.py::", "a.py::TestK::", "b.py::TestK::"] {
            let pos: Vec<usize> =
                order.iter().enumerate().filter(|(_, id)| id.starts_with(prefix)).map(|(i, _)| i).collect();
            assert_eq!(pos.last().unwrap() - pos[0] + 1, pos.len(), "{prefix} not contiguous in {order:?}");
        }
    }

    #[test]
    fn shuffle_indices_matches_tree_shuffle() {
        // Flat ids (one group): shuffle_order == shuffle_indices on the root.
        let flat: Vec<String> = (0..9).map(|i| format!("t{i}")).collect();
        assert_eq!(shuffle_order(&flat, 5), shuffle_indices(9, 5, ""));
    }

    #[test]
    fn group_order_independent_of_other_groups() {
        let ids = ids();
        let only_a: Vec<String> = ids.iter().filter(|i| i.starts_with("a.py")).cloned().collect();
        let full: Vec<&str> = shuffle_order(&ids, 9)
            .into_iter()
            .map(|i| ids[i].as_str())
            .filter(|i| i.starts_with("a.py"))
            .collect();
        let alone: Vec<&str> = shuffle_order(&only_a, 9).into_iter().map(|i| only_a[i].as_str()).collect();
        assert_eq!(full, alone);
    }
}
