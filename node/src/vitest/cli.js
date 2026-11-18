'use strict';
// `detjs vitest [--det ...] [vitest args]`
//
// Without --det (and without DETJS=1) the project's vitest CLI runs unchanged.
// With --det: vitest runs through its Node API with
//   * one worker, files one after the other (fileParallelism: false,
//     maxWorkers: 1) whatever the pool (threads / forks / vmThreads): worker
//     isolation is kept, parallelism is not; the choice is written in the trace;
//   * maxConcurrency 1 and sequence.concurrent false (test.concurrent runs
//     one test at a time, in order); sequence.shuffle off;
//   * a sequencer that sorts files by path (or shuffles them with the seed);
//   * the detjs runner (src/vitest/runner.mjs) in every worker.
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const native = require('../native');
const controls = require('../controls');
const { exportFile } = require('./shell');

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
  const args = rest[0] === 'run' || rest[0] === 'watch' || rest[0] === 'dev' ? rest.slice(1) : rest;
  const parsed = nodeApi.parseCLI(['vitest', 'run', ...args]);
  const filters = parsed.filter || [];
  const options = parsed.options || {};

  const executed = [];
  let projectsRef = [];
  let ctxRef = null;
  const info = { pool: null, isolate: null, projects: [] };
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
        return { f, fileId, project: name, key: name ? `${name}|${fileId}` : fileId };
      });
      keyed.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
      let ordered = keyed;
      if (cfg.shuffle && cfg.controls.has('order')) ordered = native.shuffleIndices(keyed.length, cfg.seed, '').map((i) => keyed[i]);
      if (pc) {
        // end of start-up (Vitest sorts after globalSetup): reuse decision
        const skip = await pc.decide(ordered.map((k) => ({ fileId: k.fileId, project: k.project, key: k.key })));
        ordered = ordered.filter((k) => !skip.has(k.key));
        if (skip.size && !ordered.length) {
          // every file reused: an empty run is a pass, not "no test files found"
          for (const pr of projectsRef) { const pc2 = pr.config || pr.getConfig?.(); if (pc2) pc2.passWithNoTests = true; }
          if (ctxRef && ctxRef.config) ctxRef.config.passWithNoTests = true;
        }
      }
      executed.length = 0;
      for (const k of ordered) executed.push({ fileId: k.fileId, part: controls.partName(k.fileId, k.project) });
      return ordered.map((k) => k.f);
    }
  }

  // The runner is loaded through a shim in the project's node_modules: Vitest
  // imports dependencies natively, while a file outside the project root goes
  // through Vite and is refused when the project restricts server.fs (jotai).
  const shimDir = path.join(root, 'node_modules', '.detjs');
  fs.mkdirSync(shimDir, { recursive: true });
  const runnerShim = path.join(shimDir, `runner-${process.pid}.mjs`);
  fs.writeFileSync(runnerShim, `export { default } from ${JSON.stringify(pathToFileURL(path.join(__dirname, 'runner.mjs')).href)};\n`);
  process.on('exit', () => { try { fs.rmSync(runnerShim, { force: true }); } catch { /* ignore */ } });
  Object.assign(options, {
    run: true,
    watch: false,
    fileParallelism: false,
    maxWorkers: 1,
    maxConcurrency: 1,
    runner: runnerShim,
    sequence: { ...(options.sequence || {}), shuffle: false, concurrent: false, sequencer: DetSequencer },
  });
  if (major < 4) options.minWorkers = 1;

  let finished = false;
  const finalize = () => {
    if (finished) return;
    finished = true;
    if (pc) for (const l of pc.finishSync()) fs.writeSync(1, `${l}\n`);
    const isolation = `vitest pool=${info.pool || 'default'} isolate=${info.isolate}; projects=${(info.projects || []).join(',')}; maxWorkers=1, fileParallelism=false, maxConcurrency=1`;
    const { lines } = session.finish(run, opts, executed, {
      runner: 'vitest', runner_version: pkg.version, isolation, serial: true,
      pool: info.pool, isolate: info.isolate, projects: info.projects, cli_args: args,
    });
    for (const l of lines) fs.writeSync(1, `${l}\n`); // sync: the runner may be exiting
  };
  process.on('exit', finalize);
  for (const l of session.header(run, opts, { runner: 'vitest', runnerVersion: pkg.version, isolation: 'one worker, files in sequence' })) {
    process.stdout.write(`${l}\n`);
  }
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
    c.runner = options.runner;
    c.maxConcurrency = 1;
    c.sequence = { ...(c.sequence || {}), shuffle: false, concurrent: false, sequencer: DetSequencer };
    pools.add(`${c.name || 'root'}:${c.browser && c.browser.enabled ? 'browser' : c.pool}`);
    if (pc) {
      const vite = (pr.vite && pr.vite.config) || (pr.server && pr.server.config);
      if (vite && vite.cacheDir) require('../cache/capture').CAPTURE.addSkipDir(vite.cacheDir);
    }
  }
  info.projects = [...pools];
  if (pc) pc.setConfig(configParts(projects, ctx, args, pc));
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
  if (pc) {
    pc.finishSync();
    await pc.finish();
  }
  finalize();
  return process.exitCode ?? 0;
}

