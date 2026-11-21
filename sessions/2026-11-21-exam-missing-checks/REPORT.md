DONE

# P-052 exam X-01: the NOT IMPLEMENTED checks of F-01 / F-03 / F-05, three harness defects

Branch `claude/exam`. Commit `d92e259` (exam code, `[skip ci]`); proof run **44872193223** (MEASURED;
`exam.yml`, ref `claude/exam`, rows `F-01,F-03,F-05`, release_run 44868747010 = engine `5295ff0f`, branch
`claude/py-cache`), aggregate commit `2baa467` (`exam/results.json`).

## 1. What changed

| file | change |
|---|---|
| `exam/probes.py` | 8 probes that were "NOT IMPLEMENTED"; cassette-redact gets its Node half; testrun-uid fix |
| `exam/netfix.py` (new) | echo servers for the network probes (HTTP/1.1 keep-alive, TLS, an HTTP/2 server in plain `node`) on the machine's **non-loopback** address |
| `exam/rows_f.py` | click edit (defect 1); sudo wrapper keeps PYTHONPATH (defect 2) |
| `exam/lib.py` | `VOLATILE_ENV` constant (the same list `Ctx.sh` already declared) |
| `.github/workflows/exam.yml` | F-01 legs: Bun + Deno set up; `services: postgres` (image `''` on the other legs) |

The specs are the frozen ones in `exam/gap_map.json`. No check was added, removed or loosened. The one extension is the
Node half of `F-01.probe.cassette-redact`: its spec says "Python and Node", and only the Python half was written.

**Why a local echo server.** Both engines treat only loopback names and addresses as local
(`crates/detpy-py/src/network.rs` `LOCAL_NAMES` / `ip_flags`, detjs `network.js`), so to them a server on the
runner's own non-loopback IP is an external host. The audit's netproj2 runs (PY3-019/PY3-021) used the same setup.
The exam can then stop the server before the replay runs. A replayed test can only pass from its recording. Every
response echoes its request (method, path, `X-Exam` header), so a stale or swapped recording shows up in what the
test received.

## 2. The new checks: implementation, FAIL/PASS calibration, proof-run verdict

Calibration: I built the engine locally at the proof run's commit `5295ff0f`, and at the `claude/release-1` head
`74d42b38` as a known-bad engine for two of the probes. I ran each check with `exam/run.py --only`. Where no engine
behaves correctly, the PASS side was shown through the parts of the check that a correct behaviour satisfies.

