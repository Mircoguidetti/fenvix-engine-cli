#!/usr/bin/env python3
"""Re-derive every count in REPORT.md from scan.jsonl; exit 1 on any mismatch.

In REPORT.md every number that comes from the scan is written as `<number><!--key-->` (the comment is invisible
when rendered). This script recomputes `key` from scan.jsonl and compares. A key in the report that this script
does not know is also a failure, so a number cannot be added to the report without a derivation here.

    python3 harness/flaky_scan/verify_scan.py            # verify
    python3 harness/flaky_scan/verify_scan.py --print    # print every derivable key (to write the report)
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAMES = ("neutral", "mechanism", "flakyword")
MECHS = ("playwright_retries", "vitest_retry", "jest_retryTimes", "mocha_retries", "cypress_retries", "pytest_reruns",
         "pytest_mark_flaky", "flaky_plugin", "pytest_retry", "ci_rerun", "quarantine_ci", "quarantine_list",
         "skip_flaky")
BUCKETS = {"under 1": "under1", "1-6": "1_6", "6-12": "6_12", "over 12": "over12"}


def pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def compute(rows: list[dict]) -> dict:
    k: dict = {}
    k["examined"] = len(rows)
    k["scanned_ok"] = sum(r["scan_status"] == "ok" for r in rows)
    k["examined_js"] = sum(r["lang_bucket"] == "js" for r in rows)
    k["examined_py"] = sum(r["lang_bucket"] == "py" for r in rows)
    k["vendored_excluded"] = sum(bool(r["vendored_exclusion"]) for r in rows)
    k["excluded_signals"] = sum(r["excluded_signals"] or 0 for r in rows)
    k["stars_known"] = sum(r["stars"] is not None for r in rows)
    k["lives_all"] = sum(r["lives_with_flaky"] for r in rows)
    for f in FRAMES:
        fr = [r for r in rows if r["frame"] == f]
        n = len(fr)
        k[f"{f}_n"] = n
        k[f"{f}_queries"] = len({r["query"] for r in fr})
        for name, sel in (("lives", lambda r: r["lives_with_flaky"]),
                          ("stated", lambda r: r["classification"] == "stated"),
                          ("implied", lambda r: r["classification"] == "implied"),
                          ("strict_stated", lambda r: r["classification_strict"] == "stated"),
                          ("scaffold_only", lambda r: r["only_scaffold_default"]),
                          ("skip_flaky", lambda r: bool(r["skipped_flaky_tests"]))):
            c = sum(1 for r in fr if sel(r))
            k[f"{f}_{name}"] = c
            k[f"pct_{f}_{name}"] = pct(c, n)
        lives = k[f"{f}_lives"]
        k[f"pct_{f}_stated_of_lives"] = pct(k[f"{f}_stated"], lives)
        k[f"pct_{f}_strict_stated_of_lives"] = pct(k[f"{f}_strict_stated"], lives)
        k[f"pct_{f}_implied_of_lives"] = pct(k[f"{f}_implied"], lives)
        k[f"{f}_lives_excl_scaffold"] = lives - k[f"{f}_scaffold_only"]
        k[f"pct_{f}_lives_excl_scaffold"] = pct(k[f"{f}_lives_excl_scaffold"], n)
        for lb in ("js", "py"):
            sub = [r for r in fr if r["lang_bucket"] == lb]
            k[f"{f}_{lb}_n"] = len(sub)
            k[f"{f}_{lb}_lives"] = sum(r["lives_with_flaky"] for r in sub)
            k[f"pct_{f}_{lb}_lives"] = pct(k[f"{f}_{lb}_lives"], len(sub))
        big = [r for r in fr if (r["stars"] or 0) >= 100]
        k[f"{f}_100_n"] = len(big)
        k[f"{f}_100_lives"] = sum(r["lives_with_flaky"] for r in big)
        k[f"pct_{f}_100_lives"] = pct(k[f"{f}_100_lives"], len(big))
        k[f"{f}_100_stated"] = sum(r["classification"] == "stated" for r in big)
        k[f"pct_{f}_100_stated"] = pct(k[f"{f}_100_stated"], len(big))
    # per query (index = order in collect.py QUERIES): repos found FIRST by that query
    import importlib.util
    spec = importlib.util.spec_from_file_location("collect", HERE / "collect.py")
    col = importlib.util.module_from_spec(spec); spec.loader.exec_module(col)
    for i, (_, _, q, _) in enumerate(col.QUERIES, 1):
        sub = [r for r in rows if r["query"] == q]
        k[f"q{i}_n"] = len(sub)
        k[f"q{i}_lives"] = sum(r["lives_with_flaky"] for r in sub)
        k[f"q{i}_stated"] = sum(r["classification"] == "stated" for r in sub)
        k[f"pct_q{i}_lives"] = pct(k[f"q{i}_lives"], len(sub))
    nopw = [r for r in rows if r["frame"] == "neutral" and "playwright" not in r["query"]]
    k["neutral_nopw_n"] = len(nopw)
    k["neutral_nopw_lives"] = sum(r["lives_with_flaky"] for r in nopw)
    k["pct_neutral_nopw_lives"] = pct(k["neutral_nopw_lives"], len(nopw))
    k["neutral_nopw_stated"] = sum(r["classification"] == "stated" for r in nopw)
    k["pct_neutral_nopw_stated"] = pct(k["neutral_nopw_stated"], len(nopw))
    for m in MECHS:
        k[f"mech_{m}"] = sum(m in r["mechanisms"] for r in rows)
        k[f"mech_{m}_neutral"] = sum(m in r["mechanisms"] for r in rows if r["frame"] == "neutral")
        k[f"mech_{m}_stated"] = sum(1 for r in rows if (m == "skip_flaky" and r["skipped_flaky_tests"]) or
                                    any(s["mechanism"] == m and s["stated"] for s in r["signals"]))
    # retry repos with no stated reason anywhere near ANY of their retry lines
    retry = [r for r in rows if any(s["mechanism"] not in ("quarantine_ci", "quarantine_list") for s in r["signals"])]
    k["retry_repos"] = len(retry)
    k["mechanism_none"] = k["mechanism_n"] - k["mechanism_lives"]
    k["retry_repos_unstated"] = sum(not any(s["stated"] for s in r["signals"]) for r in retry)
    k["pct_retry_repos_unstated"] = pct(k["retry_repos_unstated"], len(retry))

    # ---- D22 ----
    sk = [(r, s) for r in rows for s in r["skipped_flaky_tests"]]
    for tag, sub in (("", sk), ("strict_", [(r, s) for r, s in sk if s["strict_stated"]]),
                     ("uncond_", [(r, s) for r, s in sk if s["skip_kind"] == "unconditional"])):
        n = len(sub)
        k[f"skips_{tag}n"] = n
        k[f"skips_{tag}repos"] = len({r["repo"] for r, _ in sub})
        c = Counter(s["age_bucket"] for _, s in sub)
        for b, key in BUCKETS.items():
            k[f"skips_{tag}b_{key}"] = c.get(b, 0)
            k[f"pct_skips_{tag}b_{key}"] = pct(c.get(b, 0), n)
        k[f"skips_{tag}b_lower_bound"] = sum(v for b, v in c.items() if b.startswith("lower_bound"))
        k[f"skips_{tag}b_unknown"] = c.get("UNKNOWN", 0)
        over6 = c.get("6-12", 0) + c.get("over 12", 0) + c.get("lower_bound 6-12", 0)
        k[f"skips_{tag}over6"] = over6
        k[f"pct_skips_{tag}over6"] = pct(over6, n)
        st = Counter(s["issue_state"] for _, s in sub)
        k[f"skips_{tag}ref_any"] = n - st.get("none", 0)
        k[f"pct_skips_{tag}ref_any"] = pct(k[f"skips_{tag}ref_any"], n)
        for x in ("open", "closed", "UNKNOWN", "none"):
            k[f"skips_{tag}ref_{x.lower()}"] = st.get(x, 0)
            k[f"pct_skips_{tag}ref_{x.lower()}"] = pct(st.get(x, 0), n)
    k["skips_over12_lower_bound"] = sum(1 for _, s in sk if s["age_bucket"] == "over 12" and s["added_date_is_lower_bound"])
    k["skips_unconditional"] = sum(s["skip_kind"] == "unconditional" for _, s in sk)
    k["skips_conditional"] = sum(s["skip_kind"] == "conditional" for _, s in sk)
    top = Counter(r["repo"] for r, _ in sk).most_common(3)
    k["skips_top3_share"] = pct(sum(v for _, v in top), len(sk))
    # per repository: the OLDEST dated flaky skip it carries
    order = ["over 12", "lower_bound 6-12", "6-12", "lower_bound 1-6", "1-6", "lower_bound under 1", "under 1"]
    per = {}
    for r, s in sk:
        if s["age_bucket"] in order:
            cur = per.get(r["repo"])
            if cur is None or order.index(s["age_bucket"]) < order.index(cur):
                per[r["repo"]] = s["age_bucket"]
    k["repos_dated"] = len(per)
    pc = Counter(v.replace("lower_bound ", "") for v in per.values())
    for b, key in BUCKETS.items():
        k[f"repos_oldest_{key}"] = pc.get(b, 0)
        k[f"pct_repos_oldest_{key}"] = pct(pc.get(b, 0), len(per))
    k["repos_oldest_over6"] = pc.get("6-12", 0) + pc.get("over 12", 0)
    k["pct_repos_oldest_over6"] = pct(k["repos_oldest_over6"], len(per))
    k["repos_with_open_issue_ref"] = len({r["repo"] for r, s in sk if s["issue_state"] == "open"})
    k["issue_refs_total"] = sum(len(s["issue_ref"]) for _, s in sk)
    k["issue_refs_checked"] = sum(1 for _, s in sk for x in s["issue_ref"] if x.get("state") not in (None, "UNKNOWN"))
    return k


def fmt(v) -> str:
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def main() -> int:
    rows = [json.loads(l) for l in (HERE / "scan.jsonl").open() if l.strip()]
    k = compute(rows)
    if "--print" in sys.argv:
        for key in sorted(k):
            print(f"{key}={fmt(k[key])}")
        return 0
    text = (HERE / "REPORT.md").read_text()
    found = re.findall(r"([0-9][0-9.]*)%?<!--(\w+)-->", text)
    bad = 0
    for val, key in found:
        if key not in k:
            print(f"UNKNOWN KEY {key} (value {val})"); bad += 1
        elif fmt(k[key]) != val:
            print(f"MISMATCH {key}: report {val}, scan.jsonl {fmt(k[key])}"); bad += 1
    if not found:
        print("no tagged numbers found in REPORT.md"); bad += 1
    print(f"{len(found)} tagged numbers checked, {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
