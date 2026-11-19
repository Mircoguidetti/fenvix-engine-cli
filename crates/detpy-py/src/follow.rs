//! The strace log parser of `detpy/follow.py` (followed children under the cache with proof), in Rust.
//!
//! At the end of a session every followed process tree's logs (`strace -ff -y -ttt`) become inputs of the context
//! that started it; a Python child importing the standard library writes thousands of lines per process. The
//! parser is here, with the same rules; `detpy.follow` keeps the `fork_exec` wrapper (`Follower`), the strace probe
//! and the clock shim build, and builds its `Result` from what `follow_parse` returns.
//!
//! Port of `_strip_ts`, `_logs`, `_complete`, `_unquote`, `_split_args`, `_split_line`, `parse`, `_base`, `_join`,
//! `_sockaddr`, `_parse_one`, `special` and `shebang` (with `_PATH_CALLS`, `_IGNORED_CALLS`, `_DEV_OK`, `_MACHINE`,
//! `_REALTIME_CLOCKS`, `SHIM_MARK`). The Python original is kept verbatim in `tests/rust_hotpaths_ref/_ref_follow.py`
//! and `tests/test_follow_rust.py` checks every result against it (real strace logs and synthetic ones).
//!
//! The logs are parsed as bytes. Python decoded them as UTF-8 with `surrogateescape` and worked on characters; every
//! rule only looks at ASCII characters, so the byte rules give the same results, and the strings handed back are
//! decoded as `os.fsdecode` decodes (the same as UTF-8 with `surrogateescape` on Linux). The few character-level
//! operations are reproduced: `str.splitlines` (its Unicode line boundaries), `str.strip` (Unicode white space)
//! and the 120-character cut of a refused line. Differences: `\d` and `str.isdigit` are ASCII here (Python also
//! accepts other Unicode digits; strace writes timestamps, results and pids in ASCII); an exception of the original
//! (an `int()` of an invalid octal escape, an index out of range on a malformed line, a NUL in a path) is raised
//! with the same type and message.

use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};
use std::collections::{HashMap, HashSet};
use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::os::unix::ffi::{OsStrExt, OsStringExt};

/// `SHIM_MARK`: the path of the clock shim's marker call.
const SHIM_MARK: &[u8] = b"/__detpy_clock_shim__";
const REALTIME_CLOCKS: [&[u8]; 4] = [b"CLOCK_REALTIME", b"CLOCK_REALTIME_COARSE", b"CLOCK_REALTIME_ALARM", b"CLOCK_TAI"];
const IGNORED_CALLS: [&[u8]; 7] = [b"clone", b"clone3", b"fork", b"vfork", b"fchdir", b"getcwd", b"umask"];
const DEV_OK: [&[u8]; 7] =
    [b"/dev/null", b"/dev/zero", b"/dev/full", b"/dev/tty", b"/dev/stdin", b"/dev/stdout", b"/dev/stderr"];
const MACHINE: [&[u8]; 9] = [
    b"/proc/sys/vm/overcommit_memory",
    b"/proc/cpuinfo",
    b"/proc/meminfo",
    b"/sys/devices/system/cpu/",
    b"/sys/fs/cgroup/",
    b"/proc/filesystems",
    b"/proc/mounts",
    b"/sys/fs/selinux",
    b"/sys/fs/selinux/",
];

/// `_PATH_CALLS`: syscall -> (index of the dirfd, index of the path, kind); kind r = probe/read, w = write,
/// x = exec, c = chdir. (`getcwd` maps to None there but is one of the ignored calls, so it never gets here.)
fn path_call(name: &[u8]) -> Option<(Option<usize>, usize, u8)> {
    Some(match name {
        b"stat" | b"lstat" | b"stat64" | b"lstat64" | b"access" | b"readlink" | b"statfs" | b"statfs64"
        | b"getxattr" | b"lgetxattr" | b"listxattr" | b"llistxattr" => (None, 0, b'r'),
        b"newfstatat" | b"fstatat64" | b"statx" | b"faccessat" | b"faccessat2" | b"readlinkat"
        | b"name_to_handle_at" => (Some(0), 1, b'r'),
        b"execve" => (None, 0, b'x'),
        b"execveat" => (Some(0), 1, b'x'),
        b"chdir" => (None, 0, b'c'),
        b"unlink" | b"rmdir" | b"mkdir" | b"chmod" | b"chown" | b"lchown" | b"utime" | b"utimes" | b"mknod"
        | b"truncate" | b"creat" | b"setxattr" | b"lsetxattr" | b"removexattr" | b"lremovexattr" => (None, 0, b'w'),
        b"unlinkat" | b"mkdirat" | b"mknodat" | b"fchmodat" | b"fchmodat2" | b"fchownat" | b"utimensat"
        | b"futimesat" => (Some(0), 1, b'w'),
        b"inotify_add_watch" => (None, 1, b'r'),
        _ => return None,
    })
}

/// An exception the Python original raised out of `parse` (or `_unquote`, `shebang`).
#[derive(Debug)]
enum Fail {
    /// `args[i]` out of range on a malformed line (IndexError).
    Index,
    /// `int(b"8", 8)` for an escape `\8` / `\9` (ValueError).
    Octal(u8),
    /// `open()` of a path with a NUL (ValueError).
    Nul,
}

impl From<Fail> for PyErr {
    fn from(f: Fail) -> PyErr {
        match f {
            Fail::Index => PyIndexError::new_err("list index out of range"),
            Fail::Octal(b) => {
                PyValueError::new_err(format!("invalid literal for int() with base 8: b'{}'", b as char))
            }
            Fail::Nul => PyValueError::new_err("embedded null byte"),
        }
    }
}

