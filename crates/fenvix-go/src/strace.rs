//! Dependency capture of a Go test binary run under `strace -f`.
//!
//! The fenvix testing hook marks the start and end of every top-level test
//! with `access("/__fenvix_marker__/B/<i>")` and `.../X/<i>`; syscalls outside
//! any test (package init, TestMain, between tests) belong to the package
//! (segment -1) and every test depends on them.
//!
//! What a segment depends on (review R-025 F1-F5):
//!
//! * `content`: a file whose content before the run was observable (opened
//!   read-only, or for writing without truncating or creating it);
//! * `meta`: a path stat'ed or probed with `stat`, `access`, `open`
//!   (following symlinks): its type, mode, size and mtime, or its absence;
//! * `lmeta`: the same without following symlinks (`lstat`, `readlink`,
//!   `unlink`...): a symlink's target is part of it;
//! * `lists`: a directory listed (`getdents64`): names and entry types;
//! * `execs`: programs started;
//! * `net`: every address the process tree connected or sent a datagram to
//!   (`connect`, `sendto`, `sendmsg`), inet or unix; locality is decided
//!   later against the listeners the run itself opened (`bind`,
//!   `getsockname`).
//!
//! A path whose first access in the run created or clobbered it (`O_TRUNC`,
//! `O_EXCL`, `creat`, `mkdir`, a rename or link target, a unix socket bound),
//! and every path under a directory the run created, is an output of the
//! run: later observations of it are not dependencies.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::io::{BufRead, BufReader};
use std::path::{Component, Path, PathBuf};

/// The `strace -e trace=` set.
pub const SYSCALLS: &str = "%file,getdents64,connect,bind,getsockname,sendto,sendmsg,sendmmsg,fchdir,fchmod,fchown,\
ftruncate,clone,clone3,fork,vfork";

/// The strace command prefix that writes its log to `log`.
pub fn args(log: &str) -> Vec<String> {
    [
        "strace",
        "-f",
        "-qq",
        "-y",
        "--seccomp-bpf",
        "-e",
        &format!("trace={SYSCALLS}"),
        "-e",
        "signal=none",
        "-s",
        "512",
        "-o",
        log,
        "--",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect()
}

/// An address the process tree talked to.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Addr {
    Inet(String, u16),
    Unix(String),
}

/// What one segment (a test, or the package) depended on.
#[derive(Clone, Debug, Default)]
pub struct Deps {
    pub content: BTreeSet<String>,
    pub meta: BTreeSet<String>,
    pub lmeta: BTreeSet<String>,
    pub lists: BTreeSet<String>,
    pub execs: Vec<String>,
    pub net: Vec<Addr>,
}

/// The parsed log.
#[derive(Debug, Default)]
pub struct Parsed {
    pub segments: BTreeMap<i64, Deps>,
    /// Paths whose first access created or clobbered them (outputs).
    pub outputs: BTreeSet<String>,
    /// Directories the run created: everything under them is an output.
    pub created_dirs: BTreeSet<String>,
    /// Ports of sockets the process tree bound or learned (its own listeners).
    pub bound_ports: BTreeSet<u16>,
    /// Unix socket paths the process tree bound.
    pub bound_unix: BTreeSet<String>,
    /// Paths the process tree changed in any way (content, metadata, entry).
    pub touched: BTreeSet<String>,
    pub lines: usize,
}

impl Parsed {
    /// Whether the value of an input at `p` after the run can differ from its
    /// value before the run: the run changed `p`, an ancestor of it, or an
    /// entry directly in it (a directory's listing and mtime).
    pub fn changed(&self, p: &str) -> bool {
        if self.touched.contains(p) {
            return true;
        }
        let prefix = if p == "/" { "/".to_owned() } else { format!("{p}/") };
        if let Some(t) = self.touched.range(prefix.clone()..).next() {
            if t.starts_with(&prefix) && !t[prefix.len()..].contains('/') {
                return true;
            }
            // a deeper entry: check the direct children range fully
            for t in self.touched.range(prefix.clone()..) {
                if !t.starts_with(&prefix) {
                    break;
                }
                if !t[prefix.len()..].contains('/') {
                    return true;
                }
            }
        }
        let mut cur = Path::new(p);
        while let Some(parent) = cur.parent() {
            if let Some(s) = parent.to_str() {
                if self.touched.contains(s) {
                    return true;
                }
            }
            cur = parent;
        }
        false
    }

