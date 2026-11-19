'use strict';
// Seed space of a lockstep run (round 4, items 2 and 4): what a --det-seed may perturb, and where.
// The draws themselves are made by the Rust scheduler (crates/detpy-core/src/lockstep.rs); this file only reads
// the options:
//
//   DETJS_LS_LATENCIES   latency choices of a released message, in ms (e.g. "1,1,1,20,200"); a choice D[factor]
//                        means factor x the test's expect timeout (D1.5 = 1.5 x 5000 ms by default)
//   DETJS_LS_REORDER     1 (default) / 0: may a seed choose another pending message than the first in key order
//   DETJS_LS_FAULTS      socket faults a seed may plan: reset-request,reset-response,partial:MS,close-after
//   DETJS_LS_FAULT_KINDS message kinds faults apply to (api, browser, nav, ws-send, ws-recv); default api
//   DETJS_LS_FAULT_PERMILLE  probability (per mille) that a decision in focus draws a fault; default 0
//   DETJS_LS_FOCUS_TEST  only tests whose id contains this text are perturbed
//   DETJS_LS_FOCUS_FROM / _TO  only decisions in [from, to] of the focused test (from the default schedule)
//   DETJS_LS_FOCUS_KEYS  only messages whose key contains one of these (`|`-separated) texts
const NS = 1e6;

function deadlineMs(env) {
  return Number(env.DETJS_PW_DEADLINE_MS || 5000);
}

function parseLatencies(spec, env) {
  if (!spec) return [];
  return String(spec).split(',').map((x) => x.trim()).filter(Boolean).map((x) => {
    if (/^D[\d.]*$/.test(x)) return Math.ceil((Number(x.slice(1)) || 1.5) * deadlineMs(env)) * NS;
    return Math.max(0, Number(x)) * NS;
  }).filter((x) => Number.isFinite(x));
}

function configure(sched, env) {
  const lat = parseLatencies(env.DETJS_LS_LATENCIES, env);
  const faults = env.DETJS_LS_FAULTS || '';
  const kinds = (env.DETJS_LS_FAULT_KINDS || 'api').split(',').map((s) => s.trim()).filter(Boolean);
  const pm = Number(env.DETJS_LS_FAULT_PERMILLE || 0);
  sched.setSpace(lat, faults, kinds, pm, env.DETJS_LS_REORDER !== '0');
  sched.setFocus(env.DETJS_LS_FOCUS_TEST || '', Number(env.DETJS_LS_FOCUS_FROM || 0), Number(env.DETJS_LS_FOCUS_TO || 0),
    (env.DETJS_LS_FOCUS_KEYS || '').split('|').filter(Boolean));
}

module.exports = { configure, parseLatencies };
