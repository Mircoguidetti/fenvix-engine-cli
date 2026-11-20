'use strict';
// `detjs jest [--det ...] [jest args]`
//
// Without --det (and without DETJS=1) the project's jest CLI runs unchanged.
// With --det, jest runs in this process with
//   --runInBand            files one after the other in this process (each in
//                          its own vm context, as usual): no worker processes;
//   --maxConcurrency=1     test.concurrent runs one test at a time, in order;
//   --testSequencer        files sorted by path (or shuffled with the seed);
//   --testRunner           the detjs runner, which delegates to the project's
//                          runner (jest-circus) after installing the controls.
// `--showConfig` is read first to find each project's own test runner.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const parallel = require('../parallel');
const { writeShim } = require('../shim');

function findJest(root) {
  const req = require('node:module').createRequire(path.join(root, 'noop.js'));
  let pkgFile;
  try {
    pkgFile = req.resolve('jest/package.json');
  } catch {
    throw new Error(`detjs: jest is not installed in ${root}`);
  }
  const dir = path.dirname(fs.realpathSync(pkgFile));
  const pkg = JSON.parse(fs.readFileSync(pkgFile, 'utf8'));
  const bin = path.join(dir, typeof pkg.bin === 'string' ? pkg.bin : pkg.bin.jest);
  return { dir, pkg, bin };
}

function showConfig(bin, args) {
  const r = spawnSync(process.execPath, [bin, ...args, '--showConfig'], { encoding: 'utf8', maxBuffer: 256 << 20, env: { ...process.env, DETJS: '0' } });
  const out = r.stdout || '';
  const start = out.indexOf('{');
  if (start < 0) return null;
  try { return JSON.parse(out.slice(start)); } catch { return null; }
}

