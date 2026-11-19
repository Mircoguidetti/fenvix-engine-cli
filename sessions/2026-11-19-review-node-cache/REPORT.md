FIX 9

# Review r021: skip with proof for JavaScript / TypeScript (`detjs --det-cache`)

Target: `claude/node-cache-proof` at 495f858 (report `sessions/2026-11-18-node-cache-proof/REPORT.md`, design
`docs/NODE-CACHE.md`). Reviewer branch: `claude/review-r021`. Environment: Node 22.23.5 (the walks' workflow uses
Node 22 too), Vitest 5.1.0, Jest 30.5.2, native core built from the target (`node scripts/build.js`).

## Verdict

**FIX 9.** Eight independent ways to make the cache reuse a result it should not, each shown by a test that passes
on run 1, is reused on run 2, then fails in a fresh run after one input changes while the cached run still reuses
the stale pass. Most of them reproduce on both Vitest and Jest. One more finding is about the report's labels:
overhead and runtime-identity figures that understate what was measured.

The "0 wrong in 449,270" measurement is correct as a count (re-derived below). But it only shows that these five
repositories, over these transitions, did not hit a hole. It does not show the cache is sound. The holes below are
ordinary test idioms: `statSync().size`, `readdirSync(dir, { recursive: true })`, `fs.cpSync` of a fixture,
`import.meta.glob`, `vi.mock` with a `__mocks__` file, and an optional `import()` in a `try` block.

## Findings (each has a failing test on this branch)

