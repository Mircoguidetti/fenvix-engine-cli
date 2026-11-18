//! Stand-ins for the module callables detpy replaces with a recording wrapper (`random.random`, `os.urandom`,
//! `os.listdir`, ...): callable objects whose `__call__` is Rust, so a draw or a listing runs no detpy Python frame.
//!
//! They keep what `detpy._patch.disguise` / `nonbinding` gave the Python wrappers: `__name__`, `__qualname__`,
//! `__module__`, `__doc__` and `__wrapped__` (in the instance `__dict__`, as on `_NonBinding` objects), a builtin-like
//! `repr`, pickling by reference (`__reduce__` returns the qualified name) and, for `stand_in`, no `__get__`: stored
//! on a class and read through an instance they are not bound, like the builtins and bound methods they replace.
//! `method_stand_in` (for `random.Random.seed`, which replaced a Python method) binds like a function.

use crate::{fsorder, seeds};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyDict, PyString, PyTuple};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(crate) enum Kind {
    /// `seeds._wrap_numeric`: `random.<name>(...)`, records `repr(value)`.
    Numeric,
    /// `seeds._wrap_sequence`: `random.<name>(seq, ...)`, records `n=<len(seq) or -1>`.
    Sequence,
    /// `random.randbytes(n)`: records the digest of the bytes.
    RandBytes,
    /// `seeds._module_seed`: `random.seed(a=None, version=2)`.
    ModuleSeed,
    /// `seeds._seed`: `random.Random.seed(self, a=None, version=2)` (binds).
    RandomSeed,
    /// `seeds._urandom`: `os.urandom(n)` and `random._urandom` (`real` is `seeds`' globals).
    Urandom,
    /// `seeds._numpy_default_rng`: `numpy.random.default_rng(seed=None)`.
    DefaultRng,
    /// `fsorder.listdir(path=None)` (`real` is `fsorder`'s globals).
    Listdir,
    /// `fsorder.scandir(path=None)` (`real` is `fsorder`'s globals).
    Scandir,
}

impl Kind {
    fn parse(s: &str) -> PyResult<Kind> {
        Ok(match s {
            "numeric" => Kind::Numeric,
            "sequence" => Kind::Sequence,
            "randbytes" => Kind::RandBytes,
            "module_seed" => Kind::ModuleSeed,
            "random_seed" => Kind::RandomSeed,
            "urandom" => Kind::Urandom,
            "default_rng" => Kind::DefaultRng,
            "listdir" => Kind::Listdir,
            "scandir" => Kind::Scandir,
            _ => return Err(PyValueError::new_err(format!("unknown stand-in kind {s:?}"))),
        })
    }
}

/// What a stand-in does: its kind, the event's op and the real callable (or the module globals it reads it from).
pub(crate) struct Target {
    pub kind: Kind,
    pub op: String,
    /// the error-message name of the Python original (`__qualname__` of the function it replaces)
    pub fname: String,
    pub real: Py<PyAny>,
}

impl Target {
    fn call<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match self.kind {
            Kind::Listdir | Kind::Scandir => fsorder::call(py, self, args, kwargs),
            _ => seeds::call(py, self, args, kwargs),
        }
    }
}

/// `f(*args, **kwargs)` with the caller's tuple and dict (no repacking).
pub(crate) fn call_with<'py>(
    f: &Bound<'py, PyAny>,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    let kw = kwargs.map_or(std::ptr::null_mut(), |k| k.as_ptr());
    unsafe { Bound::from_owned_ptr_or_err(f.py(), ffi::PyObject_Call(f.as_ptr(), args.as_ptr(), kw)) }
}

/// Bind `args` / `kwargs` to the parameters `names` of a Python `def f(n0, ..., nk=default, ...)` whose first
/// `required` parameters have no default; `None` for a parameter not given. The errors are the interpreter's.
pub(crate) fn bind<'py, const N: usize>(
    fname: &str,
    names: [&str; N],
    required: usize,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, PyDict>>,
) -> PyResult<[Option<Bound<'py, PyAny>>; N]> {
    let mut out: [Option<Bound<'py, PyAny>>; N] = std::array::from_fn(|_| None);
    let given = args.len();
    if given > N {
        let takes = if required == N {
            format!("{N} positional argument{}", if N == 1 { "" } else { "s" })
        } else {
            format!("from {required} to {N} positional arguments")
        };
        let were = if given == 1 { "was" } else { "were" };
        return Err(PyTypeError::new_err(format!("{fname}() takes {takes} but {given} {were} given")));
    }
    for (i, a) in args.iter().enumerate() {
        out[i] = Some(a);
    }
    if let Some(kw) = kwargs {
        for (k, v) in kw.iter() {
            let key = k.cast::<PyString>().map_err(|_| PyTypeError::new_err(format!("{fname}() keywords must be strings")))?;
            let key = key.to_cow()?;
            match names.iter().position(|n| *n == key) {
                Some(i) if out[i].is_some() => {
                    return Err(PyTypeError::new_err(format!("{fname}() got multiple values for argument '{key}'")))
                }
                Some(i) => out[i] = Some(v),
                None => {
                    return Err(PyTypeError::new_err(format!("{fname}() got an unexpected keyword argument '{key}'")))
                }
            }
        }
    }
    let missing: Vec<&str> = (0..required).filter(|&i| out[i].is_none()).map(|i| names[i]).collect();
    if !missing.is_empty() {
        let quoted: Vec<String> = missing.iter().map(|m| format!("'{m}'")).collect();
        let list = match quoted.len() {
            1 => quoted[0].clone(),
            n => format!("{} and {}", quoted[..n - 1].join(", "), quoted[n - 1]),
        };
        let s = if missing.len() == 1 { "" } else { "s" };
        return Err(PyTypeError::new_err(format!(
            "{fname}() missing {} required positional argument{s}: {list}",
            missing.len()
        )));
    }
    Ok(out)
}

fn reduce(slf: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    Ok(slf.getattr(intern!(slf.py(), "__qualname__"))?.unbind())
}

fn repr(slf: &Bound<'_, PyAny>) -> PyResult<String> {
    let name = slf.getattr(intern!(slf.py(), "__name__"))?;
    Ok(format!("<built-in function {}>", name.str()?.to_cow()?))
}

/// A recording stand-in that does not bind as a method (see the module docs).
#[pyclass(module = "detpy._core", name = "stand_in", frozen, dict, weakref)]
pub(crate) struct StandIn {
    target: Target,
}

#[pymethods]
impl StandIn {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.target.call(py, args, kwargs)
    }

    fn __reduce__(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        reduce(slf.as_any())
    }

    fn __repr__(slf: &Bound<'_, Self>) -> PyResult<String> {
        repr(slf.as_any())
    }
}

