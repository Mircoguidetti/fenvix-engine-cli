// Preload of every `deno test` process that `detjs deno-test --det` starts (`--preload`): loads the CommonJS setup
// (src/runners/deno-setup.js) with Deno's Node compatibility, so that the shared detjs modules and native core are
// the same ones Node, Vitest, Jest and Bun use.
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
require('./deno-setup.js');
