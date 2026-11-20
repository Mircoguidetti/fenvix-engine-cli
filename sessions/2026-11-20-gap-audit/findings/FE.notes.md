# FE: notes (front-end testing and the browser / L2 track)

Stopped early on the budget limit from the coordinator. Everything below is what I actually did; the section
"Not covered" lists what another session must still do. Scratch: /home/user/audit/work/FE (projects rv, rj, vv, pw,
common/ probe, optcopy = copy of build/opt with one debug line, gen/ = generator of FE.gaps.jsonl).
73 gaps written (FE-001..FE-073). All runs used `FENVIX_HOME=/home/user/audit/build/opt .../bin/fenvix node <runner>`.

## Not covered (hand-over list)

Part A (emulated DOM, release-1):
- Environments not run: Jest + `@happy-dom/jest-environment` (file rj/test/hd.test.js is written, never run);
  Jest per-file `@jest-environment` docblock under --det/--det-cache (rj/test/hd.test.js, rj/test/nodeenv.test.js
  written, not run under the cycle; only tinynode.test.js with the node docblock was run); Vitest
  `environmentMatchGlobs` (not tried); Vitest per-file pragma was run only for happy-dom/node under --det-cache
  (rv/test2/hd.test.jsx, nodeenv.test.js: recorded and reused 3 tests), not probed API by API.
- APIs not probed or inconclusive: CSS transitions/animations (jsdom has none; happy-dom has `element.animate` and
  `document.timeline` = present, behaviour under --det not tested); `XMLHttpRequest` external (async: "onerror
  status 0" in plain and --det, cannot tell blocked from failed; sync XHR in jsdom spawns a child process: the Jest
  run showed a real "getaddrinfo ENOTFOUND example.com" under --det, i.e. the sync-XHR child is outside the closed
  network, but I did not confirm it with a reachable host, so it is NOT listed as a gap); `window.localStorage`
  isolation between tests/files (only set/get); `BroadcastChannel` timing (only delivery); `structuredClone` (exists);
  network `--det-record`/replay from a DOM environment (never run); `--det-urandom` with WebSocket; env-var control
  (column 7), fs order (column 6) from DOM tests.
- Frameworks not built: Svelte 5, Angular (TestBed with Jest/Vitest; Karma+Jasmine), Solid, Preact, Next.js
  (`next/jest`), Nuxt test utils, Remix / React Router, Redux timing. React Query, SWR, Zustand, styled-components,
  emotion, fake-indexeddb, Suspense/lazy, useId, user-event with delay: ONE passing test each under --det x2 + verify
  ("covered by Level 0: 8") in rv/test/libs.test.jsx and rv|rj/test/button.test.jsx; no deeper timing cases.
  React 18 (rv) and React 19 (rj) both used; React concurrent scheduler internals not examined.
- Cache invalidation not tested: Jest `moduleNameMapper` (identity-obj-proxy, styleMock) and custom `transform`
  files (rj/test/svgTransform.js, rawTransform.js are written) because Jest+jsdom records nothing (FE-002); a Jest
  run with happy-dom or node environment would be needed. Vite plugins other than @vitejs/plugin-react / plugin-vue.
  Shared cache URL (column 19), `--det-cache-verify`.
- Snapshot/visual: DOM snapshots (`toMatchSnapshot`, inline) run and pass under --det in rv, rj, vv; obsolete/updated
  snapshot handling under the cache only observed (first run writes the .snap, second run is a miss, third reuses).
  `jest-image-snapshot` installed in rj, never run. Storybook test runner, Storybook vitest addon / portable stories,
  Chromatic-like flows, Web Test Runner, Karma: only `fenvix node <name>` => usage/exit 2; not installed or run.
- Vitest `vmThreads`/`vmForks`: READ only (FE-025).

Part B (e2e runners, release-1):
- Playwright: project work/FE/pw written and run PLAIN 6 times (flaky as designed). NOT run: the documented
  measurement hook `NODE_OPTIONS="--require <detjs>/src/register.js" DETJS=1 npx playwright test --workers=1`
  (so what it really does in a worker is READ from node/src/register.js only); Playwright `page.clock`, HAR,
  retries, shards, projects, trace viewer were not exercised (entries FE-035..FE-045 are READ: absence of code).
  The "measured only" number of docs/NODE.md J11 was not looked up in harness/node/results.
