#!/usr/bin/env python3
"""REPORT.md from the committed raw rows (§6). Every number is written as ``<n><!--key-->``; ``verify.py`` recomputes
each one and re-prints the file.

Usage: report.py            (writes REPORT.md)
       report.py --print    (prints it)

Inputs (results/): probe_*.json, probe_decisions.json, search_budget_free.json, launch.json, prepass_*.json,
pool.json, orders.json, candidates.jsonl.gz, rows.jsonl, texts_search{,_wf}.jsonl, comments.jsonl, reads.jsonl,
handcheck.json, state.json, population.json, chunks.jsonl; CHANGES.md (listed PREREG changes).
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import rules as R  # noqa: E402
import texts as T  # noqa: E402

RES = HERE / "results"
STRATA = ("S1", "S2", "S3")


def _jsonl(p: Path) -> list[dict]:
    """JSON lines; a truncated last line or gzip member (a job killed mid-write) is dropped."""
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    out = []
    try:
        with op(p, "rt") as f:
            for x in f:
                if x.strip():
                    try:
                        out.append(json.loads(x))
                    except json.JSONDecodeError:
                        pass
    except (EOFError, OSError):
        pass
    return out


def _json(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def load(res: Path = RES) -> dict:
    here = res.parent
    return {
        "probe_session": _json(res / "probe_session.json"), "probe_workflow": _json(res / "probe_workflow.json"),
        "cfg": _json(res / "probe_decisions.json", {}) or {}, "budget_free": _json(res / "search_budget_free.json"),
        "launch": _json(res / "launch.json"),
        "prepass": {**(_json(res / "prepass_code.json", {}) or {}), **(_json(res / "prepass_text.json", {}) or {})},
        "pool": _json(res / "pool.json"), "orders": _json(res / "orders.json", {}) or {},
        "candidates": _jsonl(res / "candidates.jsonl.gz"), "rows": _jsonl(res / "rows.jsonl"),
        "search": _jsonl(res / "texts_search.jsonl") + _jsonl(res / "texts_search_wf.jsonl"),
        "comments": _jsonl(res / "comments.jsonl"), "reads": _jsonl(res / "reads.jsonl"),
        "handcheck": _json(res / "handcheck.json", {}) or {}, "state": _json(res / "state.json", {}) or {},
        "population": _json(res / "population.json", {}) or {}, "chunks": _jsonl(res / "chunks.jsonl"),
        "changes": (here / "CHANGES.md").read_text() if (here / "CHANGES.md").exists() else "",
        "notes": (_json(res / "report_notes.json", {}) or {}).get("notes") or [],
    }


def _last(recs: list[dict], key) -> dict:
    out = {}
    for r in recs:
        out[key(r)] = r
    return out


def reads_map(recs: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in recs:
        out.setdefault(r["url"], {})[r["reader"]] = r
    return out


def apply_handcheck_reads(reads: dict, hc: dict) -> dict:
    """AC4: a text whose hand check failed is reclassified (its second read set to rejected)."""
    out = {u: dict(v) for u, v in reads.items()}
    for k, v in (hc.get("items") or {}).items():
        if k.startswith("text:") and v.get("ok") is False:
            out.setdefault(k[5:], {})["second"] = {"label": "rejected", "reader": "second", "url": k[5:]}
    return out


def member_record(row: dict, cand: dict, search: dict | None, comments: dict | None, reads: dict, hc: dict,
                  cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    repo = (row.get("meta") or {}).get("full_name") or row["repo"]
    rec = (row.get("recordings") or {}).get("yes")
    hc_failed = bool(rec) and ((hc.get("items") or {}).get(f"rec:{row['repo'].lower()}") or {}).get("ok") is False
    if hc_failed:
        rec = None  # later recording files and the texts were never read: pain at most unknown
    texts = T.member_texts(repo, cand.get("hits") or [], search)
    cm = T.comment_map(comments)
    cands, filt = T.candidates_of(texts, cm)
    flags = list(row.get("pain_flags") or [])
    if not rec:
        flags += T.search_flags(search) + T.comment_flags(texts, comments)
        if hc_failed:
            flags.append("recording-handcheck-failed")
        if cfg.get("repo_text_shapes_ok") is False:  # §0.2b: a dropped §3.2 shape -> at most unknown
            flags.append("text-shape-dropped")
    pain = R.member_pain(rec, sorted(set(flags)), cands, reads)
    return {"row": row, "texts": texts, "candidates": cands, "filtered": filt, "pain": pain, "comments": cm}


def compute(d: dict) -> dict:
    rows = list(_last(d["rows"], lambda r: r["idx"]).values())
    cands = {c["idx"]: c for c in d["candidates"]}
    search = {}
    for r in d["search"]:
        search.setdefault(r["repo"].lower(), {})[r["at"]] = r
    comments = _last(d["comments"], lambda r: r["repo"].lower())
    reads = apply_handcheck_reads(reads_map(d["reads"]), d["handcheck"])
    counted = [r for r in rows if r.get("cls") != "excluded"]
    excluded = [r for r in rows if r.get("cls") == "excluded"]
    members = []
    for r in counted:
        if r.get("cls") == "member":
            k = r["repo"].lower()
            members.append(member_record(r, cands.get(r["idx"]) or {}, search_for(k, comments.get(k), search),
                                         comments.get(k), reads, d["handcheck"], d["cfg"]))
    pain_of = {m["row"]["idx"]: m["pain"] for m in members}
    pool = d["pool"] or {s: {"candidates": 0, "N": 0, "missing": 0, "truncated_leaves": 0, "incomplete_leaves": 0,
                             "capped_queries": [], "unfinished": []} for s in STRATA}
    st = {}
    for s in STRATA:
        rs = [r for r in counted if r.get("stratum") == s]
        A = sum(1 for r in rs if r.get("cls") == "uncertain" or (r.get("cls") == "member" and
                                                                  pain_of[r["idx"]]["pain"] in ("yes", "unknown")))
        ids = set((d["orders"] or {}).get(s) or [])
        seen = {r["idx"] for r in rows}
        all_read = s in (d["orders"] or {}) and ids <= seen  # an empty stratum is fully read
        b = R.stratum_bound(A, len(rs), pool[s]["N"], all_read, pool[s]["truncated_leaves"] > 0,
                            pool[s]["incomplete_leaves"] > 0)
        st[s] = {"read": len(rs), "A": A, "all_read": all_read, **b,
                 "member": sum(1 for r in rs if r.get("cls") == "member"),
                 "non_member": sum(1 for r in rs if r.get("cls") == "non-member"),
                 "no_agent_lib": sum(1 for r in rs if r.get("stage") == "no-agent-lib"),
                 "no_ci_tests": sum(1 for r in rs if r.get("stage") == "no-ci-tests"),
                 "uncertain": sum(1 for r in rs if r.get("cls") == "uncertain"),
                 "excluded": sum(1 for r in excluded if r.get("stratum") == s),
                 "yes": sum(1 for r in rs if r.get("cls") == "member" and pain_of[r["idx"]]["pain"] == "yes"),
                 "yes_recording": sum(1 for r in rs if r.get("cls") == "member" and pain_of[r["idx"]]["kind"]
                                      == "recording"),
                 "yes_text": sum(1 for r in rs if r.get("cls") == "member" and pain_of[r["idx"]]["kind"] == "text"),
                 "unknown": sum(1 for r in rs if r.get("cls") == "member" and pain_of[r["idx"]]["pain"] == "unknown"),
                 "no": sum(1 for r in rs if r.get("cls") == "member" and pain_of[r["idx"]]["pain"] == "no")}
    yes = [m for m in members if m["pain"]["pain"] == "yes"]
    hc = handcheck_status(d["handcheck"], yes)
    c = {"yes": len(yes), "handcheck_ok": hc["ok"], "bounds": {s: st[s]["B"] for s in STRATA},
         "read_started": bool(counted or excluded), "state": dict(d["state"])}
    if d["cfg"].get("blocked"):
        c["state"]["blocked"] = True
    dec = R.decide(c)
    return {"rows": rows, "counted": counted, "excluded": excluded, "members": members, "strata": st, "pool": pool,
            "yes": yes, "c": c, "dec": dec, "handcheck": hc, "reads": reads, "cands": cands,
            "text_of": lambda t, m=None: T.text_of(t, (m or {}).get("comments") if m else _comments_for(members, t))}


def search_for(repo_key: str, comments: dict | None, search: dict) -> dict | None:
    """The search record the comment pass used (its ``search_at``), else the member's latest search record."""
    recs = search.get(repo_key) or {}
    if comments and comments.get("search_at") in recs:
        return recs[comments["search_at"]]
    return recs[max(recs)] if recs else None


