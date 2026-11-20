#!/usr/bin/env node
'use strict';
// detjs: deterministic execution of JavaScript/TypeScript tests (Level 0).
//   detjs vitest [--det [--det-seed=N] ...] [vitest args]
//   detjs jest   [--det [--det-seed=N] ...] [jest args]
//   detjs bun-test  [--det ...] [bun test args]   (src/runners/bun.js)
//   detjs deno-test [--det ...] [deno test args]  (src/runners/deno.js)
//   detjs node-test [--det ...] [node flags] [file patterns]   (node --test)
//   detjs mocha  [--det ...] [mocha args]
//   detjs tap|ava|jasmine|uvu [--det ...] [runner args]  (src/runners/<name>.js)
//   detjs playwright [test] [--det ...] [playwright test args]  (src/playwright/cli.js)
//   detjs verify TRACE TRACE [...] [--json] [--show-stable]
//   detjs repro TEST | explore --budget MIN | replay BUNDLE  (the repro driver: python -m detpy.fenvix_js, as fenvix)
const RUNNER_SHELLS = new Set(['tap', 'ava', 'jasmine', 'uvu']);
const USAGE = `usage: detjs vitest|jest|playwright|node-test|mocha|bun-test|deno-test|tap|ava|jasmine|uvu [--det options] [runner args]
       detjs verify TRACE TRACE [...] [--json] [--show-stable]
       detjs repro TEST [options] [-- runner args]     flaky Vitest / Jest / Playwright test -> reproducible defect
       detjs explore --budget MIN [options] [-- runner args]
       detjs replay BUNDLE [--runs N]                  (same options and output as fenvix repro / explore / replay)
       detjs --det-help`;

async function main(argv) {
  const [cmd, ...rest] = argv;
  if (cmd === 'vitest') return require('../src/vitest/cli').main(rest);
  if (cmd === 'jest') return require('../src/jest/cli').main(rest);
  if (cmd === 'playwright') return require('../src/playwright/cli').main(rest);
  if (cmd === 'repro' || cmd === 'explore' || cmd === 'replay') return reproDriver(cmd, rest);
  if (cmd === 'bun-test') return require('../src/runners/bun').main(rest);
  if (cmd === 'deno-test') return require('../src/runners/deno').main(rest);
  if (cmd === 'node-test') return require('../src/nodetest/cli').main(rest);
  if (cmd === 'mocha') return require('../src/mocha/cli').main(rest);
  if (RUNNER_SHELLS.has(cmd)) return require(`../src/runners/${cmd}`).main(rest);
  if (cmd === 'verify') {
    const native = require('../src/native');
    const fs = require('node:fs');
    const paths = rest.filter((a) => !a.startsWith('--'));
    // one run proves nothing (audit G-2186); a missing trace is a usage error, not a stack trace (G-2187)
    if (paths.length < 2) { console.error(`detjs verify: needs at least two traces of the same suite (got ${paths.length})\n${USAGE}`); return 2; }
    for (const p of paths) {
      try { fs.accessSync(p, fs.constants.R_OK); } catch { console.error(`detjs verify: cannot read trace ${p}`); return 2; }
    }
    let rep;
    try {
      rep = JSON.parse(native.verify(paths));
      if (rest.includes('--json')) process.stdout.write(`${JSON.stringify(rep)}\n`);
      else process.stdout.write(native.verifyText(paths, rest.includes('--show-stable')).replace(/^detpy verify:/m, 'detjs verify:'));
    } catch (e) {
      console.error(`detjs verify: unreadable trace: ${e && e.message}`);
      return 2;
    }
    if (!rep.summary.tests) { console.error('detjs verify: no test ran in these traces: nothing verified'); return 1; }
    return rep.summary.diverged || rep.summary.missing ? 1 : 0;
  }
  if (cmd === '--det-help') { process.stdout.write(require('../src/session').HELP); return 0; }
  console.error(USAGE);
  return 2;
}

/**
 * `detjs repro|explore|replay`: the repro driver is runner-neutral Rust behind the Python package (python/detpy/
 * fenvix_js.py, the same code as `fenvix repro`): run it with this detjs. FENVIX_PYTHON names the interpreter that has
 * detpy installed (default python3).
 */
function reproDriver(cmd, rest) {
  const { spawnSync } = require('node:child_process');
  const py = process.env.FENVIX_PYTHON || 'python3';
  const env = { ...process.env, FENVIX_DETJS: process.env.FENVIX_DETJS || `${JSON.stringify(process.execPath)} ${JSON.stringify(__filename)}` };
  const r = spawnSync(py, ['-m', 'detpy.fenvix_js', cmd, ...rest], { stdio: 'inherit', env });
  if (r.error) {
    console.error(`detjs ${cmd}: cannot start ${py} (${r.error.message}): the repro driver needs Python with detpy installed (FENVIX_PYTHON=<python>)`);
    return 2;
  }
  return r.status ?? 1;
}

