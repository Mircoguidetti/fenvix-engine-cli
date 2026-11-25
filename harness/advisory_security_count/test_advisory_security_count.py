"""Tests for the pre-registered rules (PREREG.md). Each test states protects= / fails_when= / no_claim=."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ghapi  # noqa: E402
import rules as R  # noqa: E402


def adv(gid="GHSA-aaaa-bbbb-cccc", cwes=None, summary="", description="", eco="npm", withdrawn=None):
    return {"ghsa_id": gid, "cwes": cwes, "summary": summary, "description": description, "withdrawn_at": withdrawn,
            "vulnerabilities": [{"package": {"ecosystem": eco, "name": "pkg"}}]}


def cwe(*ids):
    return [{"cwe_id": i, "name": ""} for i in ids]


# ---------------------------------------------------------------- frame

def test_frame_cwe_routes():
    """protects=§1.2 (a): an advisory with a listed CWE is a candidate and one with only CWE-79 is not;
    fails_when=CWE-362 is not a candidate or CWE-79 alone is; no_claim=the CWE list catches every relevant advisory."""
    assert R.route(adv(cwes=cwe("CWE-362"))) == "a"
    assert R.route(adv(cwes=cwe("CWE-79"), summary="Stored XSS in profile page")) is None


def test_frame_narrow_regex_route_whatever_cwe():
    """protects=§1.2 (b): narrow-regex wording makes a candidate whatever its CWE; fails_when=CWE-20 with "race
    condition in token refresh" is not a candidate; no_claim=keyword candidates are relevant."""
    assert R.route(adv(cwes=cwe("CWE-20"), summary="race condition in token refresh")) == "b"


def test_frame_no_cwe_broad_route():
    """protects=§1.2 (c): no CWE plus broad-regex wording is a candidate, no CWE plus unrelated wording is not, and
    cwes null / NVD-CWE-noinfo count as no CWE; fails_when=any of these flips; no_claim=(c) is complete."""
    a = adv(cwes=None, summary="race condition allows redeeming a coupon twice")
    assert R.route(a) in ("b", "c") and R.memberships(a)["c"]
    assert R.route(adv(cwes=None, summary="XSS in comment field")) is None
    assert R.route(adv(cwes=[], summary="cached response served")) == "c"
    assert R.route(adv(cwes=cwe("NVD-CWE-noinfo"), summary="token reused")) == "c"
    assert R.route(adv(cwes=cwe("CWE-20"), summary="token reused")) is None  # broad only applies to no-CWE rows


def test_frame_dedup_and_withdrawn():
    """protects=§1.1: one row per ghsa_id with all its ecosystems, withdrawn rows dropped; fails_when=the same
    ghsa_id in two ecosystem listings gives two rows, or a withdrawn row stays; no_claim=listing completeness."""
    a1 = adv(gid="GHSA-1", eco="maven")
    rows = R.merge_listing({"npm": [a1, adv(gid="GHSA-2", withdrawn="2025-01-01T00:00:00Z")], "maven": [a1]})
    assert [r["ghsa_id"] for r in rows] == ["GHSA-1"]
    assert rows[0]["ecosystems"] == ["maven", "npm"]


@pytest.mark.parametrize("text", ["race conditions", "race-condition", "data race", "simultaneously",
                                  "double-spending", "replays", "time of check", "ThreadLocal", "AsyncLocalStorage",
                                  "multi-tenant", "another tenant", "cache key", "in parallel",
                                  "at the same time", "nonatomic", "other organizations", "TOCTTOU"])
def test_narrow_regex_matches(text):
    """protects=§1.2 narrow regex wording; fails_when=a pre-registered phrase does not match; no_claim=precision."""
    assert R.narrow_match(f"An issue: {text} here.")


