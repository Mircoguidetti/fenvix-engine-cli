'use strict';
// The runners' test and hook timeouts on the virtual clock (audit G-0144, docs/NODE.md J15).
//
// The runners arm their timeout with a timer they captured before the controls (Vitest: its "safe timers", stored
// under a symbol on the global object; jest-circus: the realm's `setTimeout` captured when the circus module was
// evaluated, which is detjs' own but called from runner code) and check "did the test take longer than its
// timeout?" again when it returns (Vitest: `now() - startTime >= timeout`, Vitest 5 `TaskDeadline.exceeded()`, with
// `Date.now` / `performance.now` captured when the module was evaluated).
//
// * The timer: a call from the runner's timeout code (frames `runWithTimeout`, `new TaskDeadline`,
//   `callAsyncCircusFn`) inside a test becomes a runner deadline of the virtual timer driver (src/clock.js:
//   fires on the virtual clock, or after a real watchdog when the test truly hangs).
// * The check: the clock functions the runner captured are those of src/deadline-preload.js (loaded first in
//   Vitest's workers), which answer calls from the same frames with the deadline clock: the virtual time charged to
//   deadlines, so that the runner's check agrees with the virtual timer.
const { STATE } = require('./state');

const KEY = Symbol.for('detjs.deadlineClock');
const DEADLINE_SETUP = /\b(?:callAsyncCircusFn|runWithTimeout|new TaskDeadline)\b/;
// frames that read the clock for a deadline: Vitest 1-4 `runWithTimeout` / its `resolve`, Vitest 5 `TaskDeadline`
const INITIALIZER = /^\s*at <instance_members_initializer>/;
const DEADLINE_READ = /^\s*at (?:runWithTimeout|resolve|new TaskDeadline|TaskDeadline\.(?:remaining|exceeded|derive|track|settle)) \(.*[\\/](?:@vitest[\\/]runner|vitest[\\/]dist)[\\/]/m;

function stackOf(limit) {
  const lim = Error.stackTraceLimit;
  Error.stackTraceLimit = limit;
  let st;
  try { st = new Error().stack || ''; } finally { Error.stackTraceLimit = lim; }
  return st;
}

/** Whether the timer being created is a runner's test or hook timeout. */
function isDeadlineCaller() {
  return DEADLINE_SETUP.test(stackOf(8));
}

/**
 * Deadline clock for the preload's clock functions: `unit` 'perf' (performance.now) or 'date' (Date.now). Returns
 * undefined (=> the real clock) unless the caller is a runner's deadline check inside a test.
 */
function installClockHook() {
  const box = globalThis[KEY];
  if (!box || box.hook) return;
  const clock = require('./clock');
  const base = { perf: box.perfNow(), date: box.dateNow() };
  const charged0 = () => (clock.CLOCK ? clock.CLOCK.charged() : 0);
  const c0 = charged0();
  box.hook = function deadlineClock(unit) {
    if (STATE.testId === null || !clock.CLOCK || clock.DRIVER.mode !== 'virtual') return undefined;
    // the caller of the preload's clock function (frames: stackOf, this hook, the preload's function, its caller)
    // (a class field initializer, `startTime = now()`, runs in a frame of its own below the constructor)
    const lines = stackOf(5).split('\n');
    if (lines.length < 5) return undefined;
    const caller = INITIALIZER.test(lines[4]) && lines.length > 5 ? lines[5] : lines[4];
    if (!DEADLINE_READ.test(caller)) return undefined;
    return base[unit] + (clock.CLOCK.charged() - c0) / 1e6;
  };
}

/** Vitest: the runner's safe timers (captured before the controls) create runner deadlines for its timeouts. */
function installVitest(g) {
  const sym = Object.getOwnPropertySymbols(g).find((s) => s.description === 'vitest:SAFE_TIMERS');
  if (!sym) return;
  const safe = g[sym];
  if (!safe || typeof safe.setTimeout !== 'function' || safe.setTimeout.__detjsDeadline) return;
  const clock = require('./clock');
  const realSet = safe.setTimeout;
  const realClear = safe.clearTimeout;
  const set = function setTimeout(fn, ms, ...args) {
    if (STATE.testId !== null && typeof fn === 'function' && clock.CLOCK && clock.DRIVER.mode === 'virtual' && isDeadlineCaller()) {
      return clock.DRIVER.deadline(() => fn(...args), clock.normDelay(ms));
    }
    return realSet(fn, ms, ...args);
  };
  const clear = function clearTimeout(t) {
    if (t instanceof clock.Timeout) return clock.DRIVER.clear(t);
    return realClear(t);
  };
  Object.defineProperty(set, '__detjsDeadline', { value: true });
  try {
    g[sym] = { ...safe, setTimeout: set, clearTimeout: clear };
  } catch { /* frozen: the runner keeps real timeouts */ }
}

module.exports = { isDeadlineCaller, installClockHook, installVitest, KEY };
