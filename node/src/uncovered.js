'use strict';
// Code Level 0 cannot reach is never silent (founder rule, P-041): the run prints it, the trace records an
// `uncontrolled.level0` event in each test concerned, and the cache never reuses that test (STATE.onLevel0Gap).
// The event's value carries a nonce drawn once per process from the real entropy source: two runs never record the
// same value, so `detjs verify` never calls such a test identical ("NOT COVERED by Level 0", with this event as the
// first difference) however deterministic the rest of its events look.
const { STATE } = require('./state');

let nonce = null;
function runNonce() {
  if (nonce === null) {
    STATE.quietDepth++;
    try { nonce = require('node:crypto').randomBytes(6).toString('hex'); } finally { STATE.quietDepth--; }
  }
  return nonce;
}

const printed = new Set();
/** Print `message` once per process (stderr). */
function warnOnce(message) {
  if (printed.has(message)) return;
  printed.add(message);
  process.stderr.write(`detjs: WARNING: ${message}\n`);
}

/** Record in the running test that `what` ran out of Level 0's reach. */
function mark(what) {
  STATE.recordAt('other', 'uncontrolled.level0', '<detjs>', `${what} [run ${runNonce()}]`);
  if (STATE.onLevel0Gap) STATE.onLevel0Gap(what);
}

module.exports = { mark, warnOnce, runNonce };
