#!/usr/bin/env python3
"""R-019c, item 1: re-derive REPORT-4's numbers from the committed rows, independently of aggregate4.py.

    python3 rederive.py RESULTS_DIR

Correctness is recomputed here (named == truth), never read from the rows' ``finder_correct`` fields; those are
only cross-checked. Case ids are matched against ``RESULTS_DIR/round3``.
"""
import glob
import json
import os
import statistics
import sys


def rows(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    # nearest-rank, as a check of both conventions below
    import math
    return xs[max(0, math.ceil(q * len(xs)) - 1)]


def med(xs):
    return statistics.median(xs) if xs else None


def named_of(fd):
    c = (fd or {}).get("culprit") or {}
    return c.get("commit") or c.get("input") or (tuple(sorted(c["inputs"])) if c.get("inputs") else None)


def suspect(why):
    why = why or ""
    return why.rsplit("suspect ", 1)[1].split(";")[0].strip() if "suspect " in why else None


def load(root):
    out = []
    for p in sorted(glob.glob(os.path.join(root, "a-*.jsonl"))):
        for r in rows(p):
            out.append(("a2 " + r["shape"], r["id"], r, p))
    for p in sorted(glob.glob(os.path.join(root, "b-*.jsonl"))):
        for r in rows(p):
            out.append(("b", r["id"], r, p))
    for r in rows(os.path.join(root, "c-final.jsonl")):
        out.append(("c no-code", r["id"], r, "c-final"))
    for r in rows(os.path.join(root, "c-edit.jsonl")):
        out.append(("c data edit", r["id"], r, "c-edit"))
    for r in rows(os.path.join(root, "d.jsonl")):
        out.append(("d", f"{r['repo']}|{r['victim']}|{r['config']}", r, "d"))
    return out


def judge(kind, r):
    """(usable, named, correct, suspect, executions, wall, red_probes)."""
    if kind == "d":
        n = r.get("finder_named")
        return (True, n, n is not None and n == r["truth"], suspect(r.get("red_side")), r.get("executions"),
                r.get("finder_wall"), r.get("red_side_probes", 0))
    if r.get("skip") or r.get("green_run") != "pass" or r.get("red_run") != "fail":
        return (False,) + (None,) * 6
    fd = r["finder"]
    n = named_of(fd)
    truth = r["truth"]
    ok = n is not None and (n == truth or (isinstance(n, tuple) and set(n) == set(truth if isinstance(truth, list)
                                                                                   else [truth])))
    return (True, n, ok, suspect(fd.get("why")), fd.get("executions"), fd.get("wall"), fd.get("red_probes") or 0)


def main(root):
    now = load(root)
    old = load(os.path.join(root, "round3"))
    ids_now = {(k.split()[0], i) for k, i, _, _ in now}
    ids_old = {(k.split()[0], i) for k, i, _, _ in old}
    print("ids only in round 3:", sorted(ids_old - ids_now))
    print("ids only in round 4:", sorted(ids_now - ids_old))
    kinds = ["a2 placed", "a2 reland", "b", "c no-code", "c data edit", "d"]
    tot = {"n": 0, "stated": 0, "right": 0, "wrong": 0, "unk": 0, "sus": 0, "sus_true": 0, "ex": [], "wall": []}
    mism = []
    for kind in kinds:
        n = st = rt = wr = un = su = st_ = 0
        ex, wa = [], []
        for k, i, r, _ in now:
            if k != kind:
                continue
            u, nm, ok, sus, e, w, _rp = judge(k, r)
            if not u:
                continue
            n += 1
            ex.append(e)
            wa.append(w)
            if nm is not None:
                st += 1
                rt += ok
                wr += (not ok)
            else:
                un += 1
                if sus:
                    su += 1
                    t = r["truth"]
                    st_ += (sus == t or t.startswith(sus) or sus.startswith(t[:10]))
            fc = r.get("finder_correct")
            if fc is not None and bool(fc) != bool(ok):
                mism.append((kind, i, fc, ok))
        print(f"{kind:12s} cases {n:3d} stated {st:3d} right {rt:3d} wrong {wr} unknown {un:2d} "
              f"(suspect {su}, = truth {st_}) exec med {med(ex)} p90 {pct(ex, .9)} max {max(ex)} "
              f"wall med {med(wa):.1f} p90 {pct(wa, .9):.1f}")
        for key, v in (("n", n), ("stated", st), ("right", rt), ("wrong", wr), ("unk", un), ("sus", su),
                       ("sus_true", st_)):
            tot[key] += v
        tot["ex"] += ex
        tot["wall"] += wa
    print(f"ALL cases {tot['n']} stated {tot['stated']} ({tot['stated'] / tot['n']:.1%}) right {tot['right']} "
          f"wrong {tot['wrong']} unknown {tot['unk']} suspect {tot['sus']} = truth {tot['sus_true']}; "
          f"exec med {med(tot['ex'])} p90 {pct(tot['ex'], .9)} max {max(tot['ex'])}; wall med "
          f"{med(tot['wall']):.1f} p90 {pct(tot['wall'], .9):.1f} max {max(tot['wall']):.0f}")
    print("finder_correct field disagrees with recomputed correctness:", mism)
    # round 3, from round-3 rows
    n3 = s3 = 0
    for k, i, r, _ in old:
        if k == "d":
            n3 += 1
            s3 += r.get("finder_named") is not None
            continue
        if r.get("skip"):
            continue
        n3 += 1
        s3 += named_of(r.get("finder")) is not None and r.get("green_run") == "pass" and r.get("red_run") == "fail"
    print(f"round 3 rows: cases {n3} stated {s3} ({s3 / n3:.1%})")
    # transitions a2 + b
    o = {(k.split()[0], i): r for k, i, r, _ in old}
    tr = {}
    for k, i, r, _ in now:
        if k.split()[0] not in ("a2", "b"):
            continue
        r3 = o.get((k.split()[0], i))
        a = "stated" if named_of(r3["finder"]) else "unknown"
        b = "stated" if named_of(r["finder"]) else "unknown"
        tr[(k.split()[0], a, b)] = tr.get((k.split()[0], a, b), 0) + 1
    print("transitions:", tr)
    # round-3 rows of the dropped no-code cases
    for k, i, r, _ in old:
        if k == "c no-code" and (k.split()[0], i) in ids_old and not judge(k, dict(r, skip=None))[0] is None:
            pass
    inf = rp = 0
    for k, i, r, _ in now:
        if k.split()[0] in ("a2", "b"):
            inf += r["finder"].get("red_inferred") or 0
            rp += r["finder"].get("red_probes") or 0
    print("a2+b red_inferred", inf, "red_probes", rp)
    for kind in ("a2", "b", "d"):
        xs = [judge(k, r)[6] for k, i, r, _ in now if k.split()[0] == kind and judge(k, r)[0]]
        print(f"red probes {kind}: median {med(xs)} p90 {pct(xs, .9)} max {max(xs)}")


if __name__ == "__main__":
    main(sys.argv[1])
