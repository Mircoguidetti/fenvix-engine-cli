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
  const nodeApi = await import(pathToFileURL(exportFile(dir, './node')).href);
  if (typeof nodeApi.parseCLI !== 'function') throw new Error(`detjs: vitest ${pkg.version} has no parseCLI (need vitest >= 1.4)`);
  const args = rest[0] === 'run' || rest[0] === 'watch' || rest[0] === 'dev' ? rest.slice(1) : rest;
  const parsed = nodeApi.parseCLI(['vitest', 'run', ...args]);
  const filters = parsed.filter || [];
  const options = parsed.options || {};

  const executed = [];
  const info = { pool: null, isolate: null };
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
      executed.length = 0;
      for (const k of ordered) executed.push({ fileId: k.fileId, part: controls.partName(k.fileId, k.project) });
      return ordered.map((k) => k.f);
    }
  }

  Object.assign(options, {
    run: true,
    watch: false,
    fileParallelism: false,
    maxWorkers: 1,
    maxConcurrency: 1,
    runner: path.join(__dirname, 'runner.mjs'),
    sequence: { ...(options.sequence || {}), shuffle: false, concurrent: false, sequencer: DetSequencer },
  });
  if (major < 4) options.minWorkers = 1;

  let finished = false;
  const finalize = () => {
    if (finished) return;
    finished = true;
    const isolation = `vitest pool=${info.pool || 'default'} isolate=${info.isolate}; maxWorkers=1, fileParallelism=false, maxConcurrency=1`;
    const { lines } = session.finish(run, opts, executed, {
      runner: 'vitest', runner_version: pkg.version, isolation, serial: true,
      pool: info.pool, isolate: info.isolate, cli_args: args,
    });
    for (const l of lines) process.stdout.write(`${l}\n`);
  };
  process.on('exit', finalize);
  for (const l of session.header(run, opts, { runner: 'vitest', runnerVersion: pkg.version, isolation: 'one worker, files in sequence' })) {
    process.stdout.write(`${l}\n`);
  }
  const ctx = major >= 5
    ? await nodeApi.startVitest(filters, options)
    : await nodeApi.startVitest('test', filters, options);
  if (ctx && typeof ctx.close === 'function' && !ctx.closingPromise) await ctx.close();
  finalize();
  return process.exitCode ?? 0;
}

module.exports = { main };
