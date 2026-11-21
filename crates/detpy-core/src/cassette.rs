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
    /// A UDP exchange: each segment is one datagram (audit G-1518).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub udp: bool,
    pub segments: Vec<Segment>,
    /// What TLS negotiated at record time (version, cipher, ALPN, peer certificate), returned by the replay stand-in
    /// (audit G-1522).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tls_info: Option<serde_json::Value>,
    /// A later test went on using this connection (a client that keeps connections alive): its exchanges are
    /// recorded under that test (`Cassette::continue_in`), and the replay keeps the connection open for them.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub continued: bool,
    /// The server had not closed the connection when the recording ended (no end of file read): the replay keeps
    /// it open for a next request, as the server did. False in cassettes written before this field: those replay
    /// as before (end of file after the last segment).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub kept_open: bool,
}

impl Connection {
    /// Whether the replay keeps the connection open after its last segment.
    pub fn keep(&self) -> bool {
        self.continued || self.kept_open
    }
}

impl Connection {
    /// One datagram: never merged with the previous segment.
    pub fn append_datagram(&mut self, dir: Direction, data: &[u8]) {
        self.segments.push(Segment { dir, data: data.to_vec() });
    }

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
    /// When each test's connections were recorded (UTC, RFC 3339; audit G-1519): replay can refuse recordings older
    /// than `--det-cassette-max-age`.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub recorded: BTreeMap<String, String>,
}

impl Default for Cassette {
    fn default() -> Self {
        Cassette {
            format: CASSETTE_FORMAT.into(),
            version: CASSETTE_VERSION,
            tests: BTreeMap::new(),
            recorded: BTreeMap::new(),
        }
    }
}

/// Header names whose values are secrets (case-insensitive): masked in sent bytes before a cassette is written, and
/// on both sides of the replay comparison (audit G-0167).
pub const SECRET_HEADERS: [&str; 12] = [
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
    "api-key",
    "apikey",
    "x-auth-token",
    "x-access-token",
    "x-amz-security-token",
    "x-goog-api-key",
    "x-csrf-token",
    "private-token",
];

/// The bytes with the values of secret HTTP headers replaced by `*` of the same length (the length is kept: replay
/// reads a request of the recorded size). Lines are `Name: value` terminated by CRLF or LF.
pub fn redact(data: &[u8]) -> Vec<u8> {
    let mut out = data.to_vec();
    let mut start = 0usize;
    while start < out.len() {
        let end = out[start..].iter().position(|&b| b == b'\n').map(|i| start + i).unwrap_or(out.len());
        let line = &out[start..end];
        if let Some(colon) = line.iter().position(|&b| b == b':') {
            let name = &line[..colon];
            if SECRET_HEADERS.iter().any(|h| name.eq_ignore_ascii_case(h.as_bytes())) {
                let mut v = start + colon + 1;
                while v < end && (out[v] == b' ' || out[v] == b'\t') {
                    v += 1;
                }
                let stop = if end > v && out[end - 1] == b'\r' { end - 1 } else { end };
                if !already_tagged(&out[v..stop]) {
                    for b in &mut out[v..stop] {
                        *b = b'*';
                    }
                }
            }
        }
        start = end + 1;
    }
    out
}

