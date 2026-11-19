//! Skip with proof for the JVM shell: the decider.
//!
//! A base run (A) is a test run with the skip-with-proof capture on (`fenvix-jvm run --deps`):
//! every test JVM writes `<out>/deps/<module>-<pid>.jsonl`, one record per test (in execution
//! order), per class container, per JVM session scope, and one `jvm` record (class table with
//! digests, runtime identity, configuration, every environment variable and system property
//! digest, class path).
//!
//! A test of A is REUSABLE in the current state (B) when all of these hold:
//!
//! * it passed in A and wrote no file it could read back; it made no external network
//!   attempt, started no child process and ran no native code of the project (inputs the
//!   capture cannot see: never reusable);
//! * every class whose code it executed, whose static fields it accessed, whose static
//!   initialiser it depended on or whose reflective metadata it read has the same class-file
//!   digest now (B's class table, else B's class path; missing = changed);
//! * every class it looked up by name is still found, or still not found;
//! * every file it read has the same content, every path it probed the same existence state,
//!   every directory it listed the same names; every classpath resource it looked up resolves
//!   to the same location and content now, or is still absent; every `getResources` lookup
//!   returns the same locations in the same order;
//! * every environment variable and system property it read has the same value;
//! * the same runtime identity and configuration (JUnit configuration parameters included) as
//!   its JVM in B;
//! * shared state: if it (or its class scope) read static state another test could have changed
//!   (`mut`: a non-final static field, or a final one holding a mutable object), every test that
//!   runs before it in its JVM in B is either reused (it behaves as in A) or, rerun or new, touched
//!   no shared static state when it ran in B; and the state-touching tests before it are the same,
//!   in the same order, as in A. When its class shares one test instance (JUnit PER_CLASS, TestNG),
//!   every earlier test of the class is reused, in the same order. Every test it depends on through
//!   static fields written earlier in A is reused.
//!
//! The decision for a test is taken at its position in B's order: the tests before it have run
//! already, and the captures of those rerun are B's. B is described by its own capture (the
//! measurement runs every test, so every reuse is checked against the fresh outcome).

use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader, Read};
use std::path::{Component, Path, PathBuf};

/// Short (128-bit) BLAKE3 hex digest, as the Java runtime writes it.
pub fn short(data: &[u8]) -> String {
    detpy_core::fingerprint::hex(&blake3::hash(data).as_bytes()[..16])
}

pub fn digest_file(path: &Path) -> Option<String> {
    let mut f = File::open(path).ok()?;
    let mut h = blake3::Hasher::new();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        let n = f.read(&mut buf).ok()?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Some(detpy_core::fingerprint::hex(&h.finalize().as_bytes()[..16]))
}

/// One test JVM (one deps file).
#[derive(Debug, Default)]
pub struct Jvm {
    pub record: Option<Value>,
    /// test ids (with the per-module JVM suffix) in execution order
    pub order: Vec<String>,
    /// container / session scopes of this JVM
    pub scopes: HashMap<String, Value>,
}

#[derive(Debug)]
pub struct Test {
    pub rec: Value,
    pub jvm: usize,
    pub pos: usize,
}

#[derive(Debug, Default)]
pub struct Module {
    pub jvms: Vec<Jvm>,
    pub tests: BTreeMap<String, Test>,
}

pub type Mods = BTreeMap<String, Module>;

fn pid_of(p: &Path) -> i64 {
    let b = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
    b.rsplit_once('-').and_then(|(_, r)| r.split('.').next()).and_then(|x| x.parse().ok()).unwrap_or(0)
}

fn prefix_of(p: &Path) -> String {
    let b = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
    b.rsplit_once('-').map(|(l, _)| l.to_string()).unwrap_or_default()
}

/// Load a deps directory. A test run by several JVMs of one module (several Surefire executions)
/// gets the suffix "#n" for its n-th JVM after the first (JVMs in start order, by pid).
pub fn load(dir: &Path) -> std::io::Result<Mods> {
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir)?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().map(|x| x == "jsonl").unwrap_or(false))
        .collect();
    files.sort_by_key(|p| (prefix_of(p), pid_of(p)));
    let mut mods: Mods = BTreeMap::new();
    let mut seen: HashMap<(String, String), usize> = HashMap::new();
    for f in files {
        let recs: Vec<Value> = BufReader::new(File::open(&f)?)
            .lines()
            .map_while(Result::ok)
            .filter(|l| !l.trim().is_empty())
            .filter_map(|l| serde_json::from_str(&l).ok())
            .collect();
        // one Jvm per file and module
        let mut idx: HashMap<String, usize> = HashMap::new();
        for r in recs {
            let module = r.get("module").and_then(Value::as_str).unwrap_or("").to_string();
            let m = mods.entry(module.clone()).or_default();
            let ji = *idx.entry(module.clone()).or_insert_with(|| {
                m.jvms.push(Jvm::default());
                m.jvms.len() - 1
            });
            let ty = r.get("type").and_then(Value::as_str).unwrap_or("");
            match ty {
                "jvm" => m.jvms[ji].record = Some(r),
                "test" => {
                    let mut r = r;
                    let id = r["id"].as_str().unwrap_or("").to_string();
                    let n = seen.entry((module.clone(), id.clone())).or_insert(0);
                    *n += 1;
                    let id = if *n > 1 {
                        let suffix = format!("#{}", n);
                        let after: Vec<Value> = r
                            .get("after")
                            .and_then(Value::as_array)
                            .map(|a| a.iter().filter_map(Value::as_str).map(|x| Value::String(format!("{}{}", x, suffix))).collect())
                            .unwrap_or_default();
                        r["after"] = Value::Array(after);
                        let nid = format!("{}{}", id, suffix);
                        r["id"] = Value::String(nid.clone());
                        nid
                    } else {
                        id
                    };
                    let pos = m.jvms[ji].order.len();
                    m.jvms[ji].order.push(id.clone());
                    m.tests.insert(id, Test { rec: r, jvm: ji, pos });
                }
                _ => {
                    let id = r["id"].as_str().unwrap_or("").to_string();
                    m.jvms[ji].scopes.insert(id, r);
                }
            }
        }
    }
    Ok(mods)
}

