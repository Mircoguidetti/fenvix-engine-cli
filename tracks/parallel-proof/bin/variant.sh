#!/bin/bash
# variant.sh <repo> <label> <extra args...> ; runs pytest in repo with timing, logs to logs/<repo>-<label>.log
S=/tmp/claude-0/-home-user-fenvix-engine-cli/32af3bec-41bb-5cba-9492-aa37cddbeea0/scratchpad/xd
repo=$1; label=$2; shift 2
cd $S/repos/$repo
log=$S/logs/$repo-$label.log
t0=$(date +%s.%N)
timeout ${TMO:-3600} $S/venvs/$repo/bin/python -m pytest -p no:cacheprovider -q -rfE --junitxml=$S/logs/$repo-$label.xml "$@" > $log 2>&1
rc=$?
t1=$(date +%s.%N)
w=$(python3 -c "print(round($t1-$t0,1))")
echo "$repo $label rc=$rc wall=${w}s :: $(tail -n 1 $log)" | tee -a $S/logs/summary.txt
