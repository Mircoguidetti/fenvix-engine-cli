#!/usr/bin/env node
'use strict';
// detjs: deterministic execution of JavaScript/TypeScript tests (Level 0).
//   detjs vitest [--det [--det-seed=N] ...] [vitest args]
//   detjs jest   [--det [--det-seed=N] ...] [jest args]
//   detjs verify TRACE TRACE [...] [--json] [--show-stable]
const USAGE = `usage: detjs vitest|jest [--det options] [runner args]
       detjs verify TRACE TRACE [...] [--json] [--show-stable]
       detjs --det-help`;

async function main(argv) {
  const [cmd, ...rest] = argv;
  if (cmd === 'vitest') return require('../src/vitest/cli').main(rest);
  if (cmd === 'jest') return require('../src/jest/cli').main(rest);
  if (cmd === 'verify') {
    const native = require('../src/native');
    const paths = rest.filter((a) => !a.startsWith('--'));
    if (paths.length < 1) { console.error(USAGE); return 2; }
    if (rest.includes('--json')) process.stdout.write(`${native.verify(paths)}\n`);
    else process.stdout.write(native.verifyText(paths, rest.includes('--show-stable')));
    const rep = JSON.parse(native.verify(paths));
    return rep.summary.diverged || rep.summary.missing ? 1 : 0;
  }
  if (cmd === '--det-help') { process.stdout.write(require('../src/session').HELP); return 0; }
  console.error(USAGE);
  return 2;
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

if (needsEarly(process.argv.slice(2))) {
  const path = require('node:path');
  const early = path.join(__dirname, '..', 'src', 'cache', 'early.js');
  const env = { ...process.env, DETJS_EARLY: '1', NODE_OPTIONS: `--require ${JSON.stringify(early)} ${process.env.NODE_OPTIONS || ''}`.trim() };
  const r = require('node:child_process').spawnSync(process.execPath, [...process.execArgv, __filename, ...process.argv.slice(2)], { stdio: 'inherit', env });
  if (r.signal) process.kill(process.pid, r.signal);
  process.exitCode = r.status ?? 1;
} else main(process.argv.slice(2)).then((code) => {
  process.exitCode = code;
}, (err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exitCode = 2;
});
