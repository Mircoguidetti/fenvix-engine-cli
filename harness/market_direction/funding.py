#!/usr/bin/env python3
"""Part 2 §2.4: funding events -> confirmed rounds -> funding_T.csv, funding_E.csv, funding_other.csv.

Inputs: funding_queries/batch*.json (events found in the logged results only), companies.csv (§2.3 class),
results/funding_sources/*.json (each cited page fetched in the workflow, Python requests), results/fx/ (ECB rates).
A round is confirmed when a cited page that is the company's own page or a news outlet (not a funding database)
loaded with status 200 and states the amount (amount_on_page). Per (company, round) the company's own figure wins;
otherwise the news figure (if confirmed news figures disagree, the one stated by the most pages, ties -> the lower,
flagged). Rows: summed = yes only for T/E companies that are not public/division at the round date.
"""
from __future__ import annotations

import csv
import glob
import gzip
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
WIN = ("2025-01-01", "2026-11-24")
DATABASES = ("cbinsights.com", "pitchbook.com", "zoominfo.com", "caplight.com", "app.dealroom.co", "fundz.net",
             "seedtable.com", "preqin.com", "vcbeast.com", "aifunding.me", "founderlodge.com", "trysignalbase.com",
             "salestools.io", "funding.tech.eu", "parsers.vc", "raising.fi", "defillama.com", "crunchbase.com",
             "tracxn.com", "startupintros.com", "extruct.ai", "qubitcapital.com")
# dealroom.co/companies/... is a database profile; dealroom.co/news/... is an article
CURRENCY_SYMBOL = {"USD": r"(US)?\$|USD\s?", "EUR": r"€|EUR\s?", "GBP": r"£|GBP\s?", "AUD": r"A\$|AU\$|AUD\s?"}


def is_database(url: str) -> bool:
    h = urlparse(url).netloc.lower().removeprefix("www.")
    if h == "dealroom.co" and "/companies/" in url:
        return True
    return any(h == d or h.endswith("." + d) for d in DATABASES)


def page_text(slug: str) -> tuple[int | None, str]:
    j = json.loads((HERE / "results" / "funding_sources" / f"{slug}.json").read_text())
    p = HERE / "results" / "funding_sources" / f"{slug}.html.gz"
    raw = gzip.open(p, "rt").read() if p.exists() else ""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return j.get("status"), re.sub(r"\s+", " ", t)


def amount_patterns(amount: float) -> list[str]:
    m = amount / 1e6
    out = []
    if m >= 1:
        s = f"{m:.2f}".rstrip("0").rstrip(".")
        out.append(rf"(?<![\d.]){re.escape(s)}(\.0+)?\s*(-|\s)?(M\b|MM\b|mn\b|m\b|million\b|millones|Mio)")
        if m >= 1000:
            b = f"{m / 1000:.2f}".rstrip("0").rstrip(".")
            out.append(rf"(?<![\d.]){re.escape(b)}\s*(B\b|bn\b|billion\b)")
    else:
        k = f"{amount / 1e3:.0f}"
        out.append(rf"(?<![\d.]){k}\s*(K\b|k\b|thousand)")
    out.append(re.escape(f"{int(amount):,}"))
    return out


def amount_on_page(amount: float, text: str) -> bool:
    return any(re.search(p, text, re.I) for p in amount_patterns(amount))


def company_domain(url: str, comp: dict) -> bool:
    h = urlparse(url).netloc.lower().removeprefix("www.")
    homes = {urlparse(comp[k]).netloc.lower().removeprefix("www.").split(":")[0] for k in ("home_url", "final_url")}
    return any(h == x or h.endswith("." + x) for x in homes if x)


def in_window(d: str | None) -> bool:
    return bool(d) and WIN[0] <= d[:10].ljust(10, "~") and d[:7] <= WIN[1][:7] and (len(d) < 10 or d <= WIN[1])


def load():
    comps = {r["company"]: r for r in csv.DictReader(open(HERE / "companies.csv"))}
    req = json.loads((HERE / "requests" / "6.json").read_text())
    slug_of = {u: n for n, u in req["urls"].items()}
    ev = []
    for f in sorted(glob.glob(str(HERE / "funding_queries" / "batch*.json"))):
        for e in json.load(open(f)):
            e["batch"] = Path(f).name
            ev.append(e)
    return comps, slug_of, ev


def main() -> int:
    comps, slug_of, ev = load()
    checks = []
    for e in ev:
        if e.get("kind") == "info" or e.get("different_company") or e.get("not_target_company"):
            continue
        rec = {k: e.get(k) for k in ("company", "round", "amount", "currency", "date", "kind", "source_url",
                                     "source_type", "query", "batch", "outside_window")}
        rec["evidence"] = (e.get("evidence") or "")[:300]
        urls = [u for u in (e.get("source_url"), e.get("corroborating_url")) if isinstance(u, str) and u]
        rec["confirmations"] = []
        for u in urls:
            if u not in slug_of:
                continue
            st, text = page_text(slug_of[u])
            db = is_database(u)
            on = bool(e.get("amount")) and st == 200 and amount_on_page(float(e["amount"]), text)
            rec["confirmations"].append({"url": u, "status": st, "database": db, "amount_on_page": on,
                                         "company_page": company_domain(u, comps.get(e["company"], {}))
                                         if e["company"] in comps else False})
        checks.append(rec)
    (HERE / "funding_checks.json").write_text(json.dumps(checks, indent=1, sort_keys=True))
    for c in checks:
        ok = [x for x in c["confirmations"] if x["amount_on_page"] and not x["database"]]
        print(f"{c['company'][:14]:14} {str(c['round'])[:20]:20} {c['amount']} {c['currency']} {c['date']} "
              f"{c['kind']} win={not c.get('outside_window')} confirmed={len(ok)} "
              f"{[(x['status'], x['database'], x['amount_on_page'], x['company_page']) for x in c['confirmations']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
