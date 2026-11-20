# PROC3 notes: process gaps, non-Python language tracks and browser/L2

Agent PROC3. Paper-trail audit (prompts, reports, reviews, DECISIONS) against the code of `claude/release-1`.
283 entries in `PROC3.gaps.jsonl`. Nothing was built; everything is read, grep or a script already in the tree.

Abbreviations used in every `evidence` field:

- `brain:` = `/home/user/fenvix-brain-cli` (main).
- `rel1:` = `/home/user/audit/engine` = fenvix-engine-cli at `claude/release-1` (529c1609), the audited branch.
- Other branches are written in full (`fenvix-engine-cli@claude/...`), read with `git show` / `git grep` in
  `/home/user/fenvix-engine-cli`.

Id ranges: Node L0 (P-007) 001-049 · Node cache 008, 012, 050-078 · other JS runners (P-032) 079-106 ·
Go (P-021) 107-165 · JVM (P-022) 166-228 · browser/L2 229-257 · e2e (P-023) 258-259 · release (P-034) 260-273
(261 = no P-034 prompt, 262 = placeholders) ·
plan/process 274-283.

## (a) Could not check

| what | why |
|---|---|
| Whether GitHub's `ubuntu-latest` image ships Bun or Deno (PROC3-272) | No hosted runner here. The workflow installs neither and the tests skip when the binary is absent; the release report's Node count (622 tests, 1 skipped) is a local run where both exist. |
| The result of the `claude/release-1` candidate run 44695977358 | The report's table still holds placeholders (PROC3-262); Actions logs were not fetched. |
| The final number of P-030 on the 55 targets | No REPORT.md anywhere. The branch has `tracks/l2-browser-lockstep/results/hunt-*.json`, but they are raw run files without a summary; I did not re-derive a number from them (PROC3-231). |
| Whether Node has the "audit rerun" self-check (seeded 5% fresh) | NUMBERS.md says "detjs gets it with its cache with proof". `grep -i audit node/src/cache/proof.js crates/detpy-core/src/node_session.rs` finds nothing, but ALL-RUNNERS.md mentions a "verify draw" in the Rust proof core; not traced end to end, so not listed as a gap. |
| Spock, Kotest, Android unit tests under the JVM agent | They run on the JUnit Platform / as Gradle Test tasks, so they may work; no fixture or report mentions them. Not listed. |
| Whether GitHub's default branch has `go-nightly-real-clock.yml` | Only `claude/*` branches are fetched locally (`git branch -r`), no `main`; the session's own report says the cron fires from the default branch only (PROC3-152). |
| Go `-race`, `-cover`, build tags with the overlay | Not mentioned in any Go report; not tested here (other agents own the hands-on Go audit). |
| JVM numbers on GitHub Actions for the final agent | Declared UNKNOWN by the session itself (PROC3-216). |
| Whether `detjs` on release-1 honours every J-limit exactly as docs/NODE.md says | J1-J17 are listed from the doc (how = DOC) except where I grepped the code (J2, J14, J16, Playwright). |

## (b) Evidence appendix (commands run, trimmed real output)

**PROC3-001/002, 080-087 (serial under --det, every JS runner)**
```
$ grep -rn -E "fileParallelism|runInBand|--jobs=1|--concurrency=1|max-concurrency" node/src
src/vitest/cli.js:114:    fileParallelism: false,
src/vitest/cli.js:115:    maxWorkers: 1,
src/vitest/cli.js:116:    maxConcurrency: 1,
src/jest/cli.js:87:  const extra = ['--runInBand', '--forceExit', '--maxConcurrency=1',
src/runners/ava.js:84:  ... [runner.binPath, ...userArgs(rest), '--concurrency=1', '--serial'] ...
src/runners/bun.js:181:    args.push('--max-concurrency=1');
src/runners/tap.js:91:  const extra = ['--jobs=1', `--save=${save}`, ...
src/mocha/cli.js:125:  if (opts.parallel || opts.p) notes.push('--parallel is off under --det (files run one at a time)');
src/runners/deno.js:29:const REFUSED = { '--watch': 'watch mode', '--parallel': 'files run one per process, ...
```

