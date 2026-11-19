"""parallel-proof round 3, carried-set rule x memoised state held by a THIRD-PARTY library (coordinator's attack).

Test A loads ``cfg.yml`` through a library that memoises it (a module dict, a ``functools.lru_cache`` keyed by path,
the standard library's ``linecache``). Test B shares no repository file with A: it reads the library's memo and never
opens ``cfg.yml``. ``cfg.yml`` changes: A reruns, and B's cached pass must not be reused (a fresh run fails B, which
gets the new value from A's reload, or reads the file itself when it runs without A).

The library lives outside the repository (a site directory, or the standard library), so no repository file connects
A and B. Serially and with ``-n 2`` (both tests in one worker: ``--dist loadgroup``).
"""

import json
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

LIBS = {
    # a module-level dict: B runs the library's Python code (``current``) and reads what A stored
    "dict": ("memolib", """
        _CACHE = {}

        def load(path):
            if path not in _CACHE:
                with open(path) as fh:
                    _CACHE[path] = fh.read().strip()
            return _CACHE[path]
        """, "memolib.load(P)", "memolib.load(P)"),
    # functools.lru_cache keyed by path: B's hit runs no Python code of the library at all
    "lru": ("memolib", """
        import functools

        @functools.lru_cache(maxsize=None)
        def load(path):
            with open(path) as fh:
                return fh.read().strip()
        """, "memolib.load(P)", "memolib.load(P)"),
    # a third library reached through a second one: B's repository code references only ``wrap``
    "indirect": ("wrap", """
        import functools

        @functools.lru_cache(maxsize=None)
        def _load(path):
            with open(path) as fh:
                return fh.read().strip()

        def get(path):
            return _load(path)
        """, "wrap.get(P)", "wrap.get(P)"),
    # a repository module read by attribute: B runs none of its code (pkg/memo.py is executed by A only)
    "repo": ("pkg.memo", """
        _CACHE = {}

        def load(path):
            if path not in _CACHE:
                with open(path) as fh:
                    _CACHE[path] = fh.read().strip()
            return _CACHE[path]
        """, "pkg.memo.load(P)", "pkg.memo._CACHE[P]"),
    # the standard library: linecache serves a path it has seen from its cache, without reading the file
    "linecache": ("linecache", None, "linecache.getline(P, 1).strip()", "linecache.getline(P, 1).strip()"),
}


def _project(pytester, monkeypatch, tmp_path_factory, kind):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(k, raising=False)
    mod, src, a_expr, b_expr = LIBS[kind]
    if mod.startswith("pkg."):
        pytester.mkpydir("pkg")
        (pytester.path / "pkg" / "memo.py").write_text(textwrap.dedent(src))
    elif src is not None:
        # outside the project root, as a real site directory is
        env = tmp_path_factory.mktemp("env")
        site = env / "site-packages"
        boot = env / "boot"
        site.mkdir(parents=True)
        boot.mkdir()
        (site / f"{mod}.py").write_text(textwrap.dedent(src))
        (boot / "sitecustomize.py").write_text(f"import site\nsite.addsitedir({str(site)!r})\n")
        monkeypatch.setenv("PYTHONPATH", str(boot))
    pytester.makeini("[pytest]\nmarkers =\n    xdist_group: group\n")
    (pytester.path / "cfg.yml").write_text("old\n")
    pytester.makepyfile(test_a=f"""
        import os

        import pytest
        import {mod}

        P = os.path.abspath("cfg.yml")

        @pytest.mark.xdist_group("g")
        def test_a():
            assert {a_expr}
        """, test_b=f"""
        import os

        import pytest
        import {mod}

        P = os.path.abspath("cfg.yml")

        @pytest.mark.xdist_group("g")
        def test_b():
            assert {b_expr} == "old"
        """)


def _run(pytester, n, *args):
    out = pytester.path / f"o{n}.json"
    r = pytester.runpytest_subprocess("--det", f"--det-outcomes={out}", "-p", "no:cacheprovider", *args)
    d = json.loads(out.read_text()) if out.exists() else {}
    o = d.get("outcomes") or {}
    o = {k: (v["outcome"] if isinstance(v, dict) else v) for k, v in o.items()}
    return r, o, set((d.get("cache") or {}).get("reused_ids", ()))


