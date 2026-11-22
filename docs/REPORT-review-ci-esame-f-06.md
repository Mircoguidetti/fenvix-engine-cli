FIX 2

# Review: `claude/ci-esame-f-06-q8d81c`, three commits (head `3819b6f`)

Reviewer session. Scope as assigned: `2b2862a`, `7c8a651`, `d1d9d11` only.
Everything below was run on this container, Node 22.23.5, after `npm ci` + `npm run build`
(native core built from the branch as checked out). Nothing in `crates/` and nothing Python was touched.

**The two fail-fast commits cancel out, as stated.** Checked only that:
`0c93f5d` / `b83a31f` turn fail-fast off, `5096fc3` / `3819b6f` revert them;
`git diff 743f6bc..3819b6f -- .github/` is empty, so the CI file at head equals the CI file before the pair.

## Verdict

| commit | what it changes | verdict |
|---|---|---|
| `2b2862a` | test fixture (R-032b policy equivalence) | **no finding** — the 3000 seeds are not vacuous, measured |
| `7c8a651` | test assertion (SQLite gap) | **FINDING 1** — the exemption is reason-blind |
| `d1d9d11` | engine (`src/facts.js`) + guard | **engine change holds** (attacked, measured); **FINDING 2** — the new guard is unreachable where it matters |

Neither finding is a case of a red turned green by lowering the claim below the truth. In both the claim
is *true* but *looser than the commit message's own prose*, and in one case the backstop cannot fire.

---

## FINDING 1 — `7c8a651`: the `better sqlite3` test is exempted by node id, for any reason

**What is wrong.** The old assertion was `rep.summary.stable === rep.summary.tests`. The new one is

```js
const notProven = rep.tests.filter((t) => t.status === 'not-proven').map((t) => t.nodeid);
const native = first.better === 'absent' ? [] : [rep.tests.map((t) => t.nodeid).find((id) => /better sqlite3/.test(id))];
assert.deepEqual(notProven, native, ...);
```

That says *which* test may be NOT PROVEN. It never says *why*. The commit message's claim is much more
specific — "it is a native addon, so the general rule refuses to call its test IDENTICAL" — and that part
is not asserted anywhere, although the engine reports it.

**MEASURED.** Baseline, jest leg, better-sqlite3 really installed (`test/.tmp/pkgs/node_modules/better-sqlite3`
present, so the native leg is live and not skipped):

```
# jest: G-1427 G-1428 SQLite ... -> ok 1, # pass 1  (2.8 s)
summary {"runs":2,"tests":3,"stable":2,"diverged":0,"outcome_unstable":0,
         "order_identical":true,"reasons":{"native":1},"identical":2,"not_proven":1}
stable       t/a.test.js::node sqlite
not-proven   t/a.test.js::better sqlite3
stable       t/a.test.js::a function the test defines replaces Level 0s
```

The per-test reason *is* in the report and is unasserted:

```
rep.tests[better].divergence.reason      = "native"
rep.tests[better].divergence.description = "the test loaded a native extension whose own C code the engine
   has not reasoned about: not accounted for: native:.../better-sqlite3/prebuilds/linux-x64.node.
   Identical fingerprints are no evidence of an identical execution, so the verdict is NOT PROVEN ..."
```

Then I injected an unsoundness of a *completely different kind* into that one test — one line in the
fixture, inside `test('better sqlite3', ...)`:

```js
require('node:fs').readFileSync('/proc/self/stat');   // nothing to do with native addons
```

Result: **the test stayed green** — `ok 1 ... # pass 1`, `not_proven: 1`, `notProven` still exactly the
better-sqlite3 node id. A reviewer reading the test would believe the only thing unproven about that test
is the `.node` load; it is now a blanket pass for that node id.

**Where the fix belongs.** In the test, `node/test/network-p041.test.js`, at the new block: pin the reason,
so the exemption is for native-addon loading and not for the node id —

```js
const b = rep.tests.find((t) => /better sqlite3/.test(t.nodeid));
assert.match(b.divergence.reason, /^(native|api)$/, JSON.stringify(b.divergence));
```

`native|api` is the right pair: the commit message records that the two legs already answer differently
(jest `{"native":1}` via `prebuilds/linux-x64.node`, vitest `{"api":1}` via the `process.dlopen` behind it),
which is itself a reason not to leave the reason unchecked.

**Honest limit of this finding.** Reason-pinning would *not* have caught my `/proc` injection: the native
load still dominates `divergence.reason`, so the reason stayed `"native"`. That is a limit of what the
verifier reports per test, not of the test. What reason-pinning does buy is the realistic regression — the
prebuild stops loading on a new Node ABI, the refusal becomes something else entirely, and the test keeps
passing on the strength of the node id alone.

**Not findings, checked:** `diverged == 0` and `divergences(rep).length == 0` are still asserted, so a real
divergence is still red. A second NOT PROVEN test makes the `deepEqual` red. A renamed or missing
`better sqlite3` test gives `[undefined]` and is red. The `first.better === 'absent'` branch *tightens* the
claim (it then demands all three tests proven), it does not loosen it. `stable === tests - native.length`
still demands everything else proven.

