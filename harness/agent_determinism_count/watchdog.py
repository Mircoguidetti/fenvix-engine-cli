#!/usr/bin/env python3
"""Text-run watchdog (coordinator 2026-11-26 14:57Z, after the gaps 09:56-10:54Z and 12:34-14:56Z).

Every 20 minutes a harness-tracked timer in the work session wakes the session. The session reads the latest text
workflow run with the GitHub tools (the session's gh is limited to search). The API serves no log of a job still in
progress (HTTP 404, 15:04Z), so the activity time is the later of the run's start and its latest results commit
(the workflow commits a checkpoint every 30 minutes); the limit is then 35 minutes. Then:
  watchdog.py check --status <run status> --last-log <ISO time> [--stale-min 35] [--now <ISO time>]
                                                  prints "ok", or "gap: <reason>" and exits 3
  watchdog.py gap --start <ISO> --end <ISO> --cause "<text>"
                                                  records the gap in results/report_notes.json (REPORT "Notes") and
                                                  results/watchdog.jsonl
  watchdog.py queue                               writes the next noop request requests/n<k>.json (a push of a request
                                                  file starts the text workflow; pending requests run before it)
A run is healthy when it is queued, or in progress with its last activity under the limit (20 minutes for a log
line, 35 for a checkpoint commit). A completed run is
never healthy while reading goes on: a request must be pending or running (16:46Z).
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


def check(status: str, last_log: str | None, now: str, pending: list[str], stale_min: float = STALE_MIN) -> str | None:
    """None when healthy, else the reason."""
    if status in ("queued", "requested", "waiting", "pending"):
        return None
    if status == "in_progress":
        if not last_log:
            return "run in progress without a log line"
        age = (_t(now) - _t(last_log)).total_seconds() / 60
        return None if age < stale_min else f"last activity {age:.0f} min old"
    if pending:
        return f"no text run in progress or queued; {len(pending)} request(s) pending: {', '.join(pending)}"
    # 16:46Z: run 14 took chunks 4 and 5 together and run 15 found nothing; an idle workflow with nothing queued is
    # a gap too while reading is not finished
    return "no text run in progress or queued and no request pending"


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
    c.add_argument("--stale-min", type=float, default=STALE_MIN)
    c.add_argument("--now", default=datetime.now(timezone.utc).isoformat())
    g = sub.add_parser("gap")
    g.add_argument("--start", required=True)
    g.add_argument("--end", required=True)
    g.add_argument("--cause", required=True)
    sub.add_parser("queue")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        r = check(a.status, a.last_log, a.now, pending_requests(), a.stale_min)
        print("ok" if r is None else f"gap: {r}")
        return 0 if r is None else 3
    if a.cmd == "gap":
        print(record_gap(a.start, a.end, a.cause))
        return 0
    print(queue_noop())
    return 0


if __name__ == "__main__":
    sys.exit(main())
