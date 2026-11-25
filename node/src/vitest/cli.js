'use strict';
// `detjs vitest [--det ...] [vitest args]`
//
// Without --det (and without DETJS=1) the project's vitest CLI runs unchanged.
// With --det: vitest runs through its Node API with
//   * one worker, files one after the other (fileParallelism: false,
//     maxWorkers: 1) whatever the pool (threads / forks / vmThreads): worker
//     isolation is kept, parallelism is not; the choice is written in the trace;
//   * concurrent tests (test.concurrent, describe.concurrent, sequence.concurrent) run concurrently, as configured,
//     each in its own Level 0 context (src/concur.js); sequence.shuffle off;
//   * a sequencer that sorts files by path (or shuffles them with the seed);
//   * the detjs runner (src/vitest/runner.mjs) in every worker.
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const native = require('../native');
const controls = require('../controls');
const parallel = require('../parallel');
const { exportFile } = require('./shell');
const { writeShim } = require('../shim');

function findVitest(root) {
  let req;
  try {
    req = require('node:module').createRequire(path.join(root, 'noop.js'));
    return path.dirname(fs.realpathSync(req.resolve('vitest/package.json')));
  } catch {
    throw new Error(`detjs: vitest is not installed in ${root}`);
  }
}

async function main(argv) {
  const env0 = { ...process.env }; // the environment at session start (cache inputs are digested against it)
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  const dir = findVitest(root);
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  if (!opts.det) {
    const bin = path.join(dir, typeof pkg.bin === 'string' ? pkg.bin : pkg.bin.vitest);
    const r = spawnSync(process.execPath, [bin, ...rest], { stdio: 'inherit' });
    return r.status ?? 1;
  }
  const major = Number(pkg.version.split('.')[0]);
  // watch mode (audit G-2183): a --det run is one deterministic run, merged into one trace at its end
  const watch = refuseWatch(rest);
  if (watch) { process.stderr.write(`${watch}\n`); return 2; }
  const run = session.prepare(opts, root, 'vitest');
  process.env.DETJS_VITEST_DIR = dir;
  let pc = null;
  if (opts.cache) {
    const { ProofSession } = require('../cache/proof');
    pc = new ProofSession(opts, root, 'vitest', run, env0);
    pc.installMain({ mainAnyReads: true });
  }
  const nodeApi = await import(pathToFileURL(exportFile(dir, './node')).href);
  if (typeof nodeApi.parseCLI !== 'function') throw new Error(`detjs: vitest ${pkg.version} has no parseCLI (need vitest >= 1.4)`);
  if (rest[0] !== 'run' && process.stdin.isTTY && !process.env.CI) {
    process.stderr.write('detjs: --det runs the suite once (Vitest would start watch mode here: not available under --det)\n');
  }
  const args = rest[0] === 'run' ? rest.slice(1) : rest;
  const parsed = nodeApi.parseCLI(['vitest', 'run', ...args]);
  const filters = parsed.filter || [];
  const options = parsed.options || {};
  // parallel lanes: --det-workers, or Vitest's own --maxWorkers / --fileParallelism on the command line
  if (opts.plan) {
    // --det-plan: the replayed plan's lanes (src/parallel.js)
    opts.plan = path.resolve(opts.plan);
    process.env.DETJS_PLAN = opts.plan;
    if (opts.workers == null) opts.workers = String(parallel.readReplay(opts.plan).lanes.length);
  }
  const want = parallel.resolveWorkers(opts, {
    workers: options.maxWorkers !== undefined ? parallel.workerCount(options.maxWorkers) : options.fileParallelism === true ? -1 : null,
    source: options.maxWorkers !== undefined ? '--maxWorkers' : '--fileParallelism',
    serial: options.fileParallelism === false, serialSource: '--no-file-parallelism',
  });
  if (options.fileParallelism === true && options.maxWorkers === undefined && opts.workers == null) want.workers = -1; // Vitest's own default, below
  const par = { workers: want.workers, source: want.source, refused: null, plan: null, keyOf: new Map(), result: null };

  const executed = [];
  let projectsRef = [];
  let ctxRef = null;
  const info = { pool: null, isolate: null, projects: [], userRunners: [], fileScope: true };
  const composed = new Map();
  const ownRunners = new Map(); // project config -> the project's own runner file
  const cfg = run.cfg;
  class DetSequencer extends nodeApi.BaseSequencer {
    async sort(files) {
      const keyed = files.map((f) => {
        const [project, file] = Array.isArray(f) ? [f[0], f[1]] : [f.project, f.moduleId ?? f.filepath];
        const fileId = path.relative(root, file).split(path.sep).join('/');
        const name = project && (project.name || (project.config && project.config.name)) || '';
        if (project && project.config && info.pool === null) {
          info.pool = project.config.pool;
          info.isolate = project.config.isolate;
        }
        // P1 B1: every file of the run in a fresh worker of its own (isolate, forks or threads, not one shared fork)
        if (!isolatedFiles(configOf(f))) info.fileScope = false;
        return { f, fileId, project: name, key: name ? `${name}|${fileId}` : fileId };
      });
      keyed.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
      let ordered = keyed;
      if (cfg.shuffle && cfg.controls.has('order')) ordered = native.shuffleIndices(keyed.length, cfg.orderSeed, '').map((i) => keyed[i]);
      for (const k of keyed) par.keyOf.set(Array.isArray(k.f) ? k.f[1] : (k.f.moduleId ?? k.f.filepath), k.key);
      ordered = require('../repro').orderFiles(ordered); // --det-order: the listed files, in the listed order
      if (pc) {
        // a file that names a custom environment in a pragma: its project's workers start the capture early
        pc.quiet(() => {
          for (const k of keyed) {
            const [project, file] = Array.isArray(k.f) ? [k.f[0], k.f[1]] : [k.f.project, k.f.moduleId ?? k.f.filepath];
            const c = project && (project.config || project.getConfig?.());
            if (c && !(Array.isArray(c.execArgv) && c.execArgv.includes(EARLY)) && customEnvPragma(file)) addEarlyCapture(c);
          }
        });
        // isolate=false projects: their files form one group, keyed by its ordered list, reused all or none (G-1475)
        const group = ordered.filter((k) => notIsolated(configOf(k.f))).map((k) => k.key);
        if (group.length && !pc.decided) {
          const { groupPart } = require('../cache/groups');
          for (const name of new Set(ordered.filter((k) => group.includes(k.key)).map((k) => k.project))) pc.addProjectPart(name, 'process-group', groupPart(group));
        }
        // end of start-up (Vitest sorts after globalSetup): reuse decision
        const skip = await pc.decide(ordered.map((k) => ({ fileId: k.fileId, project: k.project, key: k.key })));
        if (group.length) require('../cache/groups').demote(pc, group, skip);
        ordered = ordered.filter((k) => !skip.has(k.key));
        if (skip.size && !ordered.length) {
          // every file reused: an empty run is a pass, not "no test files found"
          for (const pr of projectsRef) { const pc2 = pr.config || pr.getConfig?.(); if (pc2) pc2.passWithNoTests = true; }
          if (ctxRef && ctxRef.config) ctxRef.config.passWithNoTests = true;
        }
      }
      executed.length = 0;
      for (const k of ordered) if (!executed.some((e) => e.key === k.key)) executed.push({ fileId: k.fileId, part: controls.partName(k.fileId, k.project), key: k.key });
      if (par.workers > 1 && ordered.length) {
        // the fixed plan: lanes over the files that run (serial order), handed to Vitest in planned start order
        // a file run twice under one key (a test file that is also a typecheck spec): one place in the plan, both specs
        const byKey = new Map();
        for (const k of ordered) { if (!byKey.has(k.key)) byKey.set(k.key, []); byKey.get(k.key).push(k.f); }
        par.plan = parallel.makePlan(root, [...byKey.keys()], par.workers, { replay: opts.plan ? parallel.readReplay(path.resolve(opts.plan)) : null });
        parallel.writeRunPlan(run.dir, par.plan, 'vitest');
        return par.plan.dispatch.flatMap((key) => byKey.get(key));
      }
      return ordered.map((k) => k.f);
    }
  }

  // The runner is loaded through a shim in the project's node_modules: Vitest
  // imports dependencies natively, while a file outside the project root goes
  // through Vite and is refused when the project restricts server.fs (jotai).
  // (src/shim.js: <root>/node_modules/.detjs, or a temporary node_modules when that cannot be written, G-1477)
  const runnerShim = writeShim(root, `runner-${process.pid}.mjs`, `export { default } from ${JSON.stringify(pathToFileURL(path.join(__dirname, 'runner.mjs')).href)};\n`);
  // the runner is set per resolved project below: a project's own `test.runner` is composed, not replaced (G-1437)
  const userRunner = options.runner || null;
  delete options.runner;
  Object.assign(options, {
    run: true,
    watch: false,
    fileParallelism: par.workers !== 1,
    maxWorkers: par.workers > 1 ? par.workers : par.workers === -1 ? undefined : 1,
    sequence: { ...(options.sequence || {}), shuffle: false, sequencer: DetSequencer },
  });
  if (major < 4) options.minWorkers = par.workers > 1 ? par.workers : 1;
  if (options.maxWorkers === undefined) delete options.maxWorkers;

  let finished = false;
  // after the run, before the cache records: placement against the plan, hazards, carried state (src/parallel.js)
  const collectParallel = () => {
    if (par.result) return par.result;
    if (par.poll) clearInterval(par.poll);
    par.result = parallel.collect(root, run.dir, executed.map((e) => e.key), par.plan, {
      shared: false, planned: { workers: par.workers, source: par.source, refused: par.refused },
    });
    if (pc) pc.parallelFlags = par.result.flags;
    for (const l of par.result.lines) fs.writeSync(2, `${l}\n`);
    return par.result;
  };
  const finalize = () => {
    if (finished) return;
    finished = true;
    collectParallel();
    if (pc) for (const l of pc.finishSync()) fs.writeSync(1, `${l}\n`);
    const lanes = par.plan ? `${par.plan.workers} lanes (fixed plan ${par.plan.digest}), fileParallelism=true` : 'maxWorkers=1, fileParallelism=false';
    const isolation = `vitest pool=${info.pool || 'default'} isolate=${info.isolate}; projects=${(info.projects || []).join(',')}; ${lanes}, concurrent tests as configured (one Level 0 context each)${par.refused ? `; parallel refused: ${par.refused}` : ''}${info.userRunners && info.userRunners.length ? `; project runners composed with detjs: ${info.userRunners.join(',')}` : ''}`;
    const { lines } = session.finish(run, opts, executed, {
      runner: 'vitest', runner_version: pkg.version, isolation, serial: !par.plan,
      pool: info.pool, isolate: info.isolate, projects: info.projects, cli_args: args, parallel: par.result.meta,
      files_outside_scope: info.fileScope ? 'file' : 'run',
    });
    for (const l of lines) fs.writeSync(1, `${l}\n`); // sync: the runner may be exiting
  };
  process.on('exit', finalize);
  const headerLines = () => session.header(run, opts, {
    runner: 'vitest', runnerVersion: pkg.version,
    parallel: par.workers > 1 ? `parallel execution in ${par.workers} lanes with a fixed plan (${par.source})` : null,
    isolation: par.workers > 1 ? 'one file at a time per lane, each in a fresh worker' : `one worker, files in sequence${par.refused ? `; parallel refused: ${par.refused}` : '; --det-workers=N or --maxWorkers=N for parallel lanes'}`,
  });
  // createVitest + start (instead of startVitest) so that the detjs runner and
  // the ordering options can be set on every resolved project: project
  // configs (Vitest workspaces / `projects`) do not inherit them from the CLI.
  // What Vitest's own startVitest/prepareVitest does before creating the instance.
  process.env.TEST = 'true';
  process.env.VITEST = 'true';
  process.env.NODE_ENV ??= 'test';
  const ctx = major >= 5
    ? await nodeApi.createVitest(options, undefined, { cliFilters: filters })
    : await nodeApi.createVitest('test', options, undefined, { cliFilters: filters });
  const projects = ctx.projects || ctx.getProjects?.() || [];
  projectsRef = projects;
  ctxRef = ctx;
  const pools = new Set();
  for (const pr of projects) {
    const c = pr.config || pr.getConfig?.();
    if (!c) continue;
    const own = c.runner && !isDetjsRunner(c.runner) ? c.runner : (userRunner ? path.resolve(root, userRunner) : null);
    c.runner = own ? composedRunner(root, own, composed) : runnerShim;
    if (own) { info.userRunners.push(`${c.name || 'root'}:${path.relative(root, own)}`); ownRunners.set(c, own); }
    // the vm pools: Level 0 in the worker before Vitest's vm context takes its view of Node's modules (G-0461)
    if (c.pool === 'vmThreads' || c.pool === 'vmForks') addPreload(c, VM_PRELOAD);
    // the runner's test and hook timeouts on the virtual clock: its clock functions are captured first (G-0144)
    if (cfg.controls.has('timers')) addEarlyCapture(c, DEADLINE_PRELOAD);
    c.sequence = { ...(c.sequence || {}), shuffle: false, sequencer: DetSequencer };
    pools.add(`${c.name || 'root'}:${c.browser && c.browser.enabled ? 'browser' : c.pool}`);
    if (pc) {
      const vite = (pr.vite && pr.vite.config) || (pr.server && pr.server.config);
      const cap = require('../cache/capture').CAPTURE;
      if (vite && vite.cacheDir) cap.addSkipDir(vite.cacheDir);
      // Vitest's per-project temporary directory of transformed modules (their content is derived from the code,
      // which is keyed): read by the workers' module runner since the capture starts before it (early.js)
      if (typeof pr.tmpDir === 'string') cap.addSkipDir(pr.tmpDir);
    }
  }
  info.projects = [...pools];
  if (pc && typeof ctx._tmpDir === 'string') require('../cache/capture').CAPTURE.addSkipDir(ctx._tmpDir);
  // nested Vite configuration files leave the global digest only when the root configuration's imports are known
  if (pc) pc.setConfig(configParts(projects, ctx, args, pc, ownRunners), { nestedViteConfigs: !(ctx.vite && ctx.vite.config) });
  // the cache capture starts in each worker before the project's own preloads and the test environment's set-up
  // (src/cache/early.js; review r021b G4) where user code can run there (preloads, a custom environment; a
  // custom environment named by a file's pragma: in the sequencer); added after the configuration digest, which
  // covers the project's own execArgv (the preload modules and what they read are recorded as inputs of the tests)
  if (pc) for (const pr of projects) { const c = pr.config || pr.getConfig?.(); if (needsEarly(c)) addEarlyCapture(c); }
  // parallel lanes need one file per fresh worker: a worker shared by several files (isolate=false, vm pools),
  // browser mode, the typecheck pool or network recording (one cassette file per process) keep the run serial
  if (par.workers !== 1) {
    const reasons = new Set();
    for (const pr of projects) {
      const c = pr.config || pr.getConfig?.();
      if (!c) continue;
      const po = (c.poolOptions && c.poolOptions[c.pool]) || {};
      if (c.browser && c.browser.enabled) reasons.add('browser mode');
      else if (c.pool === 'vmThreads' || c.pool === 'vmForks') reasons.add(`pool ${c.pool} (files share a worker)`);
      else if (c.pool === 'typescript') reasons.add('typecheck pool');
      else if (c.isolate === false || po.isolate === false) reasons.add('isolate=false (files share a worker: placement would decide what state a file inherits)');
      if (po.singleThread || po.singleFork) reasons.add('singleThread/singleFork');
    }
    if (run.netMode === 'record') reasons.add('--det-record (one cassette per process)');
    if (par.workers === -1) {
      par.workers = Math.max(1, Number((ctx.config && ctx.config.maxWorkers) || 1));
      if (par.workers === 1) reasons.add('Vitest resolved maxWorkers=1');
    }
    if (reasons.size) { par.refused = [...reasons].join('; '); par.workers = 1; }
    const n = par.workers;
    process.env.DETJS_WORKERS = String(n);
    if (n > 1) {
      const dirs = [typeof ctx._tmpDir === 'string' ? ctx._tmpDir : null];
      for (const pr of projects) {
        const vite = (pr.vite && pr.vite.config) || (pr.server && pr.server.config);
        dirs.push(vite && vite.cacheDir, typeof pr.tmpDir === 'string' ? pr.tmpDir : null);
      }
      parallel.skipDirs(dirs);
    }
    for (const c of [ctx.config, ...projects.map((pr) => pr.config || pr.getConfig?.())]) {
      if (!c) continue;
      c.maxWorkers = n;
      c.fileParallelism = n > 1;
      if (major < 4) c.minWorkers = n;
      if (c.poolOptions && typeof c.poolOptions === 'object') {
        for (const [k, po] of Object.entries(c.poolOptions)) {
          if (!po || typeof po !== 'object') continue;
          if (k === 'threads' || k === 'vmThreads') { po.maxThreads = n; po.minThreads = n; }
          if (k === 'forks' || k === 'vmForks') { po.maxForks = n; po.minForks = n; }
        }
      }
    }
    if (par.refused) process.stderr.write(`detjs: parallel refused, running serially: ${par.refused}\n`);
  }
  for (const l of headerLines()) process.stdout.write(`${l}\n`);
  if (par.workers > 1) {
    // a file whose worker died never marks itself finished: the main process marks every file Vitest reports final
    par.poll = setInterval(() => {
      try {
        for (const f of (ctx.state && ctx.state.getFiles ? ctx.state.getFiles() : [])) {
          const st = f.result && f.result.state;
          if (st === 'pass' || st === 'fail' || st === 'skip' || st === 'todo') {
            const key = par.keyOf.get(f.filepath);
            if (key) parallel.markDone(run.dir, key);
          }
        }
      } catch { /* report only */ }
    }, 250);
    par.poll.unref();
  }
  try {
    await ctx.start(filters);
  } catch (e) {
    if (!(e && e.code === 'VITEST_FILES_NOT_FOUND')) throw e;
    process.exitCode = 1;
  }
  const files = ctx.state && ctx.state.getFiles ? ctx.state.getFiles() : [];
  const failed = files.some((f) => f.result && f.result.state === 'fail')
    || (ctx.state && ctx.state.getCountOfFailedTests && ctx.state.getCountOfFailedTests() > 0)
    || (ctx.state && ctx.state.errorsSet && ctx.state.errorsSet.size > 0);
  if (failed) process.exitCode = 1;
  if (!ctx.closingPromise) await ctx.close();
  collectParallel();
  if (pc) {
    pc.finishSync();
    await pc.finish();
  }
  finalize();
  return process.exitCode ?? 0;
}

