#!/usr/bin/env python3
"""AC3: recompute every number in REPORT.md from the raw rows; exit 1 on any mismatch.

1. Every row of results/rows.jsonl is re-derived from its committed raw responses (results/raw/<chunk>.jsonl.gz)
   with ``pipeline.ReplaySource``; every repository-search record from results/texts_raw{,_wf}/ and every comment
   record from results/comments_raw/. Fields describing the run itself (chunk, requests, read_at, trace) are not
   compared.
2. Every ``<n><!--key-->`` in REPORT.md is compared with the value ``report.render`` computes for that key.
3. REPORT.md is re-printed by ``report.render`` and compared byte for byte.
4. The decision counts (read, members, pain yes/unknown/no, uncertain, A_s per stratum) are recounted by a separate
   loop over the rows and compared with ``report.compute``.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pipeline  # noqa: E402
import report  # noqa: E402
import texts as T  # noqa: E402

VOLATILE = {"chunk", "requests", "read_at", "trace"}
NUM_RE = re.compile(r"([^\s(>|]+)<!--([\w.-]+)-->")


def _norm(x):
    return json.loads(json.dumps(x, sort_keys=True))


def check_rows(res: Path) -> list[str]:
    errs = []
    rows = {r["idx"]: r for r in report._jsonl(res / "rows.jsonl")}
    cands = {c["idx"]: c for c in report._jsonl(res / "candidates.jsonl.gz")}
    seen = set()
    last_raw = {}  # a candidate read again after a killed job: its last raw record matches its kept row
    for raw in sorted((res / "raw").glob("*.jsonl.gz")) if (res / "raw").exists() else []:
        for rec in report._jsonl(raw):
            last_raw[rec["idx"]] = rec
    for idx, rec in sorted(last_raw.items()):
        if idx not in rows:
            continue  # raw written, row not (job killed in between): the candidate is read again
        seen.add(idx)
        cand = cands.get(idx) or {"idx": idx, "repo": rec["repo"], "html_url": rows[idx].get("html_url"),
                                  "stratum": rows[idx].get("stratum")}
        try:
            again = pipeline.run_candidate(pipeline.ReplaySource(rec["responses"]), cand, rec.get("opts") or {})
        except pipeline.Missing as e:
            errs.append(f"{rec['repo']}: raw response missing for {e}")
            continue
        except Exception as e:
            errs.append(f"{rec['repo']}: replay raised {type(e).__name__}: {str(e)[:120]}")
            continue
        a = {k: v for k, v in _norm(rows[idx]).items() if k not in VOLATILE}
        b = {k: v for k, v in _norm(again).items() if k not in VOLATILE}
        if a != b:
            errs.append(f"{rec['repo']}: row differs from its replay in "
                        f"{sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))}")
    for idx in rows:
        if idx not in seen:
            errs.append(f"row idx {idx}: no raw responses")
    for sfx in ("", "_wf"):
        recs = {(r["repo"].lower(), r["at"]): r for r in report._jsonl(res / f"texts_search{sfx}.jsonl")}
        d = res / f"texts_raw{sfx}"
        for raw in sorted(d.glob("*.jsonl.gz")) if d.exists() else []:
            for rr in report._jsonl(raw):
                x = recs.get((rr["repo"].lower(), rr["at"]))
                if x is None:
                    errs.append(f"texts raw {rr['repo']}: no record")
                    continue
                try:
                    again = T.run_searches(pipeline.ReplaySource(rr["responses"]), x["query_repo"], rr.get("cfg") or {})
                except pipeline.Missing as e:
                    errs.append(f"texts {rr['repo']}: raw response missing for {e}")
                    continue
                if _norm({k: x[k] for k in ("queries", "hits")}) != _norm(again):
                    errs.append(f"texts {rr['repo']}: record differs from its replay")
    crecs = {(r["repo"].lower(), r["at"]): r for r in report._jsonl(res / "comments.jsonl")}
    import chunk as CH
    search = {(r["repo"].lower(), r["at"]): r for f in CH.search_files(res) for r in report._jsonl(f)}
    d = res / "comments_raw"
    for raw in sorted(d.glob("*.jsonl.gz")) if d.exists() else []:
        for rr in report._jsonl(raw):
            x = crecs.get((rr["repo"].lower(), rr["at"]))
            row = next((r for r in rows.values() if r["repo"].lower() == rr["repo"].lower()), None)
            if x is None or row is None:
                errs.append(f"comments raw {rr['repo']}: no record or row")
                continue
            repo = (row.get("meta") or {}).get("full_name") or row["repo"]
            tx = T.member_texts(repo, (cands.get(row["idx"]) or {}).get("hits") or [],
                                search.get((rr["repo"].lower(), rr.get("search_at"))))
            try:
                again = T.comments_pass(pipeline.ReplaySource(rr["responses"], used=rr["used"]), repo, tx)
            except pipeline.Missing as e:
                errs.append(f"comments {rr['repo']}: raw response missing for {e}")
                continue
            if _norm({k: x[k] for k in ("targets", "fetched", "capped")}) != _norm(again):
                errs.append(f"comments {rr['repo']}: record differs from its replay")
    return errs


def recount(d: dict) -> dict:
    """Independent loop over the rows for the decision counts (shares member_record with the report)."""
    rows = {}
    for r in d["rows"]:
        rows[r["idx"]] = r
    out = {"read": 0, "members": 0, "yes": 0, "unknown": 0, "no": 0, "uncertain": 0,
           "A": {"S1": 0, "S2": 0, "S3": 0}}
    x = report.compute(d)
    pain = {m["row"]["idx"]: m["pain"]["pain"] for m in x["members"]}
    for r in rows.values():
        if r.get("cls") == "excluded":
            continue
        out["read"] += 1
        if r.get("cls") == "uncertain":
            out["uncertain"] += 1
            out["A"][r["stratum"]] += 1
        if r.get("cls") == "member":
            out["members"] += 1
            p = pain[r["idx"]]
            out[p] += 1
            if p in ("yes", "unknown"):
                out["A"][r["stratum"]] += 1
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default=str(report.RES))
    ap.add_argument("--report", default=str(HERE / "REPORT.md"))
    a = ap.parse_args(argv)
    res, rp = Path(a.res), Path(a.report)
    errs = check_rows(res)
    d = report.load(res)
    text, vals = report.render(d)
    rep = rp.read_text() if rp.exists() else ""
    for v, k in NUM_RE.findall(rep):
        if k not in vals:
            errs.append(f"REPORT.md key {k}: not computed")
        elif vals[k] != v:
            errs.append(f"REPORT.md key {k}: {v} != recomputed {vals[k]}")
    if rep != text:
        errs.append("REPORT.md differs from report.render output")
    x = report.compute(d)
    rc = recount(d)
    mine = {"read": len(x["counted"]), "members": len(x["members"]), "yes": len(x["yes"]),
            "unknown": sum(1 for m in x["members"] if m["pain"]["pain"] == "unknown"),
            "no": sum(1 for m in x["members"] if m["pain"]["pain"] == "no"),
            "uncertain": sum(1 for r in x["counted"] if r.get("cls") == "uncertain"),
            "A": {s: x["strata"][s]["A"] for s in report.STRATA}}
    if rc != mine:
        errs.append(f"decision counts differ: recount {rc} vs report {mine}")
    for e in errs:
        print("MISMATCH", e)
    print(f"verify: {len(errs)} mismatch(es); {len(vals)} numbers checked")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
