'use strict';
// detjs uvu: control tests and wrong-reuse tests (shared cases: test/runner-b-cases.js; uvu-specific cases below).
const { defineRunnerSuite } = require('./runner-b-cases');

defineRunnerSuite('uvu', require('./runner-b-specific').uvu);
