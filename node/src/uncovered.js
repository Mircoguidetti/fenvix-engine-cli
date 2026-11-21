'use strict';
// Code Level 0 cannot reach is never silent (founder rule, P-041): the run prints it, the trace records an
// `uncontrolled.level0` event in each test concerned, and the cache never reuses that test (STATE.onLevel0Gap).
// The verifier never calls a test with an `uncontrolled.*` event identical ("not controlled by this release", with
// that source as the reason), whatever its value: the value is only what ran out of reach, the same in every run, so
// a replay of such a test keeps one fingerprint (a per-run nonce here made every replay's fingerprint differ).
const { STATE } = require('./state');

const printed = new Set();
/** Print `message` once per process (stderr). */
function warnOnce(message) {
  if (printed.has(message)) return;
  printed.add(message);
  process.stderr.write(`detjs: WARNING: ${message}\n`);
}

/** Record in the running test that `what` ran out of Level 0's reach. */
function mark(what) {
  STATE.recordAt('other', 'uncontrolled.level0', '<detjs>', what);
  if (STATE.onLevel0Gap) STATE.onLevel0Gap(what);
}

module.exports = { mark, warnOnce };
