'use strict';
// The wide sensor of the general rule, on the Node side.
//
// The rule itself is in the shared Rust core (crates/detpy-core/src/provable.rs): the accounting table and the
// one predicate that may conclude a test is provable. This file is only the sensor -- it reports facts, it
// decides nothing. What it reports, per test, is every builtin export the test reached that the core's table
// cannot account for, every builtin module the table has no rule for at all, and every native addon the engine
// has not reasoned about. The core then answers NOT PROVEN for that test, whatever its fingerprint.
//
// Why wrapping and not call monitoring
// ------------------------------------
// The Python side watches calls (sys.monitoring), because CPython's C types are immutable and their methods
// cannot be replaced. Node is the other way round: a builtin module's exports are writable, so the sensor can
// replace the ones the table does not account for with a wrapper that marks the test. That costs nothing per
// call on the accounted path -- the engine's own patches and the untouched exports run exactly as before.
//
// Where the boundary is
// ---------------------
// A test written in JavaScript can only reach outside state through a builtin module (`node:fs`, `node:os`, ...),
// a global the engine already controls (`Date`, `Math`, `crypto`, `performance`, `process`), or a native addon.
// Ordinary JavaScript is not a boundary: whatever a package does, it does through one of those. So the surface to
// account for is the builtin surface, which the `runtime` run input pins -- the same closed-world argument the
// Rust module writes out, with the Node version in place of the interpreter version.
//
// What this sensor cannot see (the declared residual)
// --------------------------------------------------
// * A native addon's own C++ reads. No in-process sensor sees them, which is why an addon the engine has not
//   reasoned about marks the test (`unaccounted.native`) instead of being trusted.
// * An export reached through a reference captured before this sensor installed. The engine installs its controls
//   before any test file is loaded, and this sensor installs with them, so a test cannot hold an earlier
//   reference; the runner itself might, and the runner is the declared controlled set (Rule E).
// * A non-function export that carries outside state through a getter. Functions are wrapped; a module whose
//   whole surface the table has no rule for marks on load, which is what covers the ones that matter
//   (`node:inspector`, `node:v8`, `node:repl`).

const native = require('./native');
const { STATE } = require('./state');

/** Name and version of this sensor, as the trace header declares it. */
const SENSOR = 'node-surface/1';

/** The runtime key the core matches against its audited runtimes (`node22`). */
function runtimeKey() {
  return `node${process.versions.node.split('.')[0]}`;
}

const seen = new Set();          // gaps already reported for the running test
const outside = new Set();       // gaps found while no test was running
let noteOutside = null;          // set by install(): controls.js' writer for not_proven_outside_tests
let active = false;
let reason = null;               // why there is no sensor, when there is none

/** Builtins that are safe and useful to arm before any test runs: the engine patches into most of them. */
const EAGER = new Set(['fs', 'fs/promises', 'os', 'net', 'dns', 'crypto', 'http', 'https', 'child_process',
  'worker_threads', 'timers', 'timers/promises', 'perf_hooks', 'path', 'util', 'events', 'stream', 'buffer',
  'url', 'querystring', 'assert', 'zlib', 'module', 'tls', 'dgram', 'string_decoder', 'console']);

/** Builtin modules this sensor has already looked at. */
const armed = new Set();

/**
 * One gap. Inside a test it is an event of that test; outside one it goes to the header.
 *
 * `atProjectSite` is the engine's existing rule for what counts (controls.js `projectSite`): a call whose nearest
 * frame outside detjs is the runner's own machinery or a package's is not something the test observed -- the
 * runner's identity is a run input and nothing writes its environment during a run (Rule E of the PROVABLE
 * measurement). Without this the sensor charges every run with the worker channel the runner talks to its parent
 * over, which no test ever sees.
 */
function report(kind, name, atProjectSite) {
  if (atProjectSite && !atProjectSite()) return;
  const key = `${kind}:${name}`;
  if (STATE.testId === null) {
    if (outside.has(key)) return;
    outside.add(key);
    if (noteOutside) { try { noteOutside(key); } catch { /* the run directory is gone */ } }
    return;
  }
  if (seen.has(key)) return;
  seen.add(key);
  STATE.recordAt('other', `unaccounted.${kind}`, '<sensor>', name);
}

function startTest() {
  seen.clear();
}

