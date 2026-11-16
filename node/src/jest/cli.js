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
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  const jest = findJest(root);
  if (!opts.det) {
    const r = spawnSync(process.execPath, [jest.bin, ...rest], { stdio: 'inherit' });
    return r.status ?? 1;
  }
  const shown = showConfig(jest.bin, rest);
  const runners = {};
  const projects = [];
  for (const c of (shown && shown.configs) || []) {
    runners[`${c.rootDir}|${c.displayName ? c.displayName.name : ''}`] = c.testRunner;
    projects.push({ rootDir: c.rootDir, testRunner: c.testRunner, testEnvironment: c.testEnvironment });
  }
  // What jest-cli's bin does before run(): many configs (Babel presets) depend on it.
  if (process.env.NODE_ENV == null) process.env.NODE_ENV = 'test';
  const run = session.prepare(opts, root, 'jest');
  process.env.DETJS_JEST_RUNNERS = JSON.stringify(runners);
  const extra = ['--runInBand', '--maxConcurrency=1',
    `--testSequencer=${path.join(__dirname, 'sequencer.js')}`,
    `--testRunner=${path.join(__dirname, 'runner.js')}`];
  const help = spawnSync(process.execPath, [jest.bin, '--help'], { encoding: 'utf8', env: { ...process.env, DETJS: '0' } });
  if (/--randomize/.test(help.stdout || '')) extra.push('--no-randomize');
  const isolation = 'jest --runInBand: one test file at a time in the main process, each in its own vm context; maxConcurrency=1';
  let finished = false;
  const finalize = () => {
    if (finished) return;
    finished = true;
    let files = [];
    try { files = JSON.parse(fs.readFileSync(path.join(run.dir, 'order.json'), 'utf8')); } catch { /* no tests */ }
    const { lines } = session.finish(run, opts, files, {
      runner: 'jest', runner_version: jest.pkg.version, isolation, serial: true, projects, cli_args: rest,
    });
    for (const l of lines) process.stdout.write(`${l}\n`);
  };
  process.on('exit', finalize);
  for (const l of session.header(run, opts, { runner: 'jest', runnerVersion: jest.pkg.version, isolation: 'runInBand' })) {
    process.stdout.write(`${l}\n`);
  }
  const cliReq = require('node:module').createRequire(jest.bin);
  const jestCli = cliReq('jest-cli');
  await jestCli.run([...rest, ...extra], undefined);
  finalize();
  return process.exitCode ?? 0;
}

module.exports = { main };
