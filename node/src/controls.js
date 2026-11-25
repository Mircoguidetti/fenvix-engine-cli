'use strict';
const volatile = require('./volatile');
// P2 Phase B timing (DETJS_PHASES=1): loaded before any control is installed (real fs and clock captured)
const phases = require('./phases');
// Installation of the Level 0 controls and per-file / per-test lifecycle,
// shared by the Vitest and Jest shells.
const fs = require('node:fs');
const path = require('node:path');
const native = require('./native');
const config = require('./config');
const sites = require('./sites');
const { STATE } = require('./state');
const { Patcher } = require('./patch');
const clock = require('./clock');
const seeds = require('./seeds');
const fsorder = require('./fsorder');
const network = require('./network');
const { ENV_LOADED } = require('./outside');

const PATCHER = new Patcher();
let processInstalled = false;
const realms = new WeakSet();

function cfg() {
  if (!STATE.config) {
    STATE.config = config.fromEnv();
    sites.setRoot(STATE.config.root);
  }
  return STATE.config;
}

/** Install the process-wide controls (node: modules) once per process. */
function installProcess() {
  const c = cfg();
  if (processInstalled || !c.active) return c.active;
  processInstalled = true;
  if (c.controls.has('seeds')) seeds.installProcess(PATCHER, c);
  if (c.controls.has('time')) clock.installProcess(PATCHER, c);
  if (c.controls.has('net')) STATE.netMode = network.installProcess(PATCHER, c);  // design A (2026-11-20): CI-volatile variables pinned, and the host name (each runner has its own)
  volatile.pinEnv();
  PATCHER.set(require('node:os'), 'hostname', () => volatile.PINNED_HOSTNAME);
  volatile.pinCpus(PATCHER); // and the CPU count (each runner has its own)
  // environment reads (audit G-0126): every variable a test reads is an event `env.get NAME=set|unset`
  // (`env.has`, `env.list` of the names for enumerations): which variable, not its value, as detpy's envobs (design A,
  // 2026-11-20). The value is a run input (`env:NAME`, src/session.js): a differing one is reported `input-differs`
  // for the tests that read it, naming it; a CI-volatile one never diverges a test. Values never reach the trace.
  installEnvRecord(process);
  // detjs' own variables are not shown to test code (src/envview.js, audit G-2162)
  require('./envview').install();
  // machine and process facts, native key generation, mkdtemp names (src/facts.js)
  require('./facts').installProcess(PATCHER);
  // P1 C: a virtual pid leaving the process through a /proc path or os.get/setPriority is the real one (src/facts.js).
  // Below the fs controls (installed before them): src/fstime.js keeps its Stats mapping the outermost wrapper and
  // retires a wrapper found below another one, so a wrapper over it made every stat of a test unmapped (MEASURED:
  // ironcurtain test/ca.test.ts 2 -> 32 failed, lstatSync and fstatSync disagreeing on the virtual inode).
  require('./facts').installPidBoundaries(PATCHER);
  // completion order of a test's concurrent asynchronous I/O (src/ioorder.js); Level 1: timers against I/O
  require('./sched').installProcess(PATCHER);
  require('./ioorder').installProcess(PATCHER);
  // Above ioorder (P1 E, docs/DESIGN-P1.md section E): the directory listings and the file reads and metadata they
  // record are written when ioorder delivers each completion, in the order the test started the calls, not in the
  // order the thread pool completed them (two runs with the same calls recorded them in different orders).
  if (c.controls.has('fs')) fsorder.installProcess(PATCHER, c);
  if (c.controls.has('fs')) require('./outside').installProcess(PATCHER); // files outside the project: recorded (R-050 N1)
  // file times, inode and device numbers, fs.watch events (src/fstime.js); Buffer.allocUnsafe (src/realmx.js)
  if (c.controls.has('time')) require('./fstime').installProcess(PATCHER);
  require('./realmx').installProcess(PATCHER);
  // SQLite's clock and randomness (node:sqlite, better-sqlite3) and WASI's (src/sqlvirt.js, src/wasi.js)
  if (c.controls.has('time') && c.controls.has('seeds')) {
    try { require('./sqlvirt').installProcess(PATCHER); } catch (e) { level0Gap(`sqlite: ${e && e.message}`, false); }
    try { require('./wasi').installProcess(PATCHER); } catch (e) { level0Gap(`wasi: ${e && e.message}`, false); }
  }
  // worker threads, child processes and vm contexts started by tests (src/children.js)
  require('./children').installProcess(PATCHER, (g) => installRealm(g, { sameRealm: false, vm: true }));
  // The general rule's wide sensor, last of the controls: it wraps every builtin export the engine's accounting
  // table cannot account for, so it must see the engine's own patches already in place (those answer
  // "accounted" and are left alone). A run that cannot start it declares no sensor in the trace header, and then
  // every test of the run is NOT PROVEN, never IDENTICAL -- crates/detpy-core/src/provable.rs.
  try {
    if (!require('./provable').install(PATCHER, noteNotProven)) {
      STATE.__provableReason = require('./provable').reason;
      try { require('./provable').declare(); } catch { /* the run directory is gone */ }
      // Without the sensor nothing in this process can be shown identical, so nothing in it may be stored for
      // reuse either: a later run that reused one of its results would have no ground to call it provable.
      level0Gap(`the general rule's sensor is not running: ${STATE.__provableReason}`, false);
    }
  } catch (e) {
    STATE.__provableReason = `the sensor could not be installed: ${e && e.message}`;
    try { require('./provable').declare(); } catch { /* the run directory is gone */ }
  }
  // ESM named imports of builtins (`import { readdirSync } from 'node:fs'`)
  // are separate bindings: bring them in line with the patched objects. After the sensor, so that an import of an
  // unaccounted export gets the marking wrapper too.
  require('node:module').syncBuiltinESMExports();
  STATE.installed.push(`process:${process.pid}`);
  return true;
}

