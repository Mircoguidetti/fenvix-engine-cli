"""GitHub REST access (GET only): workflow token (urllib) or work session (``gh api``).

Copied from db-serial-count 8150aa1 ghapi.py, with ``retry_seconds`` from market-direction f2e649b (the 429 message
gives the wait in ms or s and wins over Retry-After) and separate pacing for code search (<= 9/min) and issues search
(<= 25/min). Sleeps when X-RateLimit-Remaining < 50 until reset. User-Agent ``fenvix-research``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = "fenvix-research"
GAPS = {"code": 60.0 / 9 + 0.1, "issues": 60.0 / 25 + 0.1}
RESOURCE = {"code": "code_search", "issues": "search", None: "core"}


LIMIT_KEYS = ("x-ratelimit-resource", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
              "retry-after")


def limit_info(msg: str, h: dict) -> str:
    """One log field per rate-limited answer: the headers that name the limit, and primary (remaining 0) or secondary
    (a "secondary" message, or remaining above 0)."""
    rem = h.get("x-ratelimit-remaining")
    kind = "secondary" if "secondary" in msg or (rem not in (None, "") and rem != "0") else \
        "primary" if rem == "0" else "unknown"
    return "limit=" + kind + " " + " ".join(f"{k}={h.get(k, '-')}" for k in LIMIT_KEYS)


def retry_seconds(msg: str, h: dict, now: float | None = None) -> float:
    """Wait after a rate-limit answer. The message ("try again in 7.9s" / "try again in 581.6ms") wins over the
    Retry-After header; then the reset time; else 60 (market-direction f2e649b)."""
    m = re.search(r"try again in ([0-9.]+)(ms|s)\b", msg)
    if m:
        v = float(m.group(1))
        return (v / 1000 if m.group(2) == "ms" else v) + 2
    ra = float(h.get("retry-after") or 0)
    if ra:
        return ra
    if h.get("x-ratelimit-remaining") == "0" and h.get("x-ratelimit-reset"):
        return max(int(h["x-ratelimit-reset"]) - (time.time() if now is None else now), 0) + 3
    return 60.0


class Client:
    def __init__(self, token: str | None = None, use_gh: bool = False, pace: float = 0.4, log=None):
        self.token, self.use_gh, self.pace = token, use_gh, pace
        self.remaining, self.limit, self.reset = {}, {}, {}
        self.n_requests = 0
        self.n_search = {"code": 0, "issues": 0}
        self.log = log  # optional list: every request (method, path, status, time) for AC5
        self._last = 0.0
        self._last_search = {"code": 0.0, "issues": 0.0}

    def _rate(self, headers: dict) -> None:
        h = {k.lower(): v for k, v in headers.items()}
        res = h.get("x-ratelimit-resource", "core")
        if "x-ratelimit-remaining" in h:
            self.remaining[res] = int(h["x-ratelimit-remaining"])
            self.limit[res] = int(h.get("x-ratelimit-limit") or 0)
            self.reset[res] = int(h.get("x-ratelimit-reset") or 0)

    def _wait(self, search: str | None) -> None:
        if search:
            wait = GAPS[search] - (time.time() - self._last_search[search])
            if wait > 0:
                time.sleep(wait)
            self._last_search[search] = time.time()
        else:
            wait = self.pace - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        res = RESOURCE[search]
        rem = self.remaining.get(res)
        if rem is not None and rem < 50 and not (search and self.limit.get(res, 0) <= 50):
            sl = max(self.reset.get(res, 0) - time.time(), 0) + 3
            sys.stderr.write(f"rate limit {res} remaining {rem}: sleeping {sl:.0f}s\n")
            time.sleep(min(sl, 3700))

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
        req = urllib.request.Request(f"{API}/{path}", method="GET", headers={
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

    def get(self, path: str, search: str | None = None) -> tuple[int, object, dict]:
        """GET ``path`` (relative to the API root); ``search`` is None, "code" or "issues". Returns (status, data,
        headers). Rate-limit answers wait (``retry_seconds``) and retry; transport errors and 5xx back off; up to 6
        attempts."""
        if search not in (None, "code", "issues"):
            raise ValueError(search)
        last = (0, None, {})
        for attempt in range(6):
            self._wait(search)
            self.n_requests += 1
            if search:
                self.n_search[search] += 1
            st, hd, data = self._once(path)
            self._rate(hd)
            if self.log is not None:
                self.log.append({"method": "GET", "path": path[:200], "status": st, "search": search,
                                 "at": round(time.time(), 1)})
            last = (st, data, hd)
            msg = json.dumps(data)[:600].lower() if data is not None else ""
            h = {k.lower(): v for k, v in hd.items()}
            if st == 429 or (st == 403 and ("rate limit" in msg or "abuse" in msg or "retry-after" in h)):
                sl = retry_seconds(msg, h)
                sys.stderr.write(f"rate limited ({st}) on {path[:90]}: sleeping {sl:.0f}s {limit_info(msg, h)}\n")
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
