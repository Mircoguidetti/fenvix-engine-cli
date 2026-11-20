'use strict';
// Multi-worker lockstep (round 4, point 3): one scheduler for N Playwright workers.
//
// The hub runs in the detjs CLI process (it outlives the workers). It owns the Rust scheduler
// (crates/detpy-core/src/lockstep.rs) and the engine clock T; every worker's coordinator (lockstep.js) keeps its pages,
// runner and responses local and asks the hub for each decision. A decision is taken only when every active worker
// (one with a test running) is settled at T and asking:
//   * a pending message anywhere: the seeded choice among all of them (release, possibly held for its latency: held
//     messages are delivered by the hub at their due time, because they reach shared app servers);
//   * else, when every active worker's runner waits on time: advance T for all;
//   * else the asking workers whose runner is idle get "idle" (they wait for their own activity) and the others wait.
// Protocol: newline-delimited JSON over a Unix socket (DETJS_LS_HUB). Message ids are namespaced per worker.

const net = require('node:net');
const fs = require('node:fs');
const native = require('../native');

const NS = 1e6;
const W = 1e9; // id namespace: worker * W + local id

function start(opts) {
  const sock = opts.path;
  try { fs.rmSync(sock, { force: true }); } catch { /* none */ }
  const sched = new native.Lockstep(BigInt(opts.seed || 0), !!opts.seeded, 0, (opts.quantumMs || 20) * NS, (opts.latencyMs || 1) * NS);
  try { require('./seedspace').configure(sched, process.env); } catch (e) { process.stderr.write(`detjs hub: seed space: ${e.message}\n`); }
  const workers = new Map(); // w -> { conn, active, ask: null | { waiting, reply }, idle }
  const holds = []; // { due, seq, id, info }
  let holdSeq = 0;
  let deciding = false;
  const expected = Math.max(1, Number(opts.workers || 1));
  let started = false;
  let startTimer = null;
  const maybeStart = () => {
    if (started) return;
    if (workers.size >= expected) { started = true; decide(); return; }
    // Fewer workers than asked for (fewer test groups than workers): start once nobody connected for a while.
    if (startTimer) clearTimeout(startTimer);
    startTimer = setTimeout(() => { started = true; decide(); }, Number(process.env.DETJS_LS_HUB_START_MS || 15000));
    if (startTimer.unref) startTimer.unref();
  };

  const send = (w, obj) => { const s = workers.get(w); if (s && s.conn && !s.conn.destroyed) s.conn.write(`${JSON.stringify(obj)}\n`); };

  function decide() {
    if (deciding) return;
    deciding = true;
    try {
      for (;;) {
        // Every connected worker takes part: one between tests (setting up its next test in real time) holds the
        // decision until it asks from inside its next test or disconnects, so a test always starts at a decision
        // point, and the dispatcher can only hand work to that worker. At start, all N workers connect first.
        if (!started) return;
        const conn = [...workers.entries()].filter(([, s]) => !s.parked);
        const active = conn.filter(([, s]) => s.active);
        if (!active.length) return;
        if (conn.some(([, s]) => !s.ask)) return; // someone is settling, or between tests
        const T = sched.now();
        // Held messages due now, in (due, release) order: delivered by their owner.
        if (holds.length && holds[0].due <= T) {
          const h = holds.shift();
          const w = Math.floor(h.id / W);
          answerAll({ kind: 'deliver', id: h.id - w * W, info: h.info, t: T }, w);
          continue;
        }
        if (sched.pending() > 0) {
          const a = sched.next();
          const w = Math.floor(a.id / W);
          const info = { fault: a.fault, latencyNs: a.latencyNs, decision: a.decision };
          if (a.latencyNs > 0) {
            holds.push({ due: T + a.latencyNs, seq: holdSeq++, id: a.id, info });
            holds.sort((x, y) => x.due - y.due || x.seq - y.seq);
            sched.setDeadline('holds', holds[0].due);
            answerAll({ kind: 'released', id: a.id - w * W, idx: a.idx, n: a.n, fault: a.fault, latencyNs: a.latencyNs, decision: a.decision, t: T }, w);
          } else {
            answerAll({ kind: 'release', id: a.id - w * W, idx: a.idx, n: a.n, fault: a.fault, latencyNs: a.latencyNs, decision: a.decision, t: T }, w);
          }
          if (!holds.length) sched.setDeadline('holds', null);
          continue;
        }
        const idle = active.filter(([, s]) => !s.ask.waiting);
        if (idle.length) {
          for (const [w, s] of idle) { const r = s.ask.reply; s.ask = null; r({ kind: 'idle', t: T }); void w; }
          return;
        }
        sched.setDeadline('holds', holds.length ? holds[0].due : null);
        const a = sched.next();
        if (a.kind === 'advance') {
          for (const [, s] of active) { const r = s.ask.reply; s.ask = null; r({ kind: 'advance', toNs: a.toNs, t: a.toNs }); }
          return;
        }
        for (const [, s] of active) { const r = s.ask.reply; s.ask = null; r({ kind: 'idle', t: T }); }
        return;
      }
    } finally { deciding = false; }
  }

  // The owner gets the action; every other asking worker re-settles ("again") and asks again.
  function answerAll(action, owner) {
    let ownerAsked = false;
    for (const [w, s] of workers) {
      if (!s.ask) continue;
      const r = s.ask.reply; s.ask = null;
      if (w === owner) ownerAsked = true;
      r(w === owner ? action : { kind: 'again', t: action.t });
    }
    // The owner may not be asking (its test ended while its message waited): it gets the action anyway.
    if (!ownerAsked) send(owner, { op: 'action', action });
  }

  const server = net.createServer((conn) => {
    let w = null;
    let buf = '';
    conn.setNoDelay(true);
    conn.on('data', (d) => {
      buf += d.toString('utf8');
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1);
        let m;
        try { m = JSON.parse(line); } catch { continue; }
        if (process.env.DETJS_LS_HUB_DEBUG && !/"op":"(deadline|waiting|enqueue)"/.test(line)) fs.appendFileSync(process.env.DETJS_LS_HUB_DEBUG, `hub <- w${w} ${line.slice(0, 120)}\n`);
        if (m.op === 'hello') {
          w = m.w;
          workers.set(w, { conn, active: false, ask: null });
          send(w, { op: 'hello', t: sched.now() });
          maybeStart();
          continue;
        }
        const s = workers.get(w);
        if (!s) continue;
        switch (m.op) {
          case 'active':
            s.active = !!m.on;
            if (!m.on) { for (const n of s.names || []) sched.removeParticipant(n); s.names = new Set(); s.ask = null; }
            decide();
            break;
          // Ordered by test first: two workers' identical requests do not tie on arrival order.
          case 'enqueue': sched.enqueue(w * W + m.id, `${m.test}\u0001${m.key}`, m.test, m.conn === null || m.conn === undefined ? null : m.conn, `w${w}`, m.kind); break;
          case 'cancel': sched.cancel(w * W + m.id); break;
          case 'parked': s.parked = !!m.on; if (s.parkTimer) { clearTimeout(s.parkTimer); s.parkTimer = null; } decide(); break;
          case 'groupDone':
            // A test group ended: the worker is parked unless the dispatcher gives it another one shortly.
            if (s.parkTimer) clearTimeout(s.parkTimer);
            s.parkTimer = setTimeout(() => { s.parkTimer = null; s.parked = true; decide(); }, Number(process.env.DETJS_LS_PARK_WORKER_MS || 2000));
            break;
          case 'deadline': (s.names = s.names || new Set()).add(`${m.name}@${w}`); sched.setDeadline(`${m.name}@${w}`, m.ns === null ? null : m.ns); break;
          case 'waiting': (s.names = s.names || new Set()).add(`${m.name}@${w}`); sched.setWaiting(`${m.name}@${w}`, !!m.on); break;
          case 'next':
            s.ask = { waiting: !!m.waiting, reply: (action) => send(w, { op: 'action', seq: m.seq, action }) };
            decide();
            break;
          default: break;
        }
      }
    });
    conn.on('close', () => { if (w !== null) { const s = workers.get(w); if (s) { s.active = false; s.ask = null; for (const n of s.names || []) sched.removeParticipant(n); } decide(); } });
    conn.on('error', () => {});
  });
  server.listen(sock);
  server.unref();
  return { close: () => { try { server.close(); } catch { /* closed */ } try { fs.rmSync(sock, { force: true }); } catch { /* gone */ } } };
}