@pytest.mark.parametrize("mode", ["serial", "n2"])
@pytest.mark.parametrize("kind", sorted(LIBS))
def test_a_library_memo_written_by_an_earlier_test_is_carried(pytester, monkeypatch, tmp_path_factory, kind, mode):
    _project(pytester, monkeypatch, tmp_path_factory, kind)
    cache = f"--det-cache={pytester.path / '.c'}"
    par = () if mode == "serial" else ("-n", "2", "-p", "xdist", "--dist", "loadgroup")
    r0, o0, _ = _run(pytester, 0, cache, *par)
    assert o0 == {"test_a.py::test_a": "passed", "test_b.py::test_b": "passed"}, r0.stdout.str()
    # the memo is what B reads: B alone (no A before it in its process) gives the same pass at P
    (pytester.path / "cfg.yml").write_text("new\n")
    r1, o1, reused = _run(pytester, 1, cache, *par)
    _, truth, _ = _run(pytester, 2)
    assert truth == {"test_a.py::test_a": "passed", "test_b.py::test_b": "failed"}
    wrong = {n: (o1.get(n), truth.get(n)) for n in reused if o1.get(n) != truth.get(n)}
    assert wrong == {}, r1.stdout.str()
    assert "test_b.py::test_b" not in reused, r1.stdout.str()


# -- order dependence (coordinator): B passes only after A set a library's state, fails alone -------------------------
ORDER_LIB = """
    STATE = {}

    def configure():
        STATE["ready"] = True
    """


def _order_project(pytester, monkeypatch, tmp_path_factory):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path_factory.mktemp("env")
    site, boot = env / "site-packages", env / "boot"
    site.mkdir()
    boot.mkdir()
    (site / "statelib.py").write_text(textwrap.dedent(ORDER_LIB))
    (boot / "sitecustomize.py").write_text(f"import site\nsite.addsitedir({str(site)!r})\n")
    monkeypatch.setenv("PYTHONPATH", str(boot))
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_a="""
        import statelib

        def test_a():
            statelib.configure()
        """, test_b="""
        import statelib

        def test_b():
            assert statelib.STATE.get("ready")
        """)


SER = ()
PAR = ("-n", "2", "-p", "xdist", "--dist", "loadfile")


@pytest.mark.parametrize("record,reuse", [("serial", "n2"), ("n2", "serial")])
def test_an_order_dependent_pass_is_not_reused_in_a_placement_that_fails_it(pytester, monkeypatch, tmp_path_factory,
                                                                           record, reuse):
    _order_project(pytester, monkeypatch, tmp_path_factory)
    cache = f"--det-cache={pytester.path / '.c'}"
    rec = SER if record == "serial" else PAR
    use = SER if reuse == "serial" else PAR
    # the truth of each placement: serially B runs after A and passes; in -n 2 with one file per worker it runs alone
    _, t_ser, _ = _run(pytester, 10)
    _, t_par, _ = _run(pytester, 11, *PAR)
    assert t_ser["test_b.py::test_b"] == "passed"
    assert t_par["test_b.py::test_b"] == "failed", t_par
    truth = t_ser if reuse == "serial" else t_par
    _run(pytester, 0, cache, *rec)
    r1, o1, reused = _run(pytester, 1, cache, *use)
    wrong = {n: (o1.get(n), truth.get(n)) for n in reused if o1.get(n) != truth.get(n)}
    assert wrong == {}, r1.stdout.str()
    assert o1 == truth, r1.stdout.str()


# -- a context's own output outside the repository (claude/dep-verdict-abjcfw ee1d06c: not carried) -------------------
@pytest.mark.parametrize("mode", ["serial", "n2"])
def test_a_file_outside_the_repository_an_earlier_test_wrote_from_a_repository_input(pytester, monkeypatch,
                                                                                     tmp_path_factory, mode):
    # A writes <tmp>/state from cfg.yml; B shares no repository file with A (neither imports anything) and reads
    # <tmp>/state. cfg.yml changes: B's pass must not be reused (a fresh run fails it)
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(k, raising=False)
    state = tmp_path_factory.mktemp("out") / "state"
    pytester.makeini("[pytest]\nmarkers =\n    xdist_group: group\n")
    (pytester.path / "cfg.yml").write_text("old\n")
    pytester.makepyfile(test_a=f"""
        import pytest

        @pytest.mark.xdist_group("g")
        def test_a():
            with open("cfg.yml") as src, open({str(state)!r}, "w") as dst:
                dst.write(src.read())
        """, test_b=f"""
        import pytest

        @pytest.mark.xdist_group("g")
        def test_b():
            with open({str(state)!r}) as fh:
                assert fh.read().strip() == "old"
        """)
    cache = f"--det-cache={pytester.path / '.c'}"
    par = () if mode == "serial" else ("-n", "2", "-p", "xdist", "--dist", "loadgroup")
    r0, o0, _ = _run(pytester, 0, cache, *par)
    assert o0 == {"test_a.py::test_a": "passed", "test_b.py::test_b": "passed"}, r0.stdout.str()
    (pytester.path / "cfg.yml").write_text("new\n")
    r1, o1, reused = _run(pytester, 1, cache, *par)
    _, truth, _ = _run(pytester, 2)
    assert truth["test_b.py::test_b"] == "failed"
    wrong = {n: (o1.get(n), truth.get(n)) for n in reused if o1.get(n) != truth.get(n)}
    assert wrong == {}, r1.stdout.str()
    assert "test_b.py::test_b" not in reused, r1.stdout.str()
