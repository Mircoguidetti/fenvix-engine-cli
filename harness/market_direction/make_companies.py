"""Builds companies.csv from the workflow fetches (results/companies/*.json) and §2.3 (web.classify).
Public status: only companies public (or a division of a public company) for the whole window are marked here;
status at each round's date is judged in the funding tables (note 13)."""
import csv
import json
import re
from pathlib import Path

import web

HERE = Path(__file__).resolve().parent
PUBLIC = {"Datadog": "public company (NASDAQ: DDOG) for the whole window"}


def main():
    inp = json.loads((HERE / "companies_input.json").read_text())
    rows = []
    for listed, group in (("seed", inp["seed"]), ("added", inp["added"])):
        for c in group:
            slug = re.sub(r"[^A-Za-z0-9]+", "_", c["name"]).strip("_")
            r = json.loads((HERE / "results" / "companies" / f"{slug}.json").read_text())
            cls = web.classify(r["text"], r["status"])
            pub = PUBLIC.get(c["name"], "")
            rows.append({"company": c["name"], "listed": f"{listed}:{c.get('listed', '')}".rstrip(":"),
                         "home_url": c["url"], "final_url": r["final_url"], "status": r["status"],
                         "redirects": len(r["hops"]) - 1, "text_source": r["text_source"], "quoted_text": r["text"],
                         "access_date": r["at"][:10], "class_2_3": cls, "public_note": pub,
                         "summed_as": "" if cls in ("UNVERIFIED", "borderline") or pub else cls,
                         "error": r.get("error") or ""})
    with open(HERE / "companies.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    seed = [r for r in rows if r["listed"].startswith("seed")]
    unv = [r for r in seed if r["class_2_3"] == "UNVERIFIED"]
    print(f"{len(rows)} companies; seed {len(seed)}, seed UNVERIFIED {len(unv)} ({100*len(unv)/len(seed):.1f}%)")
    from collections import Counter
    print(Counter(r["class_2_3"] for r in rows))


if __name__ == "__main__":
    main()