/** Worker side: the scheduler API of native.Lockstep, answered by the hub. now() is a local mirror of T. */
class RemoteScheduler {
  constructor(sockPath, w) {
    this.w = w;
    this.t = 0;
    this.pendingIds = new Set();
    this.seq = 0;
    this.waitingFor = new Map();
    this.sock = net.connect(sockPath);
    this.sock.setNoDelay(true);
    this.sock.unref();
    let buf = '';
    this.ready = new Promise((resolve) => {
      this.sock.on('data', (d) => {
        buf += d.toString('utf8');
        let i;
        while ((i = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, i); buf = buf.slice(i + 1);
          let m;
          try { m = JSON.parse(line); } catch { continue; }
          if (m.op === 'hello') { this.t = m.t; resolve(); continue; }
          if (m.op === 'action') {
            if (typeof m.action.t === 'number' && m.action.t > this.t) this.t = m.action.t;
            const r = this.waitingFor.get(m.seq);
            if (r) { this.waitingFor.delete(m.seq); r(m.action); } else if (this.onAction) this.onAction(m.action);
          }
        }
      });
    });
    this.sock.on('error', () => {});
    this.write({ op: 'hello', w });
  }

  write(o) { try { this.sock.write(`${JSON.stringify(o)}\n`); } catch { /* hub gone */ } }
  now() { return this.t; }
  setSpace() { /* the hub's scheduler carries the seed space */ }
  setFocus() { /* idem */ }
  advanceTo() { /* only the hub moves T */ }
  setDeadline(name, ns) { this.write({ op: 'deadline', name, ns: ns === null || ns === undefined ? null : ns }); }
  setWaiting(name, on) { this.write({ op: 'waiting', name, on: !!on }); }
  enqueue(id, key, test, conn, owner, kind) { this.pendingIds.add(id); this.write({ op: 'enqueue', id, key, test, conn, kind }); }
  cancel(id) { this.pendingIds.delete(id); this.write({ op: 'cancel', id }); return true; }
  released(id) { this.pendingIds.delete(id); }
  pending() { return this.pendingIds.size; }
  nextDeadline() { return null; }
  log() { return []; }
  active(on) { this.write({ op: 'active', on: !!on }); }
  nextAsync(waiting) {
    const seq = ++this.seq;
    return new Promise((resolve) => { this.waitingFor.set(seq, resolve); this.write({ op: 'next', seq, waiting: !!waiting }); });
  }
}

module.exports = { start, RemoteScheduler, W };
