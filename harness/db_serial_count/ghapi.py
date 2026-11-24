"""GitHub REST access for the count: one class for the workflow token (urllib) and the work session (``gh api``).

Every request is GET. Rate headers are tracked; when ``X-RateLimit-Remaining`` < 50 the client sleeps until reset.
Search requests are paced to at most 9 per minute. User-Agent ``fenvix-research``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = "fenvix-research"
SEARCH_GAP = 60.0 / 9 + 0.1


class Client:
    def __init__(self, token: str | None = None, use_gh: bool = False, pace: float = 0.5):
        self.token, self.use_gh, self.pace = token, use_gh, pace
        self.remaining, self.limit, self.reset = {}, {}, {}
        self.n_requests = 0
        self._last = 0.0
        self._last_search = 0.0

    # ------------------------------------------------------------------ rate handling
    def _rate(self, headers: dict) -> None:
        h = {k.lower(): v for k, v in headers.items()}
        res = h.get("x-ratelimit-resource", "core")
        if "x-ratelimit-remaining" in h:
            self.remaining[res] = int(h["x-ratelimit-remaining"])
            self.limit[res] = int(h.get("x-ratelimit-limit") or 0)
            self.reset[res] = int(h.get("x-ratelimit-reset") or 0)

    def _wait(self, search: bool) -> None:
        res = "code_search" if search else "core"
        if search:
            wait = SEARCH_GAP - (time.time() - self._last_search)
            if wait > 0:
                time.sleep(wait)
            self._last_search = time.time()
        else:
            wait = self.pace - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        rem = self.remaining.get(res)
        if rem is not None and rem < 50 and not (search and self.limit.get(res, 0) <= 50):
            sl = max(self.reset.get(res, 0) - time.time(), 0) + 3
            sys.stderr.write(f"rate limit {res} remaining {rem}: sleeping {sl:.0f}s\n")
            time.sleep(min(sl, 3700))

    # ------------------------------------------------------------------ transport
    def _once(self, path: str) -> tuple[int, dict, object]:
        if self.use_gh:
            r = subprocess.run(["gh", "api", "-i", "-X", "GET", "-H", f"User-Agent: {UA}", path],
                               capture_output=True, text=True)
            head, _, body = r.stdout.partition("\r\n\r\n")
            if not body and "\n\n" in r.stdout:
                head, _, body = r.stdout.partition("\n\n")
            lines = head.splitlines()
            status = int(lines[0].split()[1]) if lines and lines[0].startswith("HTTP") else (0 if r.returncode else 200)
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip()] = v.strip()
            try:
                data = json.loads(body) if body.strip() else None
            except json.JSONDecodeError:
                data = {"raw": body[:500], "stderr": r.stderr[:500]}
            if status == 0:
                data = {"stderr": r.stderr[:500]}
            return status, headers, data
        req = urllib.request.Request(f"{API}/{path}", headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, dict(r.headers), json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body[:500]}
            return e.code, dict(e.headers or {}), data
        except Exception as e:  # network error
            return 0, {}, {"exception": repr(e)[:300]}

    def get(self, path: str, search: bool = False) -> tuple[int, object, dict]:
        """GET ``path`` (relative to the API root). Returns (status, data, headers).

        Rate-limit responses (403/429 mentioning rate limit) wait and retry; transport errors and 5xx retry with
        backoff (up to 4 attempts). Other statuses are returned as is."""
        last = (0, None, {})
        for attempt in range(6):
            self._wait(search)
            self.n_requests += 1
            st, hd, data = self._once(path)
            self._rate(hd)
            last = (st, data, hd)
            msg = json.dumps(data)[:400].lower() if data is not None else ""
            if st in (403, 429) and ("rate limit" in msg or "abuse" in msg):
                ra = int({k.lower(): v for k, v in hd.items()}.get("retry-after") or 0)
                res = "code_search" if search else "core"
                sl = ra or (max(self.reset.get(res, 0) - time.time(), 0) + 3 if self.remaining.get(res) == 0 else 60)
                sys.stderr.write(f"rate limited ({st}) on {path[:80]}: sleeping {sl:.0f}s\n")
                time.sleep(min(sl, 3700))
                continue
            if st == 0 or st >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            return last
        return last


def from_env() -> Client:
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        return Client(token=tok)
    return Client(use_gh=True)
