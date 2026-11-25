#!/usr/bin/env python3
"""Re-derive the count from committed files; exit 1 on any mismatch.

Checks: (1) PREREG.md was committed before the first data file (git order); (2) the frame and the reading order
re-derive from the committed listing; (3) every label validates against the closed lists, labels form a prefix of
the reading order, and every included row's quote is a verbatim (whitespace-collapsed) substring of its stored
material — a row whose quote fails is counted `unclear` by the report and listed here; (4) the double-read sample
equals the seeded one; (5) every logged request path avoids search endpoints (ghapi.get only issues GET: `gh api -X GET`; the
logged method is that constant, so this check covers paths, not methods); (7) the listing is complete, material
chunks are contiguous and no fix fetch was rate-limited; (8) every overridden label line is documented; (6) every <n><!--key--> in
REPORT.md equals the re-computed value and REPORT.md equals report.py's output byte for byte.
"""
from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import doubleread as DR  # noqa: E402
import fetch as F  # noqa: E402
import reading as RD  # noqa: E402
import report as REP  # noqa: E402
import rules as R  # noqa: E402

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print("MISMATCH", msg)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout


def check_prereg_first() -> None:
    def first_commit(path: str) -> str | None:
        out = git("log", "--diff-filter=A", "--format=%H %ct", "--reverse", "--", path).split("\n")
        return out[0] if out and out[0] else None

    pre = first_commit("PREREG.md")
    data = [first_commit(p) for p in ("data/budget.json", "data/listing_meta.json", "probe")]
    data = [d for d in data if d]
    if not pre:
        err("PREREG.md has no commit")
        return
    pre_t = int(pre.split()[1])
    for d in data:
        anc = subprocess.run(["git", "merge-base", "--is-ancestor", pre.split()[0], d.split()[0]], cwd=HERE)
        if int(d.split()[1]) < pre_t or anc.returncode != 0:
            err(f"data commit {d} precedes PREREG.md or does not descend from it")
    print("prereg commit", pre.split()[0][:7], "precedes", len(data), "first data commits")


def check_inputs() -> None:
    """The listing is complete (listing_meta rows per ecosystem), material chunks are contiguous, non-overlapping
    reading positions of order.json, and no fix fetch of a read row was refused by a rate limit (403/429)."""
    meta = json.loads((F.DATA / "listing_meta.json").read_text())
    for eco, pages in F.load_listing().items():
        if len(pages) != meta["pages"][eco]["rows"]:
            err(f"listing {eco}: {len(pages)} rows != listing_meta {meta['pages'][eco]['rows']}")
    order, seen = RD.order(), set()
    for p in sorted((F.DATA / "material").glob("m*.jsonl.gz")):
        rows = [json.loads(x) for x in gzip.open(p, "rt")]
        start = int(p.name[1:6])
        if [r["pos"] for r in rows] != list(range(start, start + len(rows))):
            err(f"{p.name}: positions are not contiguous from {start}")
        for r in rows:
            if r["pos"] in seen or order[r["pos"]] != r["ghsa_id"]:
                err(f"{p.name}: position {r['pos']} duplicated or not {r['ghsa_id']} in order.json")
            seen.add(r["pos"])
    mats, labs = F.load_material(), RD.load_labels()
    for g in labs:
        for f in mats[g]["fixes"]:
            if f.get("status") in (403, 429):
                err(f"{g}: fix fetch refused by rate limit ({f['status']}) for {f['ref']['url']}")


def check_overrides() -> None:
    """A label line may only be replaced by a later line when the replacement is documented (corrections.md or a
    changed row of reread/*.jsonl)."""
    lines = [json.loads(x) for x in (HERE / "labels.jsonl").read_text().splitlines() if x.strip()]
    counts: dict[str, int] = {}
    for lab in lines:
        counts[lab["ghsa_id"]] = counts.get(lab["ghsa_id"], 0) + 1
    documented = set(re.findall(r"GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}", (HERE / "corrections.md").read_text()))
    for p in sorted((HERE / "reread").glob("*.jsonl")):
        documented |= {r["ghsa_id"] for r in REP.read_jsonl(p) if r["new"] != "unchanged"}
    for g, n in counts.items():
        if n > 1 and g not in documented:
            err(f"{g}: {n} label lines but the override is not documented")
    print(sum(n > 1 for n in counts.values()), "overridden labels, all documented" if not errors else "")


def check_frame() -> None:
    frame = F.frame_rows(F.load_listing())
    committed = [json.loads(x) for x in gzip.open(F.DATA / "frame.jsonl.gz", "rt")]
    if frame != committed:
        err("frame.jsonl.gz does not re-derive from the listing")
    order = R.reading_order([r["ghsa_id"] for r in frame if r["route"]])
    if order != RD.order():
        err("order.json does not re-derive from the frame")


