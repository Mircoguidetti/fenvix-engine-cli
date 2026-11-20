# PY1 notes (Python part 1: interpreters, packaging / first use, runners other than pytest internals)

Audited: engine `claude/release-1` (worktree /home/user/audit/engine), wheel
`/home/user/audit/build/dist/detpy-0.1.0-cp39-abi3-linux_x86_64.whl`. Scratch: `/home/user/audit/work/PY1/`
(logs in `logs/`, venvs in `venvs/`, projects per topic). Date 2026-11-20. Machine: Linux 6.18 x86_64 container,
no seccomp filter (`Seccomp: 0`), `/proc/self/personality` 00000000, no Docker daemon.

(work in progress: sections are appended as the audit proceeds)

## 1. Interpreter x feature table (all RAN; logs/mx-<label>.log)

Project: scratch `proj/` (18 tests: time, datetime, random, uuid4/uuid1, os.listdir, set order, id(), socket connect,
order-dependent pair, a unittest.TestCase). Default pytest that pip resolves per interpreter, pytest-xdist 3.8.0.

| interpreter | wheel install | `pytest --det` x2 + verify | `--det-seed=7` x2 | `--det-cache` x2 | `-n 2 --det` | `--det-isolate` | `python -m detpy unittest --det` x2 + verify | re-exec / ASLR here |
|---|---|---|---|---|---|---|---|---|
| CPython 3.9.25 (pytest 8.4.2) | ok | FAILS: collection error `AttributeError: 'code' object has no attribute 'co_qualname'` (plugin.py:567), rc=2 | FAILS same | refused, clear: `ERROR: --det-cache needs Python 3.12+ (sys.monitoring)` rc=4 | FAILS: INTERNALERROR (co_qualname) rc=3 | FAILS: INTERNALERROR (co_qualname) rc=3 | FAILS: `ImportError: attempted relative import with no known parent package` (re-exec runs `__main__.py` as a script); the `detpy` console script works | re-exec ok, ASLR off; only `--det-no-reexec` lets pytest run (hash seed not fixed) |
| CPython 3.10.20 (pytest 9.2.0) | ok | FAILS: same co_qualname collection error | FAILS same | refused, clear message, rc=4 | FAILS: INTERNALERROR | FAILS: INTERNALERROR | works, verify 4/4 covered | re-exec ok, ASLR off |
| CPython 3.11.18 | ok | works; verify 17 covered, 1 not covered (uuid4: entropy, by design) rc=1 | works, same digest | refused, clear message, rc=4 | works (18 passed), merged trace = serial except uuid4 | works (order-dependent test fails, as designed) | works | ok, ASLR off |
| CPython 3.12.3 | ok | works (17 covered + uuid4) | works | works: run 2 reuses 3 of 18 (14 "after an earlier test or fixture of this process", 1 entropy) | works | works (+ PytestRemovedIn10Warning from isolate.py:187) | works | ok, ASLR off |
| CPython 3.13.18 | ok | works | works | works (3 of 18 reused) | works | works (+ warning) | works | ok |
| CPython 3.14.6 | ok | works | works | works (3 of 18 reused) | works | works (+ warning) | works | ok |
| CPython 3.13.14t (free-threaded) | REFUSED by pip: `detpy-0.1.0-cp39-abi3-linux_x86_64.whl is not a supported wheel on this platform.` Source build fails: `PyO3 does not support the free-threaded build of CPython versions below 3.14`. Forced onto sys.path: `SystemError: init function of _core returned uninitialized object` | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| CPython 3.14.6t (free-threaded) | abi3 wheel REFUSED (same message). Built from the sdist here (cp314-cp314t wheel, ~9 min, needs Rust): then everything in this row works | works (source build) | works | works (3 of 18) | works | works (+ warning) | works | ok; GIL stays disabled after import |
| PyPy 3.11 | COULD NOT RUN (download of PyPy refused by the proxy; a second route was denied). From the code: cp39-abi3 wheel is not a PyPy tag; `_patch.py:39-55` uses CPython internals; no sys.monitoring | - | - | - | - | - | - | - |

Silent degradations seen: none in the table itself (every failure is loud); but see PY1-011 (ASLR stays on under a
seccomp profile, only the header says so), PY1-012 (cold vs warm run differ in address-dependent order),
PY1-033/034 (`--det-seed` / `--det-isolate` ignored without `--det`).

