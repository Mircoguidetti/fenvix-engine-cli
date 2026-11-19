# Mocha under detjs (`detjs mocha`)

Builder: node-a (all-runners). Code: `node/src/mocha/` (`cli.js` main process, `driver.js`, `preload.js`,
`child.js`, `mod.js`), the shared `node/src/fileproc.js`, and the shared layers (`session.js`, `controls.js`,
`cache/capture.js`, `cache/proof.js`). Mocha 11 (CommonJS) and Mocha 12 (`.cjs` + ES modules) are supported.

```bash
detjs mocha --det [mocha args]                          # deterministic (Level 0), Mocha's single process
detjs mocha --det --det-seed=7 [mocha args]             # reproducible shuffle of files, suites and tests
detjs mocha --det --det-cache=.detjs-cache [mocha args] # skip spec files with proof (one process per file)
detjs mocha --det --det-cache=DIR --det-cache-verify    # decide, run everything, compare
```

Without `--det` (and without `DETJS=1`) the project's mocha runs unchanged.

## Support: `--det` and `--det-cache` (skip with proof)

| feature | status |
|---|---|
| configuration: `.mocharc.{js,cjs,mjs,json,jsonc,yaml,yml}`, `package.json` `mocha`, `--config`, `MOCHA_OPTIONS`, CLI | merged by Mocha's own `loadOptions`; the merged options (minus output and file-selection keys) are the configuration digest, plus the rc files' bytes, `MOCHA_OPTIONS`, node flags, `NODE_OPTIONS` |
| spec files: positional specs / `spec`, `--extension`, `--recursive`, `--ignore` | collected with Mocha's own `collect-files`; order: sorted (fixed) or `native.shuffleIndices` with the seed; `--sort` superseded |
| `--file` | loaded first, in every process; part of the digest by content |
| `--require` (setup modules, root hook plugins `mochaHooks`), ESM and CJS | as Mocha does (`handleRequires`); project files in the digest by content and captured as code |
| global fixtures (`mochaGlobalSetup`/`mochaGlobalTeardown`) | `--det`: as Mocha (once, in the single process). `--det-cache`: the `--require` modules (and so the global fixtures) run in each file process, where they are captured (adversarial test: what the global setup reads is an input); they run once per spec file |
| `--parallel`, `--jobs` | off under `--det` (header note): files run one at a time |
| `--grep`, `--fgrep`, `--invert`, `--bail`, `--retries`, `--forbid-only`, `--forbid-pending`, `--check-leaks`, `--timeout`, `--ui`, `--delay`, `--dry-run`, ... | passed to Mocha; in the digest (a different selection never reuses a file) |
| `--exit` | honoured in single mode by Mocha; per-file processes exit after their results when set |
| node flags among Mocha's options (`--enable-source-maps`, `--import=tsx`, `--node-option`, `-n`, ...) | split from Mocha's options exactly as Mocha's `bin/mocha.js` does; they start the driver and every file process |
| TypeScript: `--require ts-node/register`, `--import tsx`, `--require @swc-node/register`, `--require esbuild-register`, native type stripping | supported (adversarial tests for each loader) |
| reporters | any reporter in single mode; per-file mode replays every file's events through Mocha's `ParallelBufferedRunner` (the same path as Mocha's `--parallel`), so reporters that Mocha refuses in parallel mode (`progress`, `markdown`, `json-stream`) may misbehave |
| `--watch` | refused under `--det` |
| `--fail-zero` with every file reused | the run passes (set off for that session only) |

## Hooks used (the runner glue)

* **Main process** (`cli.js`): Mocha's `loadOptions` and `collect-files` (the same merge and file list Mocha would
  use), order, configuration digest, `ProofSession.decide` before any file runs; then the driver.
* **Driver** (`driver.js` + `preload.js`, role `driver`): Mocha's own CLI (`lib/cli/cli.js main([], options)`), started
  with the node flags Mocha's bin would use, after detjs' preload. The preload replaces `this.files` in
  `Mocha#loadFiles(Async)` with the plan (ordered, reused files removed, `--file` files first).
  * `--det` (single mode): the driver is the test process. Each file is seeded when Mocha requires it
    (`pre-require`), the suite tree is shuffled with the seed (each suite's `tests` and `suites`, keyed by file and
    title path), and `Runner` events bracket every test: `test` begins it (before its `beforeEach` hooks); it ends
    when the next one begins or the run ends (its `afterEach` hooks inside); `pending` records skipped tests;
    retries keep their test. One trace part for the run (Mocha runs the top-level tests of every file before the
    suites, so files interleave).
  * `--det-cache` (per-file mode): the driver only reports. `Mocha#run` switches to Mocha's parallel runner and its
    worker pool is replaced by one fresh process per spec file, run one after the other in the plan's order
    (`child.js`: what Mocha's worker does for one file, with the serial-mode options: `--require` modules and root
    hooks, the `--file` files, the spec; no forced `forbidOnly`). Each file process installs Level 0 and the capture
    before any user module, writes its serialized events for the driver and its cache capture for detjs; a file's
    verdict = its failures, its process's exit status and its `fail` events.
* **Why one process per file under `--det-cache`**: Mocha loads every file into one process; skipping file A would
  change the context file B runs in (globals, module cache, `process.env`). Control test: `a.spec` sets a global
  that `b.spec` reads; `--det` passes, `--det-cache` fails `b sees a` and the count of changed outcomes is 1.

## What is refused or not cached, and why

* Every rule of the shared capture (docs/NODE-CACHE.md and docs/runners/node-test.md).
* Under `--det-cache`, `--require` modules, root hooks and global fixtures run once per spec file (each file has its own process): a setup that binds a fixed port works (one file at a time), one that expects to run once per run sees N runs.
* Order of tests differs between `--det` (single process: top-level tests of all files first) and `--det-cache`
  (per file): the same tests and fingerprints (control test), another order digest.
* Reporters that need the live runner (Mocha refuses them with `--parallel`) under `--det-cache`.

Tests: `node/test/runner-mocha.test.js` (control + adversarial); results in docs/runners/BUILD-node-a.md.
