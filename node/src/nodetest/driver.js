'use strict';
// `detjs node-test` driver: started by the main process (src/nodetest/cli.js) as
//   node <the user's node flags> --require src/nodetest/preload.js src/nodetest/driver.js
// so that the test file processes run() starts inherit exactly the user's node flags plus the preload. It runs the
// files of the plan (already ordered, reused files removed) with node:test's run(): one file at a time, in the
// given order, attaches the reporters the user asked for (as `node --test` does from --test-reporter /
// --test-reporter-destination), sets the exit code from the summaries, and writes per-file results for the main
// process (a file whose summary says it failed is never cached).
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

async function reporterOf(name) {
  const builtin = require('node:test/reporters');
  let r = Object.prototype.hasOwnProperty.call(builtin, name) ? builtin[name] : undefined;
  if (r === undefined) {
    let spec = name;
    if (spec.startsWith('.') || path.isAbsolute(spec)) spec = pathToFileURL(path.resolve(spec)).href;
    else {
      try { spec = pathToFileURL(require('node:module').createRequire(path.join(process.cwd(), 'noop.js')).resolve(spec)).href; } catch { /* bare import */ }
    }
    r = await import(spec);
  }
  if (r && r.default) r = r.default;
  if (r && r.prototype && Object.getOwnPropertyDescriptor(r.prototype, 'constructor')) r = new r(); // eslint-disable-line new-cap
  if (!r) throw new Error(`detjs: ${name} is not a valid test reporter`);
  return r;
}

function destinationOf(d) {
  if (d === 'stdout') return process.stdout;
  if (d === 'stderr') return process.stderr;
  return fs.createWriteStream(d, { flush: true });
}

async function main() {
  const plan = JSON.parse(fs.readFileSync(process.env.DETJS_NT_PLAN, 'utf8'));
  const { run } = require('node:test');
  const options = {
    files: plan.files,
    concurrency: 1,
    isolation: plan.isolation,
    timeout: plan.timeout ?? undefined,
    only: plan.only || undefined,
    forceExit: plan.forceExit || undefined,
    testNamePatterns: plan.testNamePatterns && plan.testNamePatterns.length ? plan.testNamePatterns : undefined,
    testSkipPatterns: plan.testSkipPatterns && plan.testSkipPatterns.length ? plan.testSkipPatterns : undefined,
  };
  if (plan.coverage) Object.assign(options, plan.coverage);
  for (const k of Object.keys(options)) if (options[k] === undefined) delete options[k];
  const stream = run(options);
  if (plan.isolation === 'none') {
    const nt = globalThis[Symbol.for('detjs.nodetest')];
    if (nt) nt.attachShared();
  }
  const results = { files: {}, failed: false, unmapped: 0 };
  const fileOf = (d) => (d && d.file ? path.relative(process.cwd(), path.resolve(d.file)).split(path.sep).join('/') : null);
  const slot = (f) => results.files[f] || (results.files[f] = { pass: 0, fail: 0, summary: null });
  stream.on('test:pass', (d) => { const f = fileOf(d); if (f) slot(f).pass++; });
  stream.on('test:fail', (d) => {
    if (d && d.todo) return;
    const f = fileOf(d);
    if (f) slot(f).fail++; else results.unmapped++;
  });
  stream.on('test:summary', (d) => {
    if (!d.success) { process.exitCode = 1; results.failed = true; }
    const f = fileOf(d);
    if (f) slot(f).summary = Boolean(d.success);
  });
  const reporters = plan.reporters.length ? plan.reporters : [plan.defaultReporter];
  const dests = plan.destinations.length ? plan.destinations : reporters.map(() => 'stdout');
  if (dests.length !== reporters.length) throw new Error('detjs: --test-reporter must match the number of --test-reporter-destination');
  for (let i = 0; i < reporters.length; i++) {
    const rep = await reporterOf(reporters[i]);
    stream.compose(rep).pipe(destinationOf(dests[i]));
  }
  process.on('exit', () => {
    try { fs.writeFileSync(plan.results, JSON.stringify(results)); } catch { /* the main process treats it as failed */ }
  });
}

main().catch((e) => {
  process.stderr.write(`${e && e.stack ? e.stack : e}\n`);
  process.exitCode = 2;
});