/// A value detjs has already masked (node/src/network.js `redact`): `<` 12 hex digits of its digest `>` then only
/// `*`. Kept as it is: replay compares the request masked the same way, and the digest tells two different
/// credentials of the same length apart (it is not the credential and does not reveal it).
fn already_tagged(v: &[u8]) -> bool {
    v.len() >= 14
        && v[0] == b'<'
        && v[13] == b'>'
        && v[1..13].iter().all(|b| b.is_ascii_hexdigit())
        && v[14..].iter().all(|&b| b == b'*')
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
        // secrets never reach the file (audit G-0167)
        let mut safe = self.clone();
        for conns in safe.tests.values_mut() {
            for c in conns {
                for seg in &mut c.segments {
                    if seg.dir == Direction::Send {
                        seg.data = redact(&seg.data);
                    }
                }
            }
        }
        fs::write(&tmp, serde_json::to_vec_pretty(&safe).map_err(io::Error::other)?)?;
        fs::rename(tmp, path)
    }

    /// Start recording a new connection for `nodeid`; returns its index.
    pub fn open(&mut self, nodeid: &str, host: &str, port: u16) -> usize {
        let conns = self.tests.entry(nodeid.to_string()).or_default();
        conns.push(Connection {
            host: host.to_string(),
            port,
            tls: false,
            udp: false,
            segments: Vec::new(),
            tls_info: None,
            continued: false,
            kept_open: true,
        });
        conns.len() - 1
    }

    pub fn open_udp(&mut self, nodeid: &str, host: &str, port: u16) -> usize {
        let conns = self.tests.entry(nodeid.to_string()).or_default();
        conns.push(Connection {
            host: host.to_string(),
            port,
            tls: false,
            udp: true,
            segments: Vec::new(),
            tls_info: None,
            continued: false,
            kept_open: false,
        });
        conns.len() - 1
    }

    /// The UDP exchange of `nodeid` with `host:port`, if recorded.
    pub fn find_udp(&self, nodeid: &str, host: &str, port: u16) -> Option<usize> {
        self.tests.get(nodeid)?.iter().position(|c| c.udp && c.host == host && c.port == port)
    }

    pub fn connection(&self, nodeid: &str, idx: usize) -> Option<&Connection> {
        self.tests.get(nodeid).and_then(|c| c.get(idx))
    }

    pub fn connection_mut(&mut self, nodeid: &str, idx: usize) -> Option<&mut Connection> {
        self.tests.get_mut(nodeid).and_then(|c| c.get_mut(idx))
    }

    /// `nodeid` goes on with connection `idx` of `from` (kept alive across tests): that one is marked continued, and
    /// a connection to the same host is opened for `nodeid` (with its TLS details); returns its index.
    pub fn continue_in(&mut self, from: &str, idx: usize, nodeid: &str) -> Option<usize> {
        let old = self.connection_mut(from, idx)?;
        old.continued = true;
        let next = Connection { segments: Vec::new(), continued: false, kept_open: true, ..old.clone() };
        let conns = self.tests.entry(nodeid.to_string()).or_default();
        conns.push(next);
        Some(conns.len() - 1)
    }

    /// Find the `nth` (0-based) recorded connection of `nodeid` to `host:port`.
    pub fn find(&self, nodeid: &str, host: &str, port: u16, nth: usize) -> Option<(usize, &Connection)> {
        self.tests
            .get(nodeid)?
            .iter()
            .enumerate()
            .filter(|(_, c)| !c.udp && c.host == host && c.port == port)
            .nth(nth)
    }

    /// Drop what was recorded for `nodeid` (re-recording a test replaces it).
    pub fn clear_test(&mut self, nodeid: &str) {
        self.tests.remove(nodeid);
    }

    /// Merge `other` into `self`, tests in `other` win.
    pub fn merge(&mut self, other: Cassette) {
        for k in other.tests.keys() {
            self.recorded.remove(k);
        }
        self.tests.extend(other.tests);
        self.recorded.extend(other.recorded);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redact_masks_secret_headers_keeping_the_length() {
        let req = b"GET /x HTTP/1.1\r\nHost: a\r\nAuthorization: Bearer SECRET\r\ncookie:  s=1; t=2\r\nX-Other: v\r\n\r\n";
        let r = redact(req);
        assert_eq!(r.len(), req.len());
        let t = String::from_utf8(r).unwrap();
        assert!(t.contains("Authorization: *************\r\n"), "{t}");
        assert!(t.contains("cookie:  ********\r\n"), "{t}");
        assert!(t.contains("X-Other: v\r\n") && !t.contains("SECRET"), "{t}");
        let dir = std::env::temp_dir().join(format!("detpy-cassette-redact-{}", std::process::id()));
        let mut c = Cassette::default();
        let i = c.open("t", "h", 80);
        c.connection_mut("t", i).unwrap().append(Direction::Send, req);
        c.save(&dir).unwrap();
        let text = fs::read_to_string(&dir).unwrap();
        let back = Cassette::load(&dir).unwrap();
        fs::remove_file(&dir).ok();
        assert!(!String::from_utf8(back.tests["t"][0].segments[0].data.clone()).unwrap().contains("SECRET"));
        assert!(!text.contains("U0VDUkVU"), "base64 of SECRET in the file");
    }

    #[test]
    fn redact_keeps_a_detjs_tag_and_masks_everything_else() {
        let tagged = b"GET /x HTTP/1.1\r\nauthorization: <196c70f93800>****\r\ncookie: <zz6c70f93800>****\r\n\r\n";
        let t = String::from_utf8(redact(tagged)).unwrap();
        assert!(t.contains("authorization: <196c70f93800>****\r\n"), "{t}");
        assert!(t.contains("cookie: ******************\r\n"), "not hex: masked {t}");
        assert_eq!(redact(&redact(tagged)), redact(tagged));
    }

    #[test]
    fn append_merges_same_direction() {
        let mut c = Connection { host: "h".into(), port: 80, tls: false, udp: false, segments: vec![], tls_info: None, continued: false, kept_open: false };
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
    fn a_connection_kept_alive_continues_in_the_next_test() {
        let mut c = Cassette::default();
        let i = c.open("t::a", "example.com", 443);
        c.connection_mut("t::a", i).unwrap().tls = true;
        let j = c.continue_in("t::a", i, "t::b").unwrap();
        assert!(c.connection("t::a", i).unwrap().continued);
        let k = c.connection("t::b", j).unwrap();
        assert!(k.tls && !k.continued && k.segments.is_empty() && k.host == "example.com" && k.port == 443);
        assert_eq!(c.find("t::b", "example.com", 443, 0).map(|(x, _)| x), Some(j));
        assert!(c.continue_in("t::none", 0, "t::b").is_none());
        let back: Cassette = serde_json::from_str(&serde_json::to_string(&c).unwrap()).unwrap();
        assert_eq!(back, c);
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
