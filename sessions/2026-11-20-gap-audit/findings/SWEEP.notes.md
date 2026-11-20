# SWEEP notes (exhaustive text sweep: engine `claude/release-1` 529c1609, fenvix-app `main` c59d913)

Output: `/home/user/audit/findings/SWEEP.gaps.jsonl` (539 entries, `SWEEP-001`..`SWEEP-539`). Working files (chunks as
written, grep outputs): `/home/user/audit/work/SWEEP/` (`chunks/*.txt`, `markers-engine-prod.txt`, `m1.txt`,
`markers-engine-rest.txt`, `skips-engine.txt`, `markers-app-prod.txt`).

Labels: MEASURED = I ran it here; DECLARED = a doc/report of the repository says so; UNKNOWN = not found.

## 0. What the lead should read first

1. **Python shared cache through the service is not wired on release-1 (RAN, SWEEP-517/518/519).**
   `pytest --det --det-cache=https://...` uses the URL as a local directory name, makes no request, prints no warning,
   and leaves `FENVIX_CACHE_TOKEN` readable by the tests. `python/detpy/remote_cache.py` is in the wheel but nothing
   imports it. The 10 + 4 + 1 client tests are unconditionally skipped ("not yet ported": SWEEP-391/392/393).
   `docs/RELEASE-1.md:34` and `docs/SHARED-CACHE.md:69-73` say the URL form works. Only `--det-cache-shared=DIR`
   (a shared directory) works (RAN, SWEEP-521). The Node client (`node/src/cache/remote.js`) is wired
   (`node/src/cache/proof.js:148,399`), not run here.
2. **`pytest --det` is broken on Python 3.9 and 3.10 (RAN, SWEEP-537/538)**: collection error
   `AttributeError: 'code' object has no attribute 'co_qualname'` (`python/detpy/plugin.py:567`). `python -m detpy
   unittest --det` is broken on 3.9 (RAN, SWEEP-539). The package says `requires-python >=3.9`; CI runs 3.12/3.13 only.
3. **23 reviewer/feature tests are unconditionally skipped** for the start-up process rule and the runner wrapper (10 + 6 + 6 + 1)
   ("not yet ported onto the Rust capture": SWEEP-394..397), and one strict xfail documents a known wrong reuse
   (PYTHONWARNINGS, SWEEP-398).
4. **The release gate does not test what the release table claims**: Django, nose2, ward, zope shells (42 tests in
   4 modules), Hypothesis, numpy, time-machine, pytest-benchmark handling are skipped because the gate installs only
   `pytest pytest-xdist` (SWEEP-420/421); Bun and Deno suites skip without the binaries (SWEEP-414/415); Go runs on
   1.26 only (SWEEP-428); the JVM R-022b review tests are not in the gate (SWEEP-430); the Go job is red per the
   release report (SWEEP-527).
5. **fenvix-app**: warm-ups can only end "unsupported" (no `runner/warmup.sh` on any engine branch: RAN, SWEEP-494);
   the runner image installs the pytest path only (SWEEP-496); the App knows 4 runners, no JVM (SWEEP-495).
6. **No TODO/FIXME in either repository** (SWEEP-390, SWEEP-507): open work lives only in docs "limits" tables and
   session reports, which is exactly the pattern the audit was started for.

## 1. Counts

### 1.1 Entries by area prefix

| prefix | entries |
|---|---|
| Limits / (docs line by line, plus session reports, CLI usage texts and option parity found on the way) | 382 |
| Code marker / | 34 |
| Disabled test / | 31 |
| CI / | 27 |
| Refusal / | 47 |
| Pins / | 18 |

Severity: WRONG-RESULT 70, BLOCKS-USE 68, DEGRADES 308, MINOR 93. Class: BUILD-MVP 201, BUILD-LATER 320, DECIDE 18.
How: READ 468, DOC 61, RAN 10.

