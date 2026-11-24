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


# Decisions on single rows, each with the reason (listed in REPORT.md under "Funding decisions").
EXCLUDE = {
    ("Buildkite", "https://www.thesaasnews.com/news/buildkite-raises-21m-series-b/"):
        "the page is Buildkite's 2022 Series B (co-led by OneVentures and AirTree, total $39M), re-dated "
        "'Updated September 20, 2026'; not announced in the window",
    ("Langfuse", "https://callsphere.ai/blog/langfuse-raises-50m-series-b-ai-agent-observability"):
        "a vendor's blog (CallSphere), neither the company nor a news outlet; langfuse.com/press says "
        "'Langfuse joins ClickHouse' (2026-01-16)",
}


def round_key(company: str, rnd: str | None) -> str:
    r = (rnd or "").lower()
    r = re.sub(r"\(.*?\)", "", r)
    if "pre-seed" in r or "pre seed" in r:
        k = "pre-seed"
    elif "series" in r:
        m = re.search(r"series\s+([a-z])", r)
        k = f"series {m.group(1)}" if m else "series"
        if "seed" in r:
            k = "seed + " + k
    elif "seed" in r:
        k = "seed"
    else:
        k = r.strip() or "unspecified"
    return f"{company}|{k}"


def fx_table() -> dict:
    out = {}
    for cur in ("USD", "GBP", "AUD"):
        p = HERE / "results" / "fx" / f"ECB_EUR_{cur}.json"
        if not p.exists():
            continue
        g = HERE / "results" / "fx" / f"ECB_EUR_{cur}.html.gz"
        text = gzip.open(g, "rt").read()
        rows = list(csv.DictReader(text.splitlines()))
        out[cur] = {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE")}
    return out


def rate_on(table: dict, day: str) -> tuple[str, float]:
    """ECB reference rate of the date, or of the previous business day with a rate."""
    import datetime as dt
    d = dt.date.fromisoformat(day)
    for _ in range(10):
        if d.isoformat() in table:
            return d.isoformat(), table[d.isoformat()]
        d -= dt.timedelta(days=1)
    raise KeyError(day)


def to_usd(amount: float, cur: str, day: str, fx: dict) -> tuple[float, str]:
    if cur == "USD":
        return amount, ""
    d, eur_usd = rate_on(fx["USD"], day)
    if cur == "EUR":
        return amount * eur_usd, f"ECB {d}: 1 EUR = {eur_usd} USD"
    d2, eur_x = rate_on(fx[cur], day)
    return amount / eur_x * eur_usd, f"ECB {d}: 1 EUR = {eur_usd} USD; ECB {d2}: 1 EUR = {eur_x} {cur}"


def select(checks: list[dict], comps: dict, fx: dict, access: dict) -> tuple[list[dict], list[dict]]:
    """Confirmed rounds per (company, round); returns (rounds, listed-not-summed)."""
    groups: dict = {}
    listed = []
    for c in checks:
        name = c["company"]
        if name not in comps:
            listed.append({**c, "why": "company not in companies.csv (name variant)"})
            continue
        if c.get("outside_window") or not in_window(c.get("date")):
            continue
        if c["kind"] != "round" or not c.get("amount"):
            listed.append({**c, "why": f"{c['kind']}: not summed (acquisition or undisclosed)"})
            continue
        ok = []
        for x in c["confirmations"]:
            if (name, x["url"]) in EXCLUDE:
                listed.append({**c, "why": EXCLUDE[(name, x["url"])]})
                continue
            if x["amount_on_page"] and not x["database"]:
                ok.append(x)
        if not ok:
            if not any((name, x["url"]) in EXCLUDE for x in c["confirmations"]):
                listed.append({**c, "why": "amount not confirmed on a company or news page (database source, "
                                           "page did not load, or amount absent)"})
            continue
        groups.setdefault(round_key(name, c["round"]), []).append((c, ok))
    rounds = []
    for key, vers in groups.items():
        comp_v = [(c, ok) for c, ok in vers if any(x["company_page"] for x in ok)]
        pick_from = comp_v or vers
        def usd(v):
            c = v[0]
            return to_usd(float(c["amount"]), c["currency"], date_of(c, vers), fx)[0]
        pick_from = sorted(pick_from, key=lambda v: (-len(v[1]), usd(v)))
        c, ok = pick_from[0]
        day = date_of(c, vers)
        amt_usd, fx_note = to_usd(float(c["amount"]), c["currency"], day, fx)
        comp = comps[c["company"]]
        src = next((x for x in ok if x["company_page"]), ok[0])
        rounds.append({"company": c["company"], "class_2_3": comp["class_2_3"], "round": c["round"],
                       "round_key": key.split("|", 1)[1], "date": day, "amount": c["amount"],
                       "currency": c["currency"], "amount_usd": round(amt_usd), "fx": fx_note,
                       "source_url": src["url"], "source_type": "company" if src["company_page"] else "news",
                       "access_date": access.get(src["url"], ""), "query": c.get("query"), "batch": c["batch"],
                       "versions": "; ".join(f"{v[0]['amount']} {v[0]['currency']} ({v[0]['source_url']})"
                                             for v in vers if v[0] is not c),
                       "public_at_round": "yes" if comp.get("public_note") else "no"})
    return rounds, listed


# Month-only dates completed from the date printed on the confirming page (checked by hand).
DATE_FROM_PAGE = {("Blacksmith", "https://dealroom.co/news/164699-blacksmith-hits-1b-valuation-with-66m-series-c-led-by-sequoia/"):
                  "2026-10-21"}


def date_of(c: dict, vers: list) -> str:
    """Full date of the version, else the date printed on the confirming page (DATE_FROM_PAGE), else the earliest
    full date among versions of the same round, else the 1st of the month."""
    k = (c["company"], c.get("source_url"))
    if k in DATE_FROM_PAGE:
        return DATE_FROM_PAGE[k]
    if c.get("date") and len(c["date"]) == 10:
        return c["date"]
    full = sorted(v[0]["date"] for v in vers if v[0].get("date") and len(v[0]["date"]) == 10)
    return full[0] if full else (c["date"] + "-01")[:10]


def write_tables() -> dict:
    comps, slug_of, _ = load()
    checks = json.loads((HERE / "funding_checks.json").read_text())
    access = {}
    for u, n in slug_of.items():
        j = json.loads((HERE / "results" / "funding_sources" / f"{n}.json").read_text())
        access[u] = (j.get("at") or "")[:10]
    fx = fx_table()
    rounds, listed = select(checks, comps, fx, access)
    cols = ["company", "class_2_3", "round", "round_key", "date", "amount", "currency", "amount_usd", "fx",
            "source_url", "source_type", "access_date", "query", "batch", "versions", "public_at_round", "summed",
            "note"]
    out = {"T": [], "E": [], "other": []}
    for r in sorted(rounds, key=lambda x: (x["company"], x["date"])):
        cat = comps[r["company"]]["summed_as"]
        r["summed"] = "yes" if cat in ("T", "E") and r["public_at_round"] == "no" else "no"
        r["note"] = "" if r["summed"] == "yes" else f"class {r['class_2_3']}: listed, not summed"
        out[cat if cat in ("T", "E") else "other"].append(r)
    for r in listed:
        cat = comps.get(r["company"], {}).get("summed_as")
        out[cat if cat in ("T", "E") else "other"].append(
            {"company": r["company"], "class_2_3": comps.get(r["company"], {}).get("class_2_3", ""),
             "round": r.get("round"), "date": r.get("date"), "amount": r.get("amount"),
             "currency": r.get("currency"), "source_url": r.get("source_url"), "query": r.get("query"),
             "batch": r.get("batch"), "summed": "no", "note": r["why"]})
    for cat, rows in out.items():
        with open(HERE / f"funding_{cat}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "tables":
        o = write_tables()
        for cat, rows in o.items():
            s = sum(r.get("amount_usd") or 0 for r in rows if r.get("summed") == "yes")
            print(cat, len(rows), "rows, summed", s)
            for r in rows:
                if r.get("amount_usd"):
                    print("  ", r["company"], r["round_key"], r["date"], r["amount_usd"], r["summed"], r["source_type"])
    else:
        sys.exit(main())