    /// Whether `p` is an output of the run (or under a directory it created).
    pub fn is_output(&self, p: &str) -> bool {
        if self.outputs.contains(p) {
            return true;
        }
        let mut cur = Path::new(p);
        while let Some(parent) = cur.parent() {
            if let Some(s) = parent.to_str() {
                if self.created_dirs.contains(s) {
                    return true;
                }
            }
            cur = parent;
        }
        false
    }
}

/// Lexical clean of an absolute path (like Go's filepath.Clean).
pub fn clean(p: &str) -> String {
    let mut out: Vec<&str> = Vec::new();
    for c in Path::new(p).components() {
        match c {
            Component::RootDir | Component::Prefix(_) | Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            Component::Normal(s) => out.push(s.to_str().unwrap_or("")),
        }
    }
    let mut s = String::from("/");
    s.push_str(&out.join("/"));
    s
}

fn absify(cwd: &str, dirpart: &str, p: &str) -> String {
    if p.starts_with('/') {
        return clean(p);
    }
    let base = if dirpart.is_empty() { cwd } else { dirpart };
    clean(&PathBuf::from(base).join(p).to_string_lossy())
}

/// Decode a strace-quoted string body (`\n`, `\t`, `\\`, `\"`, `\xHH`, octal).
pub fn unescape(s: &str) -> String {
    if !s.contains('\\') {
        return s.to_owned();
    }
    let b = s.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] != b'\\' || i + 1 >= b.len() {
            out.push(b[i]);
            i += 1;
            continue;
        }
        let c = b[i + 1];
        match c {
            b'n' => {
                out.push(b'\n');
                i += 2;
            }
            b't' => {
                out.push(b'\t');
                i += 2;
            }
            b'r' => {
                out.push(b'\r');
                i += 2;
            }
            b'v' => {
                out.push(0x0b);
                i += 2;
            }
            b'f' => {
                out.push(0x0c);
                i += 2;
            }
            b'x' => {
                let h = if i + 4 <= b.len() {
                    std::str::from_utf8(&b[i + 2..i + 4]).ok().and_then(|h| u8::from_str_radix(h, 16).ok())
                } else {
                    None
                };
                match h {
                    Some(v) => {
                        out.push(v);
                        i += 4;
                    }
                    None => {
                        out.push(c);
                        i += 2;
                    }
                }
            }
            b'0'..=b'7' => {
                let mut j = i + 1;
                let mut v: u32 = 0;
                while j < b.len() && j < i + 4 && (b'0'..=b'7').contains(&b[j]) {
                    v = v * 8 + (b[j] - b'0') as u32;
                    j += 1;
                }
                out.push(v as u8);
                i = j;
            }
            _ => {
                out.push(c);
                i += 2;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// All quoted strings of `s` as (start of the opening quote, end after the
/// closing quote, decoded body).
fn quoted(s: &str) -> Vec<(usize, usize, String)> {
    let b = s.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'"' {
            let start = i;
            let mut j = i + 1;
            while j < b.len() && b[j] != b'"' {
                if b[j] == b'\\' {
                    j += 1;
                }
                j += 1;
            }
            if j >= b.len() {
                break;
            }
            out.push((start, j + 1, unescape(&s[start + 1..j])));
            i = j + 1;
        } else {
            i += 1;
        }
    }
    out
}

/// `AT_FDCWD</dir>` or `3</dir>` at the start of the arguments.
fn fd_path(args: &str) -> Option<String> {
    let rest = args.strip_prefix("AT_FDCWD").or_else(|| {
        let n = args.bytes().take_while(|c| c.is_ascii_digit()).count();
        if n > 0 {
            Some(&args[n..])
        } else {
            None
        }
    })?;
    let rest = rest.strip_prefix('<')?;
    let end = rest.find('>')?;
    Some(rest[..end].to_owned())
}

/// Text of `s` with quoted strings removed (so data cannot look like syntax).
fn unquoted(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut last = 0;
    for (a, b, _) in quoted(s) {
        out.push_str(&s[last..a]);
        out.push_str("\"\"");
        last = b;
    }
    out.push_str(&s[last..]);
    out
}

fn after<'a>(s: &'a str, key: &str) -> Option<&'a str> {
    s.find(key).map(|i| &s[i + key.len()..])
}

