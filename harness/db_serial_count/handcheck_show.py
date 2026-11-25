#!/usr/bin/env python3
"""AC4 hand-check helper: prints the committed raw evidence for one repository so a person can check it by eye.

Usage: handcheck_show.py <owner/repo>

Prints (from results/raw/*.jsonl.gz, never from the network):
  - the row's ge_10 / serial-reject pairs as classified;
  - the workflow job block text (raw YAML lines, not parsed);
  - every config file fetched (pytest/jest/vitest/package.json/...): lines mentioning -n, workers, parallel, addopts;
  - for each jobs response: job names, conclusion, and per-step durations for steps whose name matches the pair's step,
    recomputed independently of rules.py (completed_at - started_at).
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
DISPLAY: dict = {}


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def text_of(d):
    if isinstance(d, dict) and d.get("encoding") == "base64":
        return base64.b64decode(d["content"]).decode("utf-8", "replace")
    if isinstance(d, dict) and "text" in d:
        return d["text"]
    return None


def main(repo: str) -> int:
    row = next((json.loads(x) for x in open(RES / "rows.jsonl") if json.loads(x)["repo"].lower() == repo.lower()), None)
    if not row:
        print("no row"); return 1
    raw = None
    with gzip.open(RES / "raw" / f"{row['chunk']}.jsonl.gz", "rt") as f:
        for x in f:
            d = json.loads(x)
            if d["repo"].lower() == repo.lower():
                raw = d["responses"]; break
    print(f"# {row['repo']}  cls={row.get('cls')}  furthest={row.get('furthest')}  chunk={row['chunk']}")
    pairs = [p for p in row["pairs"] if p.get("stage") in ("ge_10", "below_10", "not_serial", "too_few_runs")]
    for p in pairs:
        print(f"\n## pair {p['file']} job={p['job']} stage={p['stage']} db={p.get('db')} sharded={p.get('sharded')}")
        if p.get("timing"):
            print("   timing:", json.dumps({k: v for k, v in p["timing"].items() if k != 'runs'}))
        for s in p.get("steps", [])[:4]:
            print("   step", s.get("key"), s.get("status"), s.get("reason"), "|", s.get("evidence"), "|", (s.get("commands") or [""])[0][:200])
    files = {k: v for k, v in raw.items() if "/contents/" in k}
    for p in pairs:
        if p["stage"] != "ge_10":
            continue
        wf = next((v for k, v in files.items() if k.split("?")[0].endswith(p["file"])), None)
        t = text_of(wf.get("data")) if wf else None
        if t:
            lines = t.splitlines()
            i = next((n for n, ln in enumerate(lines) if re.match(rf"^\s{{2}}{re.escape(p['job'])}:\s*$", ln)), None)
            if i is not None:
                ind = len(lines[i]) - len(lines[i].lstrip())
                j = i + 1
                while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
                    j += 1
                print(f"\n## raw YAML {p['file']} lines {i + 1}-{j}")
                print("\n".join(f"{n + 1:5} {lines[n]}" for n in range(i, min(j, i + 160))))
                m = next((re.match(r"^\s+name:\s*(.+?)\s*$", lines[n]) for n in range(i + 1, j)
                          if re.match(rf"^\s{{{ind + 2}}}name:", lines[n])), None)
                if m:
                    DISPLAY[p["job"]] = m.group(1).strip("'\"")
    print("\n## config files (lines with -n / workers / parallel / addopts / serial / runInBand / fileParallelism / -p 1)")
    pat = re.compile(r"(-n\b|workers|parallel|addopts|serial|runInBand|FileParallelism|fileParallelism|-p 1|-p=1|threads|singleFork|singleThread)", re.I)
    for k, v in files.items():
        if ".github/workflows" in k or v.get("status") != 200:
            continue
        t = text_of(v.get("data"))
        if not t:
            continue
        hits = [f"   {n + 1:4} {ln.strip()[:160]}" for n, ln in enumerate(t.splitlines()) if pat.search(ln)]
        print(f" {k.split('/contents/')[1].split('?')[0]}: {len(hits)} lines")
        print("\n".join(hits[:12]))
    for p in pairs:
        if p["stage"] != "ge_10":
            continue
        for st in p.get("steps", []):
            if st.get("status") != "serial" or not st.get("key"):
                continue
            kind, val = st["key"][0], st["key"][1]
            step_name = val if kind == "name" else None
            prefix = val if kind == "prefix" else None
            print(f"\n## recomputed step durations for job '{p['job']}' step '{val}'")
            durs = []
            for k, v in sorted(raw.items()):
                if "/jobs?" not in k:
                    continue
                for j in (v.get("data") or {}).get("jobs", []):
                    name = j.get("name") or ""
                    disp = re.sub(r"\\\$\\\{\\\{.*?\\\}\\\}", ".*", re.escape(DISPLAY.get(p["job"], p["job"])))
                    if not (re.fullmatch(disp + r"( \(.*\))?", name) or re.fullmatch(disp, name)):
                        continue
                    for s in j.get("steps") or []:
                        sn = s.get("name") or ""
                        base = re.sub(r"\\\$\\\{\\\{.*?\\\}\\\}", ".*", re.escape(step_name or ""))
                        ok = (step_name and re.fullmatch(base, sn)) or (prefix and sn.startswith(prefix))
                        if ok and s.get("conclusion") == "success":
                            d = (ts(s["completed_at"]) - ts(s["started_at"])).total_seconds()
                            durs.append((int(k.split("/runs/")[1].split("/")[0]), name, sn, d))
            for x in durs:
                print("   ", x)
            per_run: dict = {}
            for rid, _, _, d in durs:
                per_run[rid] = max(per_run.get(rid, 0), d)
            last = [per_run[r] for r in sorted(per_run)[-10:]]
            srt = sorted(last)
            med = (srt[4] + srt[5]) / 2 if len(srt) == 10 else None
            print(f"   matched legs: {len(durs)}; longest leg per run, 10 newest runs: {srt}; median {med}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