@pytest.mark.parametrize("text", ["cachet", "doublet", "Cache-Control header"])
def test_narrow_regex_non_matches(text):
    """protects=narrow regex precision on near-misses; fails_when=cachet, doublet or Cache-Control match;
    no_claim=no other false positives (e.g. "other usernames" is accepted noise)."""
    assert not R.narrow_match(text)


@pytest.mark.parametrize("text", ["background jobs", "global variables", "singletons", "reusing", "re-use",
                                  "cached", "twice"])
def test_broad_regex_matches(text):
    """protects=§1.2 broad regex; fails_when=a listed phrase does not match; no_claim=precision."""
    assert R.broad_match(text)


def test_order_stable_and_unique():
    """protects=§1.3 order: sorted then Random(5) shuffle, same on two runs, no repeats; fails_when=two runs differ
    or an id repeats; no_claim=the order is representative beyond random sampling."""
    ids = [f"GHSA-{i:04d}" for i in range(500)] + ["GHSA-0001"]
    o1, o2 = R.reading_order(ids), R.reading_order(list(reversed(ids)))
    assert o1 == o2 and len(o1) == len(set(o1)) == 500


# ---------------------------------------------------------------- label rules

def lab(inclusion="included", cls="ours", sub="O3-concurrency", quote="parallel"):
    return {"ghsa_id": "G", "inclusion": inclusion, "reason": None if inclusion == "included" else "not-web",
            "class": cls if inclusion == "included" else None, "subclass": sub, "quote": quote, "reader": "r1",
            "batch": 0}


def test_missing_quote_is_unclear():
    """protects=§2.3 a row without a quote is unclear; fails_when=an ours row without quote stays ours;
    no_claim=quotes that exist support their class."""
    e = R.effective_label(lab(quote=None), "requests in parallel")
    assert e["class"] == "unclear" and e["subclass"] is None and e["quote_flag"] == "missing"


def test_non_verbatim_quote_is_unclear_and_flagged():
    """protects=verbatim quote rule (whitespace-collapsed); fails_when=a quote not in the material keeps its class or
    a whitespace-only difference demotes; no_claim=semantic support of the quote."""
    e = R.effective_label(lab(quote="sent concurrently"), "requests in parallel")
    assert e["class"] == "unclear" and e["quote_flag"] == "not-verbatim"
    ok = R.effective_label(lab(quote="requests  in\nparallel"), "two requests in parallel win")
    assert ok["class"] == "ours" and ok["quote_flag"] is None


def test_disputed_ours_becomes_unclear():
    """protects=§2.6 a disputed ours row becomes unclear; excluded by the second reader is a dispute; a different
    subclass is not; fails_when=any of these differs; no_claim=the second reader is right."""
    first = {"A": dict(lab(), ghsa_id="A"), "B": dict(lab(), ghsa_id="B"), "C": dict(lab(), ghsa_id="C")}
    second = {"A": dict(lab(cls="read-the-code", sub=None)), "B": dict(lab(inclusion="excluded")),
              "C": dict(lab(sub="O1-shared-state"))}
    out, disputed = R.apply_disputes(first, second)
    assert disputed == ["A", "B"]
    assert out["A"]["class"] == "unclear" and out["B"]["class"] == "unclear" and out["C"]["class"] == "ours"


def test_validate_label_closed_lists():
    """protects=closed reason / class / subclass lists; fails_when=an unknown reason or an ours row without subclass
    validates; no_claim=labels are correct."""
    assert R.validate_label(lab()) == []
    assert R.validate_label(dict(lab(inclusion="excluded"), reason="own-data-disclosure"))
    assert R.validate_label(lab(sub=None))


# ---------------------------------------------------------------- stop rule

