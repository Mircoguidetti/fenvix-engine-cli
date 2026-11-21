// Vitest custom runner used under --det (set by `detjs vitest`).
import { createRequire } from 'node:module';

// detjs' own modules are loaded with the worker's own require (process.getBuiltinModule gives Node's real `module`):
// in the vm pools this file is evaluated inside each test file's vm context, whose `node:module` would evaluate a new
// copy of detjs in every context (audit G-0461)
const host = typeof process.getBuiltinModule === 'function' ? process.getBuiltinModule('node:module') : null;
const require = (host || { createRequire }).createRequire(import.meta.url);
const shell = require('./shell.js');

// Vitest's default runner class is imported from here, so that in the vm pools it is the context's own copy of Vitest;
// the realm of the test file is this module's global object (the vm context there, the worker's global elsewhere)
export default shell.makeRunner(await shell.loadBaseRunner((url) => import(url)), globalThis);
