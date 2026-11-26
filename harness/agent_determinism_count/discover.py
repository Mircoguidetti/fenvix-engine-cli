#!/usr/bin/env python3
"""§1 discovery: pre-pass, bisection (code search by size, issues/commits search by date), candidate build.

Usage: discover.py prepass --family code|text [--route session|workflow]
       discover.py run --family code|text [--route ...] [--max-minutes N] [--deadline ISO]
       discover.py population [--route ...]          (information only: file hits per agent library)
       discover.py build                              (candidates.jsonl.gz, orders.json, pool.json from the leaves)

Families run in parallel (separate rate limits): ``code`` (stratum S1, search/code, <= 9/min) and ``text``
(S2 search/issues and S3 search/commits, <= 25/min together). Resumable: results/discovery_state_<family>.json.
A node with total_count > 1,000 and a splittable range is bisected (parent); a leaf reads every page up to 1,000
results; an incomplete leaf is retried 3 times (largest total_count kept), else ``incomplete``. A query whose pre-pass
total_count exceeds QUERY_CAP is not bisected: its first 1,000 results are read (``capped-query``).
Bisection is the db-serial-count 8150aa1 discover.py scheme (copied), extended to date ranges.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import parts as PT  # noqa: E402
import rules as R  # noqa: E402

RES = HERE / "results"
DISC = RES / "discovery"
ENDPOINT = {"code": "code", "issues": "issues", "commits": "commits"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _json(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def _save(p: Path, d) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    tmp.replace(p)


def probe_config() -> dict:
    return _json(RES / "probe_decisions.json", {}) or {}


def launch_date() -> str:
    """LAUNCH: the UTC date of the first discovery request, written once (results/launch.json)."""
    p = RES / "launch.json"
    d = _json(p)
    if d is None:
        d = {"launch": dt.datetime.now(dt.timezone.utc).date().isoformat(), "at": now()}
        _save(p, d)
    return d["launch"]


def family_queries(family: str, cfg: dict) -> list[dict]:
    fams = ("code",) if family == "code" else ("issues",) + (("commits",) if cfg.get("commits_route", True)
                                                              else ())
    return [d for d in R.discovery_queries(cfg) if d["family"] in fams]


def root_range(d: dict, launch: str):
    return (0, R.SIZE_MAX) if d["family"] == "code" else (R.HISTORY_START, launch)


def split(d: dict, a, b):
    """Children of a splittable node, or None (single size or single day)."""
    if d["family"] == "code":
        if a >= b:
            return None
        m = (a + b) // 2
        return [[a, m], [m + 1, b]]
    da, db = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    if da >= db:
        return None
    m = da + dt.timedelta(days=(db - da).days // 2)
    return [[a, m.isoformat()], [(m + dt.timedelta(days=1)).isoformat(), b]]


def _trim_items(family: str, items: list) -> list:
    import pipeline as P
    if family == "code":
        return [{"repo": (x.get("repository") or {}).get("full_name"), "path": x.get("path"),
                 "url": x.get("html_url")} for x in items]
    return [P.trim_search_item(x, family) for x in items]


def fetch(c, d: dict, a, b, page: int, ranged: bool = True):
    q = R.ranged_query(d, a, b) if ranged else d["q"]
    path = f"search/{ENDPOINT[d['family']]}?" + urllib.parse.urlencode({"q": q, "per_page": 100, "page": page})
    kind = "code" if d["family"] == "code" else "issues"
    st, data = 0, None
    for _ in range(2):
        st, data, _ = c.get(path, search=kind)
        if st == 200 and isinstance(data, dict):
            return st, data
        sys.stderr.write(f"search HTTP {st} on {path[:160]}: {json.dumps(data)[:200]}\n")
        time.sleep(30)
    return st, data if isinstance(data, dict) else {"error": data}


def read_leaf(c, d: dict, a, b, first: dict, pages_max: int = 10) -> dict:
    """Read a leaf from its first page: retries while incomplete, then every page up to 1,000 results."""
    best, last, max_tc, tries = first, first, first.get("total_count") or 0, 0
    while last.get("incomplete_results") and tries < 3:
        tries += 1
        st2, d2 = fetch(c, d, a, b, 1)
        if st2 != 200:
            continue
        last = d2
        max_tc = max(max_tc, d2.get("total_count") or 0)
        if len(d2.get("items", [])) >= len(best.get("items", [])) or not d2.get("incomplete_results"):
            best = d2
    items = _trim_items(d["family"], best.get("items", []))
    incomplete = bool(last.get("incomplete_results"))
    errors = []
    for p in range(2, min(math.ceil(min(max_tc, 1000) / 100), pages_max) + 1):
        stp, dp = fetch(c, d, a, b, p)
        pt = 0
        while stp == 200 and dp.get("incomplete_results") and pt < 3:
            pt += 1
            stp, dp = fetch(c, d, a, b, p)
        if stp != 200:
            incomplete = True
            errors.append({"page": p, "status": stp})
            continue
        incomplete = incomplete or bool(dp.get("incomplete_results"))
        got = dp.get("items", [])
        items += _trim_items(d["family"], got)
        if not got:
            break
    return {"total_count": max_tc, "retries": tries, "read": len(items), "items": items, "incomplete": incomplete,
            "page_errors": errors, "truncated": max_tc > len(items) or incomplete}


def _client(route: str):
    import ghapi
    return ghapi.Client(use_gh=True) if route == "session" else ghapi.from_env()


# ---------------------------------------------------------------------------------------------- pre-pass

def prepass(family: str, route: str) -> int:
    RES.mkdir(exist_ok=True)
    cfg = probe_config()
    c = _client(route)
    launch = launch_date()
    p = RES / f"prepass_{family}.json"
    pp = _json(p, {})
    for d in family_queries(family, cfg):
        if d["key"] in pp:
            continue
        a, b = root_range(d, launch)
        st, data = fetch(c, d, a, b, 1)
        pp[d["key"]] = {"family": d["family"], "stratum": d["stratum"], "status": st, "at": now(),
                        "total_count": data.get("total_count"), "incomplete": data.get("incomplete_results"),
                        "route": route, "search_429": c.n_429,
                        "rate": {"limit": c.limit.get("search") or c.limit.get("code_search"),
                                 "remaining": c.remaining.get("search", c.remaining.get("code_search"))}}
        _save(p, pp)
        print(f"{now()} prepass {d['key']}: {st} tc={data.get('total_count')}", flush=True)
    return 0


def projection(prepass_all: dict) -> dict:
    """Per family: projected requests and hours (requests / rate); queries above QUERY_CAP read 10 pages."""
    out = {"code": {"requests": 0, "queries": 0, "capped": 0}, "text": {"requests": 0, "queries": 0, "capped": 0}}
    for k, v in prepass_all.items():
        fam = "code" if v["family"] == "code" else "text"
        tc = v.get("total_count") or 0
        out[fam]["requests"] += R.projected_requests(tc)
        out[fam]["queries"] += 1
        out[fam]["capped"] += tc > R.QUERY_CAP
    out["code"]["hours"] = out["code"]["requests"] / R.CODE_PER_MIN / 60
    out["text"]["hours"] = out["text"]["requests"] / R.TEXT_PER_MIN / 60
    out["hours"] = max(out["code"]["hours"], out["text"]["hours"])
    out["stop"] = out["hours"] > R.PREPASS_MAX_H
    return out


def load_prepass() -> dict:
    return {**_json(RES / "prepass_code.json", {}), **_json(RES / "prepass_text.json", {})}


# ---------------------------------------------------------------------------------------------- bisection

EXT = "s3ext"  # founder's S3 extension (2026-11-26 11:25Z): its own state, splits and leaf parts
EXT_HOURS = 6.0


def run(family: str, route: str, max_minutes: float, deadline: str | None, ext: bool = False) -> int:
    """``ext``: the founder's one S3 extension (session route, 2026-11-26): only the S3 queries the 24 h budget left
    unstarted or unfinished, with unchanged rules, shapes and caps, until 6 h after its own first request; its state,
    splits and leaves are kept apart (discovery_state_s3ext.json, splits_s3ext.jsonl, leaves_s3ext/) so the text
    workflow's commits never overwrite them; the build merges them."""
    DISC.mkdir(parents=True, exist_ok=True)
    files = EXT if ext else family
    cfg = probe_config()
    pp = load_prepass()
    proj = projection(pp)
    if proj[family]["hours"] > R.PREPASS_MAX_H and not (RES / f"prepass_stop_lifted_{family}.json").exists():
        st0 = _json(RES / f"discovery_state_{family}.json", {}) or {}
        st0["prepass_stop"] = {"hours": proj[family]["hours"], "at": now()}
        _save(RES / f"discovery_state_{family}.json", st0)
        print(f"pre-pass stop: projected {family} discovery {proj[family]['hours']:.1f} h > {R.PREPASS_MAX_H} h")
        return 3
    launch = launch_date()
    sp = RES / f"discovery_state_{files}.json"
    if ext and not sp.exists():
        base = _json(RES / "discovery_state_text.json", {}) or {}
        todo = {k: v for k, v in (base.get("queries") or {}).items() if not v.get("done")}
        _save(sp, {"started": now(), "finished": None, "queries": todo,
                   "extension": {"decided": "founder, main-eng-review-adc-s3-extension-20261126-112500.md "
                                            "(coordinator 2026-11-26 11:18Z)", "route": route, "hours": EXT_HOURS,
                                 "first_request": None, "hard_stop": None,
                                 "resumed_from_text_state": sorted(todo)}})
    st = _json(sp, {"started": now(), "finished": None, "queries": {}})
    st.setdefault("started", now())
    st.setdefault("queries", {})
    # each family's own 24 h discovery budget runs from its own first request (coordinator, D1 = A)
    first = (_json(RES / f"prepass_{family}.json", {}) or {}).values()
    t_first = min([v["at"] for v in first if v.get("at")] + [st["started"]])
    budget_end = (dt.datetime.fromisoformat(t_first) + dt.timedelta(hours=R.DISCOVERY_BUDGET_H)).isoformat(
        timespec="seconds")
    st["budget_end"] = budget_end
    if ext:
        xe = st["extension"]
        if not xe.get("first_request"):
            xe["first_request"] = now()
            xe["hard_stop"] = (dt.datetime.fromisoformat(xe["first_request"]) + dt.timedelta(hours=EXT_HOURS)
                               ).isoformat(timespec="seconds")
            _save(sp, st)
        budget_end = xe["hard_stop"]
    deadline = min(deadline, budget_end) if deadline else budget_end
    c = _client(route)
    t0 = time.time()
    text_done = {k for k, v in ((_json(RES / "discovery_state_text.json", {}) or {}).get("queries") or {}).items()
                 if v.get("done")} if ext else set()
    for d in family_queries(family, cfg):
        if ext and (d["stratum"] != "S3" or d["key"] in text_done):
            continue
        if d["key"] not in pp:
            sys.exit(f"no pre-pass total for {d['key']}")
        tc0 = pp[d["key"]].get("total_count") or 0
        a0, b0 = root_range(d, launch)
        if d["key"] not in st["queries"]:
            capped = tc0 > R.QUERY_CAP
            kids = split(d, a0, b0) if tc0 > 1000 and not capped else None
            st["queries"][d["key"]] = {"stack": kids or [[a0, b0]], "done": False, "capped": capped,
                                       "prepass_total": tc0, "nodes": 0, "leaves": 0, "leaf_total": 0}
        qs = st["queries"][d["key"]]
        while qs["stack"]:
            if now() >= budget_end:
                st["budget_reached"] = now()
                if ext:
                    st["extension"]["stopped_at_hard_stop"] = now()
                _save(sp, st)
                print("family discovery budget (24 h) reached: unfinished queries enter N_s as truncated leaves")
                return 0
            if (time.time() - t0) / 60 > max_minutes or (deadline and now() >= deadline):
                _save(sp, st)
                print(f"stopping (time limit / deadline); resumable from {sp.name}")
                return 0
            a, b = qs["stack"][0]
            s1, first = fetch(c, d, a, b, 1)
            rec = {"query": d["key"], "family": d["family"], "stratum": d["stratum"], "a": a, "b": b, "status": s1,
                   "total_count": first.get("total_count"), "incomplete_results": first.get("incomplete_results"),
                   "at": now(), "route": route}
            # coordinator 09:30Z (route switch): a session-route answer below the workflow route's pre-pass answer
            # for the same root range stops discovery for a report
            if route == "session" and s1 == 200 and [a, b] == [a0, b0] \
                    and (first.get("total_count") or 0) < tc0:
                st["route_check"] = {"query": d["key"], "session": first.get("total_count"), "workflow": tc0,
                                     "at": now()}
                _save(sp, st)
                print(f"route check: {d['key']} session {first.get('total_count')} < workflow pre-pass {tc0}")
                return 4
            kids = None
            if s1 != 200:
                rec.update(leaf=True, error=True, read=0, truncated=True, incomplete=True, items=[])
            else:
                tc = first.get("total_count") or 0
                kids = split(d, a, b) if tc > 1000 and not qs["capped"] else None
                if kids:
                    rec["leaf"] = False
                else:
                    rec.update(leaf=True, capped_query=qs["capped"], **read_leaf(c, d, a, b, first))
            qs["stack"].pop(0)
            if kids:
                qs["stack"] = kids + qs["stack"]
            else:
                PT.part_path(files, DISC).parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(PT.part_path(files, DISC), "at") as f:
                    f.write(json.dumps(rec, sort_keys=True) + "\n")
                qs["leaves"] += 1
                qs["leaf_total"] += rec.get("total_count") or 0
            with open(DISC / f"splits_{files}.jsonl", "a") as f:
                f.write(json.dumps({k: v for k, v in rec.items() if k != "items"}, sort_keys=True) + "\n")
            qs["nodes"] += 1
            st["search_requests"] = c.n_search
            st["search_stats"] = {"429": c.n_429, "limit": c.limit.get("search") or c.limit.get("code_search"),
                                  "remaining": c.remaining.get("search", c.remaining.get("code_search")),
                                  "reset": c.reset.get("search", c.reset.get("code_search"))}
            _save(sp, st)
            print(f"{now()} {d['key'][:70]:<70} {a}..{b} tc={rec['total_count']} leaf={rec['leaf']} "
                  f"read={rec.get('read', '-')} inc={rec.get('incomplete', '-')}", flush=True)
        qs["done"] = True
        _save(sp, st)
    st["finished"] = st["finished"] or now()
    _save(sp, st)
    print(f"discovery {files} finished")
    return 0


