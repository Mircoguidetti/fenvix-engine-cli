Synthetic cross-worker write/read project of PARALLEL-PROOF-DESIGN.md 1.4.5. `SHARED` points to a file outside
the repository (the absolute scratch path used in the run). Sequence: three `pytest --det --det-cache=.c -n 2
--dist loadfile -p xd_pertrace --det-cache-receipts=rcN.jsonl tests` sessions with `value.txt` = x, x, y; then a
fresh serial `pytest tests`. `cfg-serial.json` / `cfg-gw0.json`: `proofcache.config_identity` info of a serial
session and of an xdist worker (they differ only in xdist's `loadgroup` option).
