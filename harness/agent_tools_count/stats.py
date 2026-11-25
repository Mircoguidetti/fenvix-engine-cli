"""Agent tools count numbers from rows and hand reads (shared by report.py and verify.py). Every value is a
formatted string keyed the way REPORT.md marks it (``<value><!--key-->``)."""
from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import rules as R

HERE = Path(__file__).resolve().parent
FAMILIES = ["copilot", "devin", "jules", "codex", "claude_code"]
SAMPLE_A = 30
SAMPLE_B = 60


def pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.1f}%"


def ratio(a: int, b: int) -> float:
    return a / b if b else float("nan")


# ---------------------------------------------------------------- samples (seeds fixed in PREREG)

def sample_a(rows: list[dict]) -> list[str]:
    nw = sorted(r["url"] for r in rows if r.get("result") == R.NOT_WASTED)
    return nw if len(nw) <= SAMPLE_A else random.Random(3).sample(nw, SAMPLE_A)


def issue_key(repo: str, n: int) -> str:
    return f"{repo}#{n}"


def b_issues(brows: list[dict]) -> list[dict]:
    return [dict(i, repo=r["repo"], key=issue_key(r["repo"], i["number"])) for r in brows
            for i in r.get("issues") or [] if i.get("class")]


def samples_b(brows: list[dict]) -> tuple[list[str], list[str]]:
    iss = b_issues(brows)
    comp = sorted(i["key"] for i in iss if i["class"] == R.COMPETING)
    rest = sorted(i["key"] for i in iss if i["class"] != R.COMPETING)
    comp_s = comp if len(comp) <= SAMPLE_B else random.Random(4).sample(comp, SAMPLE_B)
    rest_s = rest if len(rest) <= SAMPLE_B else random.Random(5).sample(rest, SAMPLE_B)
    return comp_s, rest_s


# ---------------------------------------------------------------- Count A

def final_a(rows: list[dict], hand: dict[str, dict]) -> list[dict]:
    """Rows with ``final`` = the hand-read result (every ``wasted`` row must have codes)."""
    out = []
    for r in rows:
        h = hand.get(r["url"])
        codes = [c for w in (h or {}).get("commits", []) for c in w["codes"]]
        out.append(dict(r, final=R.hand_result(r.get("result"), codes)))
    return out


def block_a(rows: list[dict], p: str) -> dict[str, str]:
    c = Counter(r["final"] for r in rows)
    w, nw, nl = c[R.WASTED], c[R.NOT_WASTED], c[R.NO_LATER]
    n = w + nw + nl
    lo, hi = R.wilson(w, n)
    files = sum(1 for r in rows if r["final"] in R.RATEABLE_A and r.get("files_evidence"))
    return {f"{p}a_read": str(len(rows)), f"{p}a_rateable": str(n), f"{p}a_wasted": str(w),
            f"{p}a_not_wasted": str(nw), f"{p}a_no_later": str(nl), f"{p}a_uncertain": str(c[R.UNCERTAIN]),
            f"{p}a_not_rateable": str(c[R.NOT_RATEABLE]), f"{p}a_rate": pct(ratio(w, n)), f"{p}a_lo": pct(lo),
            f"{p}a_hi": pct(hi), f"{p}a_files": str(files), f"{p}a_files_share": pct(ratio(files, n)),
            f"{p}a_auto_wasted": str(sum(1 for r in rows if r.get("result") == R.WASTED))}


