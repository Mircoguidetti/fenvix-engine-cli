#!/usr/bin/env python3
"""Re-derive every number in REPORT.md from the committed raw rows; exit 1 on any mismatch.

In REPORT.md every number from the scan is written as `<number><!--key-->` (the comment is invisible when
rendered). This script recomputes each key from the raw rows and compares. A key in the report that this script
does not know is a failure, so a number cannot enter the report without a derivation here. It also checks the
Count 1 decision sentence against the pre-registered rule (point estimate below 2% -> leave, else stay).

    python3 harness/agent_pr_scan/verify_scan.py          # verify
    python3 harness/agent_pr_scan/verify_scan.py --print  # print every derivable key

Raw rows read: search_rows/*, rules_check.jsonl, count1_rows.jsonl, count1_excluded.jsonl, handcheck.jsonl,
unreadable.jsonl, count3_rows.jsonl, count3_excluded.jsonl.
"""
from __future__ import annotations

import gzip
import json
import math
import random
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUT = ["copilot", "devin", "jules", "codex"]
FAMS = AUT + ["claude_code"]
CODEX_MARK = re.compile(r"chatgpt\.com/codex", re.I)


def rd(name: str) -> list[dict]:
    p = HERE / name
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(100 * (c - h) / den, 1), round(100 * (c + h) / den, 1)


def family_rule(r: dict) -> bool:
    if r["family"] == "codex":
        return r["codex_marker"]
    if r["family"] == "claude_code":
        return r["cc_marker"]
    return True


EXCL_KEYS = {"repository created less than 30 days before merge": "young", "fork": "fork", "archived": "archived",
             "repository cap (3 per repository) reached": "cap"}


def excl_key(reason: str) -> str:
    if reason.startswith("excluded owner"):
        return "owner"
    if reason.startswith("not returned by search/repositories"):
        return "notfound"
    if reason.startswith("did not land on the default branch"):
        return "notdefault"
    if reason == "no test file changed":
        return "notest"
    return EXCL_KEYS.get(reason, "other")


