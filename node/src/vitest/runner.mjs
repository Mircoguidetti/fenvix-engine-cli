// Vitest custom runner used under --det (set by `detjs vitest`).
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const shell = require('./shell.js');

export default shell.makeRunner(await shell.loadBaseRunner());