const EARLY = path.join(__dirname, '..', 'cache', 'early.js');
const DEADLINE_PRELOAD = path.join(__dirname, '..', 'deadline-preload.js');
const VM_PRELOAD = path.join(__dirname, 'vm-preload.js');
const SHELL = path.join(__dirname, 'shell.js');

/** The message refusing watch mode under --det (audit G-2183), or null. */
function refuseWatch(rest) {
  const sub = rest[0];
  const flag = rest.some((a) => a === '--watch' || a === '-w' || a === '--watch=true' || a === '--dev');
  if (sub !== 'watch' && sub !== 'dev' && !flag) return null;
  return 'detjs: watch mode is not supported under --det: a --det run is one deterministic run (one trace, one cache '
    + 'decision). Run `detjs vitest run --det` for each change, or `detjs vitest watch` without --det.';
}

/** A runner path that is detjs' own (a shim of this or an earlier session). */
function isDetjsRunner(p) {
  return /[\\/]node_modules[\\/]\.detjs[\\/]runner-\d+\.mjs$/.test(p) || /[\\/]\.detjs[\\/]runner-\d+-\d+\.mjs$/.test(p)
    || p === path.join(__dirname, 'runner.mjs');
}

/**
 * The project's own Vitest runner composed with detjs' (audit G-1437, G-1476): a module that Vitest loads through its
 * module runner like the project's runner (inside the root: transformed, allowed by `server.fs`), imports the
 * project's runner class and exports detjs' runner extending it. Written once per runner in `<root>/.detjs/`.
 */