fn strs(v: &Value, k: &str) -> Vec<String> {
    v.get(k).and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default()
}

fn obj<'a>(v: &'a Value, k: &str) -> Option<&'a serde_json::Map<String, Value>> {
    v.get(k).and_then(Value::as_object)
}

fn flag(v: &Value, k: &str) -> bool {
    v.get(k).and_then(Value::as_bool).unwrap_or(false)
}

/// Lexical normalisation (`.` and `..`), as java.nio.file.Path.normalize.
fn normalize(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// The current state B: its capture plus the file system at `root`.
pub struct State<'a> {
    pub mods: &'a Mods,
    pub root: PathBuf,
    file: HashMap<PathBuf, String>,
    classes: HashMap<(String, usize, String), Option<String>>,
    jars: HashMap<String, Option<zip::ZipArchive<File>>>,
}

impl<'a> State<'a> {
    pub fn new(mods: &'a Mods, root: &Path) -> Self {
        let root = normalize(&std::path::absolute(root).unwrap_or_else(|_| root.to_path_buf()));
        State { mods, root, file: HashMap::new(), classes: HashMap::new(), jars: HashMap::new() }
    }

    /// The JVM (index) of module that ran `test_id` in B, else its first JVM with a record.
    pub fn jvm_index(&self, module: &str, test_id: Option<&str>) -> Option<usize> {
        let m = self.mods.get(module)?;
        if let Some(t) = test_id.and_then(|t| m.tests.get(t)) {
            if m.jvms[t.jvm].record.is_some() {
                return Some(t.jvm);
            }
        }
        m.jvms.iter().position(|j| j.record.is_some())
    }

    pub fn jvm(&self, module: &str, test_id: Option<&str>) -> Option<&'a Value> {
        let i = self.jvm_index(module, test_id)?;
        self.mods.get(module)?.jvms[i].record.as_ref()
    }

    pub fn path(&self, key: &str) -> Option<PathBuf> {
        if let Some(r) = key.strip_prefix("root:") {
            return Some(if r == "." { self.root.clone() } else { self.root.join(r) });
        }
        if let Some(r) = key.strip_prefix("abs:").or_else(|| key.strip_prefix("sys:")) {
            return Some(PathBuf::from(r));
        }
        None
    }

    /// Location key of a path, in the vocabulary of the Java runtime (Deps.norm).
    pub fn norm(&self, p: &Path) -> String {
        let p = normalize(p);
        if p == self.root {
            return "root:.".into();
        }
        if let Ok(rel) = p.strip_prefix(&self.root) {
            return format!("root:{}", rel.to_string_lossy());
        }
        let s = p.to_string_lossy();
        if s.starts_with("/proc/") || s.starts_with("/dev/") || s.starts_with("/sys/") {
            return format!("sys:{}", s);
        }
        format!("abs:{}", s)
    }

    pub fn file_state(&mut self, p: &Path) -> String {
        if let Some(s) = self.file.get(p) {
            return s.clone();
        }
        let s = match std::fs::metadata(p) {
            Err(_) => "absent".to_string(),
            Ok(m) if m.is_dir() => "dir".to_string(),
            Ok(_) => format!("file:{}", digest_file(p).unwrap_or_else(|| "unreadable".into())),
        };
        self.file.insert(p.to_path_buf(), s.clone());
        s
    }

    /// Current value of a files[] entry, in the recorded vocabulary.
    pub fn entry(&mut self, key: &str, value: &str) -> Option<String> {
        if key.ends_with('/') && value.starts_with("list:") {
            let p = self.path(&key[..key.len() - 1])?;
            let mut names: Vec<String> = match std::fs::read_dir(&p) {
                Ok(rd) => rd.filter_map(|e| e.ok().map(|e| e.file_name().to_string_lossy().into_owned())).collect(),
                Err(_) => return Some("list:absent".into()),
            };
            names.sort();
            let joined: String = names.iter().map(|n| format!("{}\n", n)).collect();
            return Some(format!("list:{}", short(joined.as_bytes())));
        }
        let p = self.path(key)?;
        let st = self.file_state(&p);
        if value.starts_with("probe:") {
            let k = if st == "absent" { "absent" } else if st == "dir" { "dir" } else { "file" };
            return Some(format!("probe:{}", k));
        }
        if value.starts_with("read:") {
            return Some(format!("read:{}", st));
        }
        Some(value.to_string())
    }

    fn jar(&mut self, path: &str) -> Option<&mut zip::ZipArchive<File>> {
        if !self.jars.contains_key(path) {
            let z = File::open(path).ok().and_then(|f| zip::ZipArchive::new(f).ok());
            self.jars.insert(path.to_string(), z);
        }
        self.jars.get_mut(path).and_then(|z| z.as_mut())
    }

    fn classpath(&self, module: &str, test_id: Option<&str>) -> Vec<String> {
        self.jvm(module, test_id).map(|j| strs(j, "classpath")).unwrap_or_default()
    }

    /// Digest of a class (internal name) in B: B's class table, else B's class path; None = missing.
    pub fn class_digest(&mut self, module: &str, name: &str, test_id: Option<&str>) -> Option<String> {
        let ji = self.jvm_index(module, test_id)?;
        let jvm = self.mods.get(module)?.jvms[ji].record.as_ref()?;
        if let Some(d) = jvm.get("classes").and_then(|c| c.get(name)).and_then(Value::as_str) {
            return Some(d.split(' ').next().unwrap_or("").to_string());
        }
        let key = (module.to_string(), ji, name.to_string());
        if let Some(d) = self.classes.get(&key) {
            return d.clone();
        }
        let file = format!("{}.class", name);
        let mut d = None;
        for entry in strs(jvm, "classpath") {
            if entry.ends_with(".jar") {
                if let Some(z) = self.jar(&entry) {
                    if let Ok(mut f) = z.by_name(&file) {
                        let mut b = Vec::new();
                        if f.read_to_end(&mut b).is_ok() {
                            d = Some(short(&b));
                            break;
                        }
                    }
                }
            } else {
                let p = Path::new(&entry).join(&file);
                if p.is_file() {
                    d = digest_file(&p);
                    break;
                }
            }
        }
        self.classes.insert(key, d.clone());
        d
    }

    /// Every location of a classpath resource in B, in class path order (`loc@state`).
    pub fn resource_locations(&mut self, module: &str, name: &str, test_id: Option<&str>, first_only: bool) -> Vec<String> {
        let cp = self.classpath(module, test_id);
        self.locations(&cp, name, first_only)
    }

    /// Same, over the class path of a given `jvm` record.
    pub fn resource_locations_for(&mut self, jvm: &Value, name: &str, first_only: bool) -> Vec<String> {
        let cp = strs(jvm, "classpath");
        self.locations(&cp, name, first_only)
    }

    fn locations(&mut self, cp: &[String], name: &str, first_only: bool) -> Vec<String> {
        let mut out = Vec::new();
        for entry in cp.iter().cloned() {
            if entry.ends_with(".jar") {
                let found = self.jar(&entry).map(|z| z.by_name(name).is_ok()).unwrap_or(false);
                if found {
                    let jp = PathBuf::from(&entry);
                    let st = self.file_state(&jp);
                    out.push(format!("jar:{}!/{}@{}", self.norm(&jp), name, st));
                }
            } else {
                let p = Path::new(&entry).join(name);
                if p.exists() {
                    let st = self.file_state(&p);
                    out.push(format!("{}@{}", self.norm(&p), st));
                }
            }
            if first_only && !out.is_empty() {
                break;
            }
        }
        out
    }
}

