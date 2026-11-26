# Suites: base vs final head (spec "false greens on release-1", acceptance 6)

## What was run

| | base | final head |
|---|---|---|
| sha | `24962a94` (claude/release-1 after runner-proof; first baseline on `6e79a62c`: cargo, node) | `2ca21db1` |
| Python | `/home/user/venv-base`: the release-1 wheel built locally (manylinux_2_34, CPython 3.13.18) | `/home/user/venv-branch`: same wheel, `detpy` linked to the tree's `python/detpy` |
| Node | v22.23.5 | v22.23.5 |
| mode | FULL: every file of `tests/` and `node/test/`, the command of `.github/workflows/release-1.yml` per shard (4 Python, 4 Node), serial inside the shard | same |
| not run | the shard-0 extra suites (runner, numpy, hypothesis environments) | same |
| harness | `harness/release1_false_greens/suites.sh` | same |

Node of the final head ran at `3c9d2b09`; `git diff 3c9d2b09 2ca21db1 -- node crates runner` is empty. Attacks (`tests/attacks.py`) ran on the final head's
code. Base and final suites ran partly concurrently on one machine: every failure seen on one side only was run again alone on
BOTH trees (rows marked "alone").

## Totals

| suite | base 24962a94 | final 2ca21db1 |
|---|---|---|
| cargo (detpy-core, detpy-node) | rc 0 | rc 0 |
| Node shards s0..s3 (tests / fail) | 316/0, 287/3, 186/0, 318/1 | 236/0, 359/2, 232/0, 305/2 (shard membership differs: files added) |
| Python s0..s3 | 17 F / 333 P; 0 / 476; 1 / 327; 2 / 408 | 5 / 355; 1 / 517; 4 / 350; 5 / 375 |
| attacks, Python | 15 failed, 154 passed | W11 + W7 (3) failed, others passed (see below) |
| attacks, Node | 60 / 60 | 60 / 60 |

## Failures removed by the branch (base red, final green)

`tests/test_review_r056_pycache.py`: W3 (`posix.access` x2, `posix.stat` mtime, `posix.stat`/`posix.lstat` size x4), W4
(`posix.environ` PWD), W5 (`platform.release()`, `posix.uname().release`), W8 (`_random.Random` seeded/refused).

## Failures on both (pre-existing, not the branch's)

| test | classification |
|---|---|
| `test_packaging.py::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs` | baseline: `parallel-node.yml` has a `push:` trigger (also red in every GitHub run) |
| `test_py_cache.py::test_g2214_...merged_trace`, `::test_the_virtual_clocks_own_probe_of_threads_is_not_the_tests_read` | baseline (also red on GitHub, run 45710688523) |
| `test_r023c_fixes.py::test_e2_shutil_copy2_...` | ENV, same cause on both trees: `shutil.copy2` reaches `posix.listxattr`, unaccounted here (probe: identical trace `unaccounted: api:posix.listxattr` on both) |
| `test_review_r015.py::test_F3_venv_library_upgrade_runs_the_new_code` | ENV: the venv it creates has no pytest here (`No module named pytest`), both trees |
| `test_review_r056_pycache.py::test_w7_installed_code_edited_in_place[*]` (3) | ENV: red locally on both trees, green in every GitHub attacks job |
| `test_review_r056_pycache.py::test_w11_object_addresses_match_uncached_det` | known limit, docs/LIMITS.md section 10 (founder decision); red, no xfail |
| Node: `parallel-p041.test.js` (plan / fingerprints / cache / jest lanes), `host-values-timers.test.js` (b), `repro-p041.test.js` --det-order, `runner-bun.test.js` two --det runs, `runner-node-test.test.js:258` | baseline: the same set on base and final (`node.failures`) |

## Seen on one side only, cleared by a run alone on both trees

