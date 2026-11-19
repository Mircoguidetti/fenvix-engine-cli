//! Skip with proof for Go tests: the key, the decider and the cache (review
//! R-025 R1: this logic lives in the core; the Go shell only runs the binary
//! and hands over what it observed).
//!
//! A top-level test is reused (not run, its passing outcome reported) only
//! when everything its last passing run depended on is unchanged:
//!
//! * code and configuration (`static`): the test binary's content, Go version,
//!   GOOS/GOARCH, cgo, the overlay, the --det controls, the build flags, every
//!   test flag except the purely presentational ones (`-run`, `-skip`,
//!   `-timeout`, `-count` and `-shuffle` are keyed: R-025 F8), and the module
//!   root (two checkouts never share results: F9);
//! * files: content of files read, metadata (type, mode, size, mtime; a
//!   symlink's target) of paths stat'ed or probed, names and entry types of
//!   directories listed, anywhere on the machine except the run's own outputs
//!   and process-private or device paths (F2, F3). Values are taken *before
//!   the test binary starts* (F1); an input first seen in a run has no
//!   pre-run value and the test runs again next time;
//! * environment: variables read, plus those the runtime, libc and the
//!   dynamic loader read below the hooks (`LD_*`, `GLIBC_*`, `MALLOC_*`: F7);
//! * the wall clock: a comparison of the clock with a fixed time (a
//!   certificate's NotAfter...) is re-evaluated with the current clock; any
//!   other observation of the wall clock makes the test not reusable (F6);
//! * never reused: a failure or skip, a test that talked to an address
//!   outside the machine or to a local service the run did not start (F4, F5),
//!   started another program (its clock and entropy are invisible), or read a
//!   volatile machine file (`/proc/meminfo`...), and every test after it in the
//!   same process (prefix rule).

use crate::strace::{self, Addr, Deps, Parsed};
use detpy_core::fingerprint::digest_bytes;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::io::Write;
use std::net::IpAddr;
use std::path::Path;

/// Cache format version (entries of other versions are ignored).
pub const VERSION: u32 = 2;

/// Read below the hooks (Go runtime, libc, time zone, proxies, certificates).
pub const ALWAYS_ENV: &[&str] = &[
    "GODEBUG", "GOGC", "GOMAXPROCS", "GOMEMLIMIT", "GOTRACEBACK", "GORACE", "TZ", "ZONEINFO", "LANG", "LANGUAGE",
    "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LC_NUMERIC", "LC_TIME", "LC_COLLATE", "HTTP_PROXY", "HTTPS_PROXY",
    "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "GOCOVERDIR", "HOME", "TMPDIR", "PATH",
];

/// Variable families the dynamic loader and libc read (keyed as one value each).
pub const ALWAYS_ENV_PREFIXES: &[&str] = &["LD_", "GLIBC_", "MALLOC_"];

/// Test flags that change only how results are shown, never what a test does.
pub const PRESENTATION_FLAGS: &[&str] =
    &["test.v", "test.paniconexit0", "test.testlogfile", "test.outputdir", "test.gocoverdir", "test.fullpath"];

/// A comparison of the wall clock with a fixed time, re-evaluated at check.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct Cond {
    /// the fixed time (Unix ns)
    pub other: i64,
    /// the compared time minus the real clock when it was compared (ns)
    pub delta: i64,
    /// sign of (compared - other): -1, 0, 1
    pub sign: i8,
}

/// The record of one test's last run.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Entry {
    #[serde(rename = "static")]
    pub static_: String,
    pub outcome: String,
    pub elapsed: f64,
    /// "c:" content, "m:" metadata, "l:" metadata without following links,
    /// "d:" listing, "e:" environment variable -> value ("?" = no pre-run value)
    pub deps: BTreeMap<String, String>,
    #[serde(default)]
    pub net: Vec<String>,
    #[serde(default)]
    pub unkeyed: Vec<String>,
    #[serde(default)]
    pub conds: Vec<Cond>,
    pub capture: String,
    #[serde(default)]
    pub commit: String,
}

/// The cache file of one package.
#[derive(Debug, Default, Serialize, Deserialize)]
pub struct Package {
    pub version: u32,
    pub pkg: String,
    pub tests: BTreeMap<String, Entry>,
    /// Measurement only (never used to skip): entries without the prefix rule.
    #[serde(default)]
    pub own: BTreeMap<String, Entry>,
}

/// Short BLAKE3 digest of length-prefixed parts.
pub fn hash<S: AsRef<str>>(parts: &[S]) -> String {
    let mut buf = Vec::new();
    for p in parts {
        let p = p.as_ref();
        buf.extend_from_slice(format!("{}:", p.len()).as_bytes());
        buf.extend_from_slice(p.as_bytes());
        buf.push(0);
    }
    digest_bytes(&buf).short()
}

