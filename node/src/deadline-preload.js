'use strict';
// Loaded first (`--require`) in Vitest's workers under --det: the runner captures `Date.now` / `performance.now`
// when its modules are evaluated, before the controls exist, and checks its test and hook timeouts with them. These
// stand-ins answer the runner's deadline checks with the deadline clock (src/deadline.js) and every other caller with
// the real clock; until the controls are installed (and outside tests) they are the real clock.
const KEY = Symbol.for('detjs.deadlineClock');
if (!globalThis[KEY] && process.env.DETJS === '1') {
  const perf = globalThis.performance;
  const box = {
    perfNow: perf.now.bind(perf),
    dateNow: Date.now,
    hook: null,
  };
  globalThis[KEY] = box;
  const dateNow = function now() {
    if (box.hook !== null) { const v = box.hook('date'); if (v !== undefined) return Math.floor(v); }
    return box.dateNow();
  };
  const perfNow = function now() {
    if (box.hook !== null) { const v = box.hook('perf'); if (v !== undefined) return v; }
    return box.perfNow();
  };
  try { Object.defineProperty(Date, 'now', { value: dateNow, writable: true, configurable: true, enumerable: false }); } catch { /* keep */ }
  try { Object.defineProperty(perf, 'now', { value: perfNow, writable: true, configurable: true, enumerable: false }); } catch { /* keep */ }
}
