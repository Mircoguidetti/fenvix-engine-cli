"""Fingerprint and outcome comparison of detpy traces: serial noise, parallel noise, placement (design 1.4.4, P0).

usage: python -m harness.parallel_proof.fpcompare --serial A.jsonl B.jsonl --parallel PA.jsonl PB.jsonl [--json OUT]

Traces are merged traces (``--det -n N`` on this engine) or serial traces; a side may be given as a glob of per-worker
traces (``trace.gw*.jsonl``). Classes, per test present in all four traces:
* serial noise: the two serial runs differ;
* parallel noise: the two parallel runs differ;
* placement: the two serial runs agree and a parallel run differs from them;
* outcome differences between serial and parallel (a placement test whose outcome changed is a "new failure caused
  by the split" when serial passes and parallel fails).
The first differing event's source is reported for every differing test (from the stored events)."""

from __future__ import annotations

import argparse
import collections
import glob
import json


def load(pattern: str) -> tuple[dict, dict]:
    """(records by node id, header meta of the first file)."""
    recs, meta = {}, {}
    for f in sorted(glob.glob(pattern)) or [pattern]:
        with open(f) as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    break  # a cut last line (killed process)
                t = o.get("type")
                if t == "header" and not meta:
                    meta = o.get("meta") or {}
                elif t == "test":
                    recs[o["nodeid"]] = o
    return recs, meta


def first_source(a: dict, b: dict) -> str:
    for x, y in zip(a.get("events", []), b.get("events", [])):
        if x != y:
            return x.get("s", "?")
    if a.get("n_events") != b.get("n_events"):
        return "count"
    if a.get("outcome") != b.get("outcome"):
        return "outcome-only"
    return "beyond-stored"


def compare(sa: dict, sb: dict, pa: dict, pb: dict) -> dict:
    both = sorted(set(sa) & set(sb) & set(pa) & set(pb))
    fp = lambda r, n: r[n]["fingerprint"]  # noqa: E731
    serial_noise = [n for n in both if fp(sa, n) != fp(sb, n)]
    par_noise = [n for n in both if fp(pa, n) != fp(pb, n)]
    stable = [n for n in both if fp(sa, n) == fp(sb, n)]
    placement = [n for n in stable if fp(pa, n) != fp(sa, n) or fp(pb, n) != fp(sa, n)]
    placement_both = [n for n in placement if fp(pa, n) != fp(sa, n) and fp(pb, n) != fp(sa, n)]
    outcome_diff = [n for n in both if {sa[n]["outcome"], sb[n]["outcome"]} != {pa[n]["outcome"], pb[n]["outcome"]}]
    new_failures = [n for n in outcome_diff if "failed" in (pa[n]["outcome"], pb[n]["outcome"])
                    and sa[n]["outcome"] == sb[n]["outcome"] != "failed"]
    hidden_failures = [n for n in outcome_diff if "failed" in (sa[n]["outcome"], sb[n]["outcome"])
                       and pa[n]["outcome"] != "failed"]
    src = collections.Counter(first_source(sa[n], pa[n] if fp(pa, n) != fp(sa, n) else pb[n]) for n in placement)
    noise_src = collections.Counter(first_source(sa[n], sb[n]) for n in serial_noise)
    return {
        "tests_in_all": len(both),
        "only_serial": len((set(sa) | set(sb)) - (set(pa) | set(pb))),
        "only_parallel": len((set(pa) | set(pb)) - (set(sa) | set(sb))),
        "serial_noise": len(serial_noise), "serial_noise_first_source": dict(noise_src),
        "parallel_noise": len(par_noise),
        "placement": len(placement), "placement_in_both_parallel_runs": len(placement_both),
        "placement_first_source": dict(src),
        "outcome_differences": len(outcome_diff), "new_failures_caused_by_split": new_failures,
        "hidden_failures": hidden_failures,
        "placement_examples": placement[:20], "serial_noise_examples": serial_noise[:20],
    }


def plans_equal(ma: dict, mb: dict) -> bool | None:
    a, b = (ma.get("plan") or {}).get("lists"), (mb.get("plan") or {}).get("lists")
    if a is None or b is None:
        return None
    return a == b


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", nargs=2, required=True)
    ap.add_argument("--parallel", nargs=2, required=True)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    (sa, _), (sb, _) = load(a.serial[0]), load(a.serial[1])
    (pa, ma), (pb, mb) = load(a.parallel[0]), load(a.parallel[1])
    out = compare(sa, sb, pa, pb)
    out["parallel_plans_identical"] = plans_equal(ma, mb)
    out["parallel_workers_identical"] = all(pa[n].get("worker") == pb[n].get("worker") for n in set(pa) & set(pb))
    text = json.dumps(out, indent=1, sort_keys=True)
    if a.json:
        with open(a.json, "w") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
