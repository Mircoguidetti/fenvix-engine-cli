//! Network cassettes: recorded conversations used to replay network access.
//!
//! A cassette maps a test node id to the ordered list of outbound connections
//! the test opened. Each connection is a byte stream split into segments in
//! the order they happened (`send` = bytes written by the code under test,
//! `recv` = bytes the remote end returned). For TLS connections the segments
//! hold the *plaintext* above TLS (recorded at the `ssl` layer), because the
//! encrypted bytes cannot be replayed.

use base64::Engine as _;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::Path;

pub const CASSETTE_FORMAT: &str = "detpy-cassette";
pub const CASSETTE_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Send,
    Recv,
}

impl Direction {
    pub fn parse(s: &str) -> Option<Direction> {
        match s {
            "send" => Some(Direction::Send),
            "recv" => Some(Direction::Recv),
            _ => None,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Direction::Send => "send",
            Direction::Recv => "recv",
        }
    }
}

fn ser_b64<S: Serializer>(data: &[u8], s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&base64::engine::general_purpose::STANDARD.encode(data))
}

fn de_b64<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<u8>, D::Error> {
    let s = String::deserialize(d)?;
    base64::engine::general_purpose::STANDARD.decode(s.as_bytes()).map_err(serde::de::Error::custom)
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Segment {
    pub dir: Direction,
    #[serde(serialize_with = "ser_b64", deserialize_with = "de_b64")]
    pub data: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Connection {
    pub host: String,
    pub port: u16,
    #[serde(default)]
    pub tls: bool,
    pub segments: Vec<Segment>,
}

impl Connection {
    /// Append bytes, merging with the previous segment when the direction is
    /// the same (so replay does not depend on how the OS split the stream).
    pub fn append(&mut self, dir: Direction, data: &[u8]) {
        if data.is_empty() {
            return;
        }
        match self.segments.last_mut() {
            Some(last) if last.dir == dir => last.data.extend_from_slice(data),
            _ => self.segments.push(Segment { dir, data: data.to_vec() }),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Cassette {
    pub format: String,
    pub version: u32,
    pub tests: BTreeMap<String, Vec<Connection>>,
}

impl Default for Cassette {
    fn default() -> Self {
        Cassette { format: CASSETTE_FORMAT.into(), version: CASSETTE_VERSION, tests: BTreeMap::new() }
    }
}

impl Cassette {
    pub fn load(path: &Path) -> io::Result<Cassette> {
        let text = fs::read_to_string(path)?;
        let c: Cassette = serde_json::from_str(&text).map_err(io::Error::other)?;
        if c.format != CASSETTE_FORMAT || c.version > CASSETTE_VERSION {
            return Err(io::Error::other(format!("unsupported cassette {} v{}", c.format, c.version)));
        }
        Ok(c)
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent)?;
            }
        }
        let tmp = path.with_extension("tmp");
        fs::write(&tmp, serde_json::to_vec_pretty(self).map_err(io::Error::other)?)?;
        fs::rename(tmp, path)
    }

    /// Start recording a new connection for `nodeid`; returns its index.
    pub fn open(&mut self, nodeid: &str, host: &str, port: u16) -> usize {
        let conns = self.tests.entry(nodeid.to_string()).or_default();
        conns.push(Connection { host: host.to_string(), port, tls: false, segments: Vec::new() });
        conns.len() - 1
    }

    pub fn connection(&self, nodeid: &str, idx: usize) -> Option<&Connection> {
        self.tests.get(nodeid).and_then(|c| c.get(idx))
    }

    pub fn connection_mut(&mut self, nodeid: &str, idx: usize) -> Option<&mut Connection> {
        self.tests.get_mut(nodeid).and_then(|c| c.get_mut(idx))
    }

    /// Find the `nth` (0-based) recorded connection of `nodeid` to `host:port`.
    pub fn find(&self, nodeid: &str, host: &str, port: u16, nth: usize) -> Option<(usize, &Connection)> {
        self.tests
            .get(nodeid)?
            .iter()
            .enumerate()
            .filter(|(_, c)| c.host == host && c.port == port)
            .nth(nth)
    }

    /// Drop what was recorded for `nodeid` (re-recording a test replaces it).
    pub fn clear_test(&mut self, nodeid: &str) {
        self.tests.remove(nodeid);
    }

    /// Merge `other` into `self`, tests in `other` win.
    pub fn merge(&mut self, other: Cassette) {
        self.tests.extend(other.tests);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn append_merges_same_direction() {
        let mut c = Connection { host: "h".into(), port: 80, tls: false, segments: vec![] };
        c.append(Direction::Send, b"GET ");
        c.append(Direction::Send, b"/ HTTP/1.0\r\n\r\n");
        c.append(Direction::Recv, b"HTTP/1.0 200 OK\r\n");
        c.append(Direction::Recv, b"");
        c.append(Direction::Recv, b"\r\nbody");
        assert_eq!(c.segments.len(), 2);
        assert_eq!(c.segments[0].data, b"GET / HTTP/1.0\r\n\r\n");
        assert_eq!(c.segments[1].data, b"HTTP/1.0 200 OK\r\n\r\nbody");
    }

    #[test]
    fn save_load_roundtrip_and_find() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("c/cassette.json");
        let mut c = Cassette::default();
        let i = c.open("t::a", "example.com", 443);
        c.connection_mut("t::a", i).unwrap().tls = true;
        c.connection_mut("t::a", i).unwrap().append(Direction::Send, &[0, 1, 2, 255]);
        let j = c.open("t::a", "example.com", 443);
        c.connection_mut("t::a", j).unwrap().append(Direction::Recv, b"x");
        c.save(&path).unwrap();
        let back = Cassette::load(&path).unwrap();
        assert_eq!(back, c);
        assert_eq!(back.find("t::a", "example.com", 443, 1).unwrap().0, 1);
        assert!(back.find("t::a", "example.com", 80, 0).is_none());
        assert!(back.find("t::b", "example.com", 443, 0).is_none());
        let text = std::fs::read_to_string(&path).unwrap();
        assert!(text.contains("AAEC/w=="), "{text}");
    }

    #[test]
    fn clear_and_merge() {
        let mut a = Cassette::default();
        a.open("x", "h", 1);
        let mut b = Cassette::default();
        b.open("y", "h", 2);
        a.merge(b);
        assert_eq!(a.tests.len(), 2);
        a.clear_test("x");
        assert_eq!(a.tests.len(), 1);
    }
}
