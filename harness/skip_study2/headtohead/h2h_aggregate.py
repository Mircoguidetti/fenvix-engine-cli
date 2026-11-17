#!/usr/bin/env python3
"""Tables for the head-to-head walks (h2h_walk.py): time skipped and wrong skips per rule, per project and arm.

    python3 harness/skip_study2/headtohead/h2h_aggregate.py h1 [--md] [--json out.json]

* Unit cost = max(test durations, unit wall time - fixed process start-up), the start-up being the 5th percentile of
  the unit walls (as harness/skip_study2/aggregate.py). Share skipped per transition = cost of the units the rule
  does not rerun / cost of all units; median and mean over the transitions every shard reached.
* Verified skips of a rule = its skips of units that ran fresh at that commit (``extra`` = units C reran, so every
  skip of A / B / B+ that C does not make; ``sample`` = the random verification sample of C's skips).
* A mismatch is ``wrong`` when the fresh run fails while the reused outcome passed, both head re-runs fail and both
  re-runs at the cached commit pass (``rechecks``); ``flaky`` when any of those disagrees; ``unconfirmed`` when the
  re-check at the cached commit did not run (budget); ``set`` when nothing fails but the test set / outcomes differ.
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = ("A", "Ae", "Af", "B", "B+", "C")
LIBS = ("arrow attrs boltons click flask isort jinja marshmallow more-itertools pygments sqlparse structlog toolz "
        "werkzeug").split()


def stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "median": None, "mean": None}
    return {"n": len(xs), "median": statistics.median(xs), "mean": statistics.fmean(xs)}


def load(run_id):
    groups = defaultdict(list)
    for f in sorted((HERE / "results" / run_id).glob("*.json.gz")):
        d = json.loads(gzip.open(f).read())
        groups[(d["spec"]["name"], d.get("arm") or "main")].append(d)
    return groups


def is_test_unit(u, spec):
    """walk.discover matches with fnmatch, whose ``*`` also crosses ``/``: ``**/test_*.py`` then matches
    ``tests/test_apps/x/__init__.py``. Keep units whose basename matches an include pattern's basename, and the
    directory units."""
    if u in spec.get("dir_units", []):
        return True
    base = u.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(base, p.rsplit("/", 1)[-1]) for p in spec["units"]["include"])


def summarize(shards):
    spec = shards[0]["spec"]
    units = {}
    for d in shards:
        units.update({u: c for u, c in (d.get("units") or {}).items() if c and is_test_unit(u, spec)})
    dropped = {u for d in shards for u in (d.get("units") or {}) if not is_test_unit(u, spec)}
    walls = sorted(c["wall"] for c in units.values() if c.get("wall"))
    base = walls[max(0, int(len(walls) * 0.05) - 1)] if walls else 0.0
    cost = {u: max(c["test"], c.get("wall", 0.0) - base) for u, c in units.items()}
    by_i = defaultdict(list)
    for d in shards:
        for t in d["transitions"]:
            by_i[t["i"]].append(t)
    full = sorted(i for i, ts in by_i.items() if len(ts) == len(shards))
    share = {r: [] for r in RULES}
    share_at = {r: {} for r in RULES}
    checks = {r: Counter() for r in RULES}
    keys = {r: set() for r in RULES}
    present = {r for d in shards for r in d.get("rules", ["C", "A", "B", "B+"])}
    mism = {r: [] for r in RULES}
    skips = {r: 0 for r in RULES}
    unit_tr = 0
    for i in full:
        live, dec = [], {}
        for t in by_i[i]:
            live += list(t["tests"])
            dec.update(t["decisions"])
            for r in RULES:
                ck = t["checks"].get(r)
                if ck and "keys" not in ck:
                    # h1 / h2 carry counts only (no per-unit keys): non-test units cannot be removed from them
                    checks[r].update({k: v for k, v in ck.items() if k != "keys"})
                elif ck:
                    kk = [(u, ri) for u, ri in ck.get("keys", []) if u not in dropped]
                    ne = sum(1 for u, _ in kk if (t["decisions"].get(u) or {}).get("C"))
                    checks[r].update({"n": len(kk), "extra": ne, "sample": len(kk) - ne})
                    keys[r].update((u, ri) for u, ri in ck.get("keys", []) if u not in dropped)
            for m in t["mismatch"]:
                if m["unit"] in dropped:
                    continue
                mism[m["rule"]].append(dict(m, i=i))
        live = [u for u in live if u in cost]
        tot = sum(cost[u] for u in live)
        unit_tr += len(live)
        for r in RULES:
            if r not in present:
                continue
            must = sum(cost[u] for u in live if (dec.get(u) or {}).get(r))
            share[r].append(1 - must / tot if tot else None)
            share_at[r][i] = share[r][-1]
            skips[r] += sum(1 for u in live if not (dec.get(u) or {}).get(r))
    rech = {}
    for d in shards:
        for x in d.get("rechecks", []):
            rech[(x["unit"], x["rec_sha"], x.get("profile", 0))] = x
    out = {"transitions": len(full), "shards": len(shards), "units": len(cost), "unit_transitions": unit_tr,
           "non_test_units_dropped": len(dropped),
           "profiles": shards[0].get("profiles"), "interp": sorted({c.get("interp", "") for d in shards
                                                                    for c in d["commits"] if c.get("interp")}),
           "notes": sorted({n for d in shards for n in d.get("notes", [])})}
    if shards[0].get("change"):
        out["change"] = shards[0]["change"]
        out["edits"] = [e for d in shards for e in d.get("edits", [])]
        out["after_landing"] = sum(1 for i in full if by_i[i][0].get("profile") == 1)
        # units that fail fresh after the change landed but passed fresh before it (what the change broke)
        before = set().union(*[set(t.get("fresh_bad", [])) for i in full for t in by_i[i] if t.get("profile") == 0]) \
            if any(by_i[i][0].get("profile") == 0 for i in full) else set()
        after = set().union(*[set(t.get("fresh_bad", [])) for i in full for t in by_i[i] if t.get("profile") == 1]) \
            if out["after_landing"] else set()
        out["broken_by_change"] = sorted((after - before) & set(cost))
        out["units_ran_per_commit"] = [sum(t.get("ran", 0) for t in by_i[i]) for i in full]
    out["rules"] = [r for r in RULES if r in present]
    for r in out["rules"]:
        cls = Counter()
        wrong_items, incidents, why = [], set(), Counter()
        wrong_units, wrong_tr = set(), set()
        for m in mism[r]:
            if m["kind"] == "set":
                cls["set"] += 1
                continue
            if m.get("rerun_bad", 0) < 2:
                cls["flaky"] += 1
                continue
            rc = rech.get((m["unit"], m["rec_sha"], m.get("rec_profile", 0)))
            st = (rc or {}).get("status", "")
            if st == "wrong":
                cls["wrong"] += 1
                wrong_items.append(m)
                incidents.add((m["unit"], m["rec_sha"]))
                wrong_units.add(m["unit"])
                wrong_tr.add(m["i"])
                why.update(m.get("changes") or [])
            elif st.startswith("flaky"):
                cls["flaky"] += 1
            else:
                cls["unconfirmed"] += 1
        out[r] = {"time": stats(share[r]), "skips": skips[r], "checked": checks[r]["n"],
                  "checked_distinct": len(keys[r]),
                  "checked_extra": checks[r]["extra"], "checked_sample": checks[r]["sample"],
                  "wrong": cls["wrong"], "wrong_incidents": len(incidents), "flaky": cls["flaky"],
                  "wrong_units": len(wrong_units), "wrong_commits": len(wrong_tr),
                  "unconfirmed": cls["unconfirmed"], "set_diff": cls["set"],
                  "wrong_why": dict(why.most_common(12)),
                  "wrong_examples": [{k: m.get(k) for k in ("unit", "i", "rec_i", "fails", "changes", "c")}
                                     for m in wrong_items[:8]],
                  "share_series": [round(x, 4) if x is not None else None for x in share[r]]}
        if out.get("change"):
            land = out["change"].get("land", 3)
            aft = [v for i, v in share_at[r].items() if i >= land and v is not None]
            out[r]["landing_share"] = share_at[r].get(land)
            out[r]["after_share"] = stats(aft)
            missed = {m["unit"] for m in wrong_items}
            out[r]["broken_missed"] = sorted(missed & set(out["broken_by_change"]))
            out[r]["landing_wrong_units"] = sorted({m["unit"] for m in wrong_items if m["i"] == land})
    return out


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def row(name, s, r):
    x = s[r]
    t = x["time"]
    return (f"| {name} | {r} | {s['transitions']} | {pct(t['median'])} / {pct(t['mean'])} | {x['checked']} "
            f"({x['checked_extra']} extra + {x['checked_sample']} sample; {x['checked_distinct'] or 'n/a'} distinct) | "
            f"**{x['wrong']}** "
            f"({x['wrong_incidents']} incidents) | {x['flaky']} | {x['unconfirmed']} | {x['set_diff']} |")


HEAD = ("| project | rule | transitions | time skipped median / mean | verified skips (extra + sample) | wrong "
        "(distinct incidents) | flaky | unconfirmed | set differs, no failure |\n|---|---|---:|---:|---:|---:|---:|---:|---:|")


def pooled(sums, names):
    """Pooled over projects: every transition of every project weighted equally; counts summed. A rule is pooled
    over the projects that have it (Ae / Af: Python only)."""
    out = {}
    for r in RULES:
        ns = [n for n in names if n in sums and r in sums[n].get("rules", [])]
        if not ns:
            continue
        series = [x for n in ns for x in sums[n][r]["share_series"] if x is not None]
        out[r] = {"projects": len(ns), "time": stats(series),
                  "median_of_medians": statistics.median([sums[n][r]["time"]["median"] for n in ns
                                                          if sums[n][r]["time"]["median"] is not None] or [0]),
                  "mean_of_means": statistics.fmean([sums[n][r]["time"]["mean"] for n in ns
                                                     if sums[n][r]["time"]["mean"] is not None] or [0])}
        for k in ("skips", "checked", "checked_distinct", "checked_extra", "checked_sample", "wrong",
                  "wrong_incidents", "flaky", "unconfirmed", "set_diff", "wrong_units", "wrong_commits"):
            out[r][k] = sum(sums[n][r].get(k, 0) for n in ns)
    out["transitions"] = sum(sums[n]["transitions"] for n in names if n in sums)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_ids", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    groups = {}
    for rid in a.run_ids:
        groups.update(load(rid))   # a later run id replaces an earlier one for the same (project, arm)
    res = {}
    for (name, arm), shards in sorted(groups.items()):
        res.setdefault(arm, {})[name] = summarize(shards)
    for arm, sums in res.items():
        print(f"\n### arm: {arm}\n")
        print(HEAD)
        order = [n for n in ("home-assistant", "docusaurus", "vue-core") if n in sums] + \
                [n for n in LIBS if n in sums]
        for n in order:
            for r in sums[n]["rules"]:
                print(row(n, sums[n], r))
        libs = [n for n in LIBS if n in sums]
        if libs:
            p = pooled(sums, libs)
            sums["_libraries"] = p
            print(f"\nlibraries pooled ({len(libs)}): " + "; ".join(
                f"{r}: {pct(p[r]['time']['median'])} / {pct(p[r]['time']['mean'])} (median-of-medians "
                f"{pct(p[r]['median_of_medians'])}, mean-of-means {pct(p[r]['mean_of_means'])}), checked "
                f"{p[r]['checked']} ({p[r]['checked_extra']} extra), wrong {p[r]['wrong']} "
                f"({p[r]['wrong_incidents']} incidents), flaky {p[r]['flaky']}, unconfirmed {p[r]['unconfirmed']}, "
                f"set {p[r]['set_diff']}" for r in RULES if r in p))
        allp = pooled(sums, [n for n in sums if not n.startswith("_")])
        sums["_all"] = allp
        print("\nall projects pooled (each transition weighted equally): " + "; ".join(
            f"{r}: {pct(allp[r]['time']['median'])} / {pct(allp[r]['time']['mean'])}, wrong {allp[r]['wrong']} "
            f"({allp[r]['wrong_incidents']} incidents) of {allp[r]['checked']} verified" for r in RULES if r in allp))
        for n in [x for x in sums if not x.startswith("_")]:
            for r in sums[n]["rules"]:
                if sums[n][r]["wrong"]:
                    print(f"  wrong {n} {r}: why {sums[n][r]['wrong_why']} e.g. {sums[n][r]['wrong_examples'][:2]}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