**STOPPED EARLY on the coordinator's budget instruction (2026-11-20).** Part 1 (interpreters) and part 2
(packaging / first use) were run almost completely; part 3 (runners) was only started: one unittest project was run,
every other runner entry in `PY1.gaps.jsonl` is `READ` or `DOC` (said in each entry). See section 4 "Not covered".

Extra pytest-version rows (py3.12, RAN, logs/pt-*.log):

| pytest | `--det` x2 + verify | `--det-seed` | `--det-cache` run 2 | `-n 2 --det` (xdist 3.8.0) | `--det-isolate` on a unittest.TestCase |
|---|---|---|---|---|---|
| 7.0.0, 7.1.3, 7.2.2 | works (44 DeprecationWarnings from pytest itself on 7.0-7.2) | works | INTERNALERROR `TestReport.__init__() takes from 7 to 10 positional arguments but 12 were given` (PY1-025) | works | 4 setup ERRORS "recursive dependency involving fixture '_unittest_setUpClass_fixture_UT'" (PY1-026) |
| 7.3.2, 7.4.4, 8.0.0 | works | works | works (3 of 18 reused) | works | 4 setup ERRORS (PY1-026) |
| 8.1.2, 8.2.2, 8.3.5, 8.4.2 | works | works | works | works | works |
| 9.2.0 | works | works | works | works | works + PytestRemovedIn10Warning (PY1-027) |

pytest-xdist versions with pytest 7.4.4 (`pytest --det -n 2`): 2.5.0 INTERNALERROR (`No module named 'py.log'`),
3.0.2 / 3.3.1 / 3.5.0 / 3.6.1 INTERNALERROR (`cannot import name 'parse_tx_spec_config'`), 3.7.0 and 3.8.0 work (PY1-028).

## 2. Runner x feature table (for PY3 to merge)

Cells: what I observed. "not checked" = not run by me (stopped early); "none (READ)" = the code has no such path.
Columns: det x2 + verify identical | seeded shuffle | repro / replay / explore | `--det-cache` reuse | shared cache |
receipts | isolate | parallel.

| runner | det x2 + verify | seeded shuffle | repro / replay / explore | cache reuse | shared cache | receipts | isolate | parallel |
|---|---|---|---|---|---|---|---|---|
| pytest (`python -m pytest` and `pytest` script) | done RAN on 3.11-3.14 (17/18 covered, uuid4 = entropy by design); broken on 3.9/3.10 (PY1-001/002) | done RAN (`--det-seed=7` twice, same digest) | not checked (CLI help only) | partial RAN: 3 of 18 on the audit project (PY1-044) | not checked | done RAN (receipts.jsonl written; reason text PY1-045) | done RAN on pytest >= 8.1 (PY1-026/027) | done RAN `-n 2` with xdist >= 3.7 (PY1-028); PY2 owns it |
| unittest.TestCase run by pytest | done RAN (tests/test_ut.py in the matrix project) | done RAN | not checked | not checked separately | not checked | not checked | partial: errors on pytest 7.0-8.0 (PY1-026) | done RAN (part of the -n 2 run) |
| `python -m detpy unittest` (discover, subTest, setUpModule/setUpClass, skip, expectedFailure, IsolatedAsyncioTestCase) | done RAN on 3.10-3.14: 13 tests, verify "covered 13, not covered 0" rc=0 (scratch ut/); broken on 3.9 via `python -m` (PY1-003) | not checked | none (READ, PY1-050) | partial RAN: entropy test blocks later classes (PY1-048); class is the unit (PY1-053) | not checked | done RAN (receipts.jsonl written) | none (READ, PY1-052) | none (READ, PY1-051) |
| plain `python -m unittest` / `python test_x.py` | missing (READ, PY1-049) | missing | missing | missing | missing | missing | missing | missing |
| Django `manage.py test` via `python -m detpy django` | not checked | not checked | none (READ, PY1-058) | not checked (docs: sqlite only PY1-056, env in key PY1-057) | not checked | not checked | none (READ) | none: `--parallel` forced to 1 (READ, PY1-054) |
| pytest-django | not checked (incl. the database-first ordering fix: tests/test_django_order.py exists, not run by me) | not checked | not checked | not checked | not checked | not checked | not checked | not checked |
| nose2 | not checked | not checked | none (READ, PY1-061) | not checked | not checked | not checked | none (READ) | refused: `-N` usage error (READ, PY1-059) |
| ward | not checked | not checked | none (READ, PY1-065) | not checked | not checked | not checked | none (READ) | none (READ) |
| zope.testrunner | not checked | not checked | none (READ, PY1-063) | not checked | not checked | not checked | none (READ) | none: `-j` forced to 1 (READ, PY1-062) |
| doctest (`python -m detpy doctest`) | not checked | not checked | none (READ) | not checked | not checked | not checked | none (READ) | none (READ) |
| doctest via `pytest --doctest-modules` / .rst / .md | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked |
| hypothesis (under pytest / unittest) | not checked (seed per test id, `deadline` on the virtual clock, `@seed`, different examples per `--det-seed`: none run) | not checked | not checked | not checked | not checked | not checked | not checked | not checked |
| behave | missing (READ, PY1-068) | missing | missing | missing | missing | missing | missing | missing |
| pytest-bdd | not checked (a pytest plugin: expected to run under the pytest shell) | not checked | not checked | not checked | not checked | not checked | not checked | not checked |
| robotframework | missing (READ, PY1-069) | missing | missing | missing | missing | missing | missing | missing |
| twisted.trial | missing (READ, PY1-070) | missing | missing | missing | missing | missing | missing | missing |
| green | missing (READ, PY1-071) | missing | missing | missing | missing | missing | missing | missing |
| unittest-parallel | missing (READ, PY1-072) | missing | missing | missing | missing | missing | missing | missing |
| stestr / testtools | missing (READ, PY1-073) | missing | missing | missing | missing | missing | missing | missing |
| tornado.testing | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked |
| tox / nox environments | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked |

