'use strict';
// node:test for test files under `detjs node-test --det` (require): see facade.js.
const real = typeof process.getBuiltinModule === 'function' ? process.getBuiltinModule('node:test') : require('node:test');
const nt = globalThis[Symbol.for('detjs.nodetest')];
module.exports = nt && nt.facade ? nt.facade(real) : real;