async function main(argv) {
  const env0 = { ...process.env }; // the environment at session start (cache inputs are digested against it)
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  const jest = findJest(root);
  if (!opts.det) {
    const r = spawnSync(process.execPath, [jest.bin, ...rest], { stdio: 'inherit' });
    return r.status ?? 1;
  }
  // watch mode (audit G-2183): a --det run is one deterministic run, merged into one trace at its end
  if (rest.some((a) => /^--watch(?:All)?(?:=true)?$/.test(a))) {
    process.stderr.write('detjs: watch mode is not supported under --det: a --det run is one deterministic run (one trace, one cache '
      + 'decision). Run `detjs jest --det` for each change, or `detjs jest --watch` without --det.\n');
    return 2;
  }
  const shown = showConfig(jest.bin, rest);
  const runners = {};
  const projects = [];
  const customRunners = new Set();
  for (const c of (shown && shown.configs) || []) {
    runners[`${c.rootDir}|${c.displayName ? c.displayName.name : ''}`] = c.testRunner;
    projects.push({ rootDir: c.rootDir, testRunner: c.testRunner, testEnvironment: c.testEnvironment, runner: c.runner });
    if (isCustomRunner(c.runner)) customRunners.add(c.runner);
  }
  // What jest-cli's bin does before run(): many configs (Babel presets) depend on it.
  if (process.env.NODE_ENV == null) process.env.NODE_ENV = 'test';
  const run = session.prepare(opts, root, 'jest');
  // parallel lanes: --det-workers, or Jest's own --maxWorkers / -w on the command line (src/parallel.js)
  const jw = jestWorkersArg(rest);
  if (opts.plan) {
    // --det-plan: the replayed plan's lanes (src/parallel.js)
    opts.plan = path.resolve(opts.plan);
    process.env.DETJS_PLAN = opts.plan;
    if (opts.workers == null) opts.workers = String(parallel.readReplay(opts.plan).lanes.length);
  }
  const want = parallel.resolveWorkers(opts, { workers: jw.workers, source: jw.source, serial: jw.serial, serialSource: '--runInBand' });
  const par = { workers: want.workers, source: want.source, refused: null, plan: null, result: null };
  if (par.workers > 1) {
    const reasons = [];
    if (run.netMode === 'record') reasons.push('--det-record (one cassette per process)');
    if (customRunners.size) reasons.push(`custom Jest runner ${[...customRunners].join(',')} (it places the tests itself)`);
    if (rest.includes('--detectOpenHandles') || (shown && shown.globalConfig && shown.globalConfig.detectOpenHandles)) reasons.push('--detectOpenHandles runs in band');
    if (reasons.length) {
      par.refused = reasons.join('; ');
      par.workers = 1;
      process.stderr.write(`detjs: parallel refused, running in band: ${par.refused}\n`);
    }
  }
  process.env.DETJS_WORKERS = String(par.workers);
  if (par.workers > 1) parallel.skipDirs(((shown && shown.configs) || []).map((c) => c.cacheDirectory));
  process.env.DETJS_JEST_RUNNERS = JSON.stringify(runners);
  let pc = null;
  if (opts.cache) {
    const { ProofSession } = require('../cache/proof');
    pc = new ProofSession(opts, root, 'jest', run, env0);
    globalThis[Symbol.for('detjs.cache.session')] = pc;
    pc.installMain({ mainAnyReads: false });
    pc.setConfig(jestConfigParts(shown, jest.pkg.version, rest, pc, customRunners));
    if (par.workers > 1) {
      // the worker processes start the capture and wrap the environments themselves (src/jest/worker.js)
      fs.writeFileSync(path.join(run.dir, 'jest-shown.json'), JSON.stringify(shown));
      // preload modules of NODE_OPTIONS run in each worker before the capture: what they read is not observed
      if (/(?:^|\s)(?:-r|--require|--import|--loader|--experimental-loader)(?:=|\s|$)/.test(process.env.NODE_OPTIONS || '')) {
        for (const c of (shown && shown.configs) || []) pc.noteProject(c.displayName ? c.displayName.name : '', 'NODE_OPTIONS preloads run in Jest workers before the capture');
      }
    }
    const { CAPTURE } = require('../cache/capture');
    for (const c of (shown && shown.configs) || []) CAPTURE.addSkipDir(c.cacheDirectory);
  }
  // Each project's test environment is wrapped: the controls are installed before setupFiles run (G-1312, G-1436,
  // G-1466), and the file's process.argv is what an in-band `jest <args>` shows (G-2164)
  require('./environment').install(shown, { cache: Boolean(pc), argv: [process.execPath, jest.bin, ...rest] });
  // The test runner is loaded through a shim in a node_modules directory (src/shim.js) that
  // requires the detjs runner only when Jest calls it: Jest loads testRunner
  // with its transform hook active, so detjs would otherwise be compiled with
  // the project's Babel config (found on matrix-js-sdk: plugin-transform-runtime
  // made every suite fail with "Cannot find module @babel/runtime/...").
  const runnerShim = writeShim(root, `jest-runner-${process.pid}.js`, `'use strict';\nconst real = ${JSON.stringify(path.join(__dirname, 'runner.js'))};\n`
    + 'module.exports = function detjsRunner(...args) { return require(real)(...args); };\n');
  if (par.workers > 1) bindWorkers(shown, jest.bin, run.dir);
  // No --forceExit (audit G-2180): in band, a handle left open by the suite would keep this process alive where Jest's
  // worker mode kills its workers; detjs exits only in that case, after naming the open handles (exitWhenStuck).
  const userForceExit = rest.includes('--forceExit');
  const extra = [...(par.workers > 1 ? [`--maxWorkers=${par.workers}`] : ['--runInBand']), '--maxConcurrency=1',
    `--testSequencer=${path.join(__dirname, 'sequencer.js')}`,
    `--testRunner=${runnerShim}`];
  // A custom Jest `runner` (jest-light-runner, create-jest-runner tools) runs the files itself: detjs wraps its class
  // (src/jest/custom-runner.js) and brings Level 0 to each file and, where the runner registers tests with jest-circus,
  // to each test; what it cannot bracket is reported as not covered (G-0453, G-1588). DETJS_JEST_RUNNER=replace uses
  // Jest's default runner instead (measured: the native-ESM suites of babel and prettier then fail).
  let runnerNote = '';
  if (customRunners.size) {
    const names = [...customRunners].join(',');
    let replaced = false;
    if (process.env.DETJS_JEST_RUNNER === 'replace') {
      try {
        const coreReq = require('node:module').createRequire(require('node:module').createRequire(jest.bin).resolve('@jest/core'));
        extra.push(`--runner=${coreReq.resolve('jest-runner')}`);
        runnerNote = `; runner ${names} replaced by jest-runner`;
        replaced = true;
      } catch { /* keep it */ }
    }
    if (!replaced) {
      require('./custom-runner').install(customRunners);
      runnerNote = `; custom runner ${names}: wrapped by detjs (Level 0 per file, and per test where it registers tests with jest-circus; files it runs out of reach are reported as not covered)`;
    }
  }
  if (pc && !rest.includes('--passWithNoTests')) extra.push('--passWithNoTests'); // every file reused: a pass (no tests found: set below)
  const help = spawnSync(process.execPath, [jest.bin, '--help'], { encoding: 'utf8', env: { ...process.env, DETJS: '0' } });
  if (/--randomize/.test(help.stdout || '')) extra.push('--no-randomize');
  const fe = userForceExit ? ' --forceExit' : '';
  const isolation = par.workers > 1
    ? `jest --maxWorkers=${par.workers}${fe}: ${par.workers} worker processes, each runs the files of one lane in plan order, each file in its own vm context; maxConcurrency=1${runnerNote}`
    : `jest --runInBand${fe}: one test file at a time in the main process, each in its own vm context; maxConcurrency=1${runnerNote}${par.refused ? `; parallel refused: ${par.refused}` : ''}`;
  const cliReq = require('node:module').createRequire(jest.bin);
  // the cache's reuse decision after globalSetup (G-1290): when Jest schedules the files (src/jest/sequencer.js)
  if (pc) await deferDecision(cliReq, pc);
  let finished = false;
  let order = null;
  const readOrder = () => {
    if (order === null) { try { order = JSON.parse(fs.readFileSync(path.join(run.dir, 'order.json'), 'utf8')); } catch { order = []; } }
    return order;
  };
  // after the run, before the cache records: placement against the plan, hazards, carried state (src/parallel.js)
  const collectParallel = () => {
    if (par.result) return par.result;
    let plan = null;
    try { plan = JSON.parse(fs.readFileSync(path.join(run.dir, 'plan-full.json'), 'utf8')); } catch { /* serial */ }
    par.plan = plan;
    par.result = parallel.collect(root, run.dir, readOrder().map((f) => f.key), plan, {
      shared: true, planned: { workers: par.workers, source: par.source, refused: par.refused },
    });
    if (pc) pc.parallelFlags = par.result.flags;
    for (const l of par.result.lines) fs.writeSync(2, `${l}\n`);
    return par.result;
  };
  const finalize = () => {
    if (finished) return;
    finished = true;
    collectParallel();
    if (pc) {
      pc.exiting = !pc.pushed;
      for (const l of pc.finishSync()) fs.writeSync(1, `${l}\n`);
      if (pc.noTestsFound && !rest.includes('--passWithNoTests')) process.exitCode = 1;
    }
    const files = readOrder();
    if (customRunners.size) require('./custom-runner').report(files);
    const { lines } = session.finish(run, opts, files, {
      runner: 'jest', runner_version: jest.pkg.version, isolation, serial: !par.plan, projects, cli_args: rest, parallel: par.result.meta,
    });
    for (const l of lines) fs.writeSync(1, `${l}\n`); // sync: the runner may be exiting
  };
  process.on('exit', finalize);
  for (const l of session.header(run, opts, {
    runner: 'jest', runnerVersion: jest.pkg.version,
    isolation: par.workers > 1 ? `--maxWorkers=${par.workers}, one lane per worker` : `runInBand; Jest alone would use ${Math.max(parallel.workerCount('auto') - 1, 1)} workers: --det-workers=N or -w N for parallel lanes`,
    parallel: par.workers > 1 ? `parallel execution in ${par.workers} lanes with a fixed plan (${par.source})` : null,
  })) {
    process.stdout.write(`${l}\n`);
  }
  const jestCli = cliReq('jest-cli');
  // Not awaited: an awaiting caller would appear as an extra `at async main`
  // frame in the async stack traces the tests see (found on babel: stack-trace
  // inline snapshots); Jest's own bin does not await run() either.
  return new Promise((resolve, reject) => {
    jestCli.run([...stripWorkerArgs(rest, par.workers > 1), ...extra], undefined).then(async () => {
      collectParallel();
      if (pc) await pc.finish();
      finalize();
      if (!userForceExit && !rest.includes('--detectOpenHandles')) exitWhenStuck();
      resolve(process.exitCode ?? 0);
    }, reject);
  });
}

