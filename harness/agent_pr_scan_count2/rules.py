"""Count 2 rules (pure): failure states, check identity, per-check and per-PR verdicts, rates, decision sentence.

Every verdict in the results is produced by ``pipeline.run_pr`` through these functions, both in the Actions job
(live API) and in ``verify_count2.py`` (replay of the committed raw JSON), so one code path decides both.
"""
from __future__ import annotations

import datetime as dt
import math

FAILED_RUN = {"failure", "timed_out", "startup_failure"}
NOT_FAILED_RUN = {"success", "cancelled", "skipped", "neutral", "action_required", "stale"}
FAILED_STATUS = {"failure", "error"}
NOT_FAILED_STATUS = {"success", "pending"}

ALREADY_RED, NEW_RED, NO_BASE_SIGNAL, UNREADABLE = "ALREADY_RED", "NEW_RED", "NO_BASE_SIGNAL", "UNREADABLE"
RATEABLE = (ALREADY_RED, NEW_RED)
PR_ORDER = (ALREADY_RED, NEW_RED, NO_BASE_SIGNAL, UNREADABLE)
# outcomes of PRs that are not in the failed-check denominator
NO_FAILED_CHECK, PR_UNREADABLE, HEAD_UNREADABLE = "NO_FAILED_CHECK", "PR_UNREADABLE", "HEAD_UNREADABLE"

WINDOW = dt.timedelta(days=7)
THRESHOLD = 0.20
VALIDITY_CEILING = 0.50
SENT_FORWARD = "Idea 3 moves forward: the primary rate is at least 20%."
SENT_PARKED = "Idea 3 is parked: the primary rate is below 20%."
SENT_INVALID = "No decision under the rule: the measured share is not valid; the founder decides."


def ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_failed(conclusion: str | None) -> bool:
    return conclusion in FAILED_RUN


def status_failed(state: str | None) -> bool:
    return state in FAILED_STATUS


def actions_identity(workflow_name: str, job_name: str) -> str:
    return f"{workflow_name} / {job_name}"


def result_of_run(conclusion: str | None) -> str | None:
    """A completed base check run's signal: failed -> ALREADY_RED, success -> NEW_RED, else None (no signal)."""
    if conclusion in FAILED_RUN:
        return ALREADY_RED
    if conclusion == "success":
        return NEW_RED
    return None


def result_of_status(state: str | None) -> str | None:
    if state in FAILED_STATUS:
        return ALREADY_RED
    if state == "success":
        return NEW_RED
    return None


def pick_primary(base_results: list[dict], head_started: dt.datetime) -> dict | None:
    """Most recent usable base result of one identity: started before ``head_started`` and at most 7 days before it.

    ``base_results``: dicts with ``started`` (datetime), ``completed`` (bool) and ``signal`` (ALREADY_RED, NEW_RED or
    None). Results without a signal (not completed, cancelled, skipped, pending, ...) are passed over.
    """
    ok = [b for b in base_results if b["completed"] and b["signal"] and b["started"] is not None
          and head_started - WINDOW <= b["started"] < head_started]
    return max(ok, key=lambda b: b["started"]) if ok else None


def pr_verdict(check_verdicts: list[str]) -> str:
    for v in PR_ORDER:
        if v in check_verdicts:
            return v
    raise ValueError("PR with a failed check but no check verdict")


def secondary_hit(base_results: list[dict], pr_created: dt.datetime) -> bool:
    """Secondary rule: any failed base result of the identity started in [created - 7 days, created)."""
    return any(b["signal"] == ALREADY_RED and b["started"] is not None
               and pr_created - WINDOW <= b["started"] < pr_created for b in base_results)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def decision(counts: dict[str, int]) -> tuple[str, bool]:
    """Pre-registered decision sentence from pooled PR verdict counts. Returns (sentence, valid)."""
    with_failed = sum(counts.get(v, 0) for v in PR_ORDER)
    n = counts.get(ALREADY_RED, 0) + counts.get(NEW_RED, 0)
    unrated = counts.get(NO_BASE_SIGNAL, 0) + counts.get(UNREADABLE, 0)
    if n == 0 or with_failed == 0 or unrated / with_failed > VALIDITY_CEILING:
        return SENT_INVALID, False
    rate = counts.get(ALREADY_RED, 0) / n
    return (SENT_FORWARD if rate >= THRESHOLD else SENT_PARKED), True
