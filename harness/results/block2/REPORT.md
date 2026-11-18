# Block 2: detpy explore + repro vs pytest-randomly seeds

Run: https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43974053422. Targets: the 388 Block 1 baseline-unstable tests (28 repositories, same pins). Seeds 1..50, whole suite per seed, serial; 10 replays. Every number MEASURED (timings NOISY: hosted runners). Comparison on the 388 targets of the 28 repositories measured with both tools.

## Share found within K seeds

| K | detpy: failed | detpy: found (bundle replays 10/10, one fingerprint) | pytest-randomly: failed | pytest-randomly: failed and same-seed rerun fails 10/10 | detpy min/repo (median, max) | randomly min/repo (median, max) |
|---:|---:|---:|---:|---:|---|---|
| 1 | 133 (34.3%) | 123 (31.7%) | 113 (29.1%) | 111 (28.6%) | 1.5, 12.7 | 0.0, 1.3 |
| 5 | 315 (81.2%) | 304 (78.4%) | 315 (81.2%) | 313 (80.7%) | 3.9, 134.1 | 0.1, 6.4 |
| 10 | 361 (93.0%) | 349 (89.9%) | 354 (91.2%) | 350 (90.2%) | 4.6, 135.0 | 0.1, 12.8 |
| 20 | 367 (94.6%) | 355 (91.5%) | 375 (96.6%) | 370 (95.4%) | 5.2, 136.9 | 0.2, 25.6 |
| 50 | 378 (97.4%) | 365 (94.1%) | 382 (98.5%) | 376 (96.9%) | 6.5, 149.3 | 0.6, 64.4 |

## Bundles

* reproduced (bundle written, 365 replay 10/10 with one fingerprint): 365; statuses {'not-failed': 10, 'reproduced': 365, 'replay-unstable': 12, 'not-found': 1}
* order before the target: median 53, max 61436 tests; minimal order (with the target): median 2, max 4
* polluter named: 264 (72.3%); state setter named (brittle): 82 (22.5%); kinds {'order': 264, 'brittle': 82, 'fails-alone': 19}
* first diverging event of the bundles: {'entropy': 21, 'outcome-only': 255, 'time': 65, 'fs': 4, None: 19, 'random': 1}
* repro cost per test: median 21 pytest runs, 25.14 s (max 424.18 s)
* deduplication: 365 bundles in 77 polluter families and 45 first-diverging-event families; flaky failing tests outside the targets: 140
* pytest-randomly same-seed reruns: 382 targets re-run; 10/10 376, some 4, none 2; 423.8 min

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
| idoft-domain2idna | 15 | 15 | 15 | 15 | 4.5 | 0.2 | 15 / 3 |
| idoft-easypy | 44 | 34 | 44 | 44 | 33.7 | 10.9 | 34 / 5 |
| idoft-eppy | 67 | 67 | 67 | 67 | 142.5 | 5.0 | 67 / 6 |
| idoft-flask-multi-redis | 14 | 14 | 14 | 14 | 3.7 | 0.4 | 14 / 1 |
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
