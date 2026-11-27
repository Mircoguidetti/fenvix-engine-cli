#!/usr/bin/env bash
# Copied from claude/p2-speed b0d94fab harness/p2/setup_repos.sh (the pool of P2 Phase A), unchanged below this line.
# P2: fetch and install the 9 pool repositories at the commit of their spec (harness/parallel_measure/specs.json),
# with the spec's `install` line. Usage: PM_WORK=$HOME/pm bash harness/p2/setup_repos.sh [repo ...]
set -u
: "${PM_WORK:?set PM_WORK (outside the checkout, not under /tmp)}"
fetch() { # dir url commit
  mkdir -p "$1" && (cd "$1" && { [ -d .git ] || git init -q; } && git fetch -q --depth 1 "$2" "$3" && git checkout -q FETCH_HEAD)
}
one() {
  case "$1" in
  nestjs-pino) fetch $PM_WORK/repos/nestjs-pino https://github.com/iamolegga/nestjs-pino 82d92198747c64e87057dfb50c6215a936a1a052 &&
    (cd $PM_WORK/repos/nestjs-pino && npm ci --ignore-scripts --no-audit --no-fund) ;;
  agentsys) fetch $PM_WORK/repos/agentsys https://github.com/agent-sh/agentsys ce58913304d88a1d1a0513e1837ae43c33f5f6f5 &&
    (cd $PM_WORK/repos/agentsys && npm ci --ignore-scripts --no-audit --no-fund) ;;
  alakajam) fetch $PM_WORK/repos/alakajam https://github.com/alakajam-team/alakajam af63a7e0993f2f7de2ec8dff53a941ccfe855572 &&
    (cd $PM_WORK/repos/alakajam && npm ci --ignore-scripts --no-audit --no-fund && npm rebuild sqlite3) ;;
  agentlang) fetch $PM_WORK/repos/agentlang https://github.com/agentlang-ai/agentlang f02e27199b193096c19985b7877ad1644974507a &&
    (cd $PM_WORK/repos/agentlang && npx -y pnpm@10.28.2 install --frozen-lockfile --ignore-scripts && npx -y pnpm@10.28.2 rebuild better-sqlite3) ;;
  yalc) fetch $PM_WORK/repos/YALC-the-GTM-operating-system https://github.com/Othmane-Khadri/YALC-the-GTM-operating-system 5686d1f2f526346133f78eef3349fc5a655757b4 &&
    (cd $PM_WORK/repos/YALC-the-GTM-operating-system && npx -y pnpm@10.30.3 install --frozen-lockfile --ignore-scripts &&
     cd web && npx -y pnpm@10.30.3 install --frozen-lockfile --ignore-scripts --ignore-workspace) ;;
  ironcurtain) fetch $PM_WORK/repos/ironcurtain https://github.com/provos/ironcurtain abf2b44c2e1b6138ede2d0b46337c684258088d0 &&
    (cd $PM_WORK/repos/ironcurtain && npm ci --ignore-scripts --no-audit --no-fund) ;;
  codex-multi-auth) fetch $PM_WORK/repos/codex-multi-auth https://github.com/ndycode/codex-multi-auth b9886168aafcebd8581d4e344daf7abd19b510ce &&
    (cd $PM_WORK/repos/codex-multi-auth && npm ci --ignore-scripts --no-audit --no-fund) ;;
  drydock) fetch $PM_WORK/fr/CodesWhat_drydock https://github.com/CodesWhat/drydock ce562a6a84c91b7e101398766d7de560cd18e35f &&
    (cd $PM_WORK/fr/CodesWhat_drydock && PATH=/opt/node24/bin:$PATH npm ci --ignore-scripts --no-audit --no-fund &&
     cd app && PATH=/opt/node24/bin:$PATH npm ci --ignore-scripts --no-audit --no-fund) ;;
  lerna-lite) fetch $PM_WORK/repos/lerna-lite https://github.com/lerna-lite/lerna-lite fec3cb9660bac71efe5d5e5749f615a3802c1cc1 &&
    (cd $PM_WORK/repos/lerna-lite && npx -y pnpm@11.28.5 install --frozen-lockfile --ignore-scripts && npx -y pnpm@11.28.5 build) ;;
  *) echo "unknown repo $1"; return 2 ;;
  esac
}
repos=("$@"); [ ${#repos[@]} -eq 0 ] && repos=(nestjs-pino agentsys alakajam agentlang yalc ironcurtain codex-multi-auth drydock lerna-lite)
rc=0
for r in "${repos[@]}"; do
  echo "=== $r"; if one "$r" > "$PM_WORK/setup-$r.log" 2>&1; then echo "OK $r"; else echo "FAIL $r (exit $?): $(tail -3 $PM_WORK/setup-$r.log)"; rc=1; fi
done
exit $rc
