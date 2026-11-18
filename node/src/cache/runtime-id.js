'use strict';
// Runtime identity of a Node test run: equal on equivalent machines, different whenever behaviour can differ.
// The JavaScript counterpart of python/detpy/runtime_id.py (docs/SHARED-CACHE.md). Parts (each a digest):
//
//   node        version and every component version (V8, ICU, tz data, OpenSSL, ...), build flags, execArgv,
//               NODE_OPTIONS
//   executable  bytes of the node binary (not its path)
//   native      bytes of every shared library mapped into this process (libc, libstdc++, libm, the loader, ...),
//               LD_PRELOAD and /etc/ld.so.preload libraries; named by file name, not directory
//   libc        glibc version
//   tz          TZ, the zone file it names, /etc/localtime (bytes and link target), /etc/timezone, Intl's zone
//   locale      LANG, LANGUAGE, LC_*, Intl's default locale, NODE_ICU_DATA
//   cpu         CPUs visible to the process and the instruction-set level (FENVIX_RUNTIME_ISA=off leaves it out)
//   lockfiles   package-lock.json, npm-shrinkwrap.json, pnpm-lock.yaml, yarn.lock, bun.lock(b) at the root
//   packages    every installed file under every node_modules directory of the project, by relative path and
//               bytes (symlinks by target text; links leaving the project are followed), minus installer
//               bookkeeping written per machine; NODE_PATH directories the same way
//
// The project's own files are left out: they are per-test inputs.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../native');

const TREE_EXCLUDE = ['.cache', '.vite', '.vite-temp', '.vitest', '.detjs', '.modules.yaml', '.pnpm-workspace-state.json',
  '.pnpm-workspace-state-v1.json', '.vitest-cache', '.yarn-state.yml', '.yarn-integrity', '.package-lock.json', '.tmp', '.eslintcache', '.nx'];
const LOCKFILES = ['package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lock', 'bun.lockb'];
const SKIP_DIRS = new Set(['node_modules', '.git', '.detjs', '.hg', '.svn']);

function d(x) {
  return native.digest(typeof x === 'string' ? x : JSON.stringify(x));
}

function isaLevel() {
  if (process.env.FENVIX_RUNTIME_ISA === 'off') return 'off';
  let info = '';
  try { info = fs.readFileSync('/proc/cpuinfo', 'utf8'); } catch { return `${process.arch}:unknown`; }
  const line = info.split('\n').find((l) => /^(flags|Features)\s*:/.test(l)) || '';
  const flags = new Set(line.split(':').slice(1).join(':').trim().split(/\s+/));
  if (process.arch !== 'x64') return `${process.arch}:${native.digest([...flags].sort().join(' '))}`;
  const has = (...f) => f.every((x) => flags.has(x));
  if (!has('cx16', 'lahf_lm', 'popcnt', 'sse4_1', 'sse4_2', 'ssse3')) return 'x86-64-v1';
  if (!has('avx', 'avx2', 'bmi1', 'bmi2', 'f16c', 'fma', 'abm', 'movbe', 'xsave')) return 'x86-64-v2';
  if (!has('avx512f', 'avx512bw', 'avx512cd', 'avx512dq', 'avx512vl')) return 'x86-64-v3';
  return 'x86-64-v4';
}

function mappedLibraries() {
  const out = new Map();
  let maps = '';
  try { maps = fs.readFileSync('/proc/self/maps', 'utf8'); } catch { return []; }
  for (const line of maps.split('\n')) {
    const i = line.indexOf('/');
    if (i < 0) continue;
    const p = line.slice(i).trim();
    if (!/\.so(\.|$)/.test(path.basename(p)) || out.has(path.basename(p))) continue;
    out.set(path.basename(p), native.fileDigest(p) || 'unreadable');
  }
  const pre = [];
  for (const x of String(process.env.LD_PRELOAD || '').split(/[\s:]+/).filter(Boolean)) pre.push(x);
  try { for (const x of fs.readFileSync('/etc/ld.so.preload', 'utf8').split(/\s+/).filter(Boolean)) pre.push(x); } catch { /* none */ }
  for (const p of pre) out.set(`preload:${path.basename(p)}`, native.fileDigest(p) || 'missing');
  return [...out.entries()].sort();
}

/** node_modules directories of the project (not nested inside another node_modules). */
function nodeModulesDirs(root, limit = 20000) {
  const out = [];
  let n = 0;
  const walk = (dir, rel) => {
    if (n++ > limit) return;
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      if (!e.isDirectory()) continue;
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.name === 'node_modules') {
        // a node_modules holding only bookkeeping (Vite's cache, detjs' runner shim) installs nothing
        let names = [];
        try { names = fs.readdirSync(path.join(dir, e.name)); } catch { /* unreadable */ }
        if (names.some((x) => !TREE_EXCLUDE.includes(x))) out.push([r, path.join(dir, e.name)]);
        continue;
      }
      if (SKIP_DIRS.has(e.name) || e.name.startsWith('.')) continue;
      walk(path.join(dir, e.name), r);
    }
  };
  walk(root, '');
  return out.sort();
}

