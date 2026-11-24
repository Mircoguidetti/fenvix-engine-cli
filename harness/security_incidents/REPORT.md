DROP

# Security research: do real incidents happen where fenvix's per-test trace would see them?

Desk research, 2026-11-24, on `claude/security-incidents` (from `origin/claude/release-1` 9ac63d6). Public pages only;
nothing downloaded, installed or run. Every number below is recomputed from `incidents.csv` (63 rows) and
`log_only.csv` (2 rows) by `check.py`.

## Verdict

**DROP.** The 8 Dec line needs at least 5 counted incidents **and** at least 3 of them FLAGGED. The first half holds
easily: 34 counted incidents. The second half fails: **0 FLAGGED**. Four counted incidents are UNCLEAR, and UNCLEAR
counts as not flagged. Even if all four were read as FLAGGED, plus the two near-misses below, the line would only just
pass, and only by reading every doubt the generous way. Rule 5 of the spec forbids that.

Counted incidents: 34
FLAGGED: 0
UNCLEAR: 4
NOT_FLAGGED: 30
counts=no: 29
Log-only: 2

* FLAGGED by scope: per_test 0, run_level 0, setup_digest 0.
* NOT_FLAGGED by reason: not_traced 23, channel 7, not_new 0.
* UNCLEAR by reason: unclear_where 2 (I17 AsyncAPI, I19 ChainDrop), unclear_how 2 (I06 SANDWORM_MODE, I33 durabletask).
* counts=no by failing rule (a row can fail several):
  * rule 1 (not malicious, e.g. a red-team exercise or proof of concept): 4
  * rule 2 (excludes CI): 2
  * rule 3 (no qualifying secret read): 9
  * rule 4 (no network send shown): 7
  * rule 5 (no dated page URL recovered): 7
  * rule 6 (same campaign wave): 3
  * rule 7 (not named, no confirmed victim): 6
* Counted rows by ecosystem: npm 18, GitHub Actions 8, PyPI 8.
* Counted rows by execution_point: install_script 11, test_process_import 10, ci_step 8, other 4 (Python `.pth`
  start-up files), test_process_call 1.
* `flagged_if_install_traced` (information only): yes 1, no 26, unclear 7. Tracing install scripts would mostly not
  help: most install payloads hand the reading to a child (Bun, TruffleHog, native binaries).

## Why nothing is FLAGGED: the pattern in plain words

1. **Two thirds of the counted incidents (23 of 34) never touch a test process** (8 CI-step, 11 install-script, 4 `.pth` rows).
   Install scripts, workflow steps and `.pth` start-up files run before or outside the test command, so the engine is not
   loaded (channels.md C-14, C-15, C-16, C-19). In 2026 the big campaigns (Shai-Hulud lineage, TeamPCP, Miasma,
   GhostAction, WFX Phantom) live here.
2. **Where the payload does run in the test process, on import, it immediately hands the work to a child process.**
   This is true of all 7 `channel` rows: node-ipc forks a detached child; Telnyx, xinference and LiteLLM 1.82.7 start
   `subprocess.Popen`; jscrambler spawns a native binary; the Mini Shai-Hulud PyPI legs run Bun or a downloaded `.pyz`.
   Imports in test files happen at module load, outside test bodies. There the engine records no child start at all
   (Node `node/src/children.js:36`, `:97`; Python `python/detpy/uncontrolled.py:132`), and it never traces what any
   child does. The secret read and the send happen entirely inside a process the engine does not watch. The sources say
   this is deliberate: the payload returns control to the parent at once, so the package loads normally.
3. **No counted payload reads secrets in-process at import time.** That is the shape the engine would see: run-level
   `env_read_outside_tests` / `files_read_outside_tests` (channels.md C-01..C-05).
   * The only cases with that shape are not counted. chimera-sandbox-extensions (N14) was published for an internal
     audit. mrmustard (N15) explicitly does nothing when it detects CI. The fake Paysafe SDKs (N19) have no campaign
     name and no confirmed victim, and its anti-analysis checks may skip CI.
   * The one case that sends from inside a call is N08 (@injectivelabs/sdk-ts). There the stolen secret is a wallet
     key passed to a function, not a CI secret.

## The four UNCLEAR rows and the two near-misses (the closest calls)

**Closest case 1: I19 ChainDrop (keyv, cacheable, ...; 4 Aug 2026; Datadog, opened).**
* The malicious commit added a 22-line test that "directly invokes the loader". The loader starts Bun as a child and
  downloads Bun itself.
* If the call is inside a test body, under vitest (supported: `node/test/runners-p041.test.js`), the test gets an
  `uncontrolled.child` event and per-test connection events. That is `per_test`, and the commit is new versus the base
  (3c).
* The source does not say whether the call sits inside a test body, or whether that test ever ran in CI before it was
  deleted 21 minutes later. Hence UNCLEAR.

**Closest case 2: I17 AsyncAPI generator 3.3.1 (14 Jul 2026; GitHub issue and Datadog, opened).**
* Obfuscated code at module level in `lib/templates/config/validator.js` spawns a detached `node -e` child the moment
  that file loads.
* If the generator loads it lazily inside a test body, the test gets `uncontrolled.child` (`per_test`). If the file
  loads at import, nothing is recorded.
* The sources do not say when it loads, and CSO calls the trigger a preinstall hook. Hence UNCLEAR.

**Closest case 3: I12 node-ipc 9.1.6/9.2.3/12.0.1 (14 May 2026; Datadog, opened).** NOT_FLAGGED (channel), with a
side effect the founder should know about.
* Before forking, the parent checks the marker variable `__ntw`. In a Node test worker that named read outside a test
  lands in `envout` → `env_read_outside_tests` (`node/src/controls.js:124-140`). That is a run-level record that
  differs because of the payload.
