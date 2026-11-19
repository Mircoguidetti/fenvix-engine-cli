'use strict';
// `detjs mocha --det-cache`: one test file in its own process (started by the driver's pool, src/mocha/preload.js).
// What Mocha's parallel worker does for one file (lib/nodejs/worker.js), with the options of a serial run: the
// `--require` modules and their root hooks, then the `--file` files and the spec, run with the buffering reporter;
// the serialized events go to the driver, which replays them into the user's reporter.
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const plan = JSON.parse(fs.readFileSync(process.env.DETJS_MO_PLAN, 'utf8'));
  const Mocha = require(plan.mochaDir);
  const { handleRequires, validateLegacyPlugin } = require(path.join(plan.mochaDir, 'lib', 'cli', 'run-helpers'));
  const { serialize } = require(path.join(plan.mochaDir, 'lib', 'nodejs', 'serializer'));
  // eslint-disable-next-line no-eval
  const argv = eval(`(${fs.readFileSync(process.env.DETJS_MO_OPTS, 'utf8')})`);
  const opts = { ui: 'bdd', ...argv, parallel: false, isWorker: true };
  const plugins = await handleRequires(opts.require, { ignoredPlugins: ['mochaGlobalSetup', 'mochaGlobalTeardown'] });
  validateLegacyPlugin(opts, 'ui', Mocha.interfaces);
  opts.rootHooks = plugins.rootHooks;
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
