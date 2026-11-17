# Block 2: detpy explore + repro vs pytest-randomly seeds

Run: https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43974053422. Targets: the 388 Block 1 baseline-unstable tests (28 repositories, same pins). Seeds 1..50, whole suite per seed, serial; 10 replays. Every number MEASURED (timings NOISY: hosted runners). Comparison on the 388 targets of the 28 repositories measured with both tools.

## Share found within K seeds

A target that fails under **every** seed of a tool is not counted as found by that tool (Block 1 rule: under detpy it is broken by Level 0; under pytest-randomly it always fails in that environment).

| K | detpy: fails | detpy: replays 10/10 | detpy: replays 10/10, one fingerprint | pytest-randomly: fails | pytest-randomly: seed rerun fails 10/10 | detpy explore / repro min (total) | randomly seeds / reruns min (total) |
|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 115 (29.6%) | 115 (29.6%) | 105 (27.1%) | 109 (28.1%) | 107 (27.6%) | 4.6 / 65.8 | 3.5 / 27.2 |
| 5 | 311 (80.2%) | 310 (79.9%) | 300 (77.3%) | 311 (80.2%) | 309 (79.6%) | 23.2 / 289.6 | 18.2 / 58.9 |
| 10 | 357 (92.0%) | 356 (91.8%) | 345 (88.9%) | 350 (90.2%) | 346 (89.2%) | 46.1 / 321.4 | 36.7 / 76.6 |
| 20 | 363 (93.6%) | 362 (93.3%) | 351 (90.5%) | 371 (95.6%) | 366 (94.3%) | 92.3 / 331.6 | 73.2 / 80.0 |
| 50 | 374 (96.4%) | 372 (95.9%) | 361 (93.0%) | 378 (97.4%) | 372 (95.9%) | 231.0 / 349.4 | 186.3 / 107.2 |

Timings NOISY: in 18 of 28 repositories the two tools ran on different CPU models.

## Standalone `detpy repro <target>` (the developer's command, no exploration hint)

* 388 targets in 28 repositories: {'not-found': 7, 'reproduced': 364, 'budget': 1, 'replay-unstable': 16}
* reproduced 364; cause named 360 (98.9%): polluter 278, state setter 82; kinds {'order': 278, 'brittle': 82, 'fails-alone': 4}
* identical fingerprint over the replays: 364; minimal order median 2.0, max 4; configurations searched median 3.0; seconds per target median 30.43; 669.6 min in total

## Bundles

* reproduced (bundle written, 361 replay 10/10 with one fingerprint): 361; statuses {'not-failed': 10, 'reproduced': 361, 'replay-unstable': 12, 'broken-by-L0 (fails under every seed)': 4, 'not-found': 1}
* order before the target: median 55, max 61436 tests; minimal order (with the target): median 2, max 4
* polluter named: 278 (77.0%); state setter named (brittle): 82 (22.7%); kinds {'order': 278, 'brittle': 82, 'fails-alone': 1}
* first diverging event of the bundles: {'entropy': 21, 'outcome-only': 263, 'time': 65, 'fs': 4, None: 1, 'random': 7}
* repro cost per test: median 21 pytest runs, 25.15 s (max 424.18 s)
* deduplication: 365 bundles in 77 polluter families and 46 first-diverging-event families; flaky failing tests outside the targets: 152
* pytest-randomly same-seed reruns: 382 targets re-run; 10/10 376, some 4, none 2; 107.2 min

## Per repository

| repo | targets | detpy found ≤50 | randomly failed ≤50 | randomly 10/10 | detpy min (K=50, explore+repro) | randomly min (K=50) | bundles / families |
|---|---:|---:|---:|---:|---:|---:|---|
| anyio | 16 | 12 | 13 | 11 | 149.3 | 64.4 | 12 / 4 |
| arrow | 2 | 2 | 2 | 2 | 20.0 | 5.2 | 2 / 1 |
| idoft-accessify | 7 | 7 | 7 | 7 | 2.2 | 0.2 | 7 / 1 |
| idoft-breathe | 8 | 8 | 8 | 8 | 5.3 | 0.4 | 8 / 6 |
| idoft-centreon-sdk-python | 41 | 41 | 41 | 41 | 18.2 | 0.4 | 41 / 2 |
| idoft-cloudnetpy | 27 | 27 | 27 | 27 | 29.6 | 6.3 | 27 / 11 |
| idoft-coinbase-commerce-python | 8 | 8 | 8 | 8 | 6.0 | 0.4 | 8 / 3 |
| idoft-crom | 13 | 11 | 13 | 13 | 3.7 | 0.3 | 11 / 5 |
| idoft-devtracker | 6 | 6 | 6 | 6 | 3.2 | 4.3 | 6 / 4 |
| idoft-domain2idna | 15 | 12 | 15 | 15 | 4.5 | 0.2 | 15 / 3 |
| idoft-easypy | 44 | 34 | 44 | 44 | 33.7 | 10.9 | 34 / 5 |
| idoft-eppy | 67 | 66 | 67 | 67 | 142.5 | 5.0 | 67 / 6 |
| idoft-flask-multi-redis | 14 | 14 | 14 | 14 | 5.0 | 0.4 | 14 / 1 |
| idoft-freezegun | 8 | 7 | 7 | 7 | 11.5 | 0.5 | 7 / 4 |
| idoft-krllint | 3 | 3 | 3 | 3 | 2.6 | 0.1 | 3 / 2 |
| idoft-ljson | 4 | 4 | 4 | 4 | 2.8 | 0.3 | 4 / 2 |
| idoft-mdutils | 8 | 8 | 8 | 8 | 2.9 | 0.2 | 8 / 1 |
| idoft-odinweb | 12 | 12 | 12 | 12 | 5.2 | 0.4 | 12 / 1 |
| idoft-panamah-sdk-python | 4 | 0 | 3 | 0 | 5.6 | 6.5 | 0 / 0 |
| idoft-py-autodoc | 15 | 15 | 15 | 15 | 6.9 | 0.3 | 15 / 4 |
| idoft-pykicad | 28 | 28 | 28 | 28 | 8.2 | 0.9 | 28 / 2 |
| idoft-pymq | 1 | 0 | 1 | 0 | 14.4 | 32.1 | 0 / 0 |
| idoft-supertunnel | 9 | 9 | 9 | 9 | 6.1 | 0.2 | 9 / 1 |
| idoft-todo-sync | 10 | 9 | 10 | 10 | 4.0 | 0.7 | 9 / 2 |
| idoft-tunacell | 10 | 10 | 10 | 10 | 9.9 | 1.5 | 10 / 2 |
| jsonschema | 2 | 2 | 2 | 2 | 17.8 | 10.2 | 2 / 2 |
| packaging | 1 | 1 | 0 | 0 | 46.5 | 29.2 | 1 / 1 |
| rich | 5 | 5 | 5 | 5 | 12.9 | 4.8 | 5 / 1 |
