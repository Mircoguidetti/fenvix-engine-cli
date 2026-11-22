#!/bin/bash
cd $PM/repos/networkx; unset CI GITHUB_ACTIONS NODE_OPTIONS PYTEST_ADDOPTS
A="--doctest-modules --pyargs networkx -q -p no:cacheprovider"
t(){ s=$(date +%s.%N); "$@"; echo "EXIT $? WALL $(echo "$(date +%s.%N) - $s" | bc)"; }
echo "== bare"; t $PM/venv/networkx/bin/python -m pytest $A -p no:detpy > $PM/out/networkx/bare.log 2>&1; tail -2 $PM/out/networkx/bare.log
echo "== plain"; t $PM/venv/networkx/bin/python -m pytest $A --det-outcomes=$PM/out/networkx/plain.outcomes.json > $PM/out/networkx/plain.log 2>&1; tail -2 $PM/out/networkx/plain.log
rm -rf .detpy
echo "== S1 pyspy"; t $PM/venv/networkx/bin/py-spy record -r 50 -f raw -o $PM/out/networkx/S1.pyspy.txt --native -- $PM/venv/networkx/bin/python -m pytest $A --det --det-trace=$PM/out/networkx/S1.jsonl > $PM/out/networkx/S1.log 2>&1; tail -3 $PM/out/networkx/S1.log
echo "== S2"; t $PM/venv/networkx/bin/python -m pytest $A --det --det-trace=$PM/out/networkx/S2.jsonl > $PM/out/networkx/S2.log 2>&1; tail -3 $PM/out/networkx/S2.log
echo "== verify"; cd $PM/out/networkx; $PM/venv/networkx/bin/python -m detpy.fenvix verify S1.jsonl S2.jsonl --json > v12.json; echo verify exit $?
echo ALLDONE