| check | how it works | can FAIL / can PASS (how checked) | run 44872193223 |
|---|---|---|---|
| F-01.probe.cassette | Python (requests Session) and Node (Vitest + `fetch`, undici keep-alive): a pair of tests on one keep-alive connection, recorded with `--det-record`; server stopped. Then four replays: single test b (`nodeid` / `-t`), `--det-seed=1`, test a's path changed, test a's header changed. Each test must get its own echo; a changed request must not pass with the old response. | Each criterion was seen both ways: a single test b and a seeded replay got their own recordings in Node; Python rejected the changed path and header; Python's single test b got no recording; Node served stale responses. | **FAIL**: Python: single test b of the keep-alive pair: "no recording for it in this test" (G-0129/G-0130). Node: changed path and changed header PASS with the stale response (G-0091/G-0166). |
| F-01.probe.cassette-redact | Python half unchanged (example.com). New Node half: `fetch` with `Authorization: Bearer EXAMSECRET123` recorded from the echo server; cassette and `.detjs` scanned for the secret in clear or base64. | Node half seen PASS locally. Its FAIL condition is the same scan the Python half already used, and that half FAILed on run b3ae05c. | PASS (Python and Node) |
| F-01.probe.replay-clients | httpx.AsyncClient and aiohttp over HTTPS (self-signed CA via openssl), a socket using sendmsg/recvmsg, node:http2 client against an HTTP/2 TLS server, Bun fetch (elysia), Deno fetch (oak). Record with the servers up; replay with all servers down. Passes per client: offline replay passes with the recorded body, or `--det-record` refuses with a named reason. | sendmsg PASS; httpx/aiohttp FAIL; h2 "passes" with an empty body, which the check catches as FAIL; Bun refusal accepted as named. | **FAIL**: httpx and aiohttp fail offline (G-0165/G-0424); node:http2 replays an empty body (G-0425/G-0516); sendmsg OK; Bun and Deno refuse (`--det-record is not supported`, accepted by the spec). |
| F-01.probe.service-host | `services: postgres` on the F-01 legs. Its container IP goes into `/etc/hosts` as `postgres` and `exam-pg`. Python (psycopg) and Node (pg, Vitest) tests connect by name: plain, then `--det`, then `--det --det-allow-host=<names>` if needed; outcomes compared with plain. | Locally against PostgreSQL 16 on the non-loopback address (`EXAM_PG_IP`, a local-only override): Python FAILs with `--det` alone and PASSes with allow-host; Node FAILs. | **FAIL**: Python passes with `--det-allow-host` (G-0153/G-0154 closed for Python). Node `pg postgres` still fails with allow-host: "timeout expired" raised from detjs `clock.js` Driver.fire. The virtual clock fires pg's 10 s `connectionTimeoutMillis` timer while the connect is pending. |
| F-03.probe.multi-project | ufo + `vitest.workspace.ts` with a `node` and a `jsdom` project, both running one file. Each project reads its own flag file, so a change of one project's file changes only that project's part. Three verifies: identical runs (trace must hold 2 tests), divergence in node only, in jsdom only. | The first version shared one flag file, which would have hidden the bug; fixed. The node-only divergence is reported (PASS side of that sub-check); the jsdom-only one is not. | **FAIL**: the trace keeps 1 of 2 parts; a jsdom-only divergence gives verify rc 0 "identical" (G-0100). |
| F-03.probe.realm-failure | `NODE_OPTIONS=--require` setup file makes `globalThis.Date` non-configurable and read-only before detjs. Plain validity run, then two `--det` runs 2 s apart with **one** EXAM_OUT path. Console must name the missing time control and verify must not say identical (or time stays controlled). | First version: `Object.freeze(Date)` broke Vitest's own MockDate, so it was removed (spec: non-configurable). The per-run EXAM_OUT path made verify diverge on `env` alone, so it is now one path. | **FAIL**: real time leaks (values differ), nothing on the console, verify says identical (G-0181). |
| F-03.probe.zero-tests | ufo with `@vitest/browser` + Playwright Chromium, 2 tests; plain must pass 2; two `--det` traces; FAIL only if `fenvix verify` exits 0 while fewer than 2 tests were observed. | Both engines (5295ff0f and release-1 head) answer "NOTHING VERIFIED: no test ran" rc 1 on these 0-test traces. The FAIL branch is the audited behaviour (FE-022: rc 0, "covered 0"). | PASS (G-0037 closed: honest refusal; the traces still observe 0 browser tests) |
| F-05.probe.blockbuster | `tests/exam_bb/conftest.py`: an autouse blockbuster-style fixture that makes `os.path.abspath/realpath` raise inside a running loop. pytest-asyncio tests load a fresh code file inside the loop (the capture resolves each new code file with abspath/realpath, `capture.rs` `want()`). Plain, then `--det-cache` twice: outcomes equal plain, run 2 reuses >= 1. pytest-asyncio is uninstalled afterwards; left in the shared probe venv it caused INTERNALERRORs in later probes, seen locally. | **FAIL on release-1 head** `74d42b38` (no capture fallback: all 3 tests differ from plain); **PASS on 5295ff0f** (capture.rs falls back, fa290d64 line). The first version touched only already-seen files and passed on both; fixed. | PASS (both legs) |
| F-05.probe.custom-reporter | `tests/exam_cr/conftest.py` (an initial conftest) replaces the terminal reporter with one that drops `write_line`/`section`. `--det-cache` twice: entries recorded (receipts, run 2 reuses), and the cache summary reachable (printed, or a `*summary*` file in the cache dir or `.detpy`). | With the standard reporter the engine prints "detpy cache with proof / reused 3 result(s)", which matches the check's pattern (PASS side). With the project reporter nothing is printed and no summary file exists, so FAIL. | **FAIL**: entries recorded (2 reused) but the summary is unreachable (G-0412) |