Limits per document or source (first word of the area after `Limits /`): LIMITS.md 78, JVM.md 52, GO.md 50, NODE.md 35, NODE-CACHE.md 23, RELEASE-1.md 16, PARALLEL-PROOF-DESIGN.md 15, SHARED-CACHE.md 11, runners/bun.md 10, runners/deno.md 7, ALL-RUNNERS.md 6, runners/mocha.md 6, runners/node-test.md 6, runners/tap.md 6, RUNNER-PROTOTYPE.md 6, runners/django.md 5, runners/hypothesis.md 5, sessions 5, runners/unittest.md 4, runners/jasmine.md 4, runners/ava.md 4, ARCHITECTURE.md 4, runners/BUILD-node-b.md 3, runners/nose2.md 2, runners/zope-testrunner.md 2, runners/doctest.md 2, runners/ward.md 2, runners/uvu.md 2, README.md 2, detjs 2, runners/BUILD-node-a.md 1, runners/BUILD-python.md 1, HARNESS.md 1, RELEASE-1 1, REPORT-node-l0.md 1, three 1, option 1.

### 1.2 Code markers, engine product source (233 files: crates, python/detpy, node/src + bin + scripts, go/cmd,
go/internal, jvm/agent, jvm/rt, jvm/maven-ext, jvm/gradle, jvm/skip, release, runner, .github/workflows, root config)

`grep -nE` hits: 431 lines, of which 148 in `node/package-lock.json` (platform lists of third-party packages:
dismissed). Per marker (all 431):

| marker | hits | became entries | dismissed, why |
|---|---|---|---|
| TODO / FIXME / HACK / todo! / unimplemented! / "not implemented" / "for now" / workaround / placeholder / stub / hard-coded | 0 | 1 (the count itself, SWEEP-390) | nothing to dismiss |
| XXX | 1 | 0 | a token-shaped example string in a comment |
| unreachable!(... not | 1 | 0 | `crates/detpy-py/src/fsorder.rs:489`: an internal dispatch invariant |
| NotImplementedError | 4 | 1 (xdist work stealing, SWEEP-377) | 3 are `except NotImplementedError` around `cache_from_source` (handled) |
| not supported | 10 | 6 (nose2 -N, mocha --watch, node-test --watch, bun/deno refused flags and --det-record: SWEEP-254, SWEEP-268, SWEEP-275, SWEEP-296, SWEEP-297, SWEEP-306, SWEEP-307) + 1 (JVM native prefix, SWEEP-382) | 0 |
| unsupported | 2 | 0 | `unsupported cassette/trace version`: forward-compatibility checks |
| not yet | 6 | 1 (cache.rs "not yet wired", SWEEP-372) | 5 are prose ("not yet due", "not yet on the service", "not yet running", "not yet valid") |
| future | 48 | 2 (syscall backend SWEEP-365/SWEEP-373; cache.rs) | 33 `from __future__ import`, 9 `Future`/`futureGet` identifiers, rest prose |
| later | 84 | 1 (`sched.thread (later)`, SWEEP-374) | 83 prose ("a later test", "later sessions") |
| temporary | 19 | 0 | all "temporary file/directory" |
| experimental | 23 | 1 (smoke isolation flag, SWEEP-389) | 22 are Node flag names (`--experimental-*`) in option tables |
| prototype | 75 | 1 (`--det-cache-dists` PROTOTYPE, 4 lines, SWEEP-375) | 68 JavaScript `.prototype`, 2 branch names `runner-prototype-ee21he` (SWEEP-441) |
| best effort | 3 | 2 (`_patch.py`, `JdkRandoms`: SWEEP-378, SWEEP-381) | 0 |
| Linux only | 3 | 3 lines -> SWEEP-023/SWEEP-024 (reexec), SWEEP-350 (isolate) | 0 |
| macOS | 2 | 2 (runtime_id non-ELF SWEEP-376; release-1.yml other-os SWEEP-424) | 0 |
| darwin / win32 | 67 / 83 | 2 (native.js + build.js SWEEP-379; network.js named pipe SWEEP-380) | all others are `node/package-lock.json` |

Rest of the engine tree (566 files: tests, harness scripts, docs, sessions, tracks; strong markers only): 61 hits;
5 became entries (SWEEP-530 quic-go hang, SWEEP-531 jsoup, SWEEP-532 `--det-outcomes` missing in detjs, SWEEP-534 Jest < 27, and the
"not yet ported" skip reasons already counted under Disabled test); the rest are quotes of the items above, test
fixture text ("workaround" commits in the culprit review fixtures, "stub" test doubles) or the docs lines already
swept line by line.

### 1.3 Disabled tests, engine (562 files under tests/, node/test, go/, jvm/, crates/, release/, runner/,
.github/workflows)