function memoPath() {
  const v = process.env.FENVIX_RUNTIME_MEMO;
  if (v === 'off') return null;
  if (v) return v;
  const base = process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache');
  return path.join(base, 'fenvix', `runtime-memo-node-${process.getuid ? process.getuid() : 0}.json`);
}

/** {digest, parts, lists} for the project at `root`, with `env` the environment at session start. */
function runtimeIdentity(root, env = process.env) {
  const t0 = process.hrtime.bigint();
  const parts = {};
  const lists = {};
  const vars = process.config && process.config.variables ? process.config.variables : {};
  const build = {};
  for (const k of Object.keys(vars).sort()) {
    if (/^(icu|openssl|node_shared|node_use|v8_enable|napi|asan|is_debug|node_module_version|llvm|clang|gas|target_arch|host_arch)/.test(k)) build[k] = vars[k];
  }
  parts.node = d({ version: process.version, versions: process.versions, arch: process.arch, platform: process.platform,
    build, execArgv: process.execArgv, NODE_OPTIONS: env.NODE_OPTIONS || '', features: process.features });
  parts.executable = native.fileDigest(process.execPath) || 'unreadable';
  lists.native = mappedLibraries();
  parts.native = d(lists.native);
  let glibc = '';
  try { glibc = process.report.getReport().header.glibcVersionRuntime || ''; } catch { /* not glibc */ }
  parts.libc = d(glibc);
  let lt = '';
  try { lt = fs.readlinkSync('/etc/localtime'); } catch { /* not a link */ }
  const zone = env.TZ ? String(env.TZ).replace(/^:/, '') : '';
  const zoneFile = zone && !zone.includes('..') ? (path.isAbsolute(zone) ? zone : path.join('/usr/share/zoneinfo', zone)) : '';
  parts.tz = d({ TZ: env.TZ || null, zone: zoneFile ? native.fileDigest(zoneFile) : null, localtime: native.fileDigest('/etc/localtime'),
    localtimeLink: lt, timezone: native.fileDigest('/etc/timezone'), intl: Intl.DateTimeFormat().resolvedOptions().timeZone,
    tzdata: process.versions.tz || '' });
  const loc = {};
  for (const k of Object.keys(env).sort()) if (k === 'LANG' || k === 'LANGUAGE' || k.startsWith('LC_')) loc[k] = env[k];
  const ro = Intl.DateTimeFormat().resolvedOptions();
  loc.intl = [ro.locale, ro.calendar, ro.numberingSystem, new Intl.NumberFormat().resolvedOptions().locale];
  if (env.NODE_ICU_DATA) loc.icuData = native.treeDigest([['icu', env.NODE_ICU_DATA]], '/', [], null, 10000, 2);
  parts.locale = d(loc);
  parts.cpu = d({ visible: os.availableParallelism ? os.availableParallelism() : os.cpus().length, isa: isaLevel() });
  lists.lockfiles = LOCKFILES.map((f) => [f, native.fileDigest(path.join(root, f))]).filter(([, x]) => x);
  parts.lockfiles = d(lists.lockfiles);
  const roots = nodeModulesDirs(root);
  // Node's resolution also walks up from the project: node_modules of every ancestor directory
  for (let dir = path.dirname(root), up = '..'; dir !== path.dirname(dir); dir = path.dirname(dir), up += '/..') {
    const nm = path.join(dir, 'node_modules');
    let names = [];
    try { names = fs.readdirSync(nm); } catch { /* none */ }
    if (names.some((x) => !TREE_EXCLUDE.includes(x))) roots.push([`${up}/node_modules`, nm]);
  }
  for (const [i, p] of String(env.NODE_PATH || '').split(path.delimiter).filter(Boolean).entries()) roots.push([`NODE_PATH#${i}`, path.resolve(p)]);
  const threads = Math.max(2, Math.min(16, os.availableParallelism ? os.availableParallelism() : 4));
  const tree = JSON.parse(native.treeDigest(roots, root, TREE_EXCLUDE, memoPath(), 400000, threads));
  parts.packages = tree.truncated ? `truncated-${process.pid}-${Date.now()}` : tree.digest;
  lists.packages = { roots: tree.roots, files: tree.files, links: tree.links, bytes: tree.bytes, hashed: tree.hashed, followed: tree.followed };
  const digest = d(Object.keys(parts).sort().map((k) => [k, parts[k]]));
  return { digest, parts, lists, seconds: Number(process.hrtime.bigint() - t0) / 1e9 };
}

module.exports = { runtimeIdentity, nodeModulesDirs, TREE_EXCLUDE, isaLevel };

if (require.main === module) {
  const r = runtimeIdentity(path.resolve(process.argv[2] || '.'));
  process.stdout.write(`${JSON.stringify(r, null, 1)}\n`);
}