/// The socket address in a syscall's arguments.
fn sockaddr(args: &str) -> Option<Addr> {
    let plain = unquoted(args);
    if plain.contains("AF_UNIX") {
        // sun_path="..." or sun_path=@"..." (abstract)
        let i = args.find("sun_path=")?;
        let rest = &args[i + "sun_path=".len()..];
        let abstract_ = rest.starts_with('@');
        let q = quoted(rest);
        let (_, _, body) = q.first()?;
        return Some(Addr::Unix(if abstract_ { format!("@{body}") } else { body.clone() }));
    }
    let v6 = plain.contains("AF_INET6");
    if !v6 && !plain.contains("AF_INET") {
        return None;
    }
    let port_key = if v6 { "sin6_port=htons(" } else { "sin_port=htons(" };
    let port: u16 = after(&plain, port_key).and_then(|r| r.split(')').next()).and_then(|p| p.parse().ok())?;
    let ip = if v6 {
        let i = args.find("inet_pton(AF_INET6, ")?;
        quoted(&args[i..]).first().map(|q| q.2.clone())?
    } else {
        let i = args.find("inet_addr(")?;
        quoted(&args[i..]).first().map(|q| q.2.clone())?
    };
    Some(Addr::Inet(ip, port))
}

const MARKER: &str = "/__fenvix_marker__/";

#[derive(Clone, Copy, PartialEq, Eq)]
enum First {
    Observe,
    Output,
}

struct State {
    res: Parsed,
    cur: i64,
    first: HashMap<String, First>,
    missing_seen: BTreeSet<String>,
}

impl State {
    fn seg(&mut self) -> &mut Deps {
        self.res.segments.entry(self.cur).or_default()
    }
    fn observe(&mut self, p: &str) {
        self.first.entry(p.to_owned()).or_insert(First::Observe);
    }
    fn output(&mut self, p: &str) {
        if self.first.entry(p.to_owned()).or_insert(First::Output) == &First::Output {
            self.res.outputs.insert(p.to_owned());
        }
    }
}