390 grep hits. Per pattern: `skipif` 98, `xit(|xdescribe` 84 (every one is `exit(`/`sys.exit(`: dismissed),
`.skip(` 46 (mostly `pytest.skip(` and Rust iterator `.skip(1)`), `xfail` 45 (44 are fixture text or outcome names;
1 real strict xfail: SWEEP-398), `t.Skip` 42, `|| true` 41, `it.skip|test.skip|describe.skip` 28 (all `pytest.skip`
matches; node:test uses `{ skip: ... }` options, found with a second grep: 25 lines), `pytest.skip(` 27,
`importorskip` 27, `pytest.mark.skip` 11, `continue-on-error` 6, `unittest.skip|SkipTest` 1 (fixture text),
`--deselect` 1, `@Disabled`/`@Ignore`/`#[ignore]`/`test.todo` 0.

Became 31 "Disabled test" entries + 27 "CI" entries. Dismissed: (a) the 84 `exit(` matches; (b) ~60 lines that are
test fixture source text or outcome vocabulary (`"xfailed"`, `@pytest.mark.skip(reason="not here")` inside a
pytester project); (c) Rust `.skip(1)` iterator calls (9); (d) `|| true` on clean-up commands (`rm -rf`, `kill`,
`worktree remove`, `gzip`, `cp` of optional artifacts, `sudo rm` of runner disk space, `corepack enable`,
`sysctl`): 24 lines, they hide no test result; (e) skips for a missing optional tool where the product behaviour
itself is covered by another entry are grouped per condition (strace, gcc, root, locale) rather than per line, each
entry citing every line.

### 1.4 Refusals / fallbacks (step 4)

`grep -niE "warn|warning|refus|fallback|fall back|disabl|unsupported|skipping|ignored"`: python/detpy 93,
node/src 64, crates/detpy-py 66, crates/detpy-core 24, jvm/rt 17, go/cmd 11, jvm/agent 10, go/internal 9,
jvm/gradle 4, jvm/maven-ext 2, fenvix-go crate 2, fenvix-skip 1, detpy-node 1, runner 1 (305 lines), plus the
user-visible message sites (`process.stderr.write`, `System.err.println`, `fmt.Fprint(os.Stderr`, `UsageError`).
The complete refusal vocabularies were taken from the two tables in the core: Python
`crates/detpy-core/src/record.rs:139-186` (14 flags) and Node `crates/detpy-core/src/node_session.rs:20-45`
(24 flags). 47 entries. Dismissed: `--det-disable`/`fenvix.disable` plumbing (user-chosen), ASLR wording,
`ConnectionRefusedError` subclassing, `catch (... ignored)` around optional reflection where the fallback is
conservative (Deps.java supertypes), the Rust `ignored(path)` filters for detpy's own files and bytecode caches
(internal bookkeeping), JSON write helpers whose errors are ignored for memo files.

### 1.5 fenvix-app (223 production files; tests and docs separate)

Markers: 119 hits. `unsupported` 48 (one state name used by onboarding and warm-ups: entries SWEEP-494, SWEEP-497..SWEEP-503), `later` 43 (SQL `lateral`, prose), `placeholder` 13 (HTML input placeholders), `coming soon` 4 (API keys
page: SWEEP-493), `stub` 3 (EFI-stub kernel, DNS stub, a test stub mention), `future` 4 (`from __future__`),
`not supported` 2 (StateBadge label: SWEEP-502), `experimental` 2 (Node flags), `prototype` 1 (a mock repository
name), `not yet` 1 (prose), TODO/FIXME/HACK/"for now"/workaround/hard-coded 0 (SWEEP-507). Skips: 3 conditional
`{ skip: ... }` (no local Supabase: SWEEP-508, 509), `|| true` 3 that can hide a failure (SWEEP-512..514), rest
clean-up. The dashboard mock backend (`src/data/mock.ts`, ~100 "mock/sample/demo" lines) is one entry (SWEEP-505).
The app was swept for markers and skips only; its features are the APP agents' area.

