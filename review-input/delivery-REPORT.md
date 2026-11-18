DONE

# Shared cache across machines (Block 4, part 2), session 2026-11-18

A result recorded with proof on one GitHub-hosted machine is now reused on another one: on three projects, job 2 on
a second machine reused **100% of what the same pair reuses on one machine**, every reuse checked by a full fresh
run, **0 wrong**. Two pieces: a runtime identity keyed on content (equal on equivalent machines, different when
behaviour can differ) and a self-hostable cache service with its client in the engine (`--det-cache=https://...`).

## Numbers against "Exit"

| exit item | result | label |
|---|---|---|
| cross-machine reuse on hosted runners > 90% of the same pair on one machine | **100%** on all three targets, in each of 3 workflow runs (table below) | MEASURED |
| 0 wrong, every reuse checked | full suite re-run without the cache after every job 2: **7,620 of 7,620** cross-machine reuses checked in run 3 (5,288 + 1,657 + 675), wrong **0**; same in runs 1 and 2 | MEASURED |
| identity tests green | `tests/test_runtime_id.py` 10 passed; whole engine suite **136 passed, 6 skipped** (baseline was 112 passed, 6 skipped) | MEASURED (this container) |

Hosted run 3, https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44264885597 (commit `8d606a2`;
MEASURED, one run per cell, GitHub-hosted 4-CPU machines):

| target, commit N -> N+1 | tests | job 2 on the same machine as job 1: reused | job 2 on another machine, from the service: reused | ratio | checked | wrong |
|---|---:|---:|---:|---:|---:|---:|
| pygments `9c436b34` -> `b6aaaca7` | 5,314 | 5,287 (99.4% of test time) | 5,288 (99.4%) | 100.0% | 5,288 | 0 |
| click `9c4dfda` -> `8b44edf` | 1,982 | 1,657 (79.1%) | 1,657 (77.7%) | 100.0% | 1,657 | 0 |
| marshmallow `d08471b` -> `5761bea` | 1,192 | 675 (74.2%) | 675 (72.7%) | 100.0% | 675 | 0 |

* Ratio of test time, both sides priced with the same recorded durations: pygments 10.032 s / 10.030 s, click
  2.305 / 2.305 s, marshmallow 0.732 / 0.732 s: 100.0% (MEASURED). (Durations measured on different machines differ
  by up to 30% on these sub-second suites, so they are not compared directly.)
* The one extra test reused across machines on pygments (`test_html_formatter.py::test_unicode_options`) missed on
  the one-machine side on a temporary-file dependency and was checked correct on the other side (MEASURED).
* Two different machines in every pair: different runner ids and boot ids, often different CPUs (e.g. click: AMD
  EPYC 9V74 then Intel Xeon 6975P-C; marshmallow: Xeon 8573C then EPYC 7763) (MEASURED, `summary.json` `machine`).
* Same runtime identity on both machines of every pair (pygments `b814e471`, click `545ff15b`, marshmallow
  `469fb98e`), while **the previous identity differed on every pair** (pygments `a500c44e` / `8b23f7da`, click
  `9d6f6e1c` / `20047403`, marshmallow `b354ba96` / `b71c7403`): the hosted failure of the runner prototype is
  reproduced and fixed in the same jobs (MEASURED).
* Runs 1 and 2 agree: run 1 (https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44262651294): pygments
  5,287 vs 5,288, marshmallow 675 vs 675, click on the first pair (`dd149eb` -> `fdb65f4`) 0 vs 0 (see "decided");
  run 2 (https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44263752890): pygments 5,287 vs 5,288,
  click 1,657 vs 1,657, marshmallow 675 vs 675; wrong 0 everywhere (MEASURED).
* Cost (run 3, MEASURED, one run, NOISY): pygments job 2 wall time 4.4 s on the same machine vs 8.5 s on the other
  machine: pull 2.4 s (9.9 MB received for 5,290 candidates), push 1.1 s. Job 1 push 4.1 s (10.6 MB, 5,311 entries,
  1,862 file and 1,747 set documents). Service database after both jobs ~33 MB (SQLite + WAL). click and marshmallow:
  pull 0.4 s / 0.3 s, push 0.2-0.8 s.
* Local check of the same comparison (this container, `runner/local-shared-demo.sh`, two "machines" = separate
  disks, homes and virtualenvs on one host): pygments 5,287 vs 5,287, marshmallow 675 vs 675, click 1,657 vs 1,654
  (the 3 read `HOME`, which the simulation sets differently per machine; on hosted runners it is equal), wrong 0
  (MEASURED).

