# Keys of a per-test session's trace header under `--det-isolate`, and their merge rule

Spec "false greens on release-1", Phase B. Code: `node/src/isolate-meta.js` (`mergeSessionMeta`), called by
`node/src/isolate.js` after the per-test sessions.

## Where the keys come from (release-1 6e79a62c)

- `node/src/session.js` `finish()` (lines 463-519): the `full` object written as the header's `meta`, which spreads
  the runner's own `meta` argument and `provableField()`.
- The runner's `meta` argument: `node/src/vitest/cli.js:184-187` (`runner`, `runner_version`, `isolation`,
  `serial`, `pool`, `isolate`, `projects`, `cli_args`, `parallel`, `files_outside_scope`) and
  `node/src/jest/cli.js:198-205` (the same without `pool`/`isolate`). `--det-isolate` runs Vitest and Jest only.
- `parallel` is `node/src/parallel.js` `collect()` (lines 609-680): `workers`, `requested`, `plan`, `placement`,
  `hazards`, `carried`, `timing`.
- `status`: `stampStatus()` (session.js:574-630). `hazard_rerun`: `node/src/parallel-rerun.js:391` (a one-lane
  re-run; not run under `--det-isolate`, parallel-rerun.js:141). `inputs_error`: session.js:520-522.
- Measured: the `meta` of the per-test sessions of a two-file Vitest run, cold and warm cache (the keys listed below;
  the ones that differed between the sessions: `cli_args`, `files`, `isolation`, `parallel`, `reused_tests`,
  `env_read_outside_tests`, `not_proven_outside_tests`).

## Rules

| rule | keys | why |
|---|---|---|
| must be equal in every session (deep-equal); a difference fails closed | `cassette_max_age_days`, `controls`, `detjs`, `entropy`, `env_reads_recorded`, `epoch`, `epoch_ns`, `files_outside_scope`, `inputs`, `isolate`, `locale`, `network`, `node`, `order_seed`, `pinned`, `platform`, `pool`, `projects`, `runner`, `runner_version`, `runtime`, `runtime_version`, `seed`, `serial`, `shuffle`, `tick_adapt`, `tick_ns`, `timers`, `tz`, `urandom_controlled` | the run's configuration, the same outer arguments and environment for every session (the epoch is the run's: session.js `resolveEpoch`, `DETJS_ISOLATE_CHILD`). A session that differs is not the run the header would describe |
| union over the sessions, deduplicated, first appearance | `not_proven_outside_tests`, `env_read_outside_tests`, `files_read_outside_tests`, `notes` | run-level signals: what any session read outside a test is the run's (the defect: only the first session's were kept) |
| `provable` | `provable` | kept only when every session that wrote a trace declared one and all are deep-equal; otherwise deleted and `provable_absent` set naming the session(s) |
| `provable_absent` | `provable_absent` | set when any session had it: the first session's reason, then ` (+N more sessions)` |
| replaced | `parallel` | `{workers: 1, isolate: true}`: the sessions run one after another (isolate.js `groups.forEach`, `spawnSync`), one file each, so the run had no lanes. A session that reports hazards, carried state or placement deviations fails closed. The per-session timing (`parallel.timing`) is dropped |
| written by isolate.js for the run | `files`, `isolation`, `isolate_tests`, `reused_tests`, `status` | as before the change |
| the outer run's | `cli_args` | the per-session ones name one file and a `-t` filter |
| maximum (null when no session had a number) | `cassette_oldest_days` | the oldest cassette any session replayed |
| sum | `unordered_parts` | parts each session could not place |
| any session's, first one (+N) | `inputs_error` | the run's inputs are incomplete when any session's are |
| fails closed when present | `hazard_rerun` | a one-file session has no hazards to re-run; its accounting would be one session's only |
| no rule | any other key | fails closed: `provable` deleted, `provable_absent` names the key, a `NOT PROVEN` line on stderr |

## Consumers of the dropped timing (gate note 2)

- release-1: no reader of `meta.parallel.timing` outside `node/src/parallel.js`, which writes it. `meta.parallel` is
  read by `parallel-rerun.js` `hazardFiles` (not called under `--det-isolate`, line 141) and `parallel.js`
  `readReplay` (`--det-plan` from a trace: an isolate trace has no plan to replay; before this change it replayed
  the first session's one-file plan). The verifier (`crates/detpy-core/src/verify.rs`) decides "parallel" from the
  records' `worker` fields, not from `meta.parallel`.
- runner-proof (`runner/fenvix-run` `node_proof`, 6809aa13 lines 696-713): `workers == 1` means no proof is due
  (returns before `timing.lanes_wall_seconds` is read). So no consumer reads "proof incomplete" because of this
  change. Before it, runner-proof would have read the first session's 4-lane plan and its one-file lanes timing as
  the run's parallel proof.

## Known consequence, sent to the coordinator

Under `--det-cache`, a session whose tests were all reused declares `cache-reuse/1` (session.js `provableField`)
and a session that ran declares `node-surface/1`. The strict rule above then deletes `provable`, so a partly reused
isolate run is NOT PROVEN. The non-isolate path keeps the running sensor in that case. Changing the rule to mirror
it would prove more than the spec's rule, so it waits for the coordinator (spec rule 6).