/** Jest's own worker options on the command line: {workers, source, serial}. */
function jestWorkersArg(args) {
  let workers = null; let source = null; let serial = false;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    let m;
    if (a === '--runInBand' || a === '-i' || a === '--runInBand=true') serial = true;
    else if ((m = /^(?:--maxWorkers|--max-workers|-w)=(.+)$/.exec(a))) { workers = parallel.workerCount(m[1]); source = a.split('=')[0]; }
    else if ((a === '--maxWorkers' || a === '--max-workers' || a === '-w') && i + 1 < args.length) { workers = parallel.workerCount(args[i + 1]); source = a; }
  }
  return { workers, source, serial };
}

/** The runner arguments without Jest's own worker options (detjs sets them from the plan). */
function stripWorkerArgs(args, parallelRun) {
  if (!parallelRun) return args;
  const out = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (/^(?:--maxWorkers|--max-workers|-w)=/.test(a)) continue;
    if (a === '--maxWorkers' || a === '--max-workers' || a === '-w') { i++; continue; }
    out.push(a);
  }
  return out;
}

/**
 * Bind Jest's worker farm to the plan: the jest-worker `Worker` that jest-runner constructs becomes one whose task for
 * a test file goes to the worker of the file's lane (jest-worker's sticky `computeWorkerKey`, with lane k bound to
 * worker k before the first task: `JEST_WORKER_ID` = lane + 1), and whose processes start with detjs' worker preload
 * (the cache capture and the environment wrapping, src/jest/worker.js).
 */
