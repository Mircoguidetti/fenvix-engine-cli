# Shared cache across machines

A result recorded with proof on one machine is reused on another machine only when both have the same **runtime
identity** and every recorded input (code, data, environment, configuration) checks out on the second machine. Two
pieces make that work: a runtime identity keyed on content (`python/detpy/runtime_id.py`) and a cache service that
machines share (`python/detpy/cache_service.py`, client `python/detpy/remote_cache.py`).

## Runtime identity (`detpy.runtime_id`)

Equal on equivalent machines, different whenever behaviour can differ. Parts (each a digest):

| part | what | not |
|---|---|---|
| `python` | version string, implementation, ABI, `sys.flags` (`-O`, `-X utf8`...), warning options, encodings, locale, time zone | |
| `executable` | bytes of the interpreter binary | its path |
| `native` | bytes of every shared library in the dynamic-link closure of the interpreter, the stdlib's extension modules and every installed distribution's extension modules (libc, the loader, libpython, libssl, libz, libffi, libsqlite3...), resolved like the loader (RPATH/RUNPATH with `$ORIGIN`, `LD_LIBRARY_PATH`, `/etc/ld.so.cache`, default directories), named by file name | directories |
| `libc` | glibc version and the bytes of the libc actually resolved (also inside `native`) | |
| `stdlib` | bytes of every standard-library file by relative path | its location |
| `distributions` | per distribution: name, version, bytes of every file its `RECORD` lists inside the site directory | `RECORD` itself, `INSTALLER`, `REQUESTED`, `direct_url.json`, bytecode, scripts in `bin/` (installers write these per machine) |
| `site_tree` | every file under every site directory, by relative path and bytes, listed in a `RECORD` or not (packages copied in without metadata, files added to a package after installation, egg-info installs, `.pth` files) | bytecode, installer bookkeeping (`RECORD`, `INSTALLER`, `REQUESTED`, `direct_url.json`), the project's own editable install |
| `extra_paths` | content of import-path entries outside the project, the stdlib and the site directories (`PYTHONPATH`, `.pth` lines to `/opt/...`); an entry with more than 50,000 files is never reusable | |
| `sys_path` | the import path, each entry named relative to stdlib, site directories, prefixes or the project root | absolute paths (another directory keeps its path) |
| `native` (preload) | libraries `LD_PRELOAD` and `/etc/ld.so.preload` load ahead of libc (sanitizers, libfaketime, jemalloc), by bytes | their directories |
| `locale` | every category a test gets from `setlocale(LC_ALL, "")` (read by C, never through `os.environ`), `LANGUAGE`, the locale data (`LOCPATH` or `/usr/lib/locale`) | |
| `tz` | `TZ`, the zone file it names, `/etc/localtime`, `/etc/timezone` | |
| `cpu` | CPUs visible to the process, and the instruction-set level (x86-64 v1..v4; elsewhere the CPU feature list) | the CPU model |

The project under test, installed in editable mode, is left out: its files are per-test inputs.

The instruction-set level is keyed because native code that dispatches on CPU features (glibc's libm, numpy,
OpenBLAS) can return other floating-point results. It splits a mixed fleet into one cache per level (GitHub-hosted
runners mix AMD EPYC 7763, x86-64-v3, with AVX-512 machines, v4); on our own fleet the machines are chosen alike.
`FENVIX_RUNTIME_ISA=off` leaves it out: a deliberate choice for suites whose results cannot depend on it. File digests are
memoised by (device, inode, size, mtime, ctime) in `~/.cache/fenvix/runtime-memo-*.json` (`FENVIX_RUNTIME_MEMO`,
`off` to disable); a memo copied to another machine never applies there. `python -m detpy.runtime_id [ROOT]` prints
every part and the lists behind them.

