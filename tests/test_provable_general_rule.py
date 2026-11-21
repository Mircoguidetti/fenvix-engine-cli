"""The general rule: a test's verdict is IDENTICAL only if everything it did is accounted for.

Founder decision, 2026-11-21: *"Never a green on a doubt. If the engine is not certain, it answers NOT PROVEN and
the test is rerun. A test reported green that was red is the worst damage we can do to a customer. Speed never
buys an exception."*

Every other verifier test in this repository names a channel: review R-051, R-054, R-055 and R-057 each found new
ones, and each was fixed as a channel. This file is deliberately not like that. **Nothing here depends on a list
of channels.** Each test invents a channel the engine knows nothing about, or derives one from the engine's own
accounting table, and asserts that the verdict is NOT PROVEN rather than IDENTICAL. If someone adds channel
number 27 tomorrow, these tests already cover it.

The four shapes, weakest to strongest:

1. :func:`test_a_name_the_table_has_never_seen_is_never_accounted` — the table's default answer, on names
   generated at random. The property the whole design rests on.
2. :func:`test_a_run_that_cannot_say_what_it_watched_is_never_identical` — end to end, with no sensor at all.
3. :func:`test_a_channel_derived_from_the_engines_own_table_is_not_proven` — the channel is not written here: it is
   computed by asking the table which of the interpreter's own C callables it cannot account for.
4. :func:`test_an_invented_native_channel_is_not_proven_and_not_identical` — a C extension module with a name
   generated at test time, which reads a file **in C**. No in-process sensor can see that read, and on the trunk
   before this rule the verdict was IDENTICAL. This is the finish line.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import string
import subprocess
import sys
import sysconfig
import textwrap
from pathlib import Path

import pytest

from detpy import _core

PY = sys.executable


def _env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONHASHSEED", None)
    env.update(extra or {})
    return env


def _project(tmp_path: Path, files: dict) -> Path:
    proj = tmp_path / "proj"
    for rel, text in files.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    return proj


def _run(proj: Path, trace: Path, env: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
         f"--det-trace={trace}", *extra, "tests"],
        cwd=proj, env=env, capture_output=True, text=True, timeout=900)


def _verify(proj: Path, traces: list[Path]) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "detpy.fenvix", "verify", *[str(t) for t in traces]],
                          cwd=proj, env=_env(), capture_output=True, text=True, timeout=300)


# ---------------------------------------------------------------------------------------------------------------
# 1. The table's default answer, on names nobody could have listed
# ---------------------------------------------------------------------------------------------------------------

def test_a_name_the_table_has_never_seen_is_never_accounted():
    """For a randomly generated module and callable, the accounting table answers `unaccounted`.

    This is default-deny itself, and it is the reason a channel nobody has thought of cannot come out IDENTICAL.
    The names are generated here, so no list in the engine can contain them.
    """
    rnd = random.Random(20261121)
    letters = string.ascii_lowercase
    for _ in range(500):
        mod = "".join(rnd.choice(letters) for _ in range(rnd.randint(3, 12)))
        qual = "".join(rnd.choice(letters) for _ in range(rnd.randint(3, 12)))
        assert _core.provable_account(mod, qual) == "unaccounted", f"{mod}.{qual} was accounted for"
    # and the empty module (a lambda, an anonymous C callable) is not accounted for either
    assert _core.provable_account("", "whatever") == "unaccounted"


def test_the_table_only_claims_the_runtimes_it_was_audited_against():
    """The closed-world argument depends on this: the table's claims are about a pinned interpreter surface.

    A callable that did not exist when the table was written cannot be reached while the verdict is still
    IDENTICAL, because the runtime it would exist on is not one the table claims anything about.
    """
    audited = _core.provable_runtimes()
    assert audited, "the table must name the runtimes it was audited against"
    here = f"cpython{sys.version_info[0]}.{sys.version_info[1]}"
    assert here in audited, f"this interpreter ({here}) is not in {audited}: no test here could be identical"
    for made_up in ("cpython3.99", "cpython2.7", "pypy3.13", ""):
        assert made_up not in audited


# ---------------------------------------------------------------------------------------------------------------
# 2. A run that cannot say what it watched
# ---------------------------------------------------------------------------------------------------------------

def test_a_run_that_cannot_say_what_it_watched_is_never_identical(tmp_path):
    """Two runs of a trivial, genuinely deterministic test, with the wide sensor switched off.

    Nothing differs: same code, same inputs, same events, same fingerprint. The verdict must still be NOT PROVEN,
    because the run cannot say what the test did. This is the clause that makes "I do not know" the default
    instead of "identical", and it is what refuses an older shell's traces too.
    """
    proj = _project(tmp_path, {"tests/test_x.py": """
        def test_pure():
            assert sum(range(10)) == 45
    """})
    traces = []
    for i in (1, 2):
        t = tmp_path / f"off{i}.jsonl"
        r = _run(proj, t, _env({"FENVIX_NO_PROVABLE_SENSOR": "1"}))
        assert t.exists(), r.stdout[-3000:] + r.stderr[-3000:]
        traces.append(t)
    v = _verify(proj, traces)
    assert v.returncode == 1, f"expected NOT PROVEN (exit 1), got {v.returncode}\n{v.stdout}"
    assert "NOT PROVEN" in v.stdout, v.stdout
    assert "not proven: 1" in v.stdout, v.stdout
    assert "covered by Level 0: 0" in v.stdout, v.stdout

    # the same two runs with the sensor on are IDENTICAL: the refusal above is the missing sensor, not the test
    traces = []
    for i in (1, 2):
        t = tmp_path / f"on{i}.jsonl"
        r = _run(proj, t, _env())
        assert t.exists(), r.stdout[-3000:] + r.stderr[-3000:]
        traces.append(t)
    v = _verify(proj, traces)
    assert v.returncode == 0, f"expected IDENTICAL once the sensor is on, got {v.returncode}\n{v.stdout}"


# ---------------------------------------------------------------------------------------------------------------
# 3. A channel derived from the engine's own table, not written here
# ---------------------------------------------------------------------------------------------------------------

def _an_unaccounted_stdlib_callable() -> tuple[str, str]:
    """Ask the table which of the interpreter's own C callables it cannot account for, and return one.

    The point of going through the table is that this test names no channel. Whatever the engine has not reasoned
    about, this is what gets called below.
    """
    import posix

    for name in sorted(dir(posix)):
        if name.startswith("__"):
            continue
        obj = getattr(posix, name, None)
        if not callable(obj):
            continue
        if _core.provable_account("posix", name) == "unaccounted":
            return "posix", name
    pytest.skip("the table accounts for every callable of posix: nothing left to derive a channel from")


def test_a_channel_derived_from_the_engines_own_table_is_not_proven(tmp_path):
    """Call whatever the table cannot account for, and the test must not be identical.

    The channel is computed, not written: :func:`_an_unaccounted_stdlib_callable` asks the engine which callable
    it has no rule for. So this test keeps working when the table grows, and it never encodes a channel list.
    """
    mod, name = _an_unaccounted_stdlib_callable()
    proj = _project(tmp_path, {"tests/test_x.py": f"""
        import {mod}

        def test_calls_what_the_engine_cannot_account_for(tmp_path):
            p = tmp_path / "f"
            p.write_bytes(b"x")
            try:
                {mod}.{name}(str(p))
            except Exception:
                pass            # whether it succeeds is beside the point: the engine saw the call
    """})
    traces = []
    for i in (1, 2):
        t = tmp_path / f"d{i}.jsonl"
        r = _run(proj, t, _env())
        assert t.exists(), r.stdout[-3000:] + r.stderr[-3000:]
        traces.append(t)
    v = _verify(proj, traces)
    assert v.returncode != 0, (
        f"IDENTICAL although the test called {mod}.{name}, which the engine's own table says it cannot "
        f"account for\n{v.stdout}")
    assert "NOT PROVEN" in v.stdout, v.stdout
    assert f"{mod}.{name}" in v.stdout, f"the verdict does not name what was not accounted for\n{v.stdout}"


# ---------------------------------------------------------------------------------------------------------------
# 4. An invented native channel: the finish line
# ---------------------------------------------------------------------------------------------------------------

_EXT_C = r"""
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>

