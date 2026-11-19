# Exact culprit: validation harness (idea 2)

Measurement only, not the product. Reports: round 1, fenvix-brain-cli `sessions/2026-11-18-exact-culprit/REPORT.md`;
round 2 (after review R-019), `sessions/2026-11-18-exact-culprit/REPORT-2.md` on this branch.

## Round 3 (review R-019b, last fix round)

Report: `sessions/2026-11-18-exact-culprit/REPORT-3.md`.

* `finder.py`:
  * red-side check after every confirmed commit: every later footprint state must fail (N1);
  * the same check after the fallback search over every commit (N2);
  * a child process counts as an uncontrolled source (`spawn`, or a followed child seen in the key through its
    loader reads): green and red are replayed 5 times, then every confirmation is too (N3);
  * an input or set is named only if it breaks green alone and the red environment without it passes (N4).
* `orderdep.py` (step 4): the same red-side check over the pair's import footprint (`-X importtime`, Python 3.9).
* `review_r019b/`: the reviewer's tests, unchanged; `conftest.py` marks N5 (engine, fixed on
  `claude/rust-hotpaths-2`) as a non-strict expected failure; `stale_d.py` recognises rows re-run with fresh stamps.
* `round3/`: re-run drivers (`refind_a2.py`, `refind_b.py`, `run_a3.sh`, `run_b3.sh`, `run_c3.sh`, `assemble3.sh`).
* `results/`: every population re-run with the round-3 finder; round-2 rows moved to `results/round2/`;
  `results/round1/d-rerun-fresh-stamps.jsonl` is step 4 re-run with fresh stamps and the unchanged step-4 finder.

## Round 2 (review R-019)

* `finder.py` confirms every answer and says "unknown" instead of guessing (R-019 H1-H4): see its docstring.
* `common.py`: strictly increasing mtimes on checkout, no bytecode for plain runs (a same-size edit within one
  second ran the other commit's `.pyc`; the review's own control case failed here because of it).
* `review_r019/`: the reviewer's tests, copied unchanged from `claude/review-r019`.
* `round2/`: `test_finder_round2.py` (more variants), `placed.py` (kind a2: culprit at a random position, and
  revert-and-reland histories, truth by a plain walk), `realrevert.py` (kind b: commits the project reverted),
  `nocode2.py` (added no-code mechanisms: time zone, locale, terminal and interpreter variables), `run_*.sh`,
  `aggregate2.py`.
* `results/`: round-2 rows at the root (`a-*.jsonl` = kind a2, `b-*.jsonl`, `c-final.jsonl` = no-code,
  `c-edit.jsonl` = data-edit commits, `d.jsonl` carried over from round 1, `summary.json`); round 1 moved
  unchanged to `results/round1/` (`aggregate.py results/round1` still reproduces it).


## Engine change (opt-in, default unchanged)

`pytest --det --det-cache=DIR --det-cache-keys=PATH` writes every test's inputs (code units, skeletons, conftest
hooks, files read, environment variables read, runtime and configuration parts, installed and loaded distributions,
interpreter start-up settings) resolved to names and digests, **failures included**. The path is a volatile option
(not configuration). Tests: `tests/test_culprit_keys.py`.

## Files

| file | what |
|---|---|
| `finder.py` | the prototype finder: diff of two keys, pruning (per-unit commit check, loaded distributions, input groups, same-value rules), one deterministic replay per step, green environment rebuilt from the green key at the CI path |
| `common.py` | runs (`--det` with an empty cache, plain pytest), `git bisect run` baseline |
| `mutants.py` | kind a: planted one-token regressions in a replayed history (k commits between green and red) |
| `run_code_cases.py` | kind a: green/red keys, finder, bisect |
| `realhist.py` | kind b: pass-to-fail transitions of the cache-proof walks, reproduced locally |
| `nocode.py` | kind c (Python): the head-to-head's realistic CI changes, alone and with a decoy (TZ or pluggy 1.6.0) |
| `node_case.py` | kind c (Node, docusaurus): detjs store, green-key-only mode |
| `orderdep.py` | step 4: order-dependent defects, polluter then commit; baseline 10 x git bisect in random order |
| `aggregate.py` | all numbers: `aggregate.py results --json results/summary.json` |
| `run_*.sh` | the drivers used (paths of the session machine) |
| `results/` | result rows (`a-*.jsonl`, `b.jsonl`, `c-final.jsonl`, `c-node.jsonl`, `d.jsonl`, `timing-a.jsonl`), the cases (`cases/`), `summary.json` |

Planted commits live in local refs (`refs/culprit/<id>`); each case row has the green commit, file, line and the
old/new line, so the replayed history can be rebuilt (`mutants.build_chain`).
