#!/usr/bin/env python3
"""AC3: recompute every number in REPORT.md from the raw rows; exit 1 on any mismatch.

1. Every row in results/rows.jsonl is re-derived from its committed raw responses (results/raw/<chunk>.jsonl.gz) with
   ``pipeline.ReplaySource``; every issues record from results/issues_raw/. Fields that describe the run itself
   (chunk, requests, read_at) are not compared.
2. REPORT.md is re-printed by ``report.render`` and compared byte for byte.
3. The decision counts are recounted by a separate loop (no report code) and checked against the decision line.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import history  # noqa: E402
import pipeline  # noqa: E402
import report  # noqa: E402
import rules as R  # noqa: E402

VOLATILE = {"chunk", "requests", "read_at"}


def _norm(x):
    return json.loads(json.dumps(x, sort_keys=True))


def check_rows(res: Path) -> list[str]:
    errs = []
    rows = {r["idx"]: r for r in report._jsonl(res / "rows.jsonl")}
    cands = {c["idx"]: c for c in report._jsonl(res / "candidates.jsonl")}
    seen = set()
    for raw in sorted((res / "raw").glob("*.jsonl.gz")) if (res / "raw").exists() else []:
        for rec in report._jsonl(raw):
            idx = rec["idx"]
            seen.add(idx)
            if idx not in rows:
                errs.append(f"raw {raw.name} idx {idx}: no row")
                continue
            cand = cands.get(idx) or {"idx": idx, "repo": rec["repo"], "html_url": rows[idx].get("html_url")}
            try:
                again = pipeline.run_candidate(pipeline.ReplaySource(rec["responses"]), cand, rec.get("opts") or {})
            except pipeline.Missing as e:
                errs.append(f"{rec['repo']}: raw response missing for {e}")
                continue
            except Exception as e:
                again = {"idx": idx, "repo": cand["repo"], "html_url": cand.get("html_url"), "cls": "uncertain",
                         "mclass": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}
            a = {k: v for k, v in _norm(rows[idx]).items() if k not in VOLATILE and k != "trace"}
            b = {k: v for k, v in _norm(again).items() if k not in VOLATILE and k != "trace"}
            if a != b:
                diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
                errs.append(f"{rec['repo']}: row differs from its replay in {diff}")
    for idx in rows:
        if idx not in seen:
            errs.append(f"row idx {idx}: no raw responses")
    issues = {}
    for x in report._jsonl(res / "issues.jsonl"):
        issues[x["repo"].lower()] = x
    for raw in sorted((res / "issues_raw").glob("*.jsonl.gz")) if (res / "issues_raw").exists() else []:
        for rec in report._jsonl(raw):
            x = issues.get(rec["repo"].lower())
            if x is None:
                errs.append(f"issues raw {rec['repo']}: no record")
                continue
            again = history.run_issues(pipeline.ReplaySource(rec["responses"]),
                                       x.get("query_repo") or rec["repo"],
                                       x.get("tools") or [], x.get("cap_left", 300))
            keep = ("queries", "candidates", "errors", "done", "capped")
            if {k: _norm(x.get(k)) for k in keep} != {k: _norm(again.get(k)) for k in keep}:
                errs.append(f"issues {rec['repo']}: record differs from its replay")
    return errs


def recount(d: dict) -> dict:
    """Decision counts by an independent loop over the rows (hand-check reclassification applied the same way)."""
    rows = report.apply_handcheck(d["rows"], d["handcheck"])
    out = {"read": 0, "running": 0, "uncertain": 0, "pain_yes": 0, "pain_unknown": 0}
    for r in rows:
        if r.get("cls") == "excluded":
            continue
        out["read"] += 1
        if r.get("cls") == "uncertain":
            out["uncertain"] += 1
        if r.get("cls") == "running":
            out["running"] += 1
            p = r.get("pain_override") or R.pain_of(r, d["handreads"])[0]
            if p == "yes":
                out["pain_yes"] += 1
            elif p == "unknown":
                out["pain_unknown"] += 1
    return out


def main(res: Path = report.RES, report_path: Path = HERE / "REPORT.md") -> int:
    errs = check_rows(res)
    d = report.load(res)
    text = report.render(d)
    if not report_path.exists():
        errs.append("REPORT.md missing")
    elif report_path.read_text() != text:
        a, b = report_path.read_text().splitlines(), text.splitlines()
        first = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
        errs.append(f"REPORT.md differs from report.py output at line {first + 1}")
    rc = recount(d)
    x = report.compute(d)
    for k, v in rc.items():
        if x["c"][k] != v:
            errs.append(f"count {k}: report {x['c'][k]} vs recount {v}")
    for e in errs:
        print("MISMATCH", e)
    print(f"verify: {len(errs)} mismatches; read {rc['read']}, running {rc['running']}, pain yes {rc['pain_yes']}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