const OWN_ENV = /^(?:DETJS(?:$|_)|FENVIX_CACHE_)/;
// a variable read outside any test (module scope of a test file, a before/beforeAll hook, a dependency at import) is
// no test's event: its name goes to <run dir>/envout/<pid>.txt, the header lists it (src/session.js), and the
// verifier counts it as read by every test (R-054 N1); '*' for an enumeration
const outsideSeen = new Set();
// A CI-volatile variable that stays as it is (volatile.KEPT, not pinned), or a proxy variable while the network is
// closed: its value is no run input, so a test that reads it cannot be proven identical (review R-055 V1, V2,
// docs/VERIFY-CONTRACT.md section 3). A project's own FENVIX_VOLATILE_ENV names are declared irrelevant by the project
// and get no mark; engine variables neither.
const KEPT = new Set(volatile.KEPT.filter((k) => !(k in volatile.PINNED) && k !== 'FENVIX_VOLATILE_ENV'));
function unproven(name, realEnv) {
  if (name === '*') return Object.keys(realEnv || process.env).some((n) => unproven(n));
  if (KEPT.has(name)) return true;
  const c = STATE.config;
  return volatile.PROXY_ENV.has(name) && !!c && c.controls.has('net') && String(STATE.netMode) !== 'record' && String(STATE.netMode) !== 'open';
}
function projectSite() {
  const c = STATE.config;
  if (!c || !c.sites) return true;
  const site = sites.resolve();
  return site !== null && !site.startsWith('<');
}
const npSeen = new Set();
function noteNotProven(entry) {
  if (npSeen.has(entry)) return;
  const c = cfg();
  if (!c || !c.dir) return;
  npSeen.add(entry);
  STATE.quietDepth++;
  try {
    const dir = path.join(c.dir, 'npout');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, `${process.pid}.txt`), `${entry}\n`);
  } catch { /* the run directory is gone (the run ended) */ } finally { STATE.quietDepth--; }
}
/**
 * P1 A1 (docs/DESIGN-P1.md section A): the digest of what a read outside any test saw, so that `verify` can tell two
 * runs that saw the same value from two that did not (crates/detpy-core/src/verify.rs `undischarged_outside`). For an
 * enumeration, the sorted NAME=value lines without detjs' own variables and the engine's and runner's per-process
 * ones (volatile.patterns() prefixes: DETJS_, VITEST_, JEST_WORKER, ...), the exclusion runInputs (src/session.js)
 * applies to run inputs: otherwise every worker process would have its own digest.
 */
