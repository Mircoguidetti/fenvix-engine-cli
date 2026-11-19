# JVM Level 0 round on IDoFT projects (Maven)

Projects measured: 18 (prepared: 13; statuses: ok 13).

All numbers MEASURED on GitHub-hosted runners; timings NOISY.

* Documented IDoFT tests present in the runs: 496; reproduced (fail 10/10 with one fingerprint under a --det configuration, pass under another): **112/496 = 22.6%**.
* Documented tests unstable in our randomised baseline: 98.
* Tests unstable in the baseline (any test): 107; reproduced: **68 = 63.6%**.
* Broken by --det: **29** of 10621 tests.
* Fingerprint coverage (one fingerprint in all 10 seed-0 runs): 10652/10857 = 98.1%.
* Slowdown of --det (median over projects of the median test-time ratio, quiet serial pass, NOISY): **+4.1%** (min -85.9%, max +128.6%).

| project | jdk | tests | documented (categories) | doc. reproduced | baseline-unstable | reproduced | broken by --det | fingerprint coverage | slowdown | seeds |
|---|---|---|---|---|---|---|---|---|---|---|
| Java-WebSocket | 8 | 146 | 54 (NDOD 2, NDOD;OD-Vic;TD 1, NDOD;TD 29, TD 22) | 0 | 22 | 0 | 2 | 123/146 | +27.9% | 20 |
| Mapper-base | 8 | 206 | 70 (OD 5, OD-Vic 65) | 58 | 70 | 58 | 0 | 206/206 | +16.0% | 20 |
| avro-ipc-jetty | 8 | 35 | 20 (OD 20) | 0 | 0 | 0 | 0 | 29/35 | -21.0% | 20 |
| biojava-biojava-structure | 8 | 355 | 16 (NOD 16) | 0 | 0 | 0 | 8 | 355/355 | -85.9% | 20 |
| c2mon-c2mon-daq-core | 8 | 125 | 2 (NDOD 1, NOD;UD 1) | 0 | 0 | 0 | 1 | 100/125 | +9.7% | 20 |
| cat-cat-client | 8 | 67 | 2 (NOD 2) | 0 | 1 | 0 | 2 | 30/67 | +128.6% | 20 |
| easyexcel | 8 | 108 | 2 (OD 2) | 2 | 1 | 0 | 0 | 107/108 | +36.6% | 20 |
| fastjson | 8 | 4464 | 19 (NDOD 2, NOD 2, OD 15) | 3 | 2 | 1 | 1 | 4454/4464 | +4.7% | 20 |
| http-request-lib | 8 | 163 | 28 (OD-Vic 28) | 0 | 0 | 0 | 0 | 118/163 | +23.3% | 20 |
| hutool-hutool-core | 8 | 1077 | 2 (OD 2) | 0 | 1 | 1 | 1 | 1076/1077 | -56.4% | 20 |
| incubator-seata-common | 8 | 552 | 2 (OD 2) | 2 | 8 | 8 | 1 | 552/552 | -41.2% | 20 |
| java | 8 | 347 | 19 (OD 19) | 4 | 0 | 0 | 10 | 333/333 | -19.9% | 20 |
| junit-quickcheck-core | 8 | 484 | 122 (ID;NIO 3, NIO 118, NIO;OD 1) | 3 | 0 | 0 | 0 | 734/734 | -58.8% | 20 |
| mTracker-core | 8 | 38 | 2 (NIO 2) | 0 | 2 | 0 | 2 | 36/38 | -10.8% | 20 |
| marine-api | 8 | 926 | 12 (OD-Vic 12) | 12 | 0 | 0 | 0 | 925/926 | +2.1% | 20 |
| openhtmltopdf-openhtmltopdf-examples | 8 | 258 | 34 (OD 34) | 0 | 0 | 0 | 1 | 258/258 | +3.6% | 20 |
| ormlite-core | 8 | 1220 | 87 (OD-Vic 87) | 26 | 0 | 0 | 0 | 1167/1220 | +19.1% | 20 |
| wikidata-toolkit-wdtk-dumpfiles | 8 | 50 | 3 (OD-Brit 3) | 2 | 0 | 0 | 0 | 49/50 | +9.2% | 20 |
