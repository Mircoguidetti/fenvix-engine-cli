# Block 4 — cache with proof for Node (row F-06)

Branch `claude/cache-node`, based on `origin/claude/verifier-cli` @ `bbb7a8a1`.

**Headline: the defect I was sent to fix is not a cache defect.** It reproduces with the cache
switched off entirely (section 2, MEASURED). No change to the cache can make the exam check
`F-06.fake-timers` pass; the clock control has to change, and that trade is a founder decision.

Numbers are labelled MEASURED (a command run in this container, Node 22.23.5, Vitest 5.1.0),
DECLARED (from a brief or another session's report, not re-run here) or UNKNOWN.

## 1. The engine state vs the brief

### 1.1 The single predicate exists — under a different name than the brief gives

The brief names `judge(attestation) -> Verdict` and `account(module, qualname)` in
`crates/detpy-core/src/provable.rs`, owned by Block 1. MEASURED, across all 84 remote branches:
no tree contains `provable.rs`; no Rust file contains `fn judge` or `fn account(`.

But the thing the brief *describes* is real and already built, in
**`crates/detpy-core/src/node_session.rs`**:

* `UNCACHEABLE: &[(&str, &str)]` — the accounting table, 29 channels, flag -> description;
* `uncacheable_flag()` / `uncacheable(flags, outcome)` — the single predicate;
* `const UNKNOWN_FLAG: &str = "an input the engine cannot key"` — **default-deny**: a flag the
  table does not know still refuses reuse. The comment states the rule outright: "a source the
  engine cannot attribute refuses reuse."
* reached from JS through one call, `native.uncacheableTable()` (`node/src/cache/proof.js:39`).

The table already carries `("clock-real", "reads a clock Level 0 does not virtualize")`.

So there is nothing to reimplement and nothing blocking on Block 1: Node's work is **sensor**
work — raising the right existing flag — and the verdict stays in Rust. I did not add a predicate.
Worth correcting in the brief so the next block is not sent to a file that does not exist.

### 1.2 The 90% reuse target and default-deny are in tension (open)

`origin/claude/measure-provable` (fa999ce3, dated 2026-11-21) measured the cost of charging a test
with every information-carrying syscall: **0.0% of 879 real tests stay PROVABLE** as stated;
34.9% counting only the test phase; 72.1% if the project's own source files are recorded; 92.0%
with five more channels (all DECLARED by that session, not re-run here). Cause: no run input pins
the *content* of any file (`docs/LIMITS.md` F1).

The frozen check `F-06.no-edit` requires **>= 90% of tests reused on an unchanged checkout**.
Note the two figures are not measured on the same scale — `measure-provable` charges syscalls,
`UNCACHEABLE` charges 29 named channels — so they are not directly comparable, and the real reuse
share on this engine is UNKNOWN until section 4 is run. I flag the tension rather than assume it:
**if measured reuse lands under 90%, I will report the number and not loosen a flag to reach it.**

### 1.3 `claude/node-cache-proof` cannot be merged — unrelated history

MEASURED: `git merge-base origin/claude/verifier-cli origin/claude/node-cache-proof` is **empty**.
It is also the smaller, older tree:

| | files in `node/src` | `node/src/cache` |
|---|---|---|
| `claude/verifier-cli` (this base) | 86 | capture, early, **groups**, **loader-hooks**, proof, remote, runtime-id, **trace-reused** |
| `claude/node-cache-proof` | 24 | capture, early, proof, remote, runtime-id |

Its 478 commits are overwhelmingly measurement output (MEASURED: 1,487 files under
`harness/results`, 1,077 under `harness/node`, 99 under `harness/node_cache`). So "do not lose it"
can only mean its **evidence**: 0 wrong in 738,552 verified reuses; capture overhead docusaurus
+11.4%, TanStack +6.0%, vue-core +5.8% (DECLARED by that branch). Proposal: cite those as prior
results, re-measure on this engine, leave the branch untouched. **Confirm.**

### 1.4 There is no 60% baseline for F-06; no F-06 check has ever run

MEASURED from `origin/claude/exam:exam/results.json`, run 44925123655:

```
F-06: status FAIL, n_checks 0, n_passed 0,
      missing_legs [linux-x64/py3.13/node22, linux-x64/py3.13/node26],
      gaps: total 6, closed 0, open 0, no_check_ran 6
```

The brief's "today 60%" is DECLARED and unverifiable here. The exam also tests an **installed
release artifact** (that run used one built from `claude/py-cache` @ 2b67ac02), not a worktree, so
green F-06 needs a release build of this branch through Actions.

Also MEASURED: the base commit the brief names, `2b2f8e6a`, is not a valid object in this
repository.

## 2. The fake-timers defect: reproduced, and it is not in the cache

Reproduced with the exam's own probe (`exam/rows_f.py`, `FAKE_TIMERS`), Vitest 5.1.0:

```js
test('fake timers real clock', () => { vi.useFakeTimers(); const t = Date.now(); vi.useRealTimers();
  expect(t).toBeLessThan(Number(process.env.EXAM_DEADLINE)); });
```

### 2.1 With the cache: a green that a real run calls red (MEASURED)

| step | result |
|---|---|
| run 1, `--det --det-cache`, deadline = now + 4 s | 1 passed; "recorded 1 tests" |
| sleep 5 s (deadline now past) | |
| run 2, `--det --det-cache`, same deadline | **"reused with proof 1 tests in 1 files"** -> 1 passed |
| plain `vitest run`, same deadline, same moment | **1 failed** |

The reused test's trace record carries `"n_events": 0, "counts": {}, "events": []` — the engine
recorded no observation at all for it.

### 2.2 The cache is not the cause (MEASURED)

Same probe, **cache switched off entirely** (`--det`, no `--det-cache`), `.detjs` removed between
runs so nothing is carried:

| run | result |
|---|---|
| `--det`, before the deadline | 1 passed |
| `--det`, after the deadline | **1 passed** |
| plain, after the deadline | **1 failed** |

The engine already disagrees with reality with no cache in the picture. The cache faithfully
preserved a verdict the engine gets wrong on its own.

### 2.3 Root cause: the fake clock starts from a pinned past epoch

Instrumenting the real `Date.now` across `vi.useFakeTimers()` (MEASURED):

* calls to the real `Date.now` during install: **0**;
* `Date.now()` immediately after install: **1735689600000** = 2025-01-01T00:00:00Z;
* real clock at that moment: 1795294681189.

That value is `DEFAULT_EPOCH = '2025-01-01T00:00:00Z'` (`node/src/config.js:7`); under
`--det-cache` it is the virtual day instead (the trace header showed `epoch_ns`
1795219200000000000 = 2026-11-21T00:00:00Z). Either way the engine's wall clock is **pinned and in
the past**, so `Date.now() < now + 4000` is true under the engine forever and false plainly once
4 s have passed. Hence `n_events: 0`: nothing is read from a sensor, the fake clock serves a
constant that is already a pinned run input.

This virtualization is deliberate — audit G-0122 / G-0142, so that a fake clock does not start
from the machine's time and become unkeyable. My earlier hypothesis (an unrecorded real-clock read
leaking through the `FAKE_CLOCK_FRAME` stack regex at `clock.js:135` with `Error.stackTraceLimit =
6`) is **refuted** by the 0-call measurement above. The regex is still a guess about provenance and
worth hardening, but it is not this defect.