const CREDENTIALS = /:\/\/[^/@\s]*:[^/@\s]*@/;
function outsideDigest(name, realEnv) {
  const env = realEnv || process.env;
  let text;
  if (name === '*') {
    const { prefixes } = volatile.patterns();
    text = Object.keys(env).filter((n) => !OWN_ENV.test(n) && !prefixes.some((x) => n.startsWith(x))).sort()
      .map((n) => `${n}=${env[n]}`).join('\u0000');
  } else {
    text = Object.prototype.hasOwnProperty.call(env, name) ? `${name}=${env[name]}` : `${name}\u0000<unset>`;
  }
  return native.digest(Buffer.from(text)).slice(0, 16);
}
function noteOutside(op, k, realEnv) {
  if (STATE.quietDepth > 0) return;
  const name = op === 'env.list' ? '*' : String(k);
  if (name !== '*' && OWN_ENV.test(name)) return;
  // only the project's own code (not the runner copying the environment for a test file, not a package); the entry
  // carries the value's digest (P1 A1)
  if (STATE.quiet(() => unproven(name, realEnv) && projectSite())) {
    // a value carrying URL credentials (`scheme://user:pass@host`) gets no digest: a short unkeyed hash of a password
    // in the trace header can be reversed offline (review 2026-11-24). The bare name is never discharged by verify.
    const v = name === '*' ? '' : String((realEnv || process.env)[name] ?? '');
    // the file whose code made the read (its module scope, its hooks), so verify compares the values per file: two
    // files whose values swap between runs are not discharged, and a serial run compares with a parallel one
    // (founder decision D2 = A of 2026-11-25); no file open: no suffix
    const at = STATE.fileScopeLabel ? `@${STATE.fileScopeLabel}` : '';
    noteNotProven(CREDENTIALS.test(v) ? `env:${name}` : `env:${name}=${STATE.quiet(() => outsideDigest(name, realEnv))}${at}`);
  }
  if (outsideSeen.has(name)) return;
  const c = cfg();
  if (!c || !c.dir) return;
  outsideSeen.add(name);
  STATE.quietDepth++;
  try {
    const dir = path.join(c.dir, 'envout');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, `${process.pid}.txt`), `${name}\n`);
  } catch { /* the run directory is gone (the run ended) */ } finally { STATE.quietDepth--; }
}
let envSeen = new Set();
require('./concur').register({ name: 'env', save: () => envSeen, restore: (x) => { envSeen = x; } });
/**
 * The main process (the runner's configuration file, globalSetup): no test runs here, so a read from the project's
 * own code is a read outside any test (noteOutside); the runner's and its dependencies' reads are not (their first
 * frame outside detjs is under node_modules or node:). Replaced by installEnvRecord where tests run in this process.
 */
function installMainEnvRecord(root) {
  if (STATE.__envHooked || STATE.__envMainHooked) return;
  STATE.__envMainHooked = true;
  // detjs' own code: its src and bin directories (not the whole package: a project can live below it, as the test
  // fixtures do)
  const own = [path.resolve(__dirname) + path.sep, path.resolve(__dirname, '..', 'bin') + path.sep];
  STATE.onEnvRead = (op, k) => {
    if (STATE.quietDepth > 0) return;
    if (k !== '*' && OWN_ENV.test(String(k))) return;
    if (!projectFrame(root, own)) return;
    noteOutside(op, k);
  };
  try { require('./cache/capture').installLevel0Env(process); } catch (e) { level0Gap(`env: ${e && e.message}`, false); }
}

function projectFrame(root, own) {
  const stack = String(new Error().stack || '').split('\n').slice(2);
  for (const line of stack) {
    const m = line.match(/\(?((?:file:\/\/)?[^\s()]+?):\d+:\d+\)?\s*$/);
    if (!m) continue;
    let f = m[1];
    if (f.startsWith('file://')) { try { f = require('node:url').fileURLToPath(f); } catch { continue; } }
    if (f.startsWith('node:') || own.some((o) => f.startsWith(o))) continue;
    // Vite bundles the project's configuration file into node_modules/.vite-temp: it is the project's code
    const bundled = f.includes(`${path.sep}node_modules${path.sep}.vite-temp${path.sep}`);
    return f.startsWith(root + path.sep) && (bundled || !f.includes(`${path.sep}node_modules${path.sep}`));
  }
  return false;
}

