'use strict';
// Configuration of a --det run. The wrapper (bin/detjs.js) turns its command
// line options into DETJS_* environment variables, which every worker
// (thread or child process) inherits; workers read them back here.

const CONTROLS = ['order', 'seeds', 'time', 'timers', 'fs', 'net', 'isolation'];
const DEFAULT_EPOCH = '2025-01-01T00:00:00Z';

// `--det-epoch=fixed`: the epoch of the earlier default (a run that must see the same wall clock every time)
function parseEpoch(text) {
  if (text === 'fixed') text = DEFAULT_EPOCH;
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

let WARNED_EPOCH = false;

/**
 * The run's epoch. A detjs session picks it once (src/session.js resolveEpoch) and exports DETJS_EPOCH to every
 * process of the run; a process started without a session (src/register.js, the Playwright reporter) has none and
 * keeps the fixed epoch, which it says once.
 */
function envEpoch(env, active) {
  if (env.DETJS_EPOCH) return env.DETJS_EPOCH;
  if (active && !WARNED_EPOCH) {
    WARNED_EPOCH = true;
    try { process.stderr.write(`detjs: no DETJS_EPOCH, using ${DEFAULT_EPOCH}\n`); } catch { /* not printed */ }
  }
  return DEFAULT_EPOCH;
}

/** Configuration from the environment (workers). */
function fromEnv(env = process.env) {
  const active = env.DETJS === '1' || env.DETJS === 'true';
  return {
    active,
    seed: BigInt(int(env.DETJS_SEED, 0)),
    // the seed of the order (shuffle) apart from the generators' (--det-order-seed; default: --det-seed)
    orderSeed: BigInt(int(env.DETJS_ORDER_SEED === undefined || env.DETJS_ORDER_SEED === '' ? env.DETJS_SEED : env.DETJS_ORDER_SEED, 0)),
    shuffle: env.DETJS_SHUFFLE === '1',
    controls: new Set(controls(env.DETJS_DISABLE)),
    epochNs: parseEpoch(envEpoch(env, active)),
    tickNs: int(env.DETJS_TICK, 1000),
    tickAdapt: int(env.DETJS_TICK_ADAPT, 1000),
    timerBudget: int(env.DETJS_TIMER_BUDGET, 100000),
    timers: env.DETJS_TIMERS === 'real' ? 'real' : 'virtual',
    dir: env.DETJS_DIR || null,
    root: env.DETJS_ROOT || process.cwd(),
    netMode: env.DETJS_NET_MODE || 'block',
    cassette: env.DETJS_CASSETTE || null,
    allowHosts: String(env.DETJS_ALLOW_HOSTS || '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean),
    urandom: env.DETJS_URANDOM === '1',
    cassetteMaxAge: Number(env.DETJS_CASSETTE_MAX_AGE) || 0,
    maxEvents: int(env.DETJS_MAX_EVENTS, 10000),
    sites: env.DETJS_SITES !== '0',
    runner: env.DETJS_RUNNER || null,
  };
}

module.exports = { CONTROLS, DEFAULT_EPOCH, fromEnv, controls, parseEpoch, int };