- Cypress, Puppeteer (+Jest/Mocha), WebdriverIO, TestCafe, Nightwatch, Selenium, Karma: command check only.

Part C (L2 browser lockstep): NOT DONE AT ALL except the diff sizes. Not read: branches
origin/claude/l2-browser-r2, origin/claude/l2-browser-r3, origin/claude/l2-browser-lockstep-ytoqnv (code under
tracks/l2-browser-r2, tracks/l2-browser-r3, tracks/l2-browser-lockstep, plus their changes to node/src, node/bin,
node/test, .github/workflows); reports fenvix-brain-cli/sessions/2026-11-18-l2-browser-r2, 2026-11-18-l2-browser-r3,
2026-11-19-l2-browser-lockstep; review 2026-11-18-review-l2-browser-r2 (R-011 findings still open?); prompts P-014,
P-019, P-030 ("Done means" targets versus reached numbers). Open questions for the next session: what was built
(CDP lockstep? virtual time budget? which language), study/harness versus shippable component, browsers covered,
apps/frameworks measured, server stacks (Node only?), databases/containers, every "not done"/UNKNOWN, and the
clean-checkout build + run of the lockstep harness on its smallest example (not attempted).

Part D (real browser vs emulated DOM): entries FE-060..FE-073 are for release-1 only; "is there any control or record
on the branches" was not checked for any of the 15 items. Real-browser facts come from one Vitest browser-mode run
(Chromium via @vitest/browser-playwright 5.1.1); Firefox/WebKit not run.

Matrix: every `not checked` cell in FE.matrix.md; columns 16 (culprit), 17 (dependency verdict), 19 (shared cache),
23 (overhead) for the three emulated-DOM rows.

## Could not check

- Whether the page of Vitest browser mode can reach the external network under --det: the test got "Failed to
  fetch" for https://example.com (the container has no direct route), so "network not closed in the page" rests on
  the code (no browser control) plus the clock/timer evidence, not on a successful external request.
- jsdom sync-XHR bypass of the closed network (see above): needs a reachable non-loopback host.
- macOS/Windows behaviour of anything front-end: not looked at.

## Evidence appendix (commands and trimmed real outputs)

