#!/usr/bin/env python3
"""§7 REPORT.md, printed only from the committed raw rows and files under results/.

Inputs: discovery leaves (results/discovery/leaves.jsonl.gz), candidates.jsonl, rows.jsonl, issues.jsonl,
handreads.jsonl (§4.4), handcheck.jsonl (AC4), probe_*.json, chunks.jsonl, budget.json, CHANGES.md, desk_survey.md.
`report.py` writes REPORT.md; `report.py --stdout` prints it. ``render(load())`` is pure (verify.py re-runs it).
"""
from __future__ import annotations

import gzip
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import rules as R  # noqa: E402

RES = HERE / "results"
TOOLS = ["stryker", "mutmut", "cosmic-ray", "pitest", "cargo-mutants", "infection", "mutant", "go-mutesting",
         "gremlins", "mull", "muter", "mutatest", "uses-action"]


def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def _json(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def load(res: Path = RES) -> dict:
    rows_by = {}
    for r in _jsonl(res / "rows.jsonl"):
        rows_by[r["idx"]] = r
    issues = {}
    for x in sorted(_jsonl(res / "issues.jsonl") + _jsonl(res / "issues_wf.jsonl"), key=lambda z: z.get("at") or ""):
        issues[x["repo"].lower()] = x
    rows = []
    for idx in sorted(rows_by):
        r = dict(rows_by[idx])
        if r["repo"].lower() in issues and not (r.get("issues") or {}).get("done"):
            r["issues"] = issues[r["repo"].lower()]
        rows.append(r)
    handreads = {}
    for h in _jsonl(res / "handreads.jsonl"):
        handreads[(h["repo"].lower(), h["id"])] = h
    handcheck = {}
    for h in _jsonl(res / "handcheck.jsonl"):
        handcheck[(h["repo"].lower(), h["sample"])] = h
    leaves = []
    p = res / "discovery" / "leaves.jsonl.gz"
    if p.exists():
        by = {}
        for lf in _jsonl(p):
            by[(lf["query"], lf["a"], lf["b"])] = lf
        leaves = list(by.values())
    return {"rows": rows, "handreads": handreads, "handcheck": handcheck, "leaves": leaves,
            "candidates": _jsonl(res / "candidates.jsonl"), "chunks": _jsonl(res / "chunks.jsonl"),
            "probes": {k: _json(res / f"probe_{k}.json") for k in ("session", "workflow")},
            "budget": _json(res / "budget.json", {}), "state": _json(res / "discovery_state.json", {}),
            "changes": (HERE / "CHANGES.md").read_text() if (HERE / "CHANGES.md").exists() else "",
            "desk": (HERE / "desk_survey.md").read_text() if (HERE / "desk_survey.md").exists() else ""}


# ---------------------------------------------------------------------------------------------- computation

def apply_handcheck(rows: list[dict], handcheck: dict) -> list[dict]:
    out = []
    for r in rows:
        r = dict(r)
        for (repo, _s), h in sorted(handcheck.items()):
            if repo == r["repo"].lower() and not h.get("ok") and h.get("reclass"):
                rc = h["reclass"]
                if "cls" in rc:
                    r["cls"] = rc["cls"]
                if "pain" in rc:
                    r["pain_override"] = rc["pain"]
        out.append(r)
    return out


def pain(r: dict, handreads: dict) -> tuple[str, list[str]]:
    if r.get("pain_override"):
        return r["pain_override"], ["hand check"]
    return R.pain_of(r, handreads)


def samples(rows: list[dict], handreads: dict) -> dict:
    """AC4 samples (random.Random(2) over sorted repository names)."""
    rng = random.Random(2)
    run = sorted(r["repo"] for r in rows if r.get("cls") == "running")
    yes = sorted(r["repo"] for r in rows if r.get("cls") == "running" and pain(r, handreads)[0] == "yes")
    notr = sorted(r["repo"] for r in rows if r.get("cls") == "not-running")
    unl = sorted(r["repo"] for r in rows if r.get("mclass") == "tool-present-unlinked" and r.get("cls") != "excluded")
    rej = sorted(f"{repo}|{cid}" for (repo, cid), h in handreads.items() if h.get("verdict") == "rejected")
    uses = sorted({r["repo"] for r in rows if r.get("uses_actions")})
    pick = lambda xs, k: sorted(rng.sample(xs, min(k, len(xs))))  # noqa: E731
    return {"pain-yes": yes[:40], "running": pick(run, 20), "not-running": pick(notr, 10),
            "tool-present-unlinked": pick(unl, 10), "rejected": pick(rej, 10), "uses-action": uses}


def handcheck_status(smp: dict, handcheck: dict) -> dict:
    missing, fails = [], {}
    for s, xs in smp.items():
        for x in xs:
            h = handcheck.get((x.split("|")[0].lower(), s))
            if h is None:
                missing.append(f"{s}:{x}")
            elif not h.get("ok"):
                fails.setdefault(s, []).append(x)
    stop = len(fails.get("running", [])) > 2 or any(
        (handcheck.get((x.lower(), s)) or {}).get("reclass", {}).get("cls") == "running"
        for s in ("not-running", "tool-present-unlinked") for x in fails.get(s, []))
    return {"missing": missing, "fails": fails, "stop": stop, "ok": not missing and not stop}


def compute(d: dict) -> dict:
    rows = apply_handcheck(d["rows"], d["handcheck"])
    hr = d["handreads"]
    order, pool = discover.build(d["leaves"]) if d["leaves"] else ([], {"N": 0, "candidates": 0, "per_query": {},
                                                                     "truncated_leaves": 0, "incomplete_leaves": 0,
                                                                     "truncated_missing": 0, "leaves": 0,
                                                                     "drop_reachable_at": 300})
    counted = [r for r in rows if r.get("cls") != "excluded"]
    excluded = [r for r in rows if r.get("cls") == "excluded"]
    running = [r for r in counted if r.get("cls") == "running"]
    pains = {r["repo"]: pain(r, hr) for r in running}
    c = {"read": len(counted), "excluded": len(excluded), "running": len(running),
         "not_running": sum(1 for r in counted if r.get("cls") == "not-running"),
         "uncertain": sum(1 for r in counted if r.get("cls") == "uncertain"),
         "pain_yes": sum(1 for p in pains.values() if p[0] == "yes"),
         "pain_unknown": sum(1 for p in pains.values() if p[0] == "unknown"),
         "pain_no": sum(1 for p in pains.values() if p[0] == "no"),
         "N": pool["N"], "candidates": pool["candidates"]}
    cand_idx = {x["idx"] for x in d["candidates"]}
    row_idx = {r["idx"] for r in rows}
    c["all_read"] = bool(cand_idx) and cand_idx <= row_idx
    c["any_truncated"] = pool["truncated_leaves"] > 0
    c["any_incomplete"] = pool["incomplete_leaves"] > 0
    smp = samples(rows, hr)
    hc = handcheck_status(smp, d["handcheck"])
    c["handcheck_ok"] = hc["ok"]
    c["budget_over"] = bool((d.get("budget") or {}).get("over"))
    dec = R.decide(c) if c["read"] else {"kind": "NOT STARTED", "line": "NOT STARTED: no candidate read yet.",
                                         "U_R": 1.0, "U_P": 1.0, "U_R_N": float(c["N"]), "U_P_N": float(c["N"])}
    return {"rows": rows, "counted": counted, "excluded": excluded, "running": running, "pains": pains, "c": c,
            "pool": pool, "dec": dec, "samples": smp, "handcheck": hc}


def _q(vals: list[float]) -> str:
    if not vals:
        return "-"
    v = sorted(vals)
    if len(v) == 1:
        return f"{v[0]:.1f} (one value)"
    qs = statistics.quantiles(v, n=4, method="inclusive")
    return f"{statistics.median(v):.1f} (Q1 {qs[0]:.1f}, Q3 {qs[2]:.1f})"


def first_line(d: dict, x: dict) -> str:
    probes = [p for p in d["probes"].values() if p]
    code_ok = [r for p in probes for r in p["results"] if r["kind"] == "code" and r["status"] == 200]
    if probes and not code_ok:
        return "BLOCKED"
    if x["dec"]["kind"] in ("CONTINUE", "DROP", "NO DECISION") and (x["handcheck"]["ok"] or
                                                                   x["dec"]["kind"] == "NO DECISION"):
        return "DONE"
    return "NOT DONE"


def render(d: dict) -> str:
    x = compute(d)
    c, pool, dec = x["c"], x["pool"], x["dec"]
    L = [first_line(d, x), "", "# Test-quality count: repositories running mutation testing in CI, and time pain", ""]
    L += ["Printed by `report.py` from the committed raw rows; `verify.py` re-derives every row from the raw responses "
          "and re-prints this file. Rules: `PREREG.md`.", ""]
    L += ["## Changes after PREREG", "", d["changes"].strip() or "None.", ""]
    L += ["## Decision", "", f"**{dec['line']}**", "",
          "covered: GitHub Actions, tools stryker (JS/.NET/Scala), mutmut, cosmic-ray, PIT (Maven, Gradle), "
          "cargo-mutants, Infection, mutant, go-mutesting, gremlins, Mull, Muter, mutatest; not covered: other CI "
          "systems, private repositories, tools not listed.", "",
          f"read {c['read']}, running {c['running']}, not-running {c['not_running']}, uncertain {c['uncertain']}; "
          f"pain yes {c['pain_yes']}, unknown {c['pain_unknown']}, no {c['pain_no']}; N {c['N']}; "
          f"U_R {dec['U_R']:.5f} (U_R×N {dec['U_R_N']:.1f}), U_P {dec['U_P']:.5f} (U_P×N {dec['U_P_N']:.1f}); "
          f"whole frame read: {'yes' if c['all_read'] else 'no'}; truncated leaves: {pool['truncated_leaves']}; "
          f"incomplete leaves: {pool['incomplete_leaves']}; hand check: {'pass' if c['handcheck_ok'] else 'not passed'}.",
          ""]
    # ---------------------------------------------------------------- discovery
    L += ["## Discovery", "", f"leaves {pool['leaves']}, candidates {pool['candidates']}, unread hits on truncated "
          f"leaves {pool['truncated_missing']}, N {pool['N']}.",
          f"DROP reachable via U_P at r >= {pool['drop_reachable_at']} (assumes no uncertain or unknown rows).", ""]
    if x["counted"]:
        share = c["uncertain"] / c["read"]
        L += [f"Observed uncertain share {share:.3f}; DROP still reachable within the frame: "
              f"{'yes' if R.wilson_upper(c['uncertain'], max(c['read'], 1)) * c['N'] < 20 or c['N'] < 300 else 'no'}.",
              ""]
    L += ["| query | leaves | total_count | repos | only this query | unread hits | contribution to N | truncated |",
          "|---|---|---|---|---|---|---|---|"]
    for q, v in pool["per_query"].items():
        L.append(f"| `{q}` | {v['leaves']} | {v['total_count']} | {v['repos']} | {v['only_this_query']} | "
                 f"{v['unread_hits']} | {v['contribution']} | {v['truncated_leaves']} |")
    L.append("")
    tl = [lf for lf in d["leaves"] if lf.get("truncated")]
    if tl:
        L += ["Truncated leaves: " + "; ".join(f"`{lf['query']}` size:{lf['a']}..{lf['b']} total {lf['total_count']}"
                                                f" read {lf['read']}" for lf in sorted(tl, key=lambda z: (z['query'], z['a']))), ""]
    # ---------------------------------------------------------------- funnel
    cnt = lambda pred: sum(1 for r in x["counted"] if pred(r))  # noqa: E731
    mut_rows = [r for r in x["counted"] if r.get("mclass") == "has-mutation-job"]
    L += ["## Funnel", "",
          f"- candidates {pool['candidates']} -> rows {len(x['rows'])} -> excluded {c['excluded']} "
          f"({', '.join(f'{k} {v}' for k, v in sorted(_excl(x['excluded']).items())) or 'none'}) -> read {c['read']}",
          f"- has-mutation-job {len(mut_rows)}, unresolved {cnt(lambda r: r.get('mclass') == 'unresolved')}, "
          f"tool-present-unlinked {cnt(lambda r: r.get('mclass') == 'tool-present-unlinked')}, "
          f"no-mutation {cnt(lambda r: r.get('mclass') == 'no-mutation')}, error {cnt(lambda r: r.get('mclass') == 'error')}",
          f"- running {c['running']}, configured-not-running {cnt(lambda r: r.get('status') == 'configured-not-running')}, "
          f"uncertain with a mutation job {sum(1 for r in mut_rows if r.get('cls') == 'uncertain')} "
          f"(runs cap {sum(1 for r in mut_rows if any(j.get('status') == 'uncertain' for j in r.get('jobs') or []))}, "
          f"unsupported {sum(1 for r in mut_rows if any(j.get('status') == 'unsupported' for j in r.get('jobs') or []))})",
          f"- duration read {sum(1 for r in x['running'] if (r.get('duration') or {}).get('max_median_min') is not None)}"
          f", duration pain {sum(1 for r in x['running'] if (r.get('duration') or {}).get('pain'))}",
          f"- pain yes {c['pain_yes']}, unknown {c['pain_unknown']}, no {c['pain_no']}", ""]
    unk = {}
    for repo, (p, why) in x["pains"].items():
        if p == "unknown":
            for w in why:
                unk[w] = unk.get(w, 0) + 1
    if unk:
        L += ["Pain unknown reasons (a repository can have several): " +
              ", ".join(f"{k} {v}" for k, v in sorted(unk.items())), ""]
    # ---------------------------------------------------------------- per tool
    L += ["## Per tool (running repositories)", "",
          "| tool | running | every-change | scheduled | manual | other | median duration min (quartiles) | "
          "machine min per run (median) | wrapped |", "|---|---|---|---|---|---|---|---|---|"]
    for t in TOOLS:
        rs = [r for r in x["running"] if t in _tools(r)]
        if not rs:
            continue
        fr = {k: sum(1 for r in rs if _freq(r) == k) for k in ("every-change", "scheduled", "manual", "other")}
        durs = [r["duration"]["max_median_min"] for r in rs if (r.get("duration") or {}).get("max_median_min") is not None]
        mach = [r["duration"]["best"]["machine_min"] for r in rs if (r.get("duration") or {}).get("best")
                and r["duration"]["best"].get("machine_min") is not None]
        L.append(f"| {t} | {len(rs)} | {fr['every-change']} | {fr['scheduled']} | {fr['manual']} | {fr['other']} | "
                 f"{_q(durs)} | {f'{statistics.median(mach):.1f}' if mach else '-'} | "
                 f"{sum(1 for r in rs if any(j.get('wrapped') for j in r.get('jobs') or []))} |")
    L.append("")
    # ---------------------------------------------------------------- pain list
    L += ["## Pain list", "", "| repository | tool | frequency | minutes | kind | date | quote / evidence |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted(x["running"], key=lambda r: r["repo"].lower()):
        p, why = x["pains"][r["repo"]]
        if p != "yes":
            continue
        dur = r.get("duration") or {}
        mins = f"{dur['max_median_min']:.1f}" if dur.get("max_median_min") is not None else "-"
        if dur.get("pain"):
            b = dur["best"]
            L.append(f"| {r['html_url']} | {', '.join(_tools(r))} | {_freq(r)} | {mins} | duration | - | "
                     f"median of {b['n']} runs, `{b['file']}` job `{b['job']}` |")
            continue
        for cnd in _confirmed(r, d["handreads"]):
            h = d["handreads"][(r["repo"].lower(), cnd["id"])]
            kind = ", ".join(cnd.get("kinds") or [cnd.get("kind")]) if cnd.get("kind") == "commit" else "issue"
            L.append(f"| {r['html_url']} | {', '.join(_tools(r))} | {_freq(r)} | {mins} | {kind} | "
                     f"{(cnd.get('date') or '')[:10]} | \"{_esc(h.get('quote'))}\" {h.get('url')} |")
    L.append("")
    # ---------------------------------------------------------------- information
    info = [(repo, cid, h) for (repo, cid), h in sorted(d["handreads"].items()) if h.get("verdict") == "information"]
    cnr = sorted(r["repo"] for r in x["counted"] if r.get("status") == "configured-not-running")
    uses = sorted({(r["repo"], u["uses"]) for r in x["rows"] for u in r.get("uses_actions") or []})
    maint = sorted(r["repo"] for r in x["excluded"] if r.get("excluded") == ["maintainer"]
                   and r.get("cls_if_counted") == "running")
    timeouts = sorted({(r["repo"], ch["sha"][:7]) for r in x["running"] for ch in (r.get("history") or {}).get("changes") or []
                       if any("timeout" in (k or "") for k in ch.get("reasons") or [])})
    L += ["## Information (not pain, not counted)", "",
          f"- complaint-only or timeout texts (hand-read `information`): {len(info)}" +
          ("".join(f"\n  - {repo} {cid}: \"{_esc(h.get('quote'))}\" {h.get('url')}" for repo, cid, h in info)),
          f"- narrowing changes whose text mentions a timeout: {len(timeouts)}" +
          ("".join(f"\n  - {a} {b}" for a, b in timeouts)),
          f"- configured-not-running: {len(cnr)}" + ("".join(f"\n  - {a}" for a in cnr)),
          f"- uses-action matches: {len(uses)}" + ("".join(f"\n  - {a}: `{b}`" for a, b in uses)),
          f"- excluded maintainer repositories that run mutation testing in CI: {len(maint)}" +
          ("".join(f"\n  - {a}" for a in maint)), ""]
    # ---------------------------------------------------------------- hand check
    hc = x["handcheck"]
    L += ["## Hand check (AC4)", "",
          f"samples: " + ", ".join(f"{k} {len(v)}" for k, v in x["samples"].items()) +
          f"; missing verdicts {len(hc['missing'])}; failures " +
          (", ".join(f"{k} {len(v)}" for k, v in sorted(hc["fails"].items())) or "none") +
          f"; rule fix required: {'yes' if hc['stop'] else 'no'}.", ""]
    for k, v in x["samples"].items():
        if v:
            L.append(f"- {k}: " + ", ".join(v))
    L.append("")
    # ---------------------------------------------------------------- budget / chunks
    L += ["## Budget", ""]
    for ch in d["chunks"]:
        L.append(f"- chunk {ch['chunk']}: {ch['candidates']} candidates, {ch['requests']} requests, "
                 f"{ch.get('requests_per_candidate')} per candidate, {ch.get('requests_per_running')} per running "
                 f"repository, X-RateLimit-Remaining {ch.get('remaining')}, {ch['minutes']} min, methods "
                 f"{ch.get('methods')}, stopped {ch.get('stopped')}")
    if d["chunks"]:
        ch = d["chunks"][0]
        per_h = ch["candidates"] / max(ch["minutes"], 0.1) * 60
        left = max(c["candidates"] - c["read"] - c["excluded"], 0)
        L.append(f"- pool: {c['N']}, requests per candidate observed {ch.get('requests_per_candidate')}, requests per "
                 f"running repository observed {ch.get('requests_per_running')}, X-RateLimit-Remaining observed "
                 f"{ch.get('remaining')}, fits 24 h: {'yes' if left / max(per_h, 0.01) <= 24 else 'no'}")
    L.append("")
    L += ["## Limits", "", "- Files read on default branches only; public repositories only; GitHub Actions only.",
          "- Code search is legacy code search (punctuation ignored, 1,000 results per query); unread hits of "
          "truncated leaves are counted in N as possible repositories.", ""]
    if d["desk"]:
        L += [d["desk"].strip(), ""]
    return "\n".join(L) + "\n"


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def _excl(rows) -> dict:
    out = {}
    for r in rows:
        for e in r.get("excluded") or []:
            out[e] = out.get(e, 0) + 1
    return out


def _tools(r: dict) -> list[str]:
    return sorted({m["tool"] for j in r.get("jobs") or [] if j.get("status") == "running"
                   for s in j["steps"] for m in s["mutations"]})


def _freq(r: dict) -> str:
    fs = [j.get("freq") for j in r.get("jobs") or [] if j.get("status") == "running"]
    for k in ("every-change", "scheduled", "manual", "other"):
        if k in fs:
            return k
    return "-"


def _confirmed(r: dict, hr: dict) -> list[dict]:
    cs = ((r.get("history") or {}).get("candidates") or []) + ((r.get("issues") or {}).get("candidates") or [])
    return [c for c in cs if (hr.get((r["repo"].lower(), c["id"])) or {}).get("verdict") == "confirmed"
            and (c.get("date") or "") >= R.HISTORY_START]


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    text = render(load())
    if "--stdout" in argv:
        sys.stdout.write(text)
    else:
        (HERE / "REPORT.md").write_text(text)
        print(text.splitlines()[0], "|", [ln for ln in text.splitlines() if ln.startswith("**")][0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
