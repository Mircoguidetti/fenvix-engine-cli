"""Check each desk-survey quote for exact presence in its stored page (HTML tags stripped, whitespace collapsed).

    python3 harness/db_copies_read/desk_check.py [--survey desk_survey.md] [--results DIR]

desk_survey.md table columns: tool | per-worker database | how | URL | quote | fetch date | status.
A row is VERIFIED only when its page was fetched (HTTP 200) and the quote is found. Exit 1 when a row's status
column disagrees with the check, or when the Django or pytest-django row is not VERIFIED (§6 stop).
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOCKING = ("Django", "pytest-django")


def page_text(raw: bytes) -> str:
    s = raw.decode("utf-8", errors="replace")
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def norm(q: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(q.replace("\\|", "|"))).strip()


def rows(survey: Path) -> list[dict]:
    out = []
    for ln in survey.read_text().splitlines():
        if not ln.startswith("| ") or ln.startswith("| tool ") or ln.startswith("|---"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]
        if len(cells) != 7:
            raise SystemExit(f"bad row ({len(cells)} cells): {ln[:80]}")
        out.append(dict(zip(["tool", "per_worker", "how", "url", "quote", "date", "status"], cells)))
    return out


def check(survey: Path, results: Path) -> list[dict]:
    idx = {r["url"]: r for r in json.loads((results / "docs" / "index.json").read_text())}
    out = []
    for r in rows(survey):
        rec = idx.get(r["url"])
        if not rec:
            got, why = "UNVERIFIED", "page not fetched"
        elif rec.get("status") != 200:
            got, why = "UNVERIFIED", f"fetch status {rec.get('status')} {rec.get('error', '')}".strip()
        else:
            with gzip.open(results / "docs" / rec["file"], "rb") as fh:
                text = page_text(fh.read())
            q = norm(r["quote"].strip('"'))
            if q and q in text:
                got, why = "VERIFIED", "quote found"
            else:
                got, why = "UNVERIFIED", "quote not found in stored page"
        out.append({"tool": r["tool"], "declared": r["status"].split()[0] if r["status"] else "", "check": got,
                    "why": why})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", default=str(HERE / "desk_survey.md"))
    ap.add_argument("--results", default=str(HERE / "results"))
    a = ap.parse_args()
    res = check(Path(a.survey), Path(a.results))
    bad = 0
    for r in res:
        flag = "" if r["declared"] == r["check"] else "  << status column disagrees"
        print(f"{r['tool']}: {r['check']} ({r['why']}){flag}")
        bad += bool(flag)
    for t in BLOCKING:
        if not any(r["tool"] == t and r["check"] == "VERIFIED" for r in res):
            print(f"STOP: {t} row not VERIFIED")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
