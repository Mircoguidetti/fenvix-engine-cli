'use strict';
// detjs ava: control tests and wrong-reuse tests (shared cases: test/runner-b-cases.js; ava-specific cases below).
const { defineRunnerSuite } = require('./runner-b-cases');

defineRunnerSuite('ava', require('./runner-b-specific').ava);