## 2. Limits dismissed (not entries), with the reason

* `docs/LIMITS.md` rows marked **Fixed** with a named regression test and no residual: C2 (sleep with threads; its
  residual "polling real work" is SWEEP-035), C2b, C2c, C2d, C2e, F2, G1, G2. C1 (time-calibrated loops) is
  mitigated by the adaptive tick; its residuals are entries (C1b SWEEP-033, C1c SWEEP-034).
* `docs/LIMITS.md` A4 (dangling symlink): handled (recorded without following); test named. Not re-run.
* `docs/JVM.md` V11 (reordering cached), V15 as a defect (it is listed as the parallel-off limit, SWEEP-195).
* `docs/NODE.md` controls that are plain descriptions with no "not"/exception.
* `docs/GO.md` "Compared with Go's own test cache": advantages, not limits.
* `docs/PARALLEL-PROOF-DESIGN.md` section 1.4 items that the code shows as built: per-worker traces and merge
  (`python/detpy/xdist.py`, `trace.rs merge_traces`), fixed plan (`crates/detpy-core/src/schedule.rs`), controller
  decision, cross-worker write rule (`proof.rs:1325-1408`), `_` and xdist variables outside the whole-environment
  digest (`proof.rs:887 ENV_ALL_EXCLUDED`), derived `testrun_uid` (`xdist.py:110-116`). I did not run them.
* `docs/REPORT-node-l0*.md` (three harness reports): read only where a marker hit (SWEEP-532); their numbers belong
  to the Node matrix owner.

## 3. Could not check

* **Whether GitHub's `ubuntu-latest` image carries `bun` or `deno`** (SWEEP-414/415 assume it does not; the node job
  installs only Node 22). The skip counts in the CI artifacts (`node-tests.xml`) would settle it; no run artifacts
  are in the repository.
* **The four R-008/R-008b "hole" tests that fail in a venv** (SWEEP-529): in my scratch copy they fail for a harness
  reason (the tests import detpy from `python/` of the source tree, which my copy lacked), so I could not tell
  whether the venv failure the release report describes is a capture defect. DOC only.
* **blockbuster failures with the capture on** (SWEEP-324): the Rust capture still calls `os.path.abspath` through
  Python (`crates/detpy-py/src/capture.rs:844,916`); pydantic-ai not re-run (size, time).
* **`filterwarnings = error` against the remaining `warnings.warn` sites** (SWEEP-455): not run.
* **Node, Go, JVM artifacts**: nothing run here; those areas have their own agents. All Node/Go/JVM entries are
  READ or DOC.
* **macOS / Windows**: proven from code and CI config only.
* **Which engine commit the deployed runner image pins** (`FENVIX_ENGINE_CLI_COMMIT` is a repository variable):
  UNKNOWN from the code (SWEEP-515).
* **`docs/LIMITS.md:109`** "each test fails on `claude/parallel-proof-3` de41574": stale sentence or open defect;
  the file `tests/test_proofcache_import_lookups.py` is in the release gate, so probably stale (SWEEP-078).

## 4. Evidence appendix (commands run here, trimmed real output)

Set-up: `uv venv -p 3.9|3.10|3.11|3.12|3.14`, `uv pip install pytest [pytest-xdist]
/home/user/audit/build/dist/detpy-0.1.0-cp39-abi3-linux_x86_64.whl`; project `p1/test_a.py` = one passing test.

**SWEEP-517, SWEEP-518** (Python 3.12)