/** Copy a function's own properties onto its wrapper, as facts.js does, so the surface looks unchanged. */
function like(real, w) {
  for (const k of Reflect.ownKeys(real)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  try { Object.defineProperty(w, 'name', { value: real.name, configurable: true }); } catch { /* ignore */ }
  try { Object.defineProperty(w, '__detjsUnaccounted', { value: true }); } catch { /* ignore */ }
  return w;
}

/**
 * Wrap every unaccounted function export of `mod` so that calling one marks the running test.
 *
 * Returns the number of exports wrapped, and -1 when the table has no rule for the module at all (every export
 * unaccounted): the caller then marks on load instead of wrapping a whole module's surface.
 */
function arm(patcher, name, exports_, projectSite) {
  let policy;
  try { policy = native.provableModulePolicy(name); } catch { policy = 'unknown'; }
  // the table has no rule for this module at all, so reaching it is itself the gap: the caller marks on load
  // rather than wrapping a surface nothing is claimed about
  if (policy === 'unknown') return -1;
  if (policy === 'pure') return 0;
  if (!exports_ || (typeof exports_ !== 'object' && typeof exports_ !== 'function')) return 0;
  let keys;
  try { keys = Reflect.ownKeys(exports_).filter((k) => typeof k === 'string'); } catch { return 0; }
  let n = 0;
  for (const k of keys) {
    let verdict;
    try { verdict = native.provableAccount(name, k); } catch { verdict = 'unaccounted'; }
    if (verdict !== 'unaccounted') continue;
    let real;
    try { real = exports_[k]; } catch { continue; }   // a getter that throws: left alone
    if (typeof real !== 'function' || real.__detjsUnaccounted) continue;
    const w = like(real, function (...a) {
      report('api', `${name}.${k}`, projectSite);
      return real.apply(this, a);
    });
    if (patcher.set(exports_, k, w)) n++;
  }
  return n;
}

/**
 * Install the sensor. Must run after the engine's own controls, so that what the engine patched is in place and
 * already answers "accounted" in the table.
 *
 * Returns true when a sensor is active. False means this run declares none, and then every test of the run comes
 * out NOT PROVEN -- the honest answer, not a reason to stop watching.
 */
function install(patcher, notePut, projectSite) {
  noteOutside = notePut || null;
  if (process.env.FENVIX_NO_PROVABLE_SENSOR) {
    // turning the sensor off cannot buy a green: with no declaration the core refuses every test of the run.
    // It exists to measure what the sensor costs, and it is safe by construction.
    reason = 'the sensor was switched off with FENVIX_NO_PROVABLE_SENSOR';
    return false;
  }
  let audited;
  try { audited = native.provableRuntimes(); } catch { audited = []; }
  if (!audited.includes(runtimeKey())) {
    reason = `the engine's accounting table was not audited against ${runtimeKey()} (audited: ${audited.join(', ')})`;
    return false;
  }

  const mod = require('node:module');
  const builtins = (mod.builtinModules || []).filter((m) => !m.startsWith('_'));
  const unknown = new Set();

  const armOne = (name, exports_) => {
    if (arm(patcher, name, exports_, projectSite) === -1) unknown.add(name);
  };

  // `process` is the one global that is module-shaped, and the one every test touches
  armOne('process', process);

  // The builtins the engine itself patches into are armed now, before any test file is loaded, so a test cannot
  // hold a reference to an unwrapped export. The rest are armed the first time something loads them:
  // `node:repl`, `node:inspector` and `node:trace_events` do real work on first load and must not be pulled in
  // by the sensor itself.
  for (const name of builtins) {
    if (!EAGER.has(name)) continue;
    try { armOne(name, require(name.startsWith('node:') ? name : `node:${name}`)); armed.add(name); }
    catch { /* not available on this Node version */ }
  }

  // every other builtin is armed the first time something loads it, and a module the table has no rule for marks
  // the test then and there
  const realLoad = mod._load;
  if (typeof realLoad === 'function') {
    patcher.set(mod, '_load', function (request, parent, isMain) {
      const r = realLoad.call(this, request, parent, isMain);
      try {
        const bare = String(request).replace(/^node:/, '');
        if (!armed.has(bare) && builtins.includes(bare)) {
          armed.add(bare);
          if (arm(patcher, bare, r, projectSite) === -1) {
            unknown.add(bare);
            report('module', bare, projectSite);
          }
        } else if (unknown.has(bare)) {
          report('module', bare, projectSite);
        }
      } catch { /* never fail a load because of the sensor */ }
      return r;
    });
  }

  // a native addon: its C++ reads are invisible to any sensor, so loading one the engine has not reasoned about
  // is the gap itself (the declared residual)
  const realDlopen = process.dlopen;
  if (typeof realDlopen === 'function') {
    patcher.set(process, 'dlopen', function (module_, filename, ...rest) {
      report('native', String(filename));   // no project-site filter: an addon is a gap whoever loaded it
      return realDlopen.call(this, module_, filename, ...rest);
    });
  }

  // the unknown modules already loaded when the sensor started: reported without the project-site filter,
  // because by then whoever loaded them is gone from the stack
  for (const name of unknown) report('module', name);
  active = true;
  declare();
  return true;
}

/**
 * Write this process's sensor declaration into the run directory.
 *
 * Node runs tests in worker processes and merges their traces in the main process, which writes the header. A
 * worker's sensor is therefore not visible where the header is built, so every process states its own, and
 * `session.js` declares the run's sensor only when every part declared the same one. A part that could not start
 * a sensor makes the whole run declare none, which is the honest answer: its tests were not watched.
 */
function declare() {
  if (!noteOutside) return;
  try {
    const { cfg } = require('./controls');
    const c = cfg();
    if (!c || !c.dir) return;
    const fs = require('node:fs');
    const path = require('node:path');
    const dir = path.join(c.dir, 'prov');
    STATE.quietDepth++;
    try {
      fs.mkdirSync(dir, { recursive: true });
      const line = active ? `ok ${native.provableHeader(SENSOR, runtimeKey())}` : `absent ${reason || 'unknown'}`;
      fs.writeFileSync(path.join(dir, `${process.pid}.txt`), `${line}\n`);
    } finally { STATE.quietDepth--; }
  } catch { /* the run directory is gone */ }
}

/**
 * `meta.provable` for the trace header, or null when there is no sensor to declare.
 *
 * A header without it is what makes every test of the run NOT PROVEN in the core. That is the point: a run that
 * cannot say what it watched must not be able to claim a green.
 */
function header() {
  if (!active) return null;
  try { return JSON.parse(native.provableHeader(SENSOR, runtimeKey())); } catch { return null; }
}

module.exports = { install, startTest, header, runtimeKey, declare, SENSOR, get reason() { return reason; } };
