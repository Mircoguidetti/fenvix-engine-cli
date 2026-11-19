#!/usr/bin/env python3
"""Extend flaky_candidates.json with repositories found by a GitHub-wide issue search:
issues with "flaky" in the title that mention Jest or Vitest, in JavaScript/TypeScript
repositories with at least --min-stars stars, opened since 2023. Pinned like the other
issue candidates (last commit before the issue)."""
import argparse, json, subprocess, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUERIES = ['flaky in:title vitest is:issue created:>2023-01-01', 'flaky in:title jest is:issue created:>2023-01-01',
           'flaky test in:title is:issue label:test created:>2024-01-01', '"flaky test" in:title is:issue created:>2024-06-01',
           'intermittent in:title vitest is:issue created:>2023-01-01', 'intermittent in:title jest is:issue created:>2023-01-01',
           'flaky in:title "vitest" in:body is:issue created:>2023-01-01', 'flaky in:title "jest" in:body is:issue created:>2023-01-01']


def gh(path, **params):
    args = ["gh", "api", "-X", "GET", path]
    for k, v in params.items():
        args += ["-f", f"{k}={v}"]
    for attempt in range(4):
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        if "rate limit" in (r.stdout + r.stderr).lower():
            time.sleep(30 * (attempt + 1))
            continue
        return {}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-stars", type=int, default=1000)
    ap.add_argument("--max", type=int, default=45)
    args = ap.parse_args()
    data = json.loads((HERE / "flaky_candidates.json").read_text())
    have = {c["repo"].lower() for c in data["candidates"]}
    have |= {r["url"].split("github.com/")[1].lower() for r in json.loads((HERE / "repos.json").read_text())["popular"]}
    issues = {}
    for q in QUERIES:
        for page in (1, 2, 3):
            res = gh("search/issues", q=q, per_page=100, page=page, sort="created", order="desc")
            time.sleep(2.2)
            for it in res.get("items", []):
                repo = it["repository_url"].split("/repos/")[1]
                if repo.lower() in have or "pull_request" in it:
                    continue
                issues.setdefault(repo, []).append(it)
    print(f"{len(issues)} repositories with matching issues")
    out = []
    for repo, its in sorted(issues.items(), key=lambda kv: -len(kv[1])):
        if len(out) >= args.max:
            break
        info = gh("search/repositories", q=f"repo:{repo}")
        time.sleep(2.2)
        items = info.get("items") or []
        if not items:
            continue
        r = items[0]
        if r.get("stargazers_count", 0) < args.min_stars or r.get("language") not in ("TypeScript", "JavaScript", "Vue", "Svelte") \
                or r.get("archived") or r.get("fork"):
            continue
        its.sort(key=lambda i: i["created_at"], reverse=True)
        name = repo.split("/")[1].lower() + "-flaky"
        if any(c["name"] == name for c in data["candidates"] + out):
            name = repo.replace("/", "-").lower() + "-flaky"
        out.append({"name": name, "repo": repo, "url": f"https://github.com/{repo}", "source": "github-issue-search",
                    "pin": "before-issue", "stars": r["stargazers_count"],
                    "issues": [{"url": i["html_url"], "title": i["title"], "created_at": i["created_at"], "state": i["state"]}
                               for i in its[:3]]})
        print(f"{repo} ({r['stargazers_count']}*): {its[0]['title'][:80]}", flush=True)
        saved = dict(data, candidates=data["candidates"] + out)
        (HERE / "flaky_candidates.json").write_text(json.dumps(saved, indent=1))
    (HERE / "flaky_candidates.json").write_text(json.dumps(dict(data, candidates=data["candidates"] + out), indent=1))
    print("added", len(out), ",".join(c["name"] for c in out))


if __name__ == "__main__":
    main()