# ---------------------------------------------------------------------------------------------- population (info)

def population(route: str) -> int:
    names = sorted(R.PY_EXACT) + ["langchain-", "langgraph-", "llama-index-"] + sorted(R.NPM_EXACT - {"langchain"}) \
        + ["@langchain/", "@ai-sdk/", "@llamaindex/"]
    c = _client(route)
    p = RES / "population.json"
    out = _json(p, {})
    for n in names:
        for fn in R.PKG_FILES:
            k = f"{n.rstrip('-/')} {fn}"
            if k in out:
                continue
            path = "search/code?" + urllib.parse.urlencode({"q": k, "per_page": 1})
            st, d, _ = c.get(path, search="code")
            out[k] = {"status": st, "total_count": (d or {}).get("total_count") if isinstance(d, dict) else None}
            _save(p, out)
    return 0


# ---------------------------------------------------------------------------------------------- build

def _leaf_lines():
    """(file number, line number, record) of every readable leaf line, file by file (streamed)."""
    files = []
    for fam in ("code", "text", EXT):
        # the leaf files are outside git (parts.py; ``parts.py fetch`` first); the single pre-parts file if present
        legacy = DISC / f"leaves_{fam}.jsonl.gz"
        files += ([legacy] if legacy.exists() else []) + PT.part_files(fam, DISC)
    for fi, p in enumerate(files):
        try:
            with gzip.open(p, "rt") as f:
                for li, x in enumerate(f):
                    try:
                        yield fi, li, json.loads(x)
                    except json.JSONDecodeError:  # a line cut by a stopped job
                        pass
        except (EOFError, OSError):  # a gzip member cut by a cancelled job: the lines before it are kept
            pass


