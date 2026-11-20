// Preload of every `deno test` process that `detjs deno-test --det` starts (`--preload`): loads the CommonJS setup
// (src/runners/deno-setup.js) with Deno's Node compatibility, so that the shared detjs modules and native core are
// the same ones Node, Vitest, Jest and Bun use.
import { createRequire } from 'node:module';

// one process for every file (DETJS_FILES): each isolate's set-up starts a detjs segment of the permission audit log
// (closed by DETJS_AUDIT_START in the set-up), which src/runners/deno.js auditCheck leaves out
if (globalThis.Deno && Deno.env.get('DETJS_CACHE') === '1') { try { Deno.env.get('DETJS_AUDIT_SETUP'); } catch { /* no env permission */ } }
const require = createRequire(import.meta.url);
require('./deno-setup.js');
