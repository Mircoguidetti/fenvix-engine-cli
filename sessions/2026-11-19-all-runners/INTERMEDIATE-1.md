INTERMEDIATE

# All runners (P-032), intermediate 1: which test runners are really used

Branch `claude/all-runners` (fenvix-engine-cli). Raw data: `harness/runner_usage/results/`. Labels: **MEASURED**
(query, date, raw file), **DECLARED** (a registry's own numbers, with the source), **ESTIMATED**, **UNKNOWN**.

## Answer: order of work

Vitest and Jest (Node) and pytest (Python) are already covered. The new runners, in the order they will be built:

| # | Python | why this place (main number) |
|---:|---|---|
| 1 | `unittest` (`python -m unittest`, `discover`) | 8.8% of 1,000 popular Python repositories invoke it (MEASURED); next after pytest (68.1%) |
| 2 | Django `manage.py test` | 1.0% `manage.py test` + 1.0% a `runtests.py` around Django's runner (Django itself, DRF, Wagtail) (MEASURED); 18,144 workflow files (MEASURED, code search); Django 52.2 M downloads/month (DECLARED, pypistats) |
| 3 | nose2 | 0.3% of the sample; 367 workflow files, 172 tox.ini (MEASURED); 588 k downloads/month (DECLARED) |
| 4 | `python -m doctest` | 0 in the sample; 241 workflow files (MEASURED). Doctests run through pytest (`--doctest-modules`, 3.9% of the sample) are pytest and already covered |
| 5 | zope.testrunner | 0 in the sample; 60 workflow files, 390 tox.ini (MEASURED); 62 k downloads/month (DECLARED) |
| 6 | ward | 0 in the sample; 313 workflow-file hits (mostly the word, see below), 24 `[tool.ward]` (MEASURED); 2.6 k downloads/month (DECLARED) |
| all | Hypothesis, under each runner | 5.0% of the sample (MEASURED); 72.5 M downloads/month (DECLARED) |

| # | Node / JavaScript / TypeScript | why this place (main number) |
|---:|---|---|
| 1 | `node --test` (incl. `--experimental-strip-types`) | 21.4% of 1,999 popular JS/TS repositories invoke it somewhere; root `test` script: 13.5% of JS, 4.2% of TS (MEASURED) |
| 2 | Mocha | 10.2% of the sample; root `test` script 12.5% JS, 3.0% TS (MEASURED); 62.5 M downloads/month (DECLARED) |
| 3 | Bun `bun test` | 6.2% of the sample; root `test` script 3.5% TS (MEASURED) |
| 4 | tap / node-tap | 1.2% of the sample; root `test` 1.8% JS (MEASURED); 1.6 M downloads/month (DECLARED) |
| 5 | AVA | 1.2% of the sample; root `test` 1.5% JS (MEASURED); 2.4 M downloads/month (DECLARED) |
| 6 | Jasmine (Node) | 0.8% of the sample; root `test` 0.8% JS (MEASURED); `jasmine` 5.8 M/month (DECLARED) |
| 7 | Deno `deno test` | 0.8% of the sample (MEASURED) |
| 8 | uvu | 0.3% of the sample (MEASURED); its 29.3 M downloads/month (DECLARED) are mostly as a library dependency, not as a runner |
| loaders | tsx, ts-node, `--experimental-strip-types`, esbuild-register, @swc-node/register | tsx in 20.0% of the sample (4.3% of TS root `test` scripts), ts-node 6.9%, strip-types 3.9%, esbuild-register 0.3%, swc register 0.2% (MEASURED). Each loader is tested under every runner that takes a loader |
| out | Karma | 3.7% of the sample, root `test` 3.4% JS (MEASURED): **still used**, but Karma runs the tests inside a browser. That is Level 2 (P-030), so it is out of scope here, like Playwright Test (19.0%) and Cypress (3.0%) |

## Measure 1: what 3,000 popular, active repositories run (MEASURED, 2026-11-19)

Frame: GitHub repository search `language:<L> stars:>500 pushed:>=2026-08-01 archived:false fork:false`, sorted by
stars, the first 1,000 per language (the API maximum), run at 2026-11-19 13:30 to 13:40 UTC
(`results/sample-2026-11-19/query-*.json`). Per repository: the file list of a blobless depth-1 clone, then the
raw content of every `package.json` (up to 40, outside `node_modules`, `vendor`, fixtures, examples), the workflow
files, and `tox.ini`, `noxfile.py`, `pyproject.toml`, `setup.cfg`, `Makefile`, `runtests*.py` at depth ≤ 1. A
repository counts for a runner when a script, CI step or tox/nox/Makefile command invokes it, or when its config
file exists. Multi-label (a repository can use several). Script: `harness/runner_usage/sample.py`; per-repository
evidence: `repos-<Lang>.jsonl`; tables: `aggregate.py` -> `tables.md`.

**Python** (1,000 analysed, 740 with at least one runner found):

| runner | repositories | share of analysed | only runner found |
|---|---:|---:|---:|
| pytest | 681 | 68.1% | 625 |
| unittest | 88 | 8.8% | 45 |
| Hypothesis | 50 | 5.0% | 2 |
| pytest `--doctest-modules`/`--doctest-glob` | 39 | 3.9% | 0 |
| Django `manage.py test` / `django-admin test` | 10 | 1.0% | 6 |
| a `runtests.py` script (Django, DRF, Wagtail around Django's runner; mypy, luigi not) | 10 | 1.0% | 2 |
| nose (1.x, unmaintained) | 4 | 0.4% | 1 |
| nose2 | 3 | 0.3% | 2 |
| stestr | 2 | 0.2% | 1 |
| Twisted trial | 1 | 0.1% | 0 |
| `python -m doctest` / `doctest.testmod` in CI | 0 | 0% | 0 |
| zope.testrunner | 0 | 0% | 0 |
| ward | 0 | 0% | 0 |

**JavaScript + TypeScript** (1,999 analysed, 1,454 with at least one runner found):

| runner / loader | repositories | share of analysed | only runner found |
|---|---:|---:|---:|
| Vitest | 656 | 32.8% | 389 |
| `node --test` | 428 | 21.4% | 183 |
| tsx | 399 | 20.0% | — |
| Playwright Test (L2) | 379 | 19.0% | 41 |
| Jest | 331 | 16.6% | 193 |
| Mocha | 204 | 10.2% | 128 |
| ts-node | 137 | 6.9% | — |
| `bun test` | 123 | 6.2% | 47 |
| `--experimental-strip-types` / `--experimental-transform-types` | 77 | 3.9% | — |
| Karma (browser, L2) | 74 | 3.7% | 35 |
| Cypress (L2) | 60 | 3.0% | 7 |
| AVA | 23 | 1.2% | 15 |
| tap | 23 | 1.2% | 16 |
| Jasmine | 16 | 0.8% | 6 |
| `deno test` | 15 | 0.8% | 1 |
| uvu | 5 | 0.3% | 5 |
| esbuild-register | 5 | 0.3% | — |
| @swc/register, @swc-node/register | 4 | 0.2% | — |

**The runner of the project's main suite** (root `package.json` `test` script, following `npm run x` references in
the same file; `harness/runner_usage/testscript.py`, `testscript-<Lang>.jsonl`), MEASURED:

| runner in the root `test` script | TypeScript (737 with a test script; 156 delegate to turbo/nx/lerna/pnpm -r) | JavaScript (617; 15 delegate) |
|---|---:|---:|
| Vitest | 229 (31.1%) | 71 (11.5%) |
| Jest | 66 (9.0%) | 76 (12.3%) |
| `node --test` | 31 (4.2%) | 83 (13.5%) |
| Mocha | 22 (3.0%) | 77 (12.5%) |
| `bun test` | 26 (3.5%) | 5 (0.8%) |
| Karma | 4 (0.5%) | 21 (3.4%) |
| tap | 1 (0.1%) | 11 (1.8%) |
| AVA | 2 (0.3%) | 9 (1.5%) |
| Jasmine | 0 | 5 (0.8%) |
| uvu | 1 (0.1%) | 1 (0.2%) |
| `deno test` | 0 | 1 (0.2%) |
| tsx / ts-node / strip-types (as loader of the test command) | 32 / 8 / 6 | 4 / 3 / 0 |

Corrections applied after reading the evidence (in `aggregate.py`, `refine`): the word "green" (CI prose) is not the
`green` runner; `brew tap` in workflow files is not node-tap (tap counts only from `package.json` scripts and
`.taprc`); a bare `runtests.py` is not counted as Django. `--reporter tap` (Mocha, `node --test`) is excluded by the
regular expression. Known remaining limits: the frame is popular repositories (applications and AI projects are
over-represented, small libraries under-represented); files deeper than depth 1 for tox/nox/Makefile are not read;
a runner called only from a shell script under `scripts/` is not seen. tsx's 20.0% counts every use of tsx, not
only as a test loader; the root-test-script table gives the loader share for tests.

## Measure 2: GitHub code search counts (MEASURED, 2026-11-19 13:21 to 13:30 UTC)

`gh api search/code` (legacy code search `total_count`), queries and raw responses in
`results/codesearch-2026-11-19/` (`queries.tsv`, `counts.tsv`, `raw/`). Legacy code search tokenizes and its totals
are approximate; some are clearly not runner use (`ava` in workflow files: 1,179,648, which no runner reaches).
They are used only to order runners the sample cannot separate (all at 0 to 3 repositories).

| query (workflow files, `path:.github/workflows`) | count | query (other files) | count |
|---|---:|---|---:|
| `"python -m unittest"` | 93,056 | `"python -m unittest" filename:tox.ini` | 1,200 |
| `"unittest discover"` | 131,328 | `"manage.py test" filename:tox.ini` | 1,246 |
| `"manage.py test"` | 18,144 | `nose2 filename:tox.ini` | 172 |
| `nose2` | 367 | `zope.testrunner filename:tox.ini` | 390 |
| `"ward test"` | 313 | `filename:nose2.cfg` | 450 |
| `"python -m doctest"` | 241 | `"tool.ward" filename:pyproject.toml` | 24 |
| `zope.testrunner` | 60 | `"doctest.testmod" language:python` | 371,200 |
| `"node --test"` | 68,736 | `filename:.mocharc` | 17,920 |
| `"bun test"` | 20,992 | `filename:jasmine.json` | 7,024 |
| `"deno test"` | 6,072 | `"[test]" filename:bunfig.toml` | 14,608 |
| `mocha` | 5,056 | `filename:ava.config` | 2,176 |
| `karma` | 2,172 | `filename:.taprc` | 408 |
| `uvu` | 956 | `filename:karma.conf.js` | 189,952 |
| `jasmine` | 587 | `"test" filename:deno.json` | 15,216 |

`doctest.testmod` appears in 371,200 Python files: doctests are written in many modules, but the sample shows they
are almost always run through pytest or a `__main__` block, not as the CI's runner.

## Measure 3: package downloads (DECLARED by the registries; fetched on GitHub Actions run 44536402831, 2026-11-19 13:44 UTC)

The container cannot reach `api.npmjs.org` or `pypistats.org`; the workflow `runner-usage.yml` fetched them
(`results/downloads-44536402831/`). npm: last month (2026-10-20 to 2026-11-18). PyPI: pypistats `last_month`.

| npm package | downloads | PyPI package | downloads |
|---|---:|---|---:|
| vitest | 748,116,014 | pytest | 984,957,525 |
| tsx | 575,076,463 | hypothesis | 72,537,122 |
| jest | 256,767,387 | django | 52,213,697 |
| ts-node | 250,622,835 | pytest-django | 27,428,123 |
| esbuild-register | 74,035,732 | nose (unmaintained) | 5,566,080 |
| mocha | 62,516,483 | nose2 | 588,014 |
| uvu (mostly as a dependency) | 29,273,121 | zope.testrunner | 61,748 |
| @swc-node/register | 27,481,133 | green | 21,929 |
| jasmine-core / jasmine | 26,705,244 / 5,789,904 | ward | 2,588 |
| bun (npm wrapper only) | 25,327,582 | | |
| karma | 15,919,589 | | |
| ava | 2,441,522 | | |
| deno (npm wrapper only) | 2,042,566 | | |
| tap | 1,580,027 | | |

Downloads count CI installs and transitive installs; Bun and Deno are mostly installed outside npm. They confirm
the order of the sample but do not set it.

## Decisions taken from these numbers

1. **Python: one adapter family.** unittest, Django, nose2 and zope.testrunner all run `unittest.TestCase`s; doctest
   runs through `DocTestRunner`. One runner-neutral driver over the same Rust `CacheSession`, recorder and
   controls as the pytest plugin, with thin hooks per runner (design: `docs/ALL-RUNNERS.md`). ward has its own
   runner and gets its own thin hooks last.
2. **Node: shells on the existing `session.js` + `ProofSession`.** `node --test` and Mocha first. For runners that
   run every file in one process (Mocha, Jasmine, uvu, Bun), the skip runs each file in its own process, because
   skipping file A changes the context in which file B runs (details in the design document).
3. **Karma is not built here**: it is in real use (3.7%), but it is a browser runner (Level 2, P-030).
4. **nose 1.x** (0.4% of the sample, 5.6 M downloads/month) is not on the prompt's list. Whether it still runs on
   Python 3.12+ is UNKNOWN here (not checked; it is unmaintained). Not built; noted for the coordinator.

## Next

Merge of `claude/node-cache-proof` into this branch (conflicts in the shared proof core and the Python cache, being
resolved: the shared-cache Python client of `claude/shared-cache` is not on `claude/rust-hotpaths-2`), then the
adapters in the order above, each with control tests, adversarial tests and walks on GitHub Actions.