fn cache_file(dir: &str, pkg: &str) -> std::path::PathBuf {
    Path::new(dir).join(format!("{}.json", &hash(&[pkg])[..24]))
}

impl Package {
    pub fn load(dir: &str, pkg: &str) -> Package {
        let empty = || Package { version: VERSION, pkg: pkg.to_owned(), ..Default::default() };
        let Ok(b) = std::fs::read(cache_file(dir, pkg)) else { return empty() };
        match serde_json::from_slice::<Package>(&b) {
            Ok(p) if p.version == VERSION && p.pkg == pkg => p,
            _ => empty(),
        }
    }
    pub fn save(&self, dir: &str) -> std::io::Result<()> {
        std::fs::create_dir_all(dir)?;
        let f = cache_file(dir, &self.pkg);
        let tmp = f.with_extension("json.tmp");
        std::fs::write(&tmp, serde_json::to_vec(self)?)?;
        std::fs::rename(tmp, f)
    }
}

// ------------------------------------------------------------- the machine

fn mtime_ns(m: &std::fs::Metadata) -> i128 {
    use std::os::unix::fs::MetadataExt;
    m.mtime() as i128 * 1_000_000_000 + m.mtime_nsec() as i128
}

fn type_name(ft: std::fs::FileType) -> &'static str {
    use std::os::unix::fs::FileTypeExt;
    if ft.is_symlink() {
        "link"
    } else if ft.is_dir() {
        "dir"
    } else if ft.is_file() {
        "file"
    } else if ft.is_socket() {
        "sock"
    } else if ft.is_fifo() {
        "fifo"
    } else if ft.is_char_device() {
        "chr"
    } else {
        "blk"
    }
}

fn err_value(e: &std::io::Error) -> String {
    match e.raw_os_error() {
        Some(2) | Some(20) => "-".into(), // ENOENT, ENOTDIR
        Some(n) => format!("?errno:{n}"),
        None => format!("?err:{:?}", e.kind()),
    }
}

/// Metadata value of a path: type, permission bits, size and mtime for files;
/// type, mode and mtime for directories (mtime left out for world-writable
/// scratch directories such as /tmp, whose mtime any process moves);
/// "-" when missing.
pub fn meta_value(p: &str, follow: bool) -> String {
    use std::os::unix::fs::PermissionsExt;
    let m = if follow { std::fs::metadata(p) } else { std::fs::symlink_metadata(p) };
    let m = match m {
        Ok(m) => m,
        Err(e) => return err_value(&e),
    };
    let mode = m.permissions().mode() & 0o7777;
    let ft = m.file_type();
    match type_name(ft) {
        "link" => match std::fs::read_link(p) {
            Ok(t) => format!("link:{}", t.to_string_lossy()),
            Err(e) => err_value(&e),
        },
        "dir" if mode & 0o002 != 0 => format!("dir:{mode:o}"),
        "dir" => format!("dir:{mode:o}:{}", mtime_ns(&m)),
        "file" => format!("file:{mode:o}:{}:{}", m.len(), mtime_ns(&m)),
        t => format!("{t}:{mode:o}"),
    }
}

/// Content value of a file: BLAKE3 of its bytes, "dir", or "-" when missing.
pub fn content_value(p: &str) -> String {
    match std::fs::metadata(p) {
        Err(e) => err_value(&e),
        Ok(m) if m.is_dir() => "dir".into(),
        Ok(_) => match std::fs::read(p) {
            Ok(b) => digest_bytes(&b).to_hex()[..32].to_owned(),
            Err(e) => format!("?unreadable:{}", err_value(&e)),
        },
    }
}

/// Listing value of a directory: its sorted entry names with their types.
pub fn list_value(p: &str) -> String {
    match std::fs::read_dir(p) {
        Err(e) => err_value(&e),
        Ok(rd) => {
            let mut names: Vec<String> = rd
                .filter_map(|e| e.ok())
                .map(|e| {
                    let t = e.file_type().map(type_name).unwrap_or("?");
                    format!("{}\x1f{}", e.file_name().to_string_lossy(), t)
                })
                .collect();
            names.sort();
            hash(&names)
        }
    }
}

/// Value of a dependency key now.
pub fn dep_value(key: &str, env: &BTreeMap<String, String>) -> String {
    let (kind, rest) = key.split_at(2);
    match kind {
        "c:" => content_value(rest),
        "m:" => meta_value(rest, true),
        "l:" => meta_value(rest, false),
        "d:" => list_value(rest),
        "e:" => env_value(rest, env),
        _ => "?".into(),
    }
}

