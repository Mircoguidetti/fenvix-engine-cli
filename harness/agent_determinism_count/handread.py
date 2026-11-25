#!/usr/bin/env python3
"""§4 hand reads. Labels live in results/reads.jsonl, one record per label:
{"url", "reader": "first"|"second", "label": "confirmed"|"rejected"|"unclear", "reason", "quote", "chunk", "at"}
(the last record per (url, reader) wins).

Usage: handread.py queue --chunk N            texts needing a first read, member by member in §4.1 order, stopping at
                                              a member's first text both readers confirmed (JSON lines on stdout)
       handread.py label --url U --label L [--reason R] [--quote Q] --chunk N [--reader first|second]
       handread.py second --chunk N           the second-read batch: every first `confirmed` and `unclear` not yet
                                              read twice, plus a random 20 `rejected` of chunk N (seed 2 + N)
                                              (JSON lines: url and text only, never the first label)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

RES = HERE / "results"
LABELS = ("confirmed", "rejected", "unclear")
REASONS = ("varying-output", "provider-errors", "cost")


def member_queue(cands: list[dict], reads: dict) -> list[dict]:
    """The texts of one member still needing a first read, in order, up to TEXT_CAP, none once a text is confirmed by
    both readers or a confirmed first read awaits its second read."""
    out = []
    for t in cands[:R.TEXT_CAP]:
        r = reads.get(t["url"]) or {}
        f = (r.get("first") or {}).get("label")
        lab = R.final_label(f, (r.get("second") or {}).get("label"))
        if lab == "confirmed":
            return []
        if f == "confirmed" and lab == "pending":
            return []  # wait for the second read before reading further
        if f is None:
            out.append(t)
    return out


def second_batch(chunk_reads: list[dict], reads: dict, chunk) -> list[str]:
    need = [u for u, r in reads.items() if (r.get("first") or {}).get("label") in ("confirmed", "unclear")
            and "second" not in r]
    rej = sorted({r["url"] for r in chunk_reads if r["reader"] == "first" and r["label"] == "rejected"
                  and (reads.get(r["url"]) or {}).get("first", {}).get("label") == "rejected"})
    k = int(str(chunk).rstrip("c")) if str(chunk).rstrip("c").isdigit() else 0
    sample = rej if len(rej) <= 20 else random.Random(2 + k).sample(rej, 20)
    return sorted(set(need) | {u for u in sample if "second" not in (reads.get(u) or {})})


def main(argv=None) -> int:
    import report
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["queue", "label", "second"])
    ap.add_argument("--chunk", required=True)
    ap.add_argument("--url")
    ap.add_argument("--label", choices=LABELS)
    ap.add_argument("--reason", choices=REASONS)
    ap.add_argument("--quote", default="")
    ap.add_argument("--reader", default="first", choices=["first", "second"])
    a = ap.parse_args(argv)
    d = report.load()
    reads = report.reads_map(d["reads"])
    if a.cmd == "label":
        if a.label in ("confirmed", "unclear") and a.reader == "first" and not a.quote:
            sys.exit("a confirmed or unclear first read needs --quote")
        rec = {"url": a.url, "reader": a.reader, "label": a.label, "reason": a.reason, "quote": a.quote,
               "chunk": a.chunk, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        with open(RES / "reads.jsonl", "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return 0
    x = report.compute(d)
    texts = {}
    for m in x["members"]:
        if str(m["row"].get("chunk")) != str(a.chunk):
            continue
        for t in m["candidates"]:
            texts[t["url"]] = (m["row"]["repo"], t)
    if a.cmd == "queue":
        for m in x["members"]:
            if str(m["row"].get("chunk")) != str(a.chunk) or m["pain"]["pain"] == "yes":
                continue
            for t in member_queue(m["candidates"], reads):
                print(json.dumps({"repo": m["row"]["repo"], "url": t["url"], "created_at": t.get("created_at"),
                                  "discovery": t.get("discovery"), "text": x["text_of"](t)}, sort_keys=True))
        return 0
    chunk_reads = [r for r in d["reads"] if str(r.get("chunk")) == str(a.chunk)]
    for u in second_batch(chunk_reads, reads, a.chunk):
        if u in texts:
            print(json.dumps({"url": u, "text": x["text_of"](texts[u][1])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
