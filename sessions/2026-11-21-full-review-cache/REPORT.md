# R-056 full review: PR #5 (claude/py-cache @ 2b67ac0), Block 2, rows F-05, PY-05, PY-08

**FIX 11.** I found 9 families of wrong reuse (W1-W9) and 2 families where a test run under the cache gets a
different outcome than under uncached `--det` (W10, W11). Each one reports a test **passed, exit 0, where uncached
`pytest --det` with the same arguments fails it**, or the reverse for W10/W11.

- Two of them are **regressions brought in by PR #5**, both under `-n`. On the trunk e904824 those cases pass:
  - **W2** (collection-time effects of a later file under `-n 2`);
  - the `-n` variants of **W1** and **W3**.
- **W10** came with the branch's virtual-day epoch. That epoch is a recorded decision, so W10 is a conflict for the
  coordinator, not a code bug.
- The rest already happen on the trunk.
- The fixes for R-050, R-052 and R-053 all still hold.

Independent Opus reviewer, 2026-11-21. I changed no product code and pushed nothing to `claude/py-cache`.

## Verdict

| row | MERGE OK | why |
|---|---|---|
| F-05 | **no** | W1, W3-W9 are wrong reuses with serial runs, on 3.12, 3.13 and 3.14 (MEASURED). W10 and W11 are wrong outcomes of tests the cache runs |
| PY-05 | **no** | W2: 6 wrong reuses under `-n 2`, all new in this PR (the trunk passes them). The W1 and W3 `-n` variants are also new |
| PY-08 | **no** | W6: a test that calls native code (OpenSSL's `cafile`, libc's `getpwuid`) reads a file in C and is reused after the file changes. The ctypes and child-process cases hold (P3, P5, P6, P7) |

## Setup (MEASURED)

- **Wheel:** built from 2b67ac0 with `maturin build --release --compatibility linux` (abi3, one wheel for every
  version).
- **Venvs:** CPython 3.12.13, 3.13.18 and 3.14.6 (uv), each with pytest 9.2.0, pytest-xdist 3.8.0 and the wheel. For
  the in-repo test run I copied `_core` into `python/detpy`, as CI does.
- **Extra 3.13 venvs:**
  - `v3.13s`, for the site-packages attacks (W7). It is changed during those attacks, then restored;
  - one with numpy (entropy probes);
  - `vtrunk`, with a wheel built from the trunk **e904824**, for comparison.
- **Tools:** strace, setarch, unshare and gcc are present, and the user is root. The container is gVisor.
- **Harness:** `h56.py` in this folder. Each scenario does:
  1. writes the files and does a cold cached run (`--det --det-cache`);
  2. makes one change: files, a site-packages edit, environment, a `setarch`/`unshare` prefix, or cwd;
  3. does a warm cached run;
  4. compares the warm run with an **uncached `pytest --det` under the same arguments and context** (the verdict),
     and with plain pytest (shown as "vs plain").

  Modes: serial, `-n 2`, and `-n 1` (both files on one worker). The `bN_*.py` scripts are the attack batches. Their
  outputs are in `results/`. Some scripts take `HERE/` as this folder: replace it before running. b6, b8 and b11 need
  the local setup their header describes: a writable venv, root, and `unshare`.
- **Failing tests:** `tests/test_review_r056_pycache.py` on branch `claude/review-py-cache-r056`.

## Earlier findings (still hold)

| item | verdict | evidence (MEASURED) |
|---|---|---|
| R-052 S1, S3, C3, C5 | hold | `tests/test_review_r052_pycache.py`: 4 passed on 3.12, 3.13 and 3.14 |
| R-053 K1 (conftest/`__init__` next to an earlier test), P1/P2 (real CPU count and host name), E1 (`posix.urandom`) | hold | `tests/test_review_r053_pycache.py`: 9 passed on 3.12, 3.13 and 3.14 (13 for both files, `-n 4`) |
| R-050 P1/P2, late failure, in-process default, PY-08 test, g0160, g0163, g0510 | hold | `tests/test_py_cache.py -k "r050 or py08 or in_process_is_the_default or g0160 or g0163 or g0510"`: 12 passed on 3.13 |

## Failing tests: `tests/test_review_r056_pycache.py`

```
<venv>/bin/python -m pytest -q -p no:randomly -p no:cacheprovider -n 4 tests/test_review_r056_pycache.py
2b67ac0, 3.12.13: 33 failed      2b67ac0, 3.13.18: 33 failed      2b67ac0, 3.14.6: 32 failed
trunk e904824, 3.13.18: 17 failed, 16 passed
```

