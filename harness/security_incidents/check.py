#!/usr/bin/env python3
"""Consistency check for the security-incidents desk research.

protects=   the REPORT.md verdict (line 1), its headline counts, the FLAGGED-by-scope, NOT_FLAGGED-by-reason and
            counts=no-by-rule breakdowns and the query totals equal what incidents.csv and queries.md say.
fails_when= a verdict or a count the CSV does not support, a required field left empty, a counts=no row without the
            failing rule number, a FLAGGED row without its channels.md line or its rule-3c statement, a flag_reason
            that does not start with a known reason, or a BLOCKED line when no more than half the queries failed.
no_claim=   that the sources were read correctly, or that the search was complete.

Run: python harness/security_incidents/check.py   (exit 0 = consistent)
"""

from __future__ import annotations

import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

FIELDS = [
    "id", "name", "disclosed", "disclosed_url", "ecosystem", "delivery", "execution_point", "all_points",
    "ci_explicit", "secrets_read", "exfil", "sources", "n_sources", "counts", "flagged", "scope", "flag_reason",
    "channels_line", "flagged_if_install_traced",
]
NA_OK_WHEN_NOT_COUNTED = {"flagged", "scope", "channels_line", "flagged_if_install_traced"}  # note 5
ENUMS = {
    "ecosystem": {"npm", "PyPI", "GitHub Actions", "other"},
    "delivery": {"new package version", "new dependency", "new commit", "Action", "agent/tool", "other"},
    "execution_point": {"install_script", "ci_step", "build_step", "test_process_import", "test_process_call",
                        "other", "unclear"},
    "ci_explicit": {"yes", "no"},
    "flagged": {"FLAGGED", "NOT_FLAGGED", "UNCLEAR"},
    "scope": {"per_test", "run_level", "setup_digest", "none"},
    "flagged_if_install_traced": {"yes", "no", "unclear"},
}
REASONS = ("not_traced", "channel", "not_new", "unclear_where", "unclear_how")
SCOPES = ("per_test", "run_level", "setup_digest")

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def read_csv(name: str) -> list[dict]:
    with open(os.path.join(HERE, name), newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = []
        for n, raw in enumerate(reader, 2):
            if None in raw or any(v is None for v in raw.values()):
                err(f"{name} line {n}: wrong number of columns")
            rows.append({k: (v or "").strip() for k, v in raw.items() if k is not None})
    if name == "incidents.csv" and header != FIELDS:
        err(f"incidents.csv header differs from spec section 2: {header}")
    return rows


def check_rows(rows: list[dict]) -> None:
    channel_ids = set(re.findall(r"\|\s*(C-\d\d)\s*\|", open(os.path.join(HERE, "channels.md"), encoding="utf-8").read()))
    seen = set()
    for r in rows:
        rid = r.get("id", "?")
        if rid in seen:
            err(f"{rid}: duplicate id")
        seen.add(rid)
        counted = r["counts"].startswith("yes")
        for k in FIELDS:
            v = (r.get(k) or "").strip()
            if not v:
                err(f"{rid}: empty field {k}")
            elif v == "n/a" and not (k in NA_OK_WHEN_NOT_COUNTED and not counted):
                err(f"{rid}: n/a not allowed in {k}")
        for k, allowed in ENUMS.items():
            v = r[k].strip()
            if v and v != "n/a" and v not in allowed:
                err(f"{rid}: {k}={v!r} not in {sorted(allowed)}")
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", r["disclosed"]) or not ("2025-01-01" <= r["disclosed"] <= "2026-11-24"):
            err(f"{rid}: disclosed {r['disclosed']!r} not a date in 2025-01-01..2026-11-24")
        if not r["disclosed_url"].startswith("http"):
            err(f"{rid}: disclosed_url is not a URL")
        if r["disclosed_url"] not in r["sources"]:
            err(f"{rid}: disclosed_url not among sources")
        n = len([s for s in r["sources"].split(";") if s.strip()])
        if not r["n_sources"].isdigit() or int(r["n_sources"]) < 1:
            err(f"{rid}: n_sources must be a positive integer")
        elif int(r["n_sources"]) < n:
            err(f"{rid}: n_sources {r['n_sources']} lower than the {n} listed sources")
        if r["counts"] not in ("yes",) and not re.fullmatch(r"no \(rule [1-7](?:[;,] ?[1-7])*\)", r["counts"]):
            err(f"{rid}: counts must be 'yes' or 'no (rule N)', got {r['counts']!r}")
        if counted:
            if r["flagged"] == "NOT_FLAGGED" and not r["flag_reason"].startswith(REASONS[:3]):
                err(f"{rid}: NOT_FLAGGED flag_reason must start with not_traced|channel|not_new")
            if r["flagged"] == "UNCLEAR" and not r["flag_reason"].startswith(("unclear_where", "unclear_how")):
                err(f"{rid}: UNCLEAR flag_reason must start with unclear_where|unclear_how")
            if r["flagged"] == "FLAGGED":
                if r["scope"] not in SCOPES:
                    err(f"{rid}: FLAGGED needs scope per_test|run_level|setup_digest")
                if r["execution_point"] not in ("test_process_import", "test_process_call"):
                    err(f"{rid}: FLAGGED but execution_point is not in a test process (rule 3a)")
                if "3c:" not in r["flag_reason"]:
                    err(f"{rid}: FLAGGED row must state rule 3c ('3c: ...' in flag_reason)")
            else:
                if r["scope"] != "none":
                    err(f"{rid}: scope must be none unless FLAGGED")
            cited = set(re.findall(r"C-\d\d", r["channels_line"]))
            if not cited:
                err(f"{rid}: counted row must cite a channels.md line (C-NN)")
            elif not cited <= channel_ids:
                err(f"{rid}: cites unknown channels.md line(s) {sorted(cited - channel_ids)}")


def summary(rows: list[dict]) -> dict:
    counted = [r for r in rows if r["counts"] == "yes"]
    s = {
        "counted": len(counted),
        "flagged": sum(r["flagged"] == "FLAGGED" for r in counted),
        "unclear": sum(r["flagged"] == "UNCLEAR" for r in counted),
        "not_flagged": sum(r["flagged"] == "NOT_FLAGGED" for r in counted),
        "counts_no": len(rows) - len(counted),
    }
    if s["flagged"] + s["unclear"] + s["not_flagged"] != s["counted"]:
        err("FLAGGED + UNCLEAR + NOT_FLAGGED differs from the counted total")
    for sc in SCOPES:
        s[f"scope_{sc}"] = sum(r["flagged"] == "FLAGGED" and r["scope"] == sc for r in counted)
    for re_ in REASONS[:3]:
        s[f"nf_{re_}"] = sum(r["flagged"] == "NOT_FLAGGED" and r["flag_reason"].startswith(re_) for r in counted)
    for k in range(1, 8):
        s[f"no_rule_{k}"] = sum(bool(re.match(rf"no \(rule (?:[1-7][;,] ?)*{k}\b", r["counts"])) for r in rows)
    return s


def queries() -> tuple[int, int, bool]:
    text = open(os.path.join(HERE, "queries.md"), encoding="utf-8").read()
    rows = [l for l in text.splitlines() if re.match(r"\|\s*Q\d+\s*\|", l)]
    ok = sum(bool(re.search(r"\|\s*ok\s*\|", l)) for l in rows)
    failed = sum(bool(re.search(r"\|\s*failed\s*\|", l)) for l in rows)
    if ok + failed != len(rows):
        err(f"queries.md: {len(rows) - ok - failed} query rows marked neither ok nor failed")
    for fam in ("F1", "F2", "F3", "F4", "F5"):
        if not any(re.search(rf"\|\s*{fam}\s*\|", l) for l in rows):
            err(f"queries.md: required family {fam} has no query")
    m = re.search(r"^Totals: (\d+) queries, (\d+) ok, (\d+) failed", text, re.M)
    if not m or (int(m.group(1)), int(m.group(2)), int(m.group(3))) != (len(rows), ok, failed):
        err(f"queries.md: Totals line missing or differs from the rows ({len(rows)} queries, {ok} ok, {failed} failed)")
    stop = bool(re.search(r"^Stopped by:", text, re.M))
    if not stop:
        err("queries.md: no 'Stopped by:' line")
    return ok, failed, stop


def main() -> int:
    rows = read_csv("incidents.csv")
    check_rows(rows)
    s = summary(rows)
    ok, failed, _ = queries()
    expected = "CONTINUE" if s["counted"] >= 5 and s["flagged"] >= 3 else "DROP"
    report = open(os.path.join(HERE, "REPORT.md"), encoding="utf-8").read().splitlines()
    first = report[0] if report else ""
    if failed * 2 > ok + failed:
        if not first.startswith("BLOCKED: "):
            err(f"{failed} of {ok + failed} queries failed: REPORT.md line 1 must be 'BLOCKED: <reason>'")
    elif first.startswith("BLOCKED: "):
        err(f"REPORT.md says BLOCKED but only {failed} of {ok + failed} queries failed")
    elif first != expected:
        err(f"REPORT.md line 1 is {first!r}, incidents.csv gives {expected!r}")
    body = "\n".join(report)
    for key, label in (("counted", "Counted incidents"), ("flagged", "FLAGGED"), ("unclear", "UNCLEAR"),
                       ("not_flagged", "NOT_FLAGGED"), ("counts_no", "counts=no")):
        found = re.findall(rf"^{re.escape(label)}: (\d+)", body, re.M)
        if len(found) != 1:
            err(f"REPORT.md must have exactly one line '{label}: N' (found {len(found)})")
        elif int(found[0]) != s[key]:
            err(f"REPORT.md {label}: {found[0]}, incidents.csv gives {s[key]}")
    breakdown = {
        "FLAGGED by scope": [(sc, s["scope_" + sc]) for sc in SCOPES],
        "NOT_FLAGGED by reason": [(r, s["nf_" + r]) for r in REASONS[:3]],
    }
    for label, pairs in breakdown.items():
        m = re.search(rf"^\* {re.escape(label)}: (.*)$", body, re.M)
        if not m:
            err(f"REPORT.md lacks the line '* {label}: ...'")
            continue
        for k, v in pairs:
            g = re.search(rf"\b{k} (\d+)", m.group(1))
            if not g or int(g.group(1)) != v:
                err(f"REPORT.md {label}: {k} should be {v}")
    for k in range(1, 8):
        g = re.search(rf"^  \* rule {k} \([^)]*\): (\d+)", body, re.M)
        if not g or int(g.group(1)) != s[f"no_rule_{k}"]:
            err(f"REPORT.md counts=no by rule: rule {k} should be {s[f'no_rule_{k}']}")
    m = re.search(r"(\d+) queries, (\d+) ok, (\d+) failed", body)
    if not m or (int(m.group(2)), int(m.group(3))) != (ok, failed):
        err(f"REPORT.md query totals missing or differ from queries.md ({ok} ok, {failed} failed)")
    log_only = len(read_csv("log_only.csv"))
    m = re.search(r"^Log-only: (\d+)", body, re.M)
    if not m or int(m.group(1)) != log_only:
        err(f"REPORT.md Log-only line missing or differs from log_only.csv ({log_only})")
    print(f"incidents.csv: {len(rows)} rows; counted {s['counted']}; FLAGGED {s['flagged']}; "
          f"NOT_FLAGGED {s['not_flagged']}; UNCLEAR {s['unclear']}; counts=no {s['counts_no']}; log-only {log_only}")
    print("FLAGGED by scope: " + ", ".join(f"{sc} {s['scope_' + sc]}" for sc in SCOPES))
    print("NOT_FLAGGED by reason: " + ", ".join(f"{r} {s['nf_' + r]}" for r in REASONS[:3]))
    print("counts=no by rule: " + ", ".join(f"rule {k} {s[f'no_rule_{k}']}" for k in range(1, 8) if s[f"no_rule_{k}"]))
    print(f"queries: {ok} ok, {failed} failed; verdict from CSV: {expected}; REPORT line 1: {first!r}")
    for e in errors:
        print("ERROR:", e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