/// Value of an environment variable ("" when unset); "PREFIX*" names a family.
pub fn env_value(name: &str, env: &BTreeMap<String, String>) -> String {
    if let Some(prefix) = name.strip_suffix('*') {
        let parts: Vec<&str> =
            env.iter().filter(|(k, _)| k.starts_with(prefix)).flat_map(|(k, v)| [k.as_str(), v.as_str()]).collect();
        return hash(&parts);
    }
    match env.get(name) {
        Some(v) => hash(&[v]),
        None => String::new(),
    }
}

// ------------------------------------------------------------- path classes

/// What a path the run observed is for the key.
#[derive(Debug, PartialEq, Eq)]
pub enum Class {
    /// not an input (process-private, devices, the run's own scratch)
    Drop,
    /// an input, keyed by its value
    Key,
    /// an input that cannot be keyed: the test is not reusable
    Volatile,
}

/// Classify a path: everything is an input unless it is process-private
/// (`/proc/self`), a device, fenvix's or go's own working state, or under a
/// directory the configuration drops. Machine state that changes by itself
/// (`/proc/meminfo`, other processes) cannot be keyed.
pub fn classify(p: &str, drop: &[String], self_binary: &str) -> Class {
    if !p.starts_with('/') || p.starts_with("/__fenvix_marker__/") || p == self_binary {
        return Class::Drop;
    }
    let under = |d: &str| !d.is_empty() && (p == d || (p.starts_with(d) && p.as_bytes().get(d.len()) == Some(&b'/')));
    if drop.iter().any(|d| under(d)) {
        return Class::Drop;
    }
    if p == "/proc" || under("/proc/self") || under("/proc/thread-self") {
        return Class::Drop;
    }
    if under("/proc/sys") {
        return Class::Key;
    }
    if under("/proc") {
        return Class::Volatile;
    }
    if under("/dev") && !under("/dev/shm") {
        return Class::Drop;
    }
    Class::Key
}

// ------------------------------------------------------------- network

fn proxy_ports(env: &BTreeMap<String, String>) -> BTreeSet<u16> {
    let mut out = BTreeSet::new();
    for k in ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"] {
        let Some(v) = env.get(k).filter(|v| !v.is_empty()) else { continue };
        let (scheme, rest) = match v.split_once("://") {
            Some((s, r)) => (s, r),
            None => ("http", v.as_str()),
        };
        let rest = rest.rsplit_once('@').map(|x| x.1).unwrap_or(rest);
        let hostport = rest.split('/').next().unwrap_or("");
        let port = if let Some(stripped) = hostport.strip_prefix('[') {
            stripped.split_once("]:").and_then(|(_, p)| p.parse().ok())
        } else {
            hostport.rsplit_once(':').and_then(|(_, p)| p.parse().ok())
        };
        out.insert(port.unwrap_or(match scheme {
            "https" => 443,
            s if s.starts_with("socks") => 1080,
            _ => 80,
        }));
    }
    out
}

/// "" when the address stays inside the run (a loopback or own address on a
/// port the run itself bound, or a unix socket it bound), else its name.
fn outside(a: &Addr, parsed: Option<&Parsed>, own: &[IpAddr], proxies: &BTreeSet<u16>) -> Option<String> {
    match a {
        Addr::Inet(ip, port) => {
            let name = if ip.contains(':') { format!("[{ip}]:{port}") } else { format!("{ip}:{port}") };
            let Ok(addr) = ip.parse::<IpAddr>() else { return Some(name) };
            let machine = addr.is_loopback() || addr.is_unspecified() || own.contains(&addr);
            let ours = parsed.map(|p| p.bound_ports.contains(port)).unwrap_or(false);
            if machine && ours && *port != 53 && !proxies.contains(port) {
                None
            } else if machine && !ours {
                Some(format!("local-service:{name}"))
            } else {
                Some(name)
            }
        }
        Addr::Unix(p) => {
            if parsed.map(|x| x.bound_unix.contains(p)).unwrap_or(false) {
                None
            } else {
                Some(format!("unix:{p}"))
            }
        }
    }
}

// ------------------------------------------------------------- a session

/// Configuration of one package run (from the Go shell).
#[derive(Debug, Deserialize)]
pub struct Config {
    pub cache_dir: String,
    pub pkg: String,
    pub root: String,
    /// binary content id, Go version, GOOS, GOARCH, cgo, overlay digest,
    /// controls, seed, epoch, tick, GOMAXPROCS, build flags
    pub static_parts: Vec<String>,
    /// arguments passed to the test binary
    pub test_args: Vec<String>,
    /// environment of the test binary (fenvix's own variables excluded)
    pub env: Vec<String>,
    /// "strace" (complete) or "hooks" (os-level hooks only: never reuses)
    pub capture: String,
    pub self_binary: String,
    /// directories whose paths are never inputs (session, caches, go's work dir)
    pub drop: Vec<String>,
    pub own_addrs: Vec<String>,
    pub verify: bool,
    pub commit: String,
    pub decisions: String,
}

