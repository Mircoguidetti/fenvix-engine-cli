# L1 study: async flaky tests under `--det` and `--det --det-async`

Generated 2026-11-16 17:09 UTC. Per project: 10 baseline / --det / --det --det-async (seed 0) runs of the corpus tests, interleaved, serial, fixed collection order; exploration with --det-async-seed=1..20 (test order fixed); 10/10 confirmation of the first failing seed; 3 timed runs of the full suite per mode.

Run: https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/43914981044

## Projects

| project | source | status | python | commit | corpus tests |
|---|---|---|---|---|---|
| anyio | 25+25 round (popular pool, run 43892303433) | install-failed (install with python 3.13: error: Distribution not found at: file:///tmp/l1work/s) |  | 9df02f0b8362 | 0 |
| idoft-aiopylimit | IDoFT (asyncio,asynctest) | install-failed (install with python 3.9: error: Distribution not found at: file:///tmp/l1work/sr) |  | b4075a8ac30d | 0 |
| idoft-aiotasks | IDoFT (asyncio) | install-failed (install with python 3.9: error: Distribution not found at: file:///tmp/l1work/sr) |  | ec485c84db55 | 0 |
| idoft-easypy | 25+25 round (IDoFT pool) + IDoFT | install-failed (install with python 3.9: error: Distribution not found at: file:///tmp/l1work/sr) |  | 9501c3ee03dc | 0 |
| idoft-plcx | IDoFT (asyncio) | install-failed (install with python 3.9: error: Distribution not found at: file:///tmp/l1work/sr) |  | 2756c0ba78c4 | 0 |
| idoft-pyps4-2ndscreen | IDoFT (asyncio,asynctest) | install-failed (install with python 3.9: 2ndscreen/pyps4_2ndscreen/ps4.py", line 8, in <module>
) |  | 457dc9c3f040 | 0 |
| idoft-python-dugong | IDoFT (asyncio) | install-failed (install with python 3.9: error: Distribution not found at: file:///tmp/l1work/sr) |  | 00dd4d5aab6e | 0 |
| idoft-tornado-swirl | IDoFT (tornado) | install-failed (install with python 3.9: error: Distribution not found at: file:///tmp/l1work/sr) |  | b8df27efc3d7 | 0 |
| idoft-webssh | IDoFT (tornado) | install-failed (install with python 3.9: error: Distribution not found at: file:///tmp/l1work/sr) |  | 51d527fe75a6 | 0 |
| l1-repro | minimal reproductions (this study) | install-failed (install with python 3.13: error: Distribution not found at: file:///tmp/l1work/s) |  | local | 0 |

## Per test

| project | test | cat. | baseline | --det | calm | explore (20 seeds) | repro seed | confirm | passing seed | fingerprint |
|---|---|---|---|---|---|---|---|---|---|---|
