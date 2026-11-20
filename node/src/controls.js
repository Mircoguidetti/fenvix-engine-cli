'use strict';
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
  if (c.controls.has('net')) STATE.netMode = network.installProcess(PATCHER, c);
  // environment reads (audit G-0126): every variable a test reads is an event `env.get NAME=<digest of the value>`
  // (`env.has`, `env.list` for enumerations); values never reach the trace
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
let envSeen = new Set();
function installEnvRecord(proc) {
  if (!STATE.__envHooked) {
    STATE.__envHooked = true;
    STATE.onTestStart.push(() => { envSeen = new Set(); });
    STATE.onEnvRead = (op, k, realEnv) => {
      if (STATE.testId === null || STATE.quietDepth > 0 || STATE.recorder === null) return;
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
          const pairs = Object.keys(realEnv).filter((n) => !OWN_ENV.test(n)).sort().map((n) => `${n}=${realEnv[n]}`);
          value = `${pairs.length}:${native.digest(Buffer.from(pairs.join('\u0000'))).slice(0, 12)}`;
        } else if (op === 'env.has') {
          value = `${k}=${Object.prototype.hasOwnProperty.call(realEnv, k) ? 'set' : 'unset'}`;
        } else {
          const raw = Object.prototype.hasOwnProperty.call(realEnv, k) ? realEnv[k] : undefined;
          value = raw === undefined ? `${k}=unset` : `${k}=${native.digest(Buffer.from(String(raw))).slice(0, 12)}`;
        }
      } finally { STATE.quietDepth--; }
      STATE.recordAt('other', op, site, value);
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
  PATCHER, STATE,
};
