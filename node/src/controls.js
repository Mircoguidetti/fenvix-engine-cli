'use strict';
const volatile = require('./volatile');
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
  if (c.controls.has('fs')) fsorder.installProcess(PATCHER, c);
  if (c.controls.has('fs')) require('./outside').installProcess(PATCHER); // files outside the project: recorded (R-050 N1)
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
  // completion order of a test's concurrent asynchronous I/O (src/ioorder.js); Level 1: timers against I/O
  require('./sched').installProcess(PATCHER);
  require('./ioorder').installProcess(PATCHER);
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
  // ESM named imports of builtins (`import { readdirSync } from 'node:fs'`)
  // are separate bindings: bring them in line with the patched objects.
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
  return volatile.PROXY_ENV.has(name) && !!c && c.controls.has('net') && String(STATE.netMode) !== 'record';
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
function noteOutside(op, k) {
  if (STATE.quietDepth > 0) return;
  const name = op === 'env.list' ? '*' : String(k);
  if (name !== '*' && OWN_ENV.test(name)) return;
  // only the project's own code (not the runner copying the environment for a test file, not a package)
  if (STATE.quiet(() => unproven(name) && projectSite())) noteNotProven(`env:${name}`);
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
      if (STATE.testId === null) { noteOutside(op, k); return; }
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
  STATE.testIndex = 0;
  if (c.controls.has('seeds')) seeds.seedFile(label);
  if (c.controls.has('net')) network.startFile(label);
  if (c.controls.has('time')) {
    clock.DRIVER.takeBaseline();
    clock.startFile();
    require('./fstime').startFile();
  }
}

function closeFile() {
  if (STATE.testId !== null) STATE.endTest('interrupted');
  // (Timers left pending by a test were released to real time when it ended.)
  if (STATE.recorder) {
    STATE.flush();
    STATE.recorder.close();
    STATE.recorder = null;
  }
  if (STATE.netMode === 'record') network.saveRecordings();
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
  cfg, installProcess, installRealm, openFile, closeFile, partName, uniqueIds, shuffleTree, writeJson,
  installMainEnvRecord, PATCHER, STATE,
};
