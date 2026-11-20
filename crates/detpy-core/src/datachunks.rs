//! A test entry's data dependencies, stored as content-addressed chunks shared by every entry that has them
//! (py-cache item 4: on large projects the tests of a process carry the same long runs of inputs, and a store of
//! 532 MB loaded into each xdist worker reached 3 GB).
//!
//! [`Data`] is the ordered list of `(path key, dependency)` pairs an entry always had; it is cut into chunks at
//! content-defined boundaries (a boundary follows a pair whose key hashes to 0 mod [`AVG`], or after [`MAX`] pairs),
//! so two entries whose lists share a run share the chunks of that run. A chunk is addressed by the digest of its
//! pairs. In memory a chunk is one `Arc` per distinct content ([`Interner`]); in a store file each chunk is written
//! once (`Store::chunks`) and an entry lists the addresses of its chunks.
//!
//! The pairs, their order and their values are exactly those of the list the entry was recorded with: the checker
//! sees the same dependencies (iteration flattens the chunks in order).

use crate::fingerprint::digest_bytes;
use crate::proof::Str;
use serde::de::{self, Deserializer, SeqAccess, Visitor};
use serde::ser::{SerializeSeq, Serializer};
use serde::{Deserialize, Serialize};
use std::cell::Cell;
use std::collections::HashMap;
use std::fmt;
use std::sync::Arc;

pub type Chunk = Arc<[(Str, Str)]>;

/// Average chunk length (pairs); a power of two.
pub const AVG: u64 = 16;
/// Longest chunk (pairs).
pub const MAX: usize = 64;

thread_local! {
    /// While a store is written: entries serialize their chunk addresses (the store writes each chunk once).
    static BY_ADDRESS: Cell<bool> = const { Cell::new(false) };
    /// While a store is written: the address of each chunk already hashed, by the chunk's allocation (an entry's
    /// chunks are shared `Arc`s: esphome's store references 4.6 M chunks, 3,420 distinct; hashing every reference
    /// was most of the time a store took to load and save).
    static MEMO: std::cell::RefCell<HashMap<usize, String>> = std::cell::RefCell::new(HashMap::new());
    /// While a store is written: the groups of chunk addresses entries listed (group address -> chunk addresses),
    /// written once by the store's [`Groups`] field after its entries.
    static GROUPS: std::cell::RefCell<std::collections::BTreeMap<String, Vec<String>>> =
        std::cell::RefCell::new(std::collections::BTreeMap::new());
}

/// Average group length (chunk addresses) and longest group: an entry lists group addresses, each group once in
/// the store (py-cache: esphome's per-file store listed ~400 chunk addresses per entry, 120 MB of 220).
pub const GAVG: u64 = 16;
pub const GMAX: usize = 64;

/// The groups of chunk addresses a store holds (see [`GROUPS`]); serialized from the groups its entries wrote.
#[derive(Clone, Debug, Default)]
pub struct Groups(pub std::collections::BTreeMap<String, Vec<String>>);

impl Serialize for Groups {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        if BY_ADDRESS.with(|b| b.get()) {
            let g = GROUPS.with(|g| std::mem::take(&mut *g.borrow_mut()));
            g.serialize(s)
        } else {
            self.0.serialize(s)
        }
    }
}

impl<'de> Deserialize<'de> for Groups {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Groups, D::Error> {
        Ok(Groups(std::collections::BTreeMap::deserialize(d)?))
    }
}

impl Groups {
    pub fn is_empty(&self) -> bool {
        self.0.is_empty() && !BY_ADDRESS.with(|b| b.get())
    }
}

fn group_address(addrs: &[String]) -> String {
    let mut b = Vec::new();
    for a in addrs {
        b.extend_from_slice(a.as_bytes());
        b.push(0);
    }
    format!("g{}", digest_bytes(&b).short())
}

/// Run `f` with entries serializing their chunk addresses instead of their pairs.
pub fn by_address<T>(f: impl FnOnce() -> T) -> T {
    GROUPS.with(|g| g.borrow_mut().clear());
    BY_ADDRESS.with(|c| c.set(true));
    let r = f();
    BY_ADDRESS.with(|c| c.set(false));
    MEMO.with(|m| m.borrow_mut().clear());
    GROUPS.with(|g| g.borrow_mut().clear());
    r
}

/// [`address`] of a shared chunk, hashed once per allocation while a store is written ([`by_address`]); the
/// memo holds the chunk alive by its table, which outlives the write.
pub fn address_of(c: &Chunk) -> String {
    if !BY_ADDRESS.with(|b| b.get()) {
        return address(c);
    }
    let key = Arc::as_ptr(c) as *const (Str, Str) as usize;
    if let Some(a) = MEMO.with(|m| m.borrow().get(&key).cloned()) {
        return a;
    }
    let a = address(c);
    MEMO.with(|m| m.borrow_mut().insert(key, a.clone()));
    a
}

fn fnv(s: &str) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in s.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

