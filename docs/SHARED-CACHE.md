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
| `site_loose` | files directly in a site directory that no distribution owns (`.pth` run at start-up, `_virtualenv.py`) | |
| `sys_path` | the import path, each entry named relative to stdlib, site directories, prefixes or the project root | absolute paths (an unknown directory keeps its path) |

The project under test, installed in editable mode, is left out: its files are per-test inputs. File digests are
memoised by (device, inode, size, mtime, ctime) in `~/.cache/fenvix/runtime-memo-*.json` (`FENVIX_RUNTIME_MEMO`,
`off` to disable); a memo copied to another machine never applies there. `python -m detpy.runtime_id [ROOT]` prints
every part and the lists behind them.

Why: the previous identity hashed each distribution's `RECORD` file; two GitHub-hosted machines from the same image
produced different `RECORD` bytes for the engine's own wheel, so nothing recorded on machine 1 was reusable on
machine 2. `tests/test_runtime_id.py` proves the new rule: same packages at other paths through other installers,
a relocated copy of the interpreter and the same libc from another directory give the same identity; another Python
patch release, other libc bytes actually loaded, another package version, the same version with one changed file,
a changed stdlib file, a `.pth` file and `PYTHONOPTIMIZE` give a different one.

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
* The token (`FENVIX_CACHE_TOKEN` or `FENVIX_CACHE_TOKEN_FILE`) and the other client variables are removed from the
  environment before any test runs; `fenvix-run` does not pass them to the runs without the service (verify, rerun
  alone). Level 0's closed network is suspended only around the client's own requests, never while a test runs.

## Measured (see the session report)

GitHub-hosted machines, workflow `.github/workflows/fenvix-shared-cache.yml`: job 2 on another machine reuses as
much as job 2 on the same machine (pygments, click, marshmallow), every reuse checked by a full fresh run, 0 wrong.
Locally: `runner/local-shared-demo.sh <repo-url> <N> <N+1>` runs the same comparison on one host;
`runner/shared-cache-compare ROOT...` prints the table.

## Limits and next steps

* Trust: any token with write access can file a false "passed" entry for its organization. Every candidate is
  checked against code and data, but the recorded outcome itself is a claim. Next: signed entries (per-machine
  keys), or a verification sample re-run on pull.
* Data inputs outside the project are recorded by absolute path (files in the virtualenv, the project root itself):
  machines must use the same work paths (true on GitHub-hosted runners and on `runs-on: fenvix`).
* Tests that enumerate the environment depend on the whole environment, which differs between machines
  (`RUNNER_NAME`, ...): they rerun on another machine.
* Native libraries loaded only at run time with `dlopen`/`ctypes` by name are not in the closure.
* One HTTP service process with SQLite; sized for tests and a small fleet. Pull fetches every candidate document of
  the collected tests (pygments: ~10 MB, 3-4 s locally); a per-commit manifest would cut it.