---

## FINDING 2 — `d1d9d11`: the new guard sits after the assertion it is meant to back up, so it never runs

**What is wrong.** The commit adds the `ghosts` loop to `node/test/parallel-p041.test.js` *below*
`assert.deepEqual(fps(p1), fps(s));`. The commit message says: "Without the fix that assertion fails on the
jest leg even when the fingerprints happen to line up." In the actual reproduction the fingerprints do
**not** line up, so `fps` throws first and the guard is dead code in exactly the scenario it documents.
What the maintainer sees is two opaque hashes, not the named cause.

**MEASURED, three runs of the jest@29.7.0 leg** (`DETJS_TEST_RUNNERS=jest node --test
--test-name-pattern "plan identical across runs" test/parallel-p041.test.js`):

1. Branch as committed: **pass**, 25.9 s (`# pass 1`, jest 29.7.0 installed, not skipped).
2. One-line revert of the filter in `src/facts.js` (`&& byUserCode()` removed), nothing else:
   **red at `test/parallel-p041.test.js:536`**, i.e. the `fps` assertion —
   `tests/f1.test.js::group 1::timers 1`: `passed|1279f4c9cbaad32077587f6309511abe` (lanes) against
   `passed|10a78ccc1d42a76b1a740ae504d1dc0c` (serial). The defect is real and the fix does remove it.
   The `ghosts` guard never executed.
3. Same revert, with the `ghosts` loop moved three lines up, above the `fps` comparison: **the guard
   fires, with the cause named** —
   ```
   a process id read by nobody's code became an event:
   tests/f2.test.js::group 2::timers 2: process.pid at <node>
   ```
   So the guard has real power; it is only unreachable as placed.

**Where the fix belongs.** `node/test/parallel-p041.test.js`: move the `for (const r of [s, p1, p2])`
ghosts loop above `assert.deepEqual(fps(p1), fps(s));`. One line of movement, no change of claim.

---

## `d1d9d11`, the engine change: attacked with fixtures, and it held

The author's argument is that `process.pid` / `process.ppid` are plain properties read synchronously at the
reader's own site, so a real reader always has a frame on the stack. I attacked it with a fixture rather
than by reasoning: a jest project (`node/test/.tmp/par-runners/jest29/fx/pidattack`, jest 29.7.0) whose nine
tests read pid/ppid nine different ways, run under `detjs jest --det`, then the trace read back per test.

**MEASURED, branch as committed:**

```
RECORDED  a direct read in the test body                 process.pid  @ tests/p.test.js:3
RECORDED  a read after await                             process.pid  @ tests/p.test.js:4
RECORDED  a read in a then callback                      process.ppid @ tests/p.test.js:5
RECORDED  a read in a setTimeout callback                process.pid  @ tests/p.test.js:6
RECORDED  a read through a Proxy                         process.pid  @ tests/p.test.js:7
RECORDED  a read by a dependency under node_modules      process.pid  @ <deps>/pidreader/index.js:1
RECORDED  a read by a dependency in its own timer        process.pid  @ <deps>/pidreader/index.js:1
RECORDED  a read inside a native-ish getter walk         process.pid  @ tests/p.test.js:10
LOST      a read from a worker the test starts           []
```

("native-ish getter walk" = `Object.getOwnPropertyDescriptor(process, 'pid').get.call(process)`, the
patched getter invoked without the property access.) Eight of nine survive the filter with their correct
sites. **No loss of a test's own read was found in process.**

