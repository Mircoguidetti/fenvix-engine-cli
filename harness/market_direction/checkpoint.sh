#!/bin/bash
# Commits the discovery checkpoint and logs every 30 min while discover.py runs (work session).
cd "$(dirname "$0")/../.."
while pgrep -f "discover.py" >/dev/null; do
  sleep 1800
  git add harness/market_direction/discovery harness/market_direction/logs
  git commit -q -m "market-direction: discovery checkpoint (in progress)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YAF6DkSUDXwQikH19ZCnEu" || continue
  git pull -q --no-rebase --no-edit origin claude/market-direction-check && git push -q origin claude/market-direction-check
done