* Spec rule 3b counts only the payload's *secret read, file read or network send*. A marker check is none of these, so
  the row is NOT_FLAGGED.
* If D9 = C were read as "any record that differs because of the payload, whatever caused it", node-ipc would be
  FLAGGED `run_level`. That reading would also catch other payloads' marker checks. The founder should say which
  reading is meant.

**I06 SANDWORM_MODE** (Feb 2026) runs on import. The sources found do not say whether its key reads happen in-process
(that would be `run_level`) or in a child. **I33 durabletask** (May 2026) runs a downloaded `.pyz`; the sources do not
say whether it runs in the same interpreter or a child.

**Near-misses not counted:** N19 fake Paysafe SDKs (would be `run_level` only if rule 7 were relaxed **and** its anti-analysis checks were shown not to skip CI, rule 2) and N08
@injectivelabs (would be `per_test` if a wallet key passed to a function counted under rule 3).

Even counting all six, the line holds only if every doubt is resolved toward "flagged".

## The execution_point assumption (spec section 2)

When a source shows a payload running on import or call inside a Node or Python process, the row is
`test_process_import` / `test_process_call`, on the assumption that a project depending on the package imports it in
its tests.

For the flag decision this report adds one more assumption: **test files import packages at module scope**, i.e.
outside test bodies (collection in pytest, file load in mocha/vitest). This is the common case, and it is where the
engine's records differ most between "inside" and "outside" (channels.md table, two columns). Where the sources leave
open whether a payload's code is reached inside a test body, the row is UNCLEAR, never FLAGGED.

## channels.md, condensed (default proof run, release-1 9ac63d6)

| channel | Node inside a test | Node outside test bodies | Python inside a test | Python outside test bodies |
|---|---|---|---|---|
| env read | per-test (C-01) | run-level `envout`, any reader (C-01) | per-test (C-02) | run-level, project or third-party (C-02) |
| file read, outside project | per-test `fs.read.outside` (C-04) | project code: run-level; a dependency: **not recorded** (C-04) | per-test (C-05) | run-level (C-05) |
| outbound connect | per-test, `allowed` (Node default open) (C-06) | `net.setup` digest, only for a later test in the same file (C-06) | per-test, refused (Python default closed) (C-07) | **not recorded** (C-07) |
| DNS | per-test (C-08) | not recorded (C-08) | per-test (C-09) | not recorded (C-09) |
| child process | `uncontrolled.child` per test; child not traced (C-10) | **not recorded** (C-10) | same (C-11) | **not recorded** (C-11) |
| native code | not observed (C-12) | not observed | ctypes getenv observed, C-extension getenv not (C-13) | same |
| install scripts, `.pth`, CI steps | not traced (C-14, C-16, C-19) | | not traced (C-15, C-16, C-19) | |
| runner-infra package | not recorded (C-17) | env names only | not recorded (C-18) | env names only |

Full table with `file:line`, the run-level record list (note 1), the runner-written entries (note 2), the supported
runners and the default network modes: `channels.md`.

## What was verified, what was not (rule 7)

* **Engine facts** in `channels.md`: static read of release-1 9ac63d6, every cell with `file:line` or marked INFERRED.
  Nothing was run.
* **`disclosed` dates, 34 counted rows:**
  * 21 rows have a `disclosed_url` on github.com (an issue or advisory). Its creation date was read from the GitHub
    search API (`created_at`).
  * 2 rows (I12, I19) are Datadog pages opened in this session, with the date seen on the page.
  * 11 rows (I01, I04, I06, I09, I16, I21, I22, I26, I27, I31, I36) rely on
    pages this container could **not** open (the network policy refuses the vendor hosts: list in `queries.md`). Their
    date comes from search-result summaries. For these rows AC2 ("disclosed_url opens to a page dated `disclosed`") is
    **not verified**.
  * Where a GitHub issue is used because it could be dated, an earlier vendor post may exist. For example, the first
    Shai-Hulud reports were on 15 Sep 2025 per a secondary source, while I03 uses the 16 Sep issue.
* **counts=no dates:** N22 PromptPwnd's date (2025-12-04) is not from any opened page. It is approximate.
* **Payload behaviour:** read on the opened pages for node-ipc, ChainDrop, AsyncAPI and LiteLLM 1.107.0 (Datadog) and
  in the AsyncAPI GitHub issue. Everything else is from search-result summaries collected by the research agents, and
  is a claim until the coordinator re-checks it.
* **`n_sources`** counts every independent source the research agents saw, including ones not listed in `sources`. "Single source" in an `exfil` cell refers only to that host claim.
* **Engine limits that strengthen DROP:** Node does not record reads under `/proc`, `/dev`, `/sys` (`node/src/outside.js:30`), so runner-memory scraping inside a Node test would leave no file event either (channels.md C-04).
* **Not verified at all:** exfiltration hosts marked "single source" in the CSV, and the CI-detection details of
  Shai-Hulud 2.0 and Miasma.
* **What would change the verdict:** a source showing that SANDWORM_MODE, durabletask or the fake Paysafe SDKs read
  named secrets in-process at import. Even then the count reaches 3 only if the ChainDrop or AsyncAPI doubt is also
  resolved toward "flagged".

## Files

* `incidents.csv`: 63 rows, 34 counted.
* `log_only.csv`: tj-actions/changed-files and reviewdog/action-setup. Both printed secrets to job logs with no network
  send.
* `channels.md`: the engine's channels.
* `tools.md`: 8 tools; only StepSecurity Harden-Runner documents a before/after baseline, per CI job, not per test.
* `queries.md`: 180 queries, 176 ok, 4 failed, and the stop rule.
* `check.py`: recomputes the verdict and the counts.
