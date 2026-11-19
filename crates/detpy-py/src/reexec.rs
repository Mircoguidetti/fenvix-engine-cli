//! `--det`'s re-exec decisions (`detpy/reexec.py`), in Rust: whether ASLR is disabled (`/proc/self/personality`)
//! and disabling it for the exec (`personality(2)`), the bytecode cache directory and whether it is active, what a
//! re-exec would fix (`plan`), the command line to exec again (`_argv`), whether it can (`can_reexec`), the
//! precompile's directories (deduplicated by realpath) and its stamps file (read, todo/fresh decision, write).
//!
//! The process state they read is the interpreter's own (`os.environ`, `sys.flags`, `sys.pycache_prefix`,
//! `sys.orig_argv`, ...), read through Python at each call: a test's monkeypatch is seen as it was. Python keeps
//! `reexec()` itself (`os.execve`), `sysconfig.get_paths()` and the driver subprocess. The Python original is kept
//! verbatim in `tests/rust_hotpaths_ref/_ref_reexec_r2.py`.

use detpy_core::reexec as core;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::ffi::OsString;
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::path::PathBuf;

const MARKER: &str = "DETPY_REEXEC";

/// `os.environ.get(key)`.
fn environ<'py>(py: Python<'py>, key: &str) -> PyResult<Option<Bound<'py, PyAny>>> {
    let v = py.import("os")?.getattr("environ")?.call_method1("get", (key,))?;
    Ok(if v.is_none() { None } else { Some(v) })
}

/// `os.environ.get(key) or None`, as bytes.
fn environ_bytes(py: Python<'_>, key: &str) -> PyResult<Option<Vec<u8>>> {
    match environ(py, key)? {
        Some(v) if v.is_truthy()? => Ok(Some(v.extract::<OsString>()?.into_vec())),
        _ => Ok(None),
    }
}

/// `os.path.realpath(path)`: the working directory is read only for a relative path (as `os.getcwd()` is).
fn realpath(path: &[u8]) -> PyResult<Vec<u8>> {
    let cwd = if path.starts_with(b"/") { Vec::new() } else { std::env::current_dir()?.into_os_string().into_vec() };
    Ok(core::realpath(path, &cwd))
}

/// `os.path.isdir(path)`.
fn isdir(path: &[u8]) -> bool {
    std::fs::metadata(std::ffi::OsStr::from_bytes(path)).map(|m| m.is_dir()).unwrap_or(false)
}

/// `bool(int(open("/proc/self/personality").read().strip(), 16) & ADDR_NO_RANDOMIZE)`; None when unknown.
#[pyfunction]
fn aslr_disabled() -> Option<bool> {
    let bytes = std::fs::read("/proc/self/personality").ok()?;
    core::personality_no_randomize(std::str::from_utf8(&bytes).ok()?)
}

/// `aslr_disabled`'s parse of the file's text (for the equivalence tests).
#[pyfunction]
fn reexec_parse_personality(text: &str) -> Option<bool> {
    core::personality_no_randomize(text)
}

#[cfg(target_os = "linux")]
extern "C" {
    fn personality(persona: std::ffi::c_ulong) -> std::ffi::c_int;
}

/// Set ADDR_NO_RANDOMIZE in this process's personality, inherited by the exec'd program (Linux only).
#[pyfunction]
fn disable_aslr_for_exec() -> bool {
    #[cfg(target_os = "linux")]
    {
        // SAFETY: personality(2) only reads and sets this process's execution domain flags.
        let current = unsafe { personality(0xFFFF_FFFF) };
        if current == -1 {
            return false;
        }
        unsafe { personality((current as u32 as std::ffi::c_ulong) | core::ADDR_NO_RANDOMIZE as std::ffi::c_ulong) != -1 }
    }
    #[cfg(not(target_os = "linux"))]
    {
        false
    }
}

/// `os.path.expanduser("~")`.
fn home(py: Python<'_>) -> PyResult<Vec<u8>> {
    let h = match environ(py, "HOME")? {
        Some(h) => h.extract::<OsString>()?.into_vec(),
        #[allow(deprecated)] // HOME is not set: the password database's entry (getpwuid_r)
        None => match std::env::home_dir() {
            Some(h) => h.into_os_string().into_vec(),
            None => return Ok(b"~".to_vec()),
        },
    };
    let n = h.iter().rposition(|&c| c != b'/').map_or(0, |i| i + 1);
    Ok(if n == 0 { b"/".to_vec() } else { h[..n].to_vec() })
}

