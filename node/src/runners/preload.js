'use strict';
// Preload of the runner shells (`--require` through NODE_OPTIONS, set by src/runners/common.js). It runs in every
// Node process and worker thread started below the runner, and decides by DETJS_RUNNER / DETJS_RUNNER_ROLE what this
// process is: the runner's main process ('runner'), a listing ('list'), a test process ('child' / 'single'), or
// anything else (a process a test started: 'nested', left alone).
const role = process.env.DETJS_RUNNER_ROLE;
const name = process.env.DETJS_RUNNER;
const ADAPTERS = {
  tap: './tap',
  ava: './ava',
  jasmine: './jasmine',
  uvu: './uvu',
};
if (role && name && ADAPTERS[name] && role !== 'nested') {
  try {
    require(ADAPTERS[name]).preload(role);
  } catch (e) {
    process.stderr.write(`detjs: ${name} preload failed: ${e && e.stack}\n`);
    process.exitCode = 1;
    throw e;
  }
}
