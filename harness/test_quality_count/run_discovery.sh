#!/bin/bash
# §1 discovery driver (work session): 30-minute slices of discover.py, a checkpoint commit and push after each slice.
# Resumable: discover.py continues from results/discovery_state.json. Exits when discovery has finished.
cd "$(dirname "$0")/../.." || exit 1
D=harness/test_quality_count
for slice in $(seq 1 "${1:-4}"); do
  python3 $D/discover.py --route session --max-minutes 30 >> $D/results/discovery.log 2>> $D/results/discovery.err
  rc=$?
  git add -f $D/results/discovery_state.json $D/results/discovery $D/results/discovery.log $D/results/discovery.err
  git commit -q -m "test-quality-count: discovery checkpoint (slice $slice, rc $rc)

Claude-Session: https://claude.ai/code/session_01YAF6DiwFH3KnDBPwe9xkwn" || true
  for i in 1 2 3 4; do git push -q origin claude/test-quality-count && break; git pull -q --no-rebase --no-edit origin claude/test-quality-count; sleep $((2**i)); done
  echo "slice $slice rc $rc $(python3 -c "import json;s=json.load(open('$D/results/discovery_state.json'));print('finished' if s.get('finished') else 'running', sum(q.get('done',False) for q in s['queries'].values()), 'queries done of', len(s['queries']))")"
  python3 -c "import json,sys;sys.exit(0 if json.load(open('$D/results/discovery_state.json')).get('finished') else 1)" && { echo DISCOVERY_FINISHED; exit 0; }
  [ $rc -ne 0 ] && { echo "DISCOVERY_ERROR rc $rc"; exit $rc; }
done
echo SLICES_DONE
