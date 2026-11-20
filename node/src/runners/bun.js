'use strict';
// `detjs bun-test [--det ...] [bun test args]`: Bun's test runner under Level 0 and the cache with proof.
//
// Without --det (and without DETJS=1) `bun test` runs unchanged. With --det:
// * discovery: Bun's own (a `bun test` with the same filters and a preload whose loader hook returns an empty module
//   for every file and lists it: no test code runs), so the files are exactly those `bun test` would run;
// * one `bun test` process per file, in detjs' order (sorted, or shuffled with --det-seed by the core); inside a file,
//   declaration order, or Bun's own `--randomize --seed=<derived>` with --det-seed (the seed derived per file by the
//   core); `--max-concurrency=1` (test.concurrent runs one test at a time);
// * bunfig.toml: its preloads would run before detjs' preload (Bun loads them first), so detjs passes a copy of the
//   configuration without them (`--config=`) and passes them after its own preload;
// * --det-cache: a file is reused only when all its tests and its manifest prove reuse (src/cache/proof.js); the
//   configuration digest covers Bun's binary and version, bunfig.toml (and the global one), the options (filters
//   excepted), the `BUN_*` and `NODE_ENV` variables, `--env-file` files and the shared configuration files.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const common = require('./common');

// bun test options that take a value (`--opt value` as well as `--opt=value`)
const VALUE_FLAGS = new Set(['--timeout', '--rerun-each', '--seed', '--coverage-reporter', '--coverage-dir', '-t', '--test-name-pattern',
  '--reporter', '--reporter-outfile', '--preload', '-r', '--max-concurrency', '--config', '--tsconfig-override', '-d', '--define',
  '-l', '--loader', '--conditions', '--env-file', '--cwd', '--shard', '--timings', '--path-ignore-patterns', '--main-fields', '--extension-order',
  '--jsx-factory', '--jsx-fragment', '--jsx-import-source', '--jsx-runtime', '--console-depth', '--user-agent', '--dns-result-order']);
// options detjs owns under --det (order, concurrency, output) or that cannot run deterministically
const REFUSED = { '--watch': 'watch mode', '--hot': 'hot reload', '--randomize': 'use --det-seed (order is detjs\')', '--seed': 'use --det-seed' };
const DROPPED = new Set(['--concurrent', '--max-concurrency', '--preload', '-r', '--config', '-c']);
// selection / output options: not part of the configuration digest
const VOLATILE = /^--(reporter|reporter-outfile|dots|only-failures|silent|verbose|bail|coverage-dir|coverage-reporter|timings|update-timings|shard)(=|$)/;

function bunVersion(bin) {
  const r = spawnSync(bin, ['--revision'], { encoding: 'utf8' });
  return (r.stdout || '').trim() || 'unknown';
}

/** bunfig.toml as an object (parsed by Bun), or null. */
function readBunfig(bin, file) {
  if (!file || !fs.existsSync(file)) return null;
  const r = spawnSync(bin, ['-e', 'process.stdout.write(JSON.stringify(Bun.TOML.parse(require("fs").readFileSync(process.argv[1], "utf8"))))', file],
    { encoding: 'utf8', env: { ...process.env, DETJS: '0' } });
  if (r.status !== 0) throw new Error(`detjs bun-test: cannot parse ${file}: ${(r.stderr || '').slice(0, 500)}`);
  return JSON.parse(r.stdout);
}

function tomlKey(k) {
  return /^[A-Za-z0-9_-]+$/.test(k) ? k : JSON.stringify(k);
}

function tomlValue(v) {
  if (v === null || v === undefined) return '""';
  if (Array.isArray(v)) return `[${v.map(tomlValue).join(', ')}]`;
  if (typeof v === 'object') return `{ ${Object.entries(v).map(([k, x]) => `${tomlKey(k)} = ${tomlValue(x)}`).join(', ')} }`;
  if (typeof v === 'string') return JSON.stringify(v);
  return String(v);
}

/** TOML text of a parsed bunfig (tables, arrays, inline tables, strings, numbers, booleans). */
function toToml(obj, prefix = []) {
  const lines = [];
  const tables = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === 'object' && !Array.isArray(v)) tables.push([k, v]);
    else lines.push(`${tomlKey(k)} = ${tomlValue(v)}`);
  }
  const out = [];
  if (prefix.length && (lines.length || !tables.length)) out.push(`[${prefix.map(tomlKey).join('.')}]`);
  out.push(...lines);
  for (const [k, v] of tables) out.push('', toToml(v, [...prefix, k]));
  return out.join('\n');
}

