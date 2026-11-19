'use strict';
// `detjs deno-test [--det ...] [deno test args]`: Deno's test runner under Level 0 and the cache with proof.
//
// Without --det (and without DETJS=1) `deno test` runs unchanged. With --det:
// * discovery: `deno test --doc=false ... --filter <none>`-free listing is not offered by Deno, so detjs lists the
//   files with Deno's own rules through `deno test --no-run --reporter=junit` (the JUnit report of a run that does
//   not run tests lists no files either), hence: `deno info`-independent walk of the arguments (directories are
//   walked for `*_test`, `*.test`, `test.*` modules with Deno's extensions, `deno.json` "test.include/exclude"
//   honoured) — see `discover` below;
// * one `deno test` process per file (Deno already gives every file its own isolate, but the process, its
//   environment, working directory and files are shared), in detjs' order; inside a file, declaration order, or
//   Deno's own `--shuffle=<seed derived by the core>` with --det-seed;
// * `--preload` of detjs' setup; the permissions detjs itself needs (read its own files and the run directory,
//   write the run directory, its DETJS_* variables, FFI for the native core) are added to the ones given;
// * --det-cache: inputs as for the other shells, plus (a) the module graph of each test file after its run
//   (`deno info --json`: local modules by content with their stem listing, remote and JSR modules by their cached
//   content, npm packages by their files, modules that failed to resolve by what would make them resolve), (b) any
//   dynamic import whose specifier is not a literal (not in the graph): not cacheable, and (c) Deno's audit of its
//   own permission checks (DENO_AUDIT_PERMISSIONS): an access the capture did not see makes the file not cacheable.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const common = require('./common');
const native = require('../native');

const VALUE_FLAGS = new Set(['--filter', '--config', '-c', '--import-map', '--lock', '--seed', '--shuffle', '--reporter', '--junit-path',
  '--coverage', '--location', '--v8-flags', '--cert', '--node-modules-dir', '--env-file', '--preload', '--ext', '--trace-leaks',
  '--frozen', '--minimum-dependency-age', '--conditions', '--tunnel']);
const REFUSED = { '--watch': 'watch mode', '--parallel': 'files run one per process, in detjs\' order', '--shuffle': 'use --det-seed',
  '--seed': 'use --det-seed (Math.random is seeded by detjs)' };
const DROPPED = new Set(['--reporter', '--junit-path', '--preload', '--parallel']);
const VOLATILE = /^--(reporter|junit-path|quiet|q|fail-fast|coverage|clean|hide-stacktraces|permit-no-files|no-prompt)(=|$)/;
// options `deno info` takes (same module resolution as the run)
const INFO_FLAGS = /^--(config|c|no-config|import-map|lock|no-lock|node-modules-dir|vendor|no-npm|no-remote|cert|unstable[\w-]*|frozen|conditions)(=|$)|^-c$/;
const PERMS = ['read', 'write', 'env', 'ffi', 'sys', 'net', 'run', 'import'];
const TEST_MODULE = /(^|[/\\])(test\.(?:[cm]?[jt]sx?)|[^/\\]*[._]test\.(?:[cm]?[jt]sx?))$/;
const SKIP_DIRS = new Set(['node_modules', '.git', '.detjs']);

function denoVersion(bin) {
  const r = spawnSync(bin, ['--version'], { encoding: 'utf8' });
  return (r.stdout || '').split('\n')[0].replace(/^deno\s+/, '').trim() || 'unknown';
}