Tests: `node/test/review-r021.test.js`. Every case runs: record (passes), reuse (the file must be reused, otherwise the
case proves nothing), change one input, fresh run without cache (must fail), cached run (must not reuse and must have
the fresh run's exit status). Tests named `F<n>` fail on `claude/node-cache-proof`; tests named `held:` are attacks
that did not get through and pass there. Run: `cd node && node --test --test-concurrency=1 test/review-r021.test.js`.

| # | input that is not keyed | test(s) | Vitest | Jest |
|---|---|---|---|---|
| F1 | metadata returned by `stat*`/`lstat*`/`realpath*`, beyond the kind | F1a size, F1b `realpath` of a retargeted link, F1c `lstat().isSymbolicLink()` | wrong reuse | wrong reuse |
| F2 | listings beyond the top-level names: `readdir(..., { recursive: true })`, `withFileTypes` | F2a, F2b | wrong reuse | wrong reuse |
| F3 | content read by Node APIs that are not wrapped: `fs.openAsBlob`, `process.loadEnvFile`, `node:sqlite` | F3a, F3b, F3c | wrong reuse (3) | wrong reuse (F3a, F3c; F3b n/a) |
| F4 | `fs.cp`/`cpSync`: source keyed by its kind only; the copy is then the test's own output | F4 | wrong reuse | wrong reuse |
| F5 | failed module resolution: an optional module loaded in `try { await import() / require() } catch {}` appears | F5 | wrong reuse | wrong reuse |
| F6 | `import.meta.glob`: a new file matching the pattern | F6 | wrong reuse | — |
| F7 | `__mocks__` discovery: `vi.mock(path)` (Vitest), root `__mocks__/<package>.js` (Jest, applied without `jest.mock`) | F7a, F7b | wrong reuse | wrong reuse |
| F8 | a directory outside the project read through a library on the `INFRA` list without a project frame on the stack (async `tinyglobby`) | F8 | wrong reuse | wrong reuse |
| F9 | report labels: capture overhead and runtime-identity size understate the measured rows | `harness/node_cache/test_review_r021_labels.py` | — | — |

### F1: `stat`, `lstat` and `realpath` are keyed by the kind only

`capture.js` maps `exists*`, `access*`, `stat*`, `lstat*` and `realpath*` to `read(p, 's')`, and `s:` is
`stat_kind` (`file`/`dir`/`other`/`missing`, following links). A test that uses anything else those calls return
depends on things that are not keyed. That covers size, mtime, mode, the link-ness `lstat` reports and the path
`realpath` resolves to.
* F1a: `expect(fs.statSync('data/blob.bin').size).toBe(3)`; the file grows by one byte, so the kind is still `file`
  and the result is reused.
* F1b: `path.basename(fs.realpathSync('data/current'))`; the link is retargeted from `one.txt` to `two.txt`, so the
  kind is still `file` and the result is reused.
* F1c: `fs.lstatSync('data/entry').isSymbolicLink()`; the link is replaced by a regular file (`stat_kind` follows the
  link), so the result is reused.

Fix direction: key `lstat`/`realpath` like `readlink` (the `l:` kind, along the whole chain for `realpath`). For
`stat`, either key the fields a test can see (size, mode, type; mtime only if the epoch policy allows it) or make
`stat` a content dependency (`f:`) for files. This is a design question for the shared core: the Python side uses the
same `s:` kind.

### F2: listings key only the top-level names

`listing_digest` hashes the sorted names of one directory.
* F2a: `readdirSync('fixtures/cases', { recursive: true })`; a new `a/two.json` does not change the top-level names,
  so the result is reused. Fixture-driven tests are written exactly like this.
* F2b: `readdirSync(dir, { withFileTypes: true }).filter((e) => e.isFile())`; `item` changes from a file to a
  directory with the same name, so the result is reused.

Fix direction: record `recursive` listings as one listing per directory walked (or a tree digest). For
`withFileTypes`, and for `opendir` whose `Dirent`s carry types, put the entry type in the digest (a new kind, or
`d:` over `name\0type`).

### F3: content reads through APIs that bypass the wrapped `fs` functions

* F3a `fs.openAsBlob(path)` (Node ≥ 19.8) is not wrapped: `(await fs.openAsBlob('data/msg.txt')).text()`. A content
  change is reused, on both runners.
* F3b `process.loadEnvFile(path)` reads the file natively and writes `process.env`. The variable it sets is then
  "read" and keyed against the environment *at session start*, where it does not exist, so changing the env file is
  reused (Vitest). Under Jest the test sees a per-file copy of `process.env`, so the idiom does not work there and the
  case is skipped.
* F3c `node:sqlite` `new DatabaseSync('fixtures/data.db')` reads the database in native code. A changed database is
  reused, on both runners.

The design lists "native code that reads files without going through Node" as a limit. These are Node's own APIs,
reachable from any test without an addon. Fix direction: wrap `openAsBlob` (`f:`) and `loadEnvFile` (`f:` on the
file, plus key the variables it sets by the file). Mark `node:sqlite` (`DatabaseSync`, `backup`) and any other
built-in that opens paths natively (check `fs.watch`/`statfs`) as not cacheable unless the path is keyed by content.

### F4: `fs.cp`/`cpSync` keys the source by kind; the copy is an output

`installFs` records `read(src, 's')` for `cp*` and `wrote(dst)`. A test that copies a fixture tree to a work
directory and reads the copy has two problems: its reads of the copy are reads of its own output (skipped), and the
source's content is never keyed. F4 copies `fixtures/tpl` to `out/<pid>`, reads `config.json` from the copy, and
`fixtures/tpl/config.json` changes. The result is reused on both runners, on Node 22.23.

Fix direction: for `cp`/`cpSync`, key the source like a recursive listing plus the content of every file copied
(`f:` per file). Equivalently, treat reads of a path written by `cp` as reads of its source.

### F5: a failed resolution leaves no input

A test that loads an optional module in a `try` block (`try { v = (await import('../src/optional.mjs')).v } catch {}`,
or `require` under Jest) records nothing while the module is missing. Vite 8 resolves in native code, and
jest-resolve's probes are not seen (see F7). Adding `src/optional.mjs` changes the fresh outcome, but the result is
reused on both runners. This contradicts the design's limit note ("a test that reads an input only in a branch it
did not take last time is covered: the branch condition's inputs changed first"): here the branch condition is
whether the module exists, and that is not an input. The stem listing (`g:`) is recorded only for modules that were
loaded.

Fix direction: record failed resolutions. Vitest: the module runner's `fetchModule`/resolve RPC fails with the
specifier and the importer; key the stem listing of the resolved target directory (and, for bare specifiers, the
`node_modules` lookup chain, already in the runtime identity). Jest: wrap `Resolver.resolveModule` failures the
same way. Until then, a file whose run raised a resolution error that was caught cannot be told apart, so the only
safe option is to make any failed dynamic `import()`/`require()` in a test process mark that test as uncacheable.

### F6: `import.meta.glob` matches are not keyed

`import.meta.glob('../fixtures/cases/*.json', { eager: true })` is expanded by Vite in the main process, through
tinyglobby, which is on the `INFRA` list. Only the matched modules enter the module graph. The test module is keyed
by its source bytes, not by its transformed output, so a new file matching the glob is reused (F6). The same applies
to any Vite transform whose output depends on a directory listing.

Fix direction: for every module whose transform used `import.meta.glob`, key the listing of each glob base directory
(recursively for `**`). Alternatively, key the test modules by their transformed code as well as their source.

### F7: `__mocks__` discovery is not keyed

* F7a Vitest: `vi.mock('../src/dep.mjs')` without a factory automocks, unless `src/__mocks__/dep.mjs` exists.
  `@vitest/mocker/redirect` (`findMockRedirect`) runs `const { existsSync, readdirSync, statSync } = fs` when the
  module loads, in the worker, *before* detjs installs its wrappers. Its probes are invisible (this is the
  documented "references taken before the capture is installed" limit, but it decides mocks for every `vi.mock`).
  Adding the `__mocks__` file is reused.
* F7b Jest: a root `__mocks__/<package>.js` for an installed package is applied **without** any `jest.mock` call
  (Jest's documented behaviour, used by React Native-style repositories). Jest finds it through the haste map in the
  main process, and that crawl is not recorded. The package itself is under `node_modules` (the runtime identity),
  so nothing recorded for the test changes when the mock file appears. The result is reused.
* Held: `jest.mock('../src/dep.js')` with an adjacent `__mocks__/dep.js` added *is* caught (Jest test, `held:`).

Fix direction: key the `__mocks__` directories the runner consults. For Vitest, the `existsSync`/`readdirSync`
results of `findMockRedirect` (wrap `@vitest/mocker/redirect`'s `fs` reference, or key the listing of
`dirname(mock)/__mocks__` and `<root>/__mocks__/<dir>` for every `vi.mock` recorded). For Jest, key the listing of
every root `__mocks__` directory in the haste map as a global input (the mocks map is global configuration).

### F8: reads outside the project are dropped when only `INFRA` frames are on the stack

`Capture.read` drops an `outside` read unless `caller()` finds a project frame. `INFRA` lists general-purpose
libraries that tests also use directly (tinyglobby, fdir, fast-glob, picomatch, micromatch, chokidar, graceful-fs,
resolve, …). After an `await` or a callback inside such a library, the test's frame is no longer on the stack. F8
uses `await glob(['*.txt'], { cwd: <directory outside the project> })`, then adds a file there. The result is reused
on both runners. (Reads inside the root are recorded whatever the caller, so the same idiom on a project directory
is caught; the `held:` `fs.globSync` case passes.)

Fix direction: in test processes, do not filter by caller at all (record every `outside` read; the runner's own
outside reads happen in the main process). Alternatively, classify by the module that *started* the operation (the
async context at the test's call) rather than by the synchronous stack.

### F9: report labels

Headline numbers re-derived from `harness/node_cache/results/` with `aggregate.py` (run on a copy, nothing written):

| claim | re-derived | |
|---|---|---|
| docusaurus 88% / 73% (r1, 50), Nx 26% / 56% | 88% / 73%, Nx 26% / 56% | ok |
| vue-core 26% / 32% (r1, 50), Nx 28% / 29% | 26% / 32%, 28% / 29% | ok |
| TanStack Query 91% / 61% (r5, 50), Nx 92% / 69% | 91% / 61%, 92% / 69% | ok |
| React Native 0% / 1% (9), Lexical 0% / 0% (19) | 0% / 1%, 0% / 0% | ok |
| 0 wrong in 449,270 verified reuses, five repositories | 132,108 + 85,112 + 22,574 + 50,961 (r1) + 158,515 (r5) = 449,270, 0 wrong, 0 flaky | ok, see note |
| docusaurus "median on the other 43: 89%"; TanStack r5 transitions 34/35 at 95% | 89.3%; 95.1% / 95.2% | ok |
| wall: docusaurus 18 s vs 88 s (0.20), vue-core 25 s vs 64 s (0.38), TanStack r5 44 s vs 149 s (0.29) | same | ok |
| capture overhead "+6% (vue-core) to +13% (docusaurus) … TanStack +8–11%" | docusaurus up to **+13.9%** (r1 commit 10); TanStack **+6.7% to +16.4%** (r4 commit 0; r4 commit 44 and r5 commit 10) | **understated** |
| runtime identity "up to 108,610 installed files / 1.6 GB" | **220,327 files / 3.47 GB** (TanStack Query, r4/r5 commit 44; 171,316 / 2.72 GB at commit 0) | **understated** |

The overhead table in the report shows three of the eight TanStack rows (+7%, +11%, +11%). The rows it leaves out are
+11.2%, +14.1%, +16.4% (r4) and +10.0%, +16.4%, +14.6% (r5). `test_review_r021_labels.py` checks both statements
against every measured row and fails on the target.

Smaller label notes (no test):
* "Verified reuses" counts file manifests as well as tests: 18,241 of the 449,270 are file-level entries, so
  431,029 are test results. Each one is compared by outcome only (`passed`/`failed`/`skipped`), so a reused `skipped`
  test always "verifies".
* React Native transition 36 is listed as "one dependency bump", but its recorded miss reason is `config`, not
  `runtime` (the other four are `runtime`). Most likely a root `package.json` change; the reason should be named as
  measured.
* Serial Level 0 versus the project's own command: "1.7–2.1×" is 1.65–2.15× in the rows (TanStack r5 commit 0:
  1.65; docusaurus r3: 2.13–2.15; vue-core r3 commit 50: 2.12).

## Attacks that did not get through (`held:` tests and manual checks)

* A file read in `afterAll` after the last test (`held:`, both runners): the file manifest covers it.
* `fs.globSync` over a project directory (`held:`, both runners).
* A Vite plugin from a workspace package linked into `node_modules` (`node_modules/x -> ../packages/x`), whose
  transform changes (`held:`): it is caught. Note that Vitest 5's own module cache (`node_modules/.vitest-cache`)
  serves the *stale* transform to a fresh run as well. That is not detjs's decision, but anyone comparing "fresh" runs
  in that setup must clear it, so the test does.
* `import.meta.env` from an `envDir` below the root (`held:`).
* `jest.mock` with an adjacent `__mocks__` file (`held:`).
* An environment variable read by an installed library in a promise callback under Jest `runInBand` (`held:`).
* Manual checks: `--no-isolate` and `--pool=vmThreads` are not cached; an environment read under `--pool=threads`
  is keyed (changing the variable reruns the file).

Not attacked here, for lack of time: native addons that link project shared libraries; `tsconfig` `extends` to a
file above the root; Jest custom transformers (Jest's own transform cache does not key the transformer source, which
needs care in any comparison). From reading `runtime-id.js` (untested): `nodeModulesDirs` silently stops after
20,000 directories and skips dot directories. A `node_modules` under `.storybook/`, or beyond that limit, would then
be in neither the runtime identity nor the per-test log, because `where()` skips every `/node_modules/` path in the
root. Worth a test.

## Suites run (this container, Node 22.23.5)

* `node/test/cache.test.js`: **45 of 45 pass** (Vitest and Jest).
* `node/test/{controls,jsdom,projects,regressions,unchanged}.test.js`: 16 + 1 + 1 + 7 + 2 = **27 of 27 pass**.
* `node/test/review-r021.test.js` (this review): 33 cases, **24 fail, 8 pass, 1 skipped** on the target. All 24
  failures are the `WRONG REUSE` assertion: no precondition failed, so each change made the fresh run fail and the
  file had been reused before it. The 8 passes are the `held:` cases; the skip is F3b under Jest.
* Rust: `cargo test --workspace --exclude detpy-py`: **56 of 56 pass**.
* Python (`tests/test_proofcache.py`, `test_shared_cache.py`, `test_review_r008*.py`, `test_runtime_id.py`, editable
  build of the target): **77 passed, 1 skipped, 1 failed**. The failure is
  `test_finished_startup_process_that_left_a_daemon_is_not_ignored`, which the report says also fails on
  `origin/claude/shared-cache` in its container (not re-checked here).
* `harness/node_cache/test_review_r021_labels.py`: 2 of 2 fail on the target (F9).