fn contains(hay: &[u8], needle: &[u8]) -> bool {
    find(hay, needle).is_some()
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.len() > hay.len() {
        return None;
    }
    hay.windows(needle.len()).position(|w| w == needle)
}

fn cat(parts: &[&[u8]]) -> Vec<u8> {
    parts.concat()
}

fn os(b: Vec<u8>) -> OsString {
    OsString::from_vec(b)
}

// ---------------------------------------------------------------------------
// the character-level operations of the original, on UTF-8 (surrogateescape) bytes

/// Length of the Unicode white space character (`str.isspace`) at the start of `s`, 0 if none. The multi-byte ones
/// start with a lead byte, which is never part of an earlier character: matching the bytes is matching the char.
fn ws_len(s: &[u8]) -> usize {
    match s {
        [b'\t'..=b'\r' | 0x1c..=0x20, ..] => 1,
        [0xc2, 0x85 | 0xa0, ..] => 2,
        [0xe1, 0x9a, 0x80, ..] | [0xe2, 0x80, 0x80..=0x8a | 0xa8 | 0xa9 | 0xaf, ..] | [0xe2, 0x81, 0x9f, ..] => 3,
        [0xe3, 0x80, 0x80, ..] => 3,
        _ => 0,
    }
}

/// `str.strip()`.
fn strip(mut s: &[u8]) -> &[u8] {
    loop {
        let k = ws_len(s);
        if k == 0 {
            break;
        }
        s = &s[k..];
    }
    loop {
        let n = s.len();
        let k = if n >= 1 && ws_len(&s[n - 1..]) == 1 {
            1
        } else if n >= 2 && ws_len(&s[n - 2..]) == 2 {
            2
        } else if n >= 3 && ws_len(&s[n - 3..]) == 3 {
            3
        } else {
            0
        };
        if k == 0 {
            return s;
        }
        s = &s[..n - k];
    }
}

/// `str.splitlines()` (`\n`, `\r`, `\r\n`, `\v`, `\f`, `\x1c`-`\x1e`, U+0085, U+2028, U+2029).
fn splitlines(t: &[u8]) -> Vec<&[u8]> {
    let (n, mut out, mut start, mut i) = (t.len(), Vec::new(), 0, 0);
    while i < n {
        let brk = match t[i] {
            b'\n' | 0x0b | 0x0c | 0x1c..=0x1e => 1,
            b'\r' => {
                if i + 1 < n && t[i + 1] == b'\n' {
                    2
                } else {
                    1
                }
            }
            0xc2 if i + 1 < n && t[i + 1] == 0x85 => 2,
            0xe2 if i + 2 < n && t[i + 1] == 0x80 && (t[i + 2] == 0xa8 || t[i + 2] == 0xa9) => 3,
            _ => 0,
        };
        if brk > 0 {
            out.push(&t[start..i]);
            i += brk;
            start = i;
        } else {
            i += 1;
        }
    }
    if start < n {
        out.push(&t[start..]);
    }
    out
}

/// `line[:n]` in characters (a valid UTF-8 sequence is one character, an undecodable byte is one).
fn char_prefix(s: &[u8], n: usize) -> &[u8] {
    let (mut count, mut pos) = (0, 0);
    for chunk in s.utf8_chunks() {
        for c in chunk.valid().chars() {
            if count == n {
                return &s[..pos];
            }
            count += 1;
            pos += c.len_utf8();
        }
        for _ in chunk.invalid() {
            if count == n {
                return &s[..pos];
            }
            count += 1;
            pos += 1;
        }
    }
    s
}

// ---------------------------------------------------------------------------
// strace syntax

/// `_strip_ts`: `^(\d+\.\d+) ` -> (timestamp, rest).
fn strip_ts(line: &[u8]) -> (Option<f64>, &[u8]) {
    let digits = |from: usize| line[from.min(line.len())..].iter().take_while(|c| c.is_ascii_digit()).count();
    let d1 = digits(0);
    if d1 == 0 || line.get(d1) != Some(&b'.') {
        return (None, line);
    }
    let d2 = digits(d1 + 1);
    let end = d1 + 1 + d2;
    if d2 == 0 || line.get(end) != Some(&b' ') {
        return (None, line);
    }
    // ASCII digits and a dot: Rust's parse is correctly rounded, as Python's float() is
    let t = std::str::from_utf8(&line[..end]).ok().and_then(|s| s.parse::<f64>().ok());
    (t, &line[end + 1..])
}

/// `_unquote`: the bytes of a quoted strace string (escapes decoded), None when not a complete quoted string.
fn unquote(tok: &[u8]) -> Result<Option<Vec<u8>>, Fail> {
    let t = strip(tok);
    if t.ends_with(b"...") {
        return Ok(None); // truncated
    }
    if t.len() < 2 || t[0] != b'"' || t[t.len() - 1] != b'"' {
        return Ok(None);
    }
    unescape(&t[1..t.len() - 1]).map(Some)
}

