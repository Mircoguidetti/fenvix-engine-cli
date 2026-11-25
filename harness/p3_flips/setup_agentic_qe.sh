#!/usr/bin/env bash
# P3 A1: agentic-qe from its harness/parallel_measure/specs.json entry (commit, install line incl. native rebuilds).
#   PM_WORK=/tmp/pm-p3 bash harness/p3_flips/setup_agentic_qe.sh
set -eux
PM_WORK="${PM_WORK:?}"
mkdir -p "$PM_WORK/repos/agentic-qe" && cd "$PM_WORK/repos/agentic-qe"
git init -q && git fetch -q --depth 1 https://github.com/proffesor-for-testing/agentic-qe 9a42d9ebd56ed419925738cef5cf84748a108d9e
git checkout -q FETCH_HEAD
npm ci --ignore-scripts --no-audit --no-fund
npm rebuild better-sqlite3 hnswlib-node argon2 sharp
echo AQE-SETUP-DONE
