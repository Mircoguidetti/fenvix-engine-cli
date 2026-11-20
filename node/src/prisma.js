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
    const rel = new Map();
    for (const f of m.fields || []) {
      if (f.kind === 'scalar' && f.default && f.default.name === 'now') now.push(f.name);
      if (f.isUpdatedAt) upd.push(f.name);
      if (f.kind === 'object') rel.set(f.name, f.type);
    }
    Object.defineProperty(m, '__detjs', { value: { now, upd, rel } });
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
  nested(dm, mi, data, t);
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
  const t = Date.now(); // one instant for the whole write, like the engine's own now()
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

let installed = false;
function install() {
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

module.exports = { install, fill, patchClientClass };
