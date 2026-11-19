//! `--det`'s re-exec decisions (`detpy/reexec.py`): the pure parts.
//!
//! * [`personality_no_randomize`]: `/proc/self/personality` parsed as `int(text.strip(), 16) & ADDR_NO_RANDOMIZE`.
//! * [`realpath`]: `os.path.realpath` (non-strict, Python 3.13's algorithm) on bytes.
//! * [`join`]: `os.path.join` on bytes.
//! * [`Stamps`]: the precompile's `stamps-v3.json` (read as `json.load`, written as `json.dump`, key order and
//!   formatting included), and [`plan_precompile`]: which directories to check (the project always, a library
//!   directory when its stamp changed) and the stamps to write after a complete precompile.
//!
//! The Python original is kept verbatim in `tests/rust_hotpaths_ref/_ref_reexec_r2.py`.

use std::collections::HashMap;
use std::ffi::OsStr;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;

/// `personality(2)`'s ADDR_NO_RANDOMIZE.
pub const ADDR_NO_RANDOMIZE: u64 = 0x0040000;

/// Python's `str.strip()` whitespace (the characters `str.isspace` holds for).
fn py_space(c: char) -> bool {
    matches!(c, '\t'..='\r' | '\u{1c}'..='\u{20}' | '\u{85}' | '\u{a0}' | '\u{1680}' | '\u{2000}'..='\u{200a}'
        | '\u{2028}' | '\u{2029}' | '\u{202f}' | '\u{205f}' | '\u{3000}')
}

/// `int(text, 16)` reduced modulo 2**64 (two's complement for a negative value), None where Python raises.
pub fn parse_hex_int(text: &str) -> Option<u64> {
    let s = text.trim_matches(py_space);
    let (neg, s) = match s.as_bytes().first() {
        Some(b'-') => (true, &s[1..]),
        Some(b'+') => (false, &s[1..]),
        _ => (false, s),
    };
    let s = if s.len() >= 2 && (s.starts_with("0x") || s.starts_with("0X")) {
        // an underscore may follow the prefix
        s[2..].strip_prefix('_').unwrap_or(&s[2..])
    } else {
        s
    };
    if s.is_empty() || s.starts_with('_') || s.ends_with('_') || s.contains("__") {
        return None;
    }
    let mut v: u64 = 0;
    for c in s.chars() {
        if c == '_' {
            continue;
        }
        let d = c.to_digit(16)?;
        v = v.wrapping_mul(16).wrapping_add(d as u64);
    }
    Some(if neg { v.wrapping_neg() } else { v })
}

/// `bool(int(text.strip(), 16) & ADDR_NO_RANDOMIZE)`, None when the text is not a hex number.
pub fn personality_no_randomize(text: &str) -> Option<bool> {
    parse_hex_int(text).map(|v| v & ADDR_NO_RANDOMIZE != 0)
}

/// `os.path.join(a, *parts)` on bytes.
pub fn join(a: &[u8], parts: &[&[u8]]) -> Vec<u8> {
    let mut out = a.to_vec();
    for b in parts {
        if b.starts_with(b"/") {
            out = b.to_vec();
        } else if out.is_empty() || out.ends_with(b"/") {
            out.extend_from_slice(b);
        } else {
            out.push(b'/');
            out.extend_from_slice(b);
        }
    }
    out
}

fn os(b: &[u8]) -> &Path {
    Path::new(OsStr::from_bytes(b))
}

