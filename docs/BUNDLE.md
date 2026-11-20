# Defect bundles

`fenvix repro TEST` and `fenvix explore` turn a flaky test into a **defect bundle**: a directory that holds
everything needed to make the test fail again, with proof that it does.

## Where bundles live

| written by | local address |
|---|---|
| `fenvix repro TEST` | `.detpy/repro/<slug>/` (`<slug>` = test name + 8 hex digits of its id) |
| `fenvix explore` | `.detpy/repro/bundles/<slug>/`, with the exploration summary in `.detpy/repro/explore.json` |
| `--out DIR` | `DIR/<slug>/` (repro), `DIR/bundles/<slug>/` (explore) |

The service and the dashboard name the same bundle `.fenvix/defects/<id>/` once it is uploaded. The bundle files and
`bundle.json` are identical; only the directory differs. Uploading bundles from a CI job is the service's part and
not covered here. In a CI job, upload the directory as an artifact (see docs/EXPLORE.md); on a laptop,
`fenvix replay <dir>` takes the downloaded directory.

The runs' work files (outcomes, traces and orders of every search run) go to `<out>/.work/` and are removed when
the command ends; `--keep-work` keeps them.

## Files

| file | content |
|---|---|
| `bundle.json` | the defect (below) |
| `order.txt` | the minimal order: one test id per line, the failing test last |
| `fail.trace.jsonl` | trace of the failing run (docs/TRACE.md) |
| `pass.trace.jsonl` | trace of a passing run of the same test (present when one exists: alone, or after its state setters) |

## `bundle.json`

| field | meaning |
|---|---|
| `test` | the test id |
| `runner` | `pytest`, `unittest`, `django`, `nose2`, `ward`, `zope-testrunner`, `doctest` (picks the replay adapter) |
| `status` | `reproduced` (every replay failed with one fingerprint), `replay-unstable`, `not-found`, `not-minimised`, `not-collected` |
| `config`, `seed` | the configuration that fails: `fixed` (collection order) or the `--det-seed` |
| `configs_searched` | configurations tried before one failed |
| `kind` | `order` (polluters found), `brittle` (fails alone, passes after its state setters), `fails-alone` |
| `polluters` | the tests whose state makes it fail (minimal, in order) |
| `setters` | the tests it needs to pass (minimal, in order) |
| `order` | the minimal failing order (same as `order.txt`) |
| `prefix_length`, `minimal_length` | tests before it in the failing run, and in the minimal order (with it) |
| `outcome`, `exception` | the failure: `[type, phase, message, location relative to the project]` |
| `replay` | `{runs, fails, fingerprints, identical_fingerprint}` of the proof replays (`--confirm`, default 10) |
| `divergence` | first divergent event against the passing run: `{index, reason, description, event_a, event_b, fingerprints}` (docs/TRACE.md for the reasons) |
| `command` | the runner command that replays it: `pytest --det [--det-seed=N] --det-order=<bundle>/order.txt [args]` |
| `replay_command` | `fenvix replay <bundle>` |
| `pytest_args` | the runner arguments given after `--` |
| `controls`, `detpy`, `python` | the controls, the engine version, the interpreter version |
| `provenance` | `commit` (git HEAD), `dirty` (local changes), `python`, `platform`, `distributions` (`name==version` of every installed distribution), `inputs` (the failing run's inputs: time zone, locale, environment digests, seed, ...) |
| `runs`, `seconds` | the runner runs the search, minimisation and proof took |

## Replaying

```bash
fenvix replay .detpy/repro/test_victim-a60269ec          # 10 runs; exit 0 when every run fails with one fingerprint
fenvix replay .detpy/repro/test_victim-a60269ec --runs 3
pytest --det --det-order=.detpy/repro/test_victim-a60269ec/order.txt   # the same run, by hand (bundle.json: command)
```

When the replay no longer fails, the defect is fixed or the bundle depends on something that changed since it was
written. Compare `provenance` (commit, distributions, inputs) with the current checkout.