**PROC3-004..009, 107-115, 171-177 (features that exist for Python only)**
```
$ grep -n "add_parser" python/detpy/cli.py
41:    r = sub.add_parser("repro", help="find, minimise and bundle a failing order for one test",
47:    e = sub.add_parser("explore", help="nightly exploration: seeds within a time budget, one bundle per failure",
54:    rp = sub.add_parser("replay", help="replay a bundle and check it fails with the same fingerprint")
$ sed -n 19,26p node/bin/detjs.js      # vitest, jest, bun-test, deno-test, node-test, mocha, ..., verify
$ grep -n 'case "' go/cmd/fenvix-go/main.go
36:	case "test":   38:	case "exec":   40:	case "verify":   42:	case "overlay":
$ grep -n 'case "' jvm/agent/src/main/java/dev/fenvix/cli/Main.java   # run, merge, verify, paths
$ grep -rn -o -- "--det-cache-[a-z-]*" node/src | sed 's/.*://' | sort -u
--det-cache-receipts --det-cache-summary --det-cache-verify
$ grep -o -- "--det-cache-[a-z-]*\|--det-isolate" python/detpy/_level0.py | sort -u
--det-cache-dists --det-cache-epoch-window --det-cache-keys --det-cache-max-age --det-cache-no-follow --det-cache-receipts --det-cache-shared --det-cache-verify
$ grep -rn -i "receipt" go/cmd crates/fenvix-go/src crates/fenvix-skip/src jvm/rt/src jvm/agent/src     # no output
$ grep -n -i "replay\|reproduce with\|rerun with" go/cmd/fenvix-go/{test,exec,main}.go                  # no output
```

**PROC3-017 (Playwright measured only)** `node/src/register.js:2`: "Level 0 inside Playwright Test worker processes
(measurement only) ... no per-test brackets ... no trace is written. The browser is a separate process and is not
controlled at all."

**PROC3-040** `node/src/session.js:92`: `const netMode = opts.record ? 'record' : fs.existsSync(cassette) ? 'replay' : 'block';`
(no reference to the disabled controls), printed at `:126`.

**PROC3-059** `grep -rni "day_epoch\|virtual day\|max-age\|real-clock" node/src` => no output; Python has
`--det-cache-max-age` (30 days) and no virtual-day key either (`python/detpy/_level0.py:97`), so DECISIONS 2026-11-19
("Same rule for Python, Node and Go") is implemented in Go only. Python is outside my area: for the lead.

**PROC3-065** `node/src/cache/runtime-id.js:69-73`: `function nodeModulesDirs(root, limit = 20000) { ... if (n++ > limit) return;`

**PROC3-093**
```
$ git log --oneline origin/claude/release-1..origin/claude/all-runners-2 | wc -l      => 90
$ git diff --stat origin/claude/release-1 origin/claude/all-runners-2 -- node/src crates python/detpy | tail -3
 python/detpy/_proof.py | 71 +- ... (fenvix-skip absent on all-runners-2: expected)
```

**PROC3-133, 158** `go/cmd/fenvix-go/test.go:777`: `if os.Geteuid() != 0 {` ... `:390`: "NOT the pid (needs root and
util-linux unshare for a PID namespace)"; `review_r025b_test.go:333`: `t.Skip("needs root to chown")`, `:350`:
`t.Skip("needs unshare and root")`; `.github/workflows/release-1.yml:135`: `go vet ./... && go test -count=1 -v ./...`.