def compute_a(rows: list[dict], hand: dict[str, dict], sample: list[dict]) -> dict[str, str]:
    rows = final_a(rows, hand)
    v = block_a(rows, "")
    for f in FAMILIES:
        v.update(block_a([r for r in rows if r["family"] == f], f"{f}_"))
    rate = [r for r in rows if r["final"] in R.RATEABLE_A]
    w = sum(1 for r in rate if r["final"] == R.WASTED)
    nw = sum(1 for r in rate if r["final"] == R.NOT_WASTED)
    files = sum(1 for r in rate if r.get("files_evidence"))
    misses = sum(1 for s in sample if s.get("miss"))
    v["a_sample_n"], v["a_misses"] = str(len(sample)), str(misses)
    v["a_miss_adj"] = pct(R.miss_adjusted(w, len(rate), misses, len(sample), nw)) if 1 <= misses <= 3 else "n/a"
    from fractions import Fraction
    fshare = Fraction(files, len(rate)) if rate else Fraction(0)
    v["_decision_a"] = R.decide_a(w, len(rate), fshare, misses if misses <= 3 else 0, len(sample), nw)
    # reasons and hand codes
    reasons = Counter()
    for r in rows:
        if r.get("result") == R.WASTED:
            rs = {x_ for x in r["xs"] for c in x["window"] for x_ in c["reasons"]}
            for x_ in rs:
                reasons[x_] += 1
    for k in ("i", "ii", "iii", "iv"):
        v[f"a_reason_{k}"] = str(reasons[k])
    codes = Counter(c for h in hand.values() for wc in h.get("commits", []) for c in wc["codes"])
    for k in sorted(R.W_CODES | R.R_CODES):
        v["a_code_" + k.lower().replace("-", "_")] = str(codes[k])
    v["a_hand_n"] = str(len(hand))
    v["a_hand_to_not"] = str(sum(1 for r in rows if r.get("result") == R.WASTED and r["final"] == R.NOT_WASTED))
    # §1.10 information
    marks = Counter()
    for r in rows:
        if r.get("result") == R.WASTED:
            for x in r["xs"]:
                hit = {f for c in x["window"] if "i" in c["reasons"] for f in c_files(c)} & set(x["evidence"]["files"])
                for f in hit:
                    marks[x["in_base"].get(f, "base-unknown")] += 1
    for k in ("yes", "no", "base-unknown"):
        v["a_inbase_" + k.replace("-", "_")] = str(marks[k])
    anyx = [r for r in rows if r.get("xs")]
    v["a_any_x"] = str(len(anyx))
    klt = [r for r in rate if any(x["k"] < r["n_commits"] for x in r["xs"])]
    kw = sum(1 for r in klt if r["final"] == R.WASTED)
    v["a_k_lt_last"], v["a_k_lt_last_rate"] = str(len(klt)), pct(ratio(kw, len(klt)))
    v["a_single_commit"] = str(sum(1 for r in rows if r.get("n_commits") == 1))
    v["a_single_commit_rateable"] = str(sum(1 for r in rate if r.get("n_commits") == 1))
    v["a_force_prs"] = str(sum(1 for r in rows if (r.get("force_pushes") or 0) > 0))
    v["a_force_events"] = str(sum(r.get("force_pushes") or 0 for r in rows))
    kinds = Counter(x["kind"] for r in rate for x in r["xs"])
    for k in ("actions", "check", "status"):
        v[f"a_x_{k}"] = str(kinds[k])
    act = [r for r in rate if all(x["kind"] == "actions" for x in r["xs"])]
    v["a_actions_only"] = str(len(act))
    v["a_actions_only_rate"] = pct(ratio(sum(1 for r in act if r["final"] == R.WASTED), len(act)))
    cop = [c for r in rows if r["family"] == "copilot" for c in r.get("commits") or []]
    v["a_copilot_commits"] = str(len(cop))
    v["a_copilot_no_checks"] = str(sum(1 for c in cop if not (c.get("n_runs") or c.get("n_statuses"))))
    v["a_copilot_action_required"] = str(sum(1 for c in cop if c.get("n_runs") and
                                             c.get("n_action_required") == c.get("n_runs")))
    v["a_pr_event_only"] = str(sum(1 for r in rate if r["xs"] and all(
        x["kind"] == "actions" and x.get("base_event") == "pull_request" for x in r["xs"])))
    c2 = [r for r in rows if r.get("c2_verdict") == "ALREADY_RED"]
    c2c = Counter(r["final"] for r in c2)
    v["a_c2_n"] = str(len(c2))
    for k, name in ((R.WASTED, "wasted"), (R.NOT_WASTED, "not_wasted"), (R.NO_LATER, "no_later"),
                    (R.UNCERTAIN, "uncertain"), (R.NOT_RATEABLE, "not_rateable")):
        v["a_c2_" + name] = str(c2c[k])
    v["a_human_after"] = str(sum(r.get("human_after") or 0 for r in rate))
    v["a_human_after_prs"] = str(sum(1 for r in rate if (r.get("human_after") or 0) > 0))
    return v


