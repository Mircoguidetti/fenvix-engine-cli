'use strict';
// Programmatic entry of the npm package `fenvix` (require('fenvix')): the version, the platform check and,
// on first use, the native core. The test-runner shells are the `fenvix` / `detjs` commands (bin/).
const { platformTriple, SUPPORTED } = require('./platform');

module.exports = {
  version: require('../package.json').version,
  platformTriple,
  SUPPORTED,
  get native() { return require('./native'); },
};