fn cache_dir(py: Python<'_>, hashseed: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    let base = match environ_bytes(py, "DETPY_PYC_CACHE")? {
        Some(b) => b,
        None => {
            let cache = match environ_bytes(py, "XDG_CACHE_HOME")? {
                Some(x) => x,
                None => core::join(&home(py)?, &[b".cache"]),
            };
            core::join(&cache, &[b"detpy", b"pyc"])
        }
    };
    let tag = py.import("sys")?.getattr("implementation")?.getattr("cache_tag")?.str()?;
    let leaf = format!("{}-hashseed{}", tag.to_cow()?, hashseed.str()?.to_cow()?);
    let leaf: OsString = pyo3::types::PyString::new(py, &leaf).extract()?;
    Ok(core::join(&base, &[leaf.as_bytes()]))
}

/// `$DETPY_PYC_CACHE` or `$XDG_CACHE_HOME/detpy/pyc` (`~/.cache/detpy/pyc`), then `<cache_tag>-hashseed<seed>`.
#[pyfunction]
fn pyc_cache_dir(py: Python<'_>, hashseed: &Bound<'_, PyAny>) -> PyResult<OsString> {
    Ok(OsString::from_vec(cache_dir(py, hashseed)?))
}

fn bytecode_on(py: Python<'_>, hashseed: &Bound<'_, PyAny>) -> PyResult<bool> {
    let sys = py.import("sys")?;
    if !sys.getattr("flags")?.getattr("dont_write_bytecode")?.is_truthy()? {
        return Ok(false);
    }
    let prefix = sys.getattr("pycache_prefix")?;
    if !prefix.is_truthy()? {
        return Ok(false);
    }
    let prefix = prefix.extract::<OsString>()?.into_vec();
    Ok(realpath(&prefix)? == realpath(&cache_dir(py, hashseed)?)?)
}

/// The interpreter runs without writing bytecode, from the cache of this hash seed.
#[pyfunction]
fn bytecode_active(py: Python<'_>, hashseed: &Bound<'_, PyAny>) -> PyResult<bool> {
    bytecode_on(py, hashseed)
}

/// What a re-exec would fix: `{"hashseed", "aslr", "bytecode"}` (a falsy want is returned as it was given).
#[pyfunction]
#[pyo3(signature = (want_hashseed, want_no_aslr, want_bytecode))]
fn reexec_plan<'py>(
    py: Python<'py>,
    want_hashseed: &Bound<'py, PyAny>,
    want_no_aslr: &Bound<'py, PyAny>,
    want_bytecode: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyDict>> {
    let current = py.import("os")?.getattr("environ")?.call_method1("get", ("PYTHONHASHSEED",))?;
    let need_hash = current.ne(want_hashseed)?;
    let need_aslr = if want_no_aslr.is_truthy()? {
        pyo3::types::PyBool::new(py, aslr_disabled() == Some(false)).to_owned().into_any()
    } else {
        want_no_aslr.clone()
    };
    let need_bytecode = if want_bytecode.is_truthy()? {
        pyo3::types::PyBool::new(py, !bytecode_on(py, want_hashseed)?).to_owned().into_any()
    } else {
        want_bytecode.clone()
    };
    let d = PyDict::new(py);
    d.set_item("hashseed", need_hash)?;
    d.set_item("aslr", need_aslr)?;
    d.set_item("bytecode", need_bytecode)?;
    Ok(d)
}

fn argv<'py>(py: Python<'py>) -> PyResult<Option<Bound<'py, PyList>>> {
    let sys = py.import("sys")?;
    let exe = sys.getattr("executable")?;
    let orig = sys.getattr_opt("orig_argv")?;
    if let Some(orig) = orig.filter(|o| o.is_truthy().unwrap_or(false)) {
        let out = PyList::new(py, [exe])?;
        for a in orig.get_item(pyo3::types::PySlice::new(py, 1, isize::MAX, 1))?.try_iter()? {
            out.append(a?)?;
        }
        return Ok(Some(out));
    }
    // Python < 3.10: rebuild the command line (interpreter flags are lost)
    let main = sys.getattr("modules")?.call_method1("get", ("__main__",))?;
    let spec = main.getattr_opt("__spec__")?;
    let argv = sys.getattr("argv")?;
    if let Some(spec) = spec.filter(|s| !s.is_none()) {
        let name = spec.getattr("name")?;
        if name.eq("pytest")? || name.eq("pytest.__main__")? {
            let out = PyList::new(py, [exe.clone(), "-m".into_pyobject(py)?.into_any(), "pytest".into_pyobject(py)?.into_any()])?;
            for a in argv.get_item(pyo3::types::PySlice::new(py, 1, isize::MAX, 1))?.try_iter()? {
                out.append(a?)?;
            }
            return Ok(Some(out));
        }
    }
    if argv.is_truthy()? && argv.get_item(0)?.is_truthy()? {
        let out = PyList::new(py, [exe])?;
        for a in argv.try_iter()? {
            out.append(a?)?;
        }
        return Ok(Some(out));
    }
    Ok(None)
}