/// One test's result as the shell saw it.
#[derive(Debug, Deserialize)]
pub struct TestResult {
    pub name: String,
    pub outcome: String,
    pub elapsed: f64,
    /// position in the run (the strace markers)
    pub pos: i64,
    /// packed hook dependencies (0x1e between items, 0x1f after the kind)
    pub deps: String,
}

/// What the shell hands over after the binary exited.
#[derive(Debug, Deserialize)]
pub struct Run {
    /// test names as the binary listed them
    pub names: Vec<String>,
    /// tests in execution order (reused ones included)
    pub order: Vec<String>,
    pub results: Vec<TestResult>,
    /// packed hook dependencies of the package (init, TestMain)
    pub pkg_deps: String,
    /// strace log ("" with hooks capture)
    pub strace_log: String,
    pub cwd: String,
}

/// A decisions.jsonl line.
#[derive(Debug, Serialize)]
pub struct Decision {
    pub pkg: String,
    pub test: String,
    pub reuse: bool,
    pub reuse_own: bool,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub why_own: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub why: String,
    pub cached: String,
    pub cached_elapsed: f64,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub fresh: String,
    pub elapsed: f64,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub commit: String,
}

/// Observations of one segment, before values are attached.
#[derive(Clone, Debug, Default)]
pub struct Raw {
    pub keys: BTreeSet<String>,
    pub net: Vec<String>,
    pub unkeyed: BTreeSet<String>,
    pub conds: BTreeSet<Cond>,
}

impl Raw {
    pub fn merge(&mut self, o: &Raw) {
        self.keys.extend(o.keys.iter().cloned());
        self.net.extend(o.net.iter().cloned());
        self.unkeyed.extend(o.unkeyed.iter().cloned());
        self.conds.extend(o.conds.iter().cloned());
    }
}

pub struct Session {
    pub cfg: Config,
    pub cache: Package,
    pub static_: String,
    env: BTreeMap<String, String>,
    own: Vec<IpAddr>,
    /// pre-run values of every input any entry of the package recorded
    snapshot: HashMap<String, String>,
    /// real clock at open (ns)
    now: i64,
    why: HashMap<String, String>,
    why_own: HashMap<String, String>,
    reuse: BTreeSet<String>,
}

fn now_ns() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as i64).unwrap_or(0)
}

/// The test flags that are part of the key.
pub fn keyed_test_args(args: &[String]) -> Vec<String> {
    args.iter()
        .filter(|a| {
            let n = a.trim_start_matches('-');
            let name = n.split('=').next().unwrap_or("");
            !PRESENTATION_FLAGS.contains(&name)
        })
        .cloned()
        .collect()
}

impl Session {
    /// Load the package's cache and take the pre-run values of every input
    /// its entries recorded. Call before the test binary starts.
    pub fn open(cfg: Config) -> Session {
        let cache = Package::load(&cfg.cache_dir, &cfg.pkg);
        let env: BTreeMap<String, String> =
            cfg.env.iter().filter_map(|kv| kv.split_once('=')).map(|(k, v)| (k.to_owned(), v.to_owned())).collect();
        let mut parts: Vec<String> = vec![format!("v{VERSION}"), "root".into(), cfg.root.clone(), "static".into()];
        parts.extend(cfg.static_parts.iter().cloned());
        parts.push("testflags".into());
        parts.extend(keyed_test_args(&cfg.test_args));
        let static_ = hash(&parts);
        let own = cfg.own_addrs.iter().filter_map(|a| a.parse().ok()).collect();
        let mut snapshot = HashMap::new();
        for e in cache.tests.values().chain(cache.own.values()) {
            for k in e.deps.keys() {
                if !k.starts_with("e:") && !snapshot.contains_key(k) {
                    snapshot.insert(k.clone(), dep_value(k, &env));
                }
            }
        }
        Session {
            cfg,
            cache,
            static_,
            env,
            own,
            snapshot,
            now: now_ns(),
            why: HashMap::new(),
            why_own: HashMap::new(),
            reuse: BTreeSet::new(),
        }
    }

    fn value(&self, key: &str) -> String {
        if key.starts_with("e:") {
            return env_value(&key[2..], &self.env);
        }
        self.snapshot.get(key).cloned().unwrap_or_else(|| "?".into())
    }