function composedRunner(root, own, cache) {
  if (cache.has(own)) return cache.get(own);
  const body = `import Base from ${JSON.stringify(pathToFileURL(own).href)};\n`
    + "import { createRequire } from 'node:module';\n"
    + "const host = typeof process.getBuiltinModule === 'function' ? process.getBuiltinModule('node:module') : null;\n"
    + `const shell = (host || { createRequire }).createRequire(${JSON.stringify(pathToFileURL(SHELL).href)})(${JSON.stringify(SHELL)});\n`
    + 'export default shell.makeRunner(Base, globalThis);\n';
  const dir = path.join(root, '.detjs');
  const file = path.join(dir, `runner-${process.pid}-${cache.size + 1}.mjs`);
  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(file, body);
  } catch (e) {
    throw new Error(`detjs: cannot write ${file} (composition of the project's runner ${own} with detjs' runner): ${e.message}`);
  }
  process.on('exit', () => { try { fs.rmSync(file, { force: true }); } catch { /* ignore */ } });
  cache.set(own, file);
  return file;
}

/** Put `--require file` first among a project's worker preloads (as addEarlyCapture). */
function addPreload(c, file) {
  const add = (list) => (Array.isArray(list) && !list.includes(file) ? ['--require', file, ...list] : list);
  if (Array.isArray(c.execArgv) || !c.poolOptions) c.execArgv = add(c.execArgv || []);
  if (c.poolOptions && typeof c.poolOptions === 'object') {
    for (const k of Object.keys(c.poolOptions)) {
      const po = c.poolOptions[k];
      if (po && typeof po === 'object') po.execArgv = add(po.execArgv || []);
    }
  }
}

