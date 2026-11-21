# Prompt: cache inputs matrix (F-05), for a work session in fenvix-engine-cli

You are a work session on `mircoguidetti/fenvix-engine-cli`. Read `CLAUDE.md` of `fenvix-brain-cli` (work-session
rules). Everything you write is in English. Every number carries MEASURED / ESTIMATED / DECLARED / UNKNOWN.

## Goal

The Python proof cache (`--det-cache`) must report, for every test, the outcome a fresh uncached `--det` run reports,
while keeping its reuse (founder decision: no downgrade of the cache; fix it properly). Reviewers keep finding one
channel at a time (R-050, R-052, R-053). Do the systematic pass instead.

## Base

Branch `claude/py-cache` (PR #5), which carries the R-050, R-052 and R-053 fixes (K1 conftest/__init__ in the code
prefix, P real CPU count and host name in the key, E posix entropy controlled). Work on your own branch
`claude/cache-inputs` created from it, never on `claude/py-cache` or `claude/release-1`.

## Deliverable 1: `docs/CACHE-INPUTS.md`

One table, one row per channel through which a test's outcome can depend on something:

- code: test files, conftest.py, __init__.py, imported repository modules, modules outside the repository, plugins
  and entry points, pytest.ini / pyproject.toml / setup.cfg / tox.ini (addopts included), .pth files, sitecustomize
  and usercustomize;
- process state: module globals, C extension state, recursion limit, signal handlers, cwd, umask, warning filters,
  sys.path, sys.modules, the import system's caches;
- files read and written, including by child processes;
- environment variables, including those read at import or collection time;
- machine: real CPU count and affinity, host name, uname, locale, time zone, resource limits;
- time (clock, monotonic, file times);
- entropy through os, posix, secrets, random, ssl, uuid and C code;
- network (sockets, name resolution, loopback services).

Columns: channel; the rule the cache applies (in the key / refused / proven not to matter, with the code location);
the attack test that covers it (file::name); state (covered / GAP). Every channel without a test is listed as a GAP.

## Deliverable 2: attack tests

For each channel at least one test in `tests/test_cache_inputs.py`: cold cached run, change that channel only,
warm cached run; assert the cached outcome of every test equals a fresh uncached `--det` run (and plain pytest where
it applies). Follow the shape of `tests/test_review_r052_pycache.py` and `tests/test_review_r053_pycache.py`
(no root conftest; `import helper`). Include a serial and a `-n 2` variant where placement can matter.

A test that finds a wrong result: fix the engine so it passes, keeping the reuse of tests the change cannot reach
(add a reuse assertion next to it). If a fix would drop reuse broadly, stop and write it in the report as a decision
for the founder with the measured cost.

## Rules

- Run locally only the targeted tests (the new file, `tests/test_review_r05*_pycache.py`, `tests/test_py_cache.py`,
  and the test files your engine changes touch) on Python 3.12, 3.13 and 3.14; GitHub runs the full suites.
- Never skip or disable a test to get green. Never push to `claude/release-1`. Do not edit `exam/`.
- Long runs in the background.
- Push once to `claude/cache-inputs`; report in `fenvix-brain-cli/sessions/2026-11-21-cache-inputs/REPORT.md`; in
  chat write only `Report ready: <path>`.
