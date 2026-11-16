'use strict';
// Main-process side of a --det run, shared by `detjs vitest` and `detjs jest`:
// option parsing, environment for the workers, merge of the per-file trace
// parts into one trace (same format as the Python shell), comparison report.
const fs = require('node:fs');
const path = require('node:path');
const native = require('./native');
const config = require('./config');

const VERSION = require('../package.json').version;

const HELP = `detjs options (all others are passed to the test runner):
  --det                    enable deterministic execution (Level 0); also DETJS=1
  --det-seed=N             reproducible shuffle of files and tests, seed of every generator
                           (default: fixed order, seed 0)
  --det-trace=PATH         trace file (default: <root>/.detjs/trace.jsonl)
  --det-compare=TRACE      compare fingerprints with a previous trace
  --det-record             allow external network access and record it into the cassette
  --det-cassette=PATH      network cassette (default: <root>/.detjs/cassette.json); replayed when present
  --det-allow-host=HOST    external host that may be reached (repeatable)
  --det-epoch=ISO          wall clock at the start of every test (default ${config.DEFAULT_EPOCH})
  --det-tick=NS            nanoseconds per clock read (default 1000)
  --det-tick-adapt=N       double the tick after N consecutive reads with no other event (default 8, 0 = fixed)
  --det-timers=real        timers wait for real (default: virtual, fast while no I/O is pending)
  --det-timer-budget=N     fast timer firings per test before falling back to real waits (default 100000)
  --det-disable=LIST       controls to turn off: ${config.CONTROLS.join(',')}
  --det-urandom            also make crypto.randomBytes/randomFillSync/randomInt deterministic (NOT for crypto tests)
  --det-max-events=N       events stored verbatim per test (default 10000)
  --det-sites=off          do not resolve call sites (faster; runner frames are then not told apart)
`;

/** Split argv into detjs options and runner arguments. */
function parseArgs(argv, env = process.env) {
  const opts = {
    det: env.DETJS === '1' || env.DETJS === 'true',
    seed: null, trace: null, compare: null, record: false, cassette: null, allowHosts: [],
    epoch: config.DEFAULT_EPOCH, tick: 1000, tickAdapt: 8, timers: 'virtual', timerBudget: 100000,
    disable: '', urandom: false, maxEvents: 10000, sites: true,
  };
  if (env.DETJS_SEED !== undefined && env.DETJS_SEED !== '') opts.seed = config.int(env.DETJS_SEED, 0);
  const rest = [];
  const takes = new Set(['--det-seed', '--det-trace', '--det-compare', '--det-cassette', '--det-allow-host', '--det-epoch',
    '--det-tick', '--det-tick-adapt', '--det-timers', '--det-timer-budget', '--det-disable', '--det-max-events', '--det-sites']);
  for (let i = 0; i < argv.length; i++) {
    let a = argv[i];
    if (!a.startsWith('--det')) { rest.push(a); continue; }
    let value;
    const eq = a.indexOf('=');
    if (eq >= 0) { value = a.slice(eq + 1); a = a.slice(0, eq); } else if (takes.has(a)) { value = argv[++i]; }
    switch (a) {
      case '--det': opts.det = true; break;
      case '--det-seed': opts.seed = config.int(value, 0); break;
      case '--det-trace': opts.trace = value; break;
      case '--det-compare': opts.compare = value; break;
      case '--det-record': opts.record = true; break;
      case '--det-cassette': opts.cassette = value; break;
      case '--det-allow-host': opts.allowHosts.push(value); break;
      case '--det-epoch': config.parseEpoch(value); opts.epoch = value; break;
      case '--det-tick': opts.tick = config.int(value, 1000); break;
      case '--det-tick-adapt': opts.tickAdapt = config.int(value, 8); break;
      case '--det-timers': opts.timers = value === 'real' ? 'real' : 'virtual'; break;
      case '--det-timer-budget': opts.timerBudget = config.int(value, 100000); break;
      case '--det-disable': config.controls(value); opts.disable = value; break;
      case '--det-urandom': opts.urandom = true; break;
      case '--det-max-events': opts.maxEvents = config.int(value, 10000); break;
      case '--det-sites': opts.sites = value !== 'off' && value !== '0'; break;
      case '--det-help': process.stdout.write(HELP); process.exit(0); break;
      default: throw new Error(`detjs: unknown option ${a}\n${HELP}`);
    }
  }
  return { opts, rest };
}