/** Files of this project share one worker one after the other (module cache and globals kept): Vitest isolate=false. */
function configOf(f) {
  const project = Array.isArray(f) ? f[0] : f.project;
  return project && (project.config || (project.getConfig && project.getConfig()));
}

/**
 * Each file of this project runs in a fresh worker (P1 B1): Vitest's isolate with the forks or threads pool and not
 * one shared fork / thread. vm pools share the process (and its environment), browser mode is another world: no.
 */
function isolatedFiles(c) {
  if (!c || (c.browser && c.browser.enabled)) return false;
  const pool = c.pool || 'forks';
  if (pool !== 'forks' && pool !== 'threads') return false;
  const po = (c.poolOptions && c.poolOptions[pool]) || {};
  return c.isolate !== false && po.isolate !== false && !po.singleFork && !po.singleThread;
}

function notIsolated(c) {
  if (!c || c.pool === 'vmThreads' || c.pool === 'vmForks' || (c.browser && c.browser.enabled)) return false;
  const po = c.poolOptions && c.poolOptions[c.pool];
  return c.isolate === false || Boolean(po && po.isolate === false);
}
const PRELOAD_ARG = /^(?:-r|--require|--import|--loader|--experimental-loader)(?:=|$)/;
// Vitest's own test environments: their set-up reads no project file
const BUILTIN_ENVS = new Set(['node', 'jsdom', 'happy-dom', 'edge-runtime']);
const ENV_PRAGMA = /@(?:vitest|jest)-environment\s+([^\s*]+)/;