/// `_ESC.sub(sub, raw)` with `_ESC = rb"\\(x[0-9a-fA-F]{2}|[0-7]{1,3}|.)"`.
fn unescape(raw: &[u8]) -> Result<Vec<u8>, Fail> {
    let n = raw.len();
    let mut out = Vec::with_capacity(n);
    let mut i = 0;
    while i < n {
        let b = raw[i];
        if b != b'\\' || i + 1 >= n || raw[i + 1] == b'\n' {
            out.push(b);
            i += 1;
            continue;
        }
        let e = raw[i + 1];
        if e == b'x' && i + 3 < n && raw[i + 2].is_ascii_hexdigit() && raw[i + 3].is_ascii_hexdigit() {
            let hex = |c: u8| (c as char).to_digit(16).unwrap_or(0) as u8;
            out.push(hex(raw[i + 2]) * 16 + hex(raw[i + 3]));
            i += 4;
            continue;
        }
        if (b'0'..=b'7').contains(&e) {
            let mut v: u32 = 0;
            let mut k = 0;
            while k < 3 && i + 1 + k < n && (b'0'..=b'7').contains(&raw[i + 1 + k]) {
                v = v * 8 + (raw[i + 1 + k] - b'0') as u32;
                k += 1;
            }
            out.push((v & 0xFF) as u8);
            i += 1 + k;
            continue;
        }
        if e == b'8' || e == b'9' {
            return Err(Fail::Octal(e)); // int(e, 8) on the `.` alternative
        }
        out.push(match e {
            b'n' => b'\n',
            b't' => b'\t',
            b'r' => b'\r',
            b'v' => 0x0b,
            b'f' => 0x0c,
            b'a' => 0x07,
            b'b' => 0x08,
            b'e' => 0x1b,
            other => other, // \\ \" \' and unknown escapes: the character itself
        });
        i += 2;
    }
    Ok(out)
}

/// `_split_args`: the top-level comma-separated arguments (quotes and brackets respected), each stripped.
fn split_args(s: &[u8]) -> Vec<&[u8]> {
    let n = s.len();
    let (mut out, mut depth, mut i, mut start) = (Vec::new(), 0i64, 0usize, 0usize);
    while i < n {
        let ch = s[i];
        if ch == b'"' {
            let mut j = i + 1;
            while j < n && s[j] != b'"' {
                j += if s[j] == b'\\' { 2 } else { 1 };
            }
            i = j + 1;
            continue;
        }
        match ch {
            b'{' | b'[' | b'(' | b'<' => depth += 1,
            b'}' | b']' | b')' | b'>' => depth -= 1,
            b',' if depth == 0 => {
                out.push(strip(&s[start..i]));
                i += 1;
                start = i;
                continue;
            }
            _ => {}
        }
        i += 1;
    }
    if start < n {
        out.push(strip(&s[start..]));
    }
    out
}

/// One parsed strace line: (syscall, args text, result, decoration, errno).
struct Split<'a> {
    name: &'a [u8],
    args: &'a [u8],
    ret: &'a [u8],
    deco: Option<&'a [u8]>,
    err: Option<&'a [u8]>,
}

/// The tail after the decoration: `( [A-Z][A-Z0-9_]+ \(.*\))?( <unavailable>)?$` -> Some(errno name).
fn res_tail(s: &[u8]) -> Option<Option<&[u8]>> {
    if s.len() >= 3 && s[0] == b' ' && s[1].is_ascii_uppercase() {
        let mut q = 2;
        while q < s.len() && (s[q].is_ascii_uppercase() || s[q].is_ascii_digit() || s[q] == b'_') {
            q += 1;
        }
        if q >= 3 && s[q..].starts_with(b" (") {
            let open = q + 1;
            for c in (open + 1..s.len()).rev() {
                if s[c] == b')' {
                    let rest = &s[c + 1..];
                    if rest.is_empty() || rest == b" <unavailable>" {
                        return Some(Some(&s[1..q]));
                    }
                }
            }
        }
    }
    if s.is_empty() || s == b" <unavailable>" {
        Some(None)
    } else {
        None
    }
}

/// After the result value: `(<.*>)?` then `res_tail` -> (decoration, errno).
#[allow(clippy::type_complexity)]
fn res_rest(s: &[u8]) -> Option<(Option<&[u8]>, Option<&[u8]>)> {
    if s.first() == Some(&b'<') {
        for j in (1..s.len()).rev() {
            if s[j] == b'>' {
                if let Some(err) = res_tail(&s[j + 1..]) {
                    return Some((Some(&s[..=j]), err));
                }
            }
        }
    }
    res_tail(s).map(|e| (None, e))
}

/// `_RES.fullmatch(r)`: `(-?\d+|\?|0x[0-9a-f]+)(<.*>)?( [A-Z][A-Z0-9_]+ \(.*\))?( <unavailable>)?$`.
#[allow(clippy::type_complexity)]
fn res_match(r: &[u8]) -> Option<(&[u8], Option<&[u8]>, Option<&[u8]>)> {
    if r.contains(&b'\n') {
        return None; // no part of the pattern matches a newline
    }
    let neg = usize::from(r.first() == Some(&b'-'));
    let d = r[neg..].iter().take_while(|c| c.is_ascii_digit()).count();
    if d > 0 {
        if let Some((deco, err)) = res_rest(&r[neg + d..]) {
            return Some((&r[..neg + d], deco, err));
        }
    }
    if r.first() == Some(&b'?') {
        if let Some((deco, err)) = res_rest(&r[1..]) {
            return Some((&r[..1], deco, err));
        }
    }
    if r.starts_with(b"0x") {
        let h = r[2..].iter().take_while(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(c)).count();
        if h > 0 {
            if let Some((deco, err)) = res_rest(&r[2 + h..]) {
                return Some((&r[..2 + h], deco, err));
            }
        }
    }
    None
}

/// `_split_line`: the last `) += ` after which the rest is a result.
fn split_line(line: &[u8]) -> Option<Split<'_>> {
    let k = line.iter().position(|&c| c == b'(')?;
    if k == 0 {
        return None;
    }
    let n = line.len();
    // `_SEP = \) += `: a ')' then one or more spaces then "= " (a match holds no other ')')
    for i in (k..n).rev() {
        if line[i] != b')' {
            continue;
        }
        let mut j = i + 1;
        while j < n && line[j] == b' ' {
            j += 1;
        }
        if j == i + 1 || j + 1 >= n || line[j] != b'=' || line[j + 1] != b' ' {
            continue;
        }
        if let Some((ret, deco, err)) = res_match(&line[j + 2..]) {
            return Some(Split { name: &line[..k], args: &line[k + 1..i], ret, deco, err });
        }
    }
    None
}