/* Reads a file in C. There is no Python call and no audit event anywhere in here, so no in-process sensor can
   see this read -- which is exactly why a test that loads an extension nobody audited must be NOT PROVEN. */
static PyObject *peek(PyObject *self, PyObject *Py_UNUSED(ignored)) {
    const char *path = getenv("ATK_FILE");
    char buf[128];
    memset(buf, 0, sizeof buf);
    if (path) {
        FILE *f = fopen(path, "r");
        if (f) {
            if (!fgets(buf, (int)sizeof buf, f)) { buf[0] = 0; }
            fclose(f);
        }
    }
    return PyUnicode_FromString(buf);
}

static PyMethodDef Methods[] = {
    {"peek", peek, METH_NOARGS, "read outside state in C"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "%(name)s", NULL, -1, Methods, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit_%(name)s(void) { return PyModule_Create(&module); }
"""


def _build_extension(where: Path, name: str) -> Path:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler: the invented native channel cannot be built here")
    inc = sysconfig.get_paths()["include"]
    if not os.path.exists(os.path.join(inc, "Python.h")):
        pytest.skip(f"no Python headers in {inc}: the invented native channel cannot be built here")
    src = where / f"{name}.c"
    src.write_text(_EXT_C % {"name": name})
    so = where / f"{name}{sysconfig.get_config_var('EXT_SUFFIX') or '.so'}"
    r = subprocess.run([cc, "-shared", "-fPIC", f"-I{inc}", "-o", str(so), str(src)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        pytest.skip(f"the C compiler could not build the extension: {r.stderr[-800:]}")
    return so


def test_an_invented_native_channel_is_not_proven_and_not_identical(tmp_path):
    """The channel the engine knows nothing about, built at test time, with a name generated at test time.

    A C extension module called ``atk_<random>`` reads a file in C. Nothing about it exists anywhere in the
    engine: not in the accounting table, not in the audited native list, not in any channel rule. The two runs
    see **different bytes**, and no sensor in the process can see the read at all.

    So the engine cannot know the runs differed -- and that is the whole point. It must not answer IDENTICAL. It
    must answer NOT PROVEN, which is what forces the rerun that would catch the difference.

    Before this rule existed the verdict here was IDENTICAL: file content leaves no trace of any kind
    (MEASURED on ``claude/release-1`` by the parallel measurement session, docs/REPORT-measure-provable.md), and
    a C-level read leaves even less.
    """
    name = "atk_" + "".join(random.Random().choice(string.ascii_lowercase) for _ in range(8))
    proj = _project(tmp_path, {"tests/test_x.py": f"""
        import os
        import {name}

        def test_reads_outside_state_in_c():
            v = {name}.peek()
            with open(os.environ["ATK_OUT"], "w") as fh:
                fh.write(repr(v))
    """})
    proj.mkdir(parents=True, exist_ok=True)
    _build_extension(proj, name)

    secret = tmp_path / "secret.txt"
    # one output path and one secret path for both runs: every environment variable the test reads must have the
    # same value in both, or the verdict would be INPUT DIFFERS for that variable and the invented channel would
    # never be reached. The only difference between the runs is the *content* of the secret file.
    out = tmp_path / "observed.txt"
    observed, traces = [], []
    for i in (1, 2):
        secret.write_text(f"run-{i}-value\n")      # the only thing that differs between the runs
        out.unlink(missing_ok=True)
        t = tmp_path / f"n{i}.jsonl"
        r = _run(proj, t, _env({"ATK_FILE": str(secret), "ATK_OUT": str(out)}))
        assert t.exists(), r.stdout[-3000:] + r.stderr[-3000:]
        assert out.exists(), r.stdout[-3000:] + r.stderr[-3000:]
        observed.append(out.read_text())
        traces.append(t)

    # the attack really did change what the test saw -- otherwise it proves nothing
    assert observed[0] != observed[1], f"the invented channel did not change what the test observed: {observed}"

    v = _verify(proj, traces)
    assert v.returncode != 0, (
        f"IDENTICAL although the test observed {observed[0].strip()} in one run and {observed[1].strip()} in the "
        f"other, through a channel the engine knows nothing about. This is the wrong green the rule exists to "
        f"prevent.\n{v.stdout}")
    assert "NOT PROVEN" in v.stdout or "DIVERGENT" in v.stdout, v.stdout
    assert name in v.stdout, f"the verdict does not name the extension it could not account for\n{v.stdout}"


def test_the_invented_native_channel_is_refused_even_when_nothing_differs(tmp_path):
    """The same extension, with the two runs seeing the *same* bytes.

    Nothing differs, so nothing is there to be caught -- and the verdict must still be NOT PROVEN, because the
    engine cannot see what the extension did. A rule that only refuses when it happens to notice a difference is
    not a rule; this is what makes the refusal unconditional.
    """
    name = "atk_" + "".join(random.Random().choice(string.ascii_lowercase) for _ in range(8))
    proj = _project(tmp_path, {"tests/test_x.py": f"""
        import {name}

        def test_reads_outside_state_in_c():
            assert isinstance({name}.peek(), str)
    """})
    proj.mkdir(parents=True, exist_ok=True)
    _build_extension(proj, name)

    secret = tmp_path / "same.txt"
    secret.write_text("identical in both runs\n")
    traces = []
    for i in (1, 2):
        t = tmp_path / f"s{i}.jsonl"
        r = _run(proj, t, _env({"ATK_FILE": str(secret)}))
        assert t.exists(), r.stdout[-3000:] + r.stderr[-3000:]
        traces.append(t)
    v = _verify(proj, traces)
    assert v.returncode == 1, f"expected NOT PROVEN (exit 1), got {v.returncode}\n{v.stdout}"
    assert "NOT PROVEN" in v.stdout, v.stdout
    assert name in v.stdout, v.stdout


# ---------------------------------------------------------------------------------------------------------------
# 5. The cache must not reuse what the rule refuses
# ---------------------------------------------------------------------------------------------------------------

def test_the_cache_never_reuses_a_test_the_rule_refuses(tmp_path):
    """A result the rule will not call identical must not come back as "reused" either.

    "Reused" is as much a claim about the engine's certainty as "identical" is, and the founder's rule covers
    both: whatever the cache cannot observe with certainty forces a rerun. The channel here is derived from the
    engine's own table, as in :func:`test_a_channel_derived_from_the_engines_own_table_is_not_proven`, so this
    test names none either.
    """
    mod, name = _an_unaccounted_stdlib_callable()
    proj = _project(tmp_path, {"tests/test_x.py": f"""
        import {mod}

        def test_clean():
            assert sum(range(10)) == 45

        def test_reaches_what_the_engine_cannot_account_for(tmp_path):
            p = tmp_path / "f"
            p.write_bytes(b"x")
            try:
                {mod}.{name}(str(p))
            except Exception:
                pass
    """})
    cache = tmp_path / "cache"
    out = tmp_path / "o.json"
    for i in (1, 2):
        r = subprocess.run(
            [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
             f"--det-cache={cache}", f"--det-outcomes={out}", "tests"],
            cwd=proj, env=_env(), capture_output=True, text=True, timeout=900)
        assert out.exists(), r.stdout[-3000:] + r.stderr[-3000:]
        data = json.loads(out.read_text())
        cache_part = data.get("cache") or {}
        reused = set(cache_part.get("reused_ids") or [])
        if i == 2:
            # the clean test may be reused; the one that reached an unaccounted callable must not be
            bad = [t for t in reused if "cannot_account_for" in t]
            assert not bad, f"the cache reused a test the rule refuses: {bad}\n{json.dumps(cache_part)[:1500]}"