def _comments_for(members, t):
    for m in members:
        if t["url"] in m["comments"]:
            return m["comments"]
    return {}


def handcheck_status(hc: dict, yes: list[dict]) -> dict:
    """AC4: every recording yes (up to 30) and every text yes (up to 30) checked, plus the samples listed in
    handcheck.json; ok when every required key is present and at most 3 checked yes failed."""
    items = hc.get("items") or {}
    req = sorted(f"rec:{m['row']['repo'].lower()}" for m in yes if m["pain"]["kind"] == "recording")[:30] + \
        sorted(f"text:{m['pain']['evidence']['url']}" for m in yes if m["pain"]["kind"] == "text")[:30]
    missing = [k for k in req if k not in items]
    failed = [k for k, v in items.items() if v.get("ok") is False and k.startswith(("rec:", "text:"))]
    samples_ok = bool(hc.get("samples_done"))
    ok = samples_ok and not missing and len(failed) <= 3
    return {"ok": ok, "required": len(req), "missing": missing, "failed": failed, "samples_done": samples_ok}


def _q(vals) -> str:
    v = sorted(vals)
    if not v:
        return "-"
    p90 = v[min(len(v) - 1, math.ceil(0.9 * len(v)) - 1)]
    return f"median {statistics.median(v):g}, p90 {p90:g}, max {v[-1]:g}"