- Each test asserts its precondition: uncached `--det` gives the outcome the test names.
- Every failure is on the final assertion (MEASURED by counting the `AssertionError` lines):
  - 30 × `--det-cache reports ...` (29 on 3.14);
  - 1 × `reused while fresh --det runs read ...`;
  - 2 × `uncached --det: ...; --det-cache: ...`.
- 3.14 has one test fewer: the annotation case does not apply there (PEP 649).
- The 16 tests that pass on the trunk are all 6 W2 cases, the 6 W1 `-n` cases, the 3 W3 `-n` cases and W10.

Typical failure (W1, serial, 3.13):

```
E AssertionError: --det-cache reports {'tests/a/test_a.py::test_a': 'passed', 'tests/b/test_b.py::test_victim': 'passed',
  'tests/z/test_z.py::test_z': 'passed'} (exit 0); uncached --det fails tests/b/test_b.py::test_victim:
  reused 3 result(s) with proof, ran 0, recorded 0 ...
```

## Defects, ranked (wrong reuse first)

In every row the victim is `tests/b/test_b.py::test_victim`. Plain `pytest` and uncached `pytest --det` fail it with
exit 1, and the cached warm run reports it **passed, exit 0**, unless the row says otherwise. Base layout, as in
R-052/R-053:

- `helper.py`: `STATE = {'mode': 'good'}`;
- `tests/a/test_a.py`: `def test_a(): pass`;
- `tests/b/test_b.py`: asserts `helper.STATE['mode'] == 'good'`;
- `tests/z/test_z.py`: `def test_z(): pass`.

### W1: a conftest.py in a directory without collected test files (serial, `-n 1`, `-n 2`)

pytest imports every `conftest.py` of the directories it collects, before any test runs, even when the directory
holds no test file. `code_prefix_stale` (`_proof.py:1325`, `loaded_with`) only adds the conftest/`__init__` files of
the directories of *collected test files*. Layouts that break:

- `tests/c/` holding only `data.txt`;
- `tests/0/` (collected first);
- `tests/a/sub/` (a subdirectory of an earlier test's directory).

In each one, a new `conftest.py` that writes `helper.STATE` at import leaves `reused 3 result(s) with proof, ran 0`.
Realistic: `tests/helpers/conftest.py` and `tests/fixtures/conftest.py` are common.

- 2b67ac0: wrong in 9/9 cases (3 layouts × serial, n1, n2) on 3.12, 3.13 and 3.14.
- Trunk: wrong in the 3 serial cases; the `-n` ones pass.
- Fix direction (suggestion): digest every conftest.py and `__init__.py` pytest loaded in this session, and whether
  it exists, into every test's prefix. Or take pytest's own list (`pluginmanager._conftest_plugins`) plus the
  collected directories.

### W2: `-n 2` misses collection-time effects of a later file (REGRESSION in PR #5; PY-05)

Under `-n`, every xdist worker collects every file, so a later file's import-time code runs in the victim's worker
before the victim. Uncached `--det -n 2` fails the victim; the cache reuses it.

- **Serial** catches these cases only because the edited later test reruns and drags in every earlier test.
- **`-n`** does not drag them in. The only guard left is the AST import-effect check (`_import_effects`,
  `_proof.py:1227`), which misses all six changes below.

| change between run 1 and run 2 | `-n 2` | serial / `-n 1` | trunk `-n 2` |
|---|---|---|---|
| new `tests/z/conftest.py`, write at import | **passed, wrong** | correct | correct |
| new `tests/z/__init__.py`, write at import | **wrong** | correct | correct |
| `tests/z/test_z.py` gains `@helper.poison` (a bare decorator is "pure" for `_pure_expr`) | **wrong** | correct | correct |
| `test_z.py` gains `class TestZ(helper.Poison)` (`__init_subclass__` runs; bases count as pure) | **wrong** | correct | correct |
| `test_z.py` gains `def test_z() -> helper.poison()` (annotation evaluated at def time, 3.12/3.13) | **wrong** | correct | correct |
| new `tests/z/conftest.py` with `pytest_collection_modifyitems` writing the state | **wrong** | correct | correct |

Also wrong in the harness under `-n 2` (b1): a module-level annotation `X: helper.poison() = 1`, and a
`pytest_collection_finish` hook. Controls that hold, serial and `-n`:

- an effect in a default argument (A15);
- a later test's decorator module whose body changes (A16);
- its metaclass module (A18);
- a module imported by a later or an earlier conftest (A21, A21b).

The run 2 line in the A1 case: `plan ...: 2 workers (ran/planned gw0=0/2, gw1=1/1) ... reused by the controller: 2`.
The victim is reused, and only `test_z` reruns, for `code: tests/z/test_z.py (module level)`.

Fix direction: under `-n`, a test's prefix is every collected file, conftest and `__init__` of the session, not the
files before it. Or count decorators, class bases, keywords and annotations as effects in `_import_effect_nodes`, and
add conftest/`__init__` files to `_import_effects`.

### W7: installed code edited in place, version unchanged (serial and `-n 2`)

The runtime key holds each distribution as name and version (`runtime_identity`). A file changed under an unchanged
version is not seen. This happens with dependencies installed from a git branch, which keep the same version, with
patched site-packages, and with CI caches of a venv.

| case (venv `v3.13s`) | 2b67ac0 | trunk |
|---|---|---|
| G1: a distribution's module (`r056lib` 1.0, RECORD lists it) edited | **wrong** (serial, n2) | wrong |
| G8: an entry-point pytest plugin (`[pytest11]`) edited, sets state at import | **wrong** (serial, n2) | n/m |
| G7: a loose module in site-packages (no distribution) edited | **wrong** (serial, n2) | wrong |
| G5: the module an unchanged `.pth` runs (`import r056pth`) edited | **wrong** (serial, n2) | wrong |
| controls: sitecustomize added or edited; a `.pth` import line added | correct | n/m |

The opt-in `--det-cache-dists` makes G1 and G7 rerun (MEASURED, 3.13). The default does not. n/m: not measured.

### W5: the kernel release is not an input (serial and `-n 2`)

`process_identity()` keeps only `uname().nodename`. Under `setarch x86_64 --uname-2.6` the warm run reuses both
`platform.release()` and `posix.uname().release`, while uncached `--det` fails them. A runner image update changes
the kernel. Correct for `uname().machine` and `platform.machine()` under `setarch i686`.

### W6: files read by C code in the test process (serial and `-n 2`; PY-08)

- `ssl.create_default_context(cafile='ca.pem')`, and `SSLContext.load_verify_locations`. Replacing `ca.pem` with a
  bad PEM gives `reused 2 ... ran 0`, and the victim is reported passed.
- `pwd.getpwuid(0).pw_dir` with another `/etc/passwd` (bind mount): reused.

LIMITS 9 A1 calls this S1 ("what their C code reads stays S1"). But section 9's own rule is that "an input it cannot
see must not leave a reusable result behind", and these results are reused. Correct: sqlite3 (F7) and ctypes
libraries, from the repository or outside it (P6, P7); those are refused or recorded.

### W3: file metadata read through `posix` (serial; `-n 2` REGRESSION)

`posix.stat(p).st_size`, `posix.lstat(p).st_size`, `posix.access(p, F_OK)` and `posix.stat(p).st_mtime` are not
recorded. LIMITS 9 A3 rebinds every module global except `posix`.

- After changing the file size, removing the file or `utime`: reused, passed.
- The `os.*` equivalents are correct: `os.stat`, `os.access`, `os.path.getsize`, mtime.
- On the trunk the three `-n 2` variants are correct, so their failure under `-n` is new.

### W4: an allowlisted variable read through `posix.environ` (serial and `-n 2`)

`PWD` is on `ENV_ALLOWLIST`, so it is outside the process key, and `posix.environ` bypasses the per-test recording. A
test asserting `posix.environ[b'PWD']` is reused under another `PWD`.

Correct: `GITHUB_JOB` or `GITHUB_RUN_ID` read through `os.environ`, `os.environ._data` or `posix.environ`, at
import or at run time (E1, E12). In those runs the victim reran.

### W8: `_random.Random()` seeded from OS entropy in C (serial)

Four fresh `--det` runs gave 0.315, 0.611, 0.692 and 0.905, and the cache reuses the test (`reused=True`, b5).
`random.Random()`, `random.random()`, numpy (`default_rng()`, legacy, `RandomState()`, `SeedSequence()`),
`ssl.RAND_bytes`, uuid4, secrets, `os`/`posix.urandom` and `getrandom` are all controlled.

### W9: machine noise frozen (lowest; partly documented as LIMITS C7)

These values differ between fresh `--det` runs, and the cache reuses the test that reads them (b5):

- `resource.getrusage().ru_maxrss` (46608, 46736, 46692);
- `sys.getallocatedblocks()`;
- `os.getloadavg()`;
- `tempfile.mktemp()`: `/tmp/fenvix-det` or `/tmp/fenvix-det.1`, when another `--det` session runs at the same time.

The outcome flips only for a test that asserts on them, which is ESTIMATED rare. No failing test, except the
mechanism shared with W8.

### W11: a test the cache runs sees other object addresses than uncached `--det` (serial; also on the trunk)

The iteration order of a set of default-hash objects:

- three uncached `--det` runs: `[4, 5, 2, 3, 0, 1]` each time;
- two cold cached runs: `[2, 0, 3, 1, 5, 4]` each time.

`id()` and `hash(object())` differ the same way. A test asserting that order (a snapshot of a set's repr, for
example) passes under `--det` and fails under the cache, on every cached run (a failure is never reused). This is a
wrong outcome, not a wrong reuse.

### W10: the cache's epoch is not uncached `--det`'s (a conflict between a decision and the promise)

- Under `--det-cache` the clock starts at today 00:00 UTC (`_level0.epoch_for`, from 9f81fe2, following DECISIONS
  2026-11-19 "virtual-day clock").
- Uncached `--det` starts at the HEAD commit time, else 2025-01-01.
- In a directory outside git, `datetime.date.today()` is 2025-01-01 under `--det` and 2026-11-21 under the cache
  (MEASURED). The trunk gives 2025-01-01 for both.
- So any date-dependent test (expiry checks, LIMITS C6b) can pass under `--det` and fail under the cache, or the
  reverse.

This follows a recorded decision. The coordinator decides: either the exam's yardstick becomes "uncached `--det` at
the cache's epoch", or cached runs use `--det`'s epoch.

## Channel list: every channel checked

Held means the cached outcome equals uncached `--det` in every mode measured. Unless marked, all were MEASURED on
3.13, serial and `-n 2`; many also under `-n 1`. W-ids are also MEASURED on 3.12 and 3.14 through the failing tests.

| channel | case(s) | state |
|---|---|---|
| test file edited (earlier, same, later) | R-052 S1/S3/S5, A4 serial | held |
| conftest.py next to an earlier test (new, edited, import-time write, fixture) | R-053 K1, A24 | held |
| conftest.py in a directory without test files | W1 (3 layouts) | **broken** (serial, n1, n2) |
| conftest.py / `__init__.py` of a later directory | A1, A3 | held serial and n1; **broken n2** (W2) |
| later test file: decorator, class base, annotation | A4, A6, A6b, A14 | held serial and n1; **broken n2** (W2) |
| later test file: effect in a statement or default argument | A15 | held |
| conftest hooks (`collection_modifyitems`, `collection_finish`) | A11, A12 | held serial; **broken n2** (W2) |
| imported repository module (import-time code, decorator or metaclass module) | A7, A16, A18, A21, A21b | held |
| plugin module given by `-p` in addopts; `pytest_plugins` of the root conftest | A8, A9 | held |
| entry-point plugin edited, same version | G8 | **broken** (W7) |
| installed distribution's module edited, same version | G1 | **broken** (W7) |
| loose site-packages module edited | G7 | **broken** (W7) |
| `.pth` import line added | G4 | held |
| module run by an unchanged `.pth` | G5 | **broken** (W7) |
| sitecustomize added or edited | G2, G3 | held |
| usercustomize | — | not measured: venvs disable the user site (UNKNOWN) |
| pytest.ini, pyproject.toml, setup.cfg, tox.ini (filterwarnings, addopts) | I1-I4 | held |
| module globals of a repository module (earlier test, data-driven) | D2 | held |
| C extension state: decimal context, recursion limit, int max str digits, gc, switch interval | D8, D1/D1p, D23/D23p, D14/D14p, D29 | held |
| signal handlers | D6, D6p | held |
| cwd: chdir by an earlier test; another cwd with the same absolute arguments; relative open | D4, D4p, E3, E3b | held |
| umask | D5, D5p | held |
| sys.path, sys.modules, builtins | D10, D9/D9p, D22/D22p | held |
| warning filters (ini), logging config | I1, D7 | held |
| resource limits | D12, D32p | held |
| socket default timeout, locale set by an earlier test, `sys.dont_write_bytecode` | D26, D27, D31 | held |
| file written in-process, then read | D28, D33p | held |
| file read: open, `os.open`/`os.read`, `posix.open`/`posix.read`, sqlite3 | F1, F2, F7 | held |
| file metadata through `os.*` (stat, getsize, access, mtime) | E4b, E4d, E20, E11 | held |
| file metadata through `posix.*` (stat, lstat, access, mtime) | E4, E4c, E20b, E11b | **broken** (W3) |
| file read by C code (OpenSSL, libc nss) | E17, F3, H1 | **broken** (W6) |
| file read or written by a child process (in a test, or at conftest/module import) | F5, F6, P3, P5 | held |
| native library through ctypes (repository, outside) | P6, P7 | held (refused) |
| environment: os.environ write or delete by an earlier test; putenv | D3, D30, D3p | held |
| environment read at import or collection (allowlisted GITHUB_JOB, GITHUB_RUN_ID) | E12, E12b, E12c | held |
| allowlisted variable through posix.environ / `os.environ._data` (GITHUB_JOB) | E1, E1d | held |
| allowlisted PWD through posix.environ | E2 | **broken** (W4) |
| LANG / LC_ALL, TZ, /etc/localtime content | L1, T1, E9 | held (controlled) |
| real CPU count, host name through posix / _socket | R-053 P1, P2 | held |
| kernel release | E5, E5b | **broken** (W5) |
| machine (`uname().machine`, `platform.machine()`) | E6, E6b | held |
| RAM (`SC_PHYS_PAGES`), free disk | — | not measured: cannot be varied here (UNKNOWN) |
| time: wall, monotonic, perf, boottime, raw, process and thread time, `os.times`, uuid1 | b5 | held (controlled) |
| time: file mtime through os.stat | E11 | held |
| time: real clock through ctypes `time()` | b5 | held (refused) |
| time: the cache's epoch vs `--det`'s | W10 | **differs** (decision conflict) |
| entropy: os/posix urandom and getrandom, secrets, SystemRandom, uuid4, ssl.RAND_bytes, random, numpy, `/dev/urandom` | b5, b5b | held |
| entropy: `_random.Random()` C seed | W8 | **broken** |
| entropy: getpid, getppid, thread ident, socket fd number, str hash | b5 | held (deterministic) |
| addresses (`id`, default hash, set order) | W11 | **differs** (cached vs `--det`) |
| machine noise (getrusage, allocated blocks, loadavg, temp-dir suffix) | W9 | frozen (low) |
| network: name resolution with another /etc/hosts | E7, E7b | held (blocked under `--det`) |
| network: loopback services, sockets | — | not re-measured; R-052/R-053 and the refusal rule. UNKNOWN beyond that |
| installed packages: version bump | — | not measured separately; part of the runtime key by design (ESTIMATED held) |

Counts (MEASURED, harness, 3.13):

| batch | scenarios | wrong |
|---|---|---|
| b1 | 39 | 11 |
| b2 | 60 | 0 |
| b2b | 33 | 0 |
| b3 | 43 | 16 |
| b4 | 12 | 2 |
| b6 | 12 | 6 |
| b7 | 21 | 6 |
| b8 | 8 | 2 |
| b9 | 8 | 0 |
| b10 | 12 | 0 |
| b11 | 2 | 2 |
| b5 entropy probes | 33 | 5 frozen |
| b5b numpy probes | 4 | 0 frozen |

## Lost reuse (not defects)

- An edit to a test file reruns every earlier test of the process (b7 A4 serial: `test_a` and the victim rerun as
  "a predecessor of tests/z/test_z.py::test_z"). LIMITS 10 documents this cost.
- A failing victim reruns its carried set (E1, E1c): with GITHUB_JOB changed, `test_a` reran because the victim
  failed. With nothing failing, an allowlisted variable change reuses everything (MEASURED: `reused 1 ... ran 0`).
- Family D (b2, b2b): when an earlier test reruns because its data file changed, a later test in another file that
  imports nothing reruns too, serially. Sound, and needed in the cases where the earlier test touches interpreter
  state.

## Not done or not measured

- The full suites: GitHub's job (run 44921794369 green, DECLARED by the prompt).
- RAM and disk size, usercustomize, loopback services: UNKNOWN, listed above.
- The trunk comparison was measured on 3.13 only.

## Links

- Engine: `Mircoguidetti/fenvix-engine-cli`. Reviewed `claude/py-cache` @ 2b67ac0 (PR #5) against trunk
  `claude/release-1` @ e904824.
- Branch: `claude/review-py-cache-r056` (from 2b67ac0), with `tests/test_review_r056_pycache.py` and this folder
  (the harness, the attack batches, and `results/`). The R-052/R-053 test files are the PR's own, unchanged.

## Gaps in the brain or the prompt

- The promise ("the outcome that uncached `pytest --det` gives") conflicts with DECISIONS 2026-11-19 (virtual-day
  epoch under the cache): W10. One of the two should change.
- The cache-inputs session prompt (`PROMPT-cache-inputs.md`) lists `posix` entropy but not `posix`
  stat/access/environ, the kernel release, or C-level readers of the stdlib (`_ssl`, `pwd`). Those are the
  broken channels here.