**PROC3-144, 145, 146 (Go, newest walk, run on release-1)**
```
$ python3 harness/go/review_r025b_check.py | tail -3
S1  skip-r9 (prometheus, telegraf, terraform): broken by skip mode (...>= 10 commits): 0 []; of the 8, present in skip-r9: 7
findings:
exit=0
$ ls harness/go/results/skip-r9      # prometheus 0..7-of-8, telegraf 0..4-of-6, terraform 0..6-of-8
$ python3 harness/go/aggregate.py skip harness/go/results/skip-r9
| repository | shards | commits walked (min over shards) | ... | fenvix: share ..., median / mean | go test cache | ...
| prometheus | 8 | 7 transitions | 2097 | 38% / 45% | 39% / 49% | 52475 | 0 | 1 | ...
| telegraf | 5 | 0 transitions | 0 | n/a | n/a | 6787 | 0 | 0 | 55199 | 0 | 5 |
| terraform | 7 | 2 transitions | 3551 | 24% / 24% | 35% / 35% | 96126 | 0 | 0 | ...
Test time go's cache reused and fenvix ran ... | telegraf | 73.6 | ... unkeyed 70.6 |
$ head -1 sessions/2026-11-18-go-l0/REPORT-3.md      => PARTIAL   (same on brain and on origin/claude/go-l0)
```
The string the check requires (`broken by skip mode: 0`) occurs in REPORT-3 §5 and §9 as part of the description of
the check, so the text condition is met without the result being stated.

**PROC3-162** `docs/GO.md:40` "... not controlled: cgo crypto (BoringCrypto), `/dev/urandom` opened directly ..."
against `go/internal/overlay/files/os.go.txt:328` "fenvixDevRandom: with the crypto control on, /dev/urandom and
/dev/random ..."; `docs/GO.md:94` "A panicking test ends the test binary; the trace records it as `interrupted`."

**PROC3-166, 167, 169** `grep -n -i "skip\|exclude\|filter\|reus" jvm/gradle/fenvix.init.gradle` => one line (51, a
comment about the key). `fenvix.init.gradle:46 t.maxParallelForks = 1`, `:48 t.outputs.upToDateWhen { false }`.
`FenvixMavenExtension.java:81 if (!pl.getArtifactId().equals("maven-surefire-plugin")) continue;`

**PROC3-208, 209, 210**
```
$ grep -n "python3 jvm" .github/workflows/*.yml
jvm-tests.yml:59 run_controls.py   jvm-tests.yml:78 run_skipkeys.py   jvm-tests.yml:79 run_review_r022.py   jvm-tests.yml:95 run_l1_measure.py
release-1.yml:164 run_controls.py  release-1.yml:169 run_skipkeys.py  release-1.yml:170 run_review_r022.py     (169-170 only `if: matrix.java == '21'`)
```
`jvm-tests.yml` triggers on `claude/jvm-l0` only; `go-tests.yml` on `claude/go-l0` only.
`python3 jvm/test/check_r022b_docs.py` on release-1 => 6/6 ok, exit 0 (the docs finding of R-022b is fixed; the
stale lines of PROC3-226 are not covered by that check).

**PROC3-229, 230, 237, 239, 243**
```
$ git ls-tree -r --name-only origin/claude/release-1 | grep -iE "node/src/pw|playwright|cypress|lockstep|L2-BROWSER"
harness/runner_usage/results/downloads-44536402831/raw/npm_@playwright__test.json
harness/runner_usage/results/downloads-44536402831/raw/npm_cypress.json
$ git diff --stat origin/claude/release-1 origin/claude/l2-browser-lockstep-ytoqnv -- node/src/pw crates/detpy-core/src/lockstep.rs | tail -1
 14 files changed, 5123 insertions(+)
$ git merge-base origin/claude/release-1 origin/claude/l2-browser-lockstep-ytoqnv   => 9ffbb0a5 (2026-11-17 07:13)
$ git grep -n -i "firefox\|webkit" origin/claude/l2-browser-lockstep-ytoqnv -- node/src/pw            # no output
$ git grep -il cypress origin/claude/l2-browser-lockstep-ytoqnv -- node crates docs                    # no output
$ git grep -n -i "detpy\|python" origin/claude/l2-browser-lockstep-ytoqnv -- node/src/pw/server.js node/src/pw/cli.js
node/src/pw/server.js:404:// A message the engine released with a fault (x-detjs-fault, drawn by the seed: crates/detpy...   (the only hit: a comment)
```

