'use strict';
// P2 (coordinator 2026-11-26): src/parallel.js enter() checks the lane predecessor's done marker again before it
// reports the predecessor's process as dead. Before the fix, a predecessor that finished (done marker written) and
// exited while enter() slept was reported as "lane predecessor ... died", a false placement deviation.
//
// The race is made deterministic in-process: the done marker "appears" right after enter() reads the predecessor's
// start marker (the moment the process has just exited), and the start marker names a process that has exited.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function deadPid() {
  const r = spawnSync(process.execPath, ['-e', 'process.stdout.write(String(process.pid))'], { encoding: 'utf8' });
  return Number(r.stdout);
}

function setup() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'p2-enter-race-'));
  fs.mkdirSync(path.join(dir, 'lanes'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'plan.json'), JSON.stringify({ workers: 2, laneOf: { a: 0, b: 0 }, pred: { a: null, b: 'a' }, mode: 'vitest', digest: 'x' }));
  return dir;
}

test('enter(): a predecessor that finished and exited during the wait is not reported as dead', { timeout: 60000 }, () => {
  // protects= no false "lane predecessor died" deviation when the predecessor finished during the sleep;
  // fails_when= enter() returns that note although the done marker exists at the liveness check;
  // no_claim= a predecessor that really died (next test)
  const dir = setup();
  const parallel = require('../src/parallel');
  const native = require('../src/native');
  const name = (label, kind) => path.join(dir, 'lanes', `${native.digest(label).slice(0, 16)}.${kind}`);
  fs.writeFileSync(name('a', 'start'), JSON.stringify({ pid: deadPid(), thread: 0 }));
  const realRead = fs.readFileSync;
  fs.readFileSync = function patched(p, ...rest) {
    const out = realRead.call(fs, p, ...rest);
    if (p === name('a', 'start') && !fs.existsSync(name('a', 'done'))) fs.writeFileSync(name('a', 'done'), ''); // finished and exited now
    return out;
  };
  const old = process.env.DETJS_DIR;
  process.env.DETJS_DIR = dir;
  let info;
  try { info = parallel.enter('b'); } finally {
    fs.readFileSync = realRead;
    if (old === undefined) delete process.env.DETJS_DIR; else process.env.DETJS_DIR = old;
  }
  assert.equal(info.lane, 0);
  assert.equal(info.note, null, `note: ${info.note}`);
});

test('enter(): a predecessor whose process died without finishing is still reported', { timeout: 60000 }, () => {
  // protects= the fix does not hide a real death; fails_when= no note for a dead predecessor without a done marker;
  // no_claim= how long the wait takes
  const dir = setup();
  const parallel = require('../src/parallel');
  const native = require('../src/native');
  const name = (label, kind) => path.join(dir, 'lanes', `${native.digest(label).slice(0, 16)}.${kind}`);
  const pid = deadPid();
  fs.writeFileSync(name('a', 'start'), JSON.stringify({ pid, thread: 0 }));
  const old = process.env.DETJS_DIR;
  process.env.DETJS_DIR = dir;
  let info;
  try { info = parallel.enter('c-not-planned') && parallel.enter('b'); } finally {
    if (old === undefined) delete process.env.DETJS_DIR; else process.env.DETJS_DIR = old;
  }
  assert.equal(info.note, `lane predecessor a died (process ${pid})`);
});