function bindWorkers(shown, jestBin, dir) {
  const { createRequire } = require('node:module');
  const preload = path.join(__dirname, 'worker.js');
  const runners = new Set(((shown && shown.configs) || []).map((c) => c.runner).filter(Boolean));
  try { runners.add(createRequire(createRequire(jestBin).resolve('@jest/core')).resolve('jest-runner')); } catch { /* none */ }
  for (const r of runners) {
    let jwMod;
    try { jwMod = createRequire(r)('jest-worker'); } catch { continue; }
    const Base = jwMod.Worker;
    if (typeof Base !== 'function' || Base.__detjsPlanned) continue;
    const root = process.env.DETJS_ROOT || process.cwd();
    class PlannedWorker extends Base {
      constructor(workerPath, options = {}) {
        let plan = null;
        try { plan = JSON.parse(fs.readFileSync(path.join(dir, 'plan.json'), 'utf8')); } catch { /* not planned */ }
        const fo = options.forkOptions || {};
        const execArgv = [...(fo.execArgv || process.execArgv.filter((v) => !/^--(debug|inspect)/.test(v))), '--require', preload];
        const laneOf = (req) => {
          if (!plan || !req || typeof req.path !== 'string') return null;
          const fileId = path.relative(root, req.path).split(path.sep).join('/');
          const pc = req.config;
          const name = pc && pc.displayName ? pc.displayName.name : '';
          const lane = plan.laneOf[name ? `${name}|${fileId}` : fileId];
          return lane === undefined ? null : `detjs-lane:${lane}`;
        };
        super(workerPath, {
          ...options,
          numWorkers: plan ? plan.workers : options.numWorkers,
          computeWorkerKey: (method, req) => laneOf(req),
          forkOptions: { ...fo, execArgv },
        });
        try {
          const ws = this._workerPool.getWorkers();
          if (plan) for (let k = 0; k < plan.workers && k < ws.length; k++) this._farm._cacheKeys[`detjs-lane:${k}`] = ws[k];
        } catch { /* the markers report the placement Jest chose */ }
      }
    }
    Object.defineProperty(PlannedWorker, '__detjsPlanned', { value: true });
    try { jwMod.Worker = PlannedWorker; } catch { /* read-only export: placement reported, not bound */ }
  }
}

