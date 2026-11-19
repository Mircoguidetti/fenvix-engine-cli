//! Data dependency kinds beyond file contents, listings and the existence kind (review r021).
//!
//! Each kind is a digest of exactly what a family of filesystem calls lets the caller see, so that a recorded
//! dependency can be recomputed before a test runs ([`crate::proof::data_now`]):
//!
//! * `m:` metadata a `stat` result shows besides the kind: kind (following links), size and permission bits;
//! * `r:` the path `realpath` resolves to (every link along the way);
//! * `e:` a listing with the type of each entry (`readdir(..., { withFileTypes })`, `opendir`), links not followed;
//! * `t:` a recursive listing (`readdir(..., { recursive })`, globs below a base directory): every path below the
//!   directory with its type, links not followed;
//! * `c:` a copied tree (`cp`): every path below the source with its type, the content of every file and the
//!   target text of every link; links to files or directories are followed (a copy may dereference them).
//!
//! [`import_glob_bases`] reads the base directories of Vite's `import.meta.glob` calls from a module's source.

use crate::fingerprint::digest_bytes;
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

fn push_part(buf: &mut Vec<u8>, part: &[u8]) {
    buf.extend_from_slice(&(part.len() as u64).to_le_bytes());
    buf.extend_from_slice(part);
}

#[cfg(unix)]
fn os_bytes(s: &std::ffi::OsStr) -> Vec<u8> {
    use std::os::unix::ffi::OsStrExt;
    s.as_bytes().to_vec()
}

#[cfg(not(unix))]
fn os_bytes(s: &std::ffi::OsStr) -> Vec<u8> {
    s.to_string_lossy().as_bytes().to_vec()
}

fn type_tag(t: &fs::FileType) -> &'static [u8] {
    if t.is_symlink() {
        b"l"
    } else if t.is_dir() {
        b"d"
    } else if t.is_file() {
        b"f"
    } else {
        b"o"
    }
}

#[cfg(unix)]
fn mode_bits(m: &fs::Metadata) -> u32 {
    use std::os::unix::fs::PermissionsExt;
    m.permissions().mode() & 0o7777
}

#[cfg(not(unix))]
fn mode_bits(m: &fs::Metadata) -> u32 {
    if m.permissions().readonly() {
        0o444
    } else {
        0o666
    }
}

/// `m:` digest: kind (following links), size and permission bits. `None` when the path does not exist.
pub fn stat_meta_digest(path: &Path) -> Option<String> {
    let m = fs::metadata(path).ok()?;
    let kind: &[u8] = if m.is_file() {
        b"file"
    } else if m.is_dir() {
        b"dir"
    } else {
        b"other"
    };
    let mut buf = Vec::new();
    push_part(&mut buf, kind);
    push_part(&mut buf, m.len().to_string().as_bytes());
    push_part(&mut buf, mode_bits(&m).to_string().as_bytes());
    Some(digest_bytes(&buf).short())
}

/// `r:` digest of the canonical path (`realpath`). `None` when it cannot be resolved.
pub fn realpath_digest(path: &Path) -> Option<String> {
    let p = fs::canonicalize(path).ok()?;
    Some(digest_bytes(&os_bytes(p.as_os_str())).short())
}