```
$ FENVIX_CACHE_TOKEN=secret123 pytest -q --det --det-cache=https://cache.example.invalid/acme/repo -p no:cacheprovider
reused 0 result(s) with proof, ran 1, recorded 1 (check 0.0s, record 0.036s); config 5b9cdde9..., runtime 8854fbeb...
not reused: new 1
receipts: /home/user/audit/work/SWEEP/p1/https:/cache.example.invalid/acme/repo/receipts.jsonl
1 passed in 0.08s          (rc=0)
$ find . -maxdepth 4
./https:  ./https:/cache.example.invalid  ./https:/cache.example.invalid/acme  ./https:/cache.example.invalid/acme/repo
$ ... same command on test_tok.py (prints os.environ.get("FENVIX_CACHE_TOKEN")) with -s
TOKEN_VISIBLE= secret123
$ grep -rn "import remote_cache\|remote_cache\." python/detpy/*.py python/detpy/runners/*.py   (minus remote_cache.py itself)
(no output)
```

Scratch copy of `tests/` with the `@_CLIENT_NOT_PORTED` decorators removed from `tests/test_shared_cache.py`:

```
$ python -m pytest -q -p no:randomly tests/test_shared_cache.py -x -k "second_machine_reuses or plain_http or another_runtime"
    def test_token_is_hidden():
>       assert os.environ.get('FENVIX_CACHE_TOKEN') is None
E       AssertionError: assert 'fxc_EGQb9YT1...' is None
receipts: /tmp/pytest-of-root/pytest-214/test_second_machine_reuses_.../http:/127.0.0.1:36387/org-a/project/receipts.jsonl
FAILED tests/test_shared_cache.py::test_second_machine_reuses_with_proof_what_the_first_recorded
1 failed, 14 deselected in 12.70s
```

**SWEEP-521**

```
$ pytest -q --det --det-cache=.c --det-cache-shared=shared test_a.py
shared store shared: 0 candidate(s) for 0 test(s), 0 adopted after the check, rejected: none; pushed 1 entr(ies)
$ rm -rf .c .detpy; same command
reused 1 result(s) with proof, ran 0, recorded 0 ...
shared store shared: 1 candidate(s) for 1 test(s), 1 adopted after the check, rejected: none; pushed 0 entr(ies)
```

**SWEEP-520** (Python 3.11): `pytest -q --det --det-cache=.c` => `ERROR: --det-cache needs Python 3.12+ (sys.monitoring)`

**SWEEP-537, SWEEP-538**

```
$ v3.9/bin/python -m pytest -q --det -p no:cacheprovider test_a.py
../v3.9/lib/python3.9/site-packages/detpy/plugin.py:600: in _rewriter_digest
../v3.9/lib/python3.9/site-packages/detpy/plugin.py:567: in code
E   AttributeError: 'code' object has no attribute 'co_qualname'
ERROR test_a.py - AttributeError: 'code' object has no attribute 'co_qualname'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
$ v3.10/bin/python -m pytest -q --det -p no:cacheprovider test_a.py      -> same error, 1 error in 0.93s
$ v311 -> 1 passed in 0.03s      $ v3.14 -> 1 passed in 0.02s
```

**SWEEP-539**

```
$ v3.9/bin/python -m detpy unittest --det test_u
  File ".../v3.9/lib/python3.9/site-packages/detpy/__main__.py", line 1, in <module>
    from .cli import main
ImportError: attempted relative import with no known parent package
$ v3.10, v311, v312: "OK" and "detpy 0.1.0: runner unittest 3.1x; controls=bytecode,fs,hashseed,net,order,seeds,time ..."
```

**SWEEP-494**: `git -C /home/user/fenvix-engine-cli log --all --oneline -- runner/warmup.sh` => no output;
`ls /home/user/audit/engine/runner` => `bootstrap.sh ci-project-env.sh fenvix-run local-demo.sh local-shared-demo.sh
shared-cache-compare`.

**SWEEP-390 / SWEEP-507**: marker greps, outputs in `/home/user/audit/work/SWEEP/markers-engine-prod.txt` (431 lines)
and `markers-app-prod.txt` (119 lines).

