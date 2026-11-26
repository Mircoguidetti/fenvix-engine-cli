#!/usr/bin/env bash
# Discovery from the work session on the session route, in harness-tracked chunks.
#   session_run.sh code [max_minutes]   S1 (coordinator 2026-11-26 09:30Z route switch; finished 10:13Z)
#   session_run.sh s3ext [max_minutes]  the founder's S3 extension (2026-11-26 11:25Z decision): only the S3 queries
#                                       the 24 h budget left unstarted or unfinished, 6 h from its first request
# Resumes the committed state. Leaf parts are committed to git (the index marks them in_git): code-session for S1,
# one s3ext-session-<HHMM> part per chunk for the extension (each chunk's part stays far below GitHub's 100 MB).
# Checkpoint commits every 30 minutes and one at the end. Every request is GET; commits touch only $files.
set -u
cd "$(git rev-parse --show-toplevel)"
d=harness/agent_determinism_count
r=$d/results
mode=${1:-code}
mins=${2:-110}
if [ "$mode" = s3ext ]; then
  export ADC_PART_ID="session-$(date -u +%H%M)"
  files="$r/discovery_state_s3ext.json $r/discovery/splits_s3ext.jsonl $r/discovery/leaf_parts_s3ext.json
         $r/discovery/leaves_s3ext"
  cmd=(python3 "$d/discover.py" run --family text --route session --extension --max-minutes "$mins")
else
  export ADC_PART_ID=session
  files="$r/discovery_state_code.json $r/discovery/splits_code.jsonl $r/discovery/leaf_parts_code.json
         $r/discovery/leaves_code/code-session.jsonl.gz"
  cmd=(python3 "$d/discover.py" run --family code --route session --max-minutes "$mins")
fi
commit() {
  python3 "$d/parts.py" index >/dev/null || true
  local have=""
  for f in $files; do [ -e "$f" ] && have="$have $f"; done
  [ -n "$have" ] || return 0
  git add -f $have
  git commit -q -m "agent-determinism-count: $mode session route ($1)

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
"${cmd[@]}"
rc=$?
pkill -P "$cp" 2>/dev/null; kill "$cp" 2>/dev/null
commit "chunk end $(date -u +%H:%MZ), rc $rc"
echo "session_run $mode rc $rc"
exit $rc
