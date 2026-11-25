"""C5.3 step 2.1: job-log probe on route 1 (stop rule). Runs inside the workflow with GITHUB_TOKEN.

Request: {"kind": "probe", "max_requests": 10, "as_of": "YYYY-MM-DD",
          "jobs": [{"repo": "o/r", "job_id": 1, "completed_at": "...Z", "source": "..."}, ...]}
Jobs are tried in order until 2 jobs from different repositories have a readable log (API 302 + blob 200,
non-empty), or the request budget is spent. Per job the API status and the blob status are recorded apart, with
the first 200 characters of the body (blob body, or API error body).

Classification of a job (``classify``):
  ok       API redirect (or 200) and blob 200 with a non-empty body
  skip     API 410, or API 404 on a job older than 30 days (log past retention: not a refusal; take the next job)
  refused  API 403 / 404 on a job younger than 30 days, or any blob status other than 200 (or an empty body)
  other    anything else (network, 5xx after retries): recorded, not counted as refused
Verdict: "works" when 2 ok jobs from different repositories; "refused" when 2 jobs were refused and fewer than 2 ok;
otherwise "inconclusive".
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghrest  # noqa: E402

REDIRECTS = (301, 302, 303, 307, 308)


def age_days(completed_at: str, as_of: str) -> float:
    c = dt.datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    a = dt.datetime.fromisoformat(as_of + "T00:00:00+00:00") if len(as_of) == 10 else \
        dt.datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    return (a - c).total_seconds() / 86400


def classify(api_status, blob_status, body_len: int, age: float) -> str:
    if api_status == 410 or (api_status == 404 and age > 30):
        return "skip"
    if api_status in (403, 404):
        return "refused"
    if api_status in REDIRECTS or api_status == 200:
        return "ok" if blob_status == 200 and body_len > 0 else "refused"
    return "other"


def verdict(results: list[dict]) -> str:
    ok_repos = {r["repo"].lower() for r in results if r["class"] == "ok"}
    if len(ok_repos) >= 2:
        return "works"
    if sum(r["class"] == "refused" for r in results) >= 2:
        return "refused"
    return "inconclusive"


def run(client, req: dict) -> dict:
    budget = int(req.get("max_requests", 10))
    as_of = req.get("as_of") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results: list[dict] = []
    for j in req["jobs"]:
        if verdict(results) != "inconclusive":
            break
        if budget - client.n_requests < 2:  # a log read may take 2 requests (API + blob)
            break
        if any(r["class"] == "ok" and r["repo"].lower() == j["repo"].lower() for r in results):
            continue  # the 2 readable jobs must come from different repositories
        before = client.n_requests
        r = client.get_log(j["repo"], int(j["job_id"]))
        body = r["body"] or b""
        first = (body.decode(errors="replace") if r["body"] is not None else (r["error"] or ""))[:200]
        age = age_days(j["completed_at"], as_of)
        results.append({"repo": j["repo"], "job_id": int(j["job_id"]), "completed_at": j["completed_at"],
                        "age_days": round(age, 2), "source": j.get("source"),
                        "api_status": r["api_status"], "blob_status": r["blob_status"],
                        "body_bytes": len(body), "first_200": first,
                        "requests": client.n_requests - before,
                        "class": classify(r["api_status"], r["blob_status"], len(body), age)})
    return {"as_of": as_of, "requests": client.n_requests, "rate_limit": client.limit,
            "rate_remaining": client.remaining, "verdict": verdict(results), "jobs": results}


def main(argv: list[str]) -> int:
    req = json.loads(Path(argv[1]).read_text())
    out = run(ghrest.Client(ghrest.token()), req)
    res = HERE / "results"
    res.mkdir(exist_ok=True)
    (res / f"probe_{req.get('chunk', 'probe')}.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: out[k] for k in ("verdict", "requests", "rate_limit", "rate_remaining")}))
    for r in out["jobs"]:
        print(r["repo"], r["job_id"], r["api_status"], r["blob_status"], r["body_bytes"], r["class"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