def _leaf_key(r: dict) -> tuple:
    return r["query"], str(r["a"]), str(r["b"])


def iter_leaves():
    """The last record per (query, a, b) (a leaf re-run after an interruption), streamed in two passes so that memory
    holds keys, not the ~1.2 GB of leaf bodies (2026-11-26 build)."""
    last = {}
    for fi, li, r in _leaf_lines():
        last[_leaf_key(r)] = (fi, li)
    for fi, li, r in _leaf_lines():
        if last.get(_leaf_key(r)) == (fi, li):
            yield r


def read_leaves() -> list[dict]:
    return list(iter_leaves())


STRATA = ("S1", "S2", "S3")


def build(leaves, states: dict, prepass_all: dict) -> tuple[list[dict], dict, dict]:
    """``leaves`` may be any iterable (one pass). Hits keep the order of the leaves sorted by (stratum, query, a, b),
    then item order, and the first hit per (url, query)."""
    cand: dict[str, dict] = {}
    pool = {s: {"candidates": 0, "missing": 0, "truncated_leaves": 0, "incomplete_leaves": 0,
                "capped_queries": [], "unfinished": []} for s in STRATA}
    for lf in leaves:
        p = pool[lf["stratum"]]
        if lf.get("truncated"):
            p["truncated_leaves"] += 1
            p["missing"] += max(0, (lf.get("total_count") or 0) - (lf.get("read") or 0))
        if lf.get("incomplete"):
            p["incomplete_leaves"] += 1
        if lf.get("capped_query"):
            p["capped_queries"].append(lf["query"])
        si = STRATA.index(lf["stratum"])
        for pos, it in enumerate(lf.get("items") or []):
            repo = it.get("repo")
            if not repo:
                continue
            k = repo.lower()
            row = cand.setdefault(k, {"repo": repo, "html_url": f"https://github.com/{repo}", "stratum": lf["stratum"],
                                      "hits": []})
            if si < STRATA.index(row["stratum"]):
                row["stratum"] = lf["stratum"]
            row["hits"].append(((si, lf["query"], str(lf["a"]), str(lf["b"]), pos),
                                {"stratum": lf["stratum"], "query": lf["query"],
                                 **{x: v for x, v in it.items() if x != "repo"}}))
    for row in cand.values():
        hits, seen = [], set()
        for _, h in sorted(row["hits"], key=lambda t: t[0]):
            if (h.get("url"), h["query"]) not in seen:
                seen.add((h.get("url"), h["query"]))
                hits.append(h)
        row["hits"] = hits
    rows = sorted(cand.values(), key=lambda r: r["html_url"])
    for i, r in enumerate(rows):
        r["idx"] = i
    orders = {s: [r["idx"] for r in R.stratum_order([r for r in rows if r["stratum"] == s])] for s in STRATA}
    for s in STRATA:
        pool[s]["candidates"] = len(orders[s])
    # gate note 3: unfinished queries and leaves enter N_s as truncated leaves with their pre-pass total_count
    for fam, st in states.items():
        qsd = (st or {}).get("queries") or {}
        for key, v in prepass_all.items():
            fam_of = "code" if v["family"] == "code" else "text"
            if fam_of != fam:
                continue
            q = qsd.get(key)
            if q and q.get("done"):
                continue
            rest = max(0, (v.get("total_count") or 0) - ((q or {}).get("leaf_total") or 0))
            p = pool[v["stratum"]]
            p["unfinished"].append({"query": key, "missing": rest})
            p["missing"] += rest
            p["truncated_leaves"] += 1
    for s in STRATA:
        pool[s]["N"] = pool[s]["candidates"] + pool[s]["missing"]
        pool[s]["capped_queries"] = sorted(set(pool[s]["capped_queries"]))
    return rows, orders, pool


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepass", "run", "population", "build"])
    ap.add_argument("--family", choices=["code", "text"])
    ap.add_argument("--route", default="session")
    ap.add_argument("--max-minutes", type=float, default=24 * 60)
    ap.add_argument("--deadline")
    ap.add_argument("--extension", action="store_true", help="the founder's S3 extension (text family, session)")
    a = ap.parse_args(argv)
    if a.cmd == "prepass":
        return prepass(a.family, a.route)
    if a.cmd == "run":
        return run(a.family, a.route, a.max_minutes, a.deadline, a.extension)
    if a.cmd == "population":
        return population(a.route)
    states = {f: _json(RES / f"discovery_state_{f}.json", {}) for f in ("code", "text")}
    xs = _json(RES / f"discovery_state_{EXT}.json", None)
    if xs and states["text"]:  # the S3 extension's queries replace their unfinished text entries
        states["text"] = {**states["text"], "queries": {**states["text"].get("queries", {}), **xs["queries"]}}
    rows, orders, pool = build(iter_leaves(), states, load_prepass())
    with gzip.open(RES / "candidates.jsonl.gz", "wt") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    _save(RES / "orders.json", orders)
    _save(RES / "pool.json", pool)
    # candidates.jsonl.gz (issue/commit bodies) stays out of git like the leaves: its index is committed and the file
    # travels in this run's results artifact (parts.fetch_candidates)
    import shutil
    (RES / "build_out").mkdir(exist_ok=True)
    shutil.copyfile(RES / "candidates.jsonl.gz", RES / "build_out" / "candidates.jsonl.gz")  # this run's upload
    _save(RES / "candidates_index.json", {**PT.file_facts(RES / "candidates.jsonl.gz"), "run_id": PT.run_id(),
                                          "artifact": f"agent-determinism-count-candidates-{PT.run_id()}",
                                          "artifact_path": "candidates.jsonl.gz", "at": now()})
    import resource
    print(f"build peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB")
    print(json.dumps({s: {k: v for k, v in pool[s].items() if k not in ("unfinished",)} for s in STRATA},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