/// Parse a strace log written with [`args`]; `cwd` is the test binary's
/// working directory.
pub fn parse(log: &Path, cwd: &str) -> std::io::Result<Parsed> {
    let f = std::fs::File::open(log)?;
    let mut st = State { res: Parsed::default(), cur: -1, first: HashMap::new(), missing_seen: BTreeSet::new() };
    st.res.segments.insert(-1, Deps::default());
    let mut cwds: HashMap<String, String> = HashMap::new();
    let mut pending: HashMap<String, String> = HashMap::new();
    let mut root_pid: Option<String> = None;
    for line in BufReader::new(f).lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue, // invalid UTF-8 line: skip (paths are lossily decoded elsewhere)
        };
        let Some(sp) = line.find(|c: char| c.is_whitespace()) else { continue };
        let pid = line[..sp].to_owned();
        if !pid.bytes().all(|c| c.is_ascii_digit()) {
            continue;
        }
        let mut rest = line[sp..].trim_start().to_owned();
        if root_pid.is_none() {
            root_pid = Some(pid.clone());
            cwds.insert(pid.clone(), cwd.to_owned());
        }
        if let Some(head) = rest.strip_suffix("<unfinished ...>") {
            pending.insert(pid, head.trim_end().to_owned());
            continue;
        }
        if rest.starts_with("<...") {
            let Some(head) = pending.remove(&pid) else { continue };
            rest = match rest.find("resumed>") {
                Some(k) => format!("{head}{}", &rest[k + "resumed>".len()..]),
                None => head,
            };
        }
        if rest.starts_with("+++") || rest.starts_with("---") {
            continue;
        }
        // name(args) = ret tail
        let Some(open) = rest.find('(') else { continue };
        let name = rest[..open].to_owned();
        if name.is_empty() || !name.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_') {
            continue;
        }
        let Some(eq) = rest.rfind(") = ") else { continue };
        if eq < open {
            continue;
        }
        let args = rest[open + 1..eq].to_owned();
        let after_eq = rest[eq + 4..].trim_start();
        let ret_end = after_eq.find(|c: char| c.is_whitespace() || c == '<').unwrap_or(after_eq.len());
        let ret = &after_eq[..ret_end];
        let tail = &after_eq[ret_end..];
        st.res.lines += 1;
        let ok = ret != "?" && !ret.starts_with('-');
        let pcwd = cwds.get(&pid).cloned().unwrap_or_else(|| cwd.to_owned());
        match name.as_str() {
            "clone" | "clone3" | "fork" | "vfork" => {
                if ok && ret != "0" && !cwds.contains_key(ret) {
                    cwds.insert(ret.to_owned(), pcwd);
                }
                continue;
            }
            "chdir" => {
                if let (true, Some(q)) = (ok, quoted(&args).first()) {
                    cwds.insert(pid.clone(), absify(&pcwd, "", &q.2));
                }
                continue;
            }
            "fchdir" => {
                if let (true, Some(p)) = (ok, fd_path(&args)) {
                    cwds.insert(pid.clone(), p);
                }
                continue;
            }
            "getdents64" => {
                if let (true, Some(p)) = (ok, fd_path(&args)) {
                    st.observe(&p);
                    st.seg().lists.insert(p);
                }
                continue;
            }
            "bind" => {
                match sockaddr(&args) {
                    Some(Addr::Inet(_, port)) if ok && port != 0 => {
                        st.res.bound_ports.insert(port);
                    }
                    Some(Addr::Unix(p)) if ok => {
                        let p = if p.starts_with('@') { p } else { absify(&pcwd, "", &p) };
                        if !p.starts_with('@') {
                            st.res.touched.insert(p.clone());
                            st.output(&p);
                        }
                        st.res.bound_unix.insert(p);
                    }
                    _ => {}
                }
                continue;
            }
            "getsockname" => {
                if let (true, Some(Addr::Inet(_, port))) = (ok, sockaddr(&args)) {
                    if port != 0 {
                        st.res.bound_ports.insert(port);
                    }
                }
                continue;
            }
            "connect" | "sendto" | "sendmsg" | "sendmmsg" => {
                match sockaddr(&args) {
                    Some(Addr::Unix(p)) => {
                        let p = if p.starts_with('@') { p } else { absify(&pcwd, "", &p) };
                        if !ok && (tail.contains("ENOENT") || tail.contains("ENOTDIR")) && !p.starts_with('@') {
                            // a probe of a socket path that is not there
                            st.observe(&p);
                            st.seg().meta.insert(p);
                        } else {
                            st.seg().net.push(Addr::Unix(p));
                        }
                    }
                    Some(a) => st.seg().net.push(a),
                    None => {}
                }
                continue;
            }
            _ => {}
        }
        if matches!(name.as_str(), "fchmod" | "fchown" | "ftruncate") {
            if let (true, Some(p)) = (ok, fd_path(&args)) {
                st.res.touched.insert(p);
            }
            continue;
        }
        if matches!(name.as_str(), "utimensat" | "futimesat") && ok {
            let q = quoted(&args);
            let fdp = fd_path(&args).unwrap_or_default();
            let p = match q.first() {
                Some((_, _, raw)) => absify(&pcwd, &fdp, raw),
                None => fdp,
            };
            if !p.is_empty() {
                st.res.touched.insert(p);
            }
            continue;
        }
        let dirpart = fd_path(&args).unwrap_or_default();
        let qs = quoted(&args);
        let Some((_, qend, raw)) = qs.first().cloned() else { continue };
        if let Some(m) = raw.strip_prefix(MARKER) {
            let mut it = m.split('/');
            if let (Some(k), Some(i)) = (it.next(), it.next()) {
                if let Ok(i) = i.parse::<i64>() {
                    st.cur = if k == "B" { i } else { -1 };
                }
            }
            continue;
        }
        let path = absify(&pcwd, &dirpart, &raw);
        let missing = !ok && (tail.contains("ENOENT") || tail.contains("ENOTDIR"));
        let flags = &args[qend..];
        match name.as_str() {
            "open" | "openat" | "openat2" | "creat" => {
                if !ok {
                    st.observe(&path);
                    st.seg().meta.insert(path.clone());
                    if missing {
                        st.missing_seen.insert(path);
                    }
                    continue;
                }
                let has = |f: &str| flags.split(|c: char| !(c.is_ascii_alphanumeric() || c == '_')).any(|w| w == f);
                let creat = name == "creat";
                let write = creat || has("O_WRONLY") || has("O_RDWR") || has("O_CREAT") || has("O_TRUNC") || has("O_APPEND");
                if has("O_DIRECTORY") && !write {
                    st.observe(&path);
                    st.seg().meta.insert(path);
                    continue;
                }
                if write {
                    st.res.touched.insert(path.clone());
                    let clobber = creat
                        || has("O_TRUNC")
                        || (has("O_CREAT") && has("O_EXCL"))
                        || (has("O_CREAT") && st.missing_seen.contains(&path));
                    if clobber {
                        st.output(&path);
                        continue;
                    }
                }
                // read-only, or a write that keeps the old content: an input
                st.observe(&path);
                st.seg().content.insert(path);
            }
            "stat" | "stat64" | "access" | "faccessat" | "faccessat2" | "lstat" | "lstat64" | "newfstatat"
            | "fstatat64" | "statx" | "readlink" | "readlinkat" => {
                if path.is_empty() || raw.is_empty() {
                    continue; // AT_EMPTY_PATH: a stat of an open file
                }
                let nofollow = matches!(name.as_str(), "lstat" | "lstat64" | "readlink" | "readlinkat")
                    || unquoted(&args).contains("AT_SYMLINK_NOFOLLOW");
                st.observe(&path);
                if nofollow {
                    st.seg().lmeta.insert(path.clone());
                } else {
                    st.seg().meta.insert(path.clone());
                }
                if missing {
                    st.missing_seen.insert(path);
                }
            }
            "execve" | "execveat" => {
                if ok {
                    st.observe(&path);
                    st.seg().execs.push(path);
                } else {
                    st.observe(&path);
                    st.seg().meta.insert(path);
                }
            }
            "mkdir" | "mkdirat" => {
                if ok {
                    st.res.touched.insert(path.clone());
                    st.output(&path);
                    st.res.created_dirs.insert(path);
                } else {
                    // EEXIST (MkdirAll) or a missing parent: the state was observed
                    st.observe(&path);
                    st.seg().meta.insert(path.clone());
                    if missing {
                        st.missing_seen.insert(path);
                    }
                }
            }
            "unlink" | "unlinkat" | "rmdir" | "truncate" | "rename" | "renameat" | "renameat2" | "symlink"
            | "symlinkat" | "link" | "linkat" | "mknod" | "mknodat" => {
                // the source's prior existence is observed, then it is the run's
                let src_is_new_name = matches!(name.as_str(), "symlink" | "symlinkat");
                if !src_is_new_name {
                    if !st.first.contains_key(&path) && !st.res.is_output(&path) {
                        st.seg().lmeta.insert(path.clone());
                    }
                    if ok {
                        st.res.touched.insert(path.clone());
                        st.output(&path);
                        if name == "rmdir" {
                            st.res.created_dirs.insert(path.clone());
                        }
                    } else {
                        st.observe(&path);
                    }
                }
                if ok && qs.len() > 1 && !matches!(name.as_str(), "unlink" | "unlinkat" | "rmdir" | "truncate") {
                    // the new name (rename/link/symlink target): an output, and so
                    // is everything under it when it is a directory
                    let (_, _, last) = qs.last().cloned().unwrap();
                    let tdir = {
                        // renameat/linkat: second dirfd precedes the target
                        let between = &args[qs[0].1..qs[qs.len() - 1].0];
                        let b = between.trim_start_matches([',', ' ']);
                        fd_path(b).unwrap_or_default()
                    };
                    let target = absify(&pcwd, &tdir, &last);
                    st.res.touched.insert(target.clone());
                    st.output(&target);
                    st.res.created_dirs.insert(target);
                }
                if src_is_new_name && ok {
                    let (_, _, last) = qs.last().cloned().unwrap();
                    let target = absify(&pcwd, "", &last);
                    st.res.touched.insert(target.clone());
                    st.output(&target);
                }
            }
            "chmod" | "fchmodat" | "fchmodat2" | "chown" | "lchown" | "fchownat" | "setxattr" | "lsetxattr"
            | "removexattr" | "lremovexattr" => {
                if ok {
                    st.res.touched.insert(path);
                }
            }
            _ => {}
        }
    }
    // later observations of outputs are not dependencies
    let res = &mut st.res;
    let outputs = std::mem::take(&mut res.outputs);
    let created = std::mem::take(&mut res.created_dirs);
    let probe = Parsed { outputs, created_dirs: created, ..Default::default() };
    for d in res.segments.values_mut() {
        d.content.retain(|p| keep_obs(&probe, &st.first, p));
        d.meta.retain(|p| keep_obs(&probe, &st.first, p));
        d.lmeta.retain(|p| keep_obs(&probe, &st.first, p));
        d.lists.retain(|p| keep_obs(&probe, &st.first, p));
    }
    res.outputs = probe.outputs;
    res.created_dirs = probe.created_dirs;
    // truncating or creating a path touches it too (already inserted above)
    Ok(st.res)
}