def check_labels() -> None:
    labs, order, mats = RD.load_labels(), RD.order(), F.load_material()
    read = [g for g in order if g in labs]
    if read != order[:len(read)] or len(read) != len(labs):
        err("labels are not exactly a prefix of the reading order")
    for g in read:
        for e in R.validate_label(labs[g]):
            err(f"{g}: {e}")
        if labs[g]["inclusion"] == "included" and not R.quote_ok(labs[g]["quote"], R.material_text(mats[g])):
            err(f"{g}: quote is not a verbatim substring of the stored material")
    for g, lab in DR.load2(REP.CHECKPOINT).items():
        for e in R.validate_label(lab):
            err(f"second reader {g}: {e}")


def check_sample() -> None:
    p = DR.cp_dir(REP.CHECKPOINT) / "input.jsonl"
    if not p.exists():
        err(f"double-read input {p} is missing")
        return
    ids = [json.loads(x)["ghsa_id"] for x in p.read_text().splitlines() if x.strip()]
    if ids != R.double_read_input_order(DR.sample(REP.CHECKPOINT)):
        err("double-read input is not the seeded sample in Random(7) order")
    mats = F.load_material()
    for cp in (REP.ROUND1, REP.CHECKPOINT):
        for g, lab in DR.load2(cp).items():
            if g not in mats:
                err(f"second reader {cp}: {g} has no material")
            elif lab["inclusion"] == "included" and not R.quote_ok(lab["quote"], R.material_text(mats[g])):
                err(f"second reader {cp}: {g} quote is not verbatim")
    if set(DR.load2(REP.CHECKPOINT)) != set(ids):
        err("second-reader ids at the checkpoint are not exactly the seeded sample")
    check_round1(mats)


def check_round1(mats: dict) -> None:
    """Re-derive round 1 (cp300) from the label lines that existed before the re-read (reader != session-reread)."""
    lines = [json.loads(x) for x in (HERE / "labels.jsonl").read_text().splitlines() if x.strip()]
    labs = {}
    for lab in lines:
        if lab["reader"] != "session-reread":
            labs[lab["ghsa_id"]] = lab
    order = RD.order()
    n = R.checkpoint_prefix(order, labs)
    scope = order[:n]
    eff = {g: R.effective_label(labs[g], R.material_text(mats[g])) for g in scope}
    sample = R.double_read_sample(eff, scope)
    inp = [json.loads(x)["ghsa_id"] for x in (DR.cp_dir(REP.ROUND1) / "input.jsonl").read_text().splitlines() if x]
    if inp != R.double_read_input_order(sample):
        err("round-1 input is not the seeded sample of the pre-re-read labels")
    second = DR.load2(REP.ROUND1)
    pairs = [(R.is_ours(eff[g]), R.is_ours(second[g])) for g in sample]
    ours1 = [g for g in sample if R.is_ours(eff[g])]
    conf = sum(R.is_ours(second[g]) for g in ours1)
    st = json.loads((DR.cp_dir(REP.ROUND1) / "stats.json").read_text())
    if (round(R.cohen_kappa(pairs), 6), conf, len(ours1)) != (round(st["kappa"], 6), st["confirmed"], st["ours_first"]):
        err("round-1 stats.json does not re-derive from the pre-re-read labels")
    print("round 1 re-derived: kappa", round(R.cohen_kappa(pairs), 2), "confirmed", conf, "of", len(ours1))


def check_requests() -> None:
    for p in sorted(F.DATA.glob("requests*.jsonl")):
        for r in REP.read_jsonl(p):
            if r["method"] != "GET" or "/search/" in r["path"]:
                err(f"{p.name}: forbidden request {r['method']} {r['path']}")


def check_report() -> None:
    v = REP.compute()
    expected = REP.render(v)
    txt = (HERE / "REPORT.md").read_text()
    keys = re.findall(r"([^\s(>]+?)<!--([a-z0-9_A-Z-]+)-->", txt)
    if not keys:
        err("REPORT.md has no keyed numbers")
    for val, key in keys:
        if key not in v:
            err(f"REPORT.md key {key} unknown")
        elif str(v[key]) != val:
            err(f"REPORT.md {key}: {val} != re-computed {v[key]}")
    if txt != expected:
        err("REPORT.md differs from report.py output")
    print(len(keys), "keyed numbers checked; first line:", txt.splitlines()[0])


def main() -> None:
    check_prereg_first()
    check_inputs()
    check_overrides()
    check_frame()
    check_labels()
    check_sample()
    check_requests()
    check_report()
    if errors:
        print(len(errors), "mismatch(es)")
        sys.exit(1)
    print("verify: OK")


if __name__ == "__main__":
    main()
