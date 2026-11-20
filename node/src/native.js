'use strict';
// Loads the detpy-core Node bindings (crates/detpy-node).
//
// Installed from npm, the addon is in the platform package the `fenvix` package lists as an optional dependency
// (npm installs only the one matching os/cpu/libc): @fenvix/linux-x64-gnu, @fenvix/linux-arm64-gnu,
// @fenvix/darwin-arm64. Search order: $DETJS_NATIVE, that package, node/detjs.<platform>-<arch>.node (a checkout,
// copied by scripts/build.js; the runner image), then the cargo target directory of a checkout.
//
// Platforms outside that list stop here with one sentence naming the supported ones (Alpine/musl, glibc older
// than 2.28, Windows, macOS Intel; audit G-0240, G-0442..G-0446), never with a raw loader error.
const fs = require('node:fs');
const path = require('node:path');

const { platformTriple, SUPPORTED } = require('./platform');

function packaged(triple) {
  try {
    return require.resolve(`@fenvix/${triple}/fenvix.${triple}.node`);
  } catch {
    return null;
  }
}

function candidates() {
  const here = path.resolve(__dirname, '..');
  const out = [];
  if (process.env.DETJS_NATIVE) out.push(process.env.DETJS_NATIVE);
  const { triple, problem } = platformTriple();
  if (!problem) {
    const p = packaged(triple);
    out.push(p || `@fenvix/${triple} (not installed)`);
  }
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
  throw new Error(`detjs: native core not found: the optional package @fenvix/${triple} is missing `
    + `(reinstall with optional dependencies: npm install fenvix --include=optional); tried:\n  ${tried.join('\n  ')}`);
}

// One instance per process, shared by every realm (Jest runs each test file
// in its own vm context but loads native addons through the host require).
const KEY = Symbol.for('detjs.native');
module.exports = globalThis[KEY] || (globalThis[KEY] = load());
