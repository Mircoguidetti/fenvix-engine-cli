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
const sites = require('./sites');
const { STATE } = require('./state');

/**
 * True when the call is one the test is answerable for.
 *
 * `sites.resolve()` gives null for the runner's own machinery and the engine's, and '<node>' when no user frame
 * is in reach at all. Everything else -- a project file, and a package under `<deps>/` -- is watched.
 */
function watchedSite() {
  const c = STATE.config;
  if (!c || !c.sites) return true;   // sites are not being resolved: do not lose the gap
  const site = STATE.quiet(() => sites.resolve());
  if (site === null || site === '<node>') return false;   // the runner's own machinery, or no user frame at all
  if (STATE.testId !== null) return true;                 // inside a test: whatever the test reached counts
  // Outside any test the run is the runner setting itself up, and a package it pulled in for its own purposes --
  // a reporter asking tty.isatty to decide on colour, a loader reading a package.json -- is not something a test
  // observed. Only the project's own code counts there, which is the same line controls.js' noteOutside draws for
  // environment reads outside any test.
  return !site.startsWith('<');
}

/** Name and version of this sensor, as the trace header declares it. */
const SENSOR = 'node-surface/1';

/** The runtime key the core matches against its audited runtimes (`node22`). */
function runtimeKey() {
  return `node${process.versions.node.split('.')[0]}`;
}

let seen = new Set();            // gaps already reported for the test named by seenFor
let seenFor = null;
const outside = new Set();       // gaps found while no test was running
let noteOutside = null;          // set by install(): controls.js' writer for not_proven_outside_tests
let active = false;
let reason = null;               // why there is no sensor, when there is none

/**
 * Builtins the sensor loads and arms itself, before any test file is loaded.
 *
 * Curated rather than "every builtin": requiring all of them pulls in the deprecated `node:domain` and
 * `node:sys`, which warn on load and which the sensor would then have charged the run for -- MEASURED, it made
 * every test NOT PROVEN with `module:domain` and `module:sys`. And evaluating `node:test`, `node:repl`,
 * `node:inspector`, `node:trace_events`, `node:cluster` or `node:wasi` is not neutral: those exist to start
 * something.
 *
 * The list is the modules the engine patches into, the pure ones (arming them is a no-op), and the few
 * unaccounted ones that are safe to require -- the last group only so that `syncBuiltinESMExports()` carries
 * their wrappers into the ESM named bindings, since an ESM `import` never passes through the CJS loader.
 * Anything else is armed if and when something loads it through that loader.
 */
const PREARM = new Set([
  // the engine patches into these
  'fs', 'fs/promises', 'os', 'net', 'dns', 'dns/promises', 'crypto', 'http', 'https', 'http2', 'tls', 'dgram',
  'child_process', 'worker_threads', 'timers', 'timers/promises', 'perf_hooks', 'module',
  // pure: arming is a no-op, listed so the set reads as the whole covered surface
  'path', 'util', 'events', 'stream', 'buffer', 'url', 'querystring', 'assert', 'zlib', 'string_decoder',
  'console',
  // unaccounted, but safe to require: armed so an ESM import of them meets the wrappers
  'v8', 'vm', 'tty', 'async_hooks', 'readline', 'readline/promises',
]);

/** Builtin modules this sensor has already looked at. */
const armed = new Set();

/**
 * One gap. Inside a test it is an event of that test; outside one it goes to the header.
 *
 * `atWatchedSite` exempts only the runner's own machinery and the engine's (Rule E of the PROVABLE measurement:
 * the runner's identity is a run input and nothing writes its environment during a run). Without it the sensor
 * charges every run with the worker channel the runner talks to its parent over, which no test ever sees.
 *
 * A PACKAGE IS NOT EXEMPT. controls.js' `projectSite` additionally rejects `<deps>/...`, which is right for
 * deciding whose environment read to record but wrong here: a gap a test reaches through an ordinary dependency
 * is still a gap the test has, and dropping it would be a false IDENTICAL. The Python sensor makes the same
 * choice -- site-packages is `_USER` there, and only the runner's own paths are `_INFRA`.
 */
