'use strict';
// `detjs mocha [--det ...] [mocha args]`
//
// Without --det (and without DETJS=1): the project's mocha, unchanged.
// With --det, the main process (this file):
//   * merges Mocha's options as Mocha does (lib/cli/options loadOptions: command line, MOCHA_OPTIONS, .mocharc.*,
//     package.json `mocha`), finds the spec files with Mocha's own collect-files, orders them (sorted, or shuffled
//     with --det-seed; `--file` files always first), and, with --det-cache, decides which spec files are reused
//     with proof before any of them runs;
//   * runs Mocha's command line in a driver process started like Mocha's bin does (node flags split from Mocha's
//     options, `--node-option`), after detjs' preload (src/mocha/preload.js). --det: Mocha's usual single process,
//     `--parallel` off. --det-cache: every spec file in its own fresh process, one at a time, the results replayed
//     into the user's reporter (skipping file A must not change the context file B runs in);
//   * records the cache entries, writes receipts, summary and trace.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const native = require('../native');
const controls = require('../controls');
const { splitNodeOptions, parseNodeArgs } = require('../nodetest/cli');

function findMocha(root) {
  const req = require('node:module').createRequire(path.join(root, 'noop.js'));
  let pkgFile;
  try { pkgFile = req.resolve('mocha/package.json'); } catch { throw new Error(`detjs: mocha is not installed in ${root}`); }
  const dir = path.dirname(fs.realpathSync(pkgFile));
  return { dir, pkg: JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8')) };
}

const arr = (x) => (x === undefined || x === null || x === false ? [] : (Array.isArray(x) ? x : [x]).map(String));
const list = (x) => arr(x).flatMap((v) => v.split(/ *, */)).filter(Boolean);

// options that only select output, never a test file's result; selection of files is the plan itself
const OUTPUT_ONLY = new Set(['reporter', 'R', 'reporter-option', 'reporter-options', 'O', 'reporterOption', 'reporterOptions', 'color', 'c', 'colors',
  'diff', 'full-trace', 'fullTrace', 'growl', 'G', 'inline-diffs', 'inlineDiffs', 'list-interfaces', 'list-reporters', 'watch', 'w',
  'watch-files', 'watchFiles', 'watch-ignore', 'watchIgnore', 'parallel', 'p', 'jobs', 'j', 'sort', 'S', 'slow', 's', '_', 'spec',
  'ignore', 'exclude', 'extension', 'recursive', 'config', 'package', 'fail-zero', 'failZero', 'posix-exit-codes', 'posixExitCodes', '$0']);

function mochaConfigParts(root, opts, mocha, nodeArgv, nodeOptions) {
  const keep = {};
  for (const k of Object.keys(opts).sort()) if (!OUTPUT_ONLY.has(k)) keep[k] = opts[k];
  // modules and files the options load: project files by content (installed packages: the runtime identity)
  const fileDigest = (p) => {
    const abs = path.resolve(root, p);
    for (const cand of [abs, `${abs}.js`, `${abs}.cjs`, `${abs}.mjs`]) {
      try { if (fs.statSync(cand).isFile()) return [p, native.fileDigest(cand)]; } catch { /* next */ }
    }
    return [p, 'not a project file'];
  };
  const files = [...list(opts.require).map(fileDigest), ...arr(opts.file).map(fileDigest)];
  // configuration files Mocha reads (the merged options above cover their effect; their bytes too)
  const rc = fs.readdirSync(root).filter((n) => /^\.mocharc(\.(js|cjs|mjs|json|jsonc|yaml|yml))?$/.test(n)).sort()
    .map((n) => [n, native.fileDigest(path.join(root, n))]);
  if (opts.config && typeof opts.config === 'string') rc.push(['--config', ...fileDigest(opts.config)]);
  return {
    runner: `mocha ${mocha.pkg.version}`,
    options: keep,
    files,
    rc,
    node: nodeArgv,
    node_options: nodeOptions || '',
    mocha_options_env: process.env.MOCHA_OPTIONS || '',
  };
}

async function main(argv) {
  const env0 = { ...process.env };
  const root = process.cwd();
  const { opts: det, rest } = session.parseArgs(argv);
  const mocha = findMocha(root);
  const bin = path.join(mocha.dir, typeof mocha.pkg.bin === 'string' ? mocha.pkg.bin : mocha.pkg.bin.mocha);
  if (!det.det) {
    const r = spawnSync(process.execPath, [bin, ...rest], { stdio: 'inherit' });
    return r.status ?? 1;
  }
  const { loadOptions } = require(path.join(mocha.dir, 'lib', 'cli', 'options'));
  const nodeFlags = require(path.join(mocha.dir, 'lib', 'cli', 'node-flags'));
  const collectFiles = require(path.join(mocha.dir, 'lib', 'cli', 'collect-files'));
  const opts = loadOptions(rest);
  if (opts.watch || opts.w) throw new Error('detjs mocha: --watch is not supported under --det');
  // what Mocha's bin does: node flags among the options start the process, the rest goes to Mocha's CLI
  const nodeArgs = {};
  const mochaArgs = {};
  for (const k of Object.keys(opts)) {
    if (nodeFlags.isNodeFlag(k)) nodeArgs[k !== 'v8-options' && /^v8-/.test(k) ? k.slice(3) : k] = opts[k];
    else mochaArgs[k] = opts[k];
  }
  const nodeArgv = mochaArgs['node-option'] ? arr(mochaArgs['node-option']).map((v) => `--${v}`) : nodeFlags.unparseNodeFlags(nodeArgs);
  delete mochaArgs['node-option'];
  delete mochaArgs.n;

  // the spec files, as Mocha collects them
  const spec = arr(opts._).length ? arr(opts._) : ['./test'];
  const fileArgs = arr(opts.file).map((f) => path.resolve(root, f));
  const collected = collectFiles({ ignore: list(opts.ignore), extension: list(opts.extension), file: arr(opts.file), recursive: Boolean(opts.recursive), sort: false, spec });
  const all = Array.isArray(collected) ? collected : collected.files;
  const fileSet = new Set(fileArgs);
  const run = session.prepare(det, root, 'mocha');
  const cfg = run.cfg;
  let keyed = [...new Set(all.filter((f) => !fileSet.has(path.resolve(f))))]
    .map((f) => ({ f: path.resolve(f), fileId: path.relative(root, path.resolve(f)).split(path.sep).join('/') }));
  keyed.sort((a, b) => (a.fileId < b.fileId ? -1 : a.fileId > b.fileId ? 1 : 0));
  if (cfg.shuffle && cfg.controls.has('order')) keyed = native.shuffleIndices(keyed.length, cfg.seed, '').map((i) => keyed[i]);

  const mode = det.cache ? 'perfile' : 'single';
  const nodeOptions = env0.NODE_OPTIONS;
  let pc = null;
  let reusedAny = false;
  if (det.cache) {
    const { ProofSession } = require('../cache/proof');
    pc = new ProofSession(det, root, 'mocha', run, env0);
    pc.installMain({ mainAnyReads: false });
    pc.setConfig(mochaConfigParts(root, opts, mocha, nodeArgv, nodeOptions));
    const skip = await pc.decide(keyed.map((k) => ({ fileId: k.fileId, project: '', key: k.fileId })));
    reusedAny = keyed.some((k) => skip.has(k.fileId)) || (pc.verify && pc.reusedFiles.size > 0);
    keyed = keyed.filter((k) => !skip.has(k.fileId));
  }
  // Mocha's own process model is replaced by the plan: serial, files in the plan's order
  for (const k of ['parallel', 'p', 'jobs', 'j', 'sort', 'S']) delete mochaArgs[k];
  if (reusedAny && !keyed.length) { mochaArgs['fail-zero'] = false; mochaArgs.failZero = false; } // every file reused: a pass
  const notes = [];
  if (opts.parallel || opts.p) notes.push('--parallel is off under --det (files run one at a time)');
  if (mode === 'perfile') notes.push('--det-cache: every spec file runs in its own process (skipping a file must not change the context of another); root hooks and `--file` files run in each');
  const iso = mode === 'perfile'
    ? 'mocha: each spec file in its own process, one at a time, results replayed into the reporter'
    : 'mocha: one process, files and tests one at a time';
  for (const l of session.header(run, det, { runner: 'mocha', runnerVersion: mocha.pkg.version, isolation: iso })) process.stdout.write(`${l}\n`);
  for (const n of notes) process.stdout.write(`detjs: ${n}\n`);

  const plan = { mode, mochaDir: mocha.dir, mochaArgs, specs: keyed.map((k) => k.f), fileArgs, dir: run.dir };
  const planPath = path.join(run.dir, 'mocha-plan.json');
  fs.writeFileSync(planPath, JSON.stringify(plan));
  const driverEnv = { ...process.env, DETJS_MO_DRIVER: '1', DETJS_MO_PLAN: planPath };
  delete driverEnv.DETJS_MO_INNER;
  delete driverEnv.DETJS_MO_CHILD;
  const early = [];
  if (nodeOptions !== undefined) {
    driverEnv.DETJS_MO_NODE_OPTIONS = nodeOptions;
    const { early: e, rest: keep } = splitNodeOptions(nodeOptions);
    early.push(...e);
    driverEnv.NODE_OPTIONS = keep;
  }
  const preload = path.join(__dirname, 'preload.js');
  const r = spawnSync(process.execPath, ['--require', preload, ...early, ...nodeArgv, path.join(__dirname, 'driver.js')],
    { stdio: 'inherit', env: driverEnv, cwd: root });
  const status = r.status ?? 1;
  let results = null;
  try { results = JSON.parse(fs.readFileSync(path.join(run.dir, 'mocha-results.json'), 'utf8')); } catch { /* none */ }
  if (pc) {
    if (results && results.globalFixtures) pc.noteProject('', 'mochaGlobalSetup/mochaGlobalTeardown run in the runner process, outside the capture');
    pc.captureFilter = (cap) => {
      const fr = results && results.files[cap.fileId];
      const ok = Boolean(cap.ok && fr && fr.status === 0 && fr.failures === 0 && !fr.failed);
      return { ...cap, ok };
    };
    for (const l of pc.finishSync()) process.stdout.write(`${l}\n`);
    await pc.finish();
  }
  const executed = mode === 'perfile'
    ? keyed.map((k) => ({ fileId: k.fileId, part: controls.partName(k.fileId, '') }))
    : [{ fileId: '<mocha>', part: controls.partName('<mocha>', '') }];
  const { lines } = session.finish(run, det, executed, {
    runner: 'mocha', runner_version: mocha.pkg.version, isolation: iso, serial: true, cli_args: rest, files_planned: keyed.map((k) => k.fileId),
  });
  for (const l of lines) process.stdout.write(`${l}\n`);
  return status;
}

module.exports = { main, mochaConfigParts };