/** A Jest `runner` other than Jest's own jest-runner. */
function isCustomRunner(r) {
  return Boolean(r) && !/(^|[\\/])jest-runner([\\/]|$)/.test(r);
}

/**
 * In band, handles the tests left open (servers, intervals, sockets) live in this process: where Jest's worker mode
 * would end its workers, this process would never exit. If it is still alive a moment after the run (Jest has printed
 * its results and detjs its trace), detjs names what keeps it alive and exits with the run's status (audit G-2180:
 * instead of always adding --forceExit, whose message appeared on every run). A suite that closes everything exits by
 * itself, as with plain Jest.
 */
function exitWhenStuck(ms = Number(process.env.DETJS_JEST_EXIT_WAIT_MS || 500)) {
  const t = setTimeout(() => {
    const own = new Set(['TTYWrap', 'PipeWrap', 'FSReqCallback']);
    const res = (typeof process.getActiveResourcesInfo === 'function' ? process.getActiveResourcesInfo() : []).filter((r) => !own.has(r));
    const counts = {};
    for (const r of res) counts[r] = (counts[r] || 0) + 1;
    const list = Object.entries(counts).map(([k, n]) => (n > 1 ? `${k} x${n}` : k)).join(', ') || 'unknown handles';
    process.stderr.write(`detjs: the tests left open handles that keep this in-band Jest process alive (${list}); exiting `
      + 'with the run\'s status, as Jest\'s worker mode would end its workers. Run with --detectOpenHandles to find them.\n');
    process.exit();
  }, ms);
  t.unref();
}

/**
 * The cache decides which files to reuse when Jest schedules them, after globalSetup (audit G-1290): Jest calls the
 * sequencer before globalSetup, so a globalSetup that runs processes or reads files would change the start-up digest
 * after the decision. Jest's TestScheduler (the @jest/core jest-cli uses) gets a scheduleTests that awaits the
 * decision first and schedules the files that are not reused; the full list stays Jest's own (globalTeardown, results
 * cache). If the scheduler cannot be patched, the decision stays in the sequencer (before globalSetup).
 */
async function deferDecision(cliReq, pc) {
  pc.deferredDecision = false;
  let core;
  try { core = require('node:module').createRequire(cliReq.resolve('jest-cli'))('@jest/core'); } catch { return; }
  if (!core || typeof core.createTestScheduler !== 'function') return;
  try {
    // Jest 29 creates its scheduler asynchronously, Jest 30 synchronously; no reporter is set up for this instance
    const scheduler = await core.createTestScheduler({ reporters: [] }, {});
    const proto = scheduler && Object.getPrototypeOf(scheduler);
    if (!proto || typeof proto.scheduleTests !== 'function') return;
    if (!proto.scheduleTests.__detjs) {
      const orig = proto.scheduleTests;
      const scheduleTests = async function scheduleTests(tests, ...rest) {
        const hook = globalThis[Symbol.for('detjs.cache.session')] && globalThis[Symbol.for('detjs.cache.session')].beforeSchedule;
        const list = hook ? await hook(tests) : tests;
        return orig.call(this, list, ...rest);
      };
      Object.defineProperty(scheduleTests, '__detjs', { value: true });
      proto.scheduleTests = scheduleTests;
    }
    pc.deferredDecision = true;
  } catch { pc.deferredDecision = false; }
}