/// `os.path.realpath(path)` (non-strict): absolute, `.`/`..` and symbolic links resolved as far as they exist, a
/// symlink loop left as it is. `cwd` is `os.getcwd()`.
pub fn realpath(path: &[u8], cwd: &[u8]) -> Vec<u8> {
    enum Part {
        Name(Vec<u8>),
        Resolved(Vec<u8>),
    }
    let mut rest: Vec<Part> = path.split(|&c| c == b'/').rev().map(|p| Part::Name(p.to_vec())).collect();
    let mut part_count = rest.len();
    let mut out: Vec<u8> = if path.starts_with(b"/") { b"/".to_vec() } else { cwd.to_vec() };
    let mut seen: HashMap<Vec<u8>, Option<Vec<u8>>> = HashMap::new();
    while part_count > 0 {
        let name = match rest.pop() {
            Some(Part::Name(n)) => n,
            Some(Part::Resolved(link)) => {
                seen.insert(link, Some(out.clone()));
                continue;
            }
            None => break,
        };
        part_count -= 1;
        if name.is_empty() || name == b"." {
            continue;
        }
        if name == b".." {
            let i = out.iter().rposition(|&c| c == b'/').unwrap_or(0);
            out.truncate(i);
            if out.is_empty() {
                out = b"/".to_vec();
            }
            continue;
        }
        let newpath = if out == b"/" { [b"/".as_slice(), &name].concat() } else { [out.as_slice(), b"/", &name].concat() };
        let target = match std::fs::symlink_metadata(os(&newpath)) {
            Err(_) => {
                out = newpath;
                continue;
            }
            Ok(m) if !m.file_type().is_symlink() => {
                out = newpath;
                continue;
            }
            Ok(_) => {
                if let Some(v) = seen.get(&newpath) {
                    match v {
                        Some(p) => out = p.clone(),
                        None => out = newpath, // a loop
                    }
                    continue;
                }
                match std::fs::read_link(os(&newpath)) {
                    Ok(t) => t.into_os_string().into_encoded_bytes(),
                    Err(_) => {
                        out = newpath;
                        continue;
                    }
                }
            }
        };
        if target.starts_with(b"/") {
            out = b"/".to_vec();
        }
        seen.insert(newpath.clone(), None);
        rest.push(Part::Resolved(newpath));
        let parts: Vec<&[u8]> = target.split(|&c| c == b'/').collect();
        part_count += parts.len();
        rest.extend(parts.into_iter().rev().map(|p| Part::Name(p.to_vec())));
    }
    out
}

/// A Python `str` as its code points (lone surrogates included).
pub type PyStr = Vec<u32>;

/// `os.fsdecode(bytes)` (UTF-8, surrogateescape) as code points.
pub fn fsdecode(b: &[u8]) -> PyStr {
    let mut out = Vec::new();
    let mut rest = b;
    while !rest.is_empty() {
        match std::str::from_utf8(rest) {
            Ok(s) => {
                out.extend(s.chars().map(|c| c as u32));
                break;
            }
            Err(e) => {
                let ok = e.valid_up_to();
                out.extend(std::str::from_utf8(&rest[..ok]).unwrap().chars().map(|c| c as u32));
                out.push(0xDC00 + rest[ok] as u32);
                rest = &rest[ok + 1..];
            }
        }
    }
    out
}

fn pystr(s: &str) -> PyStr {
    s.chars().map(|c| c as u32).collect()
}

/// A JSON value as Python's `json` module holds it (object key order, big integers, lone surrogates).
#[derive(Clone, Debug, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    /// Decimal digits of a Python int (normalised: no `-0`).
    Int(String),
    Float(f64),
    Str(PyStr),
    Array(Vec<Json>),
    Object(Vec<(PyStr, Json)>),
}

struct Parser<'a> {
    s: &'a [char],
    i: usize,
}