## 3. Harness defects

1. **F-05.edit-src-flip.click**: the `make_str('exam')` edit flipped 0 tests. It now shortens
   `make_default_short_help` by one character (`max_length -= 1`). Plain run of click 8.1.8 (local and run
   44872193223): **9 tests flip** (`test_make_default_short_help[...]`, `test_commands.py::test_auto_shorthelp`). The
   check now gives a real verdict: run 2 reused 283, ran 367, **0 stale**. It still FAILs on one test,
   `tests/test_termui.py::test_fast_edit`. That test also fails under `--det` in run 1, before any edit: `click.edit`
   returns None, consistent with the engine's virtual file mtime hiding the editor's write (click compares
   mtimes). That is an engine result, not a harness one (it was in the previous runs too).
2. **F-05.wrong-reuse.hostname**: `sudo -E` drops PYTHONPATH (sudo's built-in env_delete list, checked with
   `sudo -V` and `PYTHONPATH=/x sudo -E env`). The plain run therefore could not load the exam's outcome plugin:
   "plain run produced no outcomes". `_wrap_cmd` now passes the variables sudo strips (PYTHONPATH, PYTHONHOME,
   PYTHONUSERBASE, LD_PRELOAD, LD_LIBRARY_PATH) through `env` inside the wrapper. Run 44872193223: **PASS** on
   both legs (plain fails under the other hostname, the engine does not reuse).
3. **PY-05.probe.testrun-uid**: the engine at 5295ff0f records every environment variable
   (`_level0.env_inputs`) and does not read `FENVIX_VOLATILE_ENV` (no code references it in python/, node/ or
   crates/). The per-run EXAM_OUT path therefore diverged on `env`. EXAM_OUT stays declared volatile (now also
   passed explicitly). Both runs now write **one** EXAM_OUT path, copied away after each run, so the runs differ in
   nothing the exam controls. Local: **PASS on 5295ff0f** (same derived uid, verify identical); **FAIL on the
   release-1 head** (two uuid4 values, and that engine's verify still says identical: G-0174). PY-05 was not in the
   proof run (scope F-01/F-03/F-05).

## 4. Proof run 44872193223 (engine 5295ff0f, artifact 14693425262)

| row | checks passed | new / fixed checks |
|---|---|---|
| F-01 | 3/33 | cassette FAIL, cassette-redact PASS, replay-clients FAIL, service-host FAIL |
| F-03 | 13/18 | multi-project FAIL, realm-failure FAIL, zero-tests PASS |
| F-05 | 50/56 (46/56 in run 44869317315, same engine) | blockbuster PASS x2, custom-reporter FAIL x2, wrong-reuse.hostname PASS x2, edit-src-flip.click(.n2) FAIL x4 (engine: test_fast_edit) |

None of the three rows' checks now shows "NOT IMPLEMENTED", "exam error", "INVALID" or "not run". The services
container, Bun and Deno all came up on the F-01 leg (service at 172.18.0.2; Bun and Deno answered).

## 5. Open (not done here)

* The engine does not implement `FENVIX_VOLATILE_ENV` (DECISIONS 2026-11-20, design A). Every F-01 check that writes
  through a per-run EXAM_OUT path diverges on `env` with this engine. That is an engine gap examined by F-01 itself,
  so it was left as is there.
* PY-05.probe.testrun-uid's spec has a second half ("--det-cache does not reuse a result that depended on a
  different uid") that the existing probe does not run. It was not added here (the task was the defect fix only).
* A different `key=` for `fam.py_setup` on the same project re-creates the shared checkout's venv
  (`lib.venv`: one `.venv` per checkout). Seen while reading PY-05.probe.xdist-old; not changed.