/// The address of a chunk: digest of its pairs (length-prefixed).
pub fn address(pairs: &[(Str, Str)]) -> String {
    let mut b = Vec::new();
    for (k, v) in pairs {
        b.extend_from_slice(&(k.len() as u64).to_le_bytes());
        b.extend_from_slice(k.as_bytes());
        b.extend_from_slice(&(v.len() as u64).to_le_bytes());
        b.extend_from_slice(v.as_bytes());
    }
    digest_bytes(&b).short()
}

/// Cut `pairs` at content-defined boundaries.
pub fn cut(pairs: Vec<(Str, Str)>) -> Vec<Vec<(Str, Str)>> {
    let mut out = Vec::new();
    let mut cur = Vec::new();
    for p in pairs {
        let boundary = fnv(&p.0) % AVG == 0;
        cur.push(p);
        if boundary || cur.len() >= MAX {
            out.push(std::mem::take(&mut cur));
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

/// An entry's data dependencies (see the module documentation).
#[derive(Clone, Default)]
pub struct Data {
    chunks: Vec<Chunk>,
    /// Addresses read from a store file, resolved by [`Data::resolve`] (empty once resolved).
    pending: Vec<String>,
}

impl Data {
    pub fn new(pairs: Vec<(Str, Str)>) -> Data {
        Data { chunks: cut(pairs).into_iter().map(Chunk::from).collect(), pending: Vec::new() }
    }

    pub fn iter(&self) -> impl Iterator<Item = &(Str, Str)> + '_ {
        self.chunks.iter().flat_map(|c| c.iter())
    }

    pub fn len(&self) -> usize {
        self.chunks.iter().map(|c| c.len()).sum()
    }

    pub fn is_empty(&self) -> bool {
        self.chunks.iter().all(|c| c.is_empty()) && self.pending.is_empty()
    }

    pub fn to_vec(&self) -> Vec<(Str, Str)> {
        self.iter().cloned().collect()
    }

    pub fn chunks(&self) -> &[Chunk] {
        &self.chunks
    }

    /// Replace every chunk by the interner's copy of the same content (one allocation per distinct chunk).
    pub fn share(&mut self, i: &mut Interner) {
        for c in self.chunks.iter_mut() {
            *c = i.get(c);
        }
    }

    /// Resolve addresses read from a store file against its chunk table. False when one is missing (the entry is
    /// then unusable: the caller drops it).
    pub fn resolve(&mut self, table: &HashMap<String, Chunk>) -> bool {
        self.resolve_grouped(table, &std::collections::BTreeMap::new())
    }

    /// [`Data::resolve`] where an address may be a group's ("g...": the chunk addresses of `groups`).
    pub fn resolve_grouped(&mut self, table: &HashMap<String, Chunk>, groups: &std::collections::BTreeMap<String, Vec<String>>) -> bool {
        if self.pending.is_empty() {
            return true;
        }
        let mut out = Vec::with_capacity(self.pending.len());
        for a in &self.pending {
            if a.starts_with('g') {
                let Some(g) = groups.get(a) else { return false };
                for ca in g {
                    match table.get(ca) {
                        Some(c) => out.push(c.clone()),
                        None => return false,
                    }
                }
                continue;
            }
            match table.get(a) {
                Some(c) => out.push(c.clone()),
                None => return false,
            }
        }
        self.chunks = out;
        self.pending.clear();
        true
    }

    pub fn is_pending(&self) -> bool {
        !self.pending.is_empty()
    }
}

impl From<Vec<(Str, Str)>> for Data {
    fn from(v: Vec<(Str, Str)>) -> Data {
        Data::new(v)
    }
}

impl FromIterator<(Str, Str)> for Data {
    fn from_iter<I: IntoIterator<Item = (Str, Str)>>(it: I) -> Data {
        Data::new(it.into_iter().collect())
    }
}

impl<'a> IntoIterator for &'a Data {
    type Item = &'a (Str, Str);
    type IntoIter = std::iter::FlatMap<std::slice::Iter<'a, Chunk>, std::slice::Iter<'a, (Str, Str)>, fn(&'a Chunk) -> std::slice::Iter<'a, (Str, Str)>>;
    fn into_iter(self) -> Self::IntoIter {
        fn it(c: &Chunk) -> std::slice::Iter<'_, (Str, Str)> {
            c.iter()
        }
        self.chunks.iter().flat_map(it as fn(&'a Chunk) -> std::slice::Iter<'a, (Str, Str)>)
    }
}

impl PartialEq for Data {
    fn eq(&self, o: &Data) -> bool {
        self.len() == o.len() && self.iter().eq(o.iter())
    }
}

impl fmt::Debug for Data {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_list().entries(self.iter()).finish()
    }
}

impl Serialize for Data {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        if BY_ADDRESS.with(|c| c.get()) {
            // chunk addresses cut into groups at content-defined boundaries; the entry lists the groups
            let addrs: Vec<String> = self.chunks.iter().map(address_of).collect();
            let mut out: Vec<String> = Vec::new();
            let mut cur: Vec<String> = Vec::new();
            for a in addrs {
                let boundary = fnv(&a) % GAVG == 0;
                cur.push(a);
                if boundary || cur.len() >= GMAX {
                    let g = group_address(&cur);
                    GROUPS.with(|m| { m.borrow_mut().entry(g.clone()).or_insert_with(|| cur.clone()); });
                    out.push(g);
                    cur.clear();
                }
            }
            if !cur.is_empty() {
                let g = group_address(&cur);
                GROUPS.with(|m| { m.borrow_mut().entry(g.clone()).or_insert_with(|| cur.clone()); });
                out.push(g);
            }
            let mut seq = s.serialize_seq(Some(out.len()))?;
            for g in &out {
                seq.serialize_element(g)?;
            }
            seq.end()
        } else {
            let mut seq = s.serialize_seq(Some(self.len()))?;
            for p in self.iter() {
                seq.serialize_element(p)?;
            }
            seq.end()
        }
    }
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Item {
    Pair(Str, Str),
    Address(String),
}

impl<'de> Deserialize<'de> for Data {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Data, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Data;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a list of (key, dependency) pairs or of chunk addresses")
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Data, A::Error> {
                let mut pairs = Vec::new();
                let mut addrs = Vec::new();
                while let Some(x) = a.next_element::<Item>()? {
                    match x {
                        Item::Pair(k, v) => pairs.push((k, v)),
                        Item::Address(s) => addrs.push(s),
                    }
                }
                if !pairs.is_empty() && !addrs.is_empty() {
                    return Err(de::Error::custom("mixed pairs and chunk addresses"));
                }
                if addrs.is_empty() {
                    Ok(Data::new(pairs))
                } else {
                    Ok(Data { chunks: Vec::new(), pending: addrs })
                }
            }
        }
        d.deserialize_seq(V)
    }
}

