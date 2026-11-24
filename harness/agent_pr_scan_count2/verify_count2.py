#!/usr/bin/env python3
"""Re-derive Count 2 from committed files; exit 1 on any mismatch.

Checks: (1) draw.jsonl.gz equals the seeded draw re-built from the pools and repository metadata; (2) the PRs read,
in order, and the repository-cap exclusions equal a simulation of the job's selection (quota, caps) from the
re-derived verdicts; (3) every PR's verdict, per-check verdicts and secondary flag re-derive from its committed raw
JSON (replay through pipeline.run_pr); (4) the hand-check set is random.Random(2).sample(sorted(urls with a failed
check), 20), every row has a hand verdict and four confirmed fields, and the hand verdict equals the re-derived
verdict; (5) every <n><!--key--> in REPORT.md equals the re-computed value; (6) REPORT.md carries the pre-registered
decision sentence for the re-computed counts and no other decision sentence.
"""
from __future__ import annotations

import gzip
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import draw as D  # noqa: E402
import job as J  # noqa: E402
import pipeline as P  # noqa: E402
import rules as R  # noqa: E402
import stats  # noqa: E402

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print("MISMATCH", msg)


def check_draw(draw: list[dict]) -> None:
    seq = D.sequence()
    meta = D.load_meta()
    owners = D.excluded_owners()
    for d in draw:
        r = seq[d["idx"]]
        m = meta.get(r["repo"].lower())
        why = D.static_exclusion(dict(r), m, owners) if (m or r["repo"].split("/")[0].lower() in owners) else "?"
        if (r["url"], r["family"], why) != (d["url"], d["family"], d["excluded"]):
            err(f"draw idx {d['idx']}: {d['url']} {d['excluded']!r} != re-derived {r['url']} {why!r}")
            return
    if [d["idx"] for d in draw] != list(range(len(draw))):
        err("draw positions are not 0..n-1")


def replay(raws: list[dict], rows: list[dict]) -> dict[str, dict]:
    by_url = {r["url"]: r for r in rows}
    out = {}
    for raw in raws:
        try:
            res = P.run_pr(P.ReplaySource(raw["responses"]), {"repo": raw["repo"], "number": raw["number"]},
                           probe=raw["probe"])
        except P.Missing as e:
            err(f"{raw['url']}: replay needs a response not in the raw JSON: {e}")
            continue
        out[raw["url"]] = res
        row = by_url.get(raw["url"])
        if row is None:
            err(f"{raw['url']}: raw JSON without a row")
            continue
        if row["verdict"] != res["verdict"]:
            err(f"{raw['url']}: row verdict {row['verdict']} != re-derived {res['verdict']}")
        if row.get("secondary_already_red") != res.get("secondary_already_red"):
            err(f"{raw['url']}: secondary flag differs")
        rc = [(f.get("identity"), f["verdict"]) for f in row.get("failed_checks", [])]
        xc = [(f.get("identity"), f["verdict"]) for f in res.get("failed_checks", [])]
        if rc != xc:
            err(f"{raw['url']}: per-check verdicts differ: {rc} != {xc}")
    for r in rows:
        if r["url"] not in out and not any(r["url"] == x["url"] for x in raws):
            err(f"{r['url']}: row without raw JSON")
    return out


def check_selection(draw, rows, derived, caps, checkpoint, complete) -> None:
    state = J.new_state()
    read_seq, cap_seq = [], []
    target = len(rows)
    while len(read_seq) < target:
        act, d = J.next_action(state, draw, complete)
        if act == "stop":
            break
        if act == "cap":
            cap_seq.append(d["url"])
            continue
        res = derived.get(d["url"])
        if res is None:
            err(f"selection: draw idx {d['idx']} {d['url']} should be read next but has no committed result")
            return
        read_seq.append(d["url"])
        J.record_read(state, d, res["verdict"])
    if read_seq != [r["url"] for r in rows]:
        first = next((i for i, (a, b) in enumerate(zip(read_seq, [r["url"] for r in rows])) if a != b), None)
        err(f"selection: PRs read differ from the seeded draw at position {first}")
    caps_committed = [c["url"] for c in caps]
    if cap_seq != caps_committed[:len(cap_seq)] or len(caps_committed) - len(cap_seq) > 0 and \
            not _caps_after(state, draw, complete, caps_committed[len(cap_seq):]):
        err("selection: repository-cap exclusions differ from the simulation")
    for k in ("read", "rateable"):
        if checkpoint.get(k) != state[k]:
            err(f"checkpoint {k} {checkpoint.get(k)} != simulated {state[k]}")