function report(kind, name, atWatchedSite) {
  if (atWatchedSite && !atWatchedSite()) return;
  const key = `${kind}:${name}`;
  if (STATE.testId === null) {
    if (outside.has(key)) return;
    outside.add(key);
    if (noteOutside) { try { noteOutside(key); } catch { /* the run directory is gone */ } }
    return;
  }
  // keyed by the running test, not by the process: a set that is never cleared would report a gap for the first
  // test only and leave every later test of the worker looking clean
  if (seenFor !== STATE.testId) { seenFor = STATE.testId; seen = new Set(); }
  if (seen.has(key)) return;
  seen.add(key);
  STATE.recordAt('other', `unaccounted.${kind}`, '<sensor>', name);
  // The engine's existing "never reuse this test" signal. Without it the cache could store a test the rule
  // refuses, and a later run that reused it would declare the result provable on a premise that was never true
  // (session.js provableField's cache-only branch rests on exactly this).
  if (STATE.onLevel0Gap) { try { STATE.onLevel0Gap(`not accounted for: ${key}`); } catch { /* best effort */ } }
}

/**
 * Wrap `real` so that calling or constructing it marks the running test, and nothing else about it changes.
 *
 * A Proxy and not a plain function: `new Worker(...)` must keep working, and a hand-written wrapper that calls
 * `real.apply(this, args)` throws "Class constructor cannot be invoked without 'new'". The Proxy also keeps the
 * name, the length, the prototype and every own property without copying any of them.
 */
function wrap(real, name, key) {
  const mark = () => report('api', `${name}.${key}`, watchedSite);
  const w = new Proxy(real, {
    apply(t, thisArg, args) { mark(); return Reflect.apply(t, thisArg, args); },
    construct(t, args, newTarget) { mark(); return Reflect.construct(t, args, newTarget); },
  });
  WRAPPED.add(w);
  return w;
}

/** Wrappers this sensor made, so a second pass does not wrap one of its own. */
const WRAPPED = new WeakSet();

/**
 * Wrap every unaccounted function export of `mod` so that calling one marks the running test.
 *
 * Returns the number of exports wrapped, and -1 when the table has no rule for the module at all (every export
 * unaccounted): the caller then marks on load instead of wrapping a whole module's surface.
 */
/**
 * Keys of `obj` the engine has already patched.
 *
 * The engine's own wrapper is what accounts for a channel -- `children.js` replaces `worker_threads.Worker` so
 * that creating one marks the test `uncontrolled.thread`, which is a better answer than this sensor's generic
 * one. Wrapping over it would add noise and, worse, hide the engine's own patch behind another layer. So the
 * patch list is the authority: what the engine touched is left exactly as it is.
 */
function patchedKeys(patcher, obj) {
  const out = new Set();
  for (const [o, k] of patcher.saved || []) if (o === obj) out.add(String(k));
  return out;
}

function arm(patcher, name, exports_) {
  let policy;
  try { policy = native.provableModulePolicy(name); } catch { policy = 'unknown'; }
  if (policy === 'pure') return 0;
  if (!exports_ || (typeof exports_ !== 'object' && typeof exports_ !== 'function')) return 0;
  let keys;
  try { keys = Reflect.ownKeys(exports_).filter((k) => typeof k === 'string'); } catch { return 0; }
  const engine = patchedKeys(patcher, exports_);
  let n = 0;
  for (const k of keys) {
    if (engine.has(k)) continue;                      // the engine's own patch accounts for it
    let verdict;
    // the table has no rule for this module at all, so nothing in it is accounted for
    try { verdict = policy === 'unknown' ? 'unaccounted' : native.provableAccount(name, k); }
    catch { verdict = 'unaccounted'; }
    if (verdict !== 'unaccounted') continue;
    let real;
    try { real = exports_[k]; } catch { continue; }   // a getter that throws: left alone
    if (typeof real !== 'function' || WRAPPED.has(real)) continue;
    if (patcher.set(exports_, k, wrap(real, name, k))) n++;
  }
  // a module the table has no rule for: reaching it at all is the gap, so the caller marks on load as well as
  // relying on the wrappers above (an ESM `import` of it never passes through the CJS loader)
  return policy === 'unknown' ? -1 : n;
}