The ninth, a `process.pid` read inside a `worker_threads` worker the test starts, is lost — but I ran the
same fixture again with the filter reverted and **it is lost there too**, identically. It is pre-existing
(the worker is not in the test's recording context at all), not caused by this commit. Worth its own audit
row; it is not a finding against `d1d9d11`.

I also checked the mechanism the argument rests on, in `src/sites.js`: `resolve()` tries `resolveDepth(8)`,
then `resolveDepth(30)`, and only answers `'<node>'` when neither finds a frame that is not Node, not
`node/src/`, and not a nameless frame. Reaching `'<node>'` from user code therefore needs 30 consecutive
non-user frames above the reader, which for a synchronous property read means no user code is involved.
I could not construct one. `util.inspect`, the obvious candidate, does not invoke getters at all by default
(measured: the probe getter was never called), so that path does not exist.

**Is the fix in the right place?** It works, and I would not block on this, but the natural home is
`STATE.record` (`node/src/state.js:55`), not the getter:

* `record` already resolves the site for the event's `at` field, so `byUserCode()` is a **second** stack
  capture on every pid read — one in the getter, one in `record` — where the information was already in hand.
* `record` already drops `site === null` (runner infrastructure), so for the `null` case `byUserCode()`
  changes nothing. Its only real effect is the `'<node>'` case.
* For that case `record` has a fallback chain the getter bypasses: `'<node>'` → explicit `callSite` →
  `AMBIENT.getStore()`. A pid read inside work wrapped by `STATE.withSite` is now dropped although `record`
  would have attributed it to the user's site. In practice that is narrow — `withSite` is only used by
  `fsorder.js` for `fs.glob` — but it is a real behavioural difference, and it is invisible at the call site.
* The G-1481 exception the author is protecting (a timer-fired `time` event legitimately has no caller) is
  expressible in `record`, which has `source` in hand: the rule "an `other` fact that still resolves to
  `'<node>'` after the ambient fallback belongs to no test" is one condition there, costs no extra stack
  capture, and would cover every plain-property fact rather than the two names CI happened to expose.

That last point is the substantive one: `process.pid`/`ppid` were fixed because CI showed them. Any other
plain property Node's own machinery reads inside a worker while a test is in flight produces the same
timing-dependent event list, and the same false NOT-IDENTICAL, even when its value is constant.

**Residual, NOT measured — flagging it, not claiming it.** `byUserCode()` opens with
`if (!c || !c.sites) return true;   // sites are not being resolved: do not lose a real read`, and
`config.sites` is `env.DETJS_SITES !== '0'` (`src/config.js:52`). With `DETJS_SITES=0` the ghost read is
admitted again (`record` then writes `site = ''`, which is why the new guard also tests `e.at === ''`), so
the fingerprint-equality claim becomes conditional on an env var. I tried to reproduce it: one serial and
one lanes run of the `iso` fixture with `DETJS_SITES=0` produced **no** pid event in either leg and equal
fingerprints, so this is unproven in either direction — the ghost is timing-dependent and one run proves
nothing. Someone should settle it with repeated runs.

---

## `2b2862a`: no finding — the 3000 seeds are not vacuous, and I measured it rather than argued it

The worry was that adding `provable: PROVABLE` to every capture and a fixed `controls` list makes the
3000-seed equivalence comparison trivially agree on nothing. It does not. I copied the fixture's generator
and `both()` unchanged and instrumented what the **Rust** side actually does over 300 seeds:

```
seeds=300   rs.recorded total=114   seeds with recorded>0=62
not_cached entries=1665   verified=1043
--- not_cached reasons (Rust side), by frequency, ~50 distinct:
  426 outcome failed
  170 outcome cancelled
  160 outcome (empty)
  150 outcome error
   32 environment reads not observable in this process: process.en...
   28 a module specifier that could not be resolved and is not keyed...
   21 an off-thread module loader (--loader, module.register)...
   20 touched a path or port another test file running in parallel...
   16 ran after a test file that left process-wide state changed...
   13 reads the worker or pool id the runner gives its process...
   12 a preload module read the clock or OS entropy before Level 0...
   11 an input the engine cannot key: x,2
   10 watches the file system: 1.5
   10 an input the engine cannot key: null
    9 an input the engine cannot key: 1e+21
    ... (OS randomness in native crypto, subprocess, worker thread,
        /proc /sys /dev, unkeyed file metadata, SQLite path, dynamic
        import, clock not virtualized, ...)
```

`"declared no sensor"` appears **zero** times, so the comparison is no longer decided before a name is
looked at, which was the whole defect. And the adversarial paths the file's header claims are visibly
reaching the policy and shaping the reasons: the out-of-range / fractional `upto` (`1.5`), the numeric and
object details (`1e+21`, `null`, `x,2`), `''` labels and empty outcomes, duplicate ids and unicode paths
(the env-name and path reasons). 1043 verified entries and 114 recorded tests mean the accept path is
exercised too, not only refusals.

The comparison is also two-sided (`assert.deepEqual(rs.X, js.X)` plus a byte comparison of the two stores),
so a drift on either side still shows. `node --test test/review-r032b-policy.test.js`: **2/2 pass**, 1.3 s.

**One honest gap.** I could not falsify the new `a capture that declares no sensor` test by making the Rust
policy stop refusing, because that needs a change under `crates/`, which I was told not to touch tonight.
Its power is therefore *reasoned*, not measured: it asserts `rs.recorded === 0`, `js.recorded > 0` and
`/declared no sensor/` on every entry, all three of which invert if the refusal is removed. I would accept
it, and note that it is the one assertion in these three commits I did not put a red under.

---

## Reproduction

```
cd node && npm ci && npm run build
node --test test/review-r032b-policy.test.js                                              # 2/2
DETJS_TEST_RUNNERS=jest node --test --test-name-pattern "SQLite random" test/network-p041.test.js
DETJS_TEST_RUNNERS=jest node --test --test-name-pattern "plan identical across runs" test/parallel-p041.test.js
```

Break-tests used, each reverted afterwards (`git status` clean at the end of the review):

* `src/facts.js`: drop `&& byUserCode()` from the pid/ppid getter → parallel leg red at `:536`.
* `test/parallel-p041.test.js`: with that revert in place, move the `ghosts` loop above the `fps`
  comparison → the guard fires and names the cause.
* `test/network-p041.test.js`: add `require('node:fs').readFileSync('/proc/self/stat')` inside
  `test('better sqlite3', ...)` → test still green.
* `test/_probe-r032b.js` (deleted): the fixture's generator with a reason histogram over 300 seeds.