/// The scopes of a test in its JVM of A (container chain, session).
fn chain<'m>(m: &'m Module, t: &'m Test) -> Vec<&'m Value> {
    let mut out = vec![&t.rec];
    for sid in strs(&t.rec, "scopes") {
        if let Some(s) = m.jvms[t.jvm].scopes.get(&sid) {
            out.push(s);
        }
    }
    out
}

fn runtime_of(j: &Value) -> BTreeMap<String, String> {
    obj(j, "runtime")
        .map(|o| {
            o.iter()
                .filter(|(k, _)| k.as_str() != "prop:user.timezone") // set lazily: compared through "tz"
                .map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string()))
                .collect()
        })
        .unwrap_or_default()
}

fn map_of(j: &Value, k: &str) -> BTreeMap<String, String> {
    obj(j, k).map(|o| o.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string())).collect()).unwrap_or_default()
}

fn first_diff(a: &BTreeMap<String, String>, b: &BTreeMap<String, String>) -> String {
    let mut keys: Vec<&String> = a.keys().chain(b.keys()).collect();
    keys.sort();
    keys.dedup();
    keys.into_iter().filter(|k| a.get(*k) != b.get(*k)).take(3).cloned().collect::<Vec<_>>().join(",")
}

pub type Reason = Option<(String, String)>;

fn why(code: &str, detail: impl Into<String>) -> Reason {
    Some((code.to_string(), detail.into()))
}

/// None if the test passed in A and its own key is unchanged, else the first reason.
pub fn why_not(module: &str, m: &Module, t: &Test, b: &mut State) -> Reason {
    let rec = &t.rec;
    if rec.get("outcome").and_then(Value::as_str) != Some("passed") {
        return why("not-passed", rec.get("outcome").and_then(Value::as_str).unwrap_or("none"));
    }
    key_changed(module, m, t, b)
}

