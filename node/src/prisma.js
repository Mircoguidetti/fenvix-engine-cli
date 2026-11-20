'use strict';
// Prisma on the engine clock (round 4, documenso).
//
// Prisma Client fills `@default(now())` and `@updatedAt` fields in its native query engine (Rust), which reads the
// machine's clock directly: libfaketime does not reach it (MEASURED: under libfaketime JS Date read the engine time,
// the row Prisma created carried the real time). Rows seeded by the test code and by the app server therefore carry
// real timestamps, and pages show them (documenso: `createdAt` of the seeded organisation member, first divergence of
// the gate replays).
//
// The shim gives those fields their value in JavaScript before the request reaches the engine: `new Date()`, which
// is the engine's clock inside tests (runner) and inside messages (app servers). Fields the caller set are left
// alone; nested writes (create, createMany, connectOrCreate, upsert, update) are followed through relations.
// It hooks `getPrismaClient` of Prisma's runtime (`@prisma/client/runtime/library.js` / `client.js`) and wraps
// `_executeRequest` of the client class it returns; the field metadata is the client's runtime data model.

const Module = require('node:module');

const CREATE = new Set(['create', 'createOne', 'createMany', 'createManyAndReturn', 'upsert', 'upsertOne']);
const UPDATE = new Set(['update', 'updateOne', 'updateMany', 'updateManyAndReturn']);

function modelInfo(dm, name) {
  const m = dm && dm.models && dm.models[name];
  if (!m) return null;
  if (!m.__detjs) {
    const now = [];
    const upd = [];
    const gen = [];
    const rel = new Map();
    for (const f of m.fields || []) {
      if (f.kind === 'scalar' && f.default && f.default.name === 'now') now.push(f.name);
      if (f.kind === 'scalar' && f.default && GEN.has(f.default.name)) gen.push([f.name, f.default.name, f.default.args || []]);
      if (f.isUpdatedAt) upd.push(f.name);
      if (f.kind === 'object') rel.set(f.name, f.type);
    }
    Object.defineProperty(m, '__detjs', { value: { now, upd, gen, rel } });
  }
  return m.__detjs;
}

function fillCreate(dm, model, data, t) {
  if (!data || typeof data !== 'object') return;
  if (Array.isArray(data)) { for (const d of data) fillCreate(dm, model, d, t); return; }
  const mi = modelInfo(dm, model);
  if (!mi) return;
  for (const f of mi.now) if (data[f] === undefined) data[f] = new Date(t);
  for (const f of mi.upd) if (data[f] === undefined) data[f] = new Date(t);
  for (const [f, kind, args] of mi.gen) if (data[f] === undefined) data[f] = genId(kind, args, t);
  nested(dm, mi, data, t);
}

// Ids Prisma's engine would generate (cuid from time, process id and a counter; uuid; nanoid; ulid): drawn from the
// process's own randomness instead (seeded per test in the runner, per message in app servers), same formats.
const GEN = new Set(['cuid', 'uuid', 'nanoid', 'ulid']);
function rand(n) {
  const b = new Uint8Array(n);
  globalThis.crypto.getRandomValues(b);
  return b;
}
function genId(kind, args, t) {
  if (kind === 'uuid') return globalThis.crypto.randomUUID();
  if (kind === 'cuid') {
    const a = '0123456789abcdefghijklmnopqrstuvwxyz';
    const b = rand(24);
    let s = 'c';
    for (let i = 0; i < 24; i++) s += a[b[i] % 36];
    return s;
  }
  if (kind === 'nanoid') {
    const n = Number(args && args[0]) || 21;
    const a = 'useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict';
    const b = rand(n);
    let s = '';
    for (let i = 0; i < n; i++) s += a[b[i] & 63];
    return s;
  }
  // ulid: 10 characters of time, 16 of randomness (Crockford base32)
  const a = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  let ts = Math.floor(t);
  let head = '';
  for (let i = 0; i < 10; i++) { head = a[ts % 32] + head; ts = Math.floor(ts / 32); }
  const b = rand(16);
  let tail = '';
  for (let i = 0; i < 16; i++) tail += a[b[i] & 31];
  return head + tail;
}

function fillUpdate(dm, model, data, t) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return;
  const mi = modelInfo(dm, model);
  if (!mi) return;
  for (const f of mi.upd) if (data[f] === undefined) data[f] = new Date(t);
  nested(dm, mi, data, t);
}