/**
 * Whether user code can run in a worker of project config `c` before the runner: preloads in its execArgv (or in
 * NODE_OPTIONS: then detjs restarted itself with early.js first there), or a custom test environment. Elsewhere
 * the capture starts with the runner, as nothing but Vitest runs before it (an early start costs every worker).
 */
function needsEarly(c) {
  if (!c) return false;
  const argv = [...(Array.isArray(c.execArgv) ? c.execArgv : [])];
  for (const po of Object.values(c.poolOptions || {})) if (po && Array.isArray(po.execArgv)) argv.push(...po.execArgv);
  if (argv.some((a, i) => PRELOAD_ARG.test(String(a)) && argv[i + 1] !== DEADLINE_PRELOAD && a !== `--require=${DEADLINE_PRELOAD}`)) return true;
  if (process.env.DETJS_EARLY === '1') return true;
  const env = typeof c.environment === 'string' ? c.environment : 'node';
  if (!BUILTIN_ENVS.has(env)) return true;
  if (Array.isArray(c.environmentMatchGlobs) && c.environmentMatchGlobs.some((g) => Array.isArray(g) && !BUILTIN_ENVS.has(g[1]))) return true;
  return false;
}

/** A test file whose pragma names a custom environment (`// @vitest-environment ./env.ts`). */
function customEnvPragma(file) {
  let head = '';
  try {
    const fd = fs.openSync(file, 'r');
    try {
      const b = Buffer.alloc(8192);
      head = b.toString('utf8', 0, fs.readSync(fd, b, 0, b.length, 0));
    } finally { fs.closeSync(fd); }
  } catch { return false; }
  const m = ENV_PRAGMA.exec(head);
  return Boolean(m && !BUILTIN_ENVS.has(m[1]));
}

