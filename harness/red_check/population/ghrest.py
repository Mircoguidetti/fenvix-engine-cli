"""GitHub REST client for C5.3 (route 1: GitHub Actions in this repository, GITHUB_TOKEN, read-only).

Rules (PREREG.md): User-Agent ``fenvix-research``; at most 1 request per second; the rate headers are tracked so a
chunk can stop before its next request when ``X-RateLimit-Remaining`` < 20% of ``X-RateLimit-Limit``; every request
(API and log blob) is counted.

Job logs: ``GET repos/{o}/{r}/actions/jobs/{id}/logs`` answers 302 with a signed blob URL. The ``Authorization``
header is attached with ``add_unredirected_header`` and redirects are never followed automatically: the blob is read
with a second, separate request that carries no ``Authorization``. The API status and the blob status are returned
apart.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = "fenvix-research"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # a 3xx surfaces as HTTPError; the caller decides what to do with Location


def api_request(url: str, token: str | None) -> urllib.request.Request:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA})
    if token:
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def blob_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": UA})


class Client:
    """Live client. ``api`` is the API base (tests point it at a local server)."""

    def __init__(self, token: str | None, pace: float = 1.0, api: str = API, opener=None):
        self.token, self.pace, self.api = token, pace, api.rstrip("/")
        self.opener = opener or urllib.request.build_opener(_NoRedirect)
        self.remaining = self.limit = self.reset = None
        self.n_requests = 0
        self._last = 0.0

    # -------------------------------------------------------------- budget
    def low(self, frac: float = 0.2) -> bool:
        return self.remaining is not None and bool(self.limit) and self.remaining < frac * self.limit

    def _rate(self, h) -> None:
        if h is not None and h.get("X-RateLimit-Remaining") is not None:
            self.remaining, self.limit = int(h["X-RateLimit-Remaining"]), int(h["X-RateLimit-Limit"])
            self.reset = int(h.get("X-RateLimit-Reset") or 0)

    def _open(self, req):
        """One counted, paced request. Returns (status, headers, body bytes); never raises on HTTP status."""
        wait = self.pace - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.n_requests += 1
        try:
            with self.opener.open(req, timeout=120) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:  # noqa: BLE001
                body = b""
            return e.code, e.headers, body
        except Exception as e:  # noqa: BLE001  network
            return "network", None, str(e)[:300].encode()

    def _api(self, path: str):
        """API request with retries on rate limits (403/429 with 'rate limit') and 5xx; returns (status, headers, body)."""
        for attempt in range(4):
            st, h, body = self._open(api_request(f"{self.api}/{path}", self.token))
            self._rate(h)
            if st in (403, 429) and b"rate limit" in body.lower() and attempt < 3:
                reset = int((h or {}).get("X-RateLimit-Reset") or 0)
                time.sleep(min(max(reset - time.time(), 0) + 5, 3700) if self.remaining == 0 else 60)
                continue
            if (st == "network" or (isinstance(st, int) and st >= 500)) and attempt < 3:
                time.sleep(10)
                continue
            return st, h, body
        return st, h, body

    # -------------------------------------------------------------- reads
    def get_json(self, path: str):
        """(status, parsed JSON | error text)."""
        st, _h, body = self._api(path)
        if st == 200:
            return 200, json.loads(body)
        return st, body.decode(errors="replace")[:300]

    def get_log(self, repo: str, job_id: int) -> dict:
        """Read one job log. Returns {api_status, blob_status, body (bytes|None), error}."""
        st, h, body = self._api(f"repos/{repo}/actions/jobs/{job_id}/logs")
        out = {"api_status": st, "blob_status": None, "body": None, "error": None}
        if st in (301, 302, 303, 307, 308):
            loc = (h or {}).get("Location")
            if not loc:
                out["error"] = "redirect without Location"
                return out
            bst, _bh, bbody = self._open(blob_request(loc))
            out["blob_status"] = bst
            if bst == 200:
                out["body"] = bbody
            else:
                out["error"] = bbody.decode(errors="replace")[:300]
        elif st == 200:  # served directly (not expected): keep it, the blob status is the API status
            out["blob_status"], out["body"] = 200, body
        else:
            out["error"] = body.decode(errors="replace")[:300]
        return out


def token() -> str:
    return os.environ["GITHUB_TOKEN"]
