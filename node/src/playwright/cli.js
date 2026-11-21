'use strict';
// `detjs playwright [test] [--det ...] [playwright test args]`
//
// Without --det (and without DETJS=1) the project's Playwright Test runs unchanged. With --det it runs with
//   * the project's configuration wrapped (src/playwright/config.js): one worker, no parallel mode, no retries, the
//     detjs reporter added to the project's reporters (src/playwright/reporter.js: test ids, order, --det-order,
//     --det-collect, outcomes);
//   * the Level 0 controls and per-test brackets in every worker process (src/playwright/worker.js, NODE_OPTIONS
//     --require), one trace part per test file and worker, merged here in run order into one trace (session.finish).
// The browser and the web servers Playwright starts are separate processes: recorded as such, not controlled.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const session = require('../session');

const CONFIG_NAMES = ['playwright.config.ts', 'playwright.config.js', 'playwright.config.mts', 'playwright.config.mjs',
  'playwright.config.cts', 'playwright.config.cjs'];

function findPlaywright(root) {
  const req = require('node:module').createRequire(path.join(root, 'noop.js'));
  for (const name of ['@playwright/test', 'playwright']) {
    try {
      const pkgFile = req.resolve(`${name}/package.json`);
      const dir = path.dirname(fs.realpathSync(pkgFile));
      const cli = path.join(dir, 'cli.js');
      if (fs.existsSync(cli)) return { dir, cli, version: JSON.parse(fs.readFileSync(pkgFile, 'utf8')).version };
    } catch { /* next */ }
  }
  throw new Error(`detjs: Playwright Test (@playwright/test or playwright) is not installed in ${root}`);
}

/** The --config / -c value of the runner arguments (removed from them), or the project's default config file. */
function takeConfig(args, root) {
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--config' || a === '-c') { const v = args[i + 1]; args.splice(i, 2); return path.resolve(root, v); }
    if (a.startsWith('--config=')) { args.splice(i, 1); return path.resolve(root, a.slice(9)); }
  }
  for (const n of CONFIG_NAMES) if (fs.existsSync(path.join(root, n))) return path.join(root, n);
  return null;
}

function wrapperFile(userConfig, root) {
  const ext = userConfig ? path.extname(userConfig) : '.mjs';
  const dir = userConfig ? path.dirname(userConfig) : root;
  const file = path.join(dir, `.detjs-playwright-${process.pid}.config${ext === '.ts' || ext === '.mts' || ext === '.cts' ? ext : '.mjs'}`);
  const wrapMod = JSON.stringify(path.join(__dirname, 'config.js'));
  const body = userConfig
    ? `import * as user from ${JSON.stringify(`./${path.basename(userConfig)}`)};\nimport { wrap } from ${wrapMod};\nconst u: any = user;\nexport default wrap(u && u.default !== undefined ? u.default : u);\n`
    : `import { wrap } from ${wrapMod};\nexport default wrap({});\n`;
  fs.writeFileSync(file, file.endsWith('.mjs') ? body.replace('const u: any = user;', 'const u = user;') : body);
  return file;
}

async function main(argv) {
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  const args = rest[0] === 'test' ? rest.slice(1) : [...rest];
  const pw = findPlaywright(root);
  if (!opts.det) {
    const r = spawnSync(process.execPath, [pw.cli, 'test', ...args], { stdio: 'inherit' });
    return r.status ?? 1;
  }
  const run = session.prepare(opts, root, 'playwright');
  const userConfig = takeConfig(args, root);
  const wrapper = wrapperFile(userConfig, root);
  const cleanup = () => { try { fs.rmSync(wrapper, { force: true }); } catch { /* ignore */ } };
  process.on('exit', cleanup);
  const isolation = 'playwright test --workers=1 --retries=0, fullyParallel off: one worker process at a time; the browser and web servers are separate processes (not controlled)';
  for (const l of session.header(run, opts, { runner: 'playwright', runnerVersion: pw.version, isolation })) process.stdout.write(`${l}\n`);
  const env = {
    ...process.env,
    DETJS_PLAYWRIGHT: '1',
    NODE_OPTIONS: `--require ${JSON.stringify(path.join(__dirname, 'worker.js'))} ${process.env.NODE_OPTIONS || ''}`.trim(),
  };
  const r = spawnSync(process.execPath, [pw.cli, 'test', '--config', wrapper, '--workers=1', '--retries=0', ...args],
    { stdio: 'inherit', env, cwd: root });
  cleanup();
  let info = { begun: [], files: [] };
  try { info = JSON.parse(fs.readFileSync(path.join(run.dir, 'pw-run.json'), 'utf8')); } catch { /* no test ran */ }
  const files = mergeOrder(run.dir, info);
  const { lines } = session.finish(run, opts, files, {
    runner: 'playwright', runner_version: pw.version, isolation, serial: true, cli_args: args,
    config: userConfig ? path.relative(root, userConfig) : null,
  });
  for (const l of lines) process.stdout.write(`${l}\n`);
  if (opts.collect) return 0;
  return r.status ?? 1;
}

/**
 * The trace parts in run order ([{fileId, part, side}]): a part per test file and worker process, ordered by the
 * position of its first test in the runner's begin order; then the files that ran no test (their recorded data).
 */
function mergeOrder(dir, info) {
  const { partName } = require('./reporter');
  const pos = new Map(info.begun.map((id, i) => [id, i]));
  const partsDir = path.join(dir, 'parts');
  const parts = fs.existsSync(partsDir) ? fs.readdirSync(partsDir) : [];
  const keyed = [];
  for (const p of parts) {
    const ids = session.partIds(path.join(partsDir, p));
    let meta = {};
    try { meta = JSON.parse(fs.readFileSync(path.join(partsDir, p), 'utf8').split('\n', 1)[0]).meta || {}; } catch { /* unreadable */ }
    const fileId = meta.file || (ids[0] ? ids[0].split('::')[0] : p);
    keyed.push({ fileId, part: p, side: partName(fileId), at: ids.length && pos.has(ids[0]) ? pos.get(ids[0]) : Infinity });
  }
  keyed.sort((a, b) => a.at - b.at || (a.part < b.part ? -1 : 1));
  const seen = new Set(keyed.map((k) => k.fileId));
  for (const fileId of info.files || []) {
    if (!seen.has(fileId)) keyed.push({ fileId, part: partName(fileId), side: partName(fileId) });
  }
  return keyed.map(({ fileId, part, side }) => ({ fileId, part, side }));
}

module.exports = { main, mergeOrder };