function nested(dm, mi, data, t) {
  for (const [field, target] of mi.rel) {
    const op = data[field];
    if (!op || typeof op !== 'object') continue;
    const each = (v, fn) => (Array.isArray(v) ? v.forEach(fn) : fn(v));
    if (op.create) fillCreate(dm, target, op.create, t);
    if (op.createMany && op.createMany.data) fillCreate(dm, target, op.createMany.data, t);
    if (op.connectOrCreate) each(op.connectOrCreate, (c) => c && fillCreate(dm, target, c.create, t));
    if (op.upsert) each(op.upsert, (u) => { if (u) { fillCreate(dm, target, u.create, t); fillUpdate(dm, target, u.update, t); } });
    if (op.update) each(op.update, (u) => u && fillUpdate(dm, target, u.data !== undefined ? u.data : u, t));
    if (op.updateMany) each(op.updateMany, (u) => u && fillUpdate(dm, target, u.data, t));
  }
}

function fill(dm, model, action, args) {
  if (!model || !args || typeof args !== 'object') return;
  let t = Date.now(); // one instant for the whole write, like the engine's own now()
  if (MONO) {
    // Runner (test code): the engine clock does not move while the test code itself works, so rows it seeds one
    // after another got the same millisecond and lists ordered by createdAt came back in either order (MEASURED
    // locally, documenso search-documents visibility: two seeded documents swapped places between replays). Each
    // write of the runner gets its own millisecond, in the order the test code made them (deterministic).
    if (t <= MONO.last) t = MONO.last + 1;
    MONO.last = t;
  }
  if (CREATE.has(action)) {
    if (action.startsWith('upsert')) { fillCreate(dm, model, args.create, t); fillUpdate(dm, model, args.update, t); }
    else fillCreate(dm, model, args.data, t);
  } else if (UPDATE.has(action)) {
    fillUpdate(dm, model, args.data, t);
  }
}

function patchClientClass(C) {
  const proto = C && C.prototype;
  if (!proto || typeof proto._executeRequest !== 'function' || proto.__detjsPrisma) return;
  Object.defineProperty(proto, '__detjsPrisma', { value: true });
  const orig = proto._executeRequest;
  proto._executeRequest = function _executeRequest(params) {
    try {
      if (params && params.args) {
        params = { ...params, args: structuredCloneArgs(params.args) };
        fill(this._runtimeDataModel, params.model, params.action, params.args);
      }
    } catch { /* leave the request as it was */ }
    if (GATE) return GATE(params || {}, () => orig.call(this, params));
    return orig.call(this, params);
  };
}

// The caller's object must not change under it (it may be reused): a shallow copy of every level the shim writes to.
function structuredCloneArgs(a) {
  if (!a || typeof a !== 'object' || a instanceof Date || Buffer.isBuffer(a)) return a;
  if (Array.isArray(a)) return a.map(structuredCloneArgs);
  const proto = Object.getPrototypeOf(a);
  if (proto !== Object.prototype && proto !== null) return a; // Decimal, special Prisma values: as they are
  const out = {};
  for (const k of Object.keys(a)) out[k] = structuredCloneArgs(a[k]);
  return out;
}

function patchRuntime(exp) {
  if (!exp || typeof exp.getPrismaClient !== 'function' || exp.getPrismaClient.__detjs) return;
  const orig = exp.getPrismaClient;
  const wrapped = function getPrismaClient(...a) {
    const C = orig.apply(this, a);
    patchClientClass(C);
    return C;
  };
  wrapped.__detjs = true;
  try { exp.getPrismaClient = wrapped; } catch { /* frozen exports */ }
}

// Multi-worker lockstep (point 3): the test code's own database operations become engine messages (worker.js),
// released in the scheduler's order across workers; otherwise rows that tests seed in parallel get ids and
// timestamps in real-time order (MEASURED on documenso with 2 workers: envelope bodies differed between runs).
let GATE = null;
function setGate(fn) { GATE = fn; }

let installed = false;
let MONO = null;
function install(opt = {}) {
  if (opt.monotonic && process.env.DETJS_PRISMA_MONO !== '0') MONO = MONO || { last: -Infinity };
  if (installed || process.env.DETJS_PRISMA_CLOCK === '0') return;
  installed = true;
  const origLoad = Module._load;
  Module._load = function load(request, parent, isMain) {
    const exp = origLoad.apply(this, arguments);
    if (typeof request === 'string' && /@prisma[\\/]client[\\/]runtime[\\/](library|client|binary)(\.js)?$/.test(request)) patchRuntime(exp);
    // The runtime's exports are getters (bundled): the generated client's class is patched where it is exported.
    try { if (exp && typeof exp.PrismaClient === 'function') patchClientClass(exp.PrismaClient); } catch { /* lazy getter */ }
    return exp;
  };
}

module.exports = { install, fill, patchClientClass, setGate };
