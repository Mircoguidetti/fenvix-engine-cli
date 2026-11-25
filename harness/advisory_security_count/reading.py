#!/usr/bin/env python3
"""Reading tools for the first reader (PREREG §2.5).

  reading.py show BATCH                print the compact view of batch BATCH (reading positions 20*BATCH .. +19)
  reading.py add BATCH FILE            validate FILE (JSON lines, one label per row of the batch) and append to labels.jsonl
  reading.py status                    read, included, ours (effective), checkpoint state

The compact view is a reading aid only; quotes are checked against the full stored material (rules.material_text).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch as F  # noqa: E402
import rules as R  # noqa: E402

BATCH = 20
LABELS = HERE / "labels.jsonl"


def load_labels(path: Path = LABELS) -> dict[str, dict]:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                lab = json.loads(line)
                out[lab["ghsa_id"]] = lab  # a later line (re-read) replaces an earlier one
    return out


def order() -> list[str]:
    return json.loads((F.DATA / "order.json").read_text())


def compact(m: dict, desc_chars: int = 1100, diff_lines: int = 18) -> str:
    out = [f"=== {m['ghsa_id']} pos={m.get('pos')} sev={m.get('severity')} "
           f"pkgs={sorted({(p['ecosystem'] or '') + ':' + (p['name'] or '') for p in m.get('packages') or []})}",
           f"src={m.get('source_code_location')} cwes={[c['cwe_id'] for c in m.get('cwes') or []]}",
           f"SUMMARY: {m.get('summary')}"]
    d = " ".join((m.get("description") or "").split())
    out.append("DESC: " + d[:desc_chars] + (" [...]" if len(d) > desc_chars else ""))
    seen: set[str] = set()
    for fx in m.get("fixes") or []:
        out.append(f"FIX {fx['ref']['kind']} {fx['ref']['url']} status={fx.get('status')}")
        key = " ".join(((fx.get("commits") or [{}])[0].get("message") or "").split())[:80]
        if key and key in seen:
            out.append("  (same commit message as a fix above; diff not repeated)")
            continue
        seen.add(key)
        if fx.get("title"):
            out.append("  PR: " + " ".join(fx["title"].split()) + " | " + " ".join((fx.get("body") or "").split())[:400])
        if fx.get("message"):
            out.append("  MSGS: " + " ".join(fx["message"].split())[:400])
        for c in fx.get("commits") or []:
            if c.get("message"):
                out.append("  MSG: " + " ".join(c["message"].split())[:200])
            n = 0
            for f in c.get("files") or []:
                out.append(f"  FILE {f['filename']}")
                for ln in (f.get("patch") or "").split("\n"):
                    if n >= diff_lines:
                        break
                    if ln[:1] in "+-" and ln[1:].strip() and not ln.startswith(("+++", "---")):
                        out.append("    " + ln[:160])
                        n += 1
    return "\n".join(out)


def show(batch: int) -> None:
    mats = F.load_material()
    o = order()
    for i in range(batch * BATCH, min((batch + 1) * BATCH, len(o))):
        m = mats.get(o[i])
        print(compact(m) if m else f"=== {o[i]} pos={i} NO MATERIAL YET")
        print()


def add(batch: int, path: str) -> None:
    o = order()
    want = o[batch * BATCH:(batch + 1) * BATCH]
    mats = F.load_material()
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    errs = []
    if [r["ghsa_id"] for r in rows] != want:
        errs.append(f"ids/order differ from batch {batch}: {[r['ghsa_id'] for r in rows]} != {want}")
    for r in rows:
        r.setdefault("reader", "session")
        r["batch"] = batch
        errs += [f"{r['ghsa_id']}: {e}" for e in R.validate_label(r)]
        if r["inclusion"] == "included" and not R.quote_ok(r.get("quote"), R.material_text(mats[r["ghsa_id"]])):
            errs.append(f"{r['ghsa_id']}: quote not verbatim (row would be unclear): {r.get('quote')!r}")
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    with LABELS.open("a") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in R.LABEL_FIELDS}) + "\n")
    status()


def status() -> None:
    labs, o, mats = load_labels(), order(), F.load_material()
    read = [g for g in o if g in labs]
    inc = [g for g in read if labs[g]["inclusion"] == "included"]
    eff = {g: R.effective_label(labs[g], R.material_text(mats[g])) for g in inc}
    ours = sum(1 for g in inc if eff[g]["class"] == "ours")
    print(f"read {len(read)} of {len(o)} candidates; included {len(inc)}; ours {ours}; "
          f"checkpoint300 prefix {R.checkpoint_prefix(o, labs)}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "show":
        show(int(sys.argv[2]))
    elif cmd == "add":
        add(int(sys.argv[2]), sys.argv[3])
    elif cmd == "status":
        status()
    else:
        sys.exit(__doc__)
