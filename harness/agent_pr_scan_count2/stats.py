"""Count 2 numbers from PR rows (shared by report.py and verify_count2.py). Every value is a formatted string, keyed
the way REPORT.md marks it (``<value><!--key-->``)."""
from __future__ import annotations

from collections import Counter

import rules as R

FAMILIES = ["copilot", "devin", "jules", "codex", "claude_code"]


def pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.1f}%"


def block(rows: list[dict], p: str) -> dict[str, str]:
    c = Counter(r["verdict"] for r in rows)
    with_failed = sum(c[v] for v in R.PR_ORDER)
    ar, nr = c[R.ALREADY_RED], c[R.NEW_RED]
    n = ar + nr
    lo, hi = R.wilson(ar, n)
    unrated = c[R.NO_BASE_SIGNAL] + c[R.UNREADABLE]
    sec = sum(1 for r in rows if r["verdict"] in R.PR_ORDER and r.get("secondary_already_red"))
    return {
        f"{p}read": str(len(rows)), f"{p}pr_unreadable": str(c[R.PR_UNREADABLE]),
        f"{p}head_unreadable": str(c[R.HEAD_UNREADABLE]), f"{p}no_failed": str(c[R.NO_FAILED_CHECK]),
        f"{p}with_failed": str(with_failed), f"{p}already_red": str(ar), f"{p}new_red": str(nr),
        f"{p}no_base": str(c[R.NO_BASE_SIGNAL]), f"{p}unreadable": str(c[R.UNREADABLE]), f"{p}n_rateable": str(n),
        f"{p}rate": pct(ar / n if n else float("nan")), f"{p}lo": pct(lo), f"{p}hi": pct(hi),
        f"{p}unrated_share": pct(unrated / with_failed if with_failed else float("nan")),
        f"{p}sec_already": str(sec), f"{p}sec_rate": pct(sec / with_failed if with_failed else float("nan")),
    }


def compute(rows: list[dict]) -> dict[str, str]:
    out = block(rows, "")
    for f in FAMILIES:
        out.update(block([r for r in rows if r["family"] == f], f"{f}_"))
    for st in ("merged", "closed_unmerged"):
        out.update(block([r for r in rows if r["state"] == st], f"{st}_"))
    c = Counter(r["verdict"] for r in rows)
    sentence, valid = R.decision(c)
    out["decision_valid"] = "valid" if valid else "not valid"
    out["_sentence"] = sentence
    return out
