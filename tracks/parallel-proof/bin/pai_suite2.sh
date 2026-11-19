#!/bin/bash
# pydantic-ai, second part: -n variants need -W "ignore:detpy:UserWarning" (pydantic-ai has filterwarnings = error,
# which turns detpy's "xdist is not supported" warning into an INTERNALERROR)
S=/tmp/claude-0/-home-user-fenvix-engine-cli/32af3bec-41bb-5cba-9492-aa37cddbeea0/scratchpad/xd
O=$S/out/pydantic-ai; mkdir -p $O; rm -rf $O/n4-* $O/ser-b* $O/cache-* $O/c4-* $O/cs-* $O/rc4-*
echo "--- pydantic-ai part 2 (-n runs with -W ignore:detpy:UserWarning)" >> $S/logs/summary.txt
export PYTHONPATH=$S/shim TMO=2400
SEL="tests/models tests/harness/code_mode tests/harness/refine_output tests/harness/detect_loops tests/providers/test_openai_compatible_http_clients.py"
W="-W ignore:detpy:UserWarning"
run() { $S/bin/variant.sh pydantic-ai "$@"; }
cd $S/repos/pydantic-ai
run det-n4-a $SEL -p no:randomly -m "not temporal" $W -p xd_pertrace -n 4 --dist=loadgroup --det --det-trace=$O/n4-a.jsonl
run det-n4-b $SEL -p no:randomly -m "not temporal" $W -p xd_pertrace -n 4 --dist=loadgroup --det --det-trace=$O/n4-b.jsonl
run det-serial-b $SEL -p no:randomly -m "not temporal" --det --det-trace=$O/ser-b.jsonl
run cache-n4-cold $SEL -p no:randomly -m "not temporal" $W -p xd_pertrace -n 4 --dist=loadgroup --det --det-cache=$O/cache-n4 --det-trace=$O/c4-cold.jsonl --det-cache-receipts=$O/rc4-cold.jsonl
run cache-n4-warm $SEL -p no:randomly -m "not temporal" $W -p xd_pertrace -n 4 --dist=loadgroup --det --det-cache=$O/cache-n4 --det-trace=$O/c4-warm.jsonl --det-cache-receipts=$O/rc4-warm.jsonl
run cache-ser-cold $SEL -p no:randomly -m "not temporal" --det --det-cache=$O/cache-ser --det-trace=$O/cs-cold.jsonl
run cache-ser-warm $SEL -p no:randomly -m "not temporal" --det --det-cache=$O/cache-ser --det-trace=$O/cs-warm.jsonl
echo PAI-DONE >> $S/logs/summary.txt
