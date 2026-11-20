'use strict';
// File times, inode and device numbers under --det (audit G-0143, G-1410, G-1411).
//
// The file system keeps real time while `Date` is virtual: a file the test writes had a real mtime (2026) while
// `Date.now()` said 2025-01-01, ~688 days "in the future", and `fs.utimes(f, new Date())` stamped the file with the
// virtual date. One rule maps between the two, per test:
//
// * A time field of a Stats object the test's code obtained (`stat`, `lstat`, `fstat`, sync / callback / promise /
//   FileHandle, `fs.watchFile` listeners; `*Ms`, `*Ns` and so the `atime`/`mtime`/`ctime`/`birthtime` dates) is read
//   on the virtual clock: a time before the test started keeps its distance to the test start (its age), a time
//   during the test is the virtual time of the last virtual clock event at or before it (a clock read, a timer),
//   so never later than the virtual now, a time after the real now keeps its distance to the virtual now. The real
//   test start is anchored at the virtual test start (the epoch).
// * `utimes` / `futimes` / `lutimes` (and their promise and FileHandle forms) take virtual times: the file gets the
//   real time the rule maps to that virtual time, and reading it back gives exactly the virtual time that was set.
// * `ino` and `dev` are virtual: numbered in order of first sight per test file (1, 2, ...), so equal files have equal
//   numbers and the values do not depend on the checkout or the machine.
//
// Recording: the first read of each field of a Stats object is an event (`fs` `fs.stat.<field>`, value relative to
// the virtual test start). A time read whose mapped value depends on when the run happens (anything but a time the
// test set with utimes) is a real-clock read for the cache (src/cache/capture.js: `clock-real`, never reused), and
// differs in the trace from a run at another moment, so `detjs verify` never calls the two identical.
//
// fs.watch / fs.watchFile / fs.promises.watch (G-1411): the change events delivered to the test are events
// (`fs.watch <eventType>|<file>`, `fs.watchFile <file>|<mtime>`): the kernel decides their order and coalescing, the
// trace records it. They are real-time inputs for the cache. `fs.watchFile` pollers count as pending I/O for the
// timer driver (src/sched.js), so virtual timers do not outrun the real polling interval.
const fs = require('node:fs');
const { STATE } = require('./state');
const sites = require('./sites');

const SLACK_MS = 10; // coarse kernel timestamps: a file written right after the test start can be stamped before it
const TIME_FIELDS = ['atime', 'mtime', 'ctime', 'birthtime'];
const MAPPED = new WeakMap(); // Stats -> { raw: {field: value}, infra: bool|null, seen: Set, bigint }

let clock = null;
let R0 = 0; // real wall ms at the test start
let V0 = 0; // virtual wall ms at the test start
let cpReal = [];
let cpVirt = [];
const EXACT = new Map(); // real ms (integer) set by utimes -> virtual ms the test gave
let INO = new Map();
let DEV = new Map();

function realWallMs() {
  return clock.REAL.timeOrigin + clock.realNowMs();
}

function virtualNowMs() {
  const C = clock.CLOCK;
  return C ? C.wallMs(C.elapsed) : V0;
}

function anchor() {
  const C = clock.CLOCK;
  if (!C) return;
  R0 = realWallMs();
  V0 = C.wallMs(C.testStart);
  cpReal = [R0];
  cpVirt = [V0];
}

/** The virtual clock advanced to elapsed ns `e`: a checkpoint (real, virtual) of the test's timeline. */
function checkpoint(e) {
  const r = realWallMs();
  const v = clock.CLOCK.wallMs(e);
  const n = cpReal.length;
  if (n && r - cpReal[n - 1] < 0.05 && v === cpVirt[n - 1]) return;
  if (n && v < cpVirt[n - 1]) return; // a new test restarted the wall clock: anchor() handles it
  if (n >= 200000) { cpReal = cpReal.slice(n >> 1); cpVirt = cpVirt.slice(n >> 1); }
  cpReal.push(r);
  cpVirt.push(v);
}

/** Virtual wall ms for real wall ms `r`; `dep` is set to true when the result depends on when the run happens. */
function toVirtual(r, out) {
  const k = Math.round(r);
  if (Math.abs(r - k) < 0.001 && EXACT.has(k)) { out.exact = true; return EXACT.get(k); }
  out.exact = false;
  if (r < R0 - SLACK_MS) return V0 - (R0 - r);
  const now = realWallMs();
  if (r > now + SLACK_MS) return virtualNowMs() + (r - now);
  // during the test: the last checkpoint at or before r
  let lo = 0;
  let hi = cpReal.length - 1;
  if (hi < 0 || r < cpReal[0]) return V0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (cpReal[mid] <= r) lo = mid; else hi = mid - 1;
  }
  return cpVirt[lo];
}

