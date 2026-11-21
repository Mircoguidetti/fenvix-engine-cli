'use strict';
/**
 * CI-volatile environment (design A, 2026-11-20), the same lists as detpy (python/detpy/_level0.py):
 *  - PINNED: set to fixed values under --det before the tests run (run and attempt ids, job and runner names, the
 *    host name); os.hostname() answers PINNED_HOSTNAME;
 *  - KEPT: values stay (paths that must exist, tokens a tool needs) but they are never run inputs;
 *  - FENVIX_VOLATILE_ENV=NAME,PREFIX*,... adds a project's own (a per-run output path).
 */
const PINNED = {
  GITHUB_RUN_ID: '0', GITHUB_RUN_NUMBER: '0', GITHUB_RUN_ATTEMPT: '1', GITHUB_JOB: 'fenvix',
  RUNNER_NAME: 'fenvix-runner', RUNNER_TRACKING_ID: 'fenvix', HOSTNAME: 'localhost',
};
const KEPT = [
  'RUNNER_TEMP', 'RUNNER_WORKSPACE', 'RUNNER_TOOL_CACHE', 'GITHUB_WORKSPACE', 'GITHUB_ENV', 'GITHUB_PATH',
  'GITHUB_OUTPUT', 'GITHUB_STATE', 'GITHUB_STEP_SUMMARY', 'GITHUB_EVENT_PATH', 'GITHUB_ACTION',
  'GITHUB_ACTION_PATH', 'GITHUB_ACTIONS_STEP_DEBUG', 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_RUNTIME_URL',
  'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL', 'ACTIONS_RESULTS_URL', 'ACTIONS_CACHE_URL',
  'ACTIONS_ORCHESTRATION_ID', 'TMPDIR', 'TEMP', 'TMP', 'PWD', 'OLDPWD', '_', 'SHLVL', 'INVOCATION_ID',
  'JOURNAL_STREAM', 'SSH_AUTH_SOCK', 'SSH_CLIENT', 'SSH_CONNECTION', 'SSH_TTY', 'TERM_SESSION_ID',
  'WINDOWID', 'XDG_SESSION_ID', 'XDG_RUNTIME_DIR', 'SYSTEMD_EXEC_PID', 'FENVIX_VOLATILE_ENV',
  'SUDO_USER', 'SUDO_UID', 'SUDO_GID', 'SUDO_COMMAND', 'SUDO_HOME',
];
const PINNED_HOSTNAME = 'localhost';
// the proxy variables (python/detpy/_level0.py PROXY_ENV): not inputs while the network is closed (session.runInputs)
const PROXY_ENV = new Set(['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy']);
// CPU count: CI runners differ (pool sizes, chunking, a test that prints it). Under --det os.cpus() has
// PINNED_CPUS entries and os.availableParallelism() answers PINNED_CPUS; the engine sizes its own work on the real
// machine (REAL, captured when this module loads).
const PINNED_CPUS = 2;
const os = require('node:os');
const REAL = { cpus: os.cpus, availableParallelism: os.availableParallelism };

function realParallelism() {
  return REAL.availableParallelism ? REAL.availableParallelism.call(os) : REAL.cpus.call(os).length;
}

function pinCpus(patcher) {
  patcher.set(os, 'cpus', () => {
    const r = REAL.cpus.call(os);
    return Array.from({ length: PINNED_CPUS }, (_, i) => r[i % Math.max(1, r.length)]).filter(Boolean);
  });
  if (REAL.availableParallelism) patcher.set(os, 'availableParallelism', () => PINNED_CPUS);
}
const ENGINE_PREFIXES = ['DETJS_', 'DETPY_', 'VITEST_', 'JEST_WORKER', 'PYTEST_XDIST_'];

function patterns() {
  const extra = String(process.env.FENVIX_VOLATILE_ENV || '').split(',').map((x) => x.trim()).filter(Boolean);
  const exact = new Set([...Object.keys(PINNED), ...KEPT, ...extra.filter((x) => !x.endsWith('*'))]);
  const prefixes = [...ENGINE_PREFIXES, ...extra.filter((x) => x.endsWith('*')).map((x) => x.slice(0, -1))];
  return { exact, prefixes };
}

function isVolatile(name, p = patterns()) {
  return p.exact.has(name) || p.prefixes.some((x) => name.startsWith(x));
}

/** Set the pinned variables that are present to their fixed values (children inherit them). */
function pinEnv() {
  const done = [];
  for (const [k, v] of Object.entries(PINNED)) {
    if (k in process.env && process.env[k] !== v) {
      process.env[k] = v;
      done.push(k);
    }
  }
  return done;
}

module.exports = { PINNED, KEPT, PINNED_HOSTNAME, PINNED_CPUS, PROXY_ENV, patterns, isVolatile, pinEnv, pinCpus, realParallelism };
