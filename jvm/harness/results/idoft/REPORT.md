# JVM Level 0 round on IDoFT projects (Maven)

Projects measured: 10 (prepared: 0; statuses: ).

All numbers MEASURED on GitHub-hosted runners; timings NOISY.

* Documented IDoFT tests present in the runs: 469; reproduced (fail 10/10 with one fingerprint under a --det configuration, pass under another): **94/469 = 20.0%**.
* Documented tests unstable in our randomised baseline: 94.
* Tests unstable in the baseline (any test): 94; reproduced: **59 = 62.8%**.
* Broken by --det: **22** of 7678 tests.
* Fingerprint coverage (one fingerprint in all 10 seed-0 runs): 7777/7914 = 98.3%.
* Slowdown of --det (median over projects of the median test-time ratio, quiet serial pass, NOISY): **+4.1%** (min -85.9%, max +27.9%).

| project | jdk | tests | documented (categories) | doc. reproduced | baseline-unstable | reproduced | broken by --det | fingerprint coverage | slowdown | seeds |
|---|---|---|---|---|---|---|---|---|---|---|
| Java-WebSocket | 8 | 146 | 54 (NDOD 2, NDOD;OD-Vic;TD 1, NDOD;TD 29, TD 22) | 0 | 22 | 0 | 2 | 123/146 | +27.9% | 20 |
| Mapper-base | 8 | 206 | 70 (OD 5, OD-Vic 65) | 58 | 70 | 58 | 0 | 206/206 | +16.0% | 20 |
| avro-ipc-jetty | 8 | 35 | 20 (OD 20) | 0 | 0 | 0 | 0 | 29/35 | -21.0% | 20 |
| biojava-biojava-structure | 8 | 355 | 16 (NOD 16) | 0 | 0 | 0 | 8 | 355/355 | -85.9% | 20 |
| fastjson | 8 | 4464 | 19 (NDOD 2, NOD 2, OD 15) | 3 | 2 | 1 | 1 | 4454/4464 | +4.7% | 20 |
| http-request-lib | 8 | 163 | 28 (OD-Vic 28) | 0 | 0 | 0 | 0 | 118/163 | +23.3% | 20 |
| java | 8 | 347 | 19 (OD 19) | 4 | 0 | 0 | 10 | 333/333 | -19.9% | 20 |
| junit-quickcheck-core | 8 | 484 | 122 (ID;NIO 3, NIO 118, NIO;OD 1) | 3 | 0 | 0 | 0 | 734/734 | -58.8% | 20 |
| openhtmltopdf-openhtmltopdf-examples | 8 | 258 | 34 (OD 34) | 0 | 0 | 0 | 1 | 258/258 | +3.6% | 20 |
| ormlite-core | 8 | 1220 | 87 (OD-Vic 87) | 26 | 0 | 0 | 0 | 1167/1220 | +19.1% | 20 |