Why: the previous identity hashed each distribution's `RECORD` file; two GitHub-hosted machines from the same image
produced different `RECORD` bytes for the engine's own wheel, so nothing recorded on machine 1 was reusable on
machine 2. `tests/test_runtime_id.py` proves the new rule: same packages at other paths through other installers,
a relocated copy of the interpreter and the same libc from another directory give the same identity; another Python
patch release, other libc bytes actually loaded, another package version, the same version with one changed file,
a changed stdlib file, a `.pth` file, `PYTHONOPTIMIZE`, the time zone and the ISA switch give a different one;
`tests/test_review_r008.py` (review R-008) adds unowned package directories, files outside a `RECORD`, egg-info
installs, modules on another import path, `LD_PRELOAD`, locale categories and the visible CPUs, two of them end to
end through the service.

## Cache service (`python -m detpy.cache_service`)

Standard library only (HTTP + SQLite), one data directory per deployment:

```bash
python -m detpy.cache_service token --data /srv/fenvix-cache --org acme      # prints a token once
python -m detpy.cache_service serve --data /srv/fenvix-cache --host 127.0.0.1 --port 8787
```

* **Content-addressed**: every document (`file` facts of one source-file version, `set` of files, `entry` of one
  test, `receipts` of one run) is stored under the SHA-256 of its canonical JSON; the server recomputes it and refuses
  a mismatch, so a stored document can never be replaced.
* **Append-only**: a key log `(namespace, lookup key) -> entry document` and a run log; no update or delete through
  the API, and SQLite triggers refuse them in the database too.
* **Per organization**: each token belongs to one organization; documents, keys and runs of another organization
  are invisible, even to a token that knows their address. Read-only tokens can look up but not write. Only the
  SHA-256 of each token is kept (`tokens.json`).
* The lookup key is (test id, configuration digest, runtime digest, clock epoch or empty); the entry document
  carries the engine's proof key (the digest of every recorded input).
* Put it behind a TLS reverse proxy outside a private network.

## Client (`--det-cache=https://host[:port]/<namespace>`)

```bash
FENVIX_CACHE_TOKEN=... pytest --det --det-cache=https://cache.example/acme/repo
# or: runner/fenvix-run --cache https://cache.example/acme --key acme/repo ...  (namespace = key + Python tag)
```

* The engine works on a **local mirror** directory (`FENVIX_CACHE_LOCAL`, default
  `~/.cache/fenvix/remote/<digest of the URL>`), which is also the fallback: when the service cannot be reached the
  session uses the mirror and reports the error; a cache problem never fails a test run. Entries recorded while the
  service was down are pushed by the next session (journal `remote-pushed.json`).
