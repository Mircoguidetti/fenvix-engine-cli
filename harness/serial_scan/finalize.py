#!/usr/bin/env python3
"""Step 3: build scan.jsonl from raw/examined.jsonl and review_decisions.json.

reason_kind rules:
  * auto `stated` candidates (a reason word near the flag, in a doc line mentioning the
    flag, or in the commit message that last touched the line) are confirmed or demoted
    BY HAND in review_decisions.json: {repo: {"kind", "file", "line" (the chosen
    evidence line), "quote_check" (its text, re-checked here), "category":
    breakage|resource|other, "note"}}. A repository with an
    auto `stated` candidate and no decision makes this script fail.
  * `stated` requires reason_quote (the source line, verbatim) and reason_file:reason_line.
    A stated entry without its quote is written as `none`.
  * a decision may also be `not_serial` (hand-found false positive, e.g. the flag only
    appears in a docstring); it may select evidence by "file"+"line" instead of index.
  * auto `implied` / `none` are kept as computed (implied_context holds the nearby
    comment verbatim for implied).
Usage: python3 harness/serial_scan/finalize.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
FIELDS = ["repo", "commit", "stars", "language", "runner", "flag", "file", "line", "verbatim_line",
          "reason_quote", "reason_kind", "multi_core_runner", "test_count_estimate"]


def main():
    dec_path = os.path.join(HERE, "review_decisions.json")
    decisions = json.load(open(dec_path)) if os.path.exists(dec_path) else {}
    missing = []
    out = []
    for l in open(os.path.join(RAW, "examined.jsonl")):
        r = json.loads(l)
        row = {k: r.get(k) for k in FIELDS}
        row.update({
            "readable": "error" not in r,
            "error": r.get("error"),
            "running_serially": bool(r.get("running_serially")),
            "not_serial_reason": r.get("not_serial_reason"),
            "reason_file": None, "reason_line": None, "reason_source": None, "reason_category": None,
            "review_note": None, "implied_context": None,
            "multi_core_method": r.get("multi_core_method"),
            "playwright_scaffold_default": bool(r.get("playwright_scaffold_default")),
            "blame_commit": r.get("blame_commit"),
            "blame_beyond_fetched_depth": r.get("blame_boundary"),
            "pushed_at": r.get("pushed_at"), "archived": r.get("archived"),
            "search_queries": r.get("search_queries"),
        })
        if "error" in r:
            row["running_serially"] = False
            row["multi_core_runner"] = False
        if not row["running_serially"]:
            row["reason_kind"] = None
            row["multi_core_runner"] = False
            out.append(row)
            continue
        auto = r.get("auto_reason_kind")
        if auto == "stated":
            d = decisions.get(r["repo"])
            if d is None:
                missing.append(r["repo"])
                continue
            row["review_note"] = d.get("note")
            if d["kind"] == "not_serial":
                row.update(running_serially=False, reason_kind=None, multi_core_runner=False,
                           not_serial_reason="hand review: " + d["note"])
                out.append(row)
                continue
            e = None
            if "line" in d:  # the evidence line the reviewer chose, by file:line
                hit = [x for x in r["evidence"] if x["file"] == d["file"] and x["line"] == d["line"]]
                if not hit or hit[0]["text"] != d.get("quote_check", hit[0]["text"]):
                    print(f"{r['repo']}: reviewed evidence {d['file']}:{d['line']} no longer matches", file=sys.stderr)
                    sys.exit(1)
                e = hit[0]
            if d["kind"] == "stated":
                row["reason_quote"] = e["text"]
                row["reason_file"] = e["file"]
                row["reason_line"] = e["line"]
                row["reason_source"] = e["source"]
                row["reason_category"] = d["category"]
            elif d["kind"] == "implied":
                row["implied_context"] = f'{e["file"]}:{e["line"]}: {e["text"]}' if e else d.get("note")
            row["reason_kind"] = d["kind"]
        elif auto == "implied":
            e = r["auto_reason"]
            row["reason_kind"] = "implied"
            row["implied_context"] = f'{e["file"]}:{e["line"]}: {e["text"]}'
        else:
            row["reason_kind"] = "none"
        if row["reason_kind"] == "stated" and not (row["reason_quote"] and row["reason_file"] and row["reason_line"]):
            row["reason_kind"] = "none"
        out.append(row)
    if missing:
        print(f"{len(missing)} auto-stated repositories have no review decision:", file=sys.stderr)
        for m in missing:
            print("  ", m, file=sys.stderr)
        sys.exit(1)
    with open(os.path.join(HERE, "scan.jsonl"), "w") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} rows to scan.jsonl")


if __name__ == "__main__":
    main()