/** Prepare the run directory and the DETJS_* environment inherited by the workers. */
function prepare(opts, root, runner) {
  const dir = path.join(root, '.detjs', `run-${process.pid}`);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'parts'), { recursive: true });
  const cassette = path.resolve(root, opts.cassette || path.join('.detjs', 'cassette.json'));
  const netMode = opts.record ? 'record' : fs.existsSync(cassette) ? 'replay' : 'block';
  const env = {
    DETJS: '1',
    DETJS_SEED: String(opts.seed ?? 0),
    DETJS_SHUFFLE: opts.seed !== null ? '1' : '0',
    DETJS_DIR: dir,
    DETJS_ROOT: root,
    DETJS_EPOCH: opts.epoch,
    DETJS_TICK: String(opts.tick),
    DETJS_TICK_ADAPT: String(opts.tickAdapt),
    DETJS_TIMERS: opts.timers,
    DETJS_TIMER_BUDGET: String(opts.timerBudget),
    DETJS_DISABLE: opts.disable,
    DETJS_NET_MODE: netMode,
    DETJS_CASSETTE: cassette,
    DETJS_ALLOW_HOSTS: opts.allowHosts.join(','),
    DETJS_URANDOM: opts.urandom ? '1' : '0',
    DETJS_MAX_EVENTS: String(opts.maxEvents),
    DETJS_SITES: opts.sites ? '1' : '0',
    DETJS_RUNNER: runner,
  };
  Object.assign(process.env, env);
  const cfg = config.fromEnv(process.env);
  return { dir, cassette, netMode, cfg, tracePath: path.resolve(root, opts.trace || path.join('.detjs', 'trace.jsonl')) };
}

function header(run, opts, extra) {
  const c = run.cfg;
  const order = opts.seed !== null ? `shuffled with seed ${opts.seed}` : 'fixed (sorted files, declaration order)';
  return [
    `detjs ${VERSION}: Level 0 active; runner=${extra.runner} ${extra.runnerVersion}; controls=${[...c.controls].sort().join(',')}; order ${order}`,
    `detjs: serial execution (${extra.isolation}); network=${run.netMode}; timers=${c.timers}; node ${process.version}`,
  ];
}

/** Ids of the tests recorded in a part, in execution order. */
function partIds(file) {
  const ids = [];
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch { return ids; }
  for (const line of text.split('\n')) {
    if (!line.startsWith('{"type":"test"')) continue;
    try { ids.push(JSON.parse(line).nodeid); } catch { /* truncated last line */ }
  }
  return ids;
}

/** Merge the parts of the run into the final trace. `files`: [{fileId, part}] in execution order. */
function finish(run, opts, files, meta) {
  const parts = files.map((f) => path.join(run.dir, 'parts', f.part)).filter((p) => fs.existsSync(p));
  // Parts not claimed by the sequencer order (should not happen) go last, sorted.
  const known = new Set(parts);
  const extra = fs.readdirSync(path.join(run.dir, 'parts')).map((p) => path.join(run.dir, 'parts', p)).filter((p) => !known.has(p)).sort();
  const all = [...parts, ...extra];
  const order = all.flatMap(partIds);
  const full = {
    ...meta,
    runtime: 'node',
    runtime_version: process.versions.node,
    detjs: VERSION,
    seed: Number(run.cfg.seed),
    shuffle: run.cfg.shuffle,
    controls: [...run.cfg.controls].sort(),
    epoch_ns: run.cfg.epochNs.toString(),
    tick_ns: run.cfg.tickNs,
    tick_adapt: run.cfg.tickAdapt,
    timers: run.cfg.timers,
    network: run.netMode,
    urandom_controlled: run.cfg.urandom,
    node: process.version,
    platform: process.platform,
    files: files.map((f) => f.fileId),
    unordered_parts: extra.length,
  };
  const res = native.mergeTraces(all, run.tracePath, JSON.stringify(full), order);
  fs.rmSync(run.dir, { recursive: true, force: true });
  const lines = [`detjs: trace ${path.relative(process.cwd(), run.tracePath) || run.tracePath}: ${res.nTests} tests, order digest ${res.orderDigest}`];
  if (res.skipped.length) lines.push(`detjs: unreadable trace parts: ${res.skipped.join('; ')}`);
  if (opts.compare) {
    try {
      const rep = JSON.parse(native.verify([opts.compare, run.tracePath]));
      const s = rep.summary;
      lines.push(`detjs: compare with ${opts.compare}: covered=${s.stable} not-covered=${s.diverged} missing=${s.missing} outcome-unstable=${s.outcome_unstable}${s.order_identical ? '' : ' (ORDER DIFFERS)'}`);
      for (const t of rep.tests) {
        if (t.status === 'diverged' && t.divergence) {
          lines.push(`NOT COVERED by Level 0: ${t.nodeid} [${t.divergence.reason}]`);
          lines.push(`    ${t.divergence.description}`);
        }
      }
    } catch (e) {
      lines.push(`detjs: compare failed: ${e.message}`);
    }
  }
  return { lines, result: res };
}

module.exports = { parseArgs, prepare, header, finish, partIds, HELP, VERSION };