/// `_base`: the path of a `-y` fd decoration (`3</path>`, `AT_FDCWD</cwd>`), `cwd` for a bare `AT_FDCWD`.
fn base(tok: &[u8], cwd: &[u8]) -> Option<Vec<u8>> {
    let t = strip(tok);
    // _FDPATH = ^(?:-?\d+|AT_FDCWD)<(.*)>$
    let neg = usize::from(t.first() == Some(&b'-'));
    let d = t[neg..].iter().take_while(|c| c.is_ascii_digit()).count();
    let head = if d > 0 {
        Some(neg + d)
    } else if t.starts_with(b"AT_FDCWD") {
        Some(8)
    } else {
        None
    };
    if let Some(h) = head {
        if t.len() >= h + 2 && t[h] == b'<' && t[t.len() - 1] == b'>' {
            let mid = &t[h + 1..t.len() - 1];
            if !mid.contains(&b'\n') {
                return Some(mid.to_vec());
            }
        }
    }
    if t == b"AT_FDCWD" {
        return Some(cwd.to_vec());
    }
    None
}

/// `os.path.normpath` (POSIX).
fn normpath(path: &[u8]) -> Vec<u8> {
    if path.is_empty() {
        return b".".to_vec();
    }
    let mut initial = usize::from(path.starts_with(b"/"));
    if initial == 1 && path.starts_with(b"//") && !path.starts_with(b"///") {
        initial = 2;
    }
    let mut comps: Vec<&[u8]> = Vec::new();
    for comp in path.split(|&c| c == b'/') {
        if comp.is_empty() || comp == b"." {
            continue;
        }
        if comp != b".." || (initial == 0 && comps.is_empty()) || comps.last() == Some(&&b".."[..]) {
            comps.push(comp);
        } else if !comps.is_empty() {
            comps.pop();
        }
    }
    let mut out = vec![b'/'; initial];
    for (i, c) in comps.iter().enumerate() {
        if i > 0 {
            out.push(b'/');
        }
        out.extend_from_slice(c);
    }
    if out.is_empty() {
        out.push(b'.');
    }
    out
}

/// `_join`: `normpath(p)` for an absolute `p`, else `normpath(os.path.join(base or cwd, p))`.
fn join(base: Option<&[u8]>, p: &[u8], cwd: &[u8]) -> Vec<u8> {
    if p.starts_with(b"/") {
        return normpath(p);
    }
    let a = match base {
        Some(b) if !b.is_empty() => b,
        _ => cwd,
    };
    let mut s = Vec::with_capacity(a.len() + 1 + p.len());
    s.extend_from_slice(a);
    if !(s.is_empty() || s.ends_with(b"/")) {
        s.push(b'/');
    }
    s.extend_from_slice(p);
    normpath(&s)
}

/// End of a `"(?:[^"\\]|\\.)*"` starting at `q`, if it matches there.
fn quoted_end(t: &[u8], q: usize) -> Option<usize> {
    if t.get(q) != Some(&b'"') {
        return None;
    }
    let mut j = q + 1;
    while j < t.len() {
        match t[j] {
            b'"' => return Some(j + 1),
            b'\\' => {
                if j + 1 < t.len() && t[j + 1] != b'\n' {
                    j += 2;
                } else {
                    return None;
                }
            }
            _ => j += 1,
        }
    }
    None
}

/// `_sockaddr`: (address family, Unix socket path with `@` for an abstract one).
#[allow(clippy::type_complexity)]
fn sockaddr(tok: &[u8]) -> Result<(Option<&[u8]>, Option<Vec<u8>>), Fail> {
    let mut fam = None;
    let mut from = 0;
    while let Some(k) = find(&tok[from..], b"sa_family=AF_") {
        let s = from + k + b"sa_family=".len();
        let run = tok[s + 3..].iter().take_while(|c| c.is_ascii_uppercase() || c.is_ascii_digit()).count();
        if run > 0 {
            fam = Some(&tok[s..s + 3 + run]);
            break;
        }
        from = from + k + 1;
    }
    let mut p = None;
    let mut from = 0;
    while let Some(k) = find(&tok[from..], b"sun_path=") {
        let q = from + k + b"sun_path=".len();
        let found = if tok.get(q) == Some(&b'@') {
            quoted_end(tok, q + 1).map(|e| (true, q + 1, e))
        } else {
            None
        }
        .or_else(|| quoted_end(tok, q).map(|e| (false, q, e)));
        if let Some((at, s, e)) = found {
            let mut v = if at { b"@".to_vec() } else { Vec::new() };
            v.extend(unquote(&tok[s..e])?.unwrap_or_default());
            p = Some(v);
            break;
        }
        from = from + k + 1;
    }
    Ok((fam, p))
}

// ---------------------------------------------------------------------------
// parse

enum Bad {
    Text(Vec<u8>),
    /// (index of the log in `paths`, errno): the message is the OSError's, built by the caller
    Unreadable(usize, i32),
}

