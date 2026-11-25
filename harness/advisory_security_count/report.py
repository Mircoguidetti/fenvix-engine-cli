#!/usr/bin/env python3
"""Print REPORT.md from the committed rows (PREREG "Report"). Every number is written <n><!--key-->.

  report.py            write REPORT.md
  report.py --stdout   print it instead
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import doubleread as DR  # noqa: E402
import fetch as F  # noqa: E402
import reading as RD  # noqa: E402
import rules as R  # noqa: E402

CHECKPOINT = "cp300b"  # repeated after round 1 at cp300 failed (prereg_changes.md, change 1)
ROUND1 = "cp300"


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "n/a"


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def gold_expected() -> dict[str, set[tuple]]:
    return {
        "G1": {("excluded", "not-web", None, None)},
        "G2": {("excluded", "not-web", None, None), ("excluded", "one-principal", None, None)},
        "G3": {("included", None, "read-the-code", None)},
        "G4": {("included", None, "ours", "O5-time")},
        "G5": {("included", None, "ours", "O3-concurrency")},
        "G6": {("included", None, "read-the-code", None)},
    }


def gold_score(path: Path) -> tuple[int, int, list[str]]:
    exp = gold_expected()
    rows = {r["ghsa_id"]: r for r in read_jsonl(path)}
    ok, miss = 0, []
    for g, allowed in exp.items():
        r = rows.get(g)
        t = (r["inclusion"], r.get("reason"), r.get("class"), r.get("subclass")) if r else None
        if t in allowed:
            ok += 1
        else:
            miss.append(g)
    return ok, len(exp), miss


def compute() -> dict:
    """All numbers and tables of the report, from committed files only."""
    v: dict = {}
    meta = json.loads((F.DATA / "listing_meta.json").read_text())
    budget = json.loads((F.DATA / "budget.json").read_text())
    frame = [json.loads(x) for x in gzip.open(F.DATA / "frame.jsonl.gz", "rt")]
    order = RD.order()
    labs = RD.load_labels()
    mats = F.load_material()
    fr = {r["ghsa_id"]: r for r in frame}

    v["list_date"] = meta["list_date"]
    v["first_request"] = budget["first_data_request"]
    for eco in R.ECOSYSTEMS:
        v[f"listed_{eco}"] = meta["pages"][eco]["rows"]
    v["listed_total"] = sum(meta["pages"][e]["rows"] for e in R.ECOSYSTEMS)
    v["frame"] = len(frame)
    for eco in R.ECOSYSTEMS:
        v[f"frame_{eco}"] = sum(eco in r["ecosystems"] for r in frame)
    v["candidates"] = len(order)
    for k in "abc":
        v[f"route_{k}"] = sum(r["route"] == k for r in frame)
        v[f"member_{k}"] = sum(bool(r[f"member_{k}"]) for r in frame)
    b_only = [r for r in frame if r["route"] == "b"]
    v["route_b_cwe79"] = sum("CWE-79" in r["cwes"] for r in b_only)
    v["route_b_cwe352"] = sum("CWE-352" in r["cwes"] for r in b_only)

    # reading, in order
    read = [g for g in order if g in labs]
    v["read"] = len(read)
    if read != order[:len(read)]:
        raise SystemExit("labels are not a prefix of the reading order")
    eff = {g: R.effective_label(labs[g], R.material_text(mats[g])) for g in read}
    v["quote_flags"] = sum(1 for g in read if eff[g]["quote_flag"])
    v["included_all"] = sum(eff[g]["inclusion"] == "included" for g in read)

    # checkpoint
    n_cp = R.checkpoint_prefix(order, labs)
    v["cp_rows"] = n_cp or 0
    scope = order[:n_cp] if n_cp else read
    inc = [g for g in scope if eff[g]["inclusion"] == "included"]
    exc = [g for g in scope if eff[g]["inclusion"] == "excluded"]
    v["cp_read"] = len(scope)
    v["included"] = len(inc)
    v["excluded"] = len(exc)
    for reason in sorted(R.EXCLUSION_REASONS):
        v[f"exc_{reason}"] = sum(eff[g]["reason"] == reason for g in exc)
    ours1 = [g for g in inc if eff[g]["class"] == "ours"]
    v["ours_first"] = len(ours1)

    dr = DR.stats(CHECKPOINT) if (DR.cp_dir(CHECKPOINT) / "labels-2.jsonl").exists() else None
    disputed = set(dr["disputed"]) if dr else set()
    final = {g: dict(eff[g]) for g in scope}
    for g in disputed:
        final[g]["class"], final[g]["subclass"] = "unclear", None
    ours = [g for g in inc if final[g]["class"] == "ours"]
    v["ours"] = len(ours)
    v["read_the_code"] = sum(final[g]["class"] == "read-the-code" for g in inc)
    v["unclear"] = sum(final[g]["class"] == "unclear" for g in inc)
    v["disputed"] = len(disputed)
    v["share"] = pct(len(ours), len(inc))
    lo, hi = R.wilson(len(ours), len(inc))
    v["wilson_lo"], v["wilson_hi"] = f"{100 * lo:.1f}%", f"{100 * hi:.1f}%"
    a_inc = [g for g in inc if fr[g]["route"] == "a"]
    a_ours = [g for g in ours if fr[g]["route"] == "a"]
    v["included_a"], v["ours_a"], v["share_a"] = len(a_inc), len(a_ours), pct(len(a_ours), len(a_inc))
    for sub in sorted(R.SUBCLASSES):
        v[f"sub_{sub}"] = sum(final[g]["subclass"] == sub for g in ours)
    v["with_fix"] = sum(any(f.get("status") == 200 for f in mats[g]["fixes"]) for g in inc)
    v["with_fix_share"] = pct(v["with_fix"], len(inc))

    # double read
    if dr:
        v["dr_sample"], v["dr_read"] = dr["sample"], dr["second_read"]
        v["dr_kappa"] = f"{dr['kappa']:.2f}" if dr["kappa"] is not None else "n/a"
        v["dr_ours_first"], v["dr_confirmed"] = dr["ours_first"], dr["confirmed"]
        v["dr_confirmed_share"] = pct(dr["confirmed"], dr["ours_first"])
        v["dr_second_only"] = len(dr["second_only_ours"])
        v["dr_ok"] = "yes" if dr["ok"] else "no"
    r1 = json.loads((DR.cp_dir(ROUND1) / "stats.json").read_text())
    v["r1_sample"], v["r1_kappa"] = r1["sample"], f"{r1['kappa']:.2f}"
    v["r1_confirmed"], v["r1_ours_first"] = r1["confirmed"], r1["ours_first"]
    v["r1_confirmed_share"] = pct(r1["confirmed"], r1["ours_first"])
    v["r1_gold_ok"] = gold_score(DR.cp_dir(ROUND1) / "gold-reader2.jsonl")[0]
    rr = read_jsonl(HERE / "reread" / "cp300b.jsonl")
    v["reread_rows"], v["reread_changed"] = len(rr), sum(r["new"] != "unchanged" for r in rr)
    gs = gold_score(HERE / "gold" / "labels-reader2-pre.jsonl")
    v["gold_pre_ok"], v["gold_n"] = gs[0], gs[1]
    gd = gold_score(DR.cp_dir(CHECKPOINT) / "gold-reader2.jsonl")
    v["gold_dr_ok"] = gd[0]
    v["gold_first_ok"] = gold_score(HERE / "gold" / "labels-reader1.jsonl")[0]

    # decision (integers; decisions only at checkpoints; double read must pass)
    all_read = len(read) == len(order)
    decision = None
    if dr and dr["ok"] and dr["second_read"] == dr["sample"]:
        decision = R.decide(len(ours), len(inc), at_checkpoint=n_cp is not None, all_read=all_read)
    v["decision"] = decision

    # requests
    reqs = []
    for p in sorted(F.DATA.glob("requests*.jsonl")):
        reqs += read_jsonl(p)
    v["requests"] = len(reqs)
    v["requests_non_get"] = sum(r["method"] != "GET" for r in reqs)
    v["requests_search"] = sum("/search/" in r["path"] for r in reqs)
    v["requests_workflow"] = sum(r.get("route") == "workflow" for r in reqs)

    # tables
    v["_ours_rows"] = [{"ghsa_id": g, "packages": ", ".join(sorted({p["name"] for p in mats[g]["packages"]}))[:60],
                        "eco": ",".join(fr[g]["ecosystems"]), "severity": fr[g]["severity"],
                        "subclass": final[g]["subclass"], "quote": final[g]["quote"],
                        "fix": next((f["ref"]["url"] for f in mats[g]["fixes"] if f.get("status") == 200), ""),
                        "confirmed": (g in DR.load2(CHECKPOINT) and R.is_ours(DR.load2(CHECKPOINT)[g]))}
                       for g in sorted(ours)]
    v["_disputed_rows"] = sorted(disputed)
    by_eco, by_sev, proj = Counter(), Counter(), Counter()
    for g in ours:
        for e in fr[g]["ecosystems"]:
            by_eco[e] += 1
        by_sev[fr[g]["severity"]] += 1
    for g in inc:
        proj[R.repo_of(fr[g]["source_code_location"]) or fr[g]["packages"][0]] += 1
    v["_ours_eco"], v["_ours_sev"] = dict(by_eco), dict(by_sev)
    v["_top_projects"] = proj.most_common(10)
    v["_dr"] = dr
    return v


def k(v: dict, key: str) -> str:
    return f"{v[key]}<!--{key}-->"


def render(v: dict) -> str:
    d = v["decision"]
    first = "DONE" if d in ("CONTINUE", "DROP") else "NOT DONE"
    L = [first, "",
         "# Public count of security advisories whose root cause is order, timing or shared state", "",
         "Pre-registration: `PREREG.md` (committed before any data). Branch `claude/advisory-security-count`. "
         "Every number below is written `<n><!--key-->` and re-derived by `verify.py`.", ""]
    L += ["## Decision", ""]
    if d == "CONTINUE":
        L.append(f"CONTINUE: {k(v, 'share')} ours ({k(v, 'ours')} of {k(v, 'included')} included).")
    elif d == "DROP":
        L.append(f"DROP: {k(v, 'share')} ours ({k(v, 'ours')} of {k(v, 'included')} included).")
    else:
        L.append(f"NO DECISION: budget reached; {k(v, 'share')} ours ({k(v, 'ours')} of {k(v, 'included')}).")
    L += ["", f"Wilson 95% interval: {k(v, 'wilson_lo')} to {k(v, 'wilson_hi')}. The `ours` count is a lower bound "
          "for the frame (only `ours` rows confirmed by the independent double read are counted; disputed rows are "
          "`unclear`).", ""]
    L += ["## PREREG changes (listed before the result)", "",
          "- Change 1 (`prereg_changes.md`): class-rule clarifications C1 (principal), C2 (O1 limited to in-memory "
          "or caching layers), C3 (O4 versus a precondition the attacker creates), C4 (tie-break reminder), made "
          f"because the double read at the first 300th included row failed (kappa {k(v, 'r1_kappa')}, confirmed "
          f"{k(v, 'r1_confirmed')} of {k(v, 'r1_ours_first')} = {k(v, 'r1_confirmed_share')} < 80%). Every included "
          f"row was re-read ({k(v, 'reread_rows')} rows, {k(v, 'reread_changed')} labels changed, `reread/cp300b.jsonl`); "
          "reading resumed in the same order to a new 300th included row (checkpoint `cp300b`) and the double read "
          "was repeated with fresh subagents. Thresholds, lists, regexes, seeds, budget and decision line unchanged.",
          "- Interpretations recorded in PREREG.md before data: quote check after whitespace collapsing; gate rev 3 "
          "notes 5, 8, 9 applied.",
          "- First-reader label correction before any double read: `corrections.md`.", ""]
    L += ["## Route (§0)", "",
          "Session route: both probe calls answered 403 from the session proxy (`probe/session-*.json`). Workflow "
          "route (`.github/workflows/advisory-security-count.yml`, `wf_job.py`): both answered 200 "
          "(`probe/workflow-*.json`). Listing and fix material were read through the workflow route.",
          f"Requests logged: {k(v, 'requests')} ({k(v, 'requests_workflow')} through the workflow); "
          f"non-GET {k(v, 'requests_non_get')}; search endpoints {k(v, 'requests_search')}. "
          f"Budget clock started {v['first_request']} (first data request).", ""]
    L += ["## Funnel", "",
          f"Listed (reviewed, not withdrawn, published 2024-01-01..{v['list_date']}): total "
          f"{k(v, 'listed_total')} rows over 7 ecosystem listings → {k(v, 'frame')} distinct advisories.", "",
          "| ecosystem | listed | in frame |", "|---|---|---|"]
    for e in R.ECOSYSTEMS:
        L.append(f"| {e} | {k(v, 'listed_' + e)} | {k(v, 'frame_' + e)} |")
    L += ["", f"Candidates: {k(v, 'candidates')} — route (a) CWE list {k(v, 'route_a')}, (b) narrow regex only "
          f"{k(v, 'route_b')} (of which CWE-79 {k(v, 'route_b_cwe79')}, CWE-352 {k(v, 'route_b_cwe352')}), (c) no "
          f"CWE + broad regex {k(v, 'route_c')}. Memberships: (a) {k(v, 'member_a')}, (b) {k(v, 'member_b')}, "
          f"(c) {k(v, 'member_c')}.", "",
          f"Read in the seeded order: {k(v, 'read')} rows; the 300th included row is the last of the first "
          f"{k(v, 'cp_rows')} rows of the reading order (zero-based position one less). Checkpoint scope: {k(v, 'cp_read')} read → "
          f"{k(v, 'included')} included, {k(v, 'excluded')} excluded.", "",
          "| exclusion reason | rows |", "|---|---|"]
    for reason in sorted(R.EXCLUSION_REASONS):
        L.append(f"| {reason} | {k(v, 'exc_' + reason)} |")
    L += ["", f"Included → `ours` {k(v, 'ours')} (first reader {k(v, 'ours_first')}, disputed {k(v, 'disputed')}), "
          f"`read-the-code` {k(v, 'read_the_code')}, `unclear` {k(v, 'unclear')}. Included rows with fix material "
          f"(at least one commit, PR or compare read): {k(v, 'with_fix')} ({k(v, 'with_fix_share')}). Rows whose "
          f"quote failed the verbatim check: {k(v, 'quote_flags')}.", ""]
    L += ["## `ours` breakdown", "",
          "| subclass | rows |", "|---|---|"]
    for s in sorted(R.SUBCLASSES):
        L.append(f"| {s} | {k(v, 'sub_' + s)} |")
    L += ["", "By ecosystem: " + ", ".join(f"{e} {n}" for e, n in sorted(v["_ours_eco"].items())) + ". By severity: "
          + ", ".join(f"{s} {n}" for s, n in sorted(v["_ours_sev"].items())) + ".", "",
          f"Share without the (b)/(c)-route candidates: {k(v, 'share_a')} ({k(v, 'ours_a')} of {k(v, 'included_a')} "
          "included via the CWE list).", "",
          "Top 10 projects by included rows: " + ", ".join(f"{p} {n}" for p, n in v["_top_projects"]) + ".", ""]
    L += ["## Every `ours` advisory", "", "| ghsa_id | package | ecosystem | severity | subclass | quote | fix |",
          "|---|---|---|---|---|---|---|"]
    for r in v["_ours_rows"]:
        q = r["quote"].replace("|", "\\|").replace("\n", " ")
        L.append(f"| {r['ghsa_id']} | {r['packages']} | {r['eco']} | {r['severity']} | {r['subclass']} | {q} | "
                 f"{r['fix']} |")
    if v["_disputed_rows"]:
        L += ["", "Disputed by the double read (counted as `unclear`): " + ", ".join(v["_disputed_rows"]) + "."]
    L += ["", "## Calibration and double read", "",
          f"Gold set (6 unlabeled cases, `gold/input.jsonl`): first reader {k(v, 'gold_first_ok')} of "
          f"{k(v, 'gold_n')} (not blind); independent reader before any real row {k(v, 'gold_pre_ok')} of 6; "
          f"first double-read subagent of round 1 before its rows {k(v, 'r1_gold_ok')} of 6; first double-read "
          f"subagent of round 2 before its rows {k(v, 'gold_dr_ok')} of 6.", "",
          f"Round 1 (checkpoint `cp300`, before change 1): sample {k(v, 'r1_sample')}, kappa {k(v, 'r1_kappa')}, "
          f"confirmed {k(v, 'r1_confirmed')} of {k(v, 'r1_ours_first')} ({k(v, 'r1_confirmed_share')}): failed; no "
          "decision taken there (`doubleread/cp300/stats.json`).", ""]
    if v.get("_dr"):
        L += [f"Checkpoint `{CHECKPOINT}`: sample {k(v, 'dr_sample')} rows (every first-reader `ours` plus "
              f"`random.Random(6).sample` of 40 not-`ours` included rows), second labels {k(v, 'dr_read')}. Cohen's "
              f"kappa (ours vs not-ours) {k(v, 'dr_kappa')}; first-reader `ours` confirmed "
              f"{k(v, 'dr_confirmed')} of {k(v, 'dr_ours_first')} ({k(v, 'dr_confirmed_share')}); rows only the "
              f"second reader calls `ours` {k(v, 'dr_second_only')} (never promoted). Thresholds (kappa ≥ 0.6, "
              f"confirmed ≥ 80%) met: {k(v, 'dr_ok')}.", ""]
    L += ["## Frame bias", "",
          "The CWE list and regexes can miss `ours` advisories tagged with other CWEs and wording (bias toward DROP) "
          "and bring in authorization advisories that are almost always `read-the-code` (bias toward DROP); "
          "keyword-only candidates may lean toward `ours` (bias toward CONTINUE); the share without (b)/(c) is "
          "printed above.", ""]
    L += ["## Limits", "",
          "- GitHub reviewed advisories only (libraries and frameworks, not private applications).",
          "- Classification by reading; the second reader is the same model family, not a human.",
          "- The double read can only demote `ours` rows, never promote a not-`ours` one; excluded rows are never "
          "re-read.",
          "- Many vendor advisories (Magento, some VulDB-sourced entries) do not describe the mechanism and are "
          "`unclear`.",
          f"- rust, erlang, pub and swift, and advisories published after {v['list_date']}, are not covered.", ""]
    return "\n".join(L)


def main() -> None:
    out = render(compute())
    if "--stdout" in sys.argv:
        print(out)
    else:
        (HERE / "REPORT.md").write_text(out)
        print(out.splitlines()[0], "→ REPORT.md", datetime.now().isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
