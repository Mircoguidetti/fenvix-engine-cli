'use strict';
// Loads the detpy-core Node bindings (crates/detpy-node).
// Search order: $DETJS_NATIVE, node/detjs.<platform>-<arch>.node (copied by
// scripts/build.js), then the cargo target directory of this checkout.
const fs = require('node:fs');
const path = require('node:path');

function candidates() {
  const here = path.resolve(__dirname, '..');
  const out = [];
  if (process.env.DETJS_NATIVE) out.push(process.env.DETJS_NATIVE);
  out.push(path.join(here, `detjs.${process.platform}-${process.arch}.node`));
  for (const profile of ['release', 'debug']) {
    const lib = process.platform === 'win32' ? 'detpy_node.dll'
      : process.platform === 'darwin' ? 'libdetpy_node.dylib' : 'libdetpy_node.so';
    out.push(path.join(here, '..', 'target', profile, lib));
  }
  return out;
}

function load() {
  const tried = [];
  for (const p of candidates()) {
    if (!fs.existsSync(p)) { tried.push(p); continue; }
    const m = { exports: {} };
    process.dlopen(m, p);
    m.exports.__path = p;
    return m.exports;
  }
  throw new Error(`detjs: native core not found (run \`npm run build\` in node/); tried:\n  ${tried.join('\n  ')}`);
}

// One instance per process, shared by every realm (Jest runs each test file
// in its own vm context but loads native addons through the host require).
const KEY = Symbol.for('detjs.native');
module.exports = globalThis[KEY] || (globalThis[KEY] = load());
