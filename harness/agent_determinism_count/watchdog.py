#!/usr/bin/env python3
"""Text-run watchdog (coordinator 2026-11-26 14:57Z, after the gaps 09:56-10:54Z and 12:34-14:56Z).

Every 20 minutes a harness-tracked timer in the work session wakes the session. The session reads the latest text
workflow run and the time of its last log line with the GitHub tools (the session's gh is limited to search), then:
  watchdog.py check --status <run status> --last-log <ISO time> [--now <ISO time>]
                                                  prints "ok", or "gap: <reason>" and exits 3
  watchdog.py gap --start <ISO> --end <ISO> --cause "<text>"
                                                  records the gap in results/report_notes.json (REPORT "Notes") and
                                                  results/watchdog.jsonl
  watchdog.py queue                               writes the next noop request requests/n<k>.json (a push of a request
                                                  file starts the text workflow; pending requests run before it)
A run is healthy when it is queued, or in progress with a last log line under 20 minutes old. A completed run is
healthy only when every request file has its requests_done marker (nothing left to run).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
STALE_MIN = 20


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def pending_requests(here: Path = HERE) -> list[str]:
    done = {p.name for p in (here / "results" / "requests_done").glob("*")}
    return sorted(p.name for p in (here / "requests").glob("*.json") if p.name not in done)


def check(status: str, last_log: str | None, now: str, pending: list[str]) -> str | None:
    """None when healthy, else the reason."""
    if status in ("queued", "requested", "waiting", "pending"):
        return None
    if status == "in_progress":
        if not last_log:
            return "run in progress without a log line"
        age = (_t(now) - _t(last_log)).total_seconds() / 60
        return None if age < STALE_MIN else f"last log line {age:.0f} min old"
    if pending:
        return f"no text run in progress or queued; {len(pending)} request(s) pending: {', '.join(pending)}"
    return None


def record_gap(start: str, end: str, cause: str, res: Path = RES) -> str:
    note = f"Reading gap {start}-{end}: {cause}"
    p = res / "report_notes.json"
    d = json.loads(p.read_text()) if p.exists() else {"notes": []}
    if note not in d.setdefault("notes", []):
        d["notes"].append(note)
    p.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    with open(res / "watchdog.jsonl", "a") as f:
        f.write(json.dumps({"start": start, "end": end, "cause": cause}, sort_keys=True) + "\n")
    return note


def queue_noop(here: Path = HERE) -> Path:
    ks = [int(m.group(1)) for p in (here / "requests").glob("n*.json") if (m := re.fullmatch(r"n(\d+)\.json", p.name))]
    p = here / "requests" / f"n{max(ks, default=0) + 1}.json"
    p.write_text('{"noop": true}\n')
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--status", required=True)
    c.add_argument("--last-log")
    c.add_argument("--now", default=datetime.now(timezone.utc).isoformat())
    g = sub.add_parser("gap")
    g.add_argument("--start", required=True)
    g.add_argument("--end", required=True)
    g.add_argument("--cause", required=True)
    sub.add_parser("queue")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        r = check(a.status, a.last_log, a.now, pending_requests())
        print("ok" if r is None else f"gap: {r}")
        return 0 if r is None else 3
    if a.cmd == "gap":
        print(record_gap(a.start, a.end, a.cause))
        return 0
    print(queue_noop())
    return 0


if __name__ == "__main__":
    sys.exit(main())
