'use strict';
// Concurrent tests under --det (`test.concurrent`, `describe.concurrent`, `sequence.concurrent` in Vitest;
// `test.concurrent` in Jest; audit G-1449, G-1456).
//
// Concurrent tests of a file run interleaved in one process, as without detjs (up to the runner's maxConcurrency).
// Each one gets its own Level 0 context: its test id, its event buffer, its virtual clock (the counter, the adaptive
// tick, the test start), its generators (Math.random, Web Crypto, entropy and nonce streams), and the per-test state
// of the other controls (file-time anchor, environment reads seen, temporary-directory numbering, child processes
// seen, the I/O ordering of src/ioorder.js, scheduling counters). The context travels with the test's asynchronous
// work (AsyncLocalStorage: promises, callbacks, timers); a control that runs checks which context is the running one
// (`sync`) and swaps the per-test state in when it changed. A virtual timer fires in the context of the test that
// created it. So the events of interleaved tests go to their own test, and each test's values depend only on its own
// work, not on how the others interleave with it.
//
// The interleaving itself is decided by the virtual timers (one queue ordered by due time and creation, fired one at
// a time) and by the order in which I/O completes (src/ioorder.js orders a test's file operations). Each test's trace
// gets one `sched.concurrent` event (it ran interleaved). Its own events and values do not depend on the
// interleaving; state the tests share in JavaScript (a module variable two concurrent tests both change) is not seen
// by Level 0, as order effects between serial tests are not.
//
// A concurrent test's events are written to the trace when it ends (the recorder takes one test at a time): the
// trace lists concurrent tests in the order they finished. Serial tests (no concurrent test running) take the
// unchanged path: `sync` returns at once while no concurrent test is active.
const { AsyncLocalStorage } = require('node:async_hooks');

const ALS = new AsyncLocalStorage();
const providers = []; // { name, save() -> snapshot, restore(snapshot), init?(id) }
const ACTIVE = new Set(); // contexts of concurrent tests that have not ended
let current = null; // the context whose state the controls hold now (null: the serial / outside-tests state)
let mainSnap = null;
let switching = false;

/** A control's per-test state: `save()` returns it, `restore(s)` puts it back. Called once per module. */
function register(p) {
  providers.push(p);
}

function saveAll() {
  return providers.map((p) => p.save());
}

function restoreAll(snap) {
  providers.forEach((p, i) => p.restore(snap[i]));
}

function switchTo(ctx) {
  if (ctx === current || switching) return;
  switching = true;
  try {
    const snap = saveAll();
    if (current) current.snap = snap; else mainSnap = snap;
    if (ctx && !ctx.snap) {
      // first time in: the per-test state starts afresh (as at a serial test start)
      current = ctx;
      ctx.init(ctx);
      ctx.resumes = 0;
      return;
    }
    restoreAll(ctx ? ctx.snap : mainSnap);
    if (ctx) ctx.resumes += 1;
    current = ctx;
  } finally {
    switching = false;
  }
}

/** Make the running context's state current. Cheap when no concurrent test runs. */
function sync() {
  if (ACTIVE.size === 0) {
    if (current !== null) switchTo(null);
    return;
  }
  let want = ALS.getStore() || null;
  if (want !== null && !ACTIVE.has(want)) want = null;
  if (want !== current) switchTo(want);
}

/**
 * A concurrent test starts: its context, entered for the rest of the caller's synchronous execution and everything
 * asynchronous it starts (call before the first `await` of the runner hook). `init(ctx)` sets up the per-test state
 * the first time the context runs (the shell's serial test start: STATE.beginTest in deferred mode).
 */
function begin(id, init) {
  const ctx = { id, snap: null, init, resumes: 0, done: false };
  ACTIVE.add(ctx);
  ALS.enterWith(ctx);
  return ctx;
}

/** A concurrent test's context, entered only by `within` (Jest: its test function is wrapped). */
function create(id, init) {
  const ctx = { id, snap: null, init, resumes: 0, done: false };
  ACTIVE.add(ctx);
  return ctx;
}

/** Run `fn` with `ctx` the running context (Jest: the test function; the test's end). */
function within(ctx, fn) {
  return ALS.run(ctx, () => { sync(); return fn(); });
}

/** The test of `ctx` ended (after its events were written): the context is no longer active. */
function finish(ctx) {
  ctx.done = true;
  ACTIVE.delete(ctx);
  if (current === ctx) switchTo(null);
}

/** The context the running code belongs to (null outside concurrent tests). */
function store() {
  if (ACTIVE.size === 0) return null;
  const s = ALS.getStore() || null;
  return s !== null && ACTIVE.has(s) ? s : null;
}

/** `fn` bound to the running context: it runs there later (a timer of the test, a held I/O completion). */
function bind(fn) {
  const ctx = store();
  if (ctx === null) {
    if (ACTIVE.size === 0) return fn;
    return (...a) => ALS.run(undefined, () => { sync(); return fn(...a); });
  }
  return (...a) => within(ctx, () => fn(...a));
}

function active() {
  return ACTIVE.size > 0;
}

function currentCtx() {
  return current;
}

module.exports = { register, sync, begin, create, within, finish, store, bind, active, currentCtx, ALS };
