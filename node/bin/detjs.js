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
// Installed by the npm package `fenvix` as both `fenvix` (bin/fenvix.js) and `detjs`.
const RUNNER_SHELLS = new Set(['tap', 'ava', 'jasmine', 'uvu']);
const RUNNERS = ['vitest', 'jest', 'playwright', 'node-test', 'mocha', 'bun-test', 'deno-test', 'tap', 'ava', 'jasmine', 'uvu'];
const PROG = require('node:path').basename(process.argv[1] || 'detjs').replace(/\.js$/, '');
const VERSION = require('../package.json').version;
const USAGE = `usage: detjs vitest|jest|playwright|node-test|mocha|bun-test|deno-test|tap|ava|jasmine|uvu [--det options] [runner args]
       detjs verify TRACE TRACE [...] [--json] [--show-stable]
       detjs repro TEST [options] [-- runner args]     flaky Vitest / Jest / node:test / Playwright test -> reproducible defect
       detjs explore --budget MIN [options] [-- runner args]
       detjs replay BUNDLE [--runs N]                  (same options and output as fenvix repro / explore / replay)
       detjs --det-help | --version | --help`;

async function main(argv) {
  const [cmd, ...rest] = argv;
  // --det-isolate for Vitest and Jest: one runner session per test (src/isolate.js), which run without it
  if ((cmd === 'vitest' || cmd === 'jest') && !process.env.DETJS_ISOLATE_CHILD
    && rest.some((a) => a === '--det-isolate' || a === '--det-isolate=1' || a === '--det-isolate=true')) return require('../src/isolate').main(cmd, rest);
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
      // settings, order and reuse behind each divergence (G-1482, G-1483, G-1402): src/verify-explain.js
      const ex = require('../src/verify-explain').explain(paths, rep);
      // B2/B7 (spec "Engine P0: no false green"): the verdict word of the exit rule, src/exit-status.js
      if (rest.includes('--json')) process.stdout.write(`${JSON.stringify({ ...rep, ...ex.json, status: require('../src/exit-status').verifyStatus(rep.summary) })}\n`);
      else process.stdout.write(require('../src/verify-explain').annotate(native.verifyText(paths, rest.includes('--show-stable')).replace(/^detpy verify:/m, 'detjs verify:'), ex));
    } catch (e) {
      console.error(`detjs verify: unreadable trace: ${e && e.message}`);
      return 2;
    }
    if (!rep.summary.tests) console.error('detjs verify: no test ran in these traces: nothing verified');
    // the rule of python/detpy/fenvix.py verify_exit_code, owned by src/exit-status.js: 1 on no test, diverged,
    // missing, not proven or inputs not recorded; 3 when only inputs differ; else 0
    return require('../src/exit-status').verifyExit(rep.summary);
  }
  if (cmd === '--det-help') { process.stdout.write(require('../src/session').HELP); return 0; }
  if (cmd === '--version' || cmd === '-v' || cmd === 'version') { process.stdout.write(`fenvix ${VERSION}\n`); return 0; }
  if (cmd === '--help' || cmd === '-h' || cmd === 'help') { process.stdout.write(`${USAGE}\n`); return 0; }
  if (cmd !== undefined) console.error(`${PROG}: unknown runner or command '${cmd}'; supported runners: ${RUNNERS.join(', ')}`);
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

// Time zone and locale (audit G-0139, G-0140; review P1 #7): under --det they are pinned for the runner and every
// process it starts, whatever the machine or the job's environment sets: `TZ=UTC`, `LC_ALL`/`LANG=C.UTF-8`
// (`LANGUAGE` removed), as the Python shell does. A job keeps its own value only explicitly, `--det-tz=ZONE|keep` /
// `--det-locale=LOC|keep`; that value is recorded in the trace header, keyed by the cache and named by verify. A
// detjs started by a pinned one keeps the choice made at the top (DETJS_PINNED). The locale of ICU is chosen when
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
  // default: UTC / C.UTF-8 whatever the environment says; under a pinned detjs, the choice made there
  const top = /^tz=([^;]*);locale=(.*)$/.exec(process.env.DETJS_PINNED || '');
  const tz = opt('--det-tz', top ? (top[1] === 'keep' ? 'keep' : top[1]) : 'UTC');
  const loc = opt('--det-locale', top ? (top[2] === 'keep' ? 'keep' : top[2]) : 'C.UTF-8');
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

// P1 (docs/LIMITS.md section 10, row JS-07): a placement must never decide an outcome. When a run's lanes turn out
// to have shared a path or a fixed port, the files the hazard names are run again in one lane and the re-run's
// outcomes are the ones reported (src/parallel-rerun.js).
//
// This sits OUTSIDE the two re-execs below on purpose. Each pass has to be a whole, ordinary detjs invocation: it
// must do its own early-capture re-exec and its own TZ pinning, exactly as an unwrapped run does. Putting the
// wrapper inside that chain instead (in `main`) added a process that carried the early-capture preload and the
// rewritten NODE_OPTIONS, and that process then recorded reads of its own into the run's cache inputs; it broke
// G-1402, G-1586 and the two `verify-inputs-attacks` data cases, which is how the mistake was found. From here the
// instrumented part of the chain is byte-identical to an unwrapped run, and the wrapper is just an outer process
// like the one the early re-exec already starts from.
const RERUN = require('../src/parallel-rerun');
if (RERUN.shouldWrap(process.argv[2], process.argv.slice(3))) {
  RERUN.main(process.argv[2], process.argv.slice(3)).then((r) => {
    if (r.signal) { process.kill(process.pid, r.signal); return; }
    process.exitCode = r.status;
  }, (err) => {
    const msg = err && err.message ? err.message : String(err);
    console.error(/^detjs: /.test(msg) && process.env.DETJS_DEBUG !== '1' ? msg : (err && err.stack ? err.stack : err));
    process.exitCode = require('../src/exit-status').runExit({ internalError: true });
  });
} else if (needsEarly(process.argv.slice(2)) || PIN_NEEDS_RESTART) {
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
  // B1 (spec "Engine P0: no false green"): the runner shell's code and the counts of the trace this process wrote
  // (src/session.js finish, src/isolate.js), decided by src/exit-status.js, for a `--det` run of a runner (with no
  // trace written the counts are 0 and the runner code decides). `verify` (0/1/3/2), repro and the other commands
  // keep the code they decided.
  const xs = require('../src/exit-status');
  const argv = process.argv.slice(2);
  const det = RUNNERS.includes(argv[0]) && (argv.includes('--det') || process.env.DETJS === '1' || process.env.DETJS === 'true') && !argv.includes('--no-det');
  const st = xs.recordedStatus();
  process.exitCode = det || st ? xs.runExit({ ...(st || {}), runnerCode: code }) : code;
}, (err) => {
  // A user error the shell raised itself (message `detjs: ...`) is printed without the JavaScript stack;
  // DETJS_DEBUG=1 prints the stack of every error (audit G-2176).
  const msg = err && err.message ? err.message : String(err);
  const own = /^detjs: /.test(msg) && process.env.DETJS_DEBUG !== '1';
  console.error(own ? msg : (err && err.stack ? err.stack : err));
  process.exitCode = require('../src/exit-status').runExit({ internalError: true });
});
