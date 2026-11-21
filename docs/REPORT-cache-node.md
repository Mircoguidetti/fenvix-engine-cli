# Block 4 — cache with proof for Node (row F-06)

Branch `claude/cache-node`. Status: **BLOCKED on four founder decisions** (section 1). One concrete
root cause of the known fake-timers defect is located (section 2); no product code changed yet.

Every number is labelled MEASURED (a command run in this container), DECLARED (taken from a brief or
another session's report, not re-run here), or UNKNOWN.

## 1. Four facts in the brief that the repository does not support

### 1.1 `judge()` / `account()` / `provable.rs` do not exist, on any branch

The brief says the accounting table `account(module, qualname)` and the single predicate
`judge(attestation) -> Verdict` live in `crates/detpy-core/src/provable.rs`, owned by Block 1, and
that every reuse decision must call `judge()`.

MEASURED, across all 84 remote branches:

* no tree contains `crates/detpy-core/src/provable.rs`;
* no Rust file on any branch contains `fn judge` or `fn account(`;
* the only match for "provable" in any tree is `origin/claude/measure-provable`, which is a
  measurement harness and explicitly states "No product code was changed on this branch".

What does exist is `crates/detpy-core/src/verify.rs` with `Status::NotProven` — a *verifier* status
for comparing two runs, not a cache-reuse predicate, and a file the brief forbids me to edit.

I have not written a replacement. Writing one is the "three separate notions of what a test
observed" failure the brief names as what kept the project stuck. **Decision needed: does Block 1
land `provable.rs` first, or am I to define the Node sensor's attestation format against a
predicate that does not yet exist?**

### 1.2 The rule and the F-06 reuse target are, on the only measurement available, incompatible

`origin/claude/measure-provable` (commit fa999ce3, dated 2026-11-21 — today) measured the cost of
exactly the default-deny rule I am told to adopt:

* DECLARED (that session, MEASURED by it): under the rule as stated — every information-carrying
  syscall accounted for — **0.0% of 879 real tests stay PROVABLE** across 4 projects.
* DECLARED: counting only what happens between test start and test end, **34.9% stay PROVABLE**;
  recording the project's own source files raises that to 72.1%, and five more channels to 92.0%.
* The dominant cause: no run input pins the *content* of any file. `docs/LIMITS.md` F1 confirms
  only enumeration *order* is normalised.

The frozen exam check `F-06.no-edit` requires **>= 90% of tests reused on an unchanged checkout**.
Default-deny at 34.9%–72.1% provable cannot reach 90% until file-content recording exists. The two
requirements cannot both be met by cacheability rules alone, and loosening the rule to hit 90% is
the failure mode the brief says has already happened twice.

**Decision needed: build the file-content input channel (large, and it is not in this block's
scope), or accept F-06.no-edit failing while the rule holds?** I will not trade the rule for the
number without an explicit instruction.

### 1.3 `claude/node-cache-proof` cannot be merged — it shares no history

MEASURED: `git merge-base origin/claude/verifier-cli origin/claude/node-cache-proof` is **empty**.
The two branches are unrelated histories. `node-cache-proof` is also the *smaller, older* tree:

| | node/src files | node/src/cache |
|---|---|---|
| `origin/claude/verifier-cli` (base) | 86 (MEASURED) | capture, early, groups, loader-hooks, proof, remote, runtime-id, trace-reused |
| `origin/claude/node-cache-proof` | 24 (MEASURED) | capture, early, proof, remote, runtime-id |

Its 478 commits are overwhelmingly measurement output (MEASURED: 1,487 files under
`harness/results`, 1,077 under `harness/node`, 99 under `harness/node_cache`).

So "do not lose it" can only mean its **evidence**, not its code: 0 wrong in 738,552 verified
reuses, and capture overhead docusaurus +11.4%, TanStack +6.0%, vue-core +5.8% (all DECLARED by
that branch; not re-run here). I propose carrying those forward as cited prior results and
re-measuring on this branch's engine, and leaving the branch itself untouched so nothing is lost.
**Confirm, or tell me which of its code you believe is newer than the base.**

### 1.4 "F-06 today 60%" is not in the exam record, and F-06 has never run

MEASURED, from `origin/claude/exam:exam/results.json` (run 44925123655):

```
F-06: status FAIL, n_checks 0, n_passed 0,
      missing_legs [linux-x64/py3.13/node22, linux-x64/py3.13/node26],
      gaps: total 6, closed 0, open 0, no_check_ran 6
```

No F-06 check has ever executed, so there is no 60% baseline in the repository; the figure is
DECLARED and unverifiable here. The exam also tests an **installed release artifact** (that run
used one built from `claude/py-cache` @ 2b67ac02), not a branch worktree — so making F-06 green
requires a release build of this branch through GitHub Actions, as the brief's matrix rule implies.

Also MEASURED: the base commit the brief names, `2b2f8e6a`, is not a valid object in this
repository. I branched `claude/cache-node` from `origin/claude/verifier-cli` @ `bbb7a8a1` instead.

## 2. The known defect: located, not yet fixed

The brief names it as "a test that reads the real clock inside fake timers gets reused". The
mechanism is in `node/src/clock.js` (MEASURED by reading the code at `bbb7a8a1`):

```js
Date.now = function now() {
  if (callerIsInfra()) return fakeClockCaller() ? fakeNow('Date.now')
                                                : (RealDate === REAL.Date ? REAL.dateNow() : RealDate.now());
  return Math.floor(CLOCK.wallMs(readFor('Date.now')));
};
```

* `callerIsInfra()` is true when no project site resolves in the stack.
* `fakeClockCaller()` tests the stack against
  `/\b(?:useFakeTimers|_toSinonFakeTimersConfig|getRealSystemTime|setSystemTime)\b/`
  with `Error.stackTraceLimit = 6`.

When the caller is infra and that regex does **not** match, the call returns the **real machine
clock** and records **no event**. Two ways a test's observed value comes from that path:

1. the fake-timer machinery is deeper than 6 frames, so the regex cannot see it;
2. the read reaches the test through any infra frame whose name is not one of those four.

Either way the capture holds no `time` event, the cache concludes the test is clock-independent,
and reuses it — while the value the assertion saw came from the real clock. The same unrecorded
real-clock pattern appears at `clock.js` lines 210, 217, 230, 238, 264 and 276
(`realNowMs`, `process.uptime`, performance marks and measures, `hrtime`, `hrtime.bigint`).

A stack-frame regex is a guess about provenance, and the brief's rule says a guess must yield NOT
PROVEN. The correct fix reports "real clock read, unaccounted" from the Node sensor and lets the
single predicate return NOT PROVEN — which is why 1.1 blocks the fix rather than merely delaying
it. I can build the sensor half now and wire the verdict when `judge()` lands; say the word.

## 3. Not yet done

Items 4 (attack-suite counts) and 5 (reuse share and wall-clock, cached vs uncached, serial and
parallel, on docusaurus / TanStack / vue-core) are not started. They measure the engine the
decisions above determine, so running them first would measure something that is about to change.
`node/node_modules` is absent here (MEASURED), so any local run starts with `npm ci` and
`node scripts/build.js`.
