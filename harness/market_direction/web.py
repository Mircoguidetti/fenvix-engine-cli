"""Part 2 fetch tool (PREREG constants): Python requests, GET only, User-Agent fenvix-research, redirects followed
manually (at most 5), timeout 30 s. Classification text (§2.3, note 3) and the §2.3 regex rules."""
from __future__ import annotations

import datetime as dt
import html
import re
from urllib.parse import urljoin

UA = "fenvix-research"


def fetch(url: str, max_redirects: int = 5) -> dict:
    import requests
    hops = []
    cur = url
    for _ in range(max_redirects + 1):
        try:
            r = requests.get(cur, headers={"User-Agent": UA}, allow_redirects=False, timeout=30)
        except Exception as e:  # network / TLS / proxy refusal
            hops.append({"url": cur, "status": None, "error": repr(e)[:300]})
            return {"url": url, "final_url": cur, "status": None, "hops": hops, "text": "",
                    "error": repr(e)[:300], "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        hops.append({"url": cur, "status": r.status_code})
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            cur = urljoin(cur, r.headers["Location"])
            continue
        r.encoding = r.encoding or r.apparent_encoding
        return {"url": url, "final_url": cur, "status": r.status_code, "hops": hops, "text": r.text,
                "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    return {"url": url, "final_url": cur, "status": None, "hops": hops, "text": "", "error": "more than 5 redirects",
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]*>", " ", s)          # each tag replaced by a space
    s = re.sub(r"\s+", " ", s)              # whitespace collapsed
    s = html.unescape(s)                    # entities decoded
    return re.sub(r"\s+", " ", s).strip()


def class_text(page: str) -> tuple[str, str]:
    """(text, source) with source 'h1' or 'meta description' or ''."""
    page = page or ""
    m = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1\s*>", page)
    if m:
        t = _clean(m.group(1))
        if t:
            return t, "h1"
    for m in re.finditer(r"(?is)<meta\b[^>]*>", page):
        tag = m.group(0)
        if re.search(r"""(?i)\bname\s*=\s*["']?description["']?""", tag):
            mc = re.search(r"""(?is)\bcontent\s*=\s*(".*?"|'.*?'|[^\s>]+)""", tag)
            if mc:
                t = re.sub(r"\s+", " ", html.unescape(mc.group(1).strip("\"'"))).strip()
                if t:
                    return t, "meta description"
    return "", ""


AIW_CS = re.compile(r"\b(LLM|AI|GenAI)s?\b")
AIW_CI = re.compile(r"(?i)\b(agents?|agentic|models?)\b")
EW = re.compile(r"(?i)\b(eval\w*|observab\w*|monitor\w*|quality)\b")
CIW_CS = re.compile(r"\bCI\b")
CIW_CI = re.compile(r"(?i)\b(continuous integration|GitHub Actions|runners?|builds?|tests?|testing|test suites?|flaky)\b")
STRONG_CI = re.compile(r"(?i)\b(continuous integration|GitHub Actions|runners?|flaky)\b")


def classify(text: str, status=200, public: bool = False) -> str:
    """§2.3 rules in order. Returns T, E, borderline, public or UNVERIFIED."""
    if status != 200 or not (text or "").strip():
        return "UNVERIFIED"
    if public:
        return "public"
    aiw = bool(AIW_CS.search(text) or AIW_CI.search(text))
    ew = bool(EW.search(text))
    ciw = bool(CIW_CS.search(text) or CIW_CI.search(text))
    if ciw and (CIW_CS.search(text) or STRONG_CI.search(text)):
        return "T"
    if aiw and ew:
        return "E"
    if ciw and not aiw:
        return "T"
    return "borderline"
