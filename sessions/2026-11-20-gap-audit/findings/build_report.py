#!/usr/bin/env python3
"""Build sessions/2026-11-20-gap-audit/REPORT.md from the per-agent findings.

Steps: load every findings/*.gaps.jsonl, normalize, split process gaps (area "Process / ..." or with a prompt field
from the PROC agents) from product gaps, remove cross-agent duplicates (same claim found by two agents: token Jaccard
on the 'missing' text), sort by severity, number G-001.. and P-001.., and render Markdown with the matrix files,
the lead's verification log and the could-not-check sections. Writes /home/user/audit/out/REPORT.md and
/home/user/audit/out/gaps.jsonl (the numbered list, machine-readable) and ids-map.tsv (source id -> G/P id).
"""
import glob
import json
import os
import re
import sys

F = "/home/user/audit/findings"
OUT = "/home/user/audit/out"
SEV = ["WRONG-RESULT", "BLOCKS-USE", "DEGRADES", "MINOR"]
HOWR = {"RAN": 0, "READ": 1, "DOC": 2}
STOP = set("""a an the of to in on for and or is are be by with without not no as at it its this that from into
than then when which who what does do did has have had any every all only also more less same other one two per
under over after before while their there they them can cannot so but if else via vs""".split())


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def norm_sev(s):
    s = clean(s).upper().replace("_", "-")
    return s if s in SEV else {"WRONG RESULT": "WRONG-RESULT", "BLOCKS USE": "BLOCKS-USE"}.get(s, "DEGRADES")


def norm_cls(s):
    s = clean(s).upper().replace("_", "-").replace(" ", "-")
    return s if s in ("BUILD-MVP", "BUILD-LATER", "DECIDE") else "BUILD-LATER"


def load():
    rows = []
    for path in sorted(glob.glob(os.path.join(F, "*.gaps.jsonl"))):
        agent = os.path.basename(path).split(".")[0]
        for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                print(f"skip bad line {path}:{n}", file=sys.stderr)
                continue
            if not isinstance(r, dict):
                continue
            r = {k: (clean(v) if isinstance(v, str) else v) for k, v in r.items()}
            r["agent"] = agent
            r["id"] = r.get("id") or f"{agent}-{n:03d}"
            r["severity"] = norm_sev(r.get("severity"))
            r["class"] = norm_cls(r.get("class"))
            r["how"] = clean(r.get("how")).upper() or "READ"
            r["user_sees"] = clean(r.get("user_sees")).lower() or "missing feature"
            r["area"] = clean(r.get("area")) or agent
            r["missing"] = clean(r.get("missing"))
            r["evidence"] = clean(r.get("evidence"))
            r["sources"] = [r["id"]]
            r["also"] = []
            rows.append(r)
    return rows


def is_process(r):
    return r["area"].lower().startswith("process")


def toks(s):
    return {w for w in re.findall(r"[a-z0-9_.\-/]{3,}", s.lower()) if w not in STOP}


def dedup(rows):
    """Cross-agent duplicates only: agents were told never to merge their own similar gaps."""
    for r in rows:
        r["_t"] = toks(r["missing"])
    kept = []
    order = sorted(range(len(rows)), key=lambda i: (HOWR.get(rows[i]["how"], 3), SEV.index(rows[i]["severity"])))
    for i in order:
        r = rows[i]
        dup = None
        if len(r["_t"]) >= 6:
            for k in kept:
                if k["agent"] == r["agent"] or any(s.split("-")[0] == r["agent"] for s in k["sources"]):
                    continue
                inter = len(k["_t"] & r["_t"])
                if inter < 6:
                    continue
                j = inter / len(k["_t"] | r["_t"])
                if j >= 0.4:
                    dup = k
                    break
        if dup is None:
            kept.append(r)
        else:
            dup["sources"].append(r["id"])
            dup["also"].append(f"{r['id']} ({r['how']}): {r['evidence'][:160]}")
            if SEV.index(r["severity"]) < SEV.index(dup["severity"]):
                dup["severity"] = r["severity"]
    return kept


MANUAL = [("PY2-001", "LEAD-014"), ("APP2-039", "BRANCH-068"), ("APP2-039", "APP1-007"), ("APP2-043", "APP1-011"),
          ("BRANCH-009", "SWEEP-518"), ("PY1-001", "LEAD-028"), ("LEAD-007", "PY1-018"), ("LEAD-021", "PLAT-050"),
          ("SWEEP-537", "LEAD-010")]