class Nums:
    def __init__(self):
        self.vals: dict[str, str] = {}

    def __call__(self, key: str, v) -> str:
        s = f"{v:.1f}" if isinstance(v, float) else str(v)
        if key in self.vals and self.vals[key] != s:
            raise ValueError(f"number key {key} used twice with different values")
        self.vals[key] = s
        return f"{s}<!--{key}-->"


def first_line(d: dict, x: dict) -> str:
    if d["cfg"].get("blocked"):
        return "BLOCKED"
    return x["dec"]["first"]


NOT_COVERED = ("private repositories, other CI systems, pain never written down, pain written in words outside the "
               "discovery queries (the frame is pain-first: a DROP bounds the frame, not the population), libraries "
               "and hosts not listed, texts in languages other than English, shapes dropped after the probe")


def render(d: dict) -> tuple[str, dict]:
    x = compute(d)
    n = Nums()
    st, pool, dec, c = x["strata"], x["pool"], x["dec"], x["c"]
    L = [first_line(d, x), "", "# Agent-determinism count: agent repositories with agent-test non-determinism pain", "",
         "Printed by `report.py` from the committed raw rows; `verify.py` re-derives every row from the raw "
         "responses, recomputes every number and re-prints this file. Rules: `PREREG.md`.", ""]
    L += ["## Changes after PREREG", "", d["changes"].strip() or "None.", ""]
    # ------------------------------------------------------------ decision
    no_rt = [m for m in x["yes"] if not all(R.RETRIEVAL_ONLY.match(l["lib"])
                                             for l in m["row"]["libs"]["libraries"])]
    rec_only = c["yes"] >= R.THRESHOLD and all(m["pain"]["kind"] == "recording" for m in x["yes"])
    bt = lambda s: "undefined" if st[s]["B"] is None else n(f"B_{s}", round(st[s]["B"], 1))  # noqa: E731
    L += ["## Decision", "", f"**{dec['line']}**", "",
          f"P {n('P', c['yes'])} (recording {n('P_recording', sum(1 for m in x['yes'] if m['pain']['kind'] == 'recording'))}"
          f", text {n('P_text', sum(1 for m in x['yes'] if m['pain']['kind'] == 'text'))}); P without the "
          f"repositories whose only libraries are langchain*/llama-index*/llamaindex: {n('P_no_retrieval', len(no_rt))} "
          f"(information; the decision uses P)." + (" **recordings only: free substitutes exist.**" if rec_only else ""),
          "",
          f"read {n('read', len(x['counted']))}, members {n('members', len(x['members']))}, pain yes "
          f"{n('yes', c['yes'])}, unknown {n('unknown', sum(1 for m in x['members'] if m['pain']['pain'] == 'unknown'))}"
          f", no {n('no', sum(1 for m in x['members'] if m['pain']['pain'] == 'no'))}, uncertain "
          f"{n('uncertain', sum(1 for r in x['counted'] if r.get('cls') == 'uncertain'))}; bounds S1 {bt('S1')}, "
          f"S2 {bt('S2')}, S3 {bt('S3')}; hand check: {'pass' if x['handcheck']['ok'] else 'not passed'}.", ""]
    L += ["| stratum | candidates | N_s | read | A_s | U_s | B_s | how |", "|---|---|---|---|---|---|---|---|"]
    for s in STRATA:
        L.append(f"| {s} | {n(f'cand_{s}', pool[s]['candidates'])} | {n(f'N_{s}', pool[s]['N'])} | "
                 f"{n(f'read_{s}', st[s]['read'])} | {n(f'A_{s}', st[s]['A'])} | {st[s]['U']:.5f} | {bt(s)} | "
                 f"{st[s]['how']} |")
    L += ["", f"covered: GitHub Actions, public repositories, libraries {', '.join(sorted(R.PY_EXACT))}, "
          f"{', '.join(p + '*' for p in R.PY_PREFIX)} (PyPI); {', '.join(sorted(R.NPM_EXACT))}, "
          f"{', '.join(p + '*' for p in R.NPM_PREFIX)} (npm), pain visible to code, issue and commit search; "
          f"not covered: {NOT_COVERED}.", ""]
    nc = [u for s in STRATA for u in pool[s].get("unfinished") or []]
    if nc or d["cfg"].get("dropped"):
        L += ["Not covered in detail: " + "; ".join([f"unfinished `{u['query']}` ({u['missing']} hits)" for u in nc] +
                                                    [f"dropped `{q}`" for q in d["cfg"].get("dropped") or []]), ""]
    if d.get("notes"):  # coordinator-requested notes (not rule changes): results/report_notes.json
        L += ["## Notes (not rule changes)", ""] + [f"- {x}" for x in d["notes"]] + [""]
    # ------------------------------------------------------------ timing and probes
    bf, la = d["budget_free"] or {}, d["launch"] or {}
    first_search = min([r.get("at") for p in (d["probe_session"], d["probe_workflow"]) if p
                        for r in p.get("results") or [] if r.get("at")] + ([la["at"]] if la.get("at") else []),
                       default=None)
    L += ["## Timing and probes", "",
          f"- coordinator's \"search budget free\" message received: {bf.get('at', 'not yet')}",
          f"- first search request: {first_search or 'none yet'}"
          + (" (later than the message)" if first_search and bf.get("at") and first_search > bf["at"] else ""),
          f"- LAUNCH (UTC date of the first discovery request): {la.get('launch', 'not yet')}",
          f"- probe decisions: {json.dumps({k: v for k, v in d['cfg'].items() if k not in ('text_shapes',)}, sort_keys=True) if d['cfg'] else 'not yet'}",
          ""]
    # ------------------------------------------------------------ pre-pass
    if d["prepass"]:
        proj = discover.projection(d["prepass"])
        L += ["## Pre-pass", "", f"queries {n('pp_queries', len(d['prepass']))}; code family "
              f"{n('pp_code_req', proj['code']['requests'])} requests, {proj['code']['hours']:.2f} h at "
              f"{R.CODE_PER_MIN}/min; issues+commits family {n('pp_text_req', proj['text']['requests'])} requests, "
              f"{proj['text']['hours']:.2f} h at {R.TEXT_PER_MIN}/min; projected discovery {proj['hours']:.2f} h "
              f"(stop above {R.PREPASS_MAX_H:g} h: {'yes' if proj['stop'] else 'no'}); queries above QUERY_CAP "
              f"{n('pp_capped', proj['code']['capped'] + proj['text']['capped'])}.", ""]
        Ns = {s: sum(v.get("total_count") or 0 for v in d["prepass"].values() if v["stratum"] == s) for s in STRATA}
        ns = {s: R.equal_split_reads(Ns[s]) for s in STRATA}
        L += [f"Pre-pass N_s (Σ total_count, hits, an upper bound): " +
              ", ".join(f"{s} {n(f'ppN_{s}', Ns[s])}" for s in STRATA) + "; planned reads (equal split) " +
              ", ".join(f"{s} {n(f'ppn_{s}', ns[s])}" for s in STRATA) +
              f"; zero-count bound {R.zero_bound(Ns, ns):.1f}.", ""]
        L += ["| query | stratum | status | total_count | projected requests |", "|---|---|---|---|---|"]
        for k, v in sorted(d["prepass"].items(), key=lambda kv: (kv[1]["stratum"], kv[0])):
            L.append(f"| `{k}` | {v['stratum']} | {v.get('status')} | {v.get('total_count')} | "
                     f"{R.projected_requests(v.get('total_count') or 0)} |")
        L.append("")
    # ------------------------------------------------------------ discovery / funnel
    if d["pool"]:
        ns = {s: R.equal_split_reads(pool[s]["N"]) for s in STRATA}
        L += ["## Discovery and funnel", "",
              "Zero-count bound for the planned reads (assumes no uncertain or unknown rows): "
              f"{R.zero_bound({s: pool[s]['N'] for s in STRATA}, ns):.1f}; reads needed per stratum (equal split): " +
              ", ".join(f"{s} {n(f'need_{s}', ns[s])}" for s in STRATA) + ".", ""]
        L += ["| stratum | candidates | truncated leaves | incomplete leaves | unread hits | excluded | read | member "
              "| no-agent-lib | no-ci-tests | uncertain | yes (recording / text) | unknown | no |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in STRATA:
            v = st[s]
            L.append(f"| {s} | {pool[s]['candidates']} | {pool[s]['truncated_leaves']} | {pool[s]['incomplete_leaves']}"
                     f" | {pool[s]['missing']} | {n(f'excl_{s}', v['excluded'])} | {v['read']} | "
                     f"{n(f'member_{s}', v['member'])} | {n(f'nolib_{s}', v['no_agent_lib'])} | "
                     f"{n(f'noci_{s}', v['no_ci_tests'])} | {n(f'unc_{s}', v['uncertain'])} | {n(f'yes_{s}', v['yes'])} "
                     f"({v['yes_recording']} / {v['yes_text']}) | {n(f'unk_{s}', v['unknown'])} | {n(f'no_{s}', v['no'])} |")
        L.append("")
        capped = sorted({q for s in STRATA for q in pool[s]["capped_queries"]})
        if capped:
            L += ["capped-query (first 1,000 read, rest added to N_s): " + "; ".join(f"`{q}`" for q in capped), ""]
    # ------------------------------------------------------------ chunk statistics
    if x["counted"]:
        req = [r.get("requests") or 0 for r in x["counted"]]
        tc = [len(m["candidates"]) for m in x["members"] if m["pain"]["kind"] != "recording"]
        first = sorted(r["at"] for r in d["reads"] if r.get("reader") == "first" and r.get("at"))
        rate = "-"
        if len(first) > 1:
            import datetime as dt
            h = (dt.datetime.fromisoformat(first[-1]) - dt.datetime.fromisoformat(first[0])).total_seconds() / 3600
            rate = f"{len(first) / h:.1f}" if h > 0 else "-"
        L += ["## Reading statistics", "", f"- requests per candidate: {_q(req)}",
              f"- text candidates per member without a recording: {_q(tc)}", f"- texts first-read per hour: {rate}",
              f"- search requests per member observed: {_q([len(s['queries']) for s in d['search']])}",
              f"- X-RateLimit-Remaining observed (last chunk): "
              f"{(d['chunks'][-1].get('remaining') if d['chunks'] else '-')}", ""]
        unk = {}
        for m in x["members"]:
            for w in m["pain"]["why"]:
                unk[w] = unk.get(w, 0) + 1
        if unk:
            L += ["Pain unknown reasons (a member can have several): " +
                  ", ".join(f"{k} {v}" for k, v in sorted(unk.items())), ""]
    # ------------------------------------------------------------ per library
    if x["members"]:
        L += ["## Per agent library", "", "| library | members | runtime | dev/test | optional/extras | pain yes | "
              "pain unknown |", "|---|---|---|---|---|---|---|"]
        libs = sorted({l["lib"] for m in x["members"] for l in m["row"]["libs"]["libraries"]})
        for lib in libs:
            ms = [m for m in x["members"] if any(l["lib"] == lib for l in m["row"]["libs"]["libraries"])]
            kinds = {k: sum(1 for m in ms if any(l["lib"] == lib and l["kind"] == k
                                                for l in m["row"]["libs"]["libraries"]))
                     for k in (R.RUNTIME, R.DEV, R.OPTIONAL)}
            L.append(f"| {lib} | {len(ms)} | {kinds[R.RUNTIME]} | {kinds[R.DEV]} | {kinds[R.OPTIONAL]} | "
                     f"{sum(1 for m in ms if m['pain']['pain'] == 'yes')} | "
                     f"{sum(1 for m in ms if m['pain']['pain'] == 'unknown')} |")
        L.append(f"| (total, each repository once) | {len(x['members'])} | | | | {c['yes']} | "
                 f"{sum(1 for m in x['members'] if m['pain']['pain'] == 'unknown')} |")
        L.append("")
        reasons = {}
        for m in x["yes"]:
            if m["pain"]["kind"] == "text":
                k = m["pain"]["evidence"].get("reason") or "-"
                reasons[k] = reasons.get(k, 0) + 1
        L += ["Pain yes by kind: recording " + str(sum(1 for m in x["yes"] if m["pain"]["kind"] == "recording")) +
              ", text " + str(sum(1 for m in x["yes"] if m["pain"]["kind"] == "text")) + " (" +
              ", ".join(f"{k} {v}" for k, v in sorted(reasons.items())) + ").", ""]
    # ------------------------------------------------------------ per model term
    if x["counted"]:
        L += ["## Candidates and non-members per S2/S3 model term", "", "| model term | candidates | read | "
              "non-members |", "|---|---|---|---|"]
        byidx = {r["idx"]: r for r in x["rows"]}
        for mt in R.MODEL_TERMS:
            ids = [i for i, cd in x["cands"].items() if any(
                h.get("stratum") in ("S2", "S3") and f" {mt} test" in h["query"] for h in cd.get("hits") or [])]
            rd = [byidx[i] for i in ids if i in byidx and byidx[i].get("cls") != "excluded"]
            L.append(f"| {mt} | {len(ids)} | {len(rd)} | {sum(1 for r in rd if r.get('cls') == 'non-member')} |")
        L.append("")
    # ------------------------------------------------------------ pain list
    if x["yes"]:
        L += ["## Pain list", "", "| repository | libraries | kind | date | quote or file | URL |",
              "|---|---|---|---|---|---|"]
        for m in sorted(x["yes"], key=lambda m: m["row"]["repo"].lower()):
            ev = m["pain"]["evidence"]
            libs = ", ".join(sorted({l["lib"] for l in m["row"]["libs"]["libraries"]}))
            if m["pain"]["kind"] == "recording":
                L.append(f"| {m['row']['html_url']} | {libs} | recording ({ev['rule']}) | {(ev.get('date') or '')[:10]}"
                         f" | `{ev['path']}` | {ev['url']} |")
            else:
                L.append(f"| {m['row']['html_url']} | {libs} | text ({ev.get('reason')}) | "
                         f"{(ev.get('created_at') or '')[:10]} | {_esc(ev.get('quote'))} | {ev['url']} |")
        L.append("")
    # ------------------------------------------------------------ reads
    if d["reads"]:
        firsts = [r for r in x["reads"].values() if "first" in r]
        seconds = [r for r in x["reads"].values() if "second" in r and "first" in r]
        flips = sum(1 for r in seconds if r["first"]["label"] == "rejected" and r["second"]["label"] == "confirmed")
        L += ["## Hand reads", "",
              f"first reads {n('first_reads', len(firsts))} (confirmed "
              f"{sum(1 for r in firsts if r['first']['label'] == 'confirmed')}, unclear "
              f"{sum(1 for r in firsts if r['first']['label'] == 'unclear')}, rejected "
              f"{sum(1 for r in firsts if r['first']['label'] == 'rejected')}); second reads {len(seconds)}; both "
              f"confirmed {sum(1 for r in seconds if r['first']['label'] == r['second']['label'] == 'confirmed')}; "
              f"confirmed first read not confirmed by the second "
              f"{sum(1 for r in seconds if r['first']['label'] == 'confirmed' and r['second']['label'] != 'confirmed')}"
              f"; rejected first read labelled confirmed by the second {flips}.", ""]
    # ------------------------------------------------------------ hand check
    hc = x["handcheck"]
    L += ["## Hand check (AC4)", "", f"required yes checks {hc['required']}, missing {len(hc['missing'])}, failed "
          f"{len(hc['failed'])}{' (' + ', '.join(hc['failed']) + ')' if hc['failed'] else ''}; samples (10 non-members, "
          f"10 members with pain no, every recording package hit) done: {'yes' if hc['samples_done'] else 'no'}.", ""]
    for k, v in sorted(((d["handcheck"] or {}).get("samples") or {}).items()):
        L.append(f"- sample `{k}`: {v}")
    if (d["handcheck"] or {}).get("samples"):
        L.append("")
    # ------------------------------------------------------------ information
    info = []
    mk = sorted({(m["row"]["repo"], z["marker"]) for m in x["members"] for z in m["row"]["libs"].get("markers") or []})
    if mk:
        info.append("marker findings in fetched manifests (information, not pain): " +
                    "; ".join(f"{r}: `{k}`" for r, k in mk))
    ex = [r for r in x["excluded"] if any(h.get("stratum") for h in (x["cands"].get(r["idx"]) or {}).get("hits") or [])]
    if ex:
        info.append("excluded candidates with discovery hits (pain not read): " +
                    ", ".join(f"{r['repo']} ({'/'.join(r.get('excluded') or [])})" for r in ex[:200]))
    gt = sorted({(m["row"]["repo"], t) for m in x["members"] for t in m["row"]["libs"].get("general_tools") or []
                 if m["pain"]["kind"] != "recording"})
    if gt:
        info.append("general recording tools in members without a model-host recording: " +
                    "; ".join(f"{r}: {t}" for r, t in gt))
    if d["population"]:
        info.append("population (file hits, not repositories; information only): " +
                    ", ".join(f"`{k}` {v.get('total_count')}" for k, v in sorted(d["population"].items())))
    if info:
        L += ["## Information", ""] + [f"- {i}" for i in info] + [""]
    L += ["## Limits", "", "Default branches only for files; search coverage limited to the listed queries (1,000 "
          "results per leaf, best-match order on capped queries); truncated leaves are counted in N_s; texts are the "
          f"first {R.TEXT_SEARCH_CAP} results of each repository search; comments fetched for the first "
          f"{R.COMMENT_CAP} non-candidate hits.", ""]
    return "\n".join(L), n.vals


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")[:200]


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    text, _ = render(load())
    if "--print" in argv:
        print(text)
    else:
        (HERE / "REPORT.md").write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