function installEnvRecord(proc) {
  if (!STATE.__envHooked) {
    STATE.__envHooked = true;
    STATE.onTestStart.push(() => { envSeen = new Set(); });
    STATE.onEnvRead = (op, k, realEnv) => {
      if (STATE.testId === null) { noteOutside(op, k, realEnv); return; }
      if (STATE.quietDepth > 0 || STATE.recorder === null) return;
      if (k !== '*' && OWN_ENV.test(k)) return;
      const key = `${op}\u0000${k}`;
      if (envSeen.has(key)) return;
      let site = '';
      if (STATE.config.sites) {
        site = STATE.quiet(() => sites.resolve());
        if (site === null) return; // the runner's own reads
      }
      envSeen.add(key);
      let value;
      STATE.quietDepth++;
      try {
        if (op === 'env.list') {
          const names = Object.keys(realEnv).filter((n) => !OWN_ENV.test(n)).sort();
          value = `${names.length}:${native.digest(Buffer.from(names.join('\u0000'))).slice(0, 12)}`;
        } else if (ENV_LOADED.has(k) && Object.prototype.hasOwnProperty.call(realEnv, k)) {
          // set by process.loadEnvFile: no run input, so its value is part of the event (review R-055 V16)
          value = `${k}=${native.digest(Buffer.from(`${k}=${realEnv[k]}`)).slice(0, 16)}`;
        } else {
          value = `${k}=${Object.prototype.hasOwnProperty.call(realEnv, k) ? 'set' : 'unset'}`;
        }
      } finally { STATE.quietDepth--; }
      STATE.recordAt('other', op, site, value);
      const name = op === 'env.list' ? '*' : k;
      if (STATE.quiet(() => unproven(name, realEnv))) STATE.recordAt('other', 'uncontrolled.env', site, name);
    };
  }
  try { require('./cache/capture').installLevel0Env(proc); } catch (e) { level0Gap(`env: ${e && e.message}`, false); }
}

/** Install the realm controls (globals of one realm: Math, Date, timers, crypto). */
function installRealm(g, { sameRealm, vm = false }) {
  const c = cfg();
  if (!c.active) return;
  if (!vm) sites.setRealmError(g.Error); // a vm context of the code under test is not the test realm
  if (realms.has(g)) return;
  realms.add(g);
  // Jest gives every test file its own process object with a copy of the environment
  if (!vm && g.process && g.process !== process && g.process.env) installEnvRecord(g.process);
  if (!vm) require('./facts').installRealm(PATCHER, g);
  // A realm whose globals cannot be replaced keeps them: never silently (audit G-0181). The gap is noted in the
  // trace header, printed once, recorded as an `uncontrolled.level0` event in every later test of the process (the
  // verifier does not call such a test identical) and the cache does not reuse those tests.
  const failedBefore = PATCHER.failed.length;
  for (const [name, mod] of [['seeds', seeds], ['time', clock]]) {
    if (!c.controls.has(name)) continue;
    try {
      mod.installRealm(PATCHER, g, c, { sameRealm });
    } catch (e) {
      level0Gap(`${name}: realm installation failed: ${e && e.message}`, vm);
    }
  }
  try {
    require('./realmx').installRealm(PATCHER, g, c); // Temporal.Now, ShadowRealm
  } catch (e) {
    level0Gap(`realm: ${e && e.message}`, vm);
  }
  if (PATCHER.failed.length > failedBefore) level0Gap(`not replaceable: ${[...new Set(PATCHER.failed.slice(failedBefore))].join(',')}`, vm);
}

const GAPS = new Set();
function level0Gap(what, vm) {
  STATE.notes.push(what);
  if (vm) {
    // a vm context of the code under test: only the running test is concerned
    if (STATE.testId !== null) STATE.recordAt('other', 'uncontrolled.level0', '<detjs>', what);
    if (STATE.onLevel0Gap) STATE.onLevel0Gap(what);
    return;
  }
  if (GAPS.has(what)) return;
  GAPS.add(what);
  process.stderr.write(`detjs: WARNING: a Level 0 control could not be installed (${what}); the tests of this process are marked uncontrolled and never reused by the cache\n`);
  if (STATE.onLevel0Gap) STATE.onLevel0Gap(what);
  if (!STATE.__gapHooked) {
    STATE.__gapHooked = true;
    STATE.onTestStart.push(() => {
      for (const w of GAPS) STATE.recordAt('other', 'uncontrolled.level0', '<detjs>', w);
      if (STATE.onLevel0Gap) for (const w of GAPS) STATE.onLevel0Gap(w);
    });
  }
}

function stableName(s) {
  return native.digest(s).slice(0, 16);
}

/**
 * Start a test file: open the trace part of the file and seed module-level
 * randomness. `fileId` is the file path relative to the root.
 */
