"""GitHub REST access (GET only): the workflow token (urllib) or the work session (``gh api``).

Rate rule (PREREG §0.5, rule 7 with gate note 4): User-Agent ``fenvix-research``; when the **core**
``X-RateLimit-Remaining`` < 50 sleep until reset; code search <= ``CODE_PER_MIN`` requests/min (9, or 4 while the
db-serial-count discovery shares the token); repository search <= 25/min; 403/429 with Retry-After / rate-limit text
or X-RateLimit-Reset: wait and retry (never an error).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UA = "fenvix-research"


def gap(per_min: float) -> float:
    return 60.0 / per_min + 0.05


def retry_seconds(msg: str, h: dict, now: float | None = None) -> float:
    """Wait after a rate-limit answer. The message ("try again in 7.9s" / "try again in 581.6ms") wins over the
    Retry-After header (GitHub sends a millisecond value there with the "ms" message); then the reset time; else 60."""
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
    def __init__(self, token: str | None = None, use_gh: bool = False, pace: float = 0.25,
                 code_per_min: float = 4, repo_per_min: float = 25):
        self.token, self.use_gh, self.pace = token, use_gh, pace
        self.code_gap, self.repo_gap = gap(code_per_min), gap(repo_per_min)
        self.remaining, self.limit, self.reset = {}, {}, {}
        self.n_requests = 0
        self._last = {"core": 0.0, "code": 0.0, "repo": 0.0}
        self.log = None  # optional callable(path, status, data, headers)

    def _rate(self, headers: dict) -> None:
        h = {k.lower(): v for k, v in headers.items()}
        res = h.get("x-ratelimit-resource", "core")
        if "x-ratelimit-remaining" in h:
            self.remaining[res] = int(h["x-ratelimit-remaining"])
            self.limit[res] = int(h.get("x-ratelimit-limit") or 0)
            self.reset[res] = int(h.get("x-ratelimit-reset") or 0)

    def _wait(self, kind: str) -> None:
        g = {"core": self.pace, "code": self.code_gap, "repo": self.repo_gap}[kind]
        w = g - (time.time() - self._last[kind])
        if w > 0:
            time.sleep(w)
        self._last[kind] = time.time()
        if kind == "core":  # the < 50 rule applies to the core resource only (note 4)
            rem = self.remaining.get("core")
            if rem is not None and rem < 50:
                sl = max(self.reset.get("core", 0) - time.time(), 0) + 3
                sys.stderr.write(f"core remaining {rem}: sleeping {sl:.0f}s\n")
                time.sleep(min(sl, 3700))

    def _once(self, path: str) -> tuple[int, dict, object]:
        if self.use_gh:
            r = subprocess.run(["gh", "api", "-i", "-X", "GET", "-H", f"User-Agent: {UA}", path],
                               capture_output=True, text=True)
            out = r.stdout.replace("\r\n", "\n")
            head, _, body = out.partition("\n\n")
            lines = head.splitlines()
            status = int(lines[0].split()[1]) if lines and lines[0].startswith("HTTP") else 0
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

    def get(self, path: str, kind: str = "core") -> tuple[int, object, dict]:
        """GET ``path`` (relative to the API root); kind in core|code|repo. Returns (status, data, headers).
        Rate-limit answers wait and retry without limit on attempts; transport errors and 5xx are retried 3 times."""
        errors = 0
        while True:
            self._wait(kind)
            self.n_requests += 1
            st, hd, data = self._once(path)
            self._rate(hd)
            if self.log:
                self.log(path, st, data, hd)
            msg = json.dumps(data)[:600].lower() if data is not None else ""
            h = {k.lower(): v for k, v in hd.items()}
            if st == 429 or (st == 403 and ("rate limit" in msg or "abuse" in msg or "retry-after" in h)):
                sl = retry_seconds(msg, h)
                sys.stderr.write(f"rate limited ({st}) on {path[:90]}: sleeping {sl:.0f}s (retry-after={h.get('retry-after')} msg={msg[:120]})\n")
                time.sleep(min(sl, 3700))
                continue
            if st == 0 or st >= 500:
                errors += 1
                if errors <= 3:
                    time.sleep(5 * errors)
                    continue
            return st, data, hd

    def paged(self, path: str, key: str | None = None, kind: str = "core", max_pages: int = 10**6):
        """All pages (per_page must be in path). Yields (status, data) per page; stops on a short page."""
        sep = "&" if "?" in path else "?"
        page = 1
        while page <= max_pages:
            st, data, hd = self.get(f"{path}{sep}page={page}", kind)
            yield st, data
            if st != 200:
                return
            items = data.get(key) if key and isinstance(data, dict) else data
            if not isinstance(items, list) or not re.search(r'rel="next"', hd.get("Link", hd.get("link", ""))):
                return
            page += 1


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def from_env(**kw) -> Client:
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        return Client(token=tok, **kw)
    return Client(use_gh=True, **kw)