def test_stop_rule_cases():
    """protects=§3 decision rule with integers; fails_when=any pre-registered case gives another decision;
    no_claim=the thresholds are right (founder decision)."""
    assert R.decide(45, 300, at_checkpoint=True, all_read=False) == "CONTINUE"
    assert R.decide(44, 300, at_checkpoint=True, all_read=False) == "DROP"
    assert R.decide(33, 210, at_checkpoint=False, all_read=False) is None
    first = {f"G{i:03d}": {"inclusion": "included", "class": "ours" if i < 46 else "read-the-code"} for i in range(300)}
    second = {f"G{i:03d}": {"inclusion": "included", "class": "ours" if i >= 2 else "read-the-code"} for i in range(46)}
    out, disputed = R.apply_disputes(first, second)
    ours = sum(R.is_ours(v) for v in out.values())
    assert len(disputed) == 2 and ours == 44 and R.decide(ours, 300, True, False) == "DROP"
    assert R.decide(29, 180, at_checkpoint=False, all_read=True) == "DROP"
    assert R.decide(28, 150, at_checkpoint=False, all_read=True) == "DROP"
    assert R.decide(20, 100, at_checkpoint=False, all_read=False, budget_over=True) == "NO DECISION"


def test_checkpoint_prefix_exact_300th():
    """protects=§3 checkpoint at exactly the 300th included row, even mid-batch; fails_when=the prefix stops before
    or after it; no_claim=the order is right."""
    order = [f"G{i}" for i in range(400)]
    labels = {g: {"inclusion": "included" if i % 2 == 0 else "excluded"} for i, g in enumerate(order)}
    assert R.checkpoint_prefix(order, labels) is None  # only 200 included
    order = [f"G{i}" for i in range(700)]
    labels = {g: {"inclusion": "included" if i % 2 == 0 else "excluded"} for i, g in enumerate(order)}
    assert R.checkpoint_prefix(order, labels) == 599


def test_wilson():
    """protects=Wilson 95% interval (z=1.96); fails_when=46/300 or 40/200 differ from the hand values at 3 decimals;
    no_claim=Wilson is the best interval."""
    lo, hi = R.wilson(46, 300)
    assert (round(lo, 3), round(hi, 3)) == (0.117, 0.198)
    lo, hi = R.wilson(40, 200)
    assert (round(lo, 3), round(hi, 3)) == (0.150, 0.261)


def test_kappa_hand_value_and_threshold():
    """protects=Cohen's kappa on ours vs not-ours and the re-read threshold; fails_when=a 2x2 fixture differs from
    the hand value or kappa 0.55 passes; no_claim=kappa is a sufficient agreement measure."""
    # 2x2: both ours 20, first only 5, second only 5, neither 30 -> po=50/60, pe=(25/60)^2+(35/60)^2
    pairs = [(True, True)] * 20 + [(True, False)] * 5 + [(False, True)] * 5 + [(False, False)] * 30
    po, pe = 50 / 60, (25 / 60) ** 2 + (35 / 60) ** 2
    assert R.cohen_kappa(pairs) == pytest.approx((po - pe) / (1 - pe))
    assert R.cohen_kappa(pairs) == pytest.approx(0.6571428, abs=1e-6)
    assert not R.double_read_ok(0.55, 0.9)
    assert R.double_read_ok(0.6, 0.8)


def test_double_read_sample():
    """protects=§2.6 sample: all ours plus Random(6).sample(sorted not-ours, 40), all if fewer; fails_when=an ours
    row is missing, the sample differs from the seeded one or excluded rows are drawn; no_claim=40 is enough."""
    labels = {f"G{i:03d}": {"inclusion": "included", "class": "ours" if i < 5 else "read-the-code"} for i in range(100)}
    labels["X"] = {"inclusion": "excluded"}
    ids = sorted(labels)
    s = R.double_read_sample(labels, ids)
    notours = sorted(g for g in ids if g != "X" and not R.is_ours(labels[g]))
    import random
    assert s == [f"G{i:03d}" for i in range(5)] + sorted(random.Random(6).sample(notours, 40))
    small = {k: v for k, v in labels.items() if k < "G020"}
    assert len(R.double_read_sample(small, sorted(small))) == 20


# ---------------------------------------------------------------- material and access