/** Real wall ms the rule maps virtual ms `v` to (utimes). */
function toReal(v) {
  if (v <= V0) return R0 - (V0 - v);
  const vn = virtualNowMs();
  const now = realWallMs();
  if (v >= vn) return now + (v - vn);
  // inside the test's virtual span: the checkpoint at or before v
  let i = cpVirt.length - 1;
  while (i > 0 && cpVirt[i] > v) i--;
  return Math.min(now, cpReal[Math.max(0, i)] + (v - cpVirt[Math.max(0, i)]));
}

function virtualNumber(map, key) {
  let n = map.get(key);
  if (n === undefined) { n = map.size + 1; map.set(key, n); }
  return n;
}

function relText(v) {
  const d = v - V0;
  return d >= 0 ? `+${d}` : String(d);
}

function siteOrNull() {
  if (!STATE.config || !STATE.config.sites) return '';
  return STATE.quiet(() => sites.resolve());
}

/** Read of field `k` of a mapped Stats object. */
function mappedValue(st, e, k) {
  const raw = e.get[k] ? e.get[k].call(st) : e.raw[k];
  if (e.infra === null) e.infra = siteOrNull() === null;
  if (e.infra || STATE.quietDepth > 0) return raw;
  let value = raw;
  let text = null;
  let realDep = false;
  if (k === 'ino' || k === 'dev') {
    const devRaw = e.get.dev ? e.get.dev.call(st) : e.raw.dev;
    if (k === 'dev') {
      const n = virtualNumber(DEV, String(devRaw));
      value = e.bigint ? BigInt(n) : n;
    } else {
      const n = virtualNumber(INO, `${devRaw}:${raw}`);
      value = e.bigint ? BigInt(n) : n;
    }
    text = String(value);
  } else {
    const field = k.endsWith('Ns') ? k.slice(0, -2) : k.slice(0, -2);
    const ms = k.endsWith('Ns') ? Number(raw) / 1e6 : Number(raw);
    const out = {};
    const v = toVirtual(ms, out);
    realDep = !out.exact;
    if (k.endsWith('Ns')) value = BigInt(Math.round(v * 1e3)) * 1000n;
    else value = e.bigint ? BigInt(Math.floor(v)) : v;
    text = relText(v);
    void field;
  }
  if (!e.seen.has(k)) {
    e.seen.add(k);
    if (STATE.testId !== null) STATE.recordAt('fs', `fs.stat.${k}`, e.site, text);
    // (outside a test too: a module-level read belongs to every test of the file)
    if (realDep && STATE.onRealClock) STATE.onRealClock(`fs.stat ${k} (file time on the virtual clock: depends on when the run happens)`);
  }
  return value;
}

/** Make the time, inode and device fields of Stats `st` read through the mapping (test code only). */
function mapStats(st, site) {
  if (!st || typeof st !== 'object' || MAPPED.has(st) || clock === null || !clock.CLOCK) return st;
  if (site === undefined) site = siteOrNull();
  if (site === null) return st; // the runner's own call
  const e = { raw: {}, get: {}, infra: false, seen: new Set(), bigint: typeof st.mtimeNs === 'bigint' || typeof st.ino === 'bigint', site: site || '' };
  const keys = ['ino', 'dev'];
  for (const f of TIME_FIELDS) keys.push(`${f}Ms`, `${f}Ns`);
  for (const k of keys) {
    const d = Object.getOwnPropertyDescriptor(st, k);
    if (!d || !d.configurable) continue;
    if ('value' in d) e.raw[k] = d.value; else if (typeof d.get === 'function') e.get[k] = d.get; else continue;
    try {
      Object.defineProperty(st, k, {
        get() { return mappedValue(this, e, k); },
        set(v) { try { Object.defineProperty(this, k, { value: v, writable: true, enumerable: d.enumerable, configurable: true }); } catch { /* frozen */ } },
        enumerable: d.enumerable,
        configurable: true,
      });
    } catch { /* not extensible */ }
  }
  MAPPED.set(st, e);
  return st;
}

function installInspect() {
  const proto = Object.getPrototypeOf(Object.getPrototypeOf(fs.statSync(__filename)));
  if (!proto || proto.__detjsFsTime) return;
  Object.defineProperty(proto, '__detjsFsTime', { value: true });
  const custom = Symbol.for('nodejs.util.inspect.custom');
  const prev = Object.getOwnPropertyDescriptor(proto, custom);
  Object.defineProperty(proto, custom, {
    value: function inspectStats(depth, options, inspect) {
      if (!MAPPED.has(this)) return prev && typeof prev.value === 'function' ? prev.value.call(this, depth, options, inspect) : this;
      const out = Object.create(Object.getPrototypeOf(this));
      for (const k of Object.keys(this)) Object.defineProperty(out, k, { value: this[k], writable: true, enumerable: true, configurable: true });
      return out;
    },
    writable: true, enumerable: false, configurable: true,
  });
}

