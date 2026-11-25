"""C5.3 probe and REST client tests. Run: python3 -m pytest -q harness/red_check/population/

Each test states its card: protects=<observable>; fails_when=<wrong result>; no_claim=<what green does not prove>.
"""
from __future__ import annotations

import http.server
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghrest  # noqa: E402
import probe  # noqa: E402


class _Server:
    """Two local HTTP servers: an 'API' that answers job logs with 302 to the 'blob' server; both record headers."""

    def __init__(self, api_status: int = 302, blob_status: int = 200, blob_body: bytes = b"2026-11-20T10:00:00Z log\n"):
        self.seen: dict[str, list[dict]] = {"api": [], "blob": []}
        outer = self

        def handler(role):
            class H(http.server.BaseHTTPRequestHandler):
                def log_message(self, *a):  # quiet
                    pass

                def do_GET(self):  # noqa: N802
                    outer.seen[role].append({k.lower(): v for k, v in self.headers.items()} | {"path": self.path})
                    if role == "api":
                        self.send_response(api_status)
                        self.send_header("X-RateLimit-Limit", "5000")
                        self.send_header("X-RateLimit-Remaining", "4999")
                        if api_status == 302:
                            self.send_header("Location", f"http://127.0.0.1:{outer.blob.server_port}/blob?sig=x")
                        self.end_headers()
                        if api_status != 302:
                            self.wfile.write(b'{"message": "Not Found"}')
                    else:
                        self.send_response(blob_status)
                        self.end_headers()
                        self.wfile.write(blob_body if blob_status == 200 else b"<Error>AuthenticationFailed</Error>")
            return H

        self.api = http.server.HTTPServer(("127.0.0.1", 0), handler("api"))
        self.blob = http.server.HTTPServer(("127.0.0.1", 0), handler("blob"))
        for s in (self.api, self.blob):
            threading.Thread(target=s.serve_forever, daemon=True).start()

    def client(self):
        return ghrest.Client("secret-token", pace=0, api=f"http://127.0.0.1:{self.api.server_port}")

    def close(self):
        for s in (self.api, self.blob):
            s.shutdown()


def test_authorization_not_sent_to_redirect_host():
    """protects=the token never reaches the blob host; API and blob statuses recorded apart;
    fails_when=urllib forwards Authorization on the redirect (headers= instead of add_unredirected_header, or an
    automatic redirect follow); no_claim=GitHub's real redirect host behaves like this local server."""
    s = _Server()
    try:
        r = s.client().get_log("o/r", 7)
    finally:
        s.close()
    assert s.seen["api"][0]["authorization"] == "Bearer secret-token"
    assert s.seen["api"][0]["path"] == "/repos/o/r/actions/jobs/7/logs"
    assert "authorization" not in s.seen["blob"][0]
    assert s.seen["blob"][0]["user-agent"] == "fenvix-research"
    assert (r["api_status"], r["blob_status"]) == (302, 200)
    assert r["body"].startswith(b"2026-11-20")


def test_blob_refusal_recorded_apart():
    """protects=a blob 403 after an API 302 is recorded as blob status 403 and classed refused;
    fails_when=the blob error is folded into the API status or classed ok; no_claim=nothing about real blob errors."""
    s = _Server(blob_status=403)
    try:
        c = s.client()
        r = c.get_log("o/r", 7)
    finally:
        s.close()
    assert (r["api_status"], r["blob_status"], r["body"]) == (302, 403, None)
    assert c.n_requests == 2
    assert probe.classify(r["api_status"], r["blob_status"], 0, 3) == "refused"


def test_classify_410_and_old_404_are_not_refusals():
    """protects=a 410, or a 404 on a job older than 30 days, means 'past retention, take the next job', not BLOCKED;
    fails_when=either is classed refused, or a young 404/403 is not; no_claim=GitHub's retention is 30 or 90 days."""
    assert probe.classify(410, None, 0, 5) == "skip"
    assert probe.classify(404, None, 0, 45) == "skip"
    assert probe.classify(404, None, 0, 12) == "refused"
    assert probe.classify(403, None, 0, 12) == "refused"
    assert probe.classify(302, 200, 10, 12) == "ok"
    assert probe.classify(302, 200, 0, 12) == "refused"


class _FakeClient:
    def __init__(self, answers):
        self.answers, self.n_requests, self.limit, self.remaining = answers, 0, 5000, 4990

    def get_log(self, repo, job_id):
        a = self.answers[job_id]
        self.n_requests += 2 if a[0] == 302 else 1
        return {"api_status": a[0], "blob_status": a[1], "body": a[2], "error": None if a[2] else "x"}


def test_probe_run_skips_past_retention_and_stops_at_two_repos():
    """protects=the probe takes the next job after a 410 and stops after 2 readable jobs from different repositories,
    within its request budget; fails_when=it reports refused for a 410, reads a second job of an ok repository, or
    keeps reading after 'works'; no_claim=the live probe outcome."""
    jobs = [{"repo": "a/x", "job_id": 1, "completed_at": "2026-11-15T00:00:00Z"},
            {"repo": "b/y", "job_id": 2, "completed_at": "2026-11-15T00:00:00Z"},
            {"repo": "a/x", "job_id": 3, "completed_at": "2026-11-15T00:00:00Z"},
            {"repo": "c/z", "job_id": 4, "completed_at": "2026-11-15T00:00:00Z"},
            {"repo": "d/w", "job_id": 5, "completed_at": "2026-11-15T00:00:00Z"}]
    c = _FakeClient({1: (302, 200, b"log"), 2: (410, None, None), 3: (302, 200, b"log"),
                     4: (302, 200, b"log"), 5: (302, 200, b"log")})
    out = probe.run(c, {"jobs": jobs, "max_requests": 10, "as_of": "2026-11-25"})
    assert out["verdict"] == "works"
    assert [r["job_id"] for r in out["jobs"]] == [1, 2, 4]
    assert [r["class"] for r in out["jobs"]] == ["ok", "skip", "ok"]
    assert out["requests"] == 5


def test_probe_run_refused_on_two_young_jobs():
    """protects=two young jobs refused gives verdict 'refused' (the BLOCKED line); fails_when=refusals are ignored;
    no_claim=the live outcome."""
    jobs = [{"repo": "a/x", "job_id": 1, "completed_at": "2026-11-20T00:00:00Z"},
            {"repo": "b/y", "job_id": 2, "completed_at": "2026-11-20T00:00:00Z"}]
    c = _FakeClient({1: (403, None, None), 2: (302, 403, None)})
    assert probe.run(c, {"jobs": jobs, "max_requests": 10, "as_of": "2026-11-25"})["verdict"] == "refused"
