"""GitHub REST access for db-copies-read (workflow token only).

Copied from ``85b36b2452df:harness/db_serial_count/ghapi.py`` with the spec §1.3 changes:
(a) search guard on normalised paths, no ``gh api`` fallback (a missing token is an error);
(b) no sleep longer than 600 s: a longer wait raises ``Pause`` (the job checkpoints and exits 0);
(c) at most 1 core request per 2 s;
(d) pause when the last observed core remaining is below 20% of the last observed limit;
(e) a 403/429 rate-limit response waits within the cap; any other 403 raises ``AccessDenied``;
(f) ``n_requests`` counts HTTP attempts, retries included.
Every request is GET; User-Agent ``fenvix-research``.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = "fenvix-research"
MAX_SLEEP = 600.0
PACE = 2.0
FLOOR = 0.20
FIVE_XX_ATTEMPTS = 3
RATE_LIMIT_RETRIES = 3


class SearchRefused(Exception):
    pass


class Pause(Exception):
    """A wait longer than MAX_SLEEP or the rate floor: checkpoint and exit 0."""


class AccessDenied(Exception):
    """A 403 that is not a rate-limit response: a stop (§5)."""


def normalise(path: str) -> str:
    p = path.strip()
    if p.startswith(API):
        p = p[len(API):]
    return p.lstrip("/")


def guard(path: str) -> str:
    p = normalise(path)
    if p.lower().startswith("search/") or p.lower() == "search":
        raise SearchRefused(f"search request refused: {p[:80]}")
    return p


def is_rate_limit(status: int, headers: dict, data) -> bool:
    if status not in (403, 429):
        return False
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if h.get("x-ratelimit-remaining") == "0":
        return True
    msg = json.dumps(data)[:600].lower() if data is not None else ""
    return status == 429 or "rate limit" in msg or "abuse" in msg


class Client:
    def __init__(self, token: str, log=None, sleep=time.sleep, clock=time.time, transport=None):
        if not token:
            raise RuntimeError("GITHUB_TOKEN missing: no session-route fallback exists")
        self.token = token
        self.remaining: int | None = None
        self.limit: int | None = None
        self.reset: int | None = None
        self.n_requests = 0
        self.ceiling: int | None = None  # attempts this client may make (the job sets 2,280 minus earlier runs)
        self._last = 0.0
        self._log = log  # callable(dict) or None
        self._sleep, self._clock = sleep, clock
        self._transport = transport or self._urllib

    # ------------------------------------------------------------------ rate handling
    def _rate(self, headers: dict) -> None:
        h = {k.lower(): v for k, v in (headers or {}).items()}
        if h.get("x-ratelimit-resource", "core") != "core":
            return
        if "x-ratelimit-remaining" in h:
            self.remaining = int(h["x-ratelimit-remaining"])
            self.limit = int(h.get("x-ratelimit-limit") or 0) or self.limit
            self.reset = int(h.get("x-ratelimit-reset") or 0) or self.reset

    def below_floor(self) -> bool:
        return self.remaining is not None and bool(self.limit) and self.remaining < FLOOR * self.limit

    def _nap(self, seconds: float, why: str) -> None:
        if seconds > MAX_SLEEP:
            raise Pause(f"{why}: wait {seconds:.0f}s > {MAX_SLEEP:.0f}s")
        if seconds > 0:
            self._sleep(seconds)

    def _wait(self, floor: bool = True) -> None:
        if floor and self.below_floor():
            raise Pause(f"rate floor: remaining {self.remaining} < {FLOOR:.0%} of limit {self.limit}")
        gap = PACE - (self._clock() - self._last)
        if gap > 0:
            self._sleep(gap)
        self._last = self._clock()

    # ------------------------------------------------------------------ transport
    def _urllib(self, path: str) -> tuple[int, dict, object]:
        req = urllib.request.Request(f"{API}/{path}", method="GET", headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                try:
                    data = json.loads(raw or b"null")
                except json.JSONDecodeError:
                    data = {"raw": raw[:500].decode(errors="replace")}
                return r.status, dict(r.headers), data
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body[:500]}
            return e.code, dict(e.headers or {}), data
        except Exception as e:  # network error
            return 0, {}, {"exception": repr(e)[:300]}

    def get(self, path: str, floor: bool = True) -> tuple[int, object, dict]:
        """GET ``path``. Returns (status, data, headers).

        Rate-limit responses wait (within MAX_SLEEP) and retry; transport errors and 5xx are tried
        FIVE_XX_ATTEMPTS times in all, then the last answer is returned (the caller marks the field incomplete).
        A 403 that is not a rate-limit response raises AccessDenied. ``floor=False`` is used only for the job's own
        checkpoint-reference calls on this repository (1-2 attempts, still paced and counted)."""
        p = guard(path)
        fails = limited = 0
        while True:
            if self.ceiling is not None and self.n_requests >= self.ceiling:
                raise Pause(f"attempt ceiling reached: {self.n_requests}")
            self._wait(floor)
            self.n_requests += 1
            st, hd, data = self._transport(p)
            self._rate(hd)
            if self._log:
                self._log({"path": p, "status": st, "resource": {k.lower(): v for k, v in (hd or {}).items()}
                           .get("x-ratelimit-resource", ""), "remaining": self.remaining, "limit": self.limit})
            if is_rate_limit(st, hd, data):
                h = {k.lower(): v for k, v in (hd or {}).items()}
                ra = int(h.get("retry-after") or 0)
                if ra:
                    wait = ra + 1
                elif h.get("x-ratelimit-remaining") == "0" and h.get("x-ratelimit-reset"):
                    wait = max(int(h["x-ratelimit-reset"]) - self._clock(), 0) + 3
                else:
                    wait = 60
                limited += 1
                if limited > RATE_LIMIT_RETRIES:
                    raise Pause(f"rate-limit response {limited} times on {p[:80]}")
                sys.stderr.write(f"rate limited ({st}) on {p[:80]}: wait {wait:.0f}s\n")
                self._nap(wait, "rate-limit response")
                continue
            if st == 403:
                raise AccessDenied(f"403 on {p[:120]}: {json.dumps(data)[:300]}")
            if st == 0 or st >= 500:
                fails += 1
                if fails >= FIVE_XX_ATTEMPTS:
                    return st, data, hd
                self._sleep(5 * fails)
                continue
            return st, data, hd


def from_env(log=None) -> Client:
    return Client(token=os.environ.get("GITHUB_TOKEN") or "", log=log)
