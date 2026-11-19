#!/bin/bash
S=/tmp/claude-0/-home-user-fenvix-engine-cli/32af3bec-41bb-5cba-9492-aa37cddbeea0/scratchpad/xd
O=$S/out/esphome; rm -rf $O; mkdir -p $O
export PYTHONPATH=$S/shim
A="--no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k not_udp_placeholder --timeout=120 -p xd_pertrace"
A="${A/not_udp_placeholder/not udp}"
export TMO=2400
run() { $S/bin/variant.sh esphome "$@"; }
cd $S/repos/esphome
$S/venvs/esphome/bin/python -m pytest -p no:cacheprovider -q --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -k "not udp" --collect-only -o addopts= 2>/dev/null | tail -n 1 > $O/collect.txt
run plain-serial2 --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120
run plain-n4c --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 -n 4
run det-serial-a --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 --det --det-trace=$O/ser-a.jsonl
run det-n4-a --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 -p xd_pertrace -n 4 --det --det-trace=$O/n4-a.jsonl
run det-serial-b --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 --det --det-trace=$O/ser-b.jsonl
run det-n4-b --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 -p xd_pertrace -n 4 --det --det-trace=$O/n4-b.jsonl
run cache-n4-cold --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 -p xd_pertrace -n 4 --det --det-cache=$O/cache-n4 --det-trace=$O/c4-cold.jsonl
run cache-n4-warm --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 -p xd_pertrace -n 4 --det --det-cache=$O/cache-n4 --det-trace=$O/c4-warm.jsonl
run cache-ser-cold --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 --det --det-cache=$O/cache-ser --det-trace=$O/cs-cold.jsonl
run cache-ser-warm --no-cov tests --ignore=tests/integration --ignore=tests/benchmarks -p no:randomly -k "not udp" --timeout=120 --det --det-cache=$O/cache-ser --det-trace=$O/cs-warm.jsonl
echo DONE >> $S/logs/summary.txt
