# GO matrix (agent GO, audit P-036, branch claude/release-1)

Cell = `done` / `partial` / `missing` / `excluded` + pointer (gap id in GO.gaps.jsonl, or the scratch module under
`/home/user/audit/work/GO/` where it was run). `not checked` = the audit was stopped by the budget limit before this
cell was probed (list in GO.notes.md, "Not covered"). No cell is `excluded`: brain `DECISIONS.md` records no Go
exclusion except the skip-mode virtual day (2026-11-19, GO-049).

Features that do not exist for Go at all (no command in `go/cmd/fenvix-go/main.go:35-51`) are `missing` on every row:
14 repro (GO-065), 15 nightly exploration (GO-067), 16 exact culprit (GO-068), 17 dependency-update verdict (GO-069),
19 shared cache (GO-056), 20 parallel under `--det` (GO-063), 21 `--det-isolate` (GO-064), 22 receipts (GO-057),
12 replay command printed (GO-066).

## Table 1: runners x features

Columns: 1 clock, 2 randomness, 3 hash seeds / map order, 4 test ordering, 5 network closed + record/replay,
6 fs order, 7 env vars, 8 locale, 9 timezone, 10 scheduling, 11 reproducible shuffle + seed, 12 replay command,
13 fingerprints + verifier, 14 repro, 15 nightly exploration, 16 exact culprit, 17 dependency-update verdict,
18 skip with proof, 19 shared cache, 20 parallel under --det, 21 --det-isolate, 22 receipts, 23 overhead measured.

| runner | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `go test` (plain package tests) | partial: time.Now/Sleep/timers virtual (m3, Go 1.23-1.27); GO-009 raw clocks, GO-017 epoch 2025, GO-015 mtimes, GO-035/036 none on 1.22/1.21 | done on 1.23-1.27: math/rand, v2, crypto/rand, /dev/urandom, raw getrandom identical in 2 runs (m3 TestRandGlobal); child entropy GO-014 | partial: done 1.22-1.26 (m1, m3 TestMapOrder); GO-034 missing on Go 1.27, GO-036 on 1.21 | done: source order seed 0, packages sorted (m2 det1 = det2) | partial: connect blocked (m3); GO-012 no record/replay, GO-010 UDP sendto, GO-011 raw connect, GO-001 ports, GO-013 | partial: Readdirnames sorted (m3); GO-016 raw getdents | missing GO-003 | missing GO-005 | missing GO-004 | partial: one P, seed 0 stable 30/30 (m2 race); GO-019 hides races, GO-071, GO-072, GO-008 | done for tests: `--det-seed=5` twice identical (m2 sub); package shuffle READ test.go:475; GO-020 Go's -shuffle dropped | missing GO-066 | partial: trace + verify run (sites = file:line, m2); GO-002 false identical, GO-025 -trimpath sites, GO-022 -count, GO-044; divergence output never exercised: not checked | missing GO-065 | missing GO-067 | missing GO-068 | missing GO-069 | partial: 13 probes right (probe1.log); wrong reuse GO-046, GO-048, GO-080, GO-047; GO-049 virtual day; GO-026/027 coverage; GO-051/052/053/055 reuse lost; GO-060 needs strace | missing GO-056 | missing GO-063 | missing GO-064 | missing GO-057 | partial: std rebuild 21-59 s MEASURED NOISY (GO-037), buildid 24-72 s (GO-038); run overhead on a real module not measured here; DECLARED +5.5% median over 20 projects (brain REPORT-2 line 202, NOISY) |
| `go test` with `t.Parallel` | as row 1 | as row 1 | as row 1 | done: serialised in plan order (m2 par) | as row 1 | as row 1 | missing GO-003 | missing GO-005 | missing GO-004 | partial: serialised; GO-018 overlapping parallel subtests fail; --det-keep-parallel ran (m2 par ok) but its determinism not checked | as row 1 | missing GO-066 | partial as row 1 | missing | missing | missing | missing | partial: serialised in skip mode GO-062; reuse ran (m1/b) | missing | missing GO-063 | missing | missing | not checked |
| `-race` | not checked (ran once: m2 race, builds and detects the race under --det) | not checked | not checked | not checked | not checked | not checked | missing GO-003 | missing GO-005 | missing GO-004 | partial: detector reports the race under one P (m2 `--det -race ./race`); rest not checked | not checked | missing GO-066 | not checked | missing | missing | missing | missing | not checked | missing | missing | missing | missing | not checked |
| fuzz tests (`FuzzXxx`, `-fuzz`) | partial: seed corpus runs on the virtual clock (m2 fz) | not checked (mutator not seeded: GO-028) | not checked | missing GO-028 (not in plan) | not checked | not checked | missing | missing | missing | missing GO-028 | missing GO-028 | missing | missing GO-028 (not in trace) | missing | missing | missing | missing | missing GO-028 (never skipped) | missing | missing | missing | missing | not checked |
| benchmarks | partial: runs; numbers distorted GO-029 | not checked | not checked | missing GO-029 | not checked | not checked | missing | missing | missing | missing | missing | missing | missing GO-029 | missing | missing | missing | missing | missing GO-029 | missing | missing | missing | missing | time.Now hook 1527 ns/op MEASURED (m2 BenchmarkClock) |
| examples (`ExampleXxx`) | partial: virtual clock applies; GO-017 false failure seen | partial: seeded (m2) | not checked | missing GO-030 | not checked | not checked | missing | missing | missing | missing | missing | missing | missing GO-030 | missing | missing | missing | missing | missing GO-030 | missing | missing | missing | missing | not checked |
| testify suites | not checked | not checked | not checked | not checked (suite methods are subtests: one node per suite, GO-031) | not checked | not checked | missing GO-003 | missing GO-005 | missing GO-004 | not checked | not checked | missing | not checked | missing | missing | missing | missing | not checked | missing | missing | missing | missing | not checked |
| ginkgo/gomega (`ginkgo` CLI) | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | missing | not checked | missing | missing | missing | missing | not checked | missing | missing | missing | missing | not checked |
| gotestsum wrapper | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | missing | not checked (-json events ran: GO-032) | missing | missing | missing | missing | partial GO-032, GO-033 (via -json only; gotestsum itself not run) | missing | missing | missing | missing | not checked |
| cgo packages | partial: libc time() in the test binary follows the virtual clock (m2 cg: cyear=2025); vDSO from C not controlled (start message) | not checked (C rand seeded from virtual time in m2 cg; C entropy uncontrolled per start message) | not checked | done (m2 cg in plan) | not checked | not checked | missing GO-003 | missing GO-005 | missing GO-004 | not checked | not checked | missing | not checked | missing | missing | missing | missing | not checked | missing | missing | missing | missing | not checked |
| go.work workspaces | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | missing | not checked | missing | missing | missing | missing | not checked | missing | missing | missing | missing | not checked |
| Bazel rules_go (`bazel test`) | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | not checked | missing | not checked | missing | missing | missing | missing | not checked | missing | missing | missing | missing | not checked |

