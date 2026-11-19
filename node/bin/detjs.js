#!/usr/bin/env node
'use strict';
// detjs: deterministic execution of JavaScript/TypeScript tests (Level 0).
//   detjs vitest [--det [--det-seed=N] ...] [vitest args]
//   detjs jest   [--det [--det-seed=N] ...] [jest args]
//   detjs node-test [--det ...] [node flags] [file patterns]   (node --test)
//   detjs mocha  [--det ...] [mocha args]
//   detjs verify TRACE TRACE [...] [--json] [--show-stable]
const USAGE = `usage: detjs vitest|jest|node-test|mocha [--det options] [runner args]
       detjs verify TRACE TRACE [...] [--json] [--show-stable]
       detjs --det-help`;

async function main(argv) {
  const [cmd, ...rest] = argv;
  if (cmd === 'vitest') return require('../src/vitest/cli').main(rest);
  if (cmd === 'jest') return require('../src/jest/cli').main(rest);
  if (cmd === 'node-test') return require('../src/nodetest/cli').main(rest);
  if (cmd === 'mocha') return require('../src/mocha/cli').main(rest);
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

main(process.argv.slice(2)).then((code) => {
  process.exitCode = code;
}, (err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exitCode = 2;
});