**PROC3-249** `origin/claude/l2-browser-lockstep-ytoqnv:node/test/l2r3.test.js:161`: "Found in round 3 while building
E6 (not fixed; `todo` until it is)".

**PROC3-258** `git -C /home/user/fenvix-app ls-files | grep -iE "e2e\.sh|E2E\.md|REPORT-e2e"` =>
`github-app/recordings/E2E.md` only.

**PROC3-272, 273** `.github/workflows/release-1.yml:94-118` (node job: setup-node 22, setup-python, `npm ci`,
`node --test ... test/*.test.js`); `node/test/runner-bun.test.js:17`:
`const SKIP = H.BINARY.bun ? false : 'bun not found (PATH or DETJS_BUN): Bun runner tests skipped';`
`ls node/src/index.js` => No such file or directory (`package.json` `"main": "src/index.js"`).

**PROC3-275..281**
```
$ grep -n "Done means" prompts/P-007* prompts/P-014* prompts/P-019* prompts/P-021* prompts/P-022* prompts/P-023* prompts/P-030* prompts/P-032* prompts/COMMON.md
prompts/P-007-node-l0.md:5:Done means: Node bindings of the Rust core; a Vitest and a Jest shell with `--det` ...
prompts/COMMON.md:8:- Your prompt's "Done means" is the contract. Run every test before you deliver.
$ ls prompts | grep -E "034|^R-"        => R-001-mixed-round.md  R-010-market-test.md
$ ls components                          => README.md harness.md level0.md verifier.md
$ ls sessions/2026-11-19-l2-browser-lockstep => INTERMEDIATE-1.md INTERMEDIATE-2.md
$ grep -n -i 'online decider\|`repro`\|replay bundle\|not applied\|still runs every' sessions/2026-11-19-review-{jvm,go,node-cache}/*.md sessions/2026-11-17-review-node/*.md   # no output
```

## (c) For the lead

### A. "Done means" against the promise, per prompt

| prompt | what the contract asked (quote) | what the promise needs and the contract did not ask | closed as |
|---|---|---|---|
| P-007 Node L0 | "Node bindings of the Rust core; a Vitest and a Jest shell with `--det` doing what the pytest plugin does; engine tests green; a 25+25 Node round ..." and, in step 2, "run serially under --det and record that choice" | parallel with proof (the prompt orders the opposite), repro, exploration command, replay bundle, culprit, dependency verdict, Level 1 for the event loop, Playwright beyond "measure, without building on it" | CLOSED 2026-11-18 ("TypeScript/Node stands next to Python") on 16+25 projects, 44 tests broken by --det |
| (no prompt) Node cache | no prompt file in the brain | per-test reuse, reuse under vmThreads, reporter integration, dependency verdict, virtual-day rule | CLOSED 2026-11-20 without a third review |
| P-032 all runners | "the same two guarantees: --det ... --det-cache"; table "support: none / det only / det + skip" | everything except det + skip, for 8 more JS runners; browser runners "tracked separately (P-030)" which is Playwright only | round 2 PARTIAL, "no independent review of the merged head" |
| P-021 Go | no "Done means"; "Level 0 and skip with proof for `go test`" steps 1-6; "goroutine interleaving is Level 1: measure, do not solve"; key via strace | repro, exploration, bundle, culprit, dependency verdict, shared cache, receipts, parallel with proof, record/replay, macOS/Windows, a result on real flaky tests (measured: 0 of 24) | REPORT-3 PARTIAL; NOW says it "closes" after skip-r9 |
| P-022 JVM | no "Done means"; step 3 "Skip with proof for the JVM: per test, the key is ..."; step 5b "share of test time skipped, 0 wrong (every reuse checked by a fresh run)"; "Thread interleaving is Level 1: measure, do not solve. Kotlin coroutines: measure." | actually skipping a test in Gradle or Maven (an online decider), plus the same list as Go; TestNG, Failsafe, Bazel | CLOSED 2026-11-19 (REPORT-3 DONE) |
| P-014 / P-019 / P-030 browser | exit numbers on flaky Playwright targets (>= 60% reproduced) | integration into the product branch, Cypress (DECISIONS 2026-11-18), other browsers, non-Node app servers, multi-worker | 0/15, 0/15, 0/55, then gate 8/8 and no final report; nothing in release-1 |
| P-023 e2e | pytest + "a small Vitest project" on the deployed system | every other language and runner; and the suite itself was never written | not started |
| P-034 release | no prompt file | green candidate run, macOS/Windows/arm64, packaging a user can install, L2 browser, runner wrapper for non-Python | PARTIAL |