def _caps_after(state, draw, complete, rest) -> bool:
    """Cap exclusions recorded after the last read PR (before the chunk stopped)."""
    st = json.loads(json.dumps(state))
    got = []
    while len(got) < len(rest):
        act, d = J.next_action(st, draw, complete)
        if act != "cap":
            return False
        got.append(d["url"])
    return got == rest


def check_handcheck(rows, derived) -> None:
    path = HERE / "handcheck.jsonl"
    with_failed = sorted(r["url"] for r in rows if derived.get(r["url"], {}).get("verdict") in R.PR_ORDER)
    if len(with_failed) < 20:
        err(f"hand check: only {len(with_failed)} PRs with a failed check")
        return
    want = random.Random(2).sample(with_failed, 20)
    hc = J.read_jsonl(path)
    if [h["url"] for h in hc] != want:
        err("hand check: the set is not random.Random(2).sample(sorted(urls_with_failed_check), 20)")
    for h in hc:
        if not h.get("hand_verdict"):
            err(f"hand check {h['url']}: no hand verdict")
            continue
        for k in ("confirmed_failed_check_identity", "confirmed_base_run", "confirmed_base_conclusion",
                  "confirmed_verdict"):
            if h.get(k) not in (True, False) or not h.get(k + "_note"):
                err(f"hand check {h['url']}: {k} missing")
        v = derived.get(h["url"], {}).get("verdict")
        if h["hand_verdict"] != v:
            err(f"hand check {h['url']}: hand verdict {h['hand_verdict']} != re-derived {v}")


def check_report(rows, derived) -> None:
    rep = HERE / "REPORT.md"
    if not rep.exists():
        err("REPORT.md missing")
        return
    txt = rep.read_text()
    fixed = [dict(r, **{k: derived[r["url"]][k] for k in ("verdict",) if r["url"] in derived}) for r in rows]
    for r in fixed:
        if r["url"] in derived:
            r["secondary_already_red"] = derived[r["url"]].get("secondary_already_red")
    vals = stats.compute(fixed)
    vals.update(extra_values(rows))
    keys = re.findall(r"(\d[\d.]*%?|n/a)<!--([a-z0-9_]+)-->", txt)
    if not keys:
        err("REPORT.md has no marked numbers")
    for v, k in keys:
        if k not in vals:
            err(f"REPORT.md key {k} unknown")
        elif v != vals[k]:
            err(f"REPORT.md {k}: {v} != re-computed {vals[k]}")
    sentence = vals["_sentence"]
    if sentence not in txt:
        err(f"REPORT.md lacks the decision sentence {sentence!r}")
    for other in (R.SENT_FORWARD, R.SENT_PARKED, R.SENT_INVALID):
        if other != sentence and other in txt:
            err(f"REPORT.md contains a decision sentence the rule does not give: {other!r}")


def extra_values(rows) -> dict[str, str]:
    hc = J.read_jsonl(HERE / "handcheck.jsonl")
    chunks = J.read_jsonl(HERE / "results" / "chunks.jsonl")
    caps = J.read_jsonl(HERE / "results" / "excluded_cap.jsonl")
    dm = json.loads((HERE / "draw_meta.json").read_text())
    probe = [r for r in rows if r.get("probe")]
    return {"hand_n": str(len(hc)), "hand_agree": str(sum(1 for h in hc if h.get("auto_verdict_first") ==
                                                        h.get("hand_verdict"))),
            "hand_disagree": str(sum(1 for h in hc if h.get("auto_verdict_first") != h.get("hand_verdict"))),
            "chunks": str(len(chunks)), "requests": str(sum(c["requests"] for c in chunks)),
            "cap_excluded": str(len(caps)), "draw_prepared": str(dm["prepared"]),
            "draw_eligible": str(dm["eligible"]), "probe_n": str(len(probe)),
            "probe_base_ok": str(sum(1 for r in probe if (r.get("probe_base_runs") or {}).get("status") == 200))}


def main() -> int:
    draw = J.read_jsonl(HERE / "draw.jsonl.gz")
    complete = json.loads((HERE / "draw_meta.json").read_text())["complete"]
    res = HERE / "results"
    rows = J.read_jsonl(res / "rows.jsonl")
    raws = [x for p in sorted((res / "raw").glob("*.jsonl.gz")) for x in J.read_jsonl(p)]
    caps = J.read_jsonl(res / "excluded_cap.jsonl")
    checkpoint = json.loads((res / "checkpoint.json").read_text())
    check_draw(draw)
    derived = replay(raws, rows)
    check_selection(draw, rows, derived, caps, checkpoint, complete)
    check_handcheck(rows, derived)
    check_report(rows, derived)
    print(f"verify_count2: {len(rows)} PRs, {len(errors)} mismatches")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
