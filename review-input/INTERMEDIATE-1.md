PARTIAL (intermediate 1 of P-019: the diagnosis table; fixes in progress)

# INTERMEDIATE-1 · L2 browser round 2: where two replays of the same test first diverge

Session: P-019 (L2 browser round 2). Repository fenvix-engine-cli, branch `claude/l2-browser-r2`
(= origin/claude/node-l0 @ 9ffbb0a + round 1's 11 patches + round 2 commits). Diagnosis run
[44275149752](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44275149752) (GitHub-hosted runners,
4 vCPU, unstressed, Chromium headless). Raw data: `tracks/l2-browser-r2/results/<project>.json` and
`results/<project>/diag/dN/r1|r2/` (both traces, the server trace parts and the texts behind every digest). Tool:
`tracks/l2-browser-r2/harness/diagdiff.py`.

## Method

For each of round 1's 15 flaky targets: two `detjs playwright --det` replays (default seed, same epoch), traces kept
in full (`--det-max-events=300000`), and a new diagnosis switch (`DETJS_PW_DIAG_DIR`) that stores the text behind
every digest of the fingerprint (response bodies, WebSocket frames, final DOM, page draw counts). The first diverging
event is taken from the verifier on the browser trace, the text diff below that digest from the diagnosis files, and
the first diverging server event (with its call site) from the verifier on each app-server trace part.

All 15 targets diverge again in 2 replays (MEASURED: 2 distinct fingerprints each), as in round 1.

## First divergence per target (MEASURED, run 44275149752)

| Project | Target | Outcomes r1/r2 | First divergence, browser trace | Below the digest / server side |
|---|---|---|---|---|
| documenso | 5 API/UI tests (FIND_DOCUMENTS x2, SEARCH, EMAIL_TRANSPORT, DELETE_RECIPIENT) | P / F (all 5) | event #0: replay 2 has no request at all | replay 2 fails in test setup: `prisma.user.create()` Unique constraint failed on (email). Seeded test data + database not restored |
| solid-start | handles a hash-only change before hydration | P / P | event #7 `server.fingerprint` (every response body identical) | server: Vite route scanner `fs.readdirSync` (@nodelib/fs.scandir) interleaves with Vite `Date.now` differently |
| etherpad | embed as iframe code (read only) | P / P | event #47 `server.fingerprint` (every body and frame identical) | server: `process.hrtime` in measured-core Stopwatch (stats) vs `Date.now` in tsx: background work interleaves with request handling |
| etherpad | share link encodes pad names | P / P | event #44 `server.fingerprint` (every body and frame identical) | server: `Date` in Minify.ts vs `Date` in log4js LoggingEvent |
| uptime-kuma | saves the data retention period | F / F | event #11 body of `POST /api/auth/sign-in/username` | `createdAt` 09:36:56.294 vs 09:30:16.294: the server clock is one counter for the whole process, so its value depends on how many background reads came before. Then a server push (`heartbeatLists`) lands before vs after a response: page sends `dashboardRendered` vs `getDatabaseSize` in a different order |
| uptime-kuma | creates a group from the monitor form | P / P | event #36 `ws.recv` | heartbeat frame of the monitor check (background job): `time` 09:30:21.996 vs .795, `ping` 0 vs 1; page draws 12 vs 13 random numbers; one extra page frame in the queue's pending set |
| uptime-kuma | RSS feed escapes malicious monitor names | P / P | event #51 `ws.recv` | heartbeat frames of background monitor checks (real DNS lookups, `ENOTFOUND`) at different times; session `expiresAt` differs; the page fetched `incident-history` 2 vs 1 times |
| actual | keeps the search after opening a transaction | T / T | event #203 `dom.digest` | account ids in the URL differ (`/accounts/1a456c2d-…` vs `/accounts/eb6a2bea-…`): UUIDs made in the app's web worker, which is not seeded |
| actual | applies budget template (Envelope) | P / P | event #200 `page.random` 674 vs 676 draws | DOM: a toast mid-animation (`translateY(0px) scale(1)` vs `translateY(-0.45px) scale(0.9989)`); category ids (worker UUIDs) differ |
| actual | extends after budgeting the last month | P / P | event #398 `dom.digest` | account and category ids (worker UUIDs) differ |
| actual | reconciles an account | P / P | event #200 `page.random` 599 vs 600 draws | account ids (worker UUIDs) differ |

Server trace parts of actual (static file server and Vite) diverge at event #0 on Vite and sass timers: no request
of the test is served by them, it is build-tool background work.

## Sources of divergence, by targets blocked

A target is "blocked" by a source if that source alone already makes its two replays differ (several sources can
block the same target; the first in this table is the first in the trace).

| # | Source | Projects hit | Targets blocked (of 15) | Planned control |
|---|---|---|---|---|
| S1 | **Server clock and random shared with background work**: one virtual clock counter and one seeded stream per server process, so every background read (pool reaper, socket heartbeats, stats, logger, dev-server scanner) shifts the values a request sees (timestamps in bodies) and the server's own event sequence | uptime-kuma, etherpad, solid-start | **6** (3 + 2 + 1) | clock and seeded random scoped to the message being handled: values depend only on the message's position in the run and the reads inside its handling |
| S2 | **Server background jobs interleave with request handling** (monitor checks with real DNS, socket.io heartbeats, stats, log4js, Vite scanner): their events enter the test's server fingerprint in a different order | uptime-kuma, etherpad, solid-start | **6** | request-scoped server fingerprint (events in the async context of the message the queue released; background events counted apart) |
| S3 | **Start state not restored**: database rows written by replay 1 (seeded e-mails) make replay 2 fail on a unique constraint | documenso | **5** | `--det-state`: files and Postgres restored to one snapshot before every replay (built, test fails before / passes after) |
| S4 | **Web worker not seeded** (B3): UUIDs made in the app's worker | actual | **4** | seed init prepended to worker scripts (request with `Sec-Fetch-Dest: worker`) |
| S5 | **Server-to-page WebSocket frames not gated**: a push lands before or after a response, the page reacts in a different order | uptime-kuma | **3** | push frames held and released only between two virtual-time chunks, after the server is quiet |
| S6 | **Virtual instant of observation depends on real time**: the final DOM is captured mid-animation, the page draws a different number of random values | actual, uptime-kuma | **3** (actual 2, uptime-kuma 1) | final state taken once the page is settled (no running animations, virtual time advanced); the root (runner actions land after a real-time-dependent number of chunks) needs lockstep time, see below |
| S7 | Controls break the test (fails or times out in both replays) | actual (1), uptime-kuma (1) | 2 | ablation after S1-S6 |
| - | Fonts / layout, crypto in pages, Date in pages, timers in pages, network order of HTTP requests | none | 0 | - |

Round 1's estimate is confirmed for documenso (S3) and for the "server background work" bucket, and refined: in
etherpad and solid-start every response body and frame the browser received was identical in both replays; only the
server's own internal event order differs (S1+S2). Those 3 targets should reach one fingerprint with a
request-scoped server fingerprint alone.

## Order of the fixes

1. S3 start state: **done** (`detjs playwright --det-state=FILE`, `detjs state save|restore`; files and Postgres via
   template databases; tests in `node/test/l2r2.test.js`, 2 of 2 pass after, the file-state test fails before).
2. S1 + S2 server: message-scoped clock/random and request-scoped server fingerprint (6 targets).
3. S4 web worker seeds (4 targets).
4. S5 gated server push (3 targets) and S6 settled final state.
5. Exploration: the exit asks for targets that "fail in some seed". The seeds only reorder messages today; 12 of the
   15 targets flaked only under CPU stress or 10 parallel workers (round 1), and with `--workers=1` and no load no
   seed reorders anything in a single API test. Planned: seeded message latency in virtual time (a response held for
   a seeded number of chunks), so that "slow server" schedules are explored and the failing one replays.

## Risk seen already (not yet a proven error)

S6 points at the limit of per-process control: Playwright actions reach the page after a number of virtual-time
chunks that depends on real time (the runner is not on the virtual clock). If S1-S5 do not reach one fingerprint on
actual and uptime-kuma, the report will propose lockstep virtual time (runner waits, page and server on one clock),
with its cost.