/**
 * Install the sensor. Must run after the engine's own controls, so that what the engine patched is in place and
 * already answers "accounted" in the table.
 *
 * Returns true when a sensor is active. False means this run declares none, and then every test of the run comes
 * out NOT PROVEN -- the honest answer, not a reason to stop watching.
 */
function install(patcher, notePut) {
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

  const armOne = (name, exports_, byUs) => {
    if (arm(patcher, name, exports_) === -1 && !byUs) unknown.add(name);
  };

  // `process` is the one global that is module-shaped, and the one every test touches
  armOne('process', process, true);

  // The builtins the engine itself patches into are armed now, before any test file is loaded, so a test cannot
  // hold a reference to an unwrapped export. The rest are armed the first time something loads them:
  // `node:repl`, `node:inspector` and `node:trace_events` do real work on first load and must not be pulled in
  // by the sensor itself.
  // Armed now, before any test file is loaded, so a test cannot hold a reference to an unwrapped export AND the
  // `syncBuiltinESMExports()` that controls.js calls right after carries these wrappers into the ESM named
  // bindings too. That matters: an ESM `import`/`import()` of a builtin never passes through the CJS loader, so
  // the lazy hook below would never see it. Everything is armed except the few whose evaluation is not something
  // the sensor should trigger by itself; for those, and only for those, the lazy hook is the only cover and an
  // ESM import of one is a declared residual.
  for (const name of builtins) {
    if (!PREARM.has(name)) continue;
    // `byUs`: the sensor loaded it, so loading is not something a test did and must not be marked. The wrappers
    // it installs still mark any USE of an unaccounted export, which is what the verdict turns on.
    try { armOne(name, require(name.startsWith('node:') ? name : `node:${name}`), true); armed.add(name); }
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
          if (arm(patcher, bare, r) === -1) {
            unknown.add(bare);
            report('module', bare, watchedSite);
          }
        } else if (unknown.has(bare)) {
          report('module', bare, watchedSite);
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
      // no project-site filter: an addon is a gap whoever loaded it -- unless it is one of the addons audited
      // by measurement (the core's NODE_AUDITED_NATIVE, evidence in docs/NATIVE-AUDITS.md). The engine's own
      // addon was exempt only by timing, and jest 30 loads its native resolver before the first test, which
      // made every test of every jest 30 suite NOT PROVEN.
      let audited = false;
      try { audited = native.provableNativeAudited(String(filename)); } catch { audited = false; }
      if (!audited) report('native', String(filename));
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
      // keyed by process AND thread: Vitest's pool=threads workers share one pid, and a file per pid let the last
      // thread's line overwrite another's (an `absent` replaced by `ok`: review of claude/runner-proof, C2)
      // appended, never overwritten (/review F1): a recycled pid with the same threadId adds its line to an earlier
      // part's instead of replacing it, so an `absent` line is never lost
      fs.appendFileSync(path.join(dir, `${partId()}.txt`), `${line}\n`);
    } finally { STATE.quietDepth--; }
  } catch { /* the run directory is gone */ }
}

/** This process and thread, as the name of its files under <run dir>/prov: `<pid>-<threadId>` (0: main thread). */
function partId() {
  return `${process.pid}-${require('node:worker_threads').threadId}`;
}

/**
 * Mark that this process or thread installed the engine's test hooks (src/controls.js installProcess): an empty
 * `prov/<pid>-<threadId>.ran`. `session.js` declares the run's sensor only when every marked part also declared
 * one (`prov/<pid>-<threadId>.txt`): a part that ran test code and declared nothing makes the run declare none.
 */
function markRan(dir) {
  if (!dir) return;
  const fs = require('node:fs');
  const path = require('node:path');
  STATE.quietDepth++;
  try {
    fs.mkdirSync(path.join(dir, 'prov'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'prov', `${partId()}.ran`), '');
  } catch { /* the run directory is gone */ } finally { STATE.quietDepth--; }
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

// No startTest hook: `report` keys its set by STATE.testId, so the set resets itself at the first gap of each
// test and there is nothing for the session to remember to call. An exported hook nobody calls is how the
// per-test set came to be never cleared in the first place.
module.exports = { install, header, runtimeKey, declare, markRan, SENSOR, get reason() { return reason; } };
