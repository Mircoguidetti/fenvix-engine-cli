# Exact culprit: validation harness (idea 2)

Measurement only, not the product. Report: fenvix-brain-cli `sessions/2026-11-18-exact-culprit/REPORT.md`.

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