/// The command line to exec again (`sys.orig_argv` behind `sys.executable`), None when it cannot be rebuilt.
#[pyfunction]
fn reexec_argv(py: Python<'_>) -> PyResult<Option<Bound<'_, PyList>>> {
    argv(py)
}

/// `(True, "")` or `(False, why)`: never twice, never from a nested in-process session, POSIX only.
#[pyfunction]
fn reexec_can(py: Python<'_>, session_depth: i64) -> PyResult<(bool, &'static str)> {
    if environ(py, MARKER)?.map(|v| v.eq("1")).transpose()?.unwrap_or(false) {
        return Ok((false, "already re-executed"));
    }
    if session_depth > 1 {
        return Ok((false, "nested in-process pytest session"));
    }
    if !py.import("os")?.getattr("name")?.eq("posix")? {
        return Ok((false, "exec is only supported on POSIX"));
    }
    if argv(py)?.is_none() {
        return Ok((false, "cannot reconstruct the command line"));
    }
    Ok((true, ""))
}

/// The precompile's directories: the existing `candidates` (sysconfig's stdlib, purelib, platlib) without repeats by
/// realpath, then `rootdir` when it is a directory.
#[pyfunction]
#[pyo3(signature = (candidates, rootdir))]
fn reexec_precompile_dirs<'py>(
    py: Python<'py>,
    candidates: Vec<Bound<'py, PyAny>>,
    rootdir: Option<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyList>> {
    let out = PyList::empty(py);
    let mut reals: Vec<Vec<u8>> = Vec::new();
    for p in candidates {
        if p.is_none() || !p.is_truthy()? {
            continue;
        }
        let b = p.extract::<OsString>()?.into_vec();
        if !isdir(&b) {
            continue;
        }
        let r = realpath(&b)?;
        if !reals.contains(&r) {
            reals.push(r);
            out.append(p)?;
        }
    }
    if let Some(r) = rootdir.filter(|r| r.is_truthy().unwrap_or(false)) {
        if isdir(&r.extract::<OsString>()?.into_vec()) {
            out.append(r)?;
        }
    }
    Ok(out)
}

/// The stamps to write once the precompile completed.
#[pyclass(module = "detpy._core", frozen)]
struct PrecompileStamps {
    stamps: core::Stamps,
}

#[pymethods]
impl PrecompileStamps {
    /// `json.dump` to `path` through `<path>.<pid>.tmp` and a rename (errors ignored).
    fn write(&self, path: PathBuf) {
        self.stamps.write(&path, &crate::proofcache::py_float_repr);
    }

    /// The JSON text `write` writes.
    fn dumps(&self) -> String {
        self.stamps.dumps(&crate::proofcache::py_float_repr)
    }
}

fn to_path(b: Vec<u8>) -> OsString {
    OsString::from_vec(b)
}

/// `(libs, project, stamps)`: the library directories whose stamp changed, the project, and the stamps read from
/// `stamps_path` updated with every library directory's current `dir_stamp`.
#[pyfunction]
#[pyo3(signature = (dirs, rootdir, stamps_path))]
fn reexec_precompile_plan(
    py: Python<'_>,
    dirs: Vec<OsString>,
    rootdir: Option<OsString>,
    stamps_path: PathBuf,
) -> PyResult<(Vec<OsString>, Vec<OsString>, PrecompileStamps)> {
    let dirs: Vec<Vec<u8>> = dirs.into_iter().map(|d| d.into_vec()).collect();
    let rootdir = rootdir.map(|r| r.into_vec());
    let needs_cwd = dirs.iter().chain(rootdir.iter()).any(|d| !d.starts_with(b"/"));
    let cwd = if needs_cwd { std::env::current_dir()?.into_os_string().into_vec() } else { Vec::new() };
    let plan = core::plan_precompile(&dirs, rootdir.as_deref(), &cwd, &stamps_path, |d| {
        crate::precompile::dir_stamp(py, OsString::from_vec(d.to_vec()))
    });
    Ok((
        plan.libs.into_iter().map(to_path).collect(),
        plan.project.into_iter().map(to_path).collect(),
        PrecompileStamps { stamps: plan.stamps },
    ))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(aslr_disabled, m)?)?;
    m.add_function(wrap_pyfunction!(reexec_parse_personality, m)?)?;
    m.add_function(wrap_pyfunction!(disable_aslr_for_exec, m)?)?;
    m.add_function(wrap_pyfunction!(pyc_cache_dir, m)?)?;
    m.add_function(wrap_pyfunction!(bytecode_active, m)?)?;
    m.add_function(wrap_pyfunction!(reexec_plan, m)?)?;
    m.add_function(wrap_pyfunction!(reexec_argv, m)?)?;
    m.add_function(wrap_pyfunction!(reexec_can, m)?)?;
    m.add_function(wrap_pyfunction!(reexec_precompile_dirs, m)?)?;
    m.add_function(wrap_pyfunction!(reexec_precompile_plan, m)?)?;
    m.add_class::<PrecompileStamps>()?;
    Ok(())
}