fn under_created(p: &Parsed, path: &str) -> bool {
    let mut cur = Path::new(path);
    while let Some(parent) = cur.parent() {
        if let Some(s) = parent.to_str() {
            if p.created_dirs.contains(s) {
                return true;
            }
        }
        cur = parent;
    }
    false
}

/// An observation is a dependency unless the path's first access made it an
/// output, or it lies under a directory the run created.
fn keep_obs(p: &Parsed, first: &HashMap<String, First>, path: &str) -> bool {
    if under_created(p, path) {
        return false;
    }
    first.get(path) != Some(&First::Output)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn log(lines: &str) -> Parsed {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("log");
        std::fs::write(&p, lines).unwrap();
        parse(&p, "/repo/pkg").unwrap()
    }

    #[test]
    fn segments_kinds_and_outputs() {
        let p = log(concat!(
            "10 openat(AT_FDCWD</repo/pkg>, \"/etc/hosts\", O_RDONLY|O_CLOEXEC) = 3</etc/hosts>\n",
            "10 access(\"/__fenvix_marker__/B/0\", F_OK) = -1 ENOENT (No such file or directory)\n",
            "10 openat(AT_FDCWD</repo/pkg>, \"testdata/a.txt\", O_RDONLY|O_CLOEXEC) = 3</repo/pkg/testdata/a.txt>\n",
            "10 newfstatat(AT_FDCWD</repo/pkg>, \"testdata/run.sh\", {st_mode=S_IFREG|0755, st_size=2, ...}, 0) = 0\n",
            "10 readlinkat(AT_FDCWD</repo/pkg>, \"testdata/current\", \"v1.txt\", 128) = 6\n",
            "10 newfstatat(AT_FDCWD</repo/pkg>, \"testdata/opt\", 0xc0, 0) = -1 ENOENT (No such file or directory)\n",
            "10 mkdirat(AT_FDCWD</repo/pkg>, \"/tmp/T1/001\", 0777) = 0\n",
            "10 openat(AT_FDCWD</repo/pkg>, \"/tmp/T1/001/x\", O_RDWR|O_CREAT|O_TRUNC|O_CLOEXEC, 0666) = 3</tmp/T1/001/x>\n",
            "10 openat(AT_FDCWD</repo/pkg>, \"/tmp/T1/001/x\", O_RDONLY|O_CLOEXEC) = 3</tmp/T1/001/x>\n",
            "10 openat(AT_FDCWD</repo/pkg>, \"out.txt\", O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0666) = 3</repo/pkg/out.txt>\n",
            "10 openat(AT_FDCWD</repo/pkg>, \"out.txt\", O_RDONLY|O_CLOEXEC) = 3</repo/pkg/out.txt>\n",
            "10 openat(AT_FDCWD</repo/pkg>, \"testdata\", O_RDONLY|O_CLOEXEC|O_DIRECTORY) = 3</repo/pkg/testdata>\n",
            "10 getdents64(3</repo/pkg/testdata>, 0xc0 /* 4 entries */, 8192) = 112\n",
            "10 access(\"/__fenvix_marker__/X/0\", F_OK) = -1 ENOENT (No such file or directory)\n",
        ));
        let pkg = &p.segments[&-1];
        assert!(pkg.content.contains("/etc/hosts"));
        let t = &p.segments[&0];
        assert!(t.content.contains("/repo/pkg/testdata/a.txt"));
        assert!(t.meta.contains("/repo/pkg/testdata/run.sh"));
        assert!(t.lmeta.contains("/repo/pkg/testdata/current"));
        assert!(t.meta.contains("/repo/pkg/testdata/opt"));
        assert!(t.lists.contains("/repo/pkg/testdata"));
        assert!(!t.content.contains("/tmp/T1/001/x"), "under a created dir");
        assert!(!t.content.contains("/repo/pkg/out.txt"), "truncated first: output");
        assert!(p.changed("/repo/pkg/out.txt") && p.changed("/repo/pkg") && !p.changed("/repo/pkg/testdata/a.txt"));
        assert!(!p.changed("/repo"), "a grandchild changed: the listing of /repo did not");
    }

    #[test]
    fn read_then_rewritten_stays_an_input() {
        let p = log(concat!(
            "10 access(\"/__fenvix_marker__/B/0\", F_OK) = -1 ENOENT (No such file or directory)\n",
            "10 openat(AT_FDCWD</r>, \"state.txt\", O_RDONLY|O_CLOEXEC) = 3</r/state.txt>\n",
            "10 access(\"/__fenvix_marker__/X/0\", F_OK) = -1 ENOENT (No such file or directory)\n",
            "10 access(\"/__fenvix_marker__/B/1\", F_OK) = -1 ENOENT (No such file or directory)\n",
            "10 openat(AT_FDCWD</r>, \"state.txt\", O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0666) = 3</r/state.txt>\n",
        ));
        assert!(p.segments[&0].content.contains("/r/state.txt"));
    }

    #[test]
    fn network_and_listeners() {
        let p = log(concat!(
            "10 bind(3<socket:[1]>, {sa_family=AF_INET, sin_port=htons(0), sin_addr=inet_addr(\"127.0.0.1\")}, 16) = 0\n",
            "10 getsockname(3<socket:[1]>, {sa_family=AF_INET, sin_port=htons(39187), sin_addr=inet_addr(\"127.0.0.1\")}, [112 => 16]) = 0\n",
            "10 connect(4<socket:[2]>, {sa_family=AF_INET, sin_port=htons(39187), sin_addr=inet_addr(\"127.0.0.1\")}, 16) = -1 EINPROGRESS (Operation now in progress)\n",
            "10 sendto(4<socket:[3]>, \"x\", 1, 0, {sa_family=AF_INET, sin_port=htons(9), sin_addr=inet_addr(\"192.0.2.1\")}, 16 <unfinished ...>\n",
            "10 <... sendto resumed>) = 1\n",
            "10 connect(7<socket:[4]>, {sa_family=AF_INET6, sin6_port=htons(443), sin6_flowinfo=htonl(0), inet_pton(AF_INET6, \"::1\", &sin6_addr), sin6_scope_id=0}, 28) = 0\n",
            "10 connect(7<socket:[5]>, {sa_family=AF_UNIX, sun_path=\"/var/run/docker.sock\"}, 24) = 0\n",
            "10 connect(7<socket:[6]>, {sa_family=AF_UNIX, sun_path=\"/var/run/none.sock\"}, 24) = -1 ENOENT (No such file or directory)\n",
        ));
        assert!(p.bound_ports.contains(&39187));
        let net = &p.segments[&-1].net;
        assert!(net.contains(&Addr::Inet("127.0.0.1".into(), 39187)));
        assert!(net.contains(&Addr::Inet("192.0.2.1".into(), 9)));
        assert!(net.contains(&Addr::Inet("::1".into(), 443)));
        assert!(net.contains(&Addr::Unix("/var/run/docker.sock".into())));
        assert!(p.segments[&-1].meta.contains("/var/run/none.sock"));
    }

    #[test]
    fn unescape_works() {
        assert_eq!(unescape(r#"a\"b\\c\x41\101\n"#), "a\"b\\cAA\n");
        assert_eq!(clean("/a/./b/../c"), "/a/c");
    }
}