/// One `Arc` per distinct chunk content (and the store file's chunk table).
#[derive(Clone, Debug, Default)]
pub struct Interner {
    by_address: HashMap<String, Chunk>,
}

impl Interner {
    pub fn get(&mut self, c: &Chunk) -> Chunk {
        let a = address(c);
        self.by_address.entry(a).or_insert_with(|| c.clone()).clone()
    }

    pub fn table(&self) -> &HashMap<String, Chunk> {
        &self.by_address
    }

    pub fn from_table(t: HashMap<String, Chunk>) -> Interner {
        Interner { by_address: t }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pairs(n: usize, tag: &str) -> Vec<(Str, Str)> {
        (0..n).map(|i| (format!("dir/file{i}.py").into(), format!("f:{tag}{i}").into())).collect()
    }

    #[test]
    fn same_pairs_in_the_same_order() {
        let v = pairs(1000, "a");
        let d = Data::new(v.clone());
        assert_eq!(d.to_vec(), v);
        assert_eq!(d.len(), 1000);
        assert!(d.chunks().len() > 10 && d.chunks().iter().all(|c| c.len() <= MAX));
    }

    #[test]
    fn a_shared_run_shares_chunks_and_round_trips_by_address() {
        let base = pairs(2000, "b");
        let mut a = base.clone();
        a.push(("own_a.txt".into(), "f:1".into()));
        let mut b = base.clone();
        b.insert(0, ("aaa_own_b.txt".into(), "f:2".into()));
        let (mut da, mut db) = (Data::new(a.clone()), Data::new(b.clone()));
        let mut i = Interner::default();
        da.share(&mut i);
        db.share(&mut i);
        let shared = da.chunks().iter().filter(|c| db.chunks().iter().any(|d| Arc::ptr_eq(c, d))).count();
        assert!(shared * 10 >= da.chunks().len() * 8, "{shared} of {}", da.chunks().len());
        // as a store writes it: the entry lists group addresses, the groups follow
        let (j, groups) = by_address(|| {
            let j = serde_json::to_string(&da).unwrap();
            (j, serde_json::to_string(&Groups::default()).unwrap())
        });
        let groups: Groups = serde_json::from_str(&groups).unwrap();
        let listed: Vec<String> = serde_json::from_str(&j).unwrap();
        assert!(listed.iter().all(|g| g.starts_with('g')) && listed.len() * 4 <= da.chunks().len(), "{}", listed.len());
        let mut back: Data = serde_json::from_str(&j).unwrap();
        assert!(back.is_pending());
        assert!(!back.clone().resolve(i.table()), "a group is not a chunk");
        assert!(back.resolve_grouped(i.table(), &groups.0));
        assert_eq!(back.to_vec(), a);
        // plain serialization is the pairs, as before
        let plain: Vec<(String, String)> = serde_json::from_str(&serde_json::to_string(&db).unwrap()).unwrap();
        assert_eq!(plain.len(), b.len());
        let mut missing: Data = serde_json::from_str(&j).unwrap();
        assert!(!missing.resolve(&HashMap::new()));
    }
}
