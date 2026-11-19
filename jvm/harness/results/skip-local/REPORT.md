# Skip with proof on Java/Kotlin repositories (JVM shell)

Every commit's whole suite ran with the capture on (`--det --deps`); each reuse decided by the proof rule from the previous commit's capture was checked against that commit's fresh outcome. MEASURED on GitHub-hosted runners. The per-module column is an ESTIMATED model of Gradle's build cache for test tasks (a module's tests are reused only when every output file of the module and its jar list are unchanged; per task, not per test).

| repository | tool | transitions | tests (median) | time skipped with proof, median / mean | tests skipped, median | verified reuses | wrong | flaky | not verifiable | per-module cache model: time skipped, median / mean | top rerun reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|
| commons-lang | maven | 43 | 107537 | **98% / 92%** | 99% | 4287287 | 4 | 59 | 0 | 0% / 35% | code 822040, prop 17232, after 3649, not-passed 1572 |
| gson | maven | 50 | 4641 | **84% / 65%** | 90% | 171571 | 0 | 0 | 0 | 0% / 22% | code 27311, runtime 23177, config 9325, not-passed 980 |
| jsoup | maven | 50 | 2054 | **77% / 57%** | 91% | 71952 | 0 | 0 | 0 | 0% / 0% | code 19517, config 4112, runtime 4074, prop 3128 |

Verified reuses: 4530810; wrong: **4**; flaky (failed fresh, passed and failed on reruns): 59; not verifiable (the fresh run's capture lost the test's end event: no outcome): 0.

