'use strict';
// Normalised filesystem enumeration order.
//
// `fs.readdir`, `fs.readdirSync`, `fs.promises.readdir` (names, Buffers or
// Dirents, also `recursive: true`) and `fs.opendir`/`opendirSync`/
// `promises.opendir` (the Dir is read eagerly, then iterated) return entries
// sorted by name (code units; Buffers byte-wise). Each enumeration done by the
// code under test is recorded (normalised directory, entry count, digest).

const fs = require('node:fs');
const path = require('node:path');
const { STATE } = require('./state');
const sites = require('./sites');

const real = {
  readdir: fs.readdir,
  readdirSync: fs.readdirSync,
  pReaddir: fs.promises.readdir,
  opendir: fs.opendir,
  opendirSync: fs.opendirSync,
  pOpendir: fs.promises.opendir,
};

function keyOf(e) {
  if (typeof e === 'string') return e;
  if (Buffer.isBuffer(e)) return e;
  // Dirent: with `recursive`, `parentPath`/`path` distinguishes entries.
  const parent = e.parentPath ?? e.path;
  return parent !== undefined && parent !== null ? path.join(String(parent), String(e.name)) : e.name;
}

function cmp(a, b) {
  const ka = keyOf(a);
  const kb = keyOf(b);
  if (Buffer.isBuffer(ka) || Buffer.isBuffer(kb)) return Buffer.compare(Buffer.from(ka), Buffer.from(kb));
  return ka < kb ? -1 : ka > kb ? 1 : 0;
}

function sortEntries(list) {
  return list.sort(cmp);
}

function event(op, where, list) {
  if (STATE.testId === null) return;
  const names = list.map((e) => (typeof e === 'string' || Buffer.isBuffer(e) ? e : String(e.name)));
  STATE.record('fs', op, `${sites.normPath(where)}|${names.length}|${STATE.digestNames(names)}`);
}

function readdirSync(p, options) {
  const out = sortEntries(real.readdirSync.call(fs, p, options));
  event('fs.readdirSync', p, out);
  return out;
}

function readdir(p, options, cb) {
  if (typeof options === 'function') { cb = options; options = undefined; }
  if (typeof cb !== 'function') return real.readdir.call(fs, p, options, cb); // native error
  return real.readdir.call(fs, p, options, (err, list) => {
    if (!err) { sortEntries(list); event('fs.readdir', p, list); }
    cb(err, list);
  });
}

async function pReaddir(p, options) {
  const list = sortEntries(await real.pReaddir.call(fs.promises, p, options));
  event('fs.promises.readdir', p, list);
  return list;
}

/** Stand-in for fs.Dir over a sorted, eagerly read listing. */
class SortedDir {
  constructor(dirPath, entries) {
    this.path = dirPath;
    this._entries = entries;
    this._i = 0;
    this._closed = false;
  }

  readSync() {
    return this._i < this._entries.length ? this._entries[this._i++] : null;
  }

  read(cb) {
    const v = this.readSync();
    if (typeof cb === 'function') { process.nextTick(cb, null, v); return undefined; }
    return Promise.resolve(v);
  }

  closeSync() { this._closed = true; }

  close(cb) {
    this._closed = true;
    if (typeof cb === 'function') { process.nextTick(cb, null); return undefined; }
    return Promise.resolve();
  }

  async *entries() {
    try {
      let e;
      while ((e = this.readSync()) !== null) yield e;
    } finally {
      this._closed = true;
    }
  }

  [Symbol.asyncIterator]() { return this.entries(); }

  *[Symbol.iterator]() {
    let e;
    while ((e = this.readSync()) !== null) yield e;
  }

  [Symbol.asyncDispose]() { return this.close(); }

  [Symbol.dispose]() { this.closeSync(); }
}

function readAllSync(dir) {
  const out = [];
  let e;
  while ((e = dir.readSync()) !== null) out.push(e);
  dir.closeSync();
  return sortEntries(out);
}

function opendirSync(p, options) {
  const dir = real.opendirSync.call(fs, p, options);
  const entries = readAllSync(dir);
  event('fs.opendirSync', p, entries);
  return new SortedDir(dir.path, entries);
}

async function pOpendir(p, options) {
  const dir = await real.pOpendir.call(fs.promises, p, options);
  const entries = [];
  for await (const e of dir) entries.push(e); // closes the Dir
  sortEntries(entries);
  event('fs.promises.opendir', p, entries);
  return new SortedDir(dir.path, entries);
}

function opendir(p, options, cb) {
  if (typeof options === 'function') { cb = options; options = undefined; }
  if (typeof cb !== 'function') return real.opendir.call(fs, p, options, cb);
  pOpendir(p, options).then((d) => cb(null, d), (err) => cb(err));
  return undefined;
}

function installProcess(patcher) {
  patcher.set(fs, 'readdirSync', readdirSync);
  patcher.set(fs, 'readdir', readdir);
  patcher.set(fs.promises, 'readdir', pReaddir);
  patcher.set(fs, 'opendirSync', opendirSync);
  patcher.set(fs, 'opendir', opendir);
  patcher.set(fs.promises, 'opendir', pOpendir);
}

module.exports = { installProcess, SortedDir, sortEntries };