## Part 1: runtime identity (`python/detpy/runtime_id.py`)

Which parts differed (MEASURED, runner prototype addendum + this session's hosted runs): only the engine's own
distribution, by its `RECORD` bytes; interpreter, libpython, libc, stdlib listing and every other distribution were
equal. The new identity keys every part on content:

* `python` (version, implementation, ABI, `sys.flags`, warn/X options, encodings, locale, time zone), `executable`
  (binary bytes), `native` (bytes of the whole dynamic-link closure of the interpreter, the stdlib's and every
  distribution's extension modules: libc, loader, libpython, libssl, libz, libffi, libsqlite3..., resolved like the
  loader: RPATH/RUNPATH with `$ORIGIN`, `LD_LIBRARY_PATH`, `/etc/ld.so.cache`, default dirs; named by file name),
  `libc` (glibc version + bytes), `stdlib` (bytes by relative path), `distributions` (name, version, bytes of every
  `RECORD`-listed file inside the site directory, without `RECORD`/`INSTALLER`/`REQUESTED`/`direct_url.json`/bytecode/
  `bin/` scripts), `site_loose` (unowned `.pth`/files in site dirs), `sys_path` (entries named relative to stdlib,
  site dirs, prefixes, project root). Editable install of the project under test stays out (its files are per-test
  inputs). Memoised per file by (dev, inode, size, mtime, ctime): 0.03-0.07 s warm, 0.3-0.5 s cold (MEASURED here).

Tests (`tests/test_runtime_id.py`, each identity computed in a separate interpreter process; all MEASURED green):

| case | identity |
|---|---|
| same packages, other venv paths, other installer records (RECORD with/without bytecode lines, INSTALLER, direct_url to another wheel path) | same (and the RECORD files really differ) |
| relocated copy of the interpreter + stdlib at another prefix | same |
| same libc bytes loaded from another directory (`LD_LIBRARY_PATH`, checked in `/proc/self/maps`) | same |
| editable project checked out at another path | same |
| Python 3.13.14 vs 3.13.18 (real interpreters) | different (`python`, `executable`, `stdlib`) |
| libc with other bytes, actually loaded by the process | different (`libc`, `native`) |
| installed package 1.0 vs 1.1 | different (`distributions`) |
| same version, one file changed (new wheel, or edited in place with RECORD untouched) | different |
| a changed stdlib file; a `.pth` file in site-packages; `PYTHONOPTIMIZE=1` | different |

## Part 2: cache service and client

* `python -m detpy.cache_service serve|token` (standard library only: HTTP + SQLite). Documents (`file` facts,
  `set` of files, `entry` of one test, `receipts` of one run) stored under the SHA-256 of their canonical JSON; the
  server recomputes it and refuses a mismatch. Append-only key log `(namespace, lookup key) -> entry` and run log;
  no update/delete in the API, SQLite triggers refuse them too. Per organization: a token belongs to one org;
  another org's documents, keys and runs are invisible even by address; read-only tokens; only token hashes kept.
* Client `--det-cache=https://host/<namespace>` (`python/detpy/remote_cache.py`): works on a local mirror directory,
  which is also the fallback (service down -> session continues, error reported; backlog pushed next time). Pull,
  just before the engine's reuse decision: newest 3 entries per lookup key (test id, config, runtime, epoch);
  candidates are checked exactly like local entries (the service never decides). Push: new entries with the file and
  set documents they need, then the key log, then the receipts. Token and client variables removed from the
  environment before tests run; Level 0's closed network suspended only around the client's own requests.
* `runner/fenvix-run --cache <URL>`; `runner/ci-project-env.sh`; `runner/local-shared-demo.sh`;
  `runner/shared-cache-compare`; workflow `.github/workflows/fenvix-shared-cache.yml`; `docs/SHARED-CACHE.md`.
* Tests `tests/test_shared_cache.py` (14, green): second machine reuses everything at the same commit, only unchanged
  tests after a code or data change, outcomes equal to a fresh run; another runtime never reuses; another org gets
  nothing; content addressing, append-only (API and database), read-only token, gzip bodies; service down ->
  local mirror; backlog pushed later; token invisible even to a test that enumerates the environment; a service on a
  non-loopback address is reachable under `--det` (fails without the fix); candidates checked after `.detpy/`
  exists; `fenvix-run` on two machines + verify.

## What I decided and why

* **Content, not paths or installers**: every installer-written file and every absolute path is out of the
  identity; everything that can change behaviour is in, including native libraries the interpreter and extensions
  link (libc by bytes, as the prompt asks). Same-image machines then agree without any machine-specific allowance.
* **Lookup key separate from the proof key**: the engine's entry key digests every recorded input, so it cannot be
  computed before the test runs. The service files entries under (test id, config, runtime, epoch) and returns
  candidates; the entry carries the proof key; the engine checks every candidate against current code and data.
* **File/set/entry documents**: first version embedded file sets in each entry: 197 MB of service data for pygments;
  with shared set documents it is ~31 MB, and documents are identical on every machine (pulled entries are not
  pushed back) (MEASURED locally).
* **Pull runs just before the engine's decision** (registered before the engine's plugin, `trylast`): run earlier, it
  saw the project before detpy created `.detpy/` and missed a test that lists the root (found locally, test added).
