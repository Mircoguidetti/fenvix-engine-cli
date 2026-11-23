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

// `site`: the caller's site taken when the listing was asked for (callback and promise forms report after the
// caller's frame is gone: audit G-1481)
function event(op, where, list, site) {
  if (STATE.testId === null) return;
  const names = list.map((e) => (typeof e === 'string' || Buffer.isBuffer(e) ? e : String(e.name)));
  STATE.record('fs', op, `${sites.normPath(where)}|${names.length}|${STATE.digestNames(names)}`, site);
}

function readdirSync(p, options) {
  const out = sortEntries(real.readdirSync.call(fs, p, options));
  event('fs.readdirSync', p, out);
  return out;
}

function readdir(p, options, cb) {
  if (typeof options === 'function') { cb = options; options = undefined; }
  if (typeof cb !== 'function') return real.readdir.call(fs, p, options, cb); // native error
  const site = STATE.callSite();
  return real.readdir.call(fs, p, options, (err, list) => {
    if (!err) { sortEntries(list); event('fs.readdir', p, list, site); }
    cb(err, list);
  });
}

function pReaddir(p, options) {
  const site = STATE.callSite();
  return real.pReaddir.call(fs.promises, p, options).then((list) => {
    sortEntries(list);
    event('fs.promises.readdir', p, list, site);
    return list;
  });
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

async function openSorted(p, options, op, site) {
  const dir = await real.pOpendir.call(fs.promises, p, options);
  const entries = [];
  for await (const e of dir) entries.push(e); // closes the Dir
  sortEntries(entries);
  event(op, p, entries, site);
  return new SortedDir(dir.path, entries);
}

function pOpendir(p, options) {
  return openSorted(p, options, 'fs.promises.opendir', STATE.callSite());
}

function opendir(p, options, cb) {
  if (typeof options === 'function') { cb = options; options = undefined; }
  if (typeof cb !== 'function') return real.opendir.call(fs, p, options, cb);
  openSorted(p, options, 'fs.promises.opendir', STATE.callSite()).then((d) => cb(null, d), (err) => cb(err));
  return undefined;
}

// fs.glob / fs.promises.glob (Node 22+) read directories inside Node, after their caller's frame is gone: their
// events carry the caller's site
function glob(...a) {
  const site = STATE.callSite();
  return STATE.withSite(site, () => real.glob.apply(fs, a));
}

function pGlob(...a) {
  const site = STATE.callSite();
  const it = STATE.withSite(site, () => real.pGlob.apply(fs.promises, a));
  if (!it || typeof it.next !== 'function') return it;
  const next = it.next.bind(it);
  it.next = (...x) => STATE.withSite(site, () => next(...x));
  return it;
}

function installProcess(patcher) {
  // the functions installed now (src/ioorder.js' ordered delivery, P1 E), not the ones loaded at require time
  Object.assign(real, { readdir: fs.readdir, readdirSync: fs.readdirSync, pReaddir: fs.promises.readdir,
    opendir: fs.opendir, opendirSync: fs.opendirSync, pOpendir: fs.promises.opendir });
  if (typeof fs.glob === 'function') { real.glob = fs.glob; patcher.set(fs, 'glob', glob); }
  if (typeof fs.promises.glob === 'function') { real.pGlob = fs.promises.glob; patcher.set(fs.promises, 'glob', pGlob); }
  patcher.set(fs, 'readdirSync', readdirSync);
  patcher.set(fs, 'readdir', readdir);
  patcher.set(fs.promises, 'readdir', pReaddir);
  patcher.set(fs, 'opendirSync', opendirSync);
  patcher.set(fs, 'opendir', opendir);
  patcher.set(fs.promises, 'opendir', pOpendir);
}

module.exports = { installProcess, SortedDir, sortEntries };