Pattern: every reviewer was bound to the prompt (REVIEWER.md) and spent both rounds on wrong-reuse holes; none of
the eight review reports I read says that a language lacks repro/exploration or that the JVM never skips. The first
document that states "JVM skip with proof is a decision, not a skip" as an open item is the release report
(2026-11-20), one day after the track was marked CLOSED.

### B. Review FIX items: fixed, and is the reviewer's test in the release gate?

| review | items | fixed (per the re-review or the last report) | reviewer's tests on release-1 | still open |
|---|---|---|---|---|
| R-005 (Node L0, FIX 4) | FIX 1-4 | yes, R-005b PASS on all four | `node/test/regressions.test.js` etc. run by the gate | NOTES: timing assertions (PROC3-039), header `network=block` (040) |
| R-005b (FIX 2) | wording FIX 1, 2 | applied in REPORT-2 "Re-check R-005b" (not re-reviewed) | n/a | Node 18 test (041) |
| R-011 (L2 r2, FIX 6) | R1, R2, H1-H4 | yes on `claude/l2-browser-r3` (round-3 report) | **not on release-1**: `node/test/review-r011.test.js` exists only on the L2 branches | risks: socket.io transport (252); E4 never run (254); "clean checkout" (253) |
| R-021 (Node cache, FIX 9) | F1-F9 | yes, R-021b confirms | `node/test/review-r021.test.js`, in the gate; F3b skipped under Jest (076) | untested notes: 065-068 |
| R-021b (FIX 4) | G1-G4 | yes per REPORT-3, not re-reviewed | `node/test/review-r021b.test.js`, in the gate | "not tested" list (061, 069); new leak found by the session (077) |
| R-022 (JVM, FIX 17) | S1-S11, W1, D1-D4, N1 | yes, R-022b confirms | `run_review_r022.py` in the gate on JDK 21 only; `run_review_r022_det.py` and `run_w1_verifier.py` in no CI (210); two scripts exit 1 by construction (211) | D5 = V19 (200) |
| R-022b (FIX 4) | S12, S13, S14, DOC | yes per REPORT-3, not re-reviewed; `check_r022b_docs.py` passes here (RAN) | `run_review_r022b.py` in **no CI** (209) | V20 list (201-207), JDK 8/11/17 hooks (208), online decider (168) |
| R-025 (Go, FIX 17) | F1-F9, D1-D4, N1-N3, R1 | yes, R-025b confirms | `review_r025_test.go` in the gate (`go test ./...`, Go 1.26 only; D3_Go122 skips on a cold toolchain: 159) | — |
| R-025b (Go, FIX 19) | X1, C1-C3, P1, A1, F1b, F2b, F5b, V3, R1b, S1, V1, D2b, D3b, N4, N5, R2, NC | yes per REPORT-3 (PARTIAL), not re-reviewed | `review_r025b_test.go` in the gate, but F2b and F5b skip without root (158), D3b fails on GitHub runners (133), S1 passes on an incomplete walk (144) | NC as a product feature (152); quic-go (128); vDSO (150) |
| R-032 / R-032b (Node part) | F6, F7 / F4-F7 | yes per all-runners-2 REPORT-2 (PARTIAL) | test files in the gate, but the Bun and Deno cases skip without the binaries (272) | "no independent review of the merged head" (092) |

