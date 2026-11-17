"""Python-level dependency capture for the skip study (loaded via PYTHONPATH as sitecustomize).

Active only when S2_PYREC (output directory) and S2_ROOT (repository root) are set. At process exit it
writes <S2_PYREC>/<pid>.json with:

* ``funcs``    executed code objects defined in repository files: [relpath, qualname, firstlineno]
               (sys.monitoring PY_START, each code object reported once per process);
* ``tried``    every module name the import system looked up (found or not): a file added later that
               provides one of these names can change the result;
* ``modules``  repository files of the modules loaded at exit;
* ``lists``    directories listed by Python code other than the import system (os.listdir / os.scandir);
* ``env``      environment variables read through ``os.environ`` / ``os.getenv`` / ``os.environb`` (get, ``in``,
               ``[]``) by any code in the process (review R-002 error 2). Two pseudo-names: ``*`` when code other
               than the test runner enumerated the whole environment, ``~proxy`` when the standard library's
               proxy lookup (``urllib.request.getproxies``) enumerated it for ``*_proxy`` variables.
"""

import os
import sys

_OUT = os.environ.get("S2_PYREC")
_ROOT = os.environ.get("S2_ROOT")

if _OUT and _ROOT:
    import atexit
    import json

    import sysconfig

    _root = os.path.realpath(_ROOT) + os.sep
    _STDLIB = os.path.dirname(os.__file__) + os.sep
    _DISCOVERY = (os.sep + "_pytest" + os.sep, os.sep + "pluggy" + os.sep, "__editable__", os.sep + "importlib",
                  os.sep + "setuptools" + os.sep, os.sep + "pkg_resources" + os.sep, "_virtualenv")
    _funcs = {}
    _tried = set()
    _lists = set()

    def _rel(p):
        try:
            p = os.path.realpath(p)
        except Exception:
            return None
        return p[len(_root):] if p.startswith(_root) else None

    class _Recorder:
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            _tried.add(fullname)
            return None

        @staticmethod
        def invalidate_caches():
            pass

    sys.meta_path.insert(0, _Recorder)

    _relcache = {}

    def _py_start(code, offset):
        f = code.co_filename
        r = _relcache.get(f, 0)
        if r == 0:
            r = _relcache[f] = _rel(f) if f and not f.startswith("<") else None
        if r is not None:
            _funcs[(r, code.co_qualname, code.co_firstlineno)] = 1
        return sys.monitoring.DISABLE

    if hasattr(sys, "monitoring"):
        for _tid in (4, 3, 5):
            try:
                sys.monitoring.use_tool_id(_tid, "skip-study2")
            except ValueError:
                continue
            sys.monitoring.register_callback(_tid, sys.monitoring.events.PY_START, _py_start)
            sys.monitoring.set_events(_tid, sys.monitoring.events.PY_START)
            break

    def _audit(event, args):
        if event in ("os.listdir", "os.scandir"):
            # the first caller outside the standard library decides: the import system, pytest's own
            # collection (discovery of test files and conftests) and editable-install finders are not
            # dependencies of a test's result (module lookups are recorded in ``tried``)
            try:
                f = sys._getframe(1)
                for _ in range(12):
                    if f is None:
                        break
                    fn = f.f_code.co_filename
                    if fn.startswith("<frozen") or fn.startswith(_STDLIB):
                        if "importlib" in fn:
                            return
                        f = f.f_back
                        continue
                    if any(x in fn for x in _DISCOVERY):
                        return
                    break
            except ValueError:
                pass
            a = args[0] if args and args[0] is not None else "."
            try:
                if isinstance(a, int):
                    return
                r = _rel(os.fsdecode(a))
            except Exception:
                return
            if r is not None:
                _lists.add(r)

    sys.addaudithook(_audit)

    # -- environment variables -------------------------------------------------------------------
    _env = set()
    _RUNNER = (os.sep + "_pytest" + os.sep, os.sep + "pluggy" + os.sep, os.sep + "xdist" + os.sep,
               os.sep + "execnet" + os.sep)

    def _enumerated():
        try:
            f = sys._getframe(2)
        except ValueError:
            return
        for _ in range(40):
            if f is None:
                break
            fn = f.f_code.co_filename
            if fn.endswith(os.sep + "urllib" + os.sep + "request.py") and "proxies" in f.f_code.co_name:
                _env.add("~proxy")
                return
            if fn == __file__ or fn.startswith("<frozen") or fn.startswith(_STDLIB):
                f = f.f_back
                continue
            if any(x in fn for x in _RUNNER):
                return  # the test runner forwarding or snapshotting the environment
            break
        _env.add("*")

    def _per_key_of_enumeration():
        # ItemsView / ValuesView iteration looks every key up: part of the enumeration, not separate reads
        try:
            c = sys._getframe(2).f_code
        except ValueError:
            return False
        return c.co_name == "__iter__" and c.co_filename.endswith("_collections_abc.py")

    def _make(base):
        class _Recorded(base):
            def __getitem__(self, key):
                if not _per_key_of_enumeration():
                    _env.add(os.fsdecode(key) if isinstance(key, (str, bytes)) else repr(key))
                return base.__getitem__(self, key)

            def __contains__(self, key):
                _env.add(os.fsdecode(key) if isinstance(key, (str, bytes)) else repr(key))
                return base.__contains__(self, key)

            def __iter__(self):
                _enumerated()
                return base.__iter__(self)
        return _Recorded

    for _m in ("environ", "environb"):
        _o = getattr(os, _m, None)
        if _o is not None:
            try:
                _o.__class__ = _make(type(_o))
            except TypeError:
                pass

    def _dump():
        mods = set()
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f:
                r = _rel(f)
                if r is not None:
                    mods.add(r)
        try:
            with open(os.path.join(_OUT, f"{os.getpid()}.json"), "w") as fh:
                json.dump({"funcs": sorted(_funcs), "tried": sorted(_tried), "modules": sorted(mods),
                           "lists": sorted(_lists), "env": sorted(_env)}, fh)
        except Exception:
            pass

    atexit.register(_dump)
