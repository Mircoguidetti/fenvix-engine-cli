#!/bin/sh
cd /tmp/pm-p1/repos/codex-multi-auth
for i in 1 2 3; do for e in wt-final4 wt-c2; do
  node /tmp/pm-p1/$e/node/bin/detjs.js vitest run --det --det-workers=1 > /tmp/pm-p1/codexrep-$e-$i.log 2>&1
  cp .detjs/trace.jsonl /tmp/pm-p1/codexrep-$e-$i.jsonl
done; done
echo CODEXREP-DONE >> /tmp/pm-p1/codexrep.log