// Options and configuration keys that never change a test's result (selection, output, detjs' own settings).
const VOLATILE_ARGS = new Set(['reporter', 'reporters', 'outputFile', 'silent', 'watch', 'run', 'ui', 'open', 'api', 'project',
  'shard', 'changed', 'passWithNoTests', 'clearScreen', 'logHeapUsage', 'color', 'hideSkippedTests', 'dir', 'includeTaskLocation',
  'standalone', 'printConsoleTrace', 'mergeReports', 'json', 'filter', '_', '--']);
const VOLATILE_CONFIG = new Set(['reporters', 'outputFile', 'watch', 'ui', 'api', 'open', 'runner', 'maxWorkers', 'minWorkers',
  'fileParallelism', 'maxConcurrency', 'include', 'exclude', 'includeSource', 'cliExclude', 'filters', 'shard', 'silent',
  'logHeapUsage', 'printConsoleTrace', 'cache', 'changed', 'passWithNoTests', 'hideSkippedTests', 'dir', 'standalone',
  'coverage', 'benchmark', 'sequence', 'watchTriggerPatterns', 'forceRerunTriggers', 'related', 'mergeReports', 'project',
  'inspector', 'inspect', 'inspectBrk', 'slowTestThreshold', 'onTestFinished', 'tags', 'experimental']);

/** What the configuration digest covers, per project: resolved test configuration, Vite settings, config files. */
function configParts(projects, ctx, args, pc) {
  const { stable } = require('../cache/proof');
  const nativeMod = require('../native');
  const cliArgs = args.filter((a, i) => a.startsWith('-') || (i > 0 && args[i - 1].startsWith('-') && !args[i - 1].includes('=')));
  const parsedOpts = {};
  for (const a of cliArgs) {
    const name = a.replace(/^-+/, '').split('=')[0].split('.')[0];
    if (!VOLATILE_ARGS.has(name)) parsedOpts[a] = true;
  }
  const out = { runner: `vitest ${process.env.DETJS_VITEST_DIR ? JSON.parse(fs.readFileSync(path.join(process.env.DETJS_VITEST_DIR, 'package.json'), 'utf8')).version : '?'}`, args: Object.keys(parsedOpts).sort() };
  for (const pr of projects) {
    const c = pr.config || (pr.getConfig && pr.getConfig());
    if (!c) continue;
    const name = c.name || '';
    const seq = { ...(c.sequence || {}) };
    for (const k of ['sequencer', 'seed', 'shuffle', 'concurrent']) delete seq[k];
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
    out[`project:${name}`] = { test: stable({ ...c, sequence: seq }, VOLATILE_CONFIG), coverage: cov, vite: stable(viteParts) };
    let reason = null;
    if (c.browser && c.browser.enabled) reason = 'browser mode (tests run outside the captured process)';
    else if (c.pool === 'vmThreads' || c.pool === 'vmForks') reason = `pool ${c.pool} (tests run in another realm)`;
    else if (c.isolate === false) reason = 'isolate=false (module state shared between files)';
    pc.noteProject(name, reason);
  }
  return out;
}

module.exports = { main };