def manual(rows):
    """Duplicates the lead found by reading (different wording, same claim)."""
    def find(sid):
        return next((r for r in rows if sid in r["sources"]), None)
    for keep, drop in MANUAL:
        k, d = find(keep), find(drop)
        if not k or not d or k is d:
            continue
        k["sources"] += d["sources"]
        k["also"].append(f"{d['id']} ({d['how']}): {d['evidence'][:160]}")
        k["also"] += d["also"]
        if SEV.index(d["severity"]) < SEV.index(k["severity"]):
            k["severity"] = d["severity"]
        rows.remove(d)
    return rows


def esc(s, n=None):
    s = clean(s)
    if n and len(s) > n:
        s = s[: n - 1] + "…"
    return s.replace("|", "\\|")


def gap_line(num, r):
    dec = ""
    if r["class"] == "DECIDE":
        dec = f" — for: {esc(r.get('decide_for', ''), 220)} — against: {esc(r.get('decide_against', ''), 220)}"
    ev = esc(r["evidence"], 420)
    if r["also"]:
        ev += " · also found by: " + esc("; ".join(r["also"]), 300)
    return (f"| {num} | {esc(r['area'], 70)} | {esc(r['missing'], 520)} | {ev} [{r['how']}] | {r['user_sees']} | "
            f"{r['severity']} | {r['class']}{dec} | {', '.join(r['sources'])} |")


def proc_line(num, r):
    dec = ""
    if r["class"] == "DECIDE":
        dec = f" — for: {esc(r.get('decide_for', ''), 200)} — against: {esc(r.get('decide_against', ''), 200)}"
    ev = esc(r["evidence"], 380)
    if r["also"]:
        ev += " · also found by: " + esc("; ".join(r["also"]), 240)
    area = re.sub(r"^process\s*/\s*", "", r["area"], flags=re.I)
    return (f"| {num} | {esc(r.get('prompt', '—'), 30)} | {esc(r.get('block', '—'), 40)} | {esc(area, 60)} | "
            f"{esc(r['missing'], 480)} | {ev} [{r['how']}] | {r['user_sees']} | {r['severity']} | {r['class']}{dec} | "
            f"{', '.join(r['sources'])} |")


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = load()
    prod = [r for r in rows if not is_process(r)]
    proc = [r for r in rows if is_process(r)]
    n_in = (len(prod), len(proc))
    prod, proc = manual(dedup(prod)), dedup(proc)
    key = lambda r: (SEV.index(r["severity"]), r["area"].lower(), r["id"])  # noqa: E731
    prod.sort(key=key)
    proc.sort(key=key)
    idmap = {}
    for i, r in enumerate(prod, 1):
        r["num"] = f"G-{i:03d}" if len(prod) < 1000 else f"G-{i:04d}"
        for s in r["sources"]:
            idmap[s] = r["num"]
    for i, r in enumerate(proc, 1):
        r["num"] = f"P-{i:03d}"
        for s in r["sources"]:
            idmap[s] = r["num"]
    with open(os.path.join(OUT, "gaps.jsonl"), "w") as fh:
        for r in prod + proc:
            fh.write(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "ids-map.tsv"), "w") as fh:
        for s, g in sorted(idmap.items()):
            fh.write(f"{s}\t{g}\n")
    stats = {
        "in": n_in, "prod": len(prod), "proc": len(proc),
        "prod_sev": {s: sum(1 for r in prod if r["severity"] == s) for s in SEV},
        "proc_sev": {s: sum(1 for r in proc if r["severity"] == s) for s in SEV},
        "prod_cls": {c: sum(1 for r in prod if r["class"] == c) for c in ("BUILD-MVP", "BUILD-LATER", "DECIDE")},
        "proc_cls": {c: sum(1 for r in proc if r["class"] == c) for c in ("BUILD-MVP", "BUILD-LATER", "DECIDE")},
        "how": {h: sum(1 for r in prod + proc if r["how"] == h) for h in ("RAN", "READ", "DOC")},
    }
    json.dump(stats, open(os.path.join(OUT, "stats.json"), "w"), indent=1)
    gl = ["| id | area | what is missing | evidence [how known] | user sees | severity | class | source ids |",
          "|---|---|---|---|---|---|---|---|"] + [gap_line(r["num"], r) for r in prod]
    pl = ["| id | prompt | block | area | what is missing | evidence [how known] | user sees | severity | class | source ids |",
          "|---|---|---|---|---|---|---|---|---|---|"] + [proc_line(r["num"], r) for r in proc]
    open(os.path.join(OUT, "gaplist.md"), "w").write("\n".join(gl) + "\n")
    open(os.path.join(OUT, "proclist.md"), "w").write("\n".join(pl) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
