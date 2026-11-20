'use strict';
// Loads the detpy-core Node bindings (crates/detpy-node).
//
// Search order: $DETJS_NATIVE, node/detjs.<platform>-<arch>.node (the engine artifact and the runner image; a
// checkout after scripts/build.js), then the cargo target directory of a checkout.
//
// The engine runs on Linux x86_64 with glibc 2.28+ (our machines). Any other platform stops here with one sentence
// naming the supported one (Alpine/musl, older glibc, other OS or CPU; audit G-0240, G-0442..G-0446), never with a
// raw loader error.
const fs = require('node:fs');
const path = require('node:path');

const { platformTriple, SUPPORTED } = require('./platform');

function candidates() {
  const here = path.resolve(__dirname, '..');
  const out = [];
  if (process.env.DETJS_NATIVE) out.push(process.env.DETJS_NATIVE);
  const { triple, problem } = platformTriple();
  out.push(path.join(here, `detjs.${process.platform}-${process.arch}.node`));
  for (const profile of ['release', 'debug']) {
    const lib = process.platform === 'win32' ? 'detpy_node.dll'
      : process.platform === 'darwin' ? 'libdetpy_node.dylib' : 'libdetpy_node.so';
    out.push(path.join(here, '..', 'target', profile, lib));
  }
  return { list: out, triple, problem };
}

function load() {
  const tried = [];
  const { list, triple, problem } = candidates();
  for (const p of list) {
    if (!fs.existsSync(p)) { tried.push(p); continue; }
    const m = { exports: {} };
    process.dlopen(m, p);
    m.exports.__path = p;
    return m.exports;
  }
  const supported = `supported: ${SUPPORTED.join(', ')} (Node 22, 24, 26)`;
  if (problem) throw new Error(`detjs: this platform has no native core: ${problem}; ${supported}`);
  throw new Error(`detjs: native core not found for ${triple} (install the engine artifact, or run \`npm run build\` `
    + `in node/ of a checkout); tried:\n  ${tried.join('\n  ')}`);
}

// One instance per process, shared by every realm (Jest runs each test file
// in its own vm context but loads native addons through the host require).
const KEY = Symbol.for('detjs.native');
module.exports = globalThis[KEY] || (globalThis[KEY] = load());
