#!/usr/bin/env python3
"""Independent double read (PREREG §2.6).

  doubleread.py prepare CHECKPOINT       write doubleread/<cp>/input.jsonl (material only, Random(7) order) and
                                         slice-<k>.txt reading views of about 20 rows each
  doubleread.py add CHECKPOINT FILE      validate second-reader labels (JSON lines) and append to labels-2.jsonl
  doubleread.py stats CHECKPOINT         kappa (ours vs not-ours), confirmed share, disputes

The checkpoint prefix is the reading order up to and including the 300th included row (rules.checkpoint_prefix);
for an "all read" checkpoint it is the whole order.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch as F  # noqa: E402
import reading as RD  # noqa: E402
import rules as R  # noqa: E402

SLICE = 20


def cp_dir(cp: str) -> Path:
    return HERE / "doubleread" / cp


def prefix_ids(cp: str) -> list[str]:
    o, labs = RD.order(), RD.load_labels()
    if cp.startswith("cp300"):
        n = R.checkpoint_prefix(o, labs)
        if n is None:
            raise SystemExit("no 300th included row yet")
        return o[:n]
    return [g for g in o if g in labs]


def effective_labels(ids: list[str]) -> dict[str, dict]:
    labs, mats = RD.load_labels(), F.load_material()
    return {g: R.effective_label(labs[g], R.material_text(mats[g])) for g in ids if g in labs}


def sample(cp: str) -> list[str]:
    ids = prefix_ids(cp)
    return R.double_read_sample(effective_labels(ids), ids)


def prepare(cp: str) -> None:
    d = cp_dir(cp)
    d.mkdir(parents=True, exist_ok=True)
    mats = F.load_material()
    ids = R.double_read_input_order(sample(cp))
    keep = ("ghsa_id", "summary", "description", "cwes", "references", "packages", "source_code_location", "fixes")
    with (d / "input.jsonl").open("w") as f:
        for g in ids:
            f.write(json.dumps({k: mats[g].get(k) for k in keep}) + "\n")
    for k in range(0, len(ids), SLICE):
        view = [RD.compact(mats[g], desc_chars=6000, diff_lines=30).replace(f" pos={mats[g].get('pos')}", "")
                for g in ids[k:k + SLICE]]
        (d / f"slice-{k // SLICE + 1}.txt").write_text("\n\n".join(view) + "\n")
    print(len(ids), "rows;", (len(ids) + SLICE - 1) // SLICE, "slices")


def load2(cp: str) -> dict[str, dict]:
    p = cp_dir(cp) / "labels-2.jsonl"
    return RD.load_labels(p) if p.exists() else {}


def add(cp: str, path: str) -> None:
    mats = F.load_material()
    want = set(sample(cp))
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    errs = []
    for r in rows:
        if r.get("ghsa_id") not in want:
            errs.append(f"{r.get('ghsa_id')}: not in the double-read sample")
            continue
        errs += [f"{r['ghsa_id']}: {e}" for e in R.validate_label(r)]
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    with (cp_dir(cp) / "labels-2.jsonl").open("a") as f:
        for r in rows:
            r2 = R.effective_label(r, R.material_text(mats[r["ghsa_id"]]))
            f.write(json.dumps({k: r2[k] for k in R.LABEL_FIELDS}) + "\n")
    print("added", len(rows))


def stats(cp: str) -> dict:
    ids = sample(cp)
    first = effective_labels(prefix_ids(cp))
    second = load2(cp)
    missing = [g for g in ids if g not in second]
    pairs = [(R.is_ours(first[g]), R.is_ours(second[g])) for g in ids if g in second]
    ours1 = [g for g in ids if R.is_ours(first[g])]
    confirmed = [g for g in ours1 if g in second and R.is_ours(second[g])]
    _, disputed = R.apply_disputes({g: first[g] for g in ids}, {g: second[g] for g in ids if g in second})
    out = {"sample": len(ids), "second_read": len(pairs), "missing": missing, "kappa": R.cohen_kappa(pairs),
           "ours_first": len(ours1), "confirmed": len(confirmed),
           "confirmed_share": len(confirmed) / len(ours1) if ours1 else None, "disputed": disputed,
           "second_only_ours": sorted(g for g in ids if g in second and R.is_ours(second[g])
                                      and not R.is_ours(first[g]))}
    out["ok"] = R.double_read_ok(out["kappa"], out["confirmed_share"])
    return out


if __name__ == "__main__":
    cmd, cp = sys.argv[1], sys.argv[2]
    if cmd == "prepare":
        prepare(cp)
    elif cmd == "add":
        add(cp, sys.argv[3])
    elif cmd == "stats":
        print(json.dumps(stats(cp), indent=1))
    else:
        sys.exit(__doc__)