/** Bunfig without its preloads, and the preloads (absolute paths, in Bun's order: top-level, then [test]). */
function splitBunfig(cfg, root) {
  if (!cfg) return { config: {}, preloads: [] };
  const c = JSON.parse(JSON.stringify(cfg));
  const preloads = [];
  const take = (o) => {
    if (!o || o.preload === undefined) return;
    for (const p of [].concat(o.preload)) preloads.push(path.resolve(root, String(p)));
    delete o.preload;
  };
  take(c);
  take(c.test);
  return { config: c, preloads };
}

const LIST_PRELOAD = `
const fs = require('node:fs');
const out = process.env.DETJS_BUN_LIST;
Bun.plugin({ name: 'detjs-list', setup(b) {
  b.onLoad({ filter: /.*/ }, (args) => { fs.appendFileSync(out, args.path + '\\n'); return { contents: '', loader: 'js' }; });
} });
`;

/** The test files `bun test` would run with these options and filters (relative to root, sorted). */
function discover(bin, root, cfgPath, options, positional, dir) {
  const listFile = path.join(dir, 'list.txt');
  const pre = path.join(dir, 'list-preload.js');
  fs.writeFileSync(pre, LIST_PRELOAD);
  fs.writeFileSync(listFile, '');
  const opts = options.filter((a, i, all) => !/^(-t|--test-name-pattern|--reporter|--reporter-outfile|--coverage|--bail)/.test(a)
    && !(i > 0 && /^(-t|--test-name-pattern|--reporter|--reporter-outfile)$/.test(all[i - 1])));
  const r = spawnSync(bin, ['test', `--config=${cfgPath}`, '--preload', pre, ...opts, ...positional],
    { cwd: root, encoding: 'utf8', env: { ...process.env, DETJS: '0', DETJS_BUN_LIST: listFile }, maxBuffer: 256 << 20 });
  const files = fs.readFileSync(listFile, 'utf8').split('\n').filter(Boolean);
  const out = [...new Set(files)].filter((f) => f !== pre).map((f) => path.relative(root, f).split(path.sep).join('/'));
  if (!out.length && r.status !== 0 && !/No tests found|did not match any test files|0 test files/i.test(`${r.stdout}${r.stderr}`)) {
    process.stderr.write(`detjs bun-test: discovery failed:\n${(r.stderr || r.stdout || '').slice(-3000)}\n`);
  }
  return out.sort();
}

