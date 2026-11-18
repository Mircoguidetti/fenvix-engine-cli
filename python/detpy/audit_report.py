"""Cache audit report: checked, wrong and the 95% upper bound on the wrong-skip rate, per project and over all
projects.

    python -m detpy.audit_report SUMMARY.json [...]          # fenvix-run summaries (or --det-outcomes files)
    python -m detpy.audit_report --service URL               # every run the service knows (GET /v1/audit)
    ... [--json OUT]

A *wrong skip* is a reusable result that two fresh runs contradicted; a mismatch the second fresh run did not
reproduce is *flaky with evidence* and not counted as wrong. The bound is one-sided at 95%: 3/checked when no wrong
skip was found (rule of three), else the exact Clopper-Pearson bound. Each audited test is one Bernoulli trial; the
trials of one project are not independent draws from all projects, so the overall bound assumes the audited tests
are a fair sample of all reused results (the audit's random choice makes them one within each run).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .cache_service import upper_bound_95

FIELDS = ("checked", "matched", "wrong", "flaky_evidence")


def audit_of(doc: dict) -> dict | None:
    """The audit block of a fenvix-run summary (``audit``) or of a ``--det-outcomes`` file (``cache.audit``)."""
    a = doc.get("audit")
    if a is None and isinstance(doc.get("cache"), dict):
        a = doc["cache"].get("audit")
    return a if isinstance(a, dict) else None


def project_of(doc: dict, path: str) -> str:
    return str(doc.get("project_key") or doc.get("project") or os.path.dirname(os.path.abspath(path)))


def aggregate(rows: list[tuple[str, dict]]) -> dict:
    """``rows``: (project, audit block). Returns {"projects": {name: counts}, "all": counts}, each with its bound."""
    per: dict[str, dict] = {}
    for name, a in rows:
        p = per.setdefault(name, {"runs": 0, **{k: 0 for k in FIELDS}, "wrong_tests": []})
        p["runs"] += 1
        for k in FIELDS:
            v = a.get(k, 0)
            p[k] += v if isinstance(v, int) and v >= 0 else 0
        p["wrong_tests"] += [w.get("nodeid") for w in a.get("wrong_tests", []) if isinstance(w, dict)]
    total = {"runs": 0, **{k: 0 for k in FIELDS}}
    for p in per.values():
        for k in total:
            total[k] += p[k]
        p["upper_bound_95"] = upper_bound_95(p["checked"], p["wrong"])
    total["upper_bound_95"] = upper_bound_95(total["checked"], total["wrong"])
    return {"projects": dict(sorted(per.items())), "all": total}


def render(rep: dict) -> str:
    L = [f"{'project':40} {'runs':>5} {'checked':>8} {'wrong':>6} {'flaky':>6} {'95% upper bound':>16}"]
    for name, p in rep["projects"].items():
        L.append(f"{name[:40]:40} {p['runs']:>5} {p['checked']:>8} {p['wrong']:>6} {p['flaky_evidence']:>6} "
                 f"{p['upper_bound_95']:>15.3%}")
    t = rep["all"]
    L.append(f"{'ALL PROJECTS':40} {t['runs']:>5} {t['checked']:>8} {t['wrong']:>6} {t['flaky_evidence']:>6} "
             f"{t['upper_bound_95']:>15.3%}")
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m detpy.audit_report")
    p.add_argument("summaries", nargs="*", help="fenvix-run summary.json or --det-outcomes files")
    p.add_argument("--service", default=None, help="cache service base URL (token in FENVIX_CACHE_TOKEN)")
    p.add_argument("--json", default=None, help="also write the report as JSON")
    a = p.parse_args(argv)
    if a.service:
        from .remote_cache import Http

        rep = Http(a.service.rstrip("/"), os.environ.get("FENVIX_CACHE_TOKEN")).call("GET", "/v1/audit")
    else:
        rows = []
        for path in a.summaries:
            with open(path) as fh:
                doc = json.load(fh)
            au = audit_of(doc)
            if au is not None:
                rows.append((project_of(doc, path), au))
        rep = aggregate(rows)
    print(render(rep))
    if rep.get("counted"):
        print(f"counted: {rep['counted']}")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