### 2.4 Why no cache change can make the check pass — founder decision

`F-06.fake-timers` compares run 2's outcomes against a **plain rerun**. Plain fails after the
deadline. Under a pinned past epoch the engine passes whether it reuses or reruns. So:

* refusing reuse (flagging `clock-real`) makes the test **rerun and still pass** -> check still red;
* the only way to match plain is for the test to observe the **real** clock, i.e. not to virtualize
  a fake-timer base the engine cannot account for — and then flag `clock-real` so it is never
  reused.

That second option is the brief's own rule applied honestly ("if the engine cannot be certain, it
reruns"), but it partly undoes G-0122/G-0142 and will make time-dependent tests across many suites
non-reusable and, in some cases, newly failing. I am not making that trade unilaterally.

**Decision needed.** Options as I see them:

1. **Let the real clock through for fake-timer installs, flag `clock-real`, never reuse.** Honest
   under the rule; check goes green; cost is reuse share and some suites turning red. Blast radius
   UNKNOWN until measured — I can measure it on docusaurus / TanStack / vue-core before you decide.
2. **Keep virtualizing, flag `clock-real` anyway so it is never reused.** Removes the stale-green
   half (the cache no longer certifies it) but the engine still passes where plain fails, so
   `F-06.fake-timers` stays red and the exam records a known-red check with a written reason.
3. **The check's premise is wrong** — a pinned clock is the point of `--det`, and comparing against
   a plain run that reads the real clock is not a fair comparison. Then the check needs changing,
   and the exam is frozen, so that is your call, not mine.

My recommendation is to measure option 1's blast radius first, then choose between 1 and 2. I lean
to 1 on principle: a value the engine invents for a channel it cannot account for is exactly the
"certainty the engine does not have" the rule exists to refuse.

## 3. Attack suites: all green (MEASURED)

`cd node && node --test --test-concurrency=1 <file>`, Node 22.23.5, after `npm ci` and
`node scripts/build.js`:

| suite | tests | pass | fail | duration |
|---|---|---|---|---|
| `test/verify-inputs-attacks.test.js` | 34 | 34 | 0 | 21.5 s |
| `test/review-r055.test.js` | 8 | 8 | 0 | 4.4 s |
| `test/cache.test.js` | 47 | 47 | 0 | 124.7 s |
| `test/cache-p041.test.js` | 36 | 36 | 0 | 116.7 s |
| **total** | **125** | **125** | **0** | |

Note: **none of these 125 tests catches the defect in section 2.** The suites are green and the
engine still reports a green that a plain run calls red. A regression test for it belongs in
`test/cache.test.js`, but its expected outcome depends on which option above you pick, so I have
not written one yet — writing it now would bake in a decision that is yours.

## 4. Not done

Item 5 of the brief (reuse share and wall-clock, cached vs uncached, serial and parallel, on
docusaurus / TanStack / vue-core) is not started, and no GitHub Actions matrix run (Node 22/24/26)
has been launched. Both measure an engine that section 2.4 is about to change, so they come after
that decision. `node/node_modules` was absent at session start (MEASURED); a local run needs
`npm ci` plus `node scripts/build.js` (~27 s for the Rust addon here).

## 5. Reproduction

```bash
cd node && npm ci --no-audit --no-fund && node scripts/build.js
# minimal project: package.json {"type":"module"}, vitest.config.js include test/**/*.test.ts,
# node_modules symlinked to node/node_modules, and the FAKE_TIMERS probe above as test/ft.test.ts
DL=$(( $(date +%s)*1000 + 4000 ))
EXAM_DEADLINE=$DL node <repo>/node/bin/fenvix.js vitest run --det test/ft.test.ts   # passes
sleep 5
EXAM_DEADLINE=$DL node <repo>/node/bin/fenvix.js vitest run --det test/ft.test.ts   # still passes
EXAM_DEADLINE=$DL node_modules/.bin/vitest run test/ft.test.ts                      # fails
```