    /// "" when the entry can be reused now, else the first reason not to.
    pub fn why(&self, e: Option<&Entry>) -> String {
        let Some(e) = e else { return "new".into() };
        if e.capture.is_empty() {
            return "no-capture".into();
        }
        if e.capture != "strace" {
            return format!("capture-{}", e.capture);
        }
        if e.outcome != "passed" {
            return format!("last-{}", e.outcome);
        }
        if e.static_ != self.static_ {
            return "code-or-config".into();
        }
        if !e.net.is_empty() {
            // "local-service": only services on this machine the run did not start
            return if e.net.iter().all(|n| n.starts_with("local-service:")) { "local-service" } else { "network" }.into();
        }
        if let Some(u) = e.unkeyed.first() {
            return u.clone();
        }
        for (k, v) in &e.deps {
            if v == "?" {
                return format!("unkeyed:{k}");
            }
            let now = self.value(k);
            if &now == v {
                continue;
            }
            let p = &k[2..];
            return match &k[..2] {
                "e:" => format!("env:{p}"),
                "c:" => format!("file:{p}"),
                "d:" => format!("listing:{p}"),
                _ if v == "-" => format!("appeared:{p}"),
                _ if now == "-" => format!("vanished:{p}"),
                _ => format!("meta:{p}"),
            };
        }
        for c in &e.conds {
            let cmp = (self.now + c.delta).cmp(&c.other) as i8;
            if cmp != c.sign {
                return format!("clock:{}", c.other);
            }
        }
        String::new()
    }

    /// Decide for the tests in execution order; returns the names to reuse.
    pub fn decide(&mut self, names: &[String]) -> Vec<String> {
        for n in names {
            let w = self.why(self.cache.tests.get(n));
            let wo = self.why(self.cache.own.get(n));
            if w.is_empty() {
                self.reuse.insert(n.clone());
            }
            self.why.insert(n.clone(), w);
            self.why_own.insert(n.clone(), wo);
        }
        self.reuse.iter().cloned().collect()
    }

    fn raw_from_hooks(&self, packed: &str, parsed: Option<&Parsed>) -> Raw {
        let mut raw = Raw::default();
        for item in packed.split('\x1e') {
            let b = item.as_bytes();
            if b.len() < 2 || b[1] != 0x1f {
                continue;
            }
            let kind = b[0];
            let name = &item[2..];
            match kind {
                b'E' => {
                    raw.keys.insert(format!("e:{name}"));
                }
                b'O' | b'S' | b'L' => {
                    let p = strace::clean(name);
                    if parsed.map(|x| x.is_output(&p)).unwrap_or(false) {
                        continue;
                    }
                    match classify(&p, &self.cfg.drop, &self.cfg.self_binary) {
                        Class::Drop => {}
                        Class::Volatile => {
                            raw.unkeyed.insert(format!("volatile:{p}"));
                        }
                        Class::Key => match kind {
                            b'O' => {
                                raw.keys.insert(format!("c:{p}"));
                            }
                            b'S' => {
                                raw.keys.insert(format!("m:{p}"));
                                raw.keys.insert(format!("l:{p}"));
                            }
                            _ => {
                                raw.keys.insert(format!("d:{p}"));
                                raw.keys.insert(format!("m:{p}"));
                            }
                        },
                    }
                }
                b'X' => {
                    if name != self.cfg.self_binary {
                        raw.unkeyed.insert(format!("exec:{name}"));
                    }
                }
                b'N' => raw.net.push(name.to_owned()),
                b'C' => {
                    raw.unkeyed.insert(format!("clock:{name}"));
                }
                b'K' => {
                    let f: Vec<&str> = name.split(',').collect();
                    let ok = (|| -> Option<Cond> {
                        Some(Cond { other: f.first()?.parse().ok()?, delta: f.get(1)?.parse().ok()?, sign: f.get(2)?.parse().ok()? })
                    })();
                    match ok {
                        Some(c) => {
                            raw.conds.insert(c);
                        }
                        None => {
                            raw.unkeyed.insert("clock:unparsed".into());
                        }
                    }
                }
                _ => {}
            }
        }
        raw
    }

