"""GET-only GitHub REST access through the `gh` CLI (session route). Every request is logged to data/requests.jsonl.

Rules (PREREG "Access rules"): GET only, User-Agent fenvix-research, sleep until reset when X-RateLimit-Remaining
< 500, no search endpoint.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / os.environ.get("ASC_REQLOG", "data/requests.jsonl")
ROUTE = os.environ.get("ASC_ROUTE", "session")
UA = "fenvix-research"
MIN_REMAINING = 500


class HTTPError(Exception):
    def __init__(self, status: int, path: str, body: str):
        super().__init__(f"HTTP {status} for {path}: {body[:200]}")
        self.status, self.path, self.body = status, path, body


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def parse_response(raw: str) -> tuple[int, dict[str, str], str]:
    """Split `gh api -i` output into (status, headers lower-cased, body)."""
    head, _, body = raw.replace("\r\n", "\n").partition("\n\n")
    lines = head.split("\n")
    status = int(lines[0].split()[1])
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers, body


def next_link(link_header: str | None) -> str | None:
    for part in (link_header or "").split(","):
        seg = part.split(";")
        if len(seg) >= 2 and 'rel="next"' in seg[1]:
            return seg[0].strip().strip("<>")
    return None


def get(path: str, params: dict | None = None, retries: int = 4) -> tuple[int, dict[str, str], str]:
    """GET ``path`` (relative like /advisories or an absolute api.github.com URL). Returns (status, headers, body)."""
    if "/search/" in path:
        raise ValueError("search endpoints are not allowed")
    cmd = ["gh", "api", "-i", "-X", "GET", "-H", f"User-Agent: {UA}", "-H", "Accept: application/vnd.github+json",
           path]
    for k, v in (params or {}).items():
        cmd += ["-f", f"{k}={v}"]
    for attempt in range(retries + 1):
        p = subprocess.run(cmd, capture_output=True, text=True)
        raw = p.stdout
        try:
            status, headers, body = parse_response(raw)
        except (IndexError, ValueError):
            status, headers, body = 0, {}, raw + p.stderr
        _log({"t": _now(), "route": ROUTE, "method": "GET", "path": path, "params": params or {}, "status": status,
              "remaining": headers.get("x-ratelimit-remaining")})
        if status in (0, 502, 503, 504) and attempt < retries:
            time.sleep(5 * 2 ** attempt)
            continue
        if status == 403 and headers.get("x-ratelimit-remaining") == "0" and attempt < retries:
            _sleep_until(headers)
            continue
        break
    rem = headers.get("x-ratelimit-remaining")
    if rem is not None and rem.isdigit() and int(rem) < MIN_REMAINING:
        _sleep_until(headers)
    return status, headers, body


def _sleep_until(headers: dict[str, str]) -> None:
    reset = int(headers.get("x-ratelimit-reset") or time.time() + 60)
    wait = max(5, reset - int(time.time()) + 5)
    print(f"rate limit low ({headers.get('x-ratelimit-remaining')}); sleeping {wait}s", flush=True)
    time.sleep(wait)


def get_json(path: str, params: dict | None = None):
    status, headers, body = get(path, params)
    if status != 200:
        raise HTTPError(status, path, body)
    return json.loads(body), headers
