#!/usr/bin/env python3
"""Data requests (session route): §0 probe, §1 listing and frame, §2.1 fix material.

  fetch.py probe                      raw JSON of the two §0 calls into probe/; starts the 48 h budget clock
  fetch.py list                       every page per ecosystem into data/listing/<eco>.jsonl.gz, then build_frame
  fetch.py frame                      rebuild data/frame.jsonl.gz and data/order.json from the committed listing
  fetch.py material START COUNT       material for reading positions [START, START+COUNT) into data/material/
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghapi  # noqa: E402
import rules as R  # noqa: E402

DATA = HERE / "data"
FIRST_DAY = "2024-01-01"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_jsonl_gz(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


# ---------------------------------------------------------------- probe

def probe(route: str = "session") -> None:
    out = HERE / "probe"
    out.mkdir(exist_ok=True)
    budget = DATA / "budget.json"
    if route == "session" and not budget.exists():
        DATA.mkdir(exist_ok=True)
        budget.write_text(json.dumps({"first_data_request": now(), "budget_hours": 48}, indent=1) + "\n")
    calls = [
        ("advisories", "/advisories", {"type": "reviewed", "ecosystem": "npm", "published": "2024-01-01..2024-01-31",
                                       "per_page": "5"}),
        ("commits", "/repos/expressjs/express/commits", {"per_page": "1"}),
    ]
    for name, path, params in calls:
        status, headers, body = ghapi.get(path, params)
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = body
        keep = {k: v for k, v in headers.items() if k.startswith("x-ratelimit") or k in ("link", "content-type")}
        (out / f"{route}-{name}.json").write_text(json.dumps(
            {"route": route, "path": path, "params": params, "status": status, "headers": keep, "t": now(),
             "body": parsed}, indent=1) + "\n")
        print(name, status)


# ---------------------------------------------------------------- listing

def list_all(build: bool = True) -> None:
    list_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    meta = {"list_started": now(), "list_date": list_date, "published": f"{FIRST_DAY}..{list_date}", "pages": {}}
    for eco in R.ECOSYSTEMS:
        params = {"type": "reviewed", "is_withdrawn": "false", "ecosystem": eco,
                  "published": f"{FIRST_DAY}..{list_date}", "per_page": "100"}
        rows, path, pages = [], "/advisories", 0
        while path:
            data, headers = ghapi.get_json(path, params)
            rows.extend(data)
            pages += 1
            path, params = ghapi.next_link(headers.get("link")), None
        write_jsonl_gz(DATA / "listing" / f"{eco}.jsonl.gz", rows)
        meta["pages"][eco] = {"pages": pages, "rows": len(rows)}
        print(eco, pages, len(rows), flush=True)
    meta["list_finished"] = now()
    (DATA / "listing_meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    if build:
        build_frame()


def load_listing() -> dict[str, list[dict]]:
    return {eco: read_jsonl(DATA / "listing" / f"{eco}.jsonl.gz") for eco in R.ECOSYSTEMS}


def frame_rows(pages: dict[str, list[dict]]) -> list[dict]:
    out = []
    for adv in R.merge_listing(pages):
        m = R.memberships(adv)
        out.append({
            "ghsa_id": adv["ghsa_id"], "ecosystems": adv["ecosystems"], "severity": adv.get("severity"),
            "cwes": R.cwe_ids(adv), "published_at": adv.get("published_at"),
            "packages": sorted({(v.get("package") or {}).get("name") or "" for v in adv.get("vulnerabilities") or []}),
            "source_code_location": adv.get("source_code_location"),
            "member_a": m["a"], "member_b": m["b"], "member_c": m["c"], "route": R.route(adv),
        })
    return out


def build_frame() -> None:
    frame = frame_rows(load_listing())
    write_jsonl_gz(DATA / "frame.jsonl.gz", frame)
    order = R.reading_order([r["ghsa_id"] for r in frame if r["route"]])
    (DATA / "order.json").write_text(json.dumps(order) + "\n")
    print("frame", len(frame), "candidates", len(order))


# ---------------------------------------------------------------- material

def advisories_by_id() -> dict[str, dict]:
    out = {}
    for advs in load_listing().values():
        for a in advs:
            out.setdefault(a["ghsa_id"], a)
    return out


def fetch_ref(ref: dict) -> dict:
    o, r = ref["owner"], ref["repo"]
    fx = {"ref": ref, "commits": []}
    try:
        if ref["kind"] == "commit":
            c, _ = ghapi.get_json(f"/repos/{o}/{r}/commits/{ref['sha']}")
            fx["commits"].append(commit_material(c))
        elif ref["kind"] == "pull":
            p, _ = ghapi.get_json(f"/repos/{o}/{r}/pulls/{ref['number']}")
            fx["title"], fx["body"] = p.get("title"), (p.get("body") or "")[:20000]
            fx["merged"] = bool(p.get("merged_at"))
            if p.get("merged_at") and p.get("merge_commit_sha"):
                c, _ = ghapi.get_json(f"/repos/{o}/{r}/commits/{p['merge_commit_sha']}")
                fx["commits"].append(commit_material(c))
        else:
            c, _ = ghapi.get_json(f"/repos/{o}/{r}/compare/{ref['range']}")
            fx["message"] = "\n\n".join((x.get("commit") or {}).get("message", "") for x in c.get("commits") or [])
            fx["commits"].append({"sha": None, "message": None, "files": R.cap_files(c.get("files"))})
        fx["status"] = 200
    except ghapi.HTTPError as e:
        fx["status"] = e.status
    return fx


def commit_material(c: dict) -> dict:
    return {"sha": c.get("sha"), "message": (c.get("commit") or {}).get("message"), "files": R.cap_files(c.get("files"))}


def material_for(adv: dict) -> dict:
    refs = R.fix_refs(adv)
    return {
        "ghsa_id": adv["ghsa_id"], "summary": adv.get("summary"), "description": adv.get("description"),
        "cwes": [{"cwe_id": c.get("cwe_id"), "name": c.get("name")} for c in adv.get("cwes") or []],
        "references": [x if isinstance(x, str) else x.get("url") for x in adv.get("references") or []],
        "severity": adv.get("severity"), "source_code_location": adv.get("source_code_location"),
        "packages": [{"ecosystem": (v.get("package") or {}).get("ecosystem"), "name": (v.get("package") or {}).get("name")}
                     for v in adv.get("vulnerabilities") or []],
        "fixes": [fetch_ref(ref) for ref in refs], "fetched_at": now(),
    }


def material(start: int, count: int, order: list[str] | None = None) -> None:
    order = order if order is not None else json.loads((DATA / "order.json").read_text())
    advs = advisories_by_id()
    rows = []
    for i in range(start, min(start + count, len(order))):
        rows.append(dict(material_for(advs[order[i]]), pos=i))
        print(i, order[i], [f["status"] for f in rows[-1]["fixes"]], flush=True)
    write_jsonl_gz(DATA / "material" / f"m{start:05d}.jsonl.gz", rows)


def load_material() -> dict[str, dict]:
    out = {}
    for p in sorted((DATA / "material").glob("m*.jsonl.gz")):
        for r in read_jsonl(p):
            out[r["ghsa_id"]] = r
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "probe":
        probe()
    elif cmd == "list":
        list_all()
    elif cmd == "frame":
        build_frame()
    elif cmd == "material":
        material(int(sys.argv[2]), int(sys.argv[3]))
    else:
        sys.exit(__doc__)