/// None if the test's own key (everything but its outcome) is unchanged, else the first reason.
pub fn key_changed(module: &str, m: &Module, t: &Test, b: &mut State) -> Reason {
    let rec = &t.rec;
    let id = rec["id"].as_str().unwrap_or("");
    let ja = match m.jvms[t.jvm].record.as_ref() {
        Some(j) => j,
        None => return why("no-jvm-record", module),
    };
    let jb = match b.jvm(module, Some(id)) {
        Some(j) => j,
        None => return why("no-jvm-record", module),
    };
    let (ra, rb) = (runtime_of(ja), runtime_of(jb));
    if ra != rb {
        return why("runtime", first_diff(&ra, &rb));
    }
    let (ca, cb) = (map_of(ja, "config"), map_of(jb, "config"));
    if ca != cb {
        return why("config", first_diff(&ca, &cb));
    }
    let env_b = map_of(jb, "env_all");
    let props_b = map_of(jb, "props_all");
    for s in chain(m, t) {
        if flag(s, "written") {
            return why("writes", s["id"].as_str().unwrap_or(""));
        }
        // a network attempt the shell let through: its result is an input the capture cannot see.
        // (Attempts blocked by --det are refused the same way in every run: such a test is never
        // reused either, see decide(), but it leaves the same state behind.)
        if let Some(n) = strs(s, "net").iter().find(|n| !n.ends_with(":blocked")) {
            return why("network", n.clone());
        }
        if let Some(p) = strs(s, "proc").first() {
            return why("process", p.clone());
        }
        if let Some(n) = strs(s, "native").first() {
            return why("native", n.clone());
        }
        let classes_a = obj(ja, "classes");
        for name in strs(s, "classes") {
            let da = match classes_a.and_then(|c| c.get(&name)).and_then(Value::as_str) {
                Some(d) => d.split(' ').next().unwrap_or("").to_string(),
                None => continue, // generated at run time (no code source)
            };
            if b.class_digest(module, &name, Some(id)).as_deref() != Some(da.as_str()) {
                return why("code", name);
            }
        }
        if let Some(lk) = obj(s, "lookups") {
            for (name, st) in lk {
                let present = b.class_digest(module, name, Some(id)).is_some();
                let now = if present { "present" } else { "absent" };
                if st.as_str() != Some(now) {
                    return why("class-lookup", name.clone());
                }
            }
        }
        if let Some(files) = obj(s, "files") {
            for (k, v) in files {
                let v = v.as_str().unwrap_or("");
                if v == "write" {
                    return why("writes", k.clone());
                }
                if let Some(now) = b.entry(k, v) {
                    if now != v {
                        return why("file", k.clone());
                    }
                }
            }
        }
        for r in strs(s, "resources") {
            let (name, loc) = match r.split_once('=') {
                Some(x) => x,
                None => continue,
            };
            if loc == "?" {
                // looked up through a class loader other than the class path's: not keyable
                return why("resource-loader", name);
            }
            if let Some(all) = loc.strip_prefix("all:") {
                let now = b.resource_locations(module, name, Some(id), false).join("|");
                if now != all {
                    return why("resource", name);
                }
                continue;
            }
            let now = b.resource_locations(module, name, Some(id), true);
            let now = now.first().map(String::as_str).unwrap_or("absent");
            if loc == "absent" || loc.contains('@') {
                if now != loc {
                    return why("resource", name);
                }
            } else {
                // a URL the capture could not place (another protocol): not keyable
                return why("resource-loader", name);
            }
        }
        if let Some(env) = obj(s, "env") {
            for (k, v) in env {
                if k == "*" {
                    if map_of(ja, "env_all") != env_b {
                        return why("env", "*");
                    }
                    continue;
                }
                if env_b.get(k).map(String::as_str).unwrap_or("unset") != v.as_str().unwrap_or("") {
                    return why("env", k.clone());
                }
            }
        }
        if let Some(props) = obj(s, "props") {
            // properties no test writes: the value read is the value at JVM start; properties tests
            // write are shared state (the order rule decides), their start values must match
            let written = props_written(ja, jb);
            let start_a = props_start(ja);
            let start_b = props_start(jb);
            let _ = &props_b;
            for (k, v) in props {
                if k == "*" {
                    let fa: BTreeMap<_, _> = start_a.iter().filter(|(x, _)| !x.starts_with("fenvix.")).collect();
                    let fb: BTreeMap<_, _> = start_b.iter().filter(|(x, _)| !x.starts_with("fenvix.")).collect();
                    if fa != fb {
                        return why("prop", "*");
                    }
                    continue;
                }
                if written.contains(k) || written.contains("*") {
                    if start_a.get(k) != start_b.get(k) {
                        return why("prop", k.clone());
                    }
                    continue;
                }
                if start_b.get(k).map(String::as_str).unwrap_or("unset") != v.as_str().unwrap_or("") {
                    return why("prop", k.clone());
                }
            }
        }
    }
    None
}

/// System properties written by tests in either JVM ("*": all of them).
fn props_written(ja: &Value, jb: &Value) -> HashSet<String> {
    strs(ja, "props_written").into_iter().chain(strs(jb, "props_written")).collect()
}

/// Properties at JVM start (captures without it: at JVM end).
fn props_start(j: &Value) -> BTreeMap<String, String> {
    if j.get("props_start").is_some() {
        map_of(j, "props_start")
    } else {
        map_of(j, "props_all")
    }
}

/// A scope chain read static state another test could have changed (session scope excluded):
/// a mutable static, or a system property some test writes.
fn reads_shared(m: &Module, t: &Test, written: &HashSet<String>) -> bool {
    chain(m, t).iter().any(|s| {
        s.get("type").and_then(Value::as_str) != Some("session")
            && (flag(s, "mut")
                || (!written.is_empty() && obj(s, "props").map(|p| p.keys().any(|k| k == "*" || written.contains(k) || written.contains("*"))).unwrap_or(false)))
    })
}

/// A test that left (or may have left) state behind: it read a mutable static or wrote a static.
fn touches_shared(m: &Module, t: &Test) -> bool {
    chain(m, t).iter().any(|s| s.get("type").and_then(Value::as_str) != Some("session") && (flag(s, "mut") || flag(s, "swrite")))
}