/// `e:` digest of a listing with entry types (links not followed). `None` when the directory cannot be listed.
pub fn typed_listing_digest(path: &Path) -> Option<String> {
    let mut items: Vec<(Vec<u8>, &'static [u8])> = Vec::new();
    for e in fs::read_dir(path).ok()? {
        let e = e.ok()?;
        let t = e.file_type().ok()?;
        items.push((os_bytes(&e.file_name()), type_tag(&t)));
    }
    items.sort();
    let mut buf = Vec::new();
    for (n, t) in items {
        push_part(&mut buf, &n);
        push_part(&mut buf, t);
    }
    Some(digest_bytes(&buf).short())
}

/// `t:` digest of a recursive listing: every path below `path` with its type, links not followed. `None` when
/// `path` cannot be listed. A subdirectory that cannot be listed is part of the digest as such.
pub fn tree_listing_digest(path: &Path) -> Option<String> {
    fs::read_dir(path).ok()?;
    let mut items: Vec<(Vec<u8>, &'static [u8])> = Vec::new();
    let mut stack: Vec<(PathBuf, Vec<u8>)> = vec![(path.to_path_buf(), Vec::new())];
    while let Some((dir, rel)) = stack.pop() {
        let rd = match fs::read_dir(&dir) {
            Ok(r) => r,
            Err(_) => {
                items.push((rel, b"unlistable"));
                continue;
            }
        };
        for e in rd {
            let Ok(e) = e else {
                items.push((rel.clone(), b"error"));
                continue;
            };
            let mut r = rel.clone();
            if !r.is_empty() {
                r.push(b'/');
            }
            r.extend_from_slice(&os_bytes(&e.file_name()));
            let t = match e.file_type() {
                Ok(t) => t,
                Err(_) => {
                    items.push((r, b"error"));
                    continue;
                }
            };
            let tag = type_tag(&t);
            if t.is_dir() {
                stack.push((e.path(), r.clone()));
            }
            items.push((r, tag));
        }
    }
    items.sort();
    let mut buf = Vec::new();
    for (n, t) in items {
        push_part(&mut buf, &n);
        push_part(&mut buf, t);
    }
    Some(digest_bytes(&buf).short())
}

/// `c:` digest of what a copy of `path` can produce: for a file its content; for a directory every path below it
/// with its type, the content of every file and the target text of every link, following links (cycles cut).
/// `None` when `path` does not exist.
pub fn copy_tree_digest(path: &Path) -> Option<String> {
    fs::symlink_metadata(path).ok()?;
    let mut buf = Vec::new();
    let mut visited = BTreeSet::new();
    copy_walk(path, b"", &mut buf, &mut visited, 0);
    Some(digest_bytes(&buf).short())
}

fn copy_walk(p: &Path, rel: &[u8], buf: &mut Vec<u8>, visited: &mut BTreeSet<PathBuf>, depth: u32) {
    push_part(buf, rel);
    if depth > 64 {
        push_part(buf, b"too-deep");
        return;
    }
    if let Ok(t) = fs::read_link(p) {
        push_part(buf, b"link");
        push_part(buf, &os_bytes(t.as_os_str()));
    }
    let m = match fs::metadata(p) {
        Ok(m) => m,
        Err(_) => {
            push_part(buf, b"dangling");
            return;
        }
    };
    push_part(buf, mode_bits(&m).to_string().as_bytes());
    if m.is_file() {
        push_part(buf, b"file");
        push_part(buf, crate::proof::file_digest(p).unwrap_or_else(|| "unreadable".into()).as_bytes());
        return;
    }
    if !m.is_dir() {
        push_part(buf, b"other");
        return;
    }
    push_part(buf, b"dir");
    let canon = fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
    if !visited.insert(canon.clone()) {
        push_part(buf, b"cycle");
        return;
    }
    let mut names: Vec<std::ffi::OsString> = match fs::read_dir(p) {
        Ok(rd) => rd.filter_map(|e| e.ok().map(|e| e.file_name())).collect(),
        Err(_) => {
            push_part(buf, b"unlistable");
            visited.remove(&canon);
            return;
        }
    };
    names.sort();
    for n in names {
        let mut r = rel.to_vec();
        if !r.is_empty() {
            r.push(b'/');
        }
        r.extend_from_slice(&os_bytes(&n));
        copy_walk(&p.join(&n), &r, buf, visited, depth + 1);
    }
    visited.remove(&canon);
}

/// A base directory of an `import.meta.glob` pattern: `dir` as written in the pattern (`./x`, `../x` relative to
/// the module, `/x` relative to the Vite root), `recursive` when the pattern can match below `dir`'s direct
/// entries (then the key is a `t:` listing, else an `e:` listing).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GlobBase {
    pub dir: String,
    pub recursive: bool,
}

const GLOB_MAGIC: &[char] = &['*', '?', '[', ']', '{', '}', '(', ')', '!', '+', '@'];

fn glob_base(pattern: &str) -> Option<GlobBase> {
    if !(pattern.starts_with("./") || pattern.starts_with("../") || pattern.starts_with('/')) {
        return None; // an alias or a bare pattern: resolved by Vite's configuration, not keyed here
    }
    let segs: Vec<&str> = pattern.split('/').collect();
    let first = segs.iter().position(|s| s.contains(GLOB_MAGIC));
    match first {
        None => {
            // no magic: one path; its directory listing decides whether it matches
            let dir = segs[..segs.len() - 1].join("/");
            Some(GlobBase { dir: if dir.is_empty() { "/".into() } else { dir }, recursive: false })
        }
        Some(i) => {
            let dir = segs[..i].join("/");
            let dir = if dir.is_empty() { "/".into() } else { dir };
            let recursive = i + 1 < segs.len() || segs[i].contains("**");
            Some(GlobBase { dir, recursive })
        }
    }
}

fn skip_ws_and_comments(s: &[u8], mut i: usize) -> usize {
    loop {
        while i < s.len() && (s[i] as char).is_whitespace() {
            i += 1;
        }
        if s[i..].starts_with(b"//") {
            while i < s.len() && s[i] != b'\n' {
                i += 1;
            }
        } else if s[i..].starts_with(b"/*") {
            match s[i + 2..].windows(2).position(|w| w == b"*/") {
                Some(p) => i = i + 2 + p + 2,
                None => return s.len(),
            }
        } else {
            return i;
        }
    }
}

/// A string literal at `i`: (value, index after it). Template literals with substitutions are not literals.
fn string_lit(s: &[u8], i: usize) -> Option<(String, usize)> {
    let q = *s.get(i)?;
    if q != b'\'' && q != b'"' && q != b'`' {
        return None;
    }
    let mut out = Vec::new();
    let mut j = i + 1;
    while j < s.len() {
        let c = s[j];
        if c == q {
            return Some((String::from_utf8(out).ok()?, j + 1));
        }
        if c == b'\\' {
            let n = *s.get(j + 1)?;
            match n {
                b'\\' | b'\'' | b'"' | b'`' | b'/' => out.push(n),
                _ => return None,
            }
            j += 2;
            continue;
        }
        if q == b'`' && c == b'$' && s.get(j + 1) == Some(&b'{') {
            return None;
        }
        if c == b'\n' && q != b'`' {
            return None;
        }
        out.push(c);
        j += 1;
    }
    None
}

/// Index just after the call's closing parenthesis, starting inside it at `i` (strings skipped).
fn call_end(s: &[u8], mut i: usize) -> Option<usize> {
    let mut depth = 1i32;
    while i < s.len() {
        match s[i] {
            b'\'' | b'"' | b'`' => {
                let (_, j) = string_lit(s, i)?;
                i = j;
                continue;
            }
            b'(' | b'[' | b'{' => depth += 1,
            b')' | b']' | b'}' => {
                depth -= 1;
                if depth == 0 {
                    return if s[i] == b')' { Some(i + 1) } else { None };
                }
            }
            _ => {}
        }
        i += 1;
    }
    None
}

/// Base directories of every `import.meta.glob` call in `source`. `Some(vec![])` when there is none; `None` when a
/// call cannot be read soundly (a pattern that is not a string literal, an alias or bare pattern, a `base`
/// option): the caller must then treat the module's glob results as not keyed.
pub fn import_glob_bases(source: &[u8]) -> Option<Vec<GlobBase>> {
    const NEEDLE: &[u8] = b"import.meta.glob";
    let mut out = Vec::new();
    let mut from = 0;
    while let Some(p) = source[from..].windows(NEEDLE.len()).position(|w| w == NEEDLE) {
        let at = from + p;
        let mut i = at + NEEDLE.len();
        from = i;
        if source[i..].starts_with(b"Eager") {
            i += 5;
        }
        if i < source.len() && (source[i].is_ascii_alphanumeric() || source[i] == b'_' || source[i] == b'$') {
            continue; // another identifier (import.meta.globals)
        }
        i = skip_ws_and_comments(source, i);
        if source.get(i) == Some(&b'<') {
            // TypeScript type arguments
            let mut d = 0i32;
            while i < source.len() {
                match source[i] {
                    b'<' => d += 1,
                    b'>' => {
                        d -= 1;
                        if d == 0 {
                            i += 1;
                            break;
                        }
                    }
                    _ => {}
                }
                i += 1;
            }
            i = skip_ws_and_comments(source, i);
        }
        if source.get(i) != Some(&b'(') {
            return None;
        }
        let open = i + 1;
        let end = call_end(source, open)?;
        i = skip_ws_and_comments(source, open);
        let mut patterns = Vec::new();
        if source.get(i) == Some(&b'[') {
            i += 1;
            loop {
                i = skip_ws_and_comments(source, i);
                if source.get(i) == Some(&b']') {
                    i += 1;
                    break;
                }
                let (v, j) = string_lit(source, i)?;
                patterns.push(v);
                i = skip_ws_and_comments(source, j);
                match source.get(i) {
                    Some(b',') => i += 1,
                    Some(b']') => {
                        i += 1;
                        break;
                    }
                    _ => return None,
                }
            }
        } else {
            let (v, j) = string_lit(source, i)?;
            patterns.push(v);
            i = j;
        }
        // options: a `base` changes what the patterns are relative to
        let rest = &source[i..end];
        if rest.windows(4).enumerate().any(|(k, w)| {
            w == b"base"
                && (k == 0 || !(rest[k - 1].is_ascii_alphanumeric() || rest[k - 1] == b'_'))
                && rest.get(k + 4).map_or(true, |c| !(c.is_ascii_alphanumeric() || *c == b'_'))
        }) {
            return None;
        }
        for pat in patterns {
            if let Some(neg) = pat.strip_prefix('!') {
                let _ = neg; // exclusions only remove matches of the other patterns
                continue;
            }
            out.push(glob_base(&pat)?);
        }
        from = end;
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn meta_size_mode() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("a");
        fs::write(&p, "abc").unwrap();
        let a = stat_meta_digest(&p).unwrap();
        fs::write(&p, "xyz").unwrap();
        assert_eq!(stat_meta_digest(&p).unwrap(), a, "same size, same mode");
        fs::write(&p, "abcd").unwrap();
        assert_ne!(stat_meta_digest(&p).unwrap(), a);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::write(&p, "abc").unwrap();
            fs::set_permissions(&p, fs::Permissions::from_mode(0o600)).unwrap();
            let b = stat_meta_digest(&p).unwrap();
            fs::set_permissions(&p, fs::Permissions::from_mode(0o644)).unwrap();
            assert_ne!(stat_meta_digest(&p).unwrap(), b);
        }
        assert_eq!(stat_meta_digest(&d.path().join("none")), None);
    }

    #[cfg(unix)]
    #[test]
    fn realpath_follows_retargeted_link() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join("one"), "1").unwrap();
        fs::write(d.path().join("two"), "2").unwrap();
        let l = d.path().join("cur");
        std::os::unix::fs::symlink("one", &l).unwrap();
        let a = realpath_digest(&l).unwrap();
        fs::remove_file(&l).unwrap();
        std::os::unix::fs::symlink("two", &l).unwrap();
        assert_ne!(realpath_digest(&l).unwrap(), a);
    }

    #[test]
    fn typed_listing_sees_type_changes() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join("item"), "x").unwrap();
        let a = typed_listing_digest(d.path()).unwrap();
        let b = crate::proof::listing_digest(d.path()).unwrap();
        fs::remove_file(d.path().join("item")).unwrap();
        fs::create_dir(d.path().join("item")).unwrap();
        assert_eq!(crate::proof::listing_digest(d.path()).unwrap(), b, "names alone do not change");
        assert_ne!(typed_listing_digest(d.path()).unwrap(), a);
    }

    #[test]
    fn tree_listing_sees_nested_files() {
        let d = tempfile::tempdir().unwrap();
        fs::create_dir_all(d.path().join("a")).unwrap();
        fs::write(d.path().join("a/one.json"), "{}").unwrap();
        let a = tree_listing_digest(d.path()).unwrap();
        fs::write(d.path().join("a/one.json"), "{\"changed\":1}").unwrap();
        assert_eq!(tree_listing_digest(d.path()).unwrap(), a, "contents are not part of a listing");
        fs::write(d.path().join("a/two.json"), "{}").unwrap();
        assert_ne!(tree_listing_digest(d.path()).unwrap(), a);
        assert_eq!(tree_listing_digest(&d.path().join("none")), None);
    }

    #[test]
    fn copy_tree_sees_contents() {
        let d = tempfile::tempdir().unwrap();
        fs::create_dir_all(d.path().join("tpl/sub")).unwrap();
        fs::write(d.path().join("tpl/sub/config.json"), "{\"v\":1}").unwrap();
        let a = copy_tree_digest(&d.path().join("tpl")).unwrap();
        fs::write(d.path().join("tpl/sub/config.json"), "{\"v\":2}").unwrap();
        assert_ne!(copy_tree_digest(&d.path().join("tpl")).unwrap(), a);
        #[cfg(unix)]
        {
            let b = copy_tree_digest(&d.path().join("tpl")).unwrap();
            std::os::unix::fs::symlink("..", d.path().join("tpl/sub/up")).unwrap();
            let c = copy_tree_digest(&d.path().join("tpl")).unwrap(); // cycle is cut
            assert_ne!(c, b);
        }
        let f = d.path().join("file.txt");
        fs::write(&f, "a").unwrap();
        let x = copy_tree_digest(&f).unwrap();
        fs::write(&f, "b").unwrap();
        assert_ne!(copy_tree_digest(&f).unwrap(), x);
    }

    #[test]
    fn import_glob_bases_read() {
        let g = |s: &str| import_glob_bases(s.as_bytes());
        assert_eq!(g("const x = 1;"), Some(vec![]));
        assert_eq!(
            g("const c = import.meta.glob('../fixtures/cases/*.json', { eager: true });"),
            Some(vec![GlobBase { dir: "../fixtures/cases".into(), recursive: false }])
        );
        assert_eq!(
            g("import.meta.glob(['./a/**/*.ts', '!./a/skip/*.ts', \"/src/*/x.js\"])"),
            Some(vec![
                GlobBase { dir: "./a".into(), recursive: true },
                GlobBase { dir: "/src".into(), recursive: true }
            ])
        );
        assert_eq!(g("import.meta.glob<Record<string, string>>('./x/*.md', { query: '?raw' })").map(|v| v.len()), Some(1));
        assert_eq!(g("import.meta.globEager('./*.js')").map(|v| v.len()), Some(1));
        assert_eq!(g("import.meta.glob('@/pages/*.vue')"), None, "alias");
        assert_eq!(g("import.meta.glob(pattern)"), None, "not a literal");
        assert_eq!(g("import.meta.glob(`./${d}/*.js`)"), None, "substitution");
        assert_eq!(g("import.meta.glob('./*.js', { base: './src' })"), None, "base option");
        assert_eq!(g("import.meta.glob('./*.js', { eager: true, import: 'default' })").map(|v| v.len()), Some(1));
    }
}
