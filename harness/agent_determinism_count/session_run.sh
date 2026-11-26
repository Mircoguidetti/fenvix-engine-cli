#!/usr/bin/env bash
# S1 (code search) discovery from the work session on the session route (coordinator 2026-11-26 09:30Z: the §0.2a
# re-probe tied on total_count and the session route is faster). Resumes results/discovery_state_code.json with the
# same budget_end; leaves go to results/discovery/leaves_code/code-session.jsonl.gz, which is committed to git (the
# index marks it in_git). Checkpoint commits every 30 minutes, and one at the end. $1: max minutes (default 110).
# Every request is GET; commits touch only the files listed in $files.
set -u
cd "$(git rev-parse --show-toplevel)"
d=harness/agent_determinism_count
r=$d/results
export ADC_PART_ID=session
files="$r/discovery_state_code.json $r/discovery/splits_code.jsonl $r/discovery/leaf_parts_code.json
       $r/discovery/leaves_code/code-session.jsonl.gz"
commit() {
  python3 "$d/parts.py" index >/dev/null || true
  local have=""
  for f in $files; do [ -e "$f" ] && have="$have $f"; done
  [ -n "$have" ] || return 0
  git add -f $have
  git commit -q -m "agent-determinism-count: S1 session route ($1)

Claude-Session: https://claude.ai/code/session_01YAF6Di2sbL9QooPnD2zoVc" -- $have || return 0
  for i in 1 2 3 4; do
    git pull -q --rebase --autostash origin claude/agent-determinism-count && \
      git push -q origin HEAD:claude/agent-determinism-count && return 0
    sleep $((2 ** i * 5))
  done
  echo "push failed" >&2
}
( while sleep 1800; do commit "checkpoint $(date -u +%H:%MZ)"; done ) &
cp=$!
python3 "$d/discover.py" run --family code --route session --max-minutes "${1:-110}"
rc=$?
pkill -P "$cp" 2>/dev/null; kill "$cp" 2>/dev/null
commit "chunk end $(date -u +%H:%MZ), rc $rc"
echo "session_run rc $rc"
exit $rc