function readJsonc(file) {
  try {
    const text = fs.readFileSync(file, 'utf8');
    return JSON.parse(text.replace(/("(?:\\.|[^"\\])*")|\/\/[^\n]*|\/\*[\s\S]*?\*\//g, (m, s) => s || '').replace(/,(\s*[}\]])/g, '$1'));
  } catch { return null; }
}

function findConfig(root, options) {
  const given = common.optionValue(options, ['--config', '-c']);
  if (given) return path.resolve(root, given);
  if (options.includes('--no-config')) return null;
  for (const n of ['deno.json', 'deno.jsonc']) {
    const p = path.join(root, n);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function globToRe(g) {
  let s = g.replace(/^\.\//, '').replace(/\/$/, '');
  s = s.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*\/?/g, '\u0000').replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]').replace(/\u0000/g, '(?:.*/)?');
  return new RegExp(`^${s}(?:/.*)?$`);
}

/**
 * The test modules `deno test` runs for these arguments (Deno's rules: a file argument is a test module whatever its
 * name; a directory, or no argument, is walked for `{*_,*.,}test.{js,mjs,ts,mts,jsx,tsx}`; the configuration's
 * `test.include` / `test.exclude` and top-level `exclude` apply).
 */
function discover(root, positional, conf) {
  const t = (conf && conf.test) || {};
  const include = (t.include || (t.files && t.files.include) || []).map(globToRe);
  const exclude = [...(t.exclude || (t.files && t.files.exclude) || []), ...((conf && conf.exclude) || [])].map(globToRe);
  const out = new Set();
  const rel = (p) => path.relative(root, p).split(path.sep).join('/');
  const excluded = (r) => exclude.some((re) => re.test(r));
  const walk = (dir) => {
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of ents.sort((a, b) => (a.name < b.name ? -1 : 1))) {
      const p = path.join(dir, e.name);
      const r = rel(p);
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name) || e.name.startsWith('.') || excluded(r)) continue;
        walk(p);
      } else if (TEST_MODULE.test(e.name) && !excluded(r) && (!include.length || include.some((re) => re.test(r)))) {
        out.add(r);
      }
    }
  };
  const args = positional.length ? positional : ['.'];
  for (const a of args) {
    const p = path.resolve(root, a);
    let st;
    try { st = fs.statSync(p); } catch { continue; }
    if (st.isDirectory()) walk(p);
    else out.add(rel(p));
  }
  return [...out].sort();
}

/** Add detjs' own needs to the permissions given (unless everything is allowed). */
function permissionArgs(options, needs) {
  if (options.some((a) => a === '-A' || a === '--allow-all')) return options;
  const out = [];
  const given = {};
  for (const a of options) {
    const m = /^--allow-([a-z]+)(?:=(.*))?$/.exec(a);
    if (m && needs[m[1]]) {
      if (m[2] === undefined) given[m[1]] = 'all';
      else given[m[1]] = (given[m[1]] && given[m[1]] !== 'all' ? `${given[m[1]]},` : '') + m[2];
      continue;
    }
    out.push(a);
  }
  for (const [perm, list] of Object.entries(needs)) {
    if (given[perm] === 'all') out.push(`--allow-${perm}`);
    else out.push(`--allow-${perm}=${[given[perm], ...list].filter(Boolean).join(',')}`);
  }
  return out;
}

