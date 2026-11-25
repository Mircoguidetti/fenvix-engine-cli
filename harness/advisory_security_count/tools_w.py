"""Reading helper: turn compact spec lines ("I|class|sub|quote" / "E|reason|quote") into a batch label file."""
import json
import sys

import reading as RD

b = int(sys.argv[1])
o = RD.order()[b * 20:(b + 1) * 20]
lines = [l.rstrip("\n") for l in sys.stdin if l.strip()]
assert len(lines) == len(o), (len(lines), len(o))
with open(f"batches/b{b:03d}.jsonl", "w") as f:
    for g, l in zip(o, lines):
        p = l.split("|", 3)
        if p[0] == "I":
            d = dict(inclusion="included", reason=None, subclass=p[2] or None, quote=p[3] if len(p) > 3 else None)
            d["class"] = p[1]
        else:
            q = l.split("|", 2)[2] if l.count("|") >= 2 else None
            d = dict(inclusion="excluded", reason=p[1], subclass=None, quote=q or None)
            d["class"] = None
        f.write(json.dumps(dict(ghsa_id=g, reader="session", batch=b, **d)) + "\n")
