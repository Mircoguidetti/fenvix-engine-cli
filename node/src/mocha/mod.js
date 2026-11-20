'use strict';
// Mocha's internal modules across versions (11: CommonJS `.js`; 12: `.cjs` and ES modules, loaded with require()).
const fs = require('node:fs');
const path = require('node:path');

function load(dir, rel) {
  for (const ext of ['.cjs', '.js', '']) {
    const p = path.join(dir, ...rel.split('/')) + ext;
    if (ext === '' ? fs.existsSync(p) && fs.statSync(p).isFile() : fs.existsSync(p)) return require(p);
  }
  throw new Error(`detjs: mocha ${rel} not found in ${dir}`);
}

/** The Mocha class (the same module instance Mocha's own command line uses). */
function mochaClass(dir) {
  const m = load(dir, 'lib/mocha');
  return typeof m === 'function' ? m : (m.default || m);
}

module.exports = { load, mochaClass };