const DYNAMIC_IMPORT = /\bimport\s*\(\s*(?!(['"])[^'"\n]*\1\s*[,)])(?!`[^`$]*`\s*[,)])/;

/** Items for the module graph of `fileId` (deno info --json), added to the file's capture. */
function graphItems(bin, root, fileId, infoArgs, env) {
  const r = spawnSync(bin, ['info', '--json', ...infoArgs, path.resolve(root, fileId)], { cwd: root, encoding: 'utf8', env, maxBuffer: 512 << 20 });
  if (r.status !== 0) return { items: [['flag', 'unobserved', `deno info failed: ${(r.stderr || '').slice(0, 300)}`]] };
  let g;
  try { g = JSON.parse(r.stdout); } catch { return { items: [['flag', 'unobserved', 'deno info: unreadable output']] }; }
  const items = [];
  const rootSep = fs.realpathSync(root) + path.sep;
  const key = (abs) => (abs.startsWith(rootSep) ? abs.slice(rootSep.length).split(path.sep).join('/') : abs);
  const where = (abs) => (abs.startsWith(rootSep) ? (abs.slice(rootSep.length).split(path.sep).includes('node_modules') ? 'skip' : 'root') : 'outside');
  for (const m of g.modules || []) {
    const spec = m.specifier || '';
    if (m.error) {
      if (spec.startsWith('file:')) {
        const abs = require('node:url').fileURLToPath(spec);
        if (where(abs) === 'skip') continue;
        items.push(['data', key(abs), native.fileDigest(abs) ? `f:${native.fileDigest(abs)}` : 'missing']);
        const stem = native.stemListingDigest(abs.replace(/\.[^./]*$/, ''));
        items.push(['data', key(abs.replace(/\.[^./]*$/, '')), stem ? `g:${stem}` : 'missing']);
      } else {
        items.push(['flag', 'resolve', `${spec}: ${String(m.error).slice(0, 200)}`]);
      }
      continue;
    }
    if (m.kind === 'node' || spec.startsWith('node:')) {
      // node:sqlite opens database files natively (Deno's audit sees the path; flagged here as well)
      if (/^node:sqlite$/.test(spec)) items.push(['flag', 'sqlite', 'node:sqlite in the module graph']);
      continue;
    }
    if (m.kind === 'npm' || spec.startsWith('npm:')) continue; // npmPackages below
    const local = m.local;
    if (!local) { items.push(['flag', 'unobserved', `module without a local copy: ${spec}`]); continue; }
    const w = where(local);
    if (w === 'skip') continue;
    const d = native.fileDigest(local);
    if (!d) { items.push(['flag', 'unobserved', `module not readable: ${spec}`]); continue; }
    if (w === 'root') {
      items.push(['code', key(local), d]);
      const stem = native.stemListingDigest(local.replace(/\.[^./]*$/, ''));
      items.push(['data', key(local.replace(/\.[^./]*$/, '')), stem ? `g:${stem}` : 'missing']);
    } else {
      items.push(['data', local, `f:${d}`]);
    }
    if (/^(JavaScript|TypeScript|JSX|TSX|Mjs|Mts|Cjs|Cts|Dts|Dmts|Dcts)$/i.test(m.mediaType || '') || /\.[cm]?[jt]sx?$/.test(local)) {
      let src = '';
      try { src = fs.readFileSync(local, 'latin1'); } catch { /* digest above */ }
      if (DYNAMIC_IMPORT.test(src)) items.push(['flag', 'dynamic-import', `${key(local)}: import() of a specifier that is not a literal`]);
      if (/\brequire\s*\(/.test(src) && w === 'root') items.push(['flag', 'runtime-api', `${key(local)}: require() (loaded outside the module graph)`]);
    }
  }
  // npm packages: by the files of their cached copy (Deno's global cache, or a node_modules outside the root)
  const pk = g.npmPackages || {};
  const ids = Object.keys(pk).sort();
  if (ids.length) {
    const nm = path.join(root, 'node_modules');
    const local = fs.existsSync(nm);
    for (const id of ids) {
      const p = pk[id];
      if (local) continue; // root node_modules: in the runtime identity
      const dir = npmCacheDir(env, p.name, p.version, p.registryUrl);
      if (!dir) { items.push(['flag', 'unobserved', `npm package ${id} not found in the cache`]); continue; }
      const x = native.copyTreeDigest(dir);
      items.push(['data', dir, x ? `c:${x}` : 'missing']);
    }
  }
  return { items, modules: (g.modules || []).length };
}

function denoDir(env) {
  if (env.DENO_DIR) return env.DENO_DIR;
  const r = spawnSync(process.env.DETJS_DENO || 'deno', ['info', '--json'], { encoding: 'utf8', env });
  try { return JSON.parse(r.stdout).denoDir; } catch { return path.join(os.homedir(), '.cache', 'deno'); }
}

let DENO_DIR = null;
function npmCacheDir(env, name, version, registry) {
  if (DENO_DIR === null) DENO_DIR = denoDir(env);
  const host = registry ? new URL(registry).host : 'registry.npmjs.org';
  const p = path.join(DENO_DIR, 'npm', host, name, version);
  return fs.existsSync(p) ? p : null;
}

/**
 * Deno's audit of its permission checks for one file, compared with what the capture saw: an access the capture did
 * not see (a path, a variable, a system fact), and any process, network, FFI or import permission, makes the file
 * not cacheable. Entries before detjs' marker are detjs' own set-up.
 */
function auditCheck(file, capture, root, skipDirs) {
  let lines;
  try { lines = fs.readFileSync(file, 'utf8').split('\n'); } catch { return [['flag', 'unobserved', 'no permission audit log']]; }
  const ex = capture.explained || { paths: [], env: [], sys: [] };
  const paths = new Set(ex.paths);
  for (const it of capture.items || []) {
    if (it[0] === 'code' || it[0] === 'data' || it[0] === 'write') paths.add(path.isAbsolute(it[1]) ? it[1] : path.join(root, it[1]));
  }
  const env = new Set(ex.env);
  const sys = new Set(ex.sys);
  const out = [];
  let started = false;
  let last = null;
  const skip = (abs) => skipDirs.some((d) => abs === d.slice(0, -1) || abs.startsWith(d));
  for (const l of lines) {
    if (!l) continue;
    let j;
    try { j = JSON.parse(l); } catch { continue; }
    if (!started) { if (j.permission === 'env' && j.value === 'DETJS_AUDIT_START') started = true; continue; }
    const v = j.value;
    switch (j.permission) {
      case 'read':
      case 'write': {
        if (j.permission === 'write' && last && last.permission === 'read' && last.value === v) break; // Deno checks both for a read
        if (typeof v !== 'string') { out.push(['flag', 'unobserved', `${j.permission} of every path`]); break; }
        const abs = path.resolve(capture.cwd || root, v);
        if (paths.has(abs) || skip(abs + path.sep) || skip(abs)) break;
        out.push(['flag', 'unobserved', `${j.permission} ${v}`]);
        break;
      }
      case 'env':
        if (v === null || v === undefined) { if (!env.has('*')) out.push(['flag', 'unobserved', 'env: every variable']); break; }
        if (!env.has(v) && !/^(DETJS($|_)|FENVIX_CACHE_)/.test(v)) out.push(['flag', 'unobserved', `env ${v}`]);
        break;
      case 'sys':
        if (!sys.has(v)) out.push(['flag', 'unobserved', `sys ${v}`]);
        break;
      default:
        out.push(['flag', j.permission === 'net' ? 'connect' : j.permission === 'run' ? 'spawn' : 'unobserved', `${j.permission} ${v}`]);
    }
    last = j;
  }
  if (!started) out.push(['flag', 'unobserved', 'audit log without detjs\' marker']);
  return out;
}

async function main(argv) {
  const env0 = { ...process.env };
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  const bin = common.findBinary('deno', 'DETJS_DENO');
  if (!bin) { process.stderr.write('detjs deno-test: deno not found (PATH, or DETJS_DENO)\n'); return 2; }
  if (!opts.det) return common.runInherit(bin, ['test', ...rest], { cwd: root }).status;
  const { options: rawOptions, positional } = common.splitArgs(rest, VALUE_FLAGS);
  for (const a of rawOptions) {
    const base = a.split('=')[0];
    if (REFUSED[base]) { process.stderr.write(`detjs deno-test: ${base} is not supported with --det (${REFUSED[base]})\n`); return 2; }
  }
  if (opts.record) { process.stderr.write('detjs deno-test: --det-record is not supported (Deno\'s native connections are not recorded)\n'); return 2; }
  const userPreloads = [];
  for (let i = 0; i < rawOptions.length; i++) {
    if (rawOptions[i] === '--preload') userPreloads.push(rawOptions[i + 1]);
    else if (rawOptions[i].startsWith('--preload=')) userPreloads.push(rawOptions[i].slice('--preload='.length));
  }
  const reporter = common.optionValue(rawOptions, ['--reporter']);
  const junitPath = common.optionValue(rawOptions, ['--junit-path']);
  let options = common.dropOptions(rawOptions, DROPPED, VALUE_FLAGS);
  const run = session.prepare(opts, root, 'deno');
  const version = denoVersion(bin);
  const confPath = findConfig(root, options);
  const conf = confPath ? readJsonc(confPath) : null;
  const fileIds = discover(root, positional, conf);
  const engineDir = path.resolve(__dirname, '..', '..');
  const needs = {
    read: [engineDir, run.dir, root, os.tmpdir()],
    write: [run.dir],
    env: ['DETJS', 'DETJS_SEED', 'DETJS_SHUFFLE', 'DETJS_DIR', 'DETJS_ROOT', 'DETJS_EPOCH', 'DETJS_TICK', 'DETJS_TICK_ADAPT', 'DETJS_TIMERS',
      'DETJS_TIMER_BUDGET', 'DETJS_DISABLE', 'DETJS_NET_MODE', 'DETJS_CASSETTE', 'DETJS_ALLOW_HOSTS', 'DETJS_URANDOM', 'DETJS_MAX_EVENTS',
      'DETJS_SITES', 'DETJS_RUNNER', 'DETJS_FILE', 'DETJS_CACHE', 'DETJS_CACHE_SKIP_DIRS', 'DETJS_CACHE_DEBUG', 'DETJS_NATIVE',
      'DETJS_AUDIT_START', 'TMPDIR', 'TMP', 'TEMP', 'HOME', 'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY', 'no_proxy',
      'ALL_PROXY', 'all_proxy'],
    ffi: [require('../native').__path],
    sys: ['hostname', 'osRelease', 'networkInterfaces', 'uid', 'gid', 'homedir'],
  };
  options = permissionArgs(options, needs);
  let pc = null;
  const infoArgs = options.filter((a, i, all) => INFO_FLAGS.test(a) || (i > 0 && /^(--config|-c|--import-map|--lock|--node-modules-dir|--conditions)$/.test(all[i - 1]) && !a.startsWith('-')));
  if (opts.cache) {
    const { ProofSession } = require('../cache/proof');
    pc = new ProofSession(opts, root, 'deno', run, env0);
    pc.installMain({ mainAnyReads: false });
    const importMap = common.optionValue(options, ['--import-map']) || (conf && conf.importMap);
    const lock = common.optionValue(options, ['--lock']) || (conf && typeof conf.lock === 'string' ? conf.lock : (conf && conf.lock && conf.lock.path));
    const argFiles = [importMap, lock, confPath, common.optionValue(options, ['--env-file'])].filter(Boolean);
    const runtimeEnv = Object.entries(env0).filter(([k]) => /^(DENO_|NODE_ENV$|NODE_OPTIONS$|NPM_CONFIG_REGISTRY$|TZ$)/.test(k)).sort();
    pc.setConfig({
      runner: `deno ${version}`,
      binary: common.fileDigestOr(fs.realpathSync(bin)),
      config: conf || 'none',
      args: options.filter((a) => !VOLATILE.test(a)),
      argFiles: argFiles.map((f) => [f, common.fileDigestOr(path.resolve(root, f))]),
      preloads: userPreloads,
      env: runtimeEnv,
    }, { extra: /^(deno\.jsonc?|deno\.lock|import_map\.json|importmap\.json)$/ });
  }
  const order = common.orderFiles(fileIds, run.cfg);
  const preload = path.join(__dirname, 'deno-preload.mjs');
  const junitParts = [];
  const auditDir = path.join(run.dir, 'audit');
  fs.mkdirSync(auditDir, { recursive: true });
  const auditOf = (i) => path.join(auditDir, `${String(i).padStart(6, '0')}.jsonl`);
  const spawnFile = (fileId, i, extraEnv) => {
    const args = ['test', '--preload', preload];
    for (const p of userPreloads) args.push('--preload', p);
    if (run.cfg.shuffle && run.cfg.controls.has('order')) args.push(`--shuffle=${common.fileSeed(run.cfg, fileId)}`);
    if (junitPath) {
      const part = path.join(run.dir, 'junit', `${String(i).padStart(6, '0')}.xml`);
      fs.mkdirSync(path.dirname(part), { recursive: true });
      junitParts.push(part);
      args.push(`--junit-path=${part}`);
    }
    if (reporter) args.push(`--reporter=${reporter}`);
    args.push(...options, path.resolve(root, fileId));
    const env = { ...process.env, ...extraEnv };
    if (pc) env.DENO_AUDIT_PERMISSIONS = auditOf(i);
    const r = common.runInherit(bin, args, { cwd: root, env });
    r.index = i;
    return r;
  };
  const skipDirs = () => {
    const { CAPTURE } = require('../cache/capture');
    const dd = (() => { try { if (DENO_DIR === null) DENO_DIR = denoDir(process.env); return DENO_DIR; } catch { return null; } })();
    return [...CAPTURE.skipDirs, path.join(root, '.detjs') + path.sep, ...['src', 'bin', 'node_modules'].map((d) => path.join(engineDir, d) + path.sep),
      require('../native').__path, ...(dd ? [path.resolve(dd) + path.sep] : []), path.join(root, 'node_modules') + path.sep];
  };
  const extra = (capture, fileId, r) => {
    const g = graphItems(bin, root, fileId, infoArgs, process.env);
    capture.items.push(...g.items);
    capture.graph_modules = g.modules || 0;
    capture.items.push(...auditCheck(auditOf(r.index), capture, root, skipDirs()));
  };
  const code = await common.runFiles({
    runner: 'deno', runnerVersion: version, root, opts, run, pc, fileIds: order, spawnFile,
    extra: pc && process.env.DETJS_RUNTIME_NAIVE !== '1' ? extra : null,
    isolation: 'deno test: one process per test file (detjs order)', isolationShort: 'process per file', cliArgs: rest,
    afterRun: () => { if (junitPath) common.mergeJunit(junitParts, path.resolve(root, junitPath), 'deno test'); },
  });
  return code;
}

module.exports = { main, discover, permissionArgs, auditCheck, graphItems, DYNAMIC_IMPORT };
