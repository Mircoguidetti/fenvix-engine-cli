#!/usr/bin/env python3
"""Step 1b: repository metadata (stars, language, default branch, fork, archived, pushed_at)
through GitHub repository search (gh api search/repositories, several repo: qualifiers per
query). The per-repository REST endpoints are not reachable from this session for
repositories outside its own scope, so search is the metadata source. DECLARED by GitHub."""
import json, os, subprocess, time
HERE = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(HERE, "raw")
PER_QUERY = int(os.environ.get("SERIAL_SCAN_PER_QUERY", "25"))
repos, per_query = [], {}
for l in open(os.path.join(RAW, "hits.jsonl")):
    h = json.loads(l)
    if h.get("fork"):
        continue
    seen = per_query.setdefault(h["query"], [])
    if h["repo"] not in seen and len(seen) < PER_QUERY:
        seen.append(h["repo"])
    if h["repo"] in seen and h["repo"] not in repos:
        repos.append(h["repo"])
out = os.path.join(RAW, "repo_meta.jsonl")
have = {json.loads(l)["repo"].lower() for l in open(out)} if os.path.exists(out) else set()
todo = [r for r in repos if r.lower() not in have]
with open(out, "a") as f:
    batch = []
    def flush(batch):
        q = " ".join("repo:" + r for r in batch)
        for a in range(6):
            p = subprocess.run(["gh", "api", "-X", "GET", "search/repositories", "-f", "q=" + q, "-f", "per_page=100"], capture_output=True, text=True)
            if p.returncode == 0:
                d = json.loads(p.stdout); break
            time.sleep(20 * (a + 1))
        else:
            d = {"items": []}
        got = set()
        for i in d.get("items", []):
            got.add(i["full_name"].lower())
            f.write(json.dumps({"repo": i["full_name"], "stars": i["stargazers_count"], "language": i["language"],
                                "default_branch": i["default_branch"], "fork": i["fork"], "archived": i["archived"],
                                "pushed_at": i["pushed_at"]}) + "\n")
        for r in batch:
            if r.lower() not in got:
                f.write(json.dumps({"repo": r, "missing": True}) + "\n")
        f.flush(); time.sleep(2.2)
    for r in todo:
        if len(" ".join("repo:" + x for x in batch + [r])) > 240:
            flush(batch); batch = []
        batch.append(r)
    if batch:
        flush(batch)
print(len(todo), "looked up")