const VOLATILE_GLOBAL = new Set(['json', 'outputFile', 'reporters', 'testPathPatterns', 'testPathPattern', 'nonFlagArgs', 'onlyChanged',
  'watch', 'watchAll', 'watchman', 'watchPlugins', 'maxWorkers', 'runInBand', 'forceExit', 'silent', 'verbose', 'listTests', 'passWithNoTests',
  'detectOpenHandles', 'seed', 'shard', 'useStderr', 'logHeapUsage', 'notify', 'notifyMode', 'lastCommit', 'changedSince', 'changedFilesWithAncestor',
  'findRelatedTests', 'testSequencer', 'coverageReporters', 'coverageDirectory', 'collectCoverageFrom', 'coverageThreshold', 'onlyFailures',
  'openHandlesTimeout', 'testFailureExitCode', 'noStackTrace', 'expand', 'errorOnDeprecated', 'bail', 'maxConcurrency', 'randomize', 'showSeed',
  'testNamePattern_', 'rootDir_', 'collectTests', 'waitForUnhandledRejections']);
const VOLATILE_PROJECT = new Set(['testRunner', 'cacheDirectory', 'id', 'testPathIgnorePatterns', 'testMatch', 'testRegex', 'roots_']);

/** What the configuration digest covers: Jest's resolved configuration (--showConfig) and its version. */
function jestConfigParts(shown, version, rest, pc, customRunners) {
  const { stable, projectPart } = require('../cache/proof');
  const out = { runner: `jest ${version}` };
  if (shown) {
    out.global = stable(shown.globalConfig || {}, VOLATILE_GLOBAL);
    for (const c of shown.configs || []) {
      const name = c.displayName ? c.displayName.name : '';
      projectPart(out, name, stable(c, VOLATILE_PROJECT));
      // a custom runner's files share this process one after the other: cached as one group (src/cache/groups.js)
    }
  } else {
    out.unknown = `no --showConfig output ${Date.now()}`; // never equal: nothing is reused without a known configuration
  }
  out.args = rest.filter((a) => a.startsWith('-') && !/^--(json|outputFile|reporters?|silent|verbose|ci=false|maxWorkers|max-workers|runInBand|watch|listTests|passWithNoTests|coverage|shard)/.test(a) && !/^-[wi](=|$)/.test(a)).sort();
  return out;
}

/**
 * Wrap each project's test environment class: its constructor marks the start of a test file for the cache
 * capture (before setupFiles run) and makes the file's own copy of process.env observable.
 */
function wrapEnvironments(shown, root) {
  const { CAPTURE, installEnv, installReflection } = require('../cache/capture');
  const done = new Set();
  for (const c of (shown && shown.configs) || []) {
    const file = c.testEnvironment;
    if (!file || done.has(file) || !path.isAbsolute(file)) continue;
    done.add(file);
    let mod;
    try { mod = require(file); } catch { continue; }
    const wrap = (Env) => {
      if (typeof Env !== 'function' || Env.__detjsCache) return Env;
      class Wrapped extends Env {
        constructor(config, context) {
          const testPath = context && context.testPath;
          if (testPath) {
            const fileId = path.relative(root, testPath).split(path.sep).join('/');
            const pc2 = config && config.projectConfig;
            const project = pc2 && pc2.displayName ? pc2.displayName.name : '';
            CAPTURE.resetFile();
            CAPTURE.setCtx('f', project ? `${project}|${fileId}` : fileId);
          }
          super(config, context);
          if (this.global && this.global.process) installEnv(CAPTURE, this.global.process);
          // the test file's realm has its own Object / Reflect: descriptor reads of recording Stats objects (G1)
          if (this.global && this.global !== globalThis) installReflection(CAPTURE, this.global);
        }
      }
      Object.defineProperty(Wrapped, '__detjsCache', { value: true });
      Object.defineProperty(Wrapped, 'name', { value: Env.name });
      return Wrapped;
    };
    let exp;
    if (typeof mod === 'function') exp = wrap(mod);
    else {
      exp = { ...mod };
      for (const k of Object.keys(mod)) exp[k] = typeof mod[k] === 'function' && /Environment$|^default$/.test(k) ? wrap(mod[k]) : mod[k];
      if (mod.__esModule) Object.defineProperty(exp, '__esModule', { value: true });
    }
    const resolved = require.resolve(file);
    if (require.cache[resolved]) require.cache[resolved].exports = exp;
  }
}

module.exports = { main, wrapEnvironments };