function copyMeta(real, w) {
  for (const k of Reflect.ownKeys(real)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  try { Object.defineProperty(w, 'name', { value: real.name, configurable: true }); } catch { /* ignore */ }
  return w;
}

function active() {
  return clock !== null && clock.CLOCK !== null && STATE.quietDepth === 0;
}

// The wrappers stay the outermost layer: a wrapper installed later over one of them (the cache capture's stat
// recording) is wrapped again at the next test start, and the inner one passes through. The cache then sees the
// real Stats object and keys the fields the mapping reads.
const SPECS = []; // [obj, name, make(real) -> wrapper]
const CURRENT = new WeakSet();

function install(o, name, make) {
  SPECS.push([o, name, make]);
  wrapOne(o, name, make);
}

function wrapOne(o, name, make) {
  const real = o && o[name];
  if (typeof real !== 'function' || CURRENT.has(real)) return;
  let w;
  const inner = make(real, () => CURRENT.has(w));
  w = copyMeta(real, inner);
  CURRENT.add(w);
  for (const old of [real]) if (old && old.__detjsFsTimeOld) old.__detjsFsTimeOld();
  Object.defineProperty(w, '__detjsFsTimeOld', { value: () => CURRENT.delete(w), configurable: true });
  try { o[name] = w; } catch { /* read-only */ }
}

/** Wrap again what was wrapped over the mapping since the last test start. */
function rewrap() {
  for (const [o, name, make] of SPECS) {
    const cur = o[name];
    if (typeof cur === 'function' && !CURRENT.has(cur)) {
      // our wrapper is somewhere below: retire it, wrap the current function
      wrapOne(o, name, make);
    }
  }
}

function wrapStatSync(o, name) {
  install(o, name, (real, current) => function (...a) {
    const r = real.apply(this, a);
    return current() && active() ? mapStats(r) : r;
  });
}

function wrapStatCb(o, name) {
  install(o, name, (real, current) => function (...a) {
    const i = a.length - 1;
    if (i >= 0 && typeof a[i] === 'function' && current() && active()) {
      const site = siteOrNull();
      if (site !== null) {
        const cb = a[i];
        a[i] = function (err, st) { return cb.call(this, err, err ? st : mapStats(st, site)); };
      }
    }
    return real.apply(this, a);
  });
}

function wrapStatPromise(o, name) {
  install(o, name, (real, current) => function (...a) {
    const p = real.apply(this, a);
    if (!current() || !active() || !p || typeof p.then !== 'function') return p;
    const site = siteOrNull();
    return site === null ? p : p.then((st) => mapStats(st, site));
  });
}

/** utimes-like function: argument indexes of atime and mtime (virtual times given by the test). */
function toRealArg(t) {
  if (!active() || STATE.testId === null && !clock.CLOCK) return t;
  let ms;
  if (Object.prototype.toString.call(t) === '[object Date]') ms = Date.prototype.getTime.call(t); // any realm's Date
  else if (typeof t === 'number') ms = t * 1000;
  else if (typeof t === 'bigint') ms = Number(t) * 1000;
  else if (typeof t === 'string' && t !== '' && Number.isFinite(Number(t))) ms = Number(t) * 1000;
  else return t;
  if (!Number.isFinite(ms)) return t;
  const r = Math.round(toReal(ms));
  EXACT.set(r, ms);
  if (EXACT.size > 100000) EXACT.delete(EXACT.keys().next().value);
  return r / 1000;
}

function wrapUtimes(o, name, i0) {
  install(o, name, (real, current) => function (...a) {
    if (current() && active() && siteOrNull() !== null) {
      a[i0] = toRealArg(a[i0]);
      a[i0 + 1] = toRealArg(a[i0 + 1]);
    }
    return real.apply(this, a);
  });
}

/** FileHandle methods (stat, utimes): patched on the prototype of the first handle the test opens. */
function patchFileHandle(h) {
  const P = h && Object.getPrototypeOf(h);
  if (!P || P.__detjsFsTime) return;
  Object.defineProperty(P, '__detjsFsTime', { value: true });
  wrapStatPromise(P, 'stat');
  wrapUtimes(P, 'utimes', 0);
}

let watchSeq = 0;
function recordWatch(op, site, value) {
  if (STATE.testId === null) return;
  STATE.recordAt('fs', op, site, value);
  if (STATE.onRealClock) STATE.onRealClock(`${op} events (delivered by the kernel / real-time polling)`);
}

function normName(f) {
  if (f === null || f === undefined) return '<none>';
  return Buffer.isBuffer(f) ? f.toString('utf8') : String(f);
}

function installWatch(patcher) {
  const realWatch = fs.watch;
  if (typeof realWatch === 'function' && !realWatch.__detjsFsTime) {
    const w = copyMeta(realWatch, function watch(...a) {
      const watcher = realWatch.apply(this, a);
      if (!active() || STATE.testId === null) return watcher;
      const site = siteOrNull() || '<deps>';
      const target = sites.normPath(a[0]);
      const id = watchSeq++;
      const emit = watcher.emit;
      watcher.emit = function (ev, ...x) {
        if (ev === 'change') recordWatch('fs.watch', site, `${target}|${x[0]}|${normName(x[1])}`);
        else if (ev === 'error') recordWatch('fs.watch', site, `${target}|error`);
        return emit.call(this, ev, ...x);
      };
      void id;
      return watcher;
    });
    Object.defineProperty(w, '__detjsFsTime', { value: true });
    patcher.set(fs, 'watch', w);
  }
  const realWatchFile = fs.watchFile;
  if (typeof realWatchFile === 'function' && !realWatchFile.__detjsFsTime) {
    const LISTENERS = new WeakMap();
    const w = copyMeta(realWatchFile, function watchFile(file, options, listener) {
      if (typeof options === 'function') { listener = options; options = undefined; }
      if (typeof listener !== 'function' || !active() || STATE.testId === null) return realWatchFile.call(this, file, options, listener);
      const site = siteOrNull();
      if (site === null) return realWatchFile.call(this, file, options, listener);
      const target = sites.normPath(file);
      const l = function (curr, prev) {
        mapStats(curr, site);
        mapStats(prev, site);
        recordWatch('fs.watchFile', site, `${target}|${STATE.quiet(() => curr.mtimeMs) === 0 ? 'missing' : 'changed'}`);
        return listener.call(this, curr, prev);
      };
      LISTENERS.set(listener, l);
      return options === undefined ? realWatchFile.call(this, file, l) : realWatchFile.call(this, file, options, l);
    });
    Object.defineProperty(w, '__detjsFsTime', { value: true });
    patcher.set(fs, 'watchFile', w);
    const realUnwatch = fs.unwatchFile;
    if (typeof realUnwatch === 'function') {
      patcher.set(fs, 'unwatchFile', copyMeta(realUnwatch, function unwatchFile(file, listener) {
        return realUnwatch.call(this, file, listener && LISTENERS.has(listener) ? LISTENERS.get(listener) : listener);
      }));
    }
  }
  const P = fs.promises;
  if (P && typeof P.watch === 'function' && !P.watch.__detjsFsTime) {
    const real = P.watch;
    const w = copyMeta(real, function watch(...a) {
      const it = real.apply(this, a);
      if (!active() || STATE.testId === null || !it || typeof it.next !== 'function') return it;
      const site = siteOrNull() || '<deps>';
      const target = sites.normPath(a[0]);
      const next = it.next;
      it.next = function (...x) {
        return next.apply(this, x).then((r) => {
          if (r && !r.done && r.value) recordWatch('fs.watch', site, `${target}|${r.value.eventType}|${normName(r.value.filename)}`);
          return r;
        });
      };
      return it;
    });
    Object.defineProperty(w, '__detjsFsTime', { value: true });
    patcher.set(P, 'watch', w);
  }
}

function installProcess(patcher) {
  if (STATE.__fsTimeHooked) return;
  STATE.__fsTimeHooked = true;
  clock = require('./clock');
  clock.setOnRead(checkpoint);
  STATE.onTestStart.push(() => { anchor(); rewrap(); });
  anchor();
  for (const n of ['statSync', 'lstatSync', 'fstatSync']) wrapStatSync(fs, n);
  for (const n of ['stat', 'lstat', 'fstat']) wrapStatCb(fs, n);
  for (const n of ['stat', 'lstat']) wrapStatPromise(fs.promises, n);
  for (const n of ['utimesSync', 'futimesSync', 'lutimesSync', 'utimes', 'futimes', 'lutimes']) wrapUtimes(fs, n, 1);
  for (const n of ['utimes', 'lutimes']) wrapUtimes(fs.promises, n, 1);
  install(fs.promises, 'open', (open) => function (...a) {
    return open.apply(this, a).then((h) => { try { patchFileHandle(h); } catch { /* ignore */ } return h; });
  });
  installWatch(patcher);
  try { installInspect(); } catch { /* ignore */ }
}

/** A test file starts: inode and device numbers restart. */
function startFile() {
  INO = new Map();
  DEV = new Map();
  if (clock !== null) { anchor(); rewrap(); }
}

module.exports = { installProcess, startFile, mapStats, toVirtual, toReal };
