'use strict';
// `detjs mocha` driver: Mocha's own command line (lib/cli/cli.js) with the options detjs merged and adjusted
// (src/mocha/cli.js), in a process started with the user's node flags after detjs' preload (src/mocha/preload.js).
const fs = require('node:fs');
const path = require('node:path');

const plan = JSON.parse(fs.readFileSync(process.env.DETJS_MO_PLAN, 'utf8'));
require(path.join(plan.mochaDir, 'lib', 'cli', 'cli.js')).main([], plan.mochaArgs);