impl Parser<'_> {
    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], ' ' | '\t' | '\n' | '\r') {
            self.i += 1;
        }
    }

    fn eat(&mut self, lit: &str) -> bool {
        let n = lit.chars().count();
        if self.s.len() >= self.i + n && self.s[self.i..self.i + n].iter().copied().eq(lit.chars()) {
            self.i += n;
            true
        } else {
            false
        }
    }

    fn value(&mut self) -> Option<Json> {
        let c = *self.s.get(self.i)?;
        match c {
            '{' => {
                self.i += 1;
                let mut items: Vec<(PyStr, Json)> = Vec::new();
                let mut index: HashMap<PyStr, usize> = HashMap::new();
                self.ws();
                if self.eat("}") {
                    return Some(Json::Object(items));
                }
                loop {
                    self.ws();
                    if self.s.get(self.i) != Some(&'"') {
                        return None;
                    }
                    self.i += 1;
                    let k = self.string()?;
                    self.ws();
                    if !self.eat(":") {
                        return None;
                    }
                    self.ws();
                    let v = self.value()?;
                    match index.get(&k) {
                        Some(&j) => items[j].1 = v, // a repeated key keeps its first place, takes the last value
                        None => {
                            index.insert(k.clone(), items.len());
                            items.push((k, v));
                        }
                    }
                    self.ws();
                    if self.eat("}") {
                        return Some(Json::Object(items));
                    }
                    if !self.eat(",") {
                        return None;
                    }
                }
            }
            '[' => {
                self.i += 1;
                let mut items = Vec::new();
                self.ws();
                if self.eat("]") {
                    return Some(Json::Array(items));
                }
                loop {
                    self.ws();
                    items.push(self.value()?);
                    self.ws();
                    if self.eat("]") {
                        return Some(Json::Array(items));
                    }
                    if !self.eat(",") {
                        return None;
                    }
                }
            }
            '"' => {
                self.i += 1;
                self.string().map(Json::Str)
            }
            'n' if self.eat("null") => Some(Json::Null),
            't' if self.eat("true") => Some(Json::Bool(true)),
            'f' if self.eat("false") => Some(Json::Bool(false)),
            'N' if self.eat("NaN") => Some(Json::Float(f64::NAN)),
            'I' if self.eat("Infinity") => Some(Json::Float(f64::INFINITY)),
            '-' if self.eat("-Infinity") => Some(Json::Float(f64::NEG_INFINITY)),
            '-' | '0'..='9' => self.number(),
            _ => None,
        }
    }

    fn digits(&mut self) -> usize {
        let start = self.i;
        while self.i < self.s.len() && self.s[self.i].is_ascii_digit() {
            self.i += 1;
        }
        self.i - start
    }

    fn number(&mut self) -> Option<Json> {
        let start = self.i;
        if self.s[self.i] == '-' {
            self.i += 1;
        }
        let int_start = self.i;
        match self.s.get(self.i) {
            Some('0') => self.i += 1,
            Some('1'..='9') => {
                self.digits();
            }
            _ => return None,
        }
        let int_end = self.i;
        let mut is_float = false;
        if self.s.get(self.i) == Some(&'.') && self.s.get(self.i + 1).is_some_and(|c| c.is_ascii_digit()) {
            self.i += 1;
            self.digits();
            is_float = true;
        }
        if matches!(self.s.get(self.i), Some('e' | 'E')) {
            let save = self.i;
            self.i += 1;
            if matches!(self.s.get(self.i), Some('+' | '-')) {
                self.i += 1;
            }
            if self.digits() == 0 {
                self.i = save;
            } else {
                is_float = true;
            }
        }
        let text: String = self.s[start..self.i].iter().collect();
        if is_float {
            return text.parse().ok().map(Json::Float);
        }
        let digits: String = self.s[int_start..int_end].iter().collect();
        let neg = start != int_start && digits != "0";
        Some(Json::Int(if neg { format!("-{digits}") } else { digits }))
    }

    fn hex4(&mut self) -> Option<u32> {
        let h: String = self.s.get(self.i..self.i + 4)?.iter().collect();
        if !h.chars().all(|c| c.is_ascii_hexdigit()) {
            return None;
        }
        self.i += 4;
        u32::from_str_radix(&h, 16).ok()
    }

    /// The rest of a string after its opening quote.
    fn string(&mut self) -> Option<PyStr> {
        let mut out = Vec::new();
        loop {
            let c = *self.s.get(self.i)?;
            self.i += 1;
            match c {
                '"' => return Some(out),
                '\\' => {
                    let e = *self.s.get(self.i)?;
                    self.i += 1;
                    match e {
                        '"' => out.push('"' as u32),
                        '\\' => out.push('\\' as u32),
                        '/' => out.push('/' as u32),
                        'b' => out.push(8),
                        'f' => out.push(12),
                        'n' => out.push(10),
                        'r' => out.push(13),
                        't' => out.push(9),
                        'u' => {
                            let mut u = self.hex4()?;
                            if (0xD800..0xDC00).contains(&u) && self.s.get(self.i) == Some(&'\\') && self.s.get(self.i + 1) == Some(&'u') {
                                let save = self.i;
                                self.i += 2;
                                match self.hex4() {
                                    Some(l) if (0xDC00..0xE000).contains(&l) => u = 0x10000 + ((u - 0xD800) << 10) + (l - 0xDC00),
                                    _ => self.i = save,
                                }
                            }
                            out.push(u);
                        }
                        _ => return None,
                    }
                }
                c if (c as u32) < 0x20 => return None,
                c => out.push(c as u32),
            }
        }
    }
}