    fn raw_from_strace(&self, d: &Deps, parsed: &Parsed, drop_first_exec: bool) -> Raw {
        let mut raw = Raw::default();
        let proxies = proxy_ports(&self.env);
        let add = |kind: &str, p: &str, raw: &mut Raw| match classify(p, &self.cfg.drop, &self.cfg.self_binary) {
            Class::Drop => {}
            Class::Volatile => {
                raw.unkeyed.insert(format!("volatile:{p}"));
            }
            Class::Key => {
                raw.keys.insert(format!("{kind}{p}"));
            }
        };
        for p in &d.content {
            add("c:", p, &mut raw);
        }
        for p in &d.meta {
            add("m:", p, &mut raw);
        }
        for p in &d.lmeta {
            add("l:", p, &mut raw);
        }
        for p in &d.lists {
            add("d:", p, &mut raw);
        }
        let execs = if drop_first_exec && !d.execs.is_empty() { &d.execs[1..] } else { &d.execs[..] };
        for x in execs {
            if x != &self.cfg.self_binary {
                raw.unkeyed.insert(format!("exec:{x}"));
            }
        }
        for a in &d.net {
            if let Some(o) = outside(a, Some(parsed), &self.own, &proxies) {
                raw.net.push(o);
            }
        }
        raw
    }

    /// Value of an input for a new entry: its pre-run value; else, when the
    /// run provably did not change it (strace saw no write to it, an ancestor
    /// or an entry in it), its value now; else "?" (the test runs again next
    /// time, which takes a pre-run value).
    fn entry_value(&self, key: &str, parsed: Option<&Parsed>) -> String {
        if key.starts_with("e:") {
            return env_value(&key[2..], &self.env);
        }
        if let Some(v) = self.snapshot.get(key) {
            return v.clone();
        }
        match parsed {
            Some(p) if !p.changed(&key[2..]) => dep_value(key, &self.env),
            _ => "?".into(),
        }
    }

    fn make_entry(&self, outcome: &str, elapsed: f64, raw: &Raw, parsed: Option<&Parsed>) -> Entry {
        let mut e = Entry {
            static_: self.static_.clone(),
            outcome: outcome.to_owned(),
            elapsed,
            capture: self.cfg.capture.clone(),
            commit: self.cfg.commit.clone(),
            ..Default::default()
        };
        for k in &raw.keys {
            e.deps.insert(k.clone(), self.entry_value(k, parsed));
        }
        for n in ALWAYS_ENV {
            e.deps.insert(format!("e:{n}"), env_value(n, &self.env));
        }
        for p in ALWAYS_ENV_PREFIXES {
            let n = format!("{p}*");
            e.deps.insert(format!("e:{n}"), env_value(&n, &self.env));
        }
        let mut net: Vec<String> = raw.net.clone();
        net.sort();
        net.dedup();
        e.net = net;
        e.unkeyed = raw.unkeyed.iter().cloned().collect();
        e.conds = raw.conds.iter().cloned().collect();
        e
    }

    /// Record the run: decisions, then new entries for the tests that ran.
    pub fn record(&mut self, run: Run) -> Result<serde_json::Value, String> {
        let mut parsed: Option<Parsed> = None;
        let mut capture_ok = self.cfg.capture == "strace";
        if self.cfg.capture == "strace" {
            match strace::parse(Path::new(&run.strace_log), &run.cwd) {
                Ok(p) => parsed = Some(p),
                Err(e) => {
                    capture_ok = false;
                    eprintln!("fenvix-go exec: strace: {e}");
                }
            }
        }
        let results: HashMap<&str, &TestResult> = run.results.iter().map(|r| (r.name.as_str(), r)).collect();
        let mut pkg_raw = self.raw_from_hooks(&run.pkg_deps, parsed.as_ref());
        if let Some(p) = &parsed {
            if let Some(seg) = p.segments.get(&-1) {
                pkg_raw.merge(&self.raw_from_strace(seg, p, true));
            }
        }
        // prefix closure: a test also depends on everything the tests before
        // it in the same process observed
        let mut closure: HashMap<String, Raw> = HashMap::new();
        let mut own_raw: HashMap<String, Raw> = HashMap::new();
        let mut before: HashMap<String, Vec<Entry>> = HashMap::new();
        let mut acc = pkg_raw.clone();
        let mut acc_entries: Vec<Entry> = Vec::new();
        for name in &run.order {
            let Some(res) = results.get(name.as_str()) else {
                if self.reuse.contains(name) {
                    if let Some(e) = self.cache.tests.get(name) {
                        acc_entries.push(e.clone());
                    }
                }
                continue;
            };
            let mut own = self.raw_from_hooks(&res.deps, parsed.as_ref());
            if let Some(p) = &parsed {
                if let Some(seg) = p.segments.get(&res.pos) {
                    own.merge(&self.raw_from_strace(seg, p, false));
                }
            }
            let mut o = pkg_raw.clone();
            o.merge(&own);
            own_raw.insert(name.clone(), o);
            acc.merge(&own);
            closure.insert(name.clone(), acc.clone());
            before.insert(name.clone(), acc_entries.clone());
        }
        let capture = if capture_ok { self.cfg.capture.clone() } else { String::new() };
        let mut out = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.cfg.decisions)
            .map_err(|e| format!("{}: {e}", self.cfg.decisions))?;
        let (mut n_run, mut n_reused) = (0, 0);
        for name in &run.names {
            let cached = self.cache.tests.get(name);
            let mut d = Decision {
                pkg: self.cfg.pkg.clone(),
                test: name.clone(),
                reuse: self.reuse.contains(name),
                reuse_own: self.why_own.get(name).map(|w| w.is_empty()).unwrap_or(false),
                why_own: self.why_own.get(name).cloned().unwrap_or_default(),
                why: self.why.get(name).cloned().unwrap_or_default(),
                cached: cached.map(|e| e.outcome.clone()).unwrap_or_default(),
                cached_elapsed: cached.map(|e| e.elapsed).unwrap_or(0.0),
                fresh: String::new(),
                elapsed: 0.0,
                commit: self.cfg.commit.clone(),
            };
            let Some(res) = results.get(name.as_str()) else {
                if d.reuse {
                    n_reused += 1;
                }
                writeln!(out, "{}", serde_json::to_string(&d).unwrap()).map_err(|e| e.to_string())?;
                continue;
            };
            n_run += 1;
            d.fresh = res.outcome.clone();
            d.elapsed = res.elapsed;
            writeln!(out, "{}", serde_json::to_string(&d).unwrap()).map_err(|e| e.to_string())?;
            let mut e = self.make_entry(&res.outcome, res.elapsed, &closure[name], parsed.as_ref());
            e.capture = capture.clone();
            for prev in &before[name] {
                absorb(&mut e, prev);
            }
            let mut o = self.make_entry(&res.outcome, res.elapsed, &own_raw[name], parsed.as_ref());
            o.capture = capture.clone();
            self.cache.tests.insert(name.clone(), e);
            self.cache.own.insert(name.clone(), o);
        }
        self.cache.version = VERSION;
        self.cache.save(&self.cfg.cache_dir).map_err(|e| format!("skip cache: {e}"))?;
        Ok(serde_json::json!({"ran": n_run, "reused": n_reused, "capture": capture,
            "strace_lines": parsed.as_ref().map(|p| p.lines).unwrap_or(0)}))
    }
}