#[derive(Default)]
struct Parsed {
    ops: Vec<(&'static str, Vec<u8>)>,
    net: Option<Vec<u8>>,
    bad: Option<Bad>,
    entropy: i64,
    bound: Vec<Option<Vec<u8>>>,
    bound_set: HashSet<Option<Vec<u8>>>,
    clock: Option<Vec<u8>>,
    unshimmed: Option<Vec<u8>>,
    t0: Option<f64>,
    t1: Option<f64>,
    /// path -> first time the tree wrote it (review R-009b R4)
    wrote_at: HashMap<Vec<u8>, f64>,
    /// (time, path, call): a path's times read by name, in log order
    stats: Vec<(f64, Vec<u8>, Vec<u8>)>,
}

/// Calls that return a path's times (st_mtime, st_atime, st_ctime, stx_btime).
const STAT_CALLS: [&[u8]; 7] = [b"stat", b"lstat", b"stat64", b"lstat64", b"newfstatat", b"fstatat64", b"statx"];
/// Programs whose behaviour does not depend on the times of the paths they stat (rm -r stats what it removes).
const NO_TIME_PROGRAMS: [&[u8]; 6] = [b"rm", b"rmdir", b"mkdir", b"ln", b"chmod", b"chown"];

/// `^/proc/(\d+|self|thread-self)(/task/(\d+))?$` (Python's `$` also matches before a final newline).
fn proc_pid_dir(p: &[u8]) -> bool {
    let p = p.strip_suffix(b"\n").unwrap_or(p);
    let Some(rest) = p.strip_prefix(b"/proc/") else { return false };
    let digits = |b: &[u8]| !b.is_empty() && b.iter().all(|c| c.is_ascii_digit());
    let (first, tail) = match rest.iter().position(|&c| c == b'/') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, &rest[..0]),
    };
    if !(digits(first) || first == b"self" || first == b"thread-self") {
        return false;
    }
    tail.is_empty() || tail.strip_prefix(b"/task/").is_some_and(digits)
}

impl Parsed {
    fn wrote_at(&mut self, p: &[u8], t: Option<f64>) {
        if !self.wrote_at.contains_key(p) {
            self.wrote_at.insert(p.to_vec(), t.unwrap_or(f64::NEG_INFINITY));
        }
    }

    fn bad(&mut self, msg: Vec<u8>) {
        if self.bad.is_none() {
            self.bad = Some(Bad::Text(msg));
        }
    }

    fn net(&mut self, msg: Vec<u8>) {
        if self.net.is_none() {
            self.net = Some(msg);
        }
    }

    fn clock(&mut self, msg: Vec<u8>) {
        if self.clock.is_none() {
            self.clock = Some(msg);
        }
    }
}

fn arg<'a>(args: &[&'a [u8]], i: usize) -> Result<&'a [u8], Fail> {
    args.get(i).copied().ok_or(Fail::Index)
}

fn parse_paths(paths: &[Vec<u8>], cwd: &[u8]) -> Result<Parsed, Fail> {
    let mut res = Parsed::default();
    for (ix, path) in paths.iter().enumerate() {
        if path.contains(&0) {
            return Err(Fail::Nul);
        }
        let text = match fs::read(OsStr::from_bytes(path)) {
            Ok(t) => t,
            Err(e) => {
                if res.bad.is_none() {
                    res.bad = Some(Bad::Unreadable(ix, e.raw_os_error().unwrap_or(5)));
                }
                continue;
            }
        };
        let mut lines = Vec::new();
        let mut times = Vec::new();
        let (mut first, mut last) = (None, None);
        for l in splitlines(&text) {
            let (t, rest) = strip_ts(l);
            if let Some(t) = t {
                first.get_or_insert(t);
                last = Some(t);
            }
            lines.push(rest);
            times.push(t);
        }
        if let (Some(a), Some(b)) = (first, last) {
            // min(times[0], t0) / max(times[-1], t1)
            res.t0 = Some(match res.t0 {
                Some(t0) if t0 < a => t0,
                _ => a,
            });
            res.t1 = Some(match res.t1 {
                Some(t1) if t1 > b => t1,
                _ => b,
            });
        }
        let complete = lines.last().is_some_and(|l| l.starts_with(b"+++ exited with") || l.starts_with(b"+++ killed by"));
        if !complete {
            res.bad(b"a process was still running at the end of the session".to_vec());
            continue;
        }
        parse_one(&lines, &times, cwd, &mut res)?;
    }
    // review R-009b R4: the times of a file the tree itself wrote are the real clock at the write (stat -c %Y,
    // date -r, find -newer, make, os.path.getmtime), and the times of a process directory under /proc are the real
    // clock at its start; neither passes through the clock library. Any process of the tree may write and another
    // stat, so the order is the trace's clock (-ttt), across logs.
    if res.clock.is_none() {
        for (t, p, call) in &res.stats {
            if proc_pid_dir(p) {
                res.clock = Some(cat(&[b"reads the real clock (a process start time: ", call, b" ", p, b")"]));
                break;
            }
            if let Some(&w) = res.wrote_at.get(p) {
                if w <= *t {
                    res.clock = Some(cat(&[b"reads the real clock (the time of a file it wrote: ", call, b" ", p, b")"]));
                    break;
                }
            }
        }
    }
    Ok(res)
}