/// `json.loads(text)`; None where Python raises.
pub fn json_loads(text: &str) -> Option<Json> {
    let chars: Vec<char> = text.chars().collect();
    let mut p = Parser { s: &chars, i: 0 };
    p.ws();
    let v = p.value()?;
    p.ws();
    (p.i == chars.len()).then_some(v)
}

fn dump_str(s: &[u32], out: &mut String) {
    out.push('"');
    for &c in s {
        match c {
            0x22 => out.push_str("\\\""),
            0x5C => out.push_str("\\\\"),
            0x0A => out.push_str("\\n"),
            0x0D => out.push_str("\\r"),
            0x09 => out.push_str("\\t"),
            0x08 => out.push_str("\\b"),
            0x0C => out.push_str("\\f"),
            0x20..=0x7E => out.push(char::from_u32(c).unwrap()),
            c if c > 0xFFFF => {
                let v = c - 0x10000;
                out.push_str(&format!("\\u{:04x}\\u{:04x}", 0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF)));
            }
            c => out.push_str(&format!("\\u{c:04x}")),
        }
    }
    out.push('"');
}

/// `json.dumps(value)` (default separators, ensure_ascii); `float_repr` formats a float as `float.__repr__` (with
/// `NaN`, `Infinity`, `-Infinity`).
pub fn json_dumps(v: &Json, float_repr: &dyn Fn(f64) -> String, out: &mut String) {
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Json::Int(d) => out.push_str(d),
        Json::Float(f) => out.push_str(&float_repr(*f)),
        Json::Str(s) => dump_str(s, out),
        Json::Array(items) => {
            out.push('[');
            for (i, x) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                json_dumps(x, float_repr, out);
            }
            out.push(']');
        }
        Json::Object(items) => {
            out.push('{');
            for (i, (k, x)) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                dump_str(k, out);
                out.push_str(": ");
                json_dumps(x, float_repr, out);
            }
            out.push('}');
        }
    }
}

/// The precompile stamps: library directory -> `dir_stamp`, in the file's key order.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Stamps {
    pub items: Vec<(PyStr, Json)>,
}

impl Stamps {
    /// `json.load` of the file; empty when it cannot be read or parsed, or does not hold an object (the Python
    /// original raised AttributeError on a file that held another JSON value).
    pub fn read(path: &Path) -> Stamps {
        let Ok(bytes) = std::fs::read(path) else { return Stamps::default() };
        let Ok(text) = std::str::from_utf8(&bytes) else { return Stamps::default() };
        match json_loads(text) {
            Some(Json::Object(items)) => Stamps { items },
            _ => Stamps::default(),
        }
    }