| test | where | alone |
|---|---|---|
| `node/test/parallel-p041.test.js` P1 fixed port | final, concurrent run | EADDRINUSE on port 45321 (base and branch suites shared the port); passes alone |
| `test_f01_gaps.py::test_first_run_after_a_checkout_or_an_edit_is_laid_out_like_later_runs` | related-suite run under load | passes alone (branch x2, base) |
| `test_review_r023c.py::test_1b_time_read_through_os_stat_of_a_descriptor[n2,serial]` | final attacks | passes alone on both; green in the GitHub attacks job |
| `test_runners_doctest.py::test_wrong_reuse[git_head_read, timezone_pinned]` | final s0 | 28 passed alone, both trees |
| `test_runners_unittest.py::test_wrong_reuse[child_process_reads_file, child_reads_dev_shm, timezone_pinned]` | final s3 | 28 passed alone, both trees |
| `test_capture_rust.py::test_capture_sessions_match_reference` | final s2 | passes alone, both trees |

## Failures the branch introduced and fixed

`tests/test_runner_node.py::test_wrapper_owned_args_are_not_passed_to_detjs`, `tests/test_runner_node_p0.py` (2): the stub detjs
headers declared only `{"sensor"}` and C4 (`sensor_refusal`) refused them. Fixed in `824854bf` / `f3ecbe73` (stub headers
declare contract, runtime, surface, controls); green on the final head and in GitHub runs since.

## GitHub (LIGHT, Python 3.13 / Node 24)

| run | head | red jobs: failing tests |
|---|---|---|
| 45648842329 | d5642013 | attacks: W11 only (163 passed); Node attacks 60/60 |
| 45669462518 | ca0bbb9c | test_packaging; test_runner_node (stub, fixed); repro-p041 --det-order; W11 |
| 45682060846 | 824854bf | test_runner_node_p0 x2 (stub, fixed); runner-node-test:258; W11 |
| 45695467310 | f3ecbe73 | test_packaging; runner-node-test:258; W11 |
| 45710688523 | 3c9d2b09 | test_packaging; test_py_cache x2; host-values-timers (b); runner-node-test:258; W11. Python s1, s3 green |
| 45714794481 | 2ca21db1 | test_packaging; parallel-p041 jest lanes (+3 cancelled with its hook); W11. Python s3, Node s2 green |

release-1.yml cancels the sibling shards of a matrix about 10-16 s after the first red shard, so no LIGHT run with a
baseline failure reports every shard. Since 3c9d2b09 (Node code identical to 2ca21db1) the two runs together ran every
Python shard and Node shards s0, s2, s3; Node s1 was cancelled in both (local final s1: the same failures as base).

## Final head `9f6bd4d3` (after the founder's D1 = A items: LIMITS lines, /review QA charter fix)

Local (`suites.sh`, Python only; Node, crates and runner are unchanged since `3c9d2b09`, so the Node results above stand):

| suite | failures | classification |
|---|---|---|
| py s0, s1 | `test_py_cache` x2, `test_r023c_fixes::test_e2_shutil_copy2...`, `test_review_r015::test_F3...` | base (x2), ENV (x2), as above |
| py s2 | `test_packaging` gate; W11; W7 x3; `test_capture_rust::test_capture_sessions_match_reference`; `test_review_r023b::test_3_namespace_package_gains_init[n2]`, `::test_3_new_pth_file[serial]` | base; known limit; ENV; the last three ran alone: capture_rust 1 passed (branch); r023b 4 passed on the branch AND on base 24962a94 (concurrent-run interference: the shared venv briefly held `r019c_plug.py` written by `test_absent_inputs_r019c.py` in the s0/s1 run) |
| py s3 | none | |
| attacks, Python | W11; W7 x3 | known limit; ENV (green on GitHub) |

GitHub LIGHT run 45755774138 on `9f6bd4d3`: build, smoke (node, python), Python s1 and s3 green. Red: Python s2 (`test_packaging` gate only), attacks (W11 only; Node attacks 60/60), Node s3 (`host-values-timers` (b), `runner-node-test:258`). Cancelled by the matrix fail-fast before printing results: Node s0, s1, s2 and Python s0 (local s0 on `9f6bd4d3` and Node s0-s2 on `3c9d2b09`: base failures only). Not run: install, publish-engine (skipped by the workflow). No failure outside the base set.