## 3. Could not check

* **PyPy**: `uv python install pypy3.11` => "Failed to download https://downloads.python.org/pypy/pypy3.11-v7.3.23-linux64.tar.gz
  ... tunnel error: unsuccessful" (proxy 403). A second route (PyPy packages from the Ubuntu archive unpacked into
  scratch) was denied by the session's permission system. PY1-009 is therefore READ only: the exact message a PyPy
  user sees is unverified.
* **Docker / Alpine / old-glibc images**: no Docker daemon (`docker ps` => "failed to connect to the docker API at
  unix:///var/run/docker.sock"). musllinux (PY1-019) and glibc < 2.34 (PY1-018) are reasoned from the wheel
  (`auditwheel show`), not run. ASLR under Docker's default seccomp profile (PY1-011) was simulated with
  `strace -e inject=personality:error=EPERM`, not run in a real Docker container; the claim that Docker's default
  profile denies `personality(ADDR_NO_RANDOMIZE)` is from my knowledge of that profile, not checked here.
* **PyPI upload rejection of `linux_x86_64`** (PY1-017): known PyPI rule, not tried (nothing may be uploaded).
* **Thread safety on free-threaded 3.14t** (PY1-030): only the single-threaded matrix was run.
* **`--det-isolate` labelling of order-dependent tests as findings** (DECISIONS 2026-11-20): I only saw the tail of
  the output (`FAILED tests/test_basic.py::test_order_b`, "0 children failed"); whether a finding line is printed
  elsewhere was not checked. PY2 owns pytest internals.
* **MCP server** (promise item 4): `grep -rli mcp` over the engine's Python, docs and Rust finds no MCP server code
  (hits are only harness data, node lock file, one Go comment). Not my area and fenvix-app was not searched: for
  the lead to assign.

## 4. Not covered (stopped early; for another session to finish)

Task part 1 (interpreters):
* PyPy: any run (see above).
* `--det-cache` reuse on a project where reuse is expected to be high (my project reuses 3/18 because of PY1-044).
* 3.13t/3.14t beyond what is in the table; 3.14t thread safety.
* `PYTHONHASHSEED` re-exec / ASLR inside a real Docker container, inside tox and inside nox.

Task part 2 (packaging / first use):
* `docker run python:3.12-alpine` and an old-glibc image (no Docker here).
* `maturin build` without `--compatibility linux` (which manylinux tag maturin's own audit gives; only
  `auditwheel show` on the existing wheel was run: manylinux_2_34).
* Help text of `pytest --help` for the `--det*` group read in full (only the option table in `_level0.OPTIONS` was read).
* Environment variables: the list was extracted (`DETPY_DIR`, `DETPY_PYC_CACHE`, `DETPY_CACHE_SHARED`,
  `DETPY_REWRITE_CACHE`, `DETPY_VERBOSE`, `FENVIX_CACHE_TOKEN*`, ...) but none is documented in README/LIMITS as far
  as I read, and none was exercised.
* `detpy repro` / `explore` / `replay` on a real flaky test (only `--help` and a non-existent id).
* `.hypothesis/`, cassette and `--det-cache=DIR` directories written into the repository (only `.detpy/` was looked at).

Task part 3 (runners): everything except the one unittest run. Not run at all:
* unittest: `--det-seed` shuffle, `--det-cache` on the ut/ project, a failing order-dependent replay, `load_tests`.
* Django: `manage.py test`, pytest-django, `DiscoverRunner`, `--parallel`, TransactionTestCase/TestCase
  database-first ordering under `--det-seed` (DECISIONS 2026-11-16 N6: LIMITS O2 says fixed, test
  `tests/test_django_order.py`; NOT verified by me), LiveServerTestCase, USE_TZ/TIME_ZONE. A venv with Django 6.1.3,
  pytest-django 4.14.0, nose2 0.16.0, zope.testrunner 8.4, hypothesis 6.170.17 is ready at `work/PY1/venvs/r`.
* nose2, ward, zope.testrunner, doctest (`python -m detpy doctest`, `pytest --doctest-modules`, .rst/.md).
* hypothesis: reproducibility under `--det`, different examples under different `--det-seed`, `deadline` under the
  virtual clock, `@seed`, `derandomize`, replay of a failing example, `.hypothesis/` handling.
* behave, pytest-bdd, robotframework, green, unittest-parallel, testtools/stestr, twisted.trial, tornado.testing:
  the "missing" entries are from the RUNNERS table only; whether the unittest shell can host trial/tornado/testtools
  cases was not tried.
* tox (`tox -e py312 -- --det`), nox, `pytest --pyargs`. (`python -m pytest`, the `pytest` script and
  `-p no:cacheprovider` were used throughout the matrix and work.)
* Verification by running of every claim in docs/ALL-RUNNERS.md and docs/runners/*.md: none verified by running;
  the entries PY1-053, 056, 057, 060, 066 are DOC, the others READ.

## 5. Evidence appendix (trimmed real outputs)

**A1 (PY1-001..005, 074) Python 3.9 / 3.10.** `logs/mx-py39.log`, `logs/mx-py310.log`.
```
$ venvs/py310/bin/python -m pytest --det -q -s -p no:cacheprovider --det-trace=.detpy/t1.jsonl
detpy/plugin.py:567: in code
    return (f"code({co.co_qualname}|{co.co_argcount},...
E   AttributeError: 'code' object has no attribute 'co_qualname'. Did you mean: 'co_filename'?
ERROR tests/test_basic.py - AttributeError ...   3 errors in 2.69s   rc=2
$ venvs/py39/bin/python -m detpy unittest --det discover -s tests -p test_ut.py -t .
  File ".../site-packages/detpy/__main__.py", line 1, in <module>   from .cli import main
ImportError: attempted relative import with no known parent package      rc=1
$ venvs/py39/bin/detpy unittest --det discover ...   => Ran 4 tests ... OK   (console script works)
$ venvs/py310/bin/python -m pytest --det --det-no-reexec ... tests/test_other.py
detpy: PYTHONHASHSEED=None (PYTHONHASHSEED not fixed (--det-no-reexec)); ASLR on    4 passed
$ ... --det --det-disable=bytecode   and   PYTHONHASHSEED=0 ... --det     => same co_qualname error
$ venvs/py311/bin/python -m pytest --det --det-cache=.cache1 -q  => ERROR: --det-cache needs Python 3.12+ (sys.monitoring)  rc=4
```

**A2 (PY1-008, 010, 030) free-threaded.** `logs/mx-py313t.log`, `logs/ft-build.log`, `logs/ft14-build.log`, `logs/mx-py314tsrc.log`.
```
ERROR: detpy-0.1.0-cp39-abi3-linux_x86_64.whl is not a supported wheel on this platform.
error: PyO3 does not support the free-threaded build of CPython versions below 3.14, the selected Python version is 3.13
PYTHONPATH=<unzipped wheel> python3.13t -c "import detpy" => SystemError: init function of _core returned uninitialized object
3.14t: Successfully built detpy  (detpy-0.1.0-cp314-cp314t-linux_x86_64.whl); matrix: 18 passed, cache run 2 "reused 3"
```

**A3 (PY1-011) ASLR.** Here: `cat /proc/self/personality` => 00000000; `Seccomp: 0`; header "PYTHONHASHSEED=0 (ok); ASLR off".
```
$ strace -f -e trace=personality -e inject=personality:error=EPERM:when=2+ python -m pytest --det ... -k id_addr -s
detpy: PYTHONHASHSEED=0 (hash seed fixed; not applied: aslr (already re-executed)); ASLR on; network=block; sleep=virtual
1 passed      trace meta: "aslr_disabled":false
strace: personality(PER_LINUX|ADDR_NO_RANDOMIZE) = -1 EPERM (Operation not permitted) (INJECTED)
```
`--det-keep-aslr` and `--det-no-reexec` both run (4 passed) on 3.11-3.14.

**A4 (PY1-012) cold vs warm.** scratch `coldwarm/tests/test_addr.py` (a set of 16 plain objects, order printed), py3.12:
```
run 1 (first ever)   ORDER ijkalbcmndoepfgh
run 2, 3             ORDER hniacjfklbdmegop
after a comment-only edit: ORDER ghiajklobmcnedfp, then hniacjfklbdmegop
rm -rf .detpy, 3 times:    ORDER mgnocfphkbidalje (each time; next warm run: hniacjfk...)
```
Also `id(object())` in the matrix project: first run "I 3520", every later run "I 768".

**A5 (PY1-013..015) PyPI, 2026-11-20.**
```
$ pip download detpy==0.1.0 --no-deps -d x
ERROR: Could not find a version that satisfies the requirement detpy==0.1.0 (from versions: 1.0.7, 1.0.8, 1.0.9, 1.0.10, 1.0.11, 2.0.0)
$ pip download detpy --no-deps -d x   => Saved ./x/detpy-2.0.0-py3-none-any.whl
pypi.org/pypi/detpy/json: summary 'DetPy (Differential Evolution Tools): A Python toolbox for solving optimization
problems using differential evolution'; requires_dist numpy, opfunu, matplotlib, tqdm, scipy, sympy, autograd, pandas;
top_level.txt "detpy"; releases 2024-10-31 .. 2025-12-27
pypi.org/pypi/{fenvix,detjs,pytest-det,pytest-detpy,pytest-fenvix,fenvix-cli}/json => 404
```

**A6 (PY1-017, 018, 023, 024) wheel and sdist.**
```
WHEEL: Generator: maturin (1.16.0)  Tag: cp39-abi3-linux_x86_64
METADATA: Name detpy, Version 0.1.0, Requires-Dist: pytest>=7, License: MIT, Requires-Python: >=3.9 (no URLs, no author)
dist-info: METADATA RECORD WHEEL entry_points.txt sboms      entry_points: [console_scripts] detpy=detpy.cli:main  [pytest11] detpy=detpy.plugin
$ auditwheel show ... => consistent with "manylinux_2_34_x86_64" ... libc.so.6 with versions {GLIBC_2.33, GLIBC_2.34, ...}
$ maturin sdist (scratch copy) => detpy-0.1.0.tar.gz, 459 kB, 83 files, 0 licence files; twine check PASSED for both
`pip install <wheel>` pulls pytest (9.2.0 on 3.10+; 8.4.2 on 3.9), iniconfig, packaging, pluggy, pygments.
```

**A7 (PY1-025..028) pytest / xdist versions.** `logs/pt-70.log`, `pt-74.log`, `pt-80.log`, `pt-84.log`; tables in section 1.

**A8 (PY1-029) strace.** scratch `strc/` (one test starts `python -c`, one pure test):
```
with strace:    run 1 "reused 0 ..., ran 2, recorded 2"; run 2 "reused 2 result(s) with proof, ran 0"
PATH without strace, runs 1 and 2: "reused 0 result(s) with proof, ran 2, recorded 0 ...
   not cacheable: after an earlier test or fixture of this process 1, subprocess 1"      (no line about strace)
```

**A9 (PY1-031, 032) precompile.** `--det-seed=901`: header "PYTHONHASHSEED=901 (ok)", "precompile_s":13.006 (MEASURED,
this machine, shared), `~/.cache/detpy/pyc/cpython-312-hashseed901` 27M. First-run precompile: 5.946 s (3.12),
23.318 s (3.9). `du -sh ~/.cache/detpy` 1.2G (20 `<tag>-hashseedN` directories from all agents' runs). README/LIMITS
R2 say "~3 s the first time ... ~100 MB of cache".

**A10 (PY1-033..041, 047) CLI.**
```
$ detpy --version => detpy: error: the following arguments are required: cmd   rc=2
$ detpy nose2 --det => ModuleNotFoundError: No module named 'nose2' (traceback)   rc=1
$ detpy unittest --help => usage: python -m unittest [-h] [-v] [-q] ...   (no --det options)
$ detpy unittest --det --help => unittest help, then "trace: ...  order digest: None  seed: 0"
$ detpy unittest --det-sed=3 discover => python -m unittest: error: unrecognized arguments: --det-sed=3
$ pytest --det-seed=3 -q tests/test_other.py => 4 passed (no detpy section)
$ pytest --det-isolate -q tests/test_other.py => 4 passed (no isolate line)
$ pytest --det --det-disable=clock => ERROR: --det-disable: unknown control(s) ['clock']; known: (...)   (good message)
$ pytest --det --det-epoch=yesterday => ERROR: --det-epoch: Invalid isoformat string: 'yesterday'
$ detpy verify .detpy/t1.jsonl nonexist.jsonl => Traceback ... FileNotFoundError: No such file or directory (os error 2)
$ detpy replay nonexist => Traceback ... FileNotFoundError: ... 'nonexist/bundle.json'
$ detpy repro tests/test_nope.py::test_x --max-runs 3 --seeds 1 => "not-collected / None pytest runs, None s"
```

**A11 (PY1-042, 043) configuration and state.** `pytest.ini addopts = --det --det-seed=5` => works ("seed: 5
(shuffled)"); `PYTEST_ADDOPTS=--det` works; `[tool.detpy]` ignored; `[tool.pytest.ini_options] det = true` =>
"Unknown config option: det"; `DETPY=1` ignored. After `pytest --det -n 2`: `git status --short` => `?? .detpy/`
(durations.json, plan.json, trace.gw0.jsonl, trace.gw1.jsonl, trace.jsonl).

**A12 (PY1-044, 045, 048) entropy blocks later tests.** scratch `poison/`:
```
$ pytest --det --det-cache=.c tests/test_a.py tests/test_b.py   (2nd run)
reused 0 result(s) with proof, ran 4, recorded 0 ...   not reused: new 4
not cacheable: after an earlier test or fixture of this process 3, os entropy (not controlled; use --det-urandom) 1
receipts: {"nodeid": "tests/test_a.py::test_2_pure", "reused": false, "why": "new: no recorded result"}
$ python -m detpy unittest --det --det-cache=.cu tests/test_ut_poison.py   (2nd run)
reused 0 result(s) with proof, ran 3 ... not cacheable: after an earlier test or fixture of this process 2, os entropy ... 1
```

**A13 unittest shell works (no gap).** scratch `ut/` (13 tests: subTest, setUpModule, setUpClass, skip,
expectedFailure, IsolatedAsyncioTestCase with asyncio.sleep/gather, order-dependent pair), py3.12:
two `python -m detpy unittest --det discover -s tests -t .` runs, same order digest a8fb3824..., identical printed
values; `detpy verify` => "covered by Level 0: 13  not covered: 0  missing: 0", rc=0.

## 6. For the lead: contradictions between docs and code

* docs/RELEASE-1.md "Python 3.9-3.11: Level 0 only" / "3.9+ for `--det`": 3.9 and 3.10 cannot run `pytest --det` (PY1-001/002/074).
* docs/RELEASE-1.md names the wheel `...-manylinux_*_x86_64.whl`; the workflow builds `linux_x86_64` (PY1-017).
* docs/LIMITS.md R1 says the re-exec is "not possible ... on Python < 3.10 (`sys.orig_argv`)"; the code does re-exec
  on 3.9 by rebuilding the command line (header "PYTHONHASHSEED=0 (ok)"), and that rebuild is what breaks
  `python -m detpy <runner>` there (PY1-003).
* docs/LIMITS.md R3 says address-based hashes are deterministic with ASLR disabled; cold and warm runs differ (PY1-012).
* docs/LIMITS.md R2 "~3 s the first time ... ~100 MB of cache": MEASURED 5.9-23 s, and one such cache per
  `--det-seed` value (PY1-031).
* The release gate and all CI run Python 3.12/3.13 only (PY1-007), which is why the 3.9/3.10 crashes are unseen.
* Release gates still open per docs/RELEASE-1.md itself ("all-runners-2 REPORT-2 PARTIAL", "R-032b FAIL, fixes in
  progress"): the runner shells I could not run are on an engine whose own review had not passed.
* pytest's cache finding PY1-044 (one entropy test blocks reuse of all later tests) is in pytest internals
  (PY2/PY3 area); filed here because it is what a first-time user sees and it also holds in the unittest shell (PY1-048).