/** Put the early capture first among a project's worker preloads (Vitest >= 4: `execArgv`; older: `poolOptions`). */
function addEarlyCapture(c, file = EARLY) {
  if (!c) return;
  const add = (list) => (Array.isArray(list) && !list.includes(file) ? ['--require', file, ...list] : list);
  if (Array.isArray(c.execArgv) || !c.poolOptions) c.execArgv = add(c.execArgv || []);
  if (c.poolOptions && typeof c.poolOptions === 'object') {
    for (const k of Object.keys(c.poolOptions)) {
      const po = c.poolOptions[k];
      if (po && typeof po === 'object') po.execArgv = add(po.execArgv || []);
    }
  }
}

// Options and configuration keys that never change a test's result (selection, output, detjs' own settings).
const VOLATILE_ARGS = new Set(['maxWorkers', 'max-workers', 'minWorkers', 'min-workers', 'fileParallelism', 'file-parallelism', 'no-file-parallelism', 'reporter', 'reporters', 'outputFile', 'silent', 'watch', 'run', 'ui', 'open', 'api', 'project',
  'shard', 'changed', 'passWithNoTests', 'clearScreen', 'logHeapUsage', 'color', 'hideSkippedTests', 'dir', 'includeTaskLocation',
  'standalone', 'printConsoleTrace', 'mergeReports', 'json', 'filter', '_', '--']);
