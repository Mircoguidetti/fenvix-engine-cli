'use strict';
// `detjs mocha --det-cache`: one test file in its own process (started by the driver's pool, src/mocha/preload.js).
// What Mocha's parallel worker does for one file (lib/nodejs/worker.js), with the options of a serial run: the
// `--require` modules (root hooks and global fixtures included), then the `--file` files and the spec, run with the
// buffering reporter;
// the serialized events go to the driver, which replays them into the user's reporter.
const fs = require('node:fs');

async function main() {
  const plan = JSON.parse(fs.readFileSync(process.env.DETJS_MO_PLAN, 'utf8'));
  const { load, mochaClass } = require('./mod');
  const Mocha = mochaClass(plan.mochaDir);
  const { handleRequires, validateLegacyPlugin } = load(plan.mochaDir, 'lib/cli/run-helpers');
  const { serialize } = load(plan.mochaDir, 'lib/nodejs/serializer');
  // eslint-disable-next-line no-eval
  const argv = eval(`(${fs.readFileSync(process.env.DETJS_MO_OPTS, 'utf8')})`);
  const opts = { ui: 'bdd', ...argv, parallel: false, isWorker: true };
  // the `--require` modules run here (not in the driver): setup, root hooks and global fixtures, all captured
  const plugins = await handleRequires(plan.requires);
  validateLegacyPlugin(opts, 'ui', Mocha.interfaces);
  Object.assign(opts, plugins);
  const mocha = new Mocha(opts);
  mocha.files = [...plan.fileArgs, process.env.DETJS_MO_CHILD];
  await mocha.loadFilesAsync();
  mocha.run((result) => {
    fs.writeFileSync(process.env.DETJS_MO_OUT, JSON.stringify(serialize(result)));
    process.exitCode = result && result.failureCount ? 1 : 0;
    if (opts.exit) process.exit();
  });
}

main().catch((e) => {
  process.stderr.write(`${e && e.stack ? e.stack : e}\n`);
  process.exitCode = 2;
});