fn parse_one(lines: &[&[u8]], times: &[Option<f64>], cwd0: &[u8], res: &mut Parsed) -> Result<(), Fail> {
    let mut cwd = cwd0.to_vec();
    let mut unmarked: Option<Vec<u8>> = None; // a program this process exec'd that has not made the marker call
    let mut prog: Option<Vec<u8>> = None; // the program this process runs (after its last successful exec)
    let mut t: Option<f64> = None;
    for (k, &line) in lines.iter().enumerate() {
        if let Some(Some(tk)) = times.get(k) {
            t = Some(*tk);
        }
        if line.is_empty() || line.starts_with(b"+++") || line.starts_with(b"---") {
            continue;
        }
        let Some(sp) = split_line(line) else {
            res.bad(cat(&[b"unparsed line: ", char_prefix(line, 120)]));
            continue;
        };
        let (name, argtext, ret, err) = (sp.name, sp.args, sp.ret, sp.err);
        let _ = sp.deco;
        let ok = ret != b"?" && !ret.starts_with(b"-");
        if let Some(k) = find(argtext, b"AT_FDCWD<") {
            let rest = &argtext[k + 9..];
            if let Some(q) = rest.iter().position(|&c| c == b'>') {
                cwd = rest[..q].to_vec();
            }
        }
        if contains(argtext, SHIM_MARK) && matches!(name, b"faccessat" | b"faccessat2" | b"access") {
            unmarked = None;
            continue;
        }
        if name == b"clock_gettime" {
            let first = strip(argtext.split(|&c| c == b',').next().unwrap_or(b""));
            if REALTIME_CLOCKS.contains(&first) {
                res.clock(cat(&[b"reads the real clock (", first, b")"]));
            }
            continue;
        }
        if name == b"gettimeofday" || name == b"time" {
            res.clock(cat(&[b"reads the real clock (", name, b")"]));
            continue;
        }
        if (name == b"execve" || name == b"execveat") && ok {
            let args0 = split_args(argtext);
            unmarked = if args0.is_empty() {
                Some(b"?".to_vec())
            } else {
                unquote(arg(&args0, if name == b"execve" { 0 } else { 1 })?)?
            };
            // os.path.basename(unmarked or "")
            let u: &[u8] = unmarked.as_deref().unwrap_or(b"");
            prog = Some(u[u.iter().rposition(|&c| c == b'/').map_or(0, |i| i + 1)..].to_vec());
        }
        if IGNORED_CALLS.contains(&name) {
            if name == b"fchdir" && ok {
                if let Some(b) = base(arg(&split_args(argtext), 0)?, &cwd) {
                    if !b.is_empty() {
                        cwd = b;
                    }
                }
            }
            continue;
        }
        let args = split_args(argtext);
        let unparsed_path = |res: &mut Parsed| res.bad(cat(&[b"unparsed path: ", char_prefix(line, 120)]));
        match name {
            b"open" | b"openat" | b"openat2" => {
                let i = if name == b"open" { 0 } else { 1 };
                let b = if name == b"open" { None } else { base(arg(&args, 0)?, &cwd) };
                let p = if args.len() > i { unquote(args[i])? } else { None };
                let Some(p) = p else {
                    unparsed_path(res);
                    continue;
                };
                let p = join(b.as_deref(), &p, &cwd);
                let flags: &[u8] = args.get(i + 1).copied().unwrap_or(b"");
                if contains(flags, b"O_TMPFILE") {
                    continue; // an unnamed temporary file in that directory: nothing visible changes
                }
                let has = |f: &[u8]| contains(flags, f);
                let wr = has(b"O_WRONLY") || has(b"O_RDWR") || has(b"O_CREAT") || has(b"O_TRUNC") || has(b"O_APPEND");
                if !ok || !wr {
                    res.ops.push(("r", p));
                } else {
                    if has(b"O_CREAT") && has(b"O_EXCL") {
                        res.ops.push(("a", p.clone())); // review R-009b R2: it succeeded, so the path did not exist
                    } else if has(b"O_RDWR") && !has(b"O_TRUNC") {
                        res.ops.push(("r", p.clone()));
                    }
                    res.wrote_at(&p, t);
                    res.ops.push(("w", p));
                }
                continue;
            }
            b"getdents" | b"getdents64" => {
                if ok {
                    match args.first().and_then(|a| base(a, &cwd)) {
                        None => res.bad(cat(&[b"unparsed fd: ", char_prefix(line, 120)])),
                        Some(b) => res.ops.push(("d", b)),
                    }
                }
                continue;
            }
            b"rename" | b"renameat" | b"renameat2" | b"link" | b"linkat" => {
                let pairs: [(Option<usize>, usize); 2] =
                    if name == b"rename" || name == b"link" { [(None, 0), (None, 1)] } else { [(Some(0), 1), (Some(2), 3)] };
                for (bi, pi) in pairs {
                    let p = if args.len() > pi { unquote(args[pi])? } else { None };
                    let Some(p) = p else {
                        unparsed_path(res);
                        break;
                    };
                    let b = bi.and_then(|bi| base(args[bi], &cwd));
                    res.ops.push((if ok { "w" } else { "r" }, join(b.as_deref(), &p, &cwd)));
                }
                continue;
            }
            b"symlink" | b"symlinkat" => {
                let (pi, bi) = if name == b"symlink" { (1, None) } else { (2, Some(1)) };
                let p = if args.len() > pi { unquote(args[pi])? } else { None };
                let Some(p) = p else {
                    unparsed_path(res);
                    continue;
                };
                let b = bi.and_then(|bi| base(args[bi], &cwd));
                res.ops.push((if ok { "w" } else { "r" }, join(b.as_deref(), &p, &cwd)));
                continue;
            }
            b"connect" | b"sendto" | b"sendmsg" | b"bind" => {
                let (fam, sun) = sockaddr(argtext)?;
                let Some(fam) = fam else {
                    continue; // sendto / sendmsg on a connected socket: its connect was seen
                };
                if fam == b"AF_UNIX" {
                    let real = sun.as_ref().filter(|s| !s.is_empty() && !s.starts_with(b"@"));
                    if name == b"bind" {
                        if let Some(s) = real.filter(|_| ok) {
                            res.ops.push(("w", join(None, s, &cwd)));
                        }
                        if res.bound_set.insert(sun.clone()) {
                            res.bound.push(sun);
                        }
                        continue;
                    }
                    if res.bound_set.contains(&sun) {
                        continue;
                    }
                    if let Some(s) = real {
                        if !ok && matches!(err, Some(b"ENOENT" | b"ENOTDIR")) {
                            res.ops.push(("r", join(None, s, &cwd))); // a probe (nscd): its absence is the input
                            continue;
                        }
                    }
                    let shown: &[u8] = sun.as_deref().unwrap_or(b"None");
                    res.net(cat(&[name, b" unix ", shown]));
                    continue;
                }
                if fam == b"AF_NETLINK" {
                    res.net(cat(&[name, b" netlink"]));
                    continue;
                }
                if name == b"bind" {
                    continue;
                }
                res.net(cat(&[name, b" ", fam]));
                continue;
            }
            b"getrandom" => {
                res.entropy += 1;
                continue;
            }
            _ => {}
        }
        let Some((bi, pi, kind)) = path_call(name) else {
            res.bad(cat(&[b"system call not followed: ", name]));
            continue;
        };
        let p = if args.len() > pi { unquote(args[pi])? } else { None };
        let Some(p) = p else {
            unparsed_path(res);
            continue;
        };
        if p.is_empty() && bi.is_some() {
            continue; // AT_EMPTY_PATH: the fd's own file, recorded at its open
        }
        let b = bi.and_then(|bi| base(args[bi], &cwd));
        let p = join(b.as_deref(), &p, &cwd);
        match kind {
            b'c' => {
                if ok {
                    cwd = p.clone();
                }
                res.ops.push(("r", p));
            }
            b'x' => res.ops.push(("x", p)),
            b'w' if ok => {
                res.wrote_at(&p, t);
                res.ops.push(("w", p));
            }
            _ => {
                if ok && STAT_CALLS.contains(&name) && !prog.as_deref().is_some_and(|g| NO_TIME_PROGRAMS.contains(&g)) {
                    res.stats.push((t.unwrap_or(f64::INFINITY), p.clone(), name.to_vec()));
                }
                res.ops.push(("r", p));
            }
        }
    }
    if let Some(u) = unmarked {
        if res.unshimmed.as_ref().is_none_or(|x| x.is_empty()) {
            res.unshimmed = Some(u);
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// bindings

type ParseOut = (
    Vec<(&'static str, OsString)>,
    Option<OsString>,
    Option<OsString>,
    Option<(usize, i32)>,
    i64,
    Vec<Option<OsString>>,
    Option<OsString>,
    Option<OsString>,
    Option<f64>,
    Option<f64>,
);

/// `follow.parse` of the logs `paths` of one process tree started in `cwd`: `(ops, net, bad, unreadable, entropy,
/// bound, clock, unshimmed, t0, t1)`. `unreadable` is `(index in paths, errno)` when the first refusal is a log
/// that could not be read (the caller builds the OSError message); `bound` is in first-bound order.
#[pyfunction]
pub fn follow_parse(py: Python<'_>, paths: Vec<OsString>, cwd: OsString) -> PyResult<ParseOut> {
    let paths: Vec<Vec<u8>> = paths.into_iter().map(|p| p.into_vec()).collect();
    let cwd = cwd.into_vec();
    let r = py.detach(|| parse_paths(&paths, &cwd))?;
    let (bad, unreadable) = match r.bad {
        None => (None, None),
        Some(Bad::Text(t)) => (Some(os(t)), None),
        Some(Bad::Unreadable(i, e)) => (None, Some((i, e))),
    };
    Ok((
        r.ops.into_iter().map(|(op, p)| (op, os(p))).collect(),
        r.net.map(os),
        bad,
        unreadable,
        r.entropy,
        r.bound.into_iter().map(|b| b.map(os)).collect(),
        r.clock.map(os),
        r.unshimmed.map(os),
        r.t0,
        r.t1,
    ))
}

/// `os.path.split(prefix)`.
fn path_split(p: &[u8]) -> (&[u8], &[u8]) {
    let i = p.iter().rposition(|&c| c == b'/').map_or(0, |i| i + 1);
    let (mut head, tail) = (&p[..i], &p[i..]);
    if !head.is_empty() && head.iter().any(|&c| c != b'/') {
        while head.ends_with(b"/") {
            head = &head[..head.len() - 1];
        }
    }
    (head, tail)
}

/// `follow._logs`: the logs `prefix.<pid>` of one spawn, sorted.
#[pyfunction]
pub fn follow_logs(py: Python<'_>, prefix: OsString) -> PyResult<Vec<OsString>> {
    let prefix = prefix.into_vec();
    if prefix.contains(&0) {
        return Err(Fail::Nul.into());
    }
    Ok(py.detach(|| {
        let (d, base) = path_split(&prefix);
        if d.is_empty() {
            return Vec::new(); // os.listdir("") fails
        }
        let Ok(rd) = fs::read_dir(OsStr::from_bytes(d)) else { return Vec::new() };
        let mut out = Vec::new();
        for e in rd {
            let Ok(e) = e else { return Vec::new() };
            let name = e.file_name().into_vec();
            let ok = name.len() > base.len() + 1
                && name.starts_with(base)
                && name[base.len()] == b'.'
                && name[base.len() + 1..].iter().all(|c| c.is_ascii_digit());
            if ok {
                let mut full = d.to_vec();
                if !full.ends_with(b"/") {
                    full.push(b'/');
                }
                full.extend_from_slice(&name);
                out.push(full);
            }
        }
        // the names differ only in their ASCII digits: byte order is code point order
        out.sort();
        out.into_iter().map(os).collect()
    }))
}

fn complete(path: &[u8]) -> bool {
    let tail = (|| -> std::io::Result<Vec<u8>> {
        let mut fh = fs::File::open(OsStr::from_bytes(path))?;
        let n = fh.seek(SeekFrom::End(0))?;
        fh.seek(SeekFrom::Start(n.saturating_sub(4096)))?;
        let mut buf = Vec::new();
        fh.read_to_end(&mut buf)?;
        Ok(buf)
    })();
    let Ok(buf) = tail else { return false };
    let mut end = buf.len();
    while end > 0 && buf[end - 1] == b'\n' {
        end -= 1;
    }
    let buf = &buf[..end];
    let last = match buf.iter().rposition(|&c| c == b'\n') {
        Some(i) => &buf[i + 1..],
        None => buf,
    };
    let rest = strip_ts(last).1;
    rest.starts_with(b"+++ exited with") || rest.starts_with(b"+++ killed by")
}

/// `follow._complete`: the log ends with its process's exit.
#[pyfunction]
pub fn follow_complete(py: Python<'_>, path: OsString) -> PyResult<bool> {
    let path = path.into_vec();
    if path.contains(&0) {
        return Err(Fail::Nul.into());
    }
    Ok(py.detach(|| complete(&path)))
}

/// `follow.special(p, pids)`: 'skip' (not an input), 'entropy', 'proc' (refused) or None (an ordinary path).
#[pyfunction]
pub fn follow_special(p: &Bound<'_, PyString>, pids: &Bound<'_, PyAny>) -> PyResult<Option<&'static str>> {
    let py = p.py();
    // the str's code points as UTF-8; a lone surrogate (a byte os.fsdecode could not decode) as its 3 bytes
    let owned: Vec<u8>;
    let cow;
    let b: &[u8] = match p.to_cow() {
        Ok(s) => {
            cow = s;
            cow.as_bytes()
        }
        Err(_) => {
            owned = p.call_method1("encode", ("utf-8", "surrogatepass"))?.extract()?;
            &owned
        }
    };
    let starts = |pre: &[u8]| b.starts_with(pre);
    if !(starts(b"/proc") || starts(b"/sys") || starts(b"/dev")) {
        return Ok(None);
    }
    if matches!(b, b"/proc" | b"/sys" | b"/dev") {
        return Ok(Some("skip"));
    }
    if starts(b"/dev/shm/") {
        return Ok(None); // a tmpfs of ordinary files (shared memory, test data): read and written like any file
    }
    if DEV_OK.contains(&b) || starts(b"/dev/fd/") || starts(b"/dev/pts/") {
        return Ok(Some("skip"));
    }
    if b == b"/dev/urandom" || b == b"/dev/random" {
        return Ok(Some("entropy"));
    }
    if starts(b"/proc/self") || starts(b"/proc/thread-self") {
        return Ok(Some("skip"));
    }
    if starts(b"/proc/") {
        let rest = &b[6..];
        let first = &rest[..rest.iter().position(|&c| c == b'/').unwrap_or(rest.len())];
        let first: Bound<'_, PyAny> = match std::str::from_utf8(first) {
            Ok(s) => PyString::new(py, s).into_any(),
            Err(_) => PyBytes::new(py, first).call_method1("decode", ("utf-8", "surrogatepass"))?,
        };
        if pids.contains(first)? {
            return Ok(Some("skip"));
        }
    }
    if MACHINE.iter().any(|m| b == *m || (m.ends_with(b"/") && b.starts_with(m))) {
        return Ok(Some("skip"));
    }
    Ok(Some("proc"))
}

/// `follow.shebang(path)`: the interpreter of a `#!` script, None otherwise.
#[pyfunction]
pub fn follow_shebang(py: Python<'_>, path: OsString) -> PyResult<Option<OsString>> {
    let path = path.into_vec();
    if path.contains(&0) {
        return Err(Fail::Nul.into());
    }
    Ok(py.detach(|| {
        let mut head = Vec::with_capacity(256);
        let f = fs::File::open(OsStr::from_bytes(&path)).ok()?;
        f.take(256).read_to_end(&mut head).ok()?;
        let line = head.strip_prefix(b"#!")?;
        let line = &line[..line.iter().position(|&c| c == b'\n').unwrap_or(line.len())];
        // bytes.strip().split(): ASCII white space
        let first = line.split(|c| b" \t\n\r\x0b\x0c".contains(c)).find(|w| !w.is_empty())?;
        Some(os(first.to_vec()))
    }))
}

/// `follow._split_line` on the UTF-8 (surrogateescape) bytes of a line (for the equivalence tests).
#[pyfunction]
#[allow(clippy::type_complexity)]
pub fn follow_split_line(line: &[u8]) -> Option<(OsString, OsString, OsString, Option<OsString>, Option<OsString>)> {
    let v = |b: &[u8]| os(b.to_vec());
    split_line(line).map(|s| (v(s.name), v(s.args), v(s.ret), s.deco.map(v), s.err.map(v)))
}

/// `follow._split_args` (for the equivalence tests).
#[pyfunction]
pub fn follow_split_args(s: &[u8]) -> Vec<OsString> {
    split_args(s).into_iter().map(|a| os(a.to_vec())).collect()
}

/// `follow._unquote` (for the equivalence tests).
#[pyfunction]
pub fn follow_unquote(tok: &[u8]) -> PyResult<Option<OsString>> {
    Ok(unquote(tok)?.map(os))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(follow_parse, m)?)?;
    m.add_function(wrap_pyfunction!(follow_logs, m)?)?;
    m.add_function(wrap_pyfunction!(follow_complete, m)?)?;
    m.add_function(wrap_pyfunction!(follow_special, m)?)?;
    m.add_function(wrap_pyfunction!(follow_shebang, m)?)?;
    m.add_function(wrap_pyfunction!(follow_split_line, m)?)?;
    m.add_function(wrap_pyfunction!(follow_split_args, m)?)?;
    m.add_function(wrap_pyfunction!(follow_unquote, m)?)?;
    Ok(())
}