Common helpers: work/FE/common/probe.{mjs,cjs} (one test that reads ~55 browser APIs and writes JSON),
cmp.js (plain vs det1 vs det2), cycle.sh (plain, --det x2, verify, --det-seed=7), cache.sh (--det --det-cache).
Raw logs: work/FE/{rv,rj,vv}/out/*.log, *.json; work/FE/pw/out-plain-N.log.

FE-A1 (FE-001) rv, vitest 3.2.7 + jsdom 31.0.1:
  `fenvix node vitest run test2/min.test.jsx --det --det-cache=$PWD/.cache-min` (twice)
  => "detjs cache: reused with proof 0 tests in 0 files (0 s recorded); ran 1 files; recorded 0 tests"
  .detjs/cache-summary.json not_cached_detail: "test2/min.test.jsx::pure dom": "reads a clock Level 0 does not
  virtualize: performance.timeOrigin" (same for all 5 tests and the file).
  Stack (optcopy with a debug print in capture.js `real`): Performance.get [as timeOrigin] capture.js:1773 <-
  installOwnProperties jsdom/lib/jsdom/browser/Window.js:276 <- createWindow <- new JSDOM <- vitest env setup.
  `npm pack jsdom@22.1.0|24.1.3|26.1.0`: Window.js has "timeOrigin: performance.timeOrigin + windowInitialized"
  at lines 356 / 386 / 384. With `// @vitest-environment happy-dom` in the same project: "recorded 3 tests", then
  "reused with proof 3 tests in 2 files".
FE-A2 (FE-002) rj, jest 29.7.0 + jsdom 20.0.3: `fenvix node jest test/puredom.test.js --det --det-cache=DIR` twice
  => "reused with proof 0 tests in 0 files; ran 1 files; recorded 0 tests ... not cached: reads a clock Level 0 does
  not virtualize 2". Stack: capture.js:1773 <- new Window jsdom/lib/jsdom/browser/Window.js:340 <- new JSDOM <-
  jest-environment-jsdom/build/index.js:65 <- node/src/jest/cli.js:202 <- jest-runner runTest.js:236.
FE-A3 (FE-003, FE-004) rj `fenvix node jest test/tiny --det`:
  tiny.test.js (jsdom): "WAIT2000 realDeltaMs 2004", "WAIT2000b realDeltaMs 2004";
  tinynode.test.js (`@jest-environment node`): "WAIT2000 realDeltaMs 8", "WAIT2000b realDeltaMs 4".
  probe: "setTimeout 5000" det1 {"virtualDelta":5000,"realDeltaMs":5006}; Vitest+jsdom: {"virtualDelta":5000,
  "realDeltaMs":2}. verify: "NOT-COVERED test/probe.test.js::probe [time] outcomes=passed,passed / runs 0 vs 1:
  event #23: setTimeout @ <abs>/probe.cjs:42 returned different values: "fire:5301007000" vs "schedule:1000000"".
FE-A4 (FE-005, FE-006) rj tiny.test.js FEAT line, jsdom file:
  plain {"setImmediate":"undefined","clearImmediate":"undefined","randomUUID":"undefined","perfMark":"undefined",
  "perfKeys":"","dateNative":true}
  --det {"setImmediate":"function","clearImmediate":"undefined","randomUUID":"function","perfMark":"undefined",
  "perfKeys":"timeOrigin,now","dateNative":false}
  (also visible: under --det `Date` is no longer native code and `performance` has own keys timeOrigin, now.)
FE-A5 (FE-007, FE-008, FE-009) rj probe (plain | det1 | det2):
  requestAnimationFrame det1 {"ts":[7579.385213,7599.171259,7615.392957],"perfNowBefore":6300.006,"perfNowAfter":
  6300.007,"realDeltaMs":56} | det2 {"ts":[7655.776415,7674.95813,7691.164527],...,"realDeltaMs":56}
  Event.timeStamp det1=1795164087918 det2=1795164099596; document.lastModified "11/20/2026 08:41:20" vs
  "11/20/2026 08:41:31"; File.lastModified same pair; performance.timeOrigin 1795164080300.7527 vs
  1795164091900.982. In Vitest+jsdom the same three are virtual (Event.timeStamp 1735689605350, lastModified
  "01/01/2025 00:00:00") and rAF is virtual and identical in both runs (ts 5316.67, 5333.34, 5350.01; 7 ms real).
FE-A6 (FE-010, FE-011) rv probe: "iframe realm Date/Math" det1 {"now":1795163786382,"sameDate":false,"random":
  0.9056004581911805,"perf":0.0039999} det2 {"now":1795163790944,"random":0.47685607889418025};
  "jsdom inner realm eval" det1 {"now":1795163786388,"random":0.118...,"sameDate":false} det2 {"now":1795163790946,
  "random":0.147...}. rj probe iframe: det1 {"now":1795164089150,"random":0.14331202995239,"perf":13.13} det2
  {"now":1795164100831,"random":0.6502025672026435,"perf":20.06}. happy-dom: "no iframe realm".
FE-A7 (FE-012) rv probe crypto.subtle.generateKey det1=[207,250,251,41] det2=[162,215,84,23] (Jest jsdom 20:
  crypto.subtle undefined).
FE-A8 (FE-013, FE-014) rv probe "MessageChannel vs setTimeout0 race x200": plain "M200" det1 "T1M199" det2 "M200".
  Trace ops of the probe test: setTimeout 524, setImmediate 202, Date.now 20, performance.now 11, setInterval 10,
  Date 6, net.connect 3, Math.random 1, crypto.getRandomValues 1, crypto.randomUUID 1, crypto.randomBytes 1.
  `fenvix node verify out/detjs1/trace.jsonl .detjs/trace.jsonl` => "covered by Level 0: 0 not covered: 1 /
  reasons: entropy=1 / NOT-COVERED test/probe.test.js::probe [entropy] ... event #39: crypto.randomBytes @
  <deps>/undici/lib/web/websocket/connection.js:64 returned different values: "16:faaa93..." vs "16:2fcdd3..."".
FE-A9 (FE-015) rv test/libs.test.jsx, msw 3.0.7, `setupServer(http.get('https://api.example.com/user', ...))`:
  plain: "✓ libs > msw fetch with delay() 168ms"; --det (both runs): "FAIL ... msw fetch with delay() / TypeError:
  fetch failed / Caused by: NetworkBlockedError: detjs: network access to api.example.com:443 blocked (Level 0
  closes the network ...) / blockSocket build/opt/node/src/network.js:242 / TLSSocket.connect network.js:277 /
  TLSSocket.connect node_modules/@mswjs/interceptors/src/interceptors/net/index.ts:221". Control: rv
  test2/msw2.test.js with msw 2.15.0 (alias msw2): fetch, https.get and XHR all pass plain, --det x2 (verify
  covered 3) and --det-seed=7. Note: "msw XHR" with msw 3 fails in the plain run too (not a detjs effect).
FE-A10 (FE-016, FE-017) rv: `TZ=Asia/Tokyo LANG=ja_JP.UTF-8 LC_ALL=ja_JP.UTF-8 fenvix node vitest run
  test/libs.test.jsx -t "tz and locale" --det` => TZLOC {"tz":"Asia/Tokyo","loc":"ja-JP","off":-540,"s":"2025/6/16
  0:06:40","nav":"en-US"}; "AssertionError: expected +0 to be 15"; without the variables: {"tz":"UTC","loc":"en-US",
  "off":0,"s":"6/15/2025, 3:06:40 PM"} and the test passes. (The cache identity does include tz and locale:
  cache-summary.json runtime_parts.tz / .locale; Level 0 itself does not pin them.)
FE-A11 (FE-018) rv, test3/buttonhd.test.jsx (happy-dom pragma), `--det --det-cache=.cache-bhd`:
  10/11 no change => reused 4; 12 css-module value => miss "code: src/Button.module.css (content)", 12b reused 4;
  13 class rename => miss, recorded; 13b restored to the content of 12 => miss "code: src/Button.module.css
  (content)"; 14 plain css => miss "code: src/plain.css (content)", 14b reused 4; 15 svg => miss "code: src/logo.svg
  (content)" (test fails: inlined data URI in the snapshot), 15b restored => "new: no recorded result"; 16 ?raw
  asset => miss "code: src/data.txt (content)", 16b restored => "new: no recorded result", 16c reused 4.
  So CSS modules, plain CSS, SVG, ?raw assets and the component ARE inputs of the key in Vitest (sound).
  vv (Vue SFC, vitest 5.1.1): 8 style block => miss "code: src/Counter.vue (content)"; 9 template => miss
  "data: src/Counter.vue (f)"; 10 svg => miss "code: src/logo.svg (content)"; restores => "new: no recorded result".
FE-A12 (FE-019, FE-020) vv probe: only DIFF rows between det1 and det2 are performance.timeOrigin and
  crypto.subtle.generateKey; everything else identical (Date 2025-01-01, rAF ts 6300.007/8/9, Event.timeStamp
  6300.011, setTimeout 5000 in 2 ms, happy-dom fetch external => "detjs: n[etwork access ... blocked]").
  verify => "NOT-COVERED test/probe.test.js::probe [time] ... event #73: setTimeout @ <abs>/probe.mjs:41 returned
  different values: "fire:8301023000" vs "schedule:1000000"".
FE-B1 (FE-021..FE-024) vv, vitest.browser.config.js (browser.enabled, provider playwright(), chromium, headless):
  `fenvix node vitest run --config vitest.browser.config.js --det` => "detjs 0.1.0: Level 0 active; runner=vitest
  5.1.1; controls=fs,isolation,net,order,seeds,time,timers; order fixed ..." / "detjs: serial execution (one
  worker, files in sequence); network=block; timers=virtual" / "Tests 2 passed (2)" / "detjs: trace
  .detjs/trace.jsonl: 0 tests, order digest af1349b9f5f9a1a6a0404dea36dcc949" (exit 0; no line mentions browser
  mode). btest/c.test.js under --det: "× clock is virtual (2025-01-01) in the page: expected '2026-11-20' to be
  '2025-01-01'", "× setTimeout(1500) is fast in the page: expected 1500.2000000001863 to be less than 500",
  "× external network is closed in the page: expected 'ERR Failed to fetch' to match /blocked|detjs/".
  verify of two browser traces: "detpy verify: 2 runs, 0 tests ... covered by Level 0: 0 not covered: 0".
  --det-cache twice: "reused with proof 0 tests in 0 files; ran 1 files; recorded 0 tests" both times.
FE-B2 (FE-032, FE-047..FE-057) for r in playwright cypress puppeteer wdio webdriverio testcafe nightwatch karma
  storybook test-storybook wtr web-test-runner selenium: `fenvix node $r --det` => "usage: detjs vitest|jest|
  node-test|mocha|bun-test|deno-test|tap|ava|jasmine|uvu [--det options] [runner args]" exit=2.
  `grep -rni "playwright|cypress|puppeteer|browser|jsdom|happy-dom|karma|storybook|webdriver|testcafe" node/bin
  node/src`: only src/register.js (Playwright preload), src/sites.js:9 (INFRA regexp), src/vitest/cli.js:158,200,300
  (browser-mode note, built-in env names), src/cache/proof.js:16,35,98, comments in src/clock.js, src/jest/runner.js.
FE-033 pw (static page: button enabled after 300..1500 ms random delay; test clicks with timeout 900 ms):
  6 plain `npx playwright test` runs: exit 1 (delay 1049), 0 (859), 0 (460), 0 (659), 1 (1288), 0 (455).
FE-C1 (FE-058) `git -C /home/user/fenvix-engine-cli diff --stat origin/claude/release-1...origin/claude/<b>`:
  l2-browser-r2: 90 files changed, 27179 insertions (71 files tracks/l2-browser-r2, 12 node/src);
  l2-browser-r3: 137 files, 86263 insertions (72 tracks/l2-browser-r2, 33 tracks/l2-browser-r3, 12 node/src);
  l2-browser-lockstep-ytoqnv: 294 files, 94216 insertions (141 tracks/l2-browser-lockstep, 18 node/src, 8 node/test,
  3 .github/workflows). release-1: `grep -ril "lockstep|chromium|playwright"` over *.rs, *.toml, *.js, *.md, *.yml
  => node/src/register.js, node/src/sites.js, docs/NODE.md, docs/REPORT-node-l0*.md, docs/RELEASE-1.md, harness
  reports, .github/workflows/node-harness.yml, sessions/2026-11-18-rust-hotpaths/REPORT.md (none is a browser
  component; I did not open the docs/workflow hits).

## What the lead should know

1. Skip with proof is effectively absent for the emulated DOM that most front-end projects use: every jsdom test
   file (Jest and Vitest, jsdom 20 through 31) is refused because jsdom reads `performance.timeOrigin` while creating
   the window (FE-001, FE-002). It is sound (no wrong reuse seen) but gives 0 reuse; happy-dom is not affected.
   This contradicts the impression left by NOW.md ("detjs Vitest/Jest skip (0 wrong in 738,552)" says nothing about
   how many jsdom files were ever reused). Check the reuse rate on jsdom projects in the harness results.
2. `--det` in Jest+jsdom is much weaker than in Vitest+jsdom: real-time timers, real rAF, real Event.timeStamp,
   plus injected `setImmediate` / `crypto.randomUUID` that the plain environment does not have (FE-003..FE-008).
3. `--det` produces a false failure with msw 3.x (FE-015); msw 2.x is fine.
4. docs/NODE.md J2 says browser mode is "out of reach"; in practice the CLI claims "Level 0 active ... timers=virtual"
   and writes an empty trace that verifies as identical (FE-021, FE-022): a misleading success, not an error.
5. Time zone and locale are not pinned by `--det` (FE-016, FE-017): matrix columns 8 and 9 are `missing` for every
   front-end row; this is probably true for all of detjs (the Node agent should have the same finding).
6. Seeded shuffle works and found two real order-dependence bugs in my own tiny suites (missing RTL cleanup in
   Vitest without globals; a useId-dependent snapshot in Jest), but nothing turns that into a replay command.
7. FE-018 (latest-record-only cache) and FE-026..FE-031 are generic detjs properties seen from front-end projects;
   deduplicate against the Node agent's list.
8. Gap entries FE-035..FE-046 and FE-060..FE-073 rest on the absence of any browser code in release-1 (READ) plus
   one browser-mode run; they say nothing about the unmerged L2 branches, which I did not read.
