'use strict';
// Configuration of a --det run. The wrapper (bin/detjs.js) turns its command
// line options into DETJS_* environment variables, which every worker
// (thread or child process) inherits; workers read them back here.

const CONTROLS = ['order', 'seeds', 'time', 'timers', 'fs', 'net', 'isolation'];
const DEFAULT_EPOCH = '2025-01-01T00:00:00Z';

function parseEpoch(text) {
  const ms = Date.parse(text);
  if (Number.isNaN(ms)) throw new Error(`detjs: --det-epoch: cannot parse ${JSON.stringify(text)}`);
  return BigInt(ms) * 1000000n;
}

function int(v, dflt) {
  if (v === undefined || v === '') return dflt;
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) throw new Error(`detjs: bad integer ${JSON.stringify(v)}`);
  return Math.floor(n);
}

function controls(disable) {
  const off = new Set(String(disable || '').split(',').map((s) => s.trim()).filter(Boolean));
  const unknown = [...off].filter((c) => !CONTROLS.includes(c));
  if (unknown.length) throw new Error(`detjs: --det-disable: unknown control(s) ${unknown.join(',')}; known: ${CONTROLS.join(',')}`);
  return CONTROLS.filter((c) => !off.has(c));
}

/** Configuration from the environment (workers). */
function fromEnv(env = process.env) {
  const active = env.DETJS === '1' || env.DETJS === 'true';
  return {
    active,
    seed: BigInt(int(env.DETJS_SEED, 0)),
    shuffle: env.DETJS_SHUFFLE === '1',
    controls: new Set(controls(env.DETJS_DISABLE)),
    epochNs: parseEpoch(env.DETJS_EPOCH || DEFAULT_EPOCH),
    tickNs: int(env.DETJS_TICK, 1000),
    tickAdapt: int(env.DETJS_TICK_ADAPT, 8),
    timerBudget: int(env.DETJS_TIMER_BUDGET, 100000),
    timers: env.DETJS_TIMERS === 'real' ? 'real' : 'virtual',
    dir: env.DETJS_DIR || null,
    root: env.DETJS_ROOT || process.cwd(),
    netMode: env.DETJS_NET_MODE || 'block',
    cassette: env.DETJS_CASSETTE || null,
    allowHosts: String(env.DETJS_ALLOW_HOSTS || '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean),
    urandom: env.DETJS_URANDOM === '1',
    maxEvents: int(env.DETJS_MAX_EVENTS, 10000),
    sites: env.DETJS_SITES !== '0',
    runner: env.DETJS_RUNNER || null,
  };
}

module.exports = { CONTROLS, DEFAULT_EPOCH, fromEnv, controls, parseEpoch, int };