/// Containers of a test whose tests share one test instance (old captures without the flag: shared).
fn shared_containers(m: &Module, t: &Test) -> Vec<String> {
    strs(&t.rec, "scopes")
        .into_iter()
        .filter(|sid| match m.jvms[t.jvm].scopes.get(sid) {
            Some(s) => s.get("type").and_then(Value::as_str) == Some("container") && s.get("shared").and_then(Value::as_bool).unwrap_or(true),
            None => sid != "<session>",
        })
        .collect()
}

fn in_container(m: &Module, e: &str, c: &str) -> bool {
    m.tests.get(e).map(|t| strs(&t.rec, "scopes").iter().any(|x| x == c)).unwrap_or(false)
}

pub type Decisions = BTreeMap<(String, String), Reason>;

/// {(module, id): None (reusable) or (reason, detail)} for every test of A.
///
/// A test of A that failed, or that made a network attempt the shell blocked, is never reused, but
/// when its key is unchanged it runs exactly as in A (deterministic execution), so it leaves the
/// same state behind: for the tests after it, it
/// counts as unchanged ("clean"). A test whose key changed, a new test, or a test that depends on
/// such a test is not clean.
pub fn decide(mods_a: &Mods, b: &mut State) -> Decisions {
    let mut clean: Decisions = BTreeMap::new();
    for (mn, m) in mods_a {
        for (tid, t) in &m.tests {
            clean.insert((mn.clone(), tid.clone()), key_changed(mn, m, t, b));
        }
    }
    let mods_b = b.mods;
    loop {
        let mut changed = false;
        for (mn, m) in mods_a {
            let mb = mods_b.get(mn);
            for (tid, t) in &m.tests {
                if clean[&(mn.clone(), tid.clone())].is_some() {
                    continue;
                }
                let r = order_reason(mn, m, mb, tid, t, &clean);
                if r.is_some() {
                    clean.insert((mn.clone(), tid.clone()), r);
                    changed = true;
                }
            }
        }
        if !changed {
            break;
        }
    }
    let mut fin = clean;
    for (mn, m) in mods_a {
        for (tid, t) in &m.tests {
            if fin[&(mn.clone(), tid.clone())].is_some() {
                continue;
            }
            if t.rec.get("outcome").and_then(Value::as_str) != Some("passed") {
                let o = t.rec.get("outcome").and_then(Value::as_str).unwrap_or("none").to_string();
                fin.insert((mn.clone(), tid.clone()), why("not-passed", o));
                continue;
            }
            if let Some(n) = chain(m, t).iter().flat_map(|s| strs(s, "net")).next() {
                fin.insert((mn.clone(), tid.clone()), why("network", n));
            }
        }
    }
    fin
}

/// Dependencies through shared state and order (None when there is none that blocks reuse).
fn order_reason(mn: &str, m: &Module, mb: Option<&Module>, tid: &str, t: &Test, fin: &Decisions) -> Reason {
    // static fields written by earlier tests of A (transitive)
    for dep in strs(&t.rec, "after") {
        match fin.get(&(mn.to_string(), dep.clone())) {
            Some(None) => {}
            _ => return why("after", dep),
        }
    }
    let mb = match mb {
        Some(x) => x,
        None => return None,
    };
    let tb = match mb.tests.get(tid) {
        Some(x) => x,
        None => return None, // not run in B: nothing to reuse
    };
    let prefix_b: Vec<&String> = mb.jvms[tb.jvm].order[..tb.pos].iter().collect();
    let prefix_a: Vec<&String> = m.jvms[t.jvm].order[..t.pos].iter().collect();
    let reusable = |e: &str| matches!(fin.get(&(mn.to_string(), e.to_string())), Some(None));
    // tests of a class whose test instance is shared (JUnit PER_CLASS, TestNG): every earlier test of
    // that class reused, in the same order (instance fields are not part of the capture)
    for c in shared_containers(m, t) {
        let same_b: Vec<&String> = prefix_b.iter().copied().filter(|e| in_container(mb, e, &c)).collect();
        let same_a: Vec<&String> = prefix_a.iter().copied().filter(|e| in_container(m, e, &c)).collect();
        for e in &same_b {
            if !m.tests.contains_key(*e) {
                return why("after-new", (*e).clone());
            }
            if !reusable(e) {
                return why("after", (*e).clone());
            }
        }
        if same_a != same_b {
            return why("order", c);
        }
    }
    let written = match (m.jvms[t.jvm].record.as_ref(), mb.jvms[tb.jvm].record.as_ref()) {
        (Some(ja), Some(jb)) => props_written(ja, jb),
        _ => HashSet::new(),
    };
    if reads_shared(m, t, &written) {
        // The decision is taken at the test's position, after the tests before it have run: a test
        // rerun (or new) before it either touched no shared static state when it ran in B (its
        // capture says so), or it may have left other state behind. Reused tests behave as in A.
        let mut eff_b: Vec<&String> = Vec::new();
        for e in &prefix_b {
            let clean = m.tests.contains_key(*e) && reusable(e);
            if clean {
                if m.tests.get(*e).map(|x| touches_shared(m, x)).unwrap_or(true) {
                    eff_b.push(*e);
                }
                continue;
            }
            let touched_now = mb.tests.get(*e).map(|x| touches_shared(mb, x)).unwrap_or(true);
            if touched_now {
                let code = if m.tests.contains_key(*e) { "after" } else { "after-new" };
                return why(code, (*e).clone());
            }
        }
        // the state-touching tests before it in A: the same ones, reused, in the same order
        let eff_a: Vec<&String> = prefix_a.iter().copied().filter(|e| m.tests.get(*e).map(|x| touches_shared(m, x)).unwrap_or(true)).collect();
        if eff_a != eff_b {
            let d = eff_a.iter().zip(eff_b.iter()).find(|(x, y)| x != y).map(|(x, _)| (*x).clone());
            let d = d.or_else(|| eff_a.get(eff_b.len()).map(|x| (*x).clone())).or_else(|| eff_b.get(eff_a.len()).map(|x| (*x).clone()));
            return why("order", d.unwrap_or_default());
        }
    }
    None
}

