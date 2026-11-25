#!/usr/bin/env python3
"""Print what the hand reader sees (§1.9, §2.6), from the committed rows only.

    python3 handread_dump.py a-wasted        # every automatic wasted pull request
    python3 handread_dump.py a-sample        # the 30-row not-wasted sample (random.Random(3))
    python3 handread_dump.py b               # the Count B samples (random.Random(4) / (5))
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import rules as R  # noqa: E402
import stats  # noqa: E402


def show_ev(name, ev):
    print(f"  {name}: class={ev['class']} files={ev['files']} candidates={ev['candidates'][:10]}")
    for a in ev.get("annotations") or []:
        print(f"    ann {a.get('path')}:{a.get('start_line')} {(a.get('title') or '')[:80]} | "
              f"{(a.get('message') or '')[:300]!r}")
    o = ev.get("output") or {}
    for k in ("title", "summary", "text"):
        if o.get(k):
            print(f"    {k}: {o[k][:1200]!r}")


def show_a(r):
    print("=" * 100)
    print(r["url"], r["family"], "result:", r["result"], "commits:", r.get("n_commits"), "head_ref:", r.get("head_ref"))
    for c in r.get("commits") or []:
        print(f"  #{c['pos']} {'AGENT' if c['agent'] else 'human'} {c['author_login']} parents={c['parents']} "
              f"failed={[(f['identity'], f['verdict']) for f in c['failed']]} | {c['message'][:100]!r}")
    for x in r.get("xs") or []:
        print(f"-- X {x['identity']!r} ({x['kind']}) k={x['k']} end={x['end']} T={x['T']} wf={x['workflow_path']} "
              f"in_base={x['in_base']} wasted={x['wasted_commits']}")
        show_ev("evidence at k", x["evidence"])
        show_ev("B(X) evidence", x["base_evidence"])
        for c in x["window"]:
            print(f"  window #{c['pos']} reasons={c['reasons']} files({c['n_files']})="
                  f"{[f['filename'] for f in c['files']][:15]}")
            print(f"    message: {c['message'][:400]!r}")
            for f in c["files"][:6]:
                if f.get("patch_head"):
                    print(f"    patch {f['filename']}: {f['patch_head'][:400]!r}")


def main():
    mode = sys.argv[1]
    rows = J.read_jsonl(HERE / "results" / "a_rows.jsonl")
    if mode == "a-wasted":
        for r in rows:
            if r.get("result") == R.WASTED:
                show_a(r)
    elif mode == "a-sample":
        by = {r["url"]: r for r in rows}
        for u in stats.sample_a(rows):
            show_a(by[u])
    elif mode == "b":
        brows = J.read_jsonl(HERE / "results" / "b_rows.jsonl")
        iss = {i["key"]: i for i in stats.b_issues(brows)}
        comp, rest = stats.samples_b(brows)
        for name, keys in (("competing", comp), ("addressed", rest)):
            for k in keys:
                i = iss[k]
                print("=" * 100)
                print(name, k, i["class"], "|", i["title"])
                print("  issue body:", (i["body"] or "")[:800].replace("\n", " "))
                for p in i["agent_prs"]:
                    print(f"  PR #{p['number']} {p['family']} link={p['link']} created={p['created_at']} "
                          f"merged={p['merged_at']} | {p['title']}")
                    print("    body:", (p["body"] or "")[:600].replace("\n", " "))
                    print("    files:", p.get("files"))


if __name__ == "__main__":
    main()
