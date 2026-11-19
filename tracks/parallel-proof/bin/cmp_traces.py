"""Compare per-test fingerprints and outcomes between two sets of detpy traces.

usage: cmp_traces.py A_GLOB B_GLOB [--show N]
Each side may be several files (one per xdist worker); records are keyed by nodeid.
Prints: tests on both sides, same fingerprint, different fingerprint (outcome same / outcome differs),
and for the differing ones the first differing event's source (from the stored events)."""
import collections, glob, json, sys

def load(pattern):
    recs, meta = {}, []
    for f in sorted(glob.glob(pattern)):
        if f.endswith(".ran.json"):
            continue
        with open(f) as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t = o.get("type")
                if t == "header":
                    meta.append((f, len(o.get("order", []))))
                elif t == "test":
                    recs[o["nodeid"]] = o
    return recs, meta

def first_diff(a, b):
    ea, eb = a.get("events", []), b.get("events", [])
    for i, (x, y) in enumerate(zip(ea, eb)):
        if x != y:
            return x.get("s", "?") + ":" + str(x.get("o", ""))[:40], i
    if len(ea) != len(eb):
        return "length", min(len(ea), len(eb))
    return ("beyond-stored" if a.get("truncated") or b.get("truncated") else "outcome-only"), None

A, ma = load(sys.argv[1]); B, mb = load(sys.argv[2])
show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 10
both = sorted(set(A) & set(B))
same = [n for n in both if A[n]["fingerprint"] == B[n]["fingerprint"]]
diff = [n for n in both if A[n]["fingerprint"] != B[n]["fingerprint"]]
odiff = [n for n in diff if A[n]["outcome"] != B[n]["outcome"]]
src = collections.Counter(first_diff(A[n], B[n])[0].split(":")[0] for n in diff)
ops = collections.Counter(first_diff(A[n], B[n])[0] for n in diff)
files = collections.Counter(n.split("::")[0] for n in diff)
print(json.dumps({"A_files": ma, "B_files": mb, "A_tests": len(A), "B_tests": len(B), "both": len(both),
                  "only_A": len(set(A) - set(B)), "only_B": len(set(B) - set(A)),
                  "same_fp": len(same), "diff_fp": len(diff), "diff_fp_outcome_differs": len(odiff),
                  "diff_first_source": dict(src), "diff_first_op": ops.most_common(8), "diff_top_files": files.most_common(8),
                  "outcome_diffs": [(n, A[n]["outcome"], B[n]["outcome"]) for n in odiff[:show]],
                  "diff_examples": [(n, first_diff(A[n], B[n])) for n in diff[:show]]}, indent=1))
