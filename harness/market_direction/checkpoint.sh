#!/bin/bash
# Every 30 min while discover.py runs: copy live/discovery and live/logs into the tracked folders, commit, push.
cd "$(dirname "$0")"
snap() {
  cp live/discovery/* discovery/ && cp live/logs/* logs/
  cd ../..
  git add harness/market_direction/discovery harness/market_direction/logs
  git commit -q -m "market-direction: discovery checkpoint ($1)

Claude-Session: https://claude.ai/code/session_01YAF6DkSUDXwQikH19ZCnEu" && \
  git pull -q --no-rebase --no-edit origin claude/market-direction-check && git push -q origin claude/market-direction-check
  cd harness/market_direction
}
while pgrep -f "discover.py" >/dev/null; do sleep 1800; snap "in progress"; done
snap "discover.py ended"
