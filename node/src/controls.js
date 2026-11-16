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
  // ESM named imports of builtins (`import { readdirSync } from 'node:fs'`)
  // are separate bindings: bring them in line with the patched objects.
  require('node:module').syncBuiltinESMExports();
  STATE.installed.push(`process:${process.pid}`);
  return true;
}

/** Install the realm controls (globals of one realm: Math, Date, timers, crypto). */
function installRealm(g, { sameRealm }) {
  const c = cfg();
  if (!c.active) return;
  sites.setRealmError(g.Error);
  if (realms.has(g)) return;
  realms.add(g);
  // Fail-soft: a realm whose globals cannot be replaced keeps them (noted).
  for (const [name, mod] of [['seeds', seeds], ['time', clock]]) {
    if (!c.controls.has(name)) continue;
    try {
      mod.installRealm(PATCHER, g, c, { sameRealm });
    } catch (e) {
      STATE.notes.push(`${name}: realm installation failed: ${e && e.message}`);
    }
  }
  if (PATCHER.failed.length) STATE.notes.push(`not replaceable: ${[...new Set(PATCHER.failed)].join(',')}`);
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
  if (c.controls.has('time')) clock.DRIVER.takeBaseline();
}

function closeFile() {
  if (STATE.testId !== null) STATE.endTest('interrupted');
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