def compute() -> dict:
    k: dict = {}
    # ---- search collection ----
    for f in FAMS:
        rows = rd(f"search_rows/count1_{f}.jsonl.gz")
        wins = rd(f"search_rows/count1_{f}_windows.jsonl")
        k[f"s1_rows_{f}"] = len(rows)
        k[f"s1_windows_{f}"] = sum(not w.get("split") for w in wins)
        months = {}
        for w in wins:
            if w.get("split"):
                months[w["month"]] = w["total_count"]
        for w in wins:
            if not w.get("split") and w["window"] == w["month"]:
                months[w["month"]] = w["total_count"]
        k[f"s1_total_{f}"] = sum(months.values())
        seen, pool = set(), 0
        for r in rows:
            if r["url"] not in seen:
                seen.add(r["url"])
                pool += family_rule(r)
        k[f"s1_unique_{f}"] = len(seen)
        k[f"s1_pool_{f}"] = pool
    for t in ["flaky", "flakiness", "flake", "deflake"]:
        k[f"s3_rows_{t}"] = len(rd(f"search_rows/count3_{t}.jsonl.gz"))
        k[f"s3_windows_{t}"] = sum(not w.get("split") for w in rd(f"search_rows/count3_{t}_windows.jsonl"))
    # ---- rules check ----
    rc = rd("rules_check.jsonl")
    for f in FAMS:
        k[f"rc_n_{f}"] = sum(r["family"] == f for r in rc)
        k[f"rc_yes_{f}"] = sum(r["family"] == f and r["agent_made"] for r in rc)
        k[f"rc_no_{f}"] = k[f"rc_n_{f}"] - k[f"rc_yes_{f}"]
    # ---- count 1 ----
    rows = rd("count1_rows.jsonl")
    excl = rd("count1_excluded.jsonl")
    unread = [u for u in rd("unreadable.jsonl") if u.get("count") == "count1"]
    hc = {h["url"]: h for h in rd("handcheck.jsonl")}
    for phase, fams, tag in (("autonomous", AUT, "aut"), ("claude_code", ["claude_code"], "cc")):
        pr = [r for r in rows if r["phase"] == phase]
        pe = [r for r in excl if r["phase"] == phase]
        pu = [r for r in unread if r["phase"] == phase]
        den = [r for r in pr if r["n_base_test_files"] > 0]
        k[f"c1_{tag}_drawn"] = len(pr) + len(pe) + len(pu)
        k[f"c1_{tag}_excluded"] = len(pe)
        for key, n in Counter(excl_key(e["reason"]) for e in pe).items():
            k[f"c1_{tag}_excl_{key}"] = n
        for key in ("young", "fork", "archived", "cap", "owner", "notfound", "other"):
            k.setdefault(f"c1_{tag}_excl_{key}", 0)
        k[f"c1_{tag}_unreadable"] = len(pu)
        k[f"c1_{tag}_read"] = len(pr)
        k[f"c1_{tag}_den"] = len(den)
        k[f"c1_{tag}_notests"] = len(pr) - len(den)
        k[f"c1_{tag}_pct_with_tests"] = pct(len(den), len(pr))
        for m in ("merge_commit", "squash", "pr_head_merge_base"):
            k[f"c1_{tag}_method_{m}"] = sum(r["method"] == m for r in pr)
        flagged = [r for r in den if r["tier"] != "NONE"]
        strong = [r for r in den if r["tier"] == "STRONG"]
        weak = [r for r in den if r["tier"] == "WEAK"]
        missing = [r["url"] for r in flagged if r["url"] not in hc]
        k[f"c1_{tag}_handcheck_missing"] = len(missing)
        conf_s = [r for r in strong if hc.get(r["url"], {}).get("verdict") == "weakens"]
        conf_w = [r for r in weak if hc.get(r["url"], {}).get("verdict") == "weakens"]
        k[f"c1_{tag}_strong"] = len(strong)
        k[f"c1_{tag}_weak"] = len(weak)
        k[f"c1_{tag}_conf_strong"] = len(conf_s)
        k[f"c1_{tag}_conf_weak"] = len(conf_w)
        k[f"c1_{tag}_prec_strong"] = pct(len(conf_s), len(strong))
        k[f"c1_{tag}_prec_weak"] = pct(len(conf_w), len(weak))
        conf = len(conf_s) + len(conf_w)
        k[f"c1_{tag}_conf"] = conf
        k[f"c1_{tag}_rate"] = pct(conf, len(den))
        k[f"c1_{tag}_lo"], k[f"c1_{tag}_hi"] = wilson(conf, len(den))
        k[f"c1_{tag}_strong_rate"] = pct(len(conf_s), len(den))
        k[f"c1_{tag}_strong_lo"], k[f"c1_{tag}_strong_hi"] = wilson(len(conf_s), len(den))
        k[f"c1_{tag}_rate_all"] = pct(conf, len(pr))
        k[f"c1_{tag}_borderline"] = sum(1 for r in flagged if hc.get(r["url"], {}).get("borderline"))
        k[f"c1_{tag}_flagged"] = len(flagged)
        k[f"c1_{tag}_not_conf"] = len(flagged) - conf
        k[f"c1_{tag}_conf_plus_borderline"] = conf + k[f"c1_{tag}_borderline"]
        k[f"c1_{tag}_testonly_strong_signals"] = sum(r["strong_signals_test_only_pr"] for r in den)
        k[f"c1_{tag}_snapshot_prs"] = sum(r["snapshot_files_changed"] > 0 for r in den)
        k[f"c1_{tag}_test_touching"] = sum(r["n_test_files_changed"] > 0 for r in den)
        for f in fams:
            fd = [r for r in den if r["family"] == f]
            fr = [r for r in pr if r["family"] == f]
            fc = [r for r in fd if r["tier"] != "NONE" and hc.get(r["url"], {}).get("verdict") == "weakens"]
            k[f"c1_read_{f}"] = len(fr)
            k[f"c1_den_{f}"] = len(fd)
            k[f"c1_strong_{f}"] = sum(r["tier"] == "STRONG" for r in fd)
            k[f"c1_weak_{f}"] = sum(r["tier"] == "WEAK" for r in fd)
            k[f"c1_conf_{f}"] = len(fc)
            k[f"c1_rate_{f}"] = pct(len(fc), len(fd))
            k[f"c1_lo_{f}"], k[f"c1_hi_{f}"] = wilson(len(fc), len(fd))
            k[f"c1_excluded_{f}"] = sum(e["family"] == f for e in pe)
            k[f"c1_unreadable_{f}"] = sum(u["family"] == f for u in pu)
    # WEAK sampling rule: every WEAK flag is read when there are at most 40
    k["c1_aut_weak_over_40"] = int(k["c1_aut_weak"] > 40)
    # unflagged reading (autonomous)
    unf = [h for h in hc.values() if h.get("set") == "unflagged"]
    k["c1_unflagged_read"] = len(unf)
    k["c1_unflagged_miss"] = sum(h["verdict"] == "weakens" for h in unf)
    elig = sorted([r for r in rows if r["phase"] == "autonomous" and r["n_base_test_files"] > 0
                   and r["tier"] == "NONE" and r["n_test_files_changed"] > 0], key=lambda r: r["url"])
    k["c1_unflagged_eligible"] = len(elig)
    k["c1_unflagged_draw_matches"] = int(
        {r["url"] for r in random.Random(1).sample(elig, 20)} == {h["url"] for h in unf}) if len(elig) >= 20 else 0
    k["c1_repos_max_per_repo"] = max(Counter(r["repo"].lower() for r in rows + [u for u in unread]).values())
    # ---- count 3 ----
    c3 = rd("count3_rows.jsonl")
    c3e = rd("count3_excluded.jsonl")
    c3u = [u for u in rd("unreadable.jsonl") if u.get("count") == "count3"]
    k["c3_drawn"] = len(c3) + len(c3e) + len(c3u)
    k["c3_excluded"] = len(c3e)
    for key, n in Counter(excl_key(e["reason"]) for e in c3e).items():
        k[f"c3_excl_{key}"] = n
    for key in ("cap", "fork", "notdefault", "notest", "notfound"):
        k.setdefault(f"c3_excl_{key}", 0)
    k["c3_unreadable"] = len(c3u)
    k["c3_read"] = len(c3)
    named = [r for r in c3 if r["identity"]]
    k["c3_nameable"] = len(named)
    k["c3_not_nameable"] = len(c3) - len(named)
    notheld = [r for r in named if r["held"] is False]
    k["c3_notheld"] = len(notheld)
    k["c3_held"] = len(named) - len(notheld)
    k["c3_rate"] = pct(len(notheld), len(named))
    k["c3_lo"], k["c3_hi"] = wilson(len(notheld), len(named))
    for kind in ("changed_again_flaky", "skipped", "deleted_flaky_or_after_skip", "deleted_other"):
        k[f"c3_prs_{kind}"] = sum(any(e["kind"] == kind for e in r["events"]) for r in named)
    k["c3_repos"] = len({r["repo"].lower() for r in c3})
    k["c3_named_file_only"] = sum(all(i["tests"] == ["<file>"] for i in r["identity"]) for r in named)
    k["unreadable_total"] = len(rd("unreadable.jsonl"))

    def ucls(e: str) -> str:
        if "already on the default branch" in e:
            return "head_on_default"
        if "no landing commit found and no merge-base" in e:
            return "no_merge_base"
        if "timeout" in e:
            return "timeout"
        if "couldn't find remote ref" in e:
            return "no_pull_ref"
        return "other"
    for cnt in ("count1", "count3"):
        rows_u = [u for u in rd("unreadable.jsonl") if u.get("count") == cnt]
        for c in ("head_on_default", "no_merge_base", "timeout", "no_pull_ref", "other"):
            k[f"unread_{cnt}_{c}"] = sum(ucls(u["error"]) == c for u in rows_u)
        k[f"unread_{cnt}"] = len(rows_u)
    # ---- preflight (preflight.txt holds the commands and their raw output) ----
    pf = (HERE / "preflight.txt").read_text() if (HERE / "preflight.txt").exists() else ""
    m = re.search(r'"limit":(\d+)', pf)
    k["pf_core_limit"] = int(m.group(1)) if m else -1
    m = re.search(r'"total_count":(\d+)', pf)
    k["pf_search_total"] = int(m.group(1)) if m else -1
    k["pf_http_403"] = pf.count("(HTTP 403)")
    return k


def fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def main() -> int:
    k = compute()
    if "--print" in sys.argv:
        for key in sorted(k):
            print(f"{key}={fmt(k[key])}")
        return 0
    text = (HERE / "REPORT.md").read_text()
    found = re.findall(r"([0-9][0-9.,]*)%?<!--(\w+)-->", text)
    bad = 0
    for val, key in found:
        val = val.replace(",", "")
        if key not in k:
            print(f"UNKNOWN KEY {key} (value {val})")
            bad += 1
        elif fmt(k[key]) != val:
            print(f"MISMATCH {key}: report {val}, rows {fmt(k[key])}")
            bad += 1
    if not found:
        print("no tagged numbers found in REPORT.md")
        bad += 1
    decision = "LEAVE" if k["c1_aut_rate"] < 2.0 else "STAY"
    if f"Decision: **{decision}**" not in text:
        print(f"MISMATCH decision: rule gives {decision} (rate {k['c1_aut_rate']}%)")
        bad += 1
    for must in ("c1_aut_handcheck_missing", "c1_cc_handcheck_missing"):
        if k[must]:
            print(f"INCOMPLETE {must}={k[must]}")
            bad += 1
    if k["c1_repos_max_per_repo"] > 3:
        print("MISMATCH repository cap exceeded")
        bad += 1
    if k["c1_unflagged_read"] and not k["c1_unflagged_draw_matches"]:
        print("MISMATCH unflagged reading set is not the seeded draw")
        bad += 1
    print(f"{len(found)} tagged numbers checked, decision {decision} checked, {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