/// A recording stand-in that binds as a method, like the Python function it replaces.
#[pyclass(module = "detpy._core", name = "method_stand_in", frozen, dict, weakref)]
pub(crate) struct MethodStandIn {
    target: Target,
}

static METHOD_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

#[pymethods]
impl MethodStandIn {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.target.call(py, args, kwargs)
    }

    /// Like a function: the object itself through the class, a bound method through an instance.
    fn __get__<'py>(
        slf: &Bound<'py, Self>,
        obj: Option<&Bound<'py, PyAny>>,
        _owner: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match obj {
            None => Ok(slf.clone().into_any()),
            Some(o) if o.is_none() => Ok(slf.clone().into_any()),
            Some(o) => {
                let py = slf.py();
                let mt = METHOD_TYPE.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
                    Ok(py.import("types")?.getattr("MethodType")?.unbind())
                })?;
                mt.bind(py).call1((slf, o))
            }
        }
    }

    fn __reduce__(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        reduce(slf.as_any())
    }

    fn __repr__(slf: &Bound<'_, Self>) -> PyResult<String> {
        let name = slf.getattr(intern!(slf.py(), "__qualname__"))?;
        Ok(format!("<function {}>", name.str()?.to_cow()?))
    }
}

/// `stand_in(kind, real, module, name, qualname=None, doc=None, wrapped=None, fname=None)`: a disguised recording
/// stand-in for `module.name` (`qualname` defaults to `name`, `wrapped` to `real`, `fname` (the name its argument
/// errors use) to `name`). `real` is the real callable, or the module globals the kind reads it from (`urandom`:
/// `seeds`, `listdir` / `scandir`: `fsorder`). Kind `random_seed` binds as a method; the others do not.
#[pyfunction]
#[pyo3(signature = (kind, real, module, name, qualname = None, doc = None, wrapped = None, fname = None))]
#[allow(clippy::too_many_arguments)]
pub(crate) fn stand_in<'py>(
    py: Python<'py>,
    kind: &str,
    real: Bound<'py, PyAny>,
    module: &Bound<'py, PyAny>,
    name: &Bound<'py, PyString>,
    qualname: Option<&Bound<'py, PyAny>>,
    doc: Option<&Bound<'py, PyAny>>,
    wrapped: Option<&Bound<'py, PyAny>>,
    fname: Option<String>,
) -> PyResult<Bound<'py, PyAny>> {
    let kind = Kind::parse(kind)?;
    let n = name.to_cow()?.into_owned();
    let op = match kind {
        Kind::Numeric | Kind::Sequence => format!("random.{n}"),
        Kind::RandBytes => "random.randbytes".into(),
        Kind::ModuleSeed => "random.seed".into(),
        Kind::RandomSeed => "Random.seed(None)".into(),
        Kind::Urandom => "os.urandom".into(),
        Kind::DefaultRng => "numpy.default_rng(None)".into(),
        Kind::Listdir => "os.listdir".into(),
        Kind::Scandir => "os.scandir".into(),
    };
    let target = Target { kind, op, fname: fname.unwrap_or_else(|| n.clone()), real: real.clone().unbind() };
    let obj = if kind == Kind::RandomSeed {
        Bound::new(py, MethodStandIn { target })?.into_any()
    } else {
        Bound::new(py, StandIn { target })?.into_any()
    };
    obj.setattr(intern!(py, "__name__"), name)?;
    obj.setattr(intern!(py, "__qualname__"), qualname.unwrap_or(name.as_any()))?;
    obj.setattr(intern!(py, "__module__"), module)?;
    obj.setattr(intern!(py, "__doc__"), doc.cloned().unwrap_or_else(|| py.None().into_bound(py)))?;
    obj.setattr(intern!(py, "__wrapped__"), wrapped.unwrap_or(&real))?;
    Ok(obj)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<StandIn>()?;
    m.add_class::<MethodStandIn>()?;
    m.add_function(wrap_pyfunction!(stand_in, m)?)?;
    Ok(())
}