* **Pull** (just before the engine's reuse decision, after detpy created `.detpy/`): for each collected test, the
  newest entries under its lookup keys (up to 3) are fetched; a candidate goes into the local store only when the
  local entry does not already prove reuse, and is then checked exactly like a local entry. The service supplies
  candidates, never decisions.
* **Push** (end of session): every local entry not yet on the service, with the file and set documents it needs,
  then the key log, then the session's receipts linked to the run.
* The token: `fenvix-run` takes it (from `FENVIX_CACHE_TOKEN`, or the hand-off file `FENVIX_CACHE_TOKEN_FILE`,
  which it deletes once read) and hands it to pytest on an inherited pipe (`FENVIX_CACHE_TOKEN_FD`). Used directly,
  the engine accepts the same three sources and moves a `FENVIX_CACHE_TOKEN` into a pipe before it re-executes the
  interpreter. Before any test runs, the client closes the pipe, deletes the hand-off file and removes its
  variables: no token is left in the environment, `/proc/self/environ`, an open descriptor or a file.
  **What a test can still reach**: the client runs in the test process, so code that searches the process memory
  (or imports `detpy.remote_cache`) can find the token. Without `--det` re-execution (`--det-no-reexec`), a token
  given as `FENVIX_CACHE_TOKEN` also stays in `/proc/self/environ`. Hence the policy: **write tokens only for jobs on
  trusted refs** (default and protected branches); jobs that run untrusted code (pull requests, forks) get
  **read-only tokens**. `fenvix-run` does not pass client variables to the runs without the service (verify, rerun
  alone).
* Plain `http://` is refused to hosts other than loopback (the bearer token and documents would cross the network
  in clear) unless `FENVIX_CACHE_ALLOW_HTTP=1`. Level 0's closed network is suspended only around the client's own
  requests (process-wide for that moment: a thread a test left running could connect then).
* Every fetched document's address is recomputed and a mismatch is dropped, so a compromised service or anything on
  the path cannot substitute content under a known address. A candidate must list its test's own file among its
  inputs (floor check; every entry the engine records does).

## Untrusted keys (cache audit)

A cache audit (`docs/CACHE-AUDIT.md`) that finds a wrong skip marks its proof key **untrusted**. The client pushes the
mark before any entry (`POST /v1/ns/<ns>/untrusted`, any token of the organization: a mark only stops reuse); a lookup
then leaves out every entry filed under that key before the mark, and returns entries filed after it (a fresh run
that recorded the key again). `GET /v1/ns/<ns>/untrusted` lists the marks (`?after=SEQ` follows the log): every
client reads the marks it has not seen before its lookup and marks the entries its own mirror holds under those keys,
so a machine with a warm mirror stops reusing the wrong entry too. The client refuses a candidate whose `proof_key`
is not the key of its content, or whose `report` and `outcome` disagree. `GET /v1/audit` sums the audit counts per
namespace and over all of them, with the 95% upper bound on the wrong-skip rate (`checked`/`matched` from the
write-token run summaries, `wrong` from every token's jobs, including the untrusted log). Stores created before
the audit get the `untrusted` table and the `keys.proof_key` column on start; their old key rows have no proof key
and their documents none either, so the client no longer takes them (the next fresh run files them again).

## Measured (see the session reports)

GitHub-hosted machines, workflow `.github/workflows/fenvix-shared-cache.yml` (pygments, click, marshmallow; job 2 on
the same machine vs job 2 on another machine through the service; every reuse checked by a fresh full run):

* Before review R-008 (runs 44262651294, 44263752890, 44264885597): 100% of the one-machine reuse on all pairs, 0
  wrong.
* After R-008, instruction-set level keyed (default; runs 44299953107, 44300528610): pairs at the same level reuse
  100% of the one-machine reuse (2 of 6 pairs); pairs at different levels (x86-64-v3 vs v4) reuse nothing, and the
  identities differ only in `cpu`. 0 wrong.
* After R-008, `FENVIX_RUNTIME_ISA=off` (run 44300539734): 100% on all three pairs, two of them across v3/v4
  machines; identities equal. 0 wrong.

Locally: `runner/local-shared-demo.sh <repo-url> <N> <N+1>` runs the same comparison on one host;
`runner/shared-cache-compare ROOT...` prints the table.

## Limits and next steps

* Trust: a write token can make **any test pass** on every machine of its organization, not only claim an outcome.
  The set of inputs an entry lists is a claim too: an entry that lists few inputs is checked against few. The floor
  check refuses entries that do not even list the test's own file; it does not stop a forger who lists it. Real
  answer: signed entries (per-machine keys) or a sampled re-run of pulled hits. Until then: write tokens only on
  trusted refs (above).
* Data inputs outside the project are recorded by absolute path (files in the virtualenv, the project root itself):
  machines must use the same work paths (true on GitHub-hosted runners and on `runs-on: fenvix`).
* Tests that enumerate the environment depend on the whole environment, which differs between machines
  (`RUNNER_NAME`, ...): they rerun on another machine.
* Native libraries loaded only at run time with `dlopen`/`ctypes` by name are not in the closure.
* Hardware other than the instruction-set level and the CPU count (CPU model, memory size, GPUs) is not keyed.
* One HTTP service process with SQLite; sized for tests and a small fleet. Pull fetches every candidate document of
  the collected tests (pygments: ~10 MB, 3-4 s locally); a per-commit manifest would cut it.