### Contradictions and claims I found false or stale

1. **"JVM CLOSED" (NOW, LOG, NUMBERS) against REPORT-3 "Open: ... an online decider in the runner, which is not
   built"** and docs/RELEASE-1.md "the build tool still runs every test" (PROC3-166..170).
2. **DECISIONS 2026-11-18 "TypeScript/Node stands next to Python in the product"**: Node has det + skip only and is
   serial (PROC3-279).
3. **DECISIONS 2026-11-19 "Same rule for Python, Node and Go" (virtual day + nightly real clock)**: only Go has the
   day key; Node keys a fixed 2025 epoch and has no real-clock run (PROC3-059); Python uses a 30-day max-age.
   The Go nightly is a harness workflow on one repository (PROC3-152).
4. **Go track "closes if all TestR025b pass"**: on GitHub runners `TestR025b_D3_UncontrolledEntropy` fails (release
   report §0), two reviewer tests skip for lack of root, and the S1 number check exits 0 on a walk with 7 / 2 / 0
   transitions (PROC3-133, 144, 158). REPORT-3 is still PARTIAL everywhere.
5. **Go versus Go's own cache**: in the newest committed walk fenvix reuses less test time than `go test`'s cache on
   prometheus and terraform, and on telegraf Go's cache reuses 73.6 points of test time that fenvix runs
   (PROC3-145, 146, RAN on release-1 data). The LOG's Go figures (62%, 87%, 38%, 28%) predate the soundness fixes;
   NUMBERS.md has no Go section (PROC3-165).
6. **"0 wrong in 5,731,740 verified reuses" (JVM, LOG 2026-11-18)** was measured with the pre-review rule and a
   verifier that called polluter-caused wrong reuses flaky; the sound rule was walked on two Maven repositories in a
   container (PROC3-212).
7. **docs/GO.md and docs/JVM.md contradict the code** in places (PROC3-162, 226); README.md and docs/NODE.md still
   describe "Vitest and Jest" (PROC3-271).
8. **Release report**: PARTIAL, with `RESULT_*` placeholders where the candidate run's results should be
   (PROC3-262).
9. **ROADMAP go-live names Playwright; DECISIONS names Cypress**: release-1 contains neither beyond a
   measurement-only preload for Playwright workers (PROC3-017, 229, 237).
10. **Two-round rule**: in all three skip tracks the unreviewed last round found a further wrong reuse by itself
    (Node: custom environment `setup`; JVM: `<clinit>` null read; Go: dropped strace lines). RULES says what remains
    "is decided by the founder"; no DECISIONS entry exists for any of the three (PROC3-077, 161, 225, 278).

### Notes on classification

- `how = DOC` (182 entries) means the item comes from a report, review or limits table and I did not see it in
  code; `READ` (84) means I read the code, config or tree of the named branch; `RAN` (17) means a command above.
- Documented limits (J1-J17, V1-V20, the Go lists) are listed as gaps as the brief asks; DECISIONS.md records none
  of them as an exclusion, so no matrix cell in my area is "excluded". The only clock rule that is decided
  (virtual day, 2026-11-19) is listed where its implementation or its mitigation is missing.
- Severity `WRONG-RESULT` is used for a false failure under --det/skip mode, a wrong or unsound reuse channel that a
  report or limits doc admits, and for a trace that records the wrong outcome.
