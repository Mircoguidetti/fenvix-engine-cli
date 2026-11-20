'use strict';
// Build crates/detpy-node and copy the addon next to the package.
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const profile = process.argv.includes('--debug') ? 'debug' : 'release';
execFileSync('cargo', ['build', '-p', 'detpy-node', ...(profile === 'release' ? ['--release'] : [])],
  { cwd: root, stdio: 'inherit' });
const lib = process.platform === 'win32' ? 'detpy_node.dll'
  : process.platform === 'darwin' ? 'libdetpy_node.dylib' : 'libdetpy_node.so';
const dest = path.join(root, 'node', `detjs.${process.platform}-${process.arch}.node`);
fs.copyFileSync(path.join(root, 'target', profile, lib), dest);
console.log(`detjs: native core -> ${path.relative(process.cwd(), dest)}`);