const VOLATILE_CONFIG = new Set(['reporters', 'outputFile', 'watch', 'ui', 'api', 'open', 'runner', 'maxWorkers', 'minWorkers',
  'fileParallelism', 'include', 'exclude', 'includeSource', 'cliExclude', 'filters', 'shard', 'silent',
  'logHeapUsage', 'printConsoleTrace', 'cache', 'changed', 'passWithNoTests', 'hideSkippedTests', 'dir', 'standalone',
  'coverage', 'benchmark', 'sequence', 'watchTriggerPatterns', 'forceRerunTriggers', 'related', 'mergeReports', 'project',
  'inspector', 'inspect', 'inspectBrk', 'slowTestThreshold', 'onTestFinished', 'tags', 'experimental']);

function root0(ctx) {
  return (ctx.config && ctx.config.root) || process.cwd();
}

/** What the configuration digest covers, per project: resolved test configuration, Vite settings, config files. */
function configParts(projects, ctx, args, pc, ownRunners = new Map()) {
  const { stable, projectPart } = require('../cache/proof');
  const nativeMod = require('../native');
  const cliArgs = args.filter((a, i) => a.startsWith('-') || (i > 0 && args[i - 1].startsWith('-') && !args[i - 1].includes('=')));
  const parsedOpts = {};
  for (const a of cliArgs) {
    const name = a.replace(/^-+/, '').split('=')[0].split('.')[0];
    if (!VOLATILE_ARGS.has(name)) parsedOpts[a] = true;
  }
  const out = { runner: `vitest ${process.env.DETJS_VITEST_DIR ? JSON.parse(fs.readFileSync(path.join(process.env.DETJS_VITEST_DIR, 'package.json'), 'utf8')).version : '?'}`, args: Object.keys(parsedOpts).sort() };
  // the root configuration file and every file it imports (it may import a package's Vite configuration directly)
  const rootVite = (ctx.vite && ctx.vite.config) || null;
  out.rootConfig = rootVite ? {
    file: rootVite.configFile ? [path.relative(root0(ctx), rootVite.configFile), nativeMod.fileDigest(rootVite.configFile)] : null,
    deps: (rootVite.configFileDependencies || []).map((f) => [path.relative(root0(ctx), f), nativeMod.fileDigest(f)]).sort(),
  } : 'unknown';
  for (const pr of projects) {
    const c = pr.config || (pr.getConfig && pr.getConfig());
    if (!c) continue;
    const name = c.name || '';
    const seq = { ...(c.sequence || {}) };
    for (const k of ['sequencer', 'seed', 'shuffle']) delete seq[k];
    const cov = c.coverage ? { enabled: c.coverage.enabled, provider: c.coverage.provider } : null;
    const vite = (pr.vite && pr.vite.config) || (pr.server && pr.server.config) || null;
    let viteParts = null;
    if (vite) {
      const r = vite.resolve || {};
      viteParts = {
        define: vite.define, mode: vite.mode, envPrefix: vite.envPrefix, env: vite.env, json: vite.json, esbuild: vite.esbuild,
        oxc: vite.oxc, plugins: (vite.plugins || []).map((p) => p && p.name),
        resolve: { alias: r.alias, conditions: r.conditions, mainFields: r.mainFields, extensions: r.extensions, dedupe: r.dedupe, preserveSymlinks: r.preserveSymlinks },
        ssr: vite.ssr ? { noExternal: vite.ssr.noExternal, external: vite.ssr.external, resolve: vite.ssr.resolve, target: vite.ssr.target } : null,
        configFile: vite.configFile ? [path.relative(pc.root, vite.configFile), nativeMod.fileDigest(vite.configFile)] : null,
        configFileDependencies: (vite.configFileDependencies || []).map((f) => [path.relative(pc.root, f), nativeMod.fileDigest(f)]).sort(),
      };
    }
    const own = ownRunners.get(c);
    const runnerPart = own ? [path.relative(pc.root, own), nativeMod.fileDigest(own)] : null;
    projectPart(out, name, { test: stable({ ...c, sequence: seq }, VOLATILE_CONFIG), coverage: cov, vite: stable(viteParts), ...(own ? { runner: runnerPart } : {}) });
    let reason = null;
    if (c.browser && c.browser.enabled) reason = 'browser mode (tests run outside the captured process)';
    else if (c.pool === 'vmThreads' || c.pool === 'vmForks') reason = `pool ${c.pool} (tests run in another realm)`;
    // isolate=false: cached by group (src/cache/groups.js, G-1475); the project's own runner is keyed by content
    pc.noteProject(name, reason);
  }
  return out;
}

module.exports = { main };