def test_fix_refs_same_repo_first_three():
    """protects=§2.1: commit / pull / compare references in the source repository only, first 3; fails_when=another
    repository's commit is kept or more than 3 are returned; no_claim=the fix is among them."""
    a = {"source_code_location": "https://github.com/Acme/App",
         "references": ["https://github.com/other/x/commit/abcdef1", "https://github.com/acme/app/commit/abcdef12",
                        "https://github.com/acme/app/pull/12/files", "https://github.com/acme/app/compare/v1.0...v1.1",
                        "https://github.com/acme/app/commit/1234567"]}
    refs = R.fix_refs(a)
    assert [r["kind"] for r in refs] == ["commit", "pull", "compare"]
    assert refs[2]["range"] == "v1.0...v1.1"


def test_cap_files_skips_lock_and_vendor():
    """protects=§2.1 caps: lockfiles and vendored paths skipped, 20 files, 400 lines; fails_when=any cap is broken;
    no_claim=the kept files contain the fix."""
    files = [{"filename": "package-lock.json", "patch": "x"}, {"filename": "vendor/a.go", "patch": "x"},
             {"filename": "web/app.min.js", "patch": "x"}, {"filename": "src/node_modules/y.js", "patch": "x"}]
    files += [{"filename": f"src/f{i}.py", "patch": "\n".join(["+l"] * 500)} for i in range(25)]
    out = R.cap_files(files)
    assert len(out) == 20 and out[0]["filename"] == "src/f0.py"
    assert out[0]["patch"].count("\n") == 399 and out[0]["patch_truncated"]


def test_search_endpoint_refused():
    """protects=AC5 no search endpoint is called; fails_when=ghapi.get accepts a /search/ path; no_claim=all other
    paths are allowed by policy."""
    with pytest.raises(ValueError):
        ghapi.get("/search/code", {"q": "x"})


def test_link_header_next():
    """protects=cursor pagination through the Link header; fails_when=the next URL is not extracted;
    no_claim=GitHub always sends a Link header."""
    h = '<https://api.github.com/advisories?after=Y3Vy&per_page=100>; rel="next", <https://x>; rel="prev"'
    assert ghapi.next_link(h) == "https://api.github.com/advisories?after=Y3Vy&per_page=100"
    assert ghapi.next_link(None) is None


# ---------------------------------------------------------------- report helpers

def test_gold_score_accepts_either_g2_reason(tmp_path):
    """protects=§2.4 gold scoring: G2 accepts not-web or one-principal, a wrong subclass is a miss;
    fails_when=a correct label set scores below 6 or a wrong G5 subclass scores 6; no_claim=the gold set is hard."""
    import report as REP
    rows = [("G1", "excluded", "not-web", None, None), ("G2", "excluded", "one-principal", None, None),
            ("G3", "included", None, "read-the-code", None), ("G4", "included", None, "ours", "O5-time"),
            ("G5", "included", None, "ours", "O3-concurrency"), ("G6", "included", None, "read-the-code", None)]
    p = tmp_path / "g.jsonl"
    p.write_text("\n".join(__import__("json").dumps(dict(zip(("ghsa_id", "inclusion", "reason", "class", "subclass"),
                                                             r))) for r in rows))
    assert REP.gold_score(p)[:2] == (6, 6)
    rows[4] = ("G5", "included", None, "ours", "O1-shared-state")
    p.write_text("\n".join(__import__("json").dumps(dict(zip(("ghsa_id", "inclusion", "reason", "class", "subclass"),
                                                             r))) for r in rows))
    assert REP.gold_score(p) == (5, 6, ["G5"])


def test_pct_and_wilson_format():
    """protects=report formatting of the share: one decimal, n/a for zero denominators; fails_when=19 of 300
    prints anything but 6.3%; no_claim=rounding direction matters for the decision (decisions use integers)."""
    import report as REP
    assert REP.pct(19, 300) == "6.3%" and REP.pct(0, 0) == "n/a"
