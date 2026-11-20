# Skip with proof on Java/Kotlin repositories (JVM shell)

Every commit's whole suite ran with the capture on (`--det --deps`); each reuse decided by the proof rule from the previous commit's capture was checked against that commit's fresh outcome. MEASURED on GitHub-hosted runners. The per-module column is an ESTIMATED model of Gradle's build cache for test tasks (a module's tests are reused only when every output file of the module and its jar list are unchanged; per task, not per test).

| repository | tool | transitions | tests (median) | time skipped with proof, median / mean | tests skipped, median | verified reuses | wrong | flaky | not verifiable | per-module cache model: time skipped, median / mean | top rerun reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|
| commons-io | maven | 50 | 2102 | **100% / 88%** | 99% | 98563 | 0 | 0 | 0 | 0% / 44% | config 2175, runtime 2091, code 2039, not-passed 550 |
| commons-lang | maven | 50 | 107583 | **98% / 91%** | 99% | 5133250 | 0 | 37 | 0 | 0% / 26% | code 786675, prop 17355, after 3657, not-passed 1790 |
| gson | maven | 50 | 4641 | **76% / 63%** | 89% | 163138 | 0 | 0 | 0 | 0% / 38% | runtime 32489, code 26419, config 9325, not-passed 978 |
| jackson-databind | maven | 48 | 7803 | **93% / 66%** | 98% | 276259 | 0 | 0 | 0 | 100% / 94% | code 74323, runtime 23406, after 162, not-passed 48 |
| mockito | gradle | 50 | 2660 | **34% / 27%** | 6% | 7863 | 0 | 0 | 21 | 98% / 76% | config 75439, code 35237, not-passed 7169, runtime 5119 |
| moshi | gradle | 50 | 1521 | **19% / 14%** | 96% | 52667 | 0 | 0 | 1 | 56% / 54% | runtime 8946, config 8336, code 3926, not-passed 1501 |

Verified reuses: 5731740; wrong: **0**; flaky (failed fresh, passed and failed on reruns): 37; not verifiable (the fresh run's capture lost the test's end event: no outcome): 22.

