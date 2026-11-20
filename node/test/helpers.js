'use strict';
// Fixture projects for the shell tests: the same test bodies are written for
// Vitest (ESM) and Jest (CommonJS) and run through bin/detjs.js.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const NODE_DIR = path.resolve(__dirname, '..');
const BIN = path.join(NODE_DIR, 'bin', 'detjs.js');
const TMP = path.join(__dirname, '.tmp');
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');

const HEADER = {
  vitest: [
    "import { test, expect, describe, beforeAll, afterAll, vi } from 'vitest';",
    "import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http'; import https from 'node:https';",
    "import nodeCrypto from 'node:crypto'; import { setTimeout as sleepP } from 'node:timers/promises';",
    "import golden from '../golden.cjs';",
    "const fake = vi; import os from 'node:os';",
  ].join('\n'),
  jest: [
    "const fs = require('node:fs'); const path = require('node:path'); const http = require('node:http'); const https = require('node:https');",
    "const nodeCrypto = require('node:crypto'); const { setTimeout: sleepP } = require('node:timers/promises');",
    "const golden = require('../golden.cjs');",
    "const fake = jest; const os = require('node:os');",
  ].join('\n'),
};

// golden(name, value): the first run stores the value, later runs compare.
const GOLDEN = `'use strict';
const fs = require('node:fs');
const path = require('node:path');
module.exports = function golden(name, value) {
  const file = path.join(__dirname, 'golden', name + '.json');
  const text = JSON.stringify(value);
  if (!fs.existsSync(file)) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
    return;
  }
  const want = fs.readFileSync(file, 'utf8');
  if (want !== text) throw new Error('golden ' + name + ': expected ' + want + ' got ' + text);
};
`;

const EXT = { vitest: '.test.mjs', jest: '.test.js' };

/**
 * Create a fixture project. `files`: {name: body}; `config`: runner config
 * additions ({vitest: {...}, jest: {...}}).
 */
function project(runner, name, files, config = {}) {
  const dir = path.join(TMP, runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `fixture-${name}`, private: true }));
  fs.writeFileSync(path.join(dir, 'golden.cjs'), GOLDEN);
  if (runner === 'vitest') {
    const cfg = { include: ['tests/**/*.test.mjs'], ...(config.vitest || {}) };
    fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), `export default { test: ${JSON.stringify(cfg)} };\n`);
  } else {
    const cfg = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', ...(config.jest || {}) };
    fs.writeFileSync(path.join(dir, 'jest.config.js'), `module.exports = ${JSON.stringify(cfg)};\n`);
  }
  for (const [file, body] of Object.entries(files)) {
    fs.writeFileSync(path.join(dir, 'tests', file + EXT[runner]), `${HEADER[runner]}\n${body}\n`);
  }
  return dir;
}

/** Run the fixture; returns {status, outcomes: {fullName: status}, stdout, trace}. */
function run(runner, dir, args = [], { env = {} } = {}) {
  const out = path.join(dir, 'out.json');
  fs.rmSync(out, { force: true });
  // Jest: a fresh cache directory per run, otherwise cached timings make Jest
  // run small suites in band and the parallel baseline would not be parallel.
  const report = runner === 'vitest' ? ['--reporter=json', `--outputFile=${out}`]
    : ['--json', `--outputFile=${out}`, `--cacheDirectory=${path.join(dir, '.jest-cache', String(Date.now()) + Math.random())}`];
  const childEnv = { ...process.env, ...env };
  delete childEnv.CI;
  delete childEnv.GITHUB_ACTIONS;
  delete childEnv.DETJS;
  delete childEnv.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, runner, ...(runner === 'vitest' ? ['run'] : []), ...args, ...report],
    { cwd: dir, encoding: 'utf8', env: childEnv, timeout: 120000 });
  const outcomes = {};
  if (fs.existsSync(out)) {
    const j = JSON.parse(fs.readFileSync(out, 'utf8'));
    for (const f of j.testResults || []) {
      for (const a of f.assertionResults || []) {
        outcomes[[path.basename(f.name), ...a.ancestorTitles, a.title].join(' > ')] = a.status;
      }
    }
  }
  const tracePath = path.join(dir, '.detjs', 'trace.jsonl');
  const trace = args.includes('--det') && fs.existsSync(tracePath) ? readTrace(tracePath) : null;
  return { status: r.status, outcomes, stdout: r.stdout, stderr: r.stderr, trace, tracePath };
}

function readTrace(file) {
  const lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  return { header: lines[0], tests: lines.filter((l) => l.type === 'test'), footer: lines.find((l) => l.type === 'footer') };
}

function failed(r) {
  return Object.entries(r.outcomes).filter(([, s]) => s === 'failed').map(([k]) => k);
}

function resetGolden(dir) {
  fs.rmSync(path.join(dir, 'golden'), { recursive: true, force: true });
}

module.exports = { project, run, failed, resetGolden, readTrace, RUNNERS, TMP, NODE_DIR, BIN };
