#!/bin/bash
S=/tmp/claude-0/-home-user-fenvix-engine-cli/32af3bec-41bb-5cba-9492-aa37cddbeea0/scratchpad/xd
O=$S/out/pydantic-ai; rm -rf $O; mkdir -p $O; echo "--- pydantic-ai restart after container restart (plain runs kept)" >> $S/logs/summary.txt
export PYTHONPATH=$S/shim TMO=2400
SEL="tests/models tests/harness/code_mode tests/harness/refine_output tests/harness/detect_loops tests/providers/test_openai_compatible_http_clients.py"
B="-p no:randomly -m not_temporal_ph --timeout=300"
run() { $S/bin/variant.sh pydantic-ai "$@"; }
cd $S/repos/pydantic-ai
args() { echo; }
run det-serial-a $SEL -p no:randomly -m "not temporal" --det --det-trace=$O/ser-a.jsonl
run det-n4-a $SEL -p no:randomly -m "not temporal" -p xd_pertrace -n 4 --dist=loadgroup --det --det-trace=$O/n4-a.jsonl
run det-serial-b $SEL -p no:randomly -m "not temporal" --det --det-trace=$O/ser-b.jsonl
run det-n4-b $SEL -p no:randomly -m "not temporal" -p xd_pertrace -n 4 --dist=loadgroup --det --det-trace=$O/n4-b.jsonl
run cache-n4-cold $SEL -p no:randomly -m "not temporal" -p xd_pertrace -n 4 --dist=loadgroup --det --det-cache=$O/cache-n4 --det-trace=$O/c4-cold.jsonl --det-cache-receipts=$O/rc4-cold.jsonl
run cache-n4-warm $SEL -p no:randomly -m "not temporal" -p xd_pertrace -n 4 --dist=loadgroup --det --det-cache=$O/cache-n4 --det-trace=$O/c4-warm.jsonl --det-cache-receipts=$O/rc4-warm.jsonl
run cache-ser-cold $SEL -p no:randomly -m "not temporal" --det --det-cache=$O/cache-ser --det-trace=$O/cs-cold.jsonl
run cache-ser-warm $SEL -p no:randomly -m "not temporal" --det --det-cache=$O/cache-ser --det-trace=$O/cs-warm.jsonl
echo PAI-DONE >> $S/logs/summary.txt