async function main(argv) {
  const env0 = { ...process.env };
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  const bin = common.findBinary('bun', 'DETJS_BUN');
  if (!bin) { process.stderr.write('detjs bun-test: bun not found (PATH, or DETJS_BUN)\n'); return 2; }
  if (!opts.det) return common.runInherit(bin, ['test', ...rest], { cwd: root }).status;
  const { options: rawOptions, positional } = common.splitArgs(rest, VALUE_FLAGS);
  for (const a of rawOptions) {
    const base = a.split('=')[0];
    if (REFUSED[base]) { process.stderr.write(`detjs bun-test: ${base} is not supported with --det (${REFUSED[base]})\n`); return 2; }
  }
  if (opts.record) { process.stderr.write('detjs bun-test: --det-record is not supported (Bun\'s native connections are not recorded)\n'); return 2; }
  const userCfg = common.optionValue(rawOptions, ['--config', '-c']);
  const bunfigPath = userCfg ? path.resolve(root, userCfg) : path.join(root, 'bunfig.toml');
  const userPreloads = [];
  for (let i = 0; i < rawOptions.length; i++) {
    const a = rawOptions[i];
    if (a === '--preload' || a === '-r') userPreloads.push(path.resolve(root, rawOptions[i + 1]));
    else if (a.startsWith('--preload=')) userPreloads.push(path.resolve(root, a.slice('--preload='.length)));
  }
  const options = common.dropOptions(rawOptions, DROPPED, VALUE_FLAGS);
  const reporterOut = common.optionValue(options, ['--reporter-outfile']);
  const reporter = common.optionValue(options, ['--reporter']);
  const runOptions = common.dropOptions(options, new Set(['--reporter', '--reporter-outfile']), VALUE_FLAGS);
  if (process.env.NODE_ENV == null) process.env.NODE_ENV = 'test';
  const run = session.prepare(opts, root, 'bun');
  const version = bunVersion(bin);
  const bunfig = readBunfig(bin, bunfigPath);
  const split = splitBunfig(bunfig, root);
  const cfgPath = path.join(run.dir, 'bunfig.toml');
  fs.writeFileSync(cfgPath, `${toToml(split.config)}\n`);
  const preloads = [...split.preloads, ...userPreloads];
  const fileIds = discover(bin, root, cfgPath, runOptions, positional, run.dir);
  let pc = null;
  if (opts.cache) {
    const { ProofSession } = require('../cache/proof');
    pc = new ProofSession(opts, root, 'bun', run, env0);
    pc.installMain({ mainAnyReads: false });
    const globalBunfig = [process.env.XDG_CONFIG_HOME ? path.join(process.env.XDG_CONFIG_HOME, '.bunfig.toml') : null,
      path.join(os.homedir(), '.bunfig.toml')].filter(Boolean);
    const envFiles = [];
    for (let i = 0; i < runOptions.length; i++) {
      if (runOptions[i] === '--env-file') envFiles.push(runOptions[i + 1]);
      else if (runOptions[i].startsWith('--env-file=')) envFiles.push(runOptions[i].slice('--env-file='.length));
      else if (runOptions[i] === '--tsconfig-override') envFiles.push(runOptions[i + 1]);
      else if (runOptions[i].startsWith('--tsconfig-override=')) envFiles.push(runOptions[i].slice('--tsconfig-override='.length));
    }
    const runtimeEnv = Object.entries(env0).filter(([k]) => /^(BUN_|NODE_ENV$|NODE_OPTIONS$|TZ$)/.test(k) && !/^BUN_INSTALL_CACHE_DIR$/.test(k)).sort();
    pc.setConfig({
      runner: `bun ${version}`,
      binary: common.fileDigestOr(fs.realpathSync(bin)),
      bunfig: bunfig || 'none',
      globalBunfig: globalBunfig.map((f) => [f, fs.existsSync(f) ? common.fileDigestOr(f) : 'missing']),
      preloads: preloads.map((p) => path.relative(root, p)),
      args: runOptions.filter((a) => !VOLATILE.test(a)),
      argFiles: envFiles.map((f) => [f, common.fileDigestOr(path.resolve(root, f))]),
      env: runtimeEnv,
    }, { extra: /^(bunfig\.toml|\.bunfig\.toml)$/ });
  }
  const order = common.orderFiles(fileIds, run.cfg);
  const preload = path.join(__dirname, 'bun-preload.js');
  const junitParts = [];
  const spawnFile = (fileId, i, extraEnv) => {
    const args = ['test', `--config=${cfgPath}`, '--preload', preload];
    for (const p of preloads) args.push('--preload', p);
    args.push('--max-concurrency=1');
    if (run.cfg.shuffle && run.cfg.controls.has('order')) args.push('--randomize', `--seed=${common.fileSeed(run.cfg, fileId)}`);
    if (reporter === 'junit' && reporterOut) {
      const part = path.join(run.dir, 'junit', `${String(i).padStart(6, '0')}.xml`);
      fs.mkdirSync(path.dirname(part), { recursive: true });
      junitParts.push(part);
      args.push('--reporter=junit', `--reporter-outfile=${part}`);
    } else if (reporter && reporter !== 'junit') {
      args.push(`--reporter=${reporter}`);
    }
    args.push(...runOptions, path.resolve(root, fileId));
    return common.runInherit(bin, args, { cwd: root, env: { ...process.env, ...extraEnv, DETJS_PRELOADS: preloads.join(path.delimiter) } });
  };
  const code = await common.runFileProcesses({
    runner: 'bun', runnerVersion: version, root, opts, run, pc, fileIds: order, spawnFile,
    isolation: 'bun test: one process per test file (detjs order); --max-concurrency=1', isolationShort: 'process per file',
    cliArgs: rest, meta: { bunfig_preloads: preloads.map((p) => path.relative(root, p)) },
    afterRun: () => { if (reporter === 'junit' && reporterOut) common.mergeJunit(junitParts, path.resolve(root, reporterOut), 'bun test'); },
  });
  return code;
}

module.exports = { main, toToml, splitBunfig, discover, VALUE_FLAGS };
