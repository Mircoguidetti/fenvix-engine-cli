'use strict';
// detjs jasmine: control tests and wrong-reuse tests (shared cases: test/runner-b-cases.js; jasmine-specific cases below).
const { defineRunnerSuite } = require('./runner-b-cases');

defineRunnerSuite('jasmine', require('./runner-b-specific').jasmine);