// Preload modules of the user (`NODE_OPTIONS`, `node --require/--import ... detjs`) run before detjs. With the
// cache on, detjs starts itself again with its early capture as the first preload, so that what they read is
// recorded (review r021b G4; src/cache/early.js).
const PRELOAD = /(?:^|\s)(?:-r|--require|--import|--loader|--experimental-loader)(?:=|\s|$)/;
function needsEarly(argv) {
  if (process.env.DETJS_EARLY === '1') return false;
  if (argv[0] !== 'vitest' && argv[0] !== 'jest') return false;
  const cache = argv.some((a) => a === '--det-cache' || a.startsWith('--det-cache=')) || Boolean(process.env.DETJS_CACHE_DIR);
  if (!cache) return false;
  return PRELOAD.test(process.env.NODE_OPTIONS || '') || process.execArgv.some((a) => PRELOAD.test(a));
}

// Time zone and locale (audit G-0139, G-0140): under --det they are pinned for the runner and every process it
// starts, `TZ` (UTC when the job does not set it) and `LC_ALL`/`LANG` (C.UTF-8 when the job sets neither;
// `LANGUAGE` removed); `--det-tz=ZONE|keep` / `--det-locale=LOC|keep` choose explicitly (recorded in the trace
// header either way). The locale of ICU is chosen when
// Node starts: detjs starts itself again with the pinned environment.
const RUNNERS_ALL = new Set(['vitest', 'jest', 'bun-test', 'deno-test', 'node-test', 'mocha', ...RUNNER_SHELLS]);
function pinned(argv) {
  if (!RUNNERS_ALL.has(argv[0])) return null;
  const det = argv.includes('--det') || process.env.DETJS === '1' || process.env.DETJS === 'true';
  if (!det || argv.includes('--no-det')) return null;
  const opt = (name, dflt) => {
    let v = dflt;
    for (let i = 0; i < argv.length; i++) {
      if (argv[i] === name && i + 1 < argv.length) v = argv[i + 1];
      else if (argv[i].startsWith(`${name}=`)) v = argv[i].slice(name.length + 1);
    }
    return v;
  };
  // default: the machine's own default (TZ unset: /etc/localtime; no LC_ALL/LANG) is replaced by UTC / C.UTF-8; a
  // value the job sets explicitly is its configuration and is kept (recorded, and keyed by the cache)
  const tz = opt('--det-tz', process.env.TZ !== undefined && process.env.DETJS_PINNED === undefined ? 'keep' : 'UTC');
  const loc = opt('--det-locale', (process.env.LC_ALL || process.env.LANG) && process.env.DETJS_PINNED === undefined ? 'keep' : 'C.UTF-8');
  const env = {};
  if (tz !== 'keep') env.TZ = tz;
  if (loc !== 'keep') { env.LC_ALL = loc; env.LANG = loc; }
  return { tz, loc, env };
}

function pinEnv(pin, base) {
  const env = { ...base, ...pin.env, DETJS_PINNED: `tz=${pin.tz};locale=${pin.loc}` };
  if (pin.loc !== 'keep') delete env.LANGUAGE;
  return env;
}

const PIN = pinned(process.argv.slice(2));
const PIN_NEEDS_RESTART = PIN && process.env.DETJS_PINNED === undefined && (
  Object.entries(PIN.env).some(([k, v]) => process.env[k] !== v) || (PIN.loc !== 'keep' && process.env.LANGUAGE !== undefined));
if (PIN && !PIN_NEEDS_RESTART) process.env.DETJS_PINNED = process.env.DETJS_PINNED || `tz=${PIN.tz};locale=${PIN.loc}`;

if (needsEarly(process.argv.slice(2)) || PIN_NEEDS_RESTART) {
  const path = require('node:path');
  let env = { ...process.env };
  if (needsEarly(process.argv.slice(2))) {
    const early = path.join(__dirname, '..', 'src', 'cache', 'early.js');
    env = { ...env, DETJS_EARLY: '1', NODE_OPTIONS: `--require ${JSON.stringify(early)} ${process.env.NODE_OPTIONS || ''}`.trim() };
  }
  if (PIN) env = pinEnv(PIN, env);
  const r = require('node:child_process').spawnSync(process.execPath, [...process.execArgv, __filename, ...process.argv.slice(2)], { stdio: 'inherit', env });
  if (r.signal) process.kill(process.pid, r.signal);
  process.exitCode = r.status ?? 1;
} else main(process.argv.slice(2)).then((code) => {
  process.exitCode = code;
}, (err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exitCode = 2;
});