/// Decide from two deps directories; JSON rows as the Python wrapper expects them.
pub fn decide_dirs(a: &Path, b: &Path, root_b: &Path) -> std::io::Result<Vec<Value>> {
    let mods_a = load(a)?;
    let mods_b = load(b)?;
    let mut st = State::new(&mods_b, root_b);
    let d = decide(&mods_a, &mut st);
    let mut out = Vec::new();
    for ((mn, tid), r) in d {
        let rec_b = mods_b.get(&mn).and_then(|m| m.tests.get(&tid)).map(|t| &t.rec);
        out.push(serde_json::json!({
            "module": mn,
            "id": tid,
            "reusable": r.is_none(),
            "reason": r.map(|(c, d)| vec![c, d]),
            "outcome_a": mods_a[&mn].tests[&tid].rec.get("outcome"),
            "outcome_b": rec_b.and_then(|r| r.get("outcome")),
            "ms_b": rec_b.and_then(|r| r.get("ms")),
        }));
    }
    Ok(out)
}

/// Set of test ids of a module (helper for tests).
pub fn ids(m: &Module) -> HashSet<String> {
    m.tests.keys().cloned().collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Write;

    fn jvm_rec(root: &Path, classes: Value, cp: Vec<String>) -> Value {
        json!({"type": "jvm", "module": "", "root": root.to_string_lossy(), "runtime": {"tool": "t"}, "config": {"c": "1"},
               "classes": classes, "env_all": {}, "props_all": {}, "classpath": cp})
    }

    fn test_rec(id: &str, extra: Value) -> Value {
        let mut r = json!({"type": "test", "id": id, "module": "", "outcome": "passed", "scopes": ["C", "<session>"],
                           "classes": [], "files": {}, "resources": [], "lookups": {}, "env": {}, "props": {}, "net": [],
                           "proc": [], "native": [], "after": [], "written": false, "mut": false, "swrite": false});
        for (k, v) in extra.as_object().unwrap() {
            r[k] = v.clone();
        }
        r
    }

    fn write_deps(dir: &Path, recs: &[Value]) {
        std::fs::create_dir_all(dir).unwrap();
        let mut f = File::create(dir.join("root-100.jsonl")).unwrap();
        for r in recs {
            writeln!(f, "{}", r).unwrap();
        }
    }

    fn scopes() -> Vec<Value> {
        vec![
            json!({"type": "container", "id": "C", "module": "", "scopes": ["<session>"], "classes": []}),
            json!({"type": "session", "id": "<session>", "module": "", "scopes": [], "classes": []}),
        ]
    }

    fn run(a: &[Value], b: &[Value], root: &Path) -> Decisions {
        let t = tempfile::tempdir().unwrap();
        write_deps(&t.path().join("a"), a);
        write_deps(&t.path().join("b"), b);
        let ma = load(&t.path().join("a")).unwrap();
        let mb = load(&t.path().join("b")).unwrap();
        let mut st = State::new(&mb, root);
        decide(&ma, &mut st)
    }

    fn get<'a>(d: &'a Decisions, id: &str) -> &'a Reason {
        &d[&(String::new(), id.to_string())]
    }

    #[test]
    fn new_test_before_a_shared_state_reader_reruns_it_but_not_a_plain_test() {
        let root = tempfile::tempdir().unwrap();
        let j = jvm_rec(root.path(), json!({}), vec![]);
        let own = |c: &str| json!([c, "<session>"]);
        let reader = test_rec("Reader", json!({"mut": true, "scopes": own("R")}));
        let plain = test_rec("Plain", json!({"scopes": own("P")}));
        let writer = test_rec("Writer", json!({"swrite": true, "scopes": own("W")}));
        let mut a = vec![writer.clone(), reader.clone(), plain.clone()];
        a.extend(scopes());
        a.push(j.clone());
        let mut b = vec![writer, test_rec("NewOne", json!({"scopes": own("N"), "swrite": true})), reader, plain];
        b.extend(scopes());
        b.push(j);
        let d = run(&a, &b, root.path());
        assert_eq!(get(&d, "Reader").as_ref().map(|r| r.0.as_str()), Some("after-new"));
        assert_eq!(get(&d, "Plain"), &None);
        assert_eq!(get(&d, "Writer"), &None);
    }

    #[test]
    fn a_rerun_test_that_touched_no_shared_state_in_b_does_not_invalidate_a_reader() {
        let root = tempfile::tempdir().unwrap();
        let j = jvm_rec(root.path(), json!({}), vec![]);
        let own = |c: &str| json!([c, "<session>"]);
        let net = test_rec("Net", json!({"net": ["1.1.1.1:443"], "scopes": own("N")}));
        let reader = test_rec("Reader", json!({"mut": true, "scopes": own("R")}));
        let mut a = vec![net.clone(), reader.clone()];
        a.extend(scopes());
        a.push(j.clone());
        let d = run(&a, &a, root.path());
        assert_eq!(get(&d, "Net").as_ref().map(|r| r.0.as_str()), Some("network"));
        assert_eq!(get(&d, "Reader"), &None);
        // the same test, rerun, now touched a mutable static: the reader runs again
        let mut b = vec![test_rec("Net", json!({"net": ["1.1.1.1:443"], "scopes": own("N"), "mut": true})), reader];
        b.extend(scopes());
        b.push(j);
        assert_eq!(get(&run(&a, &b, root.path()), "Reader").as_ref().map(|r| r.0.as_str()), Some("after"));
    }

    #[test]
    fn blocked_network_is_never_reused_but_clean_and_written_properties_are_shared_state() {
        let root = tempfile::tempdir().unwrap();
        let mut j = jvm_rec(root.path(), json!({}), vec![]);
        j["props_start"] = json!({"mode": "d1", "other": "o1"});
        j["props_all"] = json!({"mode": "d2", "other": "o1"});
        j["props_written"] = json!(["mode"]);
        let own = |c: &str| json!([c, "<session>"]);
        let net = test_rec("Net", json!({"net": ["dns:x:blocked"], "scopes": own("N"), "mut": true}));
        let setter = test_rec("Setter", json!({"swrite": true, "scopes": own("S")}));
        let reader = test_rec("Reader", json!({"props": {"mode": "d2"}, "scopes": own("R")}));
        let other = test_rec("Other", json!({"props": {"other": "o1"}, "scopes": own("O")}));
        let mut a = vec![net, setter.clone(), reader.clone(), other.clone()];
        a.extend(scopes());
        a.push(j.clone());
        let d = run(&a, &a, root.path());
        assert_eq!(get(&d, "Net").as_ref().map(|r| r.0.as_str()), Some("network"));
        assert_eq!(get(&d, "Reader"), &None, "value read mid-run is not compared with the end value");
        assert_eq!(get(&d, "Other"), &None);
        // the setter changed: the reader of the written property runs again, the other one does not
        let ja = jvm_rec(root.path(), json!({"Set": format!("{} root:Set.class", short(b"v1"))}), vec![]);
        let jb = jvm_rec(root.path(), json!({"Set": format!("{} root:Set.class", short(b"v2"))}), vec![]);
        let fix = |mut x: Value| {
            x["props_start"] = j["props_start"].clone();
            x["props_written"] = j["props_written"].clone();
            x
        };
        let setter = test_rec("Setter", json!({"swrite": true, "scopes": own("S"), "classes": ["Set"]}));
        let mut a = vec![setter.clone(), reader.clone(), other.clone(), fix(ja)];
        a.extend(scopes());
        let mut b = vec![setter, reader, other, fix(jb)];
        b.extend(scopes());
        let d = run(&a, &b, root.path());
        assert_eq!(get(&d, "Reader").as_ref().map(|r| r.0.as_str()), Some("after"));
        assert_eq!(get(&d, "Other"), &None);
    }

    #[test]
    fn per_method_instances_do_not_chain_the_tests_of_a_class() {
        let root = tempfile::tempdir().unwrap();
        let ja = jvm_rec(root.path(), json!({"X": format!("{} root:X.class", short(b"v1"))}), vec![]);
        let jb = jvm_rec(root.path(), json!({"X": format!("{} root:X.class", short(b"v2"))}), vec![]);
        let k = json!({"type": "container", "id": "K", "module": "", "scopes": ["<session>"], "classes": [], "shared": false});
        let one = test_rec("one", json!({"classes": ["X"], "scopes": ["K", "<session>"]}));
        let two = test_rec("two", json!({"scopes": ["K", "<session>"]}));
        let mut a = vec![one.clone(), two.clone(), k.clone()];
        a.extend(scopes());
        a.push(ja);
        let mut b = vec![one, two, k];
        b.extend(scopes());
        b.push(jb);
        let d = run(&a, &b, root.path());
        assert_eq!(get(&d, "one").as_ref().map(|r| r.0.as_str()), Some("code"));
        assert_eq!(get(&d, "two"), &None);
    }

    #[test]
    fn reordered_state_touching_tests_rerun_a_reader() {
        let root = tempfile::tempdir().unwrap();
        let j = jvm_rec(root.path(), json!({}), vec![]);
        let w1 = test_rec("W1", json!({"swrite": true, "scopes": ["D", "<session>"]}));
        let w2 = test_rec("W2", json!({"swrite": true, "scopes": ["E", "<session>"]}));
        let r = test_rec("R", json!({"mut": true}));
        let mut a = vec![w1.clone(), w2.clone(), r.clone()];
        a.extend(scopes());
        a.push(j.clone());
        let mut b = vec![w2, w1, r];
        b.extend(scopes());
        b.push(j);
        let d = run(&a, &b, root.path());
        assert_eq!(get(&d, "R").as_ref().map(|r| r.0.as_str()), Some("order"));
    }

    #[test]
    fn earlier_test_of_the_same_class_changed_reruns_the_later_one() {
        let root = tempfile::tempdir().unwrap();
        let cls = root.path().join("X.class");
        std::fs::write(&cls, b"v1").unwrap();
        let ja = jvm_rec(root.path(), json!({"X": format!("{} root:X.class", short(b"v1"))}), vec![]);
        let jb = jvm_rec(root.path(), json!({"X": format!("{} root:X.class", short(b"v2"))}), vec![]);
        let fill = test_rec("a_fill", json!({"classes": ["X"]}));
        let count = test_rec("b_count", json!({}));
        let mut a = vec![fill.clone(), count.clone()];
        a.extend(scopes());
        a.push(ja);
        let mut b = vec![fill, count];
        b.extend(scopes());
        b.push(jb);
        let d = run(&a, &b, root.path());
        assert_eq!(get(&d, "a_fill").as_ref().map(|r| r.0.as_str()), Some("code"));
        assert_eq!(get(&d, "b_count").as_ref().map(|r| r.0.as_str()), Some("after"));
    }

    #[test]
    fn failed_test_with_unchanged_key_is_rerun_but_leaves_the_same_state() {
        let root = tempfile::tempdir().unwrap();
        let j = jvm_rec(root.path(), json!({}), vec![]);
        let failing = test_rec("F", json!({"outcome": "failed", "swrite": true, "scopes": ["D", "<session>"]}));
        let r = test_rec("R", json!({"mut": true}));
        let mut a = vec![failing.clone(), r.clone()];
        a.extend(scopes());
        a.push(j.clone());
        let mut b = vec![failing, r];
        b.extend(scopes());
        b.push(j);
        let d = run(&a, &b, root.path());
        assert_eq!(get(&d, "F").as_ref().map(|r| r.0.as_str()), Some("not-passed"));
        assert_eq!(get(&d, "R"), &None);
    }

    #[test]
    fn absent_resource_and_class_must_still_be_absent() {
        let root = tempfile::tempdir().unwrap();
        let cp = root.path().join("classes");
        std::fs::create_dir_all(&cp).unwrap();
        let j = jvm_rec(root.path(), json!({}), vec![cp.to_string_lossy().into_owned()]);
        let t = test_rec("T", json!({"resources": ["opt.properties=absent"], "lookups": {"p/Plugin": "absent"}}));
        let mut a = vec![t.clone()];
        a.extend(scopes());
        a.push(j.clone());
        let mut b = a.clone();
        b[0] = t;
        assert_eq!(get(&run(&a, &b, root.path()), "T"), &None);
        std::fs::write(cp.join("opt.properties"), b"x=1").unwrap();
        assert_eq!(get(&run(&a, &b, root.path()), "T").as_ref().map(|r| r.0.as_str()), Some("resource"));
        std::fs::remove_file(cp.join("opt.properties")).unwrap();
        std::fs::create_dir_all(cp.join("p")).unwrap();
        std::fs::write(cp.join("p/Plugin.class"), b"cafe").unwrap();
        assert_eq!(get(&run(&a, &b, root.path()), "T").as_ref().map(|r| r.0.as_str()), Some("class-lookup"));
    }

    #[test]
    fn get_resources_compares_every_location_and_a_shadowing_entry_counts() {
        let root = tempfile::tempdir().unwrap();
        let c1 = root.path().join("c1");
        let c2 = root.path().join("c2");
        std::fs::create_dir_all(c1.join("META-INF/services")).unwrap();
        std::fs::create_dir_all(c2.join("META-INF/services")).unwrap();
        std::fs::write(c2.join("META-INF/services/S"), b"impl.A\n").unwrap();
        std::fs::write(c2.join("r.txt"), b"two").unwrap();
        let j = jvm_rec(root.path(), json!({}), vec![c1.to_string_lossy().into_owned(), c2.to_string_lossy().into_owned()]);
        let mods = BTreeMap::new();
        let mut st0 = State::new(&mods, root.path());
        let svc = st0.resource_locations_for(&j, "META-INF/services/S", false).join("|");
        let first = st0.resource_locations_for(&j, "r.txt", true)[0].clone();
        let t = test_rec("T", json!({"resources": [format!("META-INF/services/S=all:{}", svc), format!("r.txt={}", first)]}));
        let mut a = vec![t];
        a.extend(scopes());
        a.push(j);
        assert_eq!(get(&run(&a, &a, root.path()), "T"), &None);
        // a second provider file earlier on the class path
        std::fs::write(c1.join("META-INF/services/S"), b"impl.B\n").unwrap();
        assert_eq!(get(&run(&a, &a, root.path()), "T").as_ref().map(|r| r.0.as_str()), Some("resource"));
        std::fs::remove_file(c1.join("META-INF/services/S")).unwrap();
        // r.txt shadowed by an earlier entry with other content
        std::fs::write(c1.join("r.txt"), b"one").unwrap();
        assert_eq!(get(&run(&a, &a, root.path()), "T").as_ref().map(|r| r.0.as_str()), Some("resource"));
    }

    #[test]
    fn processes_native_code_and_other_loaders_are_never_reused() {
        let root = tempfile::tempdir().unwrap();
        let j = jvm_rec(root.path(), json!({}), vec![]);
        for (extra, code) in [
            (json!({"proc": ["cat"]}), "process"),
            (json!({"native": ["lib:/x/libn.so"]}), "native"),
            (json!({"resources": ["x.properties=?"]}), "resource-loader"),
        ] {
            let mut a = vec![test_rec("T", extra)];
            a.extend(scopes());
            a.push(j.clone());
            assert_eq!(get(&run(&a, &a, root.path()), "T").as_ref().map(|r| r.0.as_str()), Some(code));
        }
    }
}
