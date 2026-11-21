'use strict';
// Hermetic start state for Level 2 browser runs: the files and databases an app
// server reads are restored to one snapshot before every `--det` run, so that
// a replay starts from the state the recorded run started from. (Round 1: with
// seeded random a replay creates the same users and e-mails again; without a
// restore the database still holds them from the previous run and the replay
// fails on a unique constraint instead of replaying the test.)
//
// State spec (JSON file given with --det-state=FILE, paths relative to the file):
//   {
//     "files":    ["var/", "data/app.db"],              files or directories
//     "postgres": ["postgres://user:pw@host:port/db"],  databases (template copy)
//     "commands": {"save": ["..."], "restore": ["..."]} extra shell commands
//                                                       (mail catchers, caches)
//   }
// Snapshot: <dir of the spec>/.detjs/state/ (files copied, one template database
// `<db>__detjs_snap` per database). The first `--det` run with a spec and no
// snapshot saves one; every run restores it first. `detjs state save|restore
// --det-state=FILE` does the same outside a run (servers started before the runner).
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const crypto = require('node:crypto');

function load(specFile) {
  const file = path.resolve(specFile);
  const spec = JSON.parse(fs.readFileSync(file, 'utf8'));
  const base = path.dirname(file);
  return {
    file,
    base,
    dir: path.resolve(base, spec.dir || path.join('.detjs', 'state')),
    files: (spec.files || []).map((f) => path.resolve(base, f)),
    postgres: spec.postgres || [],
    commands: { save: [], restore: [], ...(spec.commands || {}) },
  };
}

// ------------------------------------------------------------------- files
function copyTree(src, dst) {
  fs.rmSync(dst, { recursive: true, force: true });
  if (!fs.existsSync(src)) return false;
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.cpSync(src, dst, { recursive: true, preserveTimestamps: true, verbatimSymlinks: true });
  return true;
}

function fileKey(spec, f) {
  return path.relative(spec.base, f).split(path.sep).join('/').replace(/\.\.\//g, '__up__/') || '.';
}

function digestTree(p, h) {
  if (!fs.existsSync(p)) { h.update('-'); return; }
  const st = fs.lstatSync(p);
  if (st.isDirectory()) {
    for (const n of fs.readdirSync(p).sort()) { h.update(`d:${n}\0`); digestTree(path.join(p, n), h); }
  } else if (st.isSymbolicLink()) h.update(`l:${fs.readlinkSync(p)}`);
  else h.update(fs.readFileSync(p));
}

// ---------------------------------------------------------------- postgres
function pgParts(url) {
  const u = new URL(url);
  const db = decodeURIComponent(u.pathname.replace(/^\//, ''));
  if (!db) throw new Error(`detjs state: no database name in ${url}`);
  const admin = new URL(url);
  admin.pathname = '/postgres';
  admin.search = '';
  return { db, snap: `${db}__detjs_snap`, admin: admin.toString() };
}

function ident(name) { return `"${name.replace(/"/g, '""')}"`; }
function lit(name) { return `'${name.replace(/'/g, "''")}'`; }

function psql(adminUrl, sql) {
  const r = spawnSync(process.env.DETJS_PSQL || 'psql', [adminUrl, '-v', 'ON_ERROR_STOP=1', '-q', '-At', '-c', sql], { encoding: 'utf8' });
  if (r.error) throw new Error(`detjs state: psql not available (${r.error.message}); set DETJS_PSQL`);
  if (r.status !== 0) throw new Error(`detjs state: psql failed: ${(r.stderr || '').trim()}`);
  return r.stdout.trim();
}

function terminate(adminUrl, db) {
  psql(adminUrl, `SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = ${lit(db)} AND pid <> pg_backend_pid()`);
}

// Copy a database with CREATE DATABASE ... TEMPLATE (a file-level copy: seconds, no dump). Connections
// to the source are closed first (Postgres refuses to copy a database in use).
function pgCopy(adminUrl, from, to) {
  terminate(adminUrl, from);
  terminate(adminUrl, to);
  psql(adminUrl, `DROP DATABASE IF EXISTS ${ident(to)}`);
  psql(adminUrl, `CREATE DATABASE ${ident(to)} TEMPLATE ${ident(from)}`);
}

// ------------------------------------------------------------------ public
function run(cmds, cwd) {
  for (const c of cmds) {
    const r = spawnSync('bash', ['-c', c], { cwd, stdio: 'inherit' });
    if (r.status !== 0) throw new Error(`detjs state: command failed (${r.status}): ${c}`);
  }
}

function exists(spec) {
  return fs.existsSync(path.join(spec.dir, 'meta.json'));
}

function save(spec) {
  fs.rmSync(spec.dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(spec.dir, 'files'), { recursive: true });
  const present = {};
  for (const f of spec.files) present[fileKey(spec, f)] = copyTree(f, path.join(spec.dir, 'files', fileKey(spec, f)));
  for (const url of spec.postgres) {
    const p = pgParts(url);
    pgCopy(p.admin, p.db, p.snap);
  }
  run(spec.commands.save, spec.base);
  const meta = { saved: new Date().toISOString(), files: present, postgres: spec.postgres.map((u) => pgParts(u).db) };
  fs.writeFileSync(path.join(spec.dir, 'meta.json'), JSON.stringify(meta, null, 1));
  return meta;
}

function restore(spec) {
  const meta = JSON.parse(fs.readFileSync(path.join(spec.dir, 'meta.json'), 'utf8'));
  for (const f of spec.files) {
    const k = fileKey(spec, f);
    fs.rmSync(f, { recursive: true, force: true });
    if (meta.files[k]) copyTree(path.join(spec.dir, 'files', k), f);
  }
  for (const url of spec.postgres) {
    const p = pgParts(url);
    pgCopy(p.admin, p.snap, p.db);
  }
  run(spec.commands.restore, spec.base);
  return meta;
}

/** Digest of the restored file state (goes into the run's meta: two runs that differ here started differently). */
function digest(spec) {
  const h = crypto.createHash('sha256');
  for (const f of spec.files) { h.update(`f:${fileKey(spec, f)}\0`); digestTree(f, h); }
  for (const url of spec.postgres) h.update(`pg:${pgParts(url).db}\0`);
  return h.digest('hex').slice(0, 16);
}

/** Before a --det run: save the snapshot if there is none, then restore it. Returns a one-line summary. */
function prepareRun(specFile) {
  const spec = load(specFile);
  let saved = false;
  if (!exists(spec)) { save(spec); saved = true; }
  restore(spec);
  return { spec, saved, digest: digest(spec) };
}

/** `detjs state save|restore|status --det-state=FILE` */
function cli(argv) {
  const cmd = argv[0];
  const flag = argv.find((a) => a.startsWith('--det-state='));
  const file = flag ? flag.slice('--det-state='.length) : argv[1];
  if (!['save', 'restore', 'status'].includes(cmd) || !file) {
    process.stderr.write('usage: detjs state save|restore|status --det-state=FILE\n');
    return 2;
  }
  const spec = load(file);
  if (cmd === 'save') save(spec);
  else if (cmd === 'restore') {
    if (!exists(spec)) save(spec);
    restore(spec);
  }
  process.stderr.write(`detjs state: ${cmd} ${exists(spec) ? `snapshot ${path.relative(process.cwd(), spec.dir)}` : 'no snapshot'}; files digest ${digest(spec)}\n`);
  return 0;
}

module.exports = { load, save, restore, exists, digest, prepareRun, cli };