    pub fn get(&self, key: &[u32]) -> Option<&Json> {
        self.items.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    /// `{**self, **fresh}`.
    pub fn merge(&mut self, fresh: &[(PyStr, String)]) {
        for (k, v) in fresh {
            let v = Json::Str(pystr(v));
            match self.items.iter_mut().find(|(x, _)| x == k) {
                Some(slot) => slot.1 = v,
                None => self.items.push((k.clone(), v)),
            }
        }
    }

    pub fn dumps(&self, float_repr: &dyn Fn(f64) -> String) -> String {
        let mut out = String::new();
        json_dumps(&Json::Object(self.items.clone()), float_repr, &mut out);
        out
    }

    /// Write through `<path>.<pid>.tmp` and a rename; errors are ignored (as `OSError` was).
    pub fn write(&self, path: &Path, float_repr: &dyn Fn(f64) -> String) {
        let mut tmp = path.as_os_str().to_owned();
        tmp.push(format!(".{}.tmp", std::process::id()));
        if std::fs::write(&tmp, self.dumps(float_repr)).is_ok() {
            let _ = std::fs::rename(&tmp, path);
        }
    }
}

/// Which directories the precompile checks, and the stamps to write once it completed.
#[derive(Clone, Debug, PartialEq)]
pub struct PrecompilePlan {
    /// Library directories whose stamp changed (checked without the project's exclusions).
    pub libs: Vec<Vec<u8>>,
    /// The project (always checked).
    pub project: Vec<Vec<u8>>,
    /// The stamps read, updated with every library directory's current stamp.
    pub stamps: Stamps,
}

/// The todo/fresh decision of `precompile`: the project (the directory whose realpath is `rootdir`'s) is always
/// checked; a library directory when its `stamp` differs from the stored one.
pub fn plan_precompile(
    dirs: &[Vec<u8>],
    rootdir: Option<&[u8]>,
    cwd: &[u8],
    stamps_path: &Path,
    mut stamp: impl FnMut(&[u8]) -> String,
) -> PrecompilePlan {
    let mut stamps = Stamps::read(stamps_path);
    let root_real = rootdir.filter(|r| !r.is_empty()).map(|r| realpath(r, cwd));
    let is_root = |d: &[u8]| root_real.as_ref().is_some_and(|r| realpath(d, cwd) == *r);
    let mut todo: Vec<&Vec<u8>> = Vec::new();
    let mut fresh: Vec<(PyStr, String)> = Vec::new();
    for d in dirs {
        if is_root(d) {
            todo.push(d);
            continue;
        }
        let st = stamp(d);
        let key = fsdecode(d);
        let same = matches!(stamps.get(&key), Some(Json::Str(s)) if *s == pystr(&st));
        // a key repeated in `dirs` is written once, with its last stamp (as a dict does)
        fresh.push((key, st));
        if !same {
            todo.push(d);
        }
    }
    let project: Vec<Vec<u8>> = todo.iter().filter(|d| is_root(d)).map(|d| d.to_vec()).collect();
    let libs: Vec<Vec<u8>> = todo.iter().filter(|d| !project.contains(d)).map(|d| d.to_vec()).collect();
    stamps.merge(&fresh);
    PrecompilePlan { libs, project, stamps }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_like_python_int() {
        assert_eq!(parse_hex_int("00040000\n"), Some(0x40000));
        assert_eq!(parse_hex_int("0x_4_0000"), Some(0x40000));
        assert_eq!(parse_hex_int("-1"), Some(u64::MAX));
        assert_eq!(parse_hex_int(""), None);
        assert_eq!(parse_hex_int("0x"), None);
        assert_eq!(parse_hex_int("1__0"), None);
        assert_eq!(parse_hex_int("g"), None);
        assert_eq!(personality_no_randomize("0040000"), Some(true));
        assert_eq!(personality_no_randomize("0000000"), Some(false));
    }

    #[test]
    fn join_like_posixpath() {
        assert_eq!(join(b"a", &[b"b", b"c"]), b"a/b/c");
        assert_eq!(join(b"a/", &[b"/x", b"y"]), b"/x/y");
        assert_eq!(join(b"", &[b"b"]), b"b");
    }

    #[test]
    fn realpath_resolves_links() {
        let t = tempfile::tempdir().unwrap();
        let root = std::fs::canonicalize(t.path()).unwrap();
        let r = root.as_os_str().as_bytes().to_vec();
        std::fs::create_dir(root.join("d")).unwrap();
        std::os::unix::fs::symlink(root.join("d"), root.join("l")).unwrap();
        std::os::unix::fs::symlink("loop", root.join("loop")).unwrap();
        let l = join(&r, &[b"l", b"x", b"..", b"y"]);
        assert_eq!(realpath(&l, b"/"), join(&r, &[b"d", b"y"]));
        assert_eq!(realpath(b"rel/./x", &r), join(&r, &[b"rel", b"x"]));
        assert_eq!(realpath(&join(&r, &[b"loop"]), b"/"), join(&r, &[b"loop"]));
        assert_eq!(realpath(b"/..", b"/"), b"/");
    }

    #[test]
    fn json_round_trip_like_python() {
        let f = |x: f64| format!("{x:?}");
        let v = json_loads(r#" {"b": "xé😀\udce9", "a": [1, -0, 2.5, null, true], "b": "y"} "#).unwrap();
        let mut out = String::new();
        json_dumps(&v, &f, &mut out);
        assert_eq!(out, r#"{"b": "y", "a": [1, 0, 2.5, null, true]}"#);
        let v = json_loads("\"\\ud83d\\ude00\\udce9\"").unwrap();
        let mut out = String::new();
        json_dumps(&v, &f, &mut out);
        assert_eq!(out, "\"\\ud83d\\ude00\\udce9\"");
        assert!(json_loads("{\"a\": 1,}").is_none());
        assert!(json_loads("\u{feff}{}").is_none());
        assert!(json_loads("[1] x").is_none());
        assert_eq!(fsdecode(b"a\xe9"), vec!['a' as u32, 0xDCE9]);
    }
}