**Absent options (several entries)**: `grep -rn "det.threads\|det_threads\|det-async" python/detpy crates/detpy-py/src`
=> no output; `grep -rni lane python/detpy crates/detpy-core/src/schedule.rs` => no output;
`grep -rniE "audit.rerun" python/detpy crates/detpy-core/src` => no output; pytest option list on release-1:
`--det-allow-host --det-cache --det-cache-dists --det-cache-epoch-window --det-cache-keys --det-cache-max-age
--det-cache-no-follow --det-cache-receipts --det-cache-shared --det-cache-verify --det-cassette --det-compare
--det-disable --det-epoch --det-isolate --det-keep-aslr --det-max-events --det-no-reexec --det-order --det-outcomes
--det-plan --det-plan-worker --det-record --det-seed --det-sleep --det-tick --det-tick-adapt --det-trace
--det-urandom`.

## 5. Contradictions between docs and code, and claims found false

| claim | where | what the code / a run says |
|---|---|---|
| `--det-cache=DIR\|URL` for Python; token hidden from tests | docs/RELEASE-1.md:34, docs/SHARED-CACHE.md:69-99 | URL is a directory name; token visible (RAN, section 4) |
| "Python 3.9-3.11: Level 0 only", "3.9+ for `--det`" | docs/RELEASE-1.md:58,113; pyproject.toml:10 | `--det` crashes at collection on 3.9 and 3.10 (RAN) |
| wheel `detpy-0.1.0-cp39-abi3-manylinux_*_x86_64.whl` | docs/RELEASE-1.md:16 | built `--compatibility linux`: tag `linux_x86_64` (SWEEP-482) |
| Block 3 closed: `--det --det-threads` | brain DECISIONS.md 2026-11-18 | no `--det-threads` option on release-1 (SWEEP-366, SWEEP-044) |
| "The cache does not cross machines yet" | docs/RUNNER-PROTOTYPE.md:122 | contradicts docs/SHARED-CACHE.md on the same branch (SWEEP-347) |
| Gradle wiring sets `forkEvery = 0` | docs/JVM.md:49 | init script keeps the project's forkEvery (SWEEP-196) |
| `sched` control vs "--det does not change GOMAXPROCS" | docs/GO.md:51 vs :53; usage text lists no `sched` | both statements in one doc (SWEEP-166) |
| result cache "not wired into the plugin yet" | docs/ARCHITECTURE.md:32 | the proof cache is the main feature; the doc describes a dead module (SWEEP-367) |
| README: Level 0 plugin, "future result cache", Vitest and Jest | README.md | four languages, 16 runner shells, cache (SWEEP-370) |
| "each test fails on claude/parallel-proof-3 de41574" | docs/LIMITS.md:109 | stale or open; not re-run (SWEEP-078) |
| nightly real-clock check "for Python, Node and Go" | brain DECISIONS.md 2026-11-19 | only a Go workflow exists, and it does not trigger on release-1 (SWEEP-434) |
| DECISIONS 2026-11-17 "syscall backend not deferred", L2 in scope | brain DECISIONS.md | `Backend::Syscall` reserved, no L2 code on release-1 (SWEEP-365) |
| customer mode (Firecracker per job) "built now" | brain DECISIONS.md 2026-11-18 | a `spike/` of shell scripts in fenvix-app (SWEEP-504) |

## 6. DECIDE entries (18) and how DECISIONS.md was used

Recorded exclusions quoted in entries: virtual-day clock (2026-11-19: SWEEP-171, 172), carried-set rule (2026-11-19:
SWEEP-524), fork isolation as an option (2026-11-20: SWEEP-350), engine on our Linux machines (2026-11-17/18: every
Linux-only / macOS / Windows entry is DECIDE with both sides, because the promise text says "any CI and any runner"
and DECISIONS records hosting, not a platform exclusion). No DECISIONS entry excludes: PyPy, Python 3.9-3.11 for the
cache, Bazel/sbt, TestNG, Cypress, WebdriverIO, remote `--tx`, NonDex-style iteration order, `--det-cache` without
`--det`. Those are DECIDE or BUILD by judgment; the N5 "decision" exists only inside docs/LIMITS.md (SWEEP-059).
