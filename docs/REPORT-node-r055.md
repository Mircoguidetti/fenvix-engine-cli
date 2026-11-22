# Node half of review R-055: report of the Node session (2026-11-21)

Branch `claude/verifier-cli`. Every number below was measured locally: Node 22.23.5, the addon built from the branch,
targeted `node --test` runs. The full CI was started by the coordinator, not by this session.

## Commits

| commit | what |
|---|---|
| `112213f` | `docs/VERIFY-CONTRACT.md`, first version. Written before the roles were split; the verifier session owns it now. |
| `8cb5451` | Rust `verify.rs` R-055 rules: `NotProven` status, `files_read_outside_tests` as `file:` inputs, `deps`/`code` reasons, `"<random>"` hashseed never equal. Python `verify_exit_code`: not proven exits 1. Written before the split. |
| `ac26fa4` | Node channels V1 V2 V3 V5 V6 V8 V16 (see below); `node/test/review-r055.test.js`; 7 attack cases. |
| `9de72f6` | Test expectations after R-050 N1 (project-file reads are inputs since `2023045`): `controls.test.js` golden runs (6 cases), `network-p041` G-1415 (2 cases). These also failed at `688e4fe`. |
| `bf05426` | `inputs.deps` became a digest of `<root>/node_modules`, so it no longer depends on what ran (it had broken cache-p041 G-1402 and parallel-p041). `fs.stat` dropped `size` (r021b cache test). |
| `33b66d1` | The coordinator's five wrong IDENTICALs (below), with 5 attack cases. |

## Node channels (node/src)

- **V1, V2** (`controls.js`): a test that reads a kept CI-volatile variable (`volatile.KEPT`, not pinned), or a proxy
  variable while the network is closed, gets an `uncontrolled.env` mark, so it is NOT PROVEN. The same read outside
  any test, by the project's own code, goes into the header as `not_proven_outside_tests: ["env:NAME"]`.
  Enumerating the environment marks `*`.
- **V3** (`outside.js`, `session.js`): files read or stat-ed while no test runs go into the header as
  `files_read_outside_tests: [{path, digest}]`. This covers the project's own code, and a dependency reading a project
  file while a module is being loaded (for example `dotenv/config`).
- **V5** (`loaded.js`, `session.js`): `inputs.deps` is the content digest of every file under `<root>/node_modules`.
  Every file is hashed on every run. Dot directories (`.prisma`, `.pnpm`) are included; tool output (`.bin`,
  `.cache`, `.detjs`, `.vite`, `.vite-temp`) is skipped.
- **V6** (`outside.js`): `fs.stat` events. The value is `<path>|missing` or `<path>|present` for existence and access
  calls, and `<path>|<type>[ size=n]` for stat and lstat. The size is read past the cache capture (`CAPTURE.busy`).
- **V8** (`network.js`): UDP to a local peer gives a `net.connect` event `<host>:<port> udp local|incoming`. At the
  end of the test it gives `net.stream udp <host>:<port> sent=… recv=…`. Local names count as one peer.
- **V16** (`outside.js`, `controls.js`): `process.loadEnvFile` counts as a read of that file. The variables it sets
  are recorded in `env.get` with a digest of their value.

## The five wrong IDENTICALs fixed in 33b66d1

1. UDP: a reply from 127.0.0.1 to a socket connected to `localhost` was dropped, and so was a datagram from a peer the
   test had not sent to. Both are recorded now.
2. `fs.stat` carried no size, so a test that saw only a size change was IDENTICAL. The size is back; times are not.
3. A dependency reading a project file at import (dotenv) was lost. It is now an entry in `files_read_outside_tests`.
4. `node_modules/.prisma` (generated code) was skipped by the deps digest. It is included now.
5. The deps digest trusted size plus mtime, and npm extracts every file with a fixed 1985 mtime. Every file is hashed
   now.

Also fixed: `fs.promises.readFile` records only while the same test is still running.

## Tests at 33b66d1 (MEASURED)

- `verify-inputs-attacks.test.js`: 34/34. That is 22 existing cases, 7 from `ac26fa4` and 5 from `33b66d1`. The 7 from
  `ac26fa4` were checked to fail without the fixes. The coordinator saw the 5 from `33b66d1` fail at `bf13934`.
- `review-r055.test.js`: 8/8.
- The attack file, review-r055, verifier-inputs, r021b-fixes, cache-p041, parallel-p041 and network-p041 run together:
  192/192.
- runners-p041, controls, time-p041, r021-fixes, review-r021b, review-r032, runner-node-test and runner-mocha:
  265/265.
- Local only, not CI failures: `runner-bun` fails at `688e4fe` too, and CI does not install Bun. `customer-nodetest`'s
  flaky-test case needs `detpy` in the system python, which CI installs.

## Open on the Node side

- **Times in `fs.stat`**: not in the value. The wrapper sees real times; `fstime.js` records the virtual ones the test
  sees. The contract says "mtime where the call returns it", and Python records it.
- **Dependencies read outside tests**: these count only while a module is being loaded, and never for stats. A
  dependency reading a project file at runtime outside a test (not at import) is not recorded. Neither is `dotenv`
  loaded through Jest's own module registry, because no Node loader frame is on the stack. Widening the rule broke
  cache-p041 G-1402 and parallel-p041, through Babel's `.babelrc` lookups and Jest's transform cache.
- **`inputs.deps`** covers only `<root>/node_modules`. A monorepo's hoisted parent `node_modules` and global installs
  are not covered. Hashing every file costs time on large `node_modules`; this was not measured on a real project.
- **`FENVIX_VOLATILE_ENV` names** get no NOT PROVEN mark. The project declared them irrelevant, and the review harness
  reads `ATK_OUT` in every test. Python should match.
- **`inputs.code` (V4)** is not written by Node.
- **`docs/VERIFY-INPUTS.md`** is not updated for these Node rules and limits; the verifier session owns docs.
- **`controls.test.js` golden runs**: the test now primes the golden values with one extra `--det` run, which makes it
  slower.