* **Service on each machine, data as an artifact** (allowed by the prompt): two hosted jobs cannot reach each other;
  machine 2 starts the service from machine 1's data directory. It exercises the real protocol, auth and storage;
  it is not a long-running deployment.
* **click pair changed** to `9c4dfda` -> `8b44edf` (one-line change inside a function): the first pair
  `dd149eb` -> `fdb65f4` changes a signature at module level in `testing.py` and reruns all 2,648 tests even on one
  machine (MEASURED, run 1), so it could not show a ratio.
* **uv pinned (0.11.32)** in the workflow: `_virtualenv.py` written by uv is part of `site_loose` (it runs at
  start-up); machines must create the same venvs.
* **Files**: new modules (`runtime_id.py`, `cache_service.py`, `remote_cache.py`) to stay out of the step-1
  session's files. Shared files touched minimally: `proofcache.py` one function (`runtime_identity` now delegates)
  and one docstring line; `plugin.py` six lines (import, URL to local mirror twice, hide the token, register the client). A trial rebase of my 8 commits onto `claude/cache-proof-step1`
  gives **one conflict, in `proofcache.runtime_identity`** (step 1 added a memo parameter there; my delegate accepts
  it). Not rebased: step 1 has not landed.

## What blocks or is missing

* Nothing blocks the exit.
* Trust: a token with write access can file a false "passed" entry for its organization; candidates are checked
  against code and data, but the recorded outcome is a claim. Next: signed entries per machine, or a sampled re-run
  of pulled hits.
* Data inputs outside the project (virtualenv files, the project root itself) are recorded by absolute path: machines
  must use the same work paths (true on hosted runners and `runs-on: fenvix`). Keying them relative to the prefix
  would need a change in `proofcache.py` (step-1 territory).
* Tests that enumerate the environment depend on all of it and rerun on another machine (none in these pairs).
* Libraries loaded only by `dlopen`/`ctypes` by name are outside the native closure.
* Pull fetches every candidate document of the collected tests (pygments ~10 MB, 2.4 s); a per-commit manifest or
  server-side filtering would cut it. Sized for tests and a small fleet (one Python process, SQLite).
* **Hygiene incident**: in runs 1 and 2 the throwaway service token was written to `$GITHUB_ENV` and GitHub printed
  it in later steps' `env:` blocks of the public logs. Those services existed only inside their jobs on localhost,
  so the tokens open nothing; fixed in run 3 (token file, never in `$GITHUB_ENV`). I did not delete the run logs
  (evidence); the coordinator may delete logs of runs 44262651294 and 44263752890 if preferred.

## Links

* Repository https://github.com/Mircoguidetti/fenvix-engine-cli, branch `claude/shared-cache` (from
  `claude/runner-prototype-ee21he`), last commit `da1afa9`.
* Code: `python/detpy/runtime_id.py`, `python/detpy/cache_service.py`, `python/detpy/remote_cache.py`,
  `python/detpy/plugin.py`, `python/detpy/proofcache.py`, `runner/fenvix-run`, `runner/ci-project-env.sh`,
  `runner/local-shared-demo.sh`, `runner/shared-cache-compare`, `.github/workflows/fenvix-shared-cache.yml`.
* Tests: `tests/test_runtime_id.py`, `tests/test_shared_cache.py`. Doc: `docs/SHARED-CACHE.md`.
* Actions runs: 44262651294, 44263752890, 44264885597 (all jobs green, about 3 minutes each, free minutes).
* No PR opened (not asked).

## Errors or gaps in the brain

* `NUMBERS.md` "Skip with proof" lists "runtime identity" among the closed holes; the runtime identity was correct
  but over-strict across machines (RECORD bytes), which blocked any shared cache. Worth a line next to the new
  numbers.
* The runner-prototype report's addendum guessed "another uv version" for the RECORD difference; this session pins
  uv and keys on content, so the cause no longer matters; the exact cause stays UNKNOWN.