/// Add the recorded inputs of a test that came before this one in the same
/// process and was reused (not run): this test may depend on state it left.
pub fn absorb(e: &mut Entry, prev: &Entry) {
    for (k, v) in &prev.deps {
        e.deps.entry(k.clone()).or_insert_with(|| v.clone());
    }
    e.net.extend(prev.net.iter().cloned());
    e.net.sort();
    e.net.dedup();
    for u in &prev.unkeyed {
        if !e.unkeyed.contains(u) {
            e.unkeyed.push(u.clone());
        }
    }
    for c in &prev.conds {
        if !e.conds.contains(c) {
            e.conds.push(c.clone());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg(dir: &str, env: Vec<String>) -> Config {
        Config {
            cache_dir: format!("{dir}/cache"),
            pkg: "example.com/p".into(),
            root: dir.into(),
            static_parts: vec!["bin".into(), "x".into()],
            test_args: vec!["-test.v=true".into(), "-test.timeout=10m0s".into()],
            env,
            capture: "strace".into(),
            self_binary: "/tmp/b/p.test".into(),
            drop: vec![],
            own_addrs: vec![],
            verify: true,
            commit: String::new(),
            decisions: format!("{dir}/decisions.jsonl"),
        }
    }

    fn entry_with(s: &Session, keys: &[&str]) -> Entry {
        let mut raw = Raw::default();
        for k in keys {
            raw.keys.insert((*k).into());
        }
        s.make_entry("passed", 0.1, &raw, None)
    }

    #[test]
    fn pre_run_values_and_new_inputs() {
        let d = tempfile::tempdir().unwrap();
        let dir = d.path().to_str().unwrap();
        let f = format!("{dir}/a.txt");
        std::fs::write(&f, "v1").unwrap();
        let s = Session::open(cfg(dir, vec![]));
        // an input first seen in this run has no pre-run value: rerun next time
        let e = entry_with(&s, &[&format!("c:{f}")]);
        assert_eq!(e.deps[&format!("c:{f}")], "?");
        let mut s = s;
        s.cache.tests.insert("T".into(), e);
        s.cache.save(&s.cfg.cache_dir).unwrap();
        let s2 = Session::open(cfg(dir, vec![]));
        assert!(s2.why(s2.cache.tests.get("T")).starts_with("unkeyed:c:"));
        // the next record takes the pre-run value, even if the run rewrites the file
        let e = entry_with(&s2, &[&format!("c:{f}")]);
        std::fs::write(&f, "v2").unwrap();
        let mut s2 = s2;
        s2.cache.tests.insert("T".into(), e);
        s2.cache.save(&s2.cfg.cache_dir).unwrap();
        let s3 = Session::open(cfg(dir, vec![]));
        assert_eq!(s3.why(s3.cache.tests.get("T")), format!("file:{f}"));
    }

    #[test]
    fn metadata_symlinks_and_listing_types() {
        let d = tempfile::tempdir().unwrap();
        let dir = d.path().to_str().unwrap();
        let f = format!("{dir}/run.sh");
        std::fs::write(&f, "x").unwrap();
        let m1 = meta_value(&f, true);
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&f, std::fs::Permissions::from_mode(0o755)).unwrap();
        assert_ne!(m1, meta_value(&f, true));
        std::os::unix::fs::symlink("run.sh", format!("{dir}/cur")).unwrap();
        assert_eq!(meta_value(&format!("{dir}/cur"), false), "link:run.sh");
        std::fs::create_dir(format!("{dir}/t")).unwrap();
        std::fs::write(format!("{dir}/t/b"), "").unwrap();
        let l1 = list_value(&format!("{dir}/t"));
        std::fs::remove_file(format!("{dir}/t/b")).unwrap();
        std::fs::create_dir(format!("{dir}/t/b")).unwrap();
        assert_ne!(l1, list_value(&format!("{dir}/t")));
        assert_eq!(meta_value(&format!("{dir}/none"), true), "-");
    }

    #[test]
    fn flags_root_and_loader_env_are_keyed() {
        let d = tempfile::tempdir().unwrap();
        let dir = d.path().to_str().unwrap();
        let a = Session::open(cfg(dir, vec![]));
        let mut c = cfg(dir, vec![]);
        c.test_args.push("-test.run=TestA/^ok$".into());
        assert_ne!(a.static_, Session::open(c).static_);
        let mut c = cfg(dir, vec![]);
        c.test_args = vec!["-test.v=test2json".into(), "-test.timeout=10m0s".into()];
        assert_eq!(a.static_, Session::open(c).static_);
        let mut c = cfg(dir, vec![]);
        c.root = "/elsewhere".into();
        assert_ne!(a.static_, Session::open(c).static_);
        let mut s = Session::open(cfg(dir, vec!["LD_LIBRARY_PATH=/a".into()]));
        let e = entry_with(&s, &[]);
        s.cache.tests.insert("T".into(), e);
        s.cache.save(&s.cfg.cache_dir).unwrap();
        let s2 = Session::open(cfg(dir, vec!["LD_LIBRARY_PATH=/b".into()]));
        assert_eq!(s2.why(s2.cache.tests.get("T")), "env:LD_*");
    }

    #[test]
    fn clock_conditions_are_reevaluated() {
        let d = tempfile::tempdir().unwrap();
        let dir = d.path().to_str().unwrap();
        let s = Session::open(cfg(dir, vec![]));
        let mut raw = Raw::default();
        raw.conds.insert(Cond { other: s.now + 3_600_000_000_000, delta: 0, sign: -1 });
        let e = s.make_entry("passed", 0.0, &raw, None);
        assert_eq!(s.why(Some(&e)), "");
        let mut raw = Raw::default();
        raw.conds.insert(Cond { other: s.now - 1, delta: 0, sign: -1 });
        let e = s.make_entry("passed", 0.0, &raw, None);
        assert!(s.why(Some(&e)).starts_with("clock:"));
    }

    #[test]
    fn classes_and_locality() {
        assert_eq!(classify("/proc/self/maps", &[], ""), Class::Drop);
        assert_eq!(classify("/proc/meminfo", &[], ""), Class::Volatile);
        assert_eq!(classify("/proc/sys/net/core/somaxconn", &[], ""), Class::Key);
        assert_eq!(classify("/var/lib/x", &[], ""), Class::Key);
        assert_eq!(classify("/dev/urandom", &[], ""), Class::Drop);
        assert_eq!(classify("/c/x", &["/c".into()], ""), Class::Drop);
        let mut p = Parsed::default();
        p.bound_ports.insert(4000);
        let own = vec![];
        let none = BTreeSet::new();
        assert_eq!(outside(&Addr::Inet("127.0.0.1".into(), 4000), Some(&p), &own, &none), None);
        assert!(outside(&Addr::Inet("127.0.0.1".into(), 5432), Some(&p), &own, &none).is_some());
        assert!(outside(&Addr::Inet("192.0.2.1".into(), 9), Some(&p), &own, &none).is_some());
        assert!(outside(&Addr::Unix("/var/run/docker.sock".into()), Some(&p), &own, &none).is_some());
    }
}
