# working notes (partial results, pricing study)
- web blocked (docs.github.com, aws.amazon.com rejected by proxy; api.github.com 403). Prices from knowledge.
- HA ci.yaml: 1 python version; full run = 10 pytest-full groups + 7 mariadb + 3 postgres + 2 sqlite + ~13 lint/build jobs; partial run when only integrations change (tests only touched integrations, 1 group).
- MEASURED job minutes (skip_study2 flaky reruns, GitHub 4 vCPU, job_s = install+build+test, excl. runner boot/checkout): HA 8.8/group (test 7.0) x10 groups; terraform 5.3 (test 4.8); docusaurus 1.1 (test 0.3); vue-core 0.7 (test 0.5).
- saleor: sum of test durations full suite ~46 CPU-min (15% sample scaled); CI = 1 unit_tests job, -n logical. Job ESTIMATED 18 min.
- saleor latest closure 0%/13% (29 transitions, aggregate --md, partial).
- idle_study: median test-step wall of 19 suites 198 s; median busy cores 2.76 of 4 -> CPU-bound, no packing gain.
- HA CI already runs partial (only touched integrations) on integration-only PRs; full suite on dev pushes/core changes.
- capture overhead (strace, MEASURED sum_traced/sum_plain): HA 2.06, docusaurus 1.54, vue-core 1.56, saleor 2.63; Go not recorded.
- plan: model.py in pricing/, PR-run shapes ESTIMATED from workflows (cloned sparse to /home/user/wf).
