"""Print the outcome from committed files only: table.jsonl, items.jsonl, handcheck.jsonl, recheck.jsonl.

    python3 harness/db_copies_read/lines.py [--results DIR]

First line: CONTINUE TO DESIGN | BACK TO LIST | SPLIT (pain holds) | SPLIT (free_off holds) | INCOMPLETE.
The session decides nothing beyond printing (spec rule 13).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DENOM = 20
THRESHOLD = 5
DB_RULES = ("P3-revert", "P3-closed", "P3-text", "P4")


def jl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def outcome(pain: int, free_off: int, incomplete: bool) -> str:
    if incomplete:
        return "INCOMPLETE"
    a, b = pain >= THRESHOLD, free_off >= THRESHOLD
    if a and b:
        return "CONTINUE TO DESIGN"
    if not a and not b:
        return "BACK TO LIST"
    return "SPLIT (pain holds)" if a else "SPLIT (free_off holds)"


def passed_items(items: list[dict], hand: list[dict], recheck: list[dict]) -> list[dict]:
    """Counted items with a hand-check pass and no coordinator reject."""
    rejected = {r["url"] for r in recheck if r.get("answer") == "reject"}
    ok = {(h["repo"], h["url"]) for h in hand if h.get("decision") == "pass" and h.get("counted")}
    return [i for i in items if i["counted"] and (i["repo"], i["url"]) in ok and i["url"] not in rejected]


def compute(table: list[dict], items: list[dict], hand: list[dict], recheck: list[dict]) -> dict:
    if len(table) != DENOM:
        raise SystemExit(f"table has {len(table)} rows, not {DENOM}")
    incomplete = any(t["status"] not in ("done", "unavailable") for t in table)
    passed = passed_items(items, hand, recheck)
    pain_repos = sorted({i["repo"] for i in passed})
    db_repos = sorted({i["repo"] for i in passed if i.get("p1_db") or any(r in DB_RULES for r in i["counted_rules"])})
    free = sorted(t["repo"] for t in table if t.get("free_off") == "yes")
    return {"outcome": outcome(len(pain_repos), len(free), incomplete), "pain": pain_repos, "free_off": free,
            "pain_db": db_repos, "incomplete": [t["repo"] for t in table if t["status"] not in ("done", "unavailable")]}


def render(r: dict) -> str:
    return (f"{r['outcome']}\npain: {len(r['pain'])} of {DENOM}\nfree_off: {len(r['free_off'])} of {DENOM}\n"
            f"pain tied to the database (P1-db or P3/P4): {len(r['pain_db'])} of {DENOM}\n")


def load(results: Path) -> dict:
    return compute(jl(results / "table.jsonl"), jl(results / "items.jsonl"), jl(results / "handcheck.jsonl"),
                   jl(results / "recheck.jsonl"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results"))
    a = ap.parse_args()
    sys.stdout.write(render(load(Path(a.results))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