Note on the last three rows and ginkgo: fenvix-go only wraps the `go test` command (`go/cmd/fenvix-go/test.go:539`);
nothing in `go/` drives `ginkgo`, `gotestsum` or `bazel`, but this was not run, so the cells stay `not checked`
rather than `missing`.

## Table 2: levels for Go

| level | promised | exists on release-1 |
|---|---|---|
| L0 hermetic (order, seeds, virtual clock, fs order, closed network with record/replay) | brain PRODUCT/BRIEF promise; engine docs/GO.md "Level 0 and skip with proof for go test" | partial. Works on Go 1.23-1.26 for order, seeds, clock, map order, os-level fs order, connect() blocking (m1, m3 run twice, verified). Missing: record/replay (GO-012), env/locale/timezone (GO-003/004/005), deterministic ports on Go 1.24+ with MPTCP (GO-001), map order on Go 1.27 (GO-034), clock on Go 1.22 (GO-035) |
| L1 runtime (goroutine scheduling) | docs/GO.md:51 "sched: goroutine scheduling (Level 1 for goroutines)" | partial. One P, no async preemption, seeded runnext: seed 0 stable 30/30, seeds flip a send race (m2). It hides preemption races instead of reproducing them (GO-019), cannot reach them by seed (GO-071), timers and netpoller stay real (GO-072) |
| L2 deterministic VM | brain ARCHITECTURE.md:9 "designed ... for native threads, Go and Java"; ROADMAP.md:68 "before go-live" | missing: no code (GO-073) |
| verifier naming the first divergent event | promise; docs/GO.md:12 | partial: `fenvix-go verify` runs and events carry Go file:line; a divergence report was never produced in this audit (not checked); false "identical" GO-002 |
