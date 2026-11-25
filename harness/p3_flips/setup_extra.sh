#!/usr/bin/env bash
# P3 A (coordinator 2026-11-25 21:56, founder D1 = A): count-only repositories alakajam, drydock, agentlang, from
# their harness/parallel_measure/specs.json entries (commit and install line).
#   PM_WORK=/tmp/pm-p3 bash harness/p3_flips/setup_extra.sh
set -eux
PM_WORK="${PM_WORK:?}"
fetch() { mkdir -p "$1" && (cd "$1" && git init -q && git fetch -q --depth 1 "https://github.com/$2" "$3" && git checkout -q FETCH_HEAD); }
mkdir -p "$PM_WORK/repos" "$PM_WORK/fr"
fetch "$PM_WORK/repos/alakajam" alakajam-team/alakajam af63a7e0993f2f7de2ec8dff53a941ccfe855572
(cd "$PM_WORK/repos/alakajam" && npm ci --ignore-scripts --no-audit --no-fund && npm rebuild sqlite3)
fetch "$PM_WORK/repos/agentlang" agentlang-ai/agentlang f02e27199b193096c19985b7877ad1644974507a
(cd "$PM_WORK/repos/agentlang" && npx -y pnpm@10.28.2 install --frozen-lockfile --ignore-scripts && npx -y pnpm@10.28.2 rebuild better-sqlite3)
fetch "$PM_WORK/fr/CodesWhat_drydock" CodesWhat/drydock ce562a6a84c91b7e101398766d7de560cd18e35f
(export PATH=/opt/node24/bin:$PATH; node --version; cd "$PM_WORK/fr/CodesWhat_drydock" && npm ci --ignore-scripts --no-audit --no-fund && cd app && npm ci --ignore-scripts --no-audit --no-fund)
echo EXTRA-SETUP-DONE
