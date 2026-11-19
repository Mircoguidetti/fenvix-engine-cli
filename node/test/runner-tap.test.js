'use strict';
// detjs tap: control tests and wrong-reuse tests (shared cases: test/runner-b-cases.js; tap-specific cases below).
const { defineRunnerSuite } = require('./runner-b-cases');

defineRunnerSuite('tap', require('./runner-b-specific').tap);
