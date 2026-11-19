'use strict';
// Review R-032: the nested-package.json absent input (N3 in review-r032.test.js) and a config file appearing, under
// tap, AVA, Jasmine and uvu (shared helpers of runner-b-cases.js).
// Run: cd node && node --test --test-concurrency=1 test/review-r032-runners-b.test.js
const { test, describe } = require('node:test');
const B = require('./runner-b-cases');

const T = { timeout: 900000 };
for (const runner of ['tap', 'ava', 'jasmine', 'uvu']) {
  const F = (n) => B.RUNNERS[runner].file(n);
  describe(`${runner}: review r032`, () => {
    test('N3 a nested package.json with "type": "module" appears (lib/x.js changes module format)', T, () => {
      const dir = B.fixture(runner, 'r032-type-appears', {
        'lib/x.js': 'exports.v = 1;\n',
        ...B.tfile(runner, 'nt', "test('nt', () => { expect(require(path.resolve('lib/x.js')).v).toBe(1); });"),
      });
      B.noWrongReuse(runner, dir, F('nt'), { 'lib/package.json': JSON.stringify({ type: 'module' }) });
    });
    test('N3b a workspace package.json "main" retargeted (both files exist)', T, () => {
      const dir = B.fixture(runner, 'r032-main', {
        'lib/package.json': JSON.stringify({ name: 'lib', main: 'a.js' }),
        'lib/a.js': 'exports.v = 1;\n', 'lib/b.js': 'exports.v = 2;\n',
        ...B.tfile(runner, 'mn', "test('mn', () => { expect(require(path.resolve('lib')).v).toBe(1); });"),
      });
      B.noWrongReuse(runner, dir, F('mn'), { 'lib/package.json': JSON.stringify({ name: 'lib', main: 'b.js' }) });
    });
  });
}