function openFile(fileId, project) {
  const c = cfg();
  if (!c.active) return;
  closeFile();
  const label = project ? `${project}|${fileId}` : fileId;
  if (c.dir) {
    const part = path.join(c.dir, 'parts', `${stableName(label)}.jsonl`);
    const rec = new native.Recorder(c.maxEvents);
    const meta = { file: fileId, project: project || null, pid: process.pid, threadId: require('node:worker_threads').threadId,
      notes: [...new Set(STATE.notes)] };
    rec.open(part, JSON.stringify(meta), []);
    STATE.recorder = rec;
  } else {
    STATE.recorder = null;
  }
  STATE.fileId = fileId;
  // the test file whose code runs outside its tests now (module scope, hooks): reads made there are scoped to it
  // (P1 B1, src/outside.js noteFile)
  STATE.fileScope = fileId;
  // the same file's label (with its project) for the outside-test env reads it makes (P1 A1, noteOutside)
  STATE.fileScopeLabel = label;
  STATE.testIndex = 0;
  STATE.begun = new Set();
  phases.fileStart(label);
  if (c.controls.has('seeds')) seeds.seedFile(label);
  // the virtual pid of the file's test code (P1 C, src/facts.js), seeded like the file's generators
  if (c.controls.has('seeds')) require('./facts').startFile(label);
  if (c.controls.has('net')) network.startFile(label);
  if (c.controls.has('time')) {
    clock.DRIVER.takeBaseline();
    clock.startFile();
    require('./fstime').startFile();
  }
}

function closeFile() {
  if (STATE.testId !== null) STATE.endTest('interrupted');
  STATE.fileScope = null;
  STATE.fileScopeLabel = null;
  require('./facts').endFile();
  // (Timers left pending by a test were released to real time when it ended.)
  if (STATE.recorder) {
    STATE.flush();
    STATE.recorder.close();
    STATE.recorder = null;
  }
  if (STATE.netMode === 'record') network.saveRecordings();
  phases.fileEnd();
}

/**
 * B5 (spec "Engine P0: no false green"): the tests of the open file that never reached the runner's per-test hook
 * (skipped by a failing beforeAll, filtered) get a record with outcome `skipped`, so that every test the runner
 * reports is in the trace whether the cache is on or not. `ids`: the file's test ids in declaration order. Called
 * by the runner shells just before the file's part is closed (src/vitest/shell.js, src/jest/runner.js).
 */
const NEVER_STARTED = 'sched.never_started';
function recordNeverStarted(ids) {
  if (!STATE.recorder) return 0;
  if (STATE.testId !== null) STATE.endTest('interrupted');
  let n = 0;
  for (const id of ids) {
    if (STATE.begun.has(id)) continue;
    STATE.beginTest(id);
    // the mark that this record is detjs', not the runner's: the hazard re-run never counts it as a re-run of the
    // test (src/parallel-rerun.js accountRerun), and a reader can tell it from a real skip
    STATE.record('sched', NEVER_STARTED, '', '<detjs>');
    STATE.endTest('skipped');
    n++;
  }
  return n;
}

/** Part file name for a test file (the wrapper merges parts in execution order). */
function partName(fileId, project) {
  return `${stableName(project ? `${project}|${fileId}` : fileId)}.jsonl`;
}

/** Ids for the tests of a file, unique within the file (`name #2` for duplicates). */
function uniqueIds(ids) {
  const seen = new Map();
  return ids.map((id) => {
    const n = (seen.get(id) || 0) + 1;
    seen.set(id, n);
    return n === 1 ? id : `${id} #${n}`;
  });
}

/**
 * Reproducible hierarchical shuffle of a tree (file -> describe blocks ->
 * tests): children of the node with key `key` are permuted with
 * shuffle_indices(n, seed, key), the same permutation the Python shell
 * applies to modules -> classes -> tests.
 */
function shuffleTree(children, seed, key, keyOf, childrenOf) {
  const perm = native.shuffleIndices(children.length, seed, key);
  const out = perm.map((i) => children[i]);
  for (const ch of out) {
    const sub = childrenOf(ch);
    if (sub && sub.length) {
      const shuffled = shuffleTree(sub, seed, keyOf(ch), keyOf, childrenOf);
      sub.splice(0, sub.length, ...shuffled);
    }
  }
  return out;
}

function writeJson(file, obj) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(obj, null, 1));
}

module.exports = {
  cfg, installProcess, installRealm, openFile, closeFile, recordNeverStarted, NEVER_STARTED, partName, uniqueIds, shuffleTree, writeJson,
  installMainEnvRecord, projectSite, PATCHER, STATE,
};