def c_files(c: dict) -> list[str]:
    return [f["filename"] for f in c.get("files") or []]


# ---------------------------------------------------------------- Count B

def block_b(iss: list[dict], p: str) -> dict[str, str]:
    c = Counter(i["class"] for i in iss)
    n = len(iss)
    comp = c[R.COMPETING]
    lo, hi = R.wilson(comp, n)
    return {f"{p}b_addressed": str(n), f"{p}b_competing": str(comp), f"{p}b_sequential": str(c[R.SEQUENTIAL]),
            f"{p}b_single": str(c[R.SINGLE]), f"{p}b_rate": pct(ratio(comp, n)), f"{p}b_lo": pct(lo),
            f"{p}b_hi": pct(hi)}


def compute_b(brows: list[dict], hand: list[dict]) -> dict[str, str]:
    st = Counter(r["status"] for r in brows)
    v = {"b_repos": str(len(brows)), "b_repos_read": str(st["read"] + st["partial-budget"]),
         "b_repos_skipped": str(st["skipped-no-agent"]), "b_repos_unreadable": str(st["unreadable"]),
         "b_repos_partial": str(st["partial-budget"]),
         "b_repos_truncated": str(sum(1 for r in brows if r.get("truncated"))),
         "b_issues": str(sum(r.get("n_issues_read") or 0 for r in brows)),
         "b_timeline_errors": str(sum(r.get("n_timeline_errors") or 0 for r in brows))}
    iss = b_issues(brows)
    v.update(block_b(iss, ""))
    for f in FAMILIES:
        v.update(block_b([i for i in iss if i["agent_prs"][0]["family"] == f], f"{f}_"))
    labels = Counter(lb for i in iss if i["class"] == R.COMPETING for lb in i.get("labels") or [])
    for k in ("first-opened", "first-green", "only-green", "reviewed", "other", "none-merged"):
        v["b_label_" + k.replace("-", "_")] = str(labels[k])
    v["_decision_b"] = R.decide_b(int(v["b_competing"]), int(v["b_addressed"]))
    # hand read (information): an issue of the competing sample keeps its class with 2 or more same-issue links,
    # one of the agent-addressed sample with 1 or more; the not-attempt share is the share of sampled issues that
    # do not keep their class.
    for name, need, sample in (("comp", 2, [h for h in hand if h["sample"] == "competing"]),
                               ("rest", 1, [h for h in hand if h["sample"] == "addressed"])):
        links = [lk for h in sample for lk in h["links"]]
        lost = sum(1 for h in sample if sum(1 for lk in h["links"] if lk["mark"] == "same-issue") < need)
        v[f"b_hand_{name}_issues"] = str(len(sample))
        v[f"b_hand_{name}_links"] = str(len(links))
        v[f"b_hand_{name}_not_attempt_links"] = str(sum(1 for lk in links if lk["mark"] == "not-attempt"))
        v[f"b_hand_{name}_lost"] = str(lost)
        v[f"b_hand_{name}_share"] = pct(ratio(lost, len(sample)))
    sc = ratio(int(v["b_hand_comp_lost"]), int(v["b_hand_comp_issues"]))
    sr = ratio(int(v["b_hand_rest_lost"]), int(v["b_hand_rest_issues"]))
    n = int(v["b_addressed"])
    sc = 0.0 if sc != sc and int(v["b_competing"]) == 0 else sc
    corr = (int(v["b_competing"]) * (1 - sc)) / (n * (1 - sr)) if n and sc == sc and sr == sr and sr < 1 \
        else float("nan")
    v["b_corrected"] = pct(corr)
    return v
