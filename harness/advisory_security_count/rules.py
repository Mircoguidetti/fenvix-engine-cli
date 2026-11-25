"""Pre-registered rules (PREREG.md §1-§3) as code: frame, order, label rules, stop rule, statistics.

Pure functions only (no network, no files), shared by the listing, the reading tools, report.py and verify.py.
"""
from __future__ import annotations

import math
import random
import re

ECOSYSTEMS = ["npm", "pip", "rubygems", "maven", "composer", "go", "nuget"]

CWE_GROUPS = {
    "authorization and access": [284, 285, 639, 862, 863, 266, 269, 732],
    "authentication bypass": [287, 288, 290, 294, 306],
    "data to the wrong party": [200, 201, 359, 488, 524, 668, 226],
    "session and expiry": [298, 324, 384, 613, 672],
    "concurrency, shared state and order": [362, 364, 366, 367, 543, 567, 662, 667, 820, 821, 1223, 1265],
    "single-use and workflow": [837, 841, 799],
}
CWE_LIST = frozenset(f"CWE-{n}" for g in CWE_GROUPS.values() for n in g)
NO_INFO_CWES = frozenset({"NVD-CWE-Other", "NVD-CWE-noinfo", "CWE-Other"})

NARROW_SRC = (
    r"\b(race[- ]?conditions?|data races?|concurren\w*|simultaneous\w*|parallel requests?|toctou|tocttou"
    r"|time[- ]of[- ]check|cache[- ]?key\w*|thread[- ]?locals?|async\w*local\w*|multi[- ]?tenan\w*"
    r"|cross[- ](tenant|user|account)s?|another (user|tenant|customer|organi[sz]ation|account)s?"
    r"|other (users?|tenants?|customers?|accounts?|organi[sz]ations?)|wrong (users?|sessions?|tenants?)"
    r"|session (fixation|mix\w*|leak\w*|confusion)|double[- ]?(spend|us|redeem|submi)\w*|replay\w*"
    r"|in parallel|at the same time|non-?atomic\w*)"
)
BROAD_EXTRA_SRC = (
    r"\b(cache[ds]?|caching|shared (state|instances?|memory)|singletons?|global (state|variables?)|async\w*"
    r"|background (jobs?|tasks?|workers?)|twice|re-?us\w*|expir\w*)\b"
)
NARROW = re.compile(NARROW_SRC, re.IGNORECASE)
BROAD_EXTRA = re.compile(BROAD_EXTRA_SRC, re.IGNORECASE)

EXCLUSION_REASONS = frozenset({
    "not-web", "one-principal", "injection", "xss", "csrf", "path-traversal", "ssrf", "memory", "dos", "crypto",
    "supply-chain", "open-redirect", "no-principal-disclosure", "no-I1-I3",
})
CLASSES = frozenset({"ours", "read-the-code", "unclear"})
SUBCLASSES = frozenset({"O1-shared-state", "O2-context-loss", "O3-concurrency", "O4-order", "O5-time"})
LABEL_FIELDS = ("ghsa_id", "inclusion", "reason", "class", "subclass", "quote", "reader", "batch")

CHECKPOINT_INCLUDED = 300
DOUBLE_READ_SAMPLE = 40
KAPPA_MIN = 0.6
CONFIRMED_MIN = 0.8


# ---------------------------------------------------------------- frame

def narrow_match(text: str) -> bool:
    return NARROW.search(text or "") is not None


def broad_match(text: str) -> bool:
    return narrow_match(text) or BROAD_EXTRA.search(text or "") is not None


def cwe_ids(adv: dict) -> list[str]:
    return [c.get("cwe_id") for c in (adv.get("cwes") or []) if c and c.get("cwe_id")]


def adv_text(adv: dict) -> str:
    return (adv.get("summary") or "") + "\n" + (adv.get("description") or "")


def memberships(adv: dict) -> dict[str, bool]:
    """Which of the routes (a), (b), (c) of PREREG §1.2 hold for ``adv``."""
    ids = cwe_ids(adv)
    text = adv_text(adv)
    no_info = all(i in NO_INFO_CWES for i in ids)  # also true for null / empty cwes
    return {
        "a": any(i in CWE_LIST for i in ids),
        "b": narrow_match(text),
        "c": no_info and broad_match(text),
    }


def route(adv: dict) -> str | None:
    """First route that holds, or None when ``adv`` is not a candidate."""
    m = memberships(adv)
    for k in ("a", "b", "c"):
        if m[k]:
            return k
    return None


def is_withdrawn(adv: dict) -> bool:
    return bool(adv.get("withdrawn_at"))


def merge_listing(pages: dict[str, list[dict]]) -> list[dict]:
    """``pages`` maps listing ecosystem -> advisories listed for it. Returns one row per ``ghsa_id`` (withdrawn
    dropped), with ``ecosystems`` = sorted union of listing ecosystems and the package ecosystems among the seven."""
    rows: dict[str, dict] = {}
    for eco, advs in pages.items():
        for adv in advs:
            if is_withdrawn(adv):
                continue
            gid = adv["ghsa_id"]
            row = rows.get(gid)
            if row is None:
                row = dict(adv)
                row["ecosystems"] = set()
                rows[gid] = row
            row["ecosystems"].add(eco)
            for v in adv.get("vulnerabilities") or []:
                e = ((v or {}).get("package") or {}).get("ecosystem")
                if e and e.lower() in ECOSYSTEMS:
                    row["ecosystems"].add(e.lower())
    out = []
    for gid in sorted(rows):
        r = rows[gid]
        r["ecosystems"] = sorted(r["ecosystems"])
        out.append(r)
    return out


def reading_order(candidate_ids: list[str]) -> list[str]:
    order = sorted(set(candidate_ids))
    random.Random(5).shuffle(order)
    return order


# ---------------------------------------------------------------- label rules

def norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def quote_ok(quote: str | None, material_text: str) -> bool:
    return bool(quote and norm_ws(quote)) and norm_ws(quote) in norm_ws(material_text)


def effective_label(label: dict, material_text: str) -> dict:
    """Apply the code-decided label rules: an included row whose quote is missing or not a verbatim substring of
    the stored material becomes ``unclear`` (``quote_flag`` set when a quote was given but not found)."""
    out = dict(label)
    out["quote_flag"] = None
    if out.get("inclusion") != "included":
        return out
    q = out.get("quote")
    if not q or not norm_ws(q):
        out["class"], out["subclass"], out["quote_flag"] = "unclear", None, "missing"
    elif not quote_ok(q, material_text):
        out["class"], out["subclass"], out["quote_flag"] = "unclear", None, "not-verbatim"
    if out["class"] != "ours":
        out["subclass"] = None
    return out


def validate_label(label: dict) -> list[str]:
    errs = []
    for f in LABEL_FIELDS:
        if f not in label:
            errs.append(f"missing field {f}")
    inc = label.get("inclusion")
    if inc == "excluded":
        if label.get("reason") not in EXCLUSION_REASONS:
            errs.append(f"bad reason {label.get('reason')!r}")
        if label.get("class") is not None:
            errs.append("excluded row with a class")
    elif inc == "included":
        if label.get("reason") is not None:
            errs.append("included row with a reason")
        if label.get("class") not in CLASSES:
            errs.append(f"bad class {label.get('class')!r}")
        if label.get("class") == "ours" and label.get("subclass") not in SUBCLASSES:
            errs.append(f"ours without a valid subclass: {label.get('subclass')!r}")
        if label.get("class") != "ours" and label.get("subclass") is not None:
            errs.append("subclass on a non-ours row")
    else:
        errs.append(f"bad inclusion {inc!r}")
    return errs


def is_ours(label: dict | None) -> bool:
    return bool(label) and label.get("inclusion") == "included" and label.get("class") == "ours"


def apply_disputes(labels: dict[str, dict], second: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """A first-reader ``ours`` row the second reader does not call ``ours`` (excluded counts as not-ours) becomes
    ``unclear``. A different O-subclass is not a dispute. Returns (new labels, disputed ids)."""
    out = {k: dict(v) for k, v in labels.items()}
    disputed = []
    for gid, lab in labels.items():
        if is_ours(lab) and gid in second and not is_ours(second[gid]):
            out[gid]["class"], out[gid]["subclass"] = "unclear", None
            out[gid]["disputed"] = True
            disputed.append(gid)
    return out, sorted(disputed)


# ---------------------------------------------------------------- stop rule

def decide(ours: int, included: int, at_checkpoint: bool, all_read: bool, budget_over: bool = False) -> str | None:
    """Return "CONTINUE", "DROP", "NO DECISION" or None (keep reading). Integers only (gate note 6)."""
    if at_checkpoint or all_read:
        if 100 * ours < 15 * included:
            return "DROP"
        if ours >= 30:
            return "CONTINUE"
        if all_read:
            return "DROP"
    if budget_over:
        return "NO DECISION"
    return None


def checkpoint_prefix(order: list[str], labels: dict[str, dict], target: int = CHECKPOINT_INCLUDED) -> int | None:
    """Number of rows (in reading order) up to and including the ``target``-th included row, or None."""
    n = 0
    for i, gid in enumerate(order):
        lab = labels.get(gid)
        if lab is None:
            return None
        if lab.get("inclusion") == "included":
            n += 1
            if n == target:
                return i + 1
    return None


# ---------------------------------------------------------------- statistics

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (centre - half, centre + half)


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    a = sum(1 for x, y in pairs if x and y)
    d = sum(1 for x, y in pairs if not x and not y)
    po = (a + d) / n
    p1 = sum(1 for x, _ in pairs if x) / n
    p2 = sum(1 for _, y in pairs if y) / n
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    if pe == 1:
        return 1.0 if po == 1 else 0.0
    return (po - pe) / (1 - pe)


def double_read_ok(kappa: float | None, confirmed: float | None) -> bool:
    return kappa is not None and confirmed is not None and kappa >= KAPPA_MIN and confirmed >= CONFIRMED_MIN


def double_read_sample(labels: dict[str, dict], ids_in_scope: list[str]) -> list[str]:
    """Every ``ours`` row plus random.Random(6).sample(sorted not-ours included, 40) (all if fewer)."""
    ours = sorted(g for g in ids_in_scope if is_ours(labels.get(g)))
    notours = sorted(g for g in ids_in_scope
                     if labels.get(g, {}).get("inclusion") == "included" and not is_ours(labels.get(g)))
    picked = notours if len(notours) <= DOUBLE_READ_SAMPLE else random.Random(6).sample(notours, DOUBLE_READ_SAMPLE)
    return ours + sorted(picked)


def double_read_input_order(ids: list[str]) -> list[str]:
    out = sorted(ids)
    random.Random(7).shuffle(out)
    return out


# ---------------------------------------------------------------- material helpers

REF_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/(commit/([0-9a-fA-F]{7,40})|pull/(\d+)|compare/([^\s#?]+?\.\.\.?[^\s#?]+))"
    r"(?:[/#?].*)?$")


def repo_of(source_code_location: str | None) -> str | None:
    m = re.match(r"^https?://github\.com/([^/]+)/([^/#?]+)", source_code_location or "")
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2).removesuffix('.git')}".lower()


def fix_refs(adv: dict, limit: int = 3) -> list[dict]:
    """Commit / pull / compare references in the advisory's source_code_location repository, first ``limit``."""
    repo = repo_of(adv.get("source_code_location"))
    if not repo:
        return []
    out, seen = [], set()
    for url in adv.get("references") or []:
        u = url if isinstance(url, str) else (url or {}).get("url", "")
        m = REF_RE.match(u.strip())
        if not m or f"{m.group(1)}/{m.group(2)}".lower() != repo:
            continue
        o, r = m.group(1), m.group(2)
        if m.group(4):
            ref = {"kind": "commit", "owner": o, "repo": r, "sha": m.group(4)}
        elif m.group(5):
            ref = {"kind": "pull", "owner": o, "repo": r, "number": int(m.group(5))}
        else:
            ref = {"kind": "compare", "owner": o, "repo": r, "range": m.group(6)}
        key = tuple(sorted(ref.items()))
        if key in seen:
            continue
        seen.add(key)
        ref["url"] = u.strip()
        out.append(ref)
        if len(out) == limit:
            break
    return out


LOCKFILES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "Gemfile.lock",
                       "poetry.lock", "Pipfile.lock", "go.sum", "Cargo.lock", "packages.lock.json",
                       "npm-shrinkwrap.json"})
VENDOR_PARTS = ("vendor/", "node_modules/", "third_party/", "dist/", "build/")


def skip_file(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if base in LOCKFILES or path.endswith(".min.js"):
        return True
    p = "/" + path
    return any(("/" + v) in p for v in VENDOR_PARTS)


def cap_files(files: list[dict], max_files: int = 20, max_lines: int = 400) -> list[dict]:
    out = []
    for f in files or []:
        name = f.get("filename", "")
        if skip_file(name):
            continue
        patch = f.get("patch") or ""
        lines = patch.split("\n")
        out.append({"filename": name, "status": f.get("status"), "patch": "\n".join(lines[:max_lines]),
                    "patch_truncated": len(lines) > max_lines})
        if len(out) == max_files:
            break
    return out


def material_text(mat: dict) -> str:
    """The text a quote must come from (PREREG §2.3 interpretation)."""
    parts = [mat.get("summary") or "", mat.get("description") or ""]
    for c in mat.get("cwes") or []:
        parts.append(f"{c.get('cwe_id', '')} {c.get('name', '')}")
    parts.extend(mat.get("references") or [])
    for fx in mat.get("fixes") or []:
        for k in ("title", "body", "message"):
            if fx.get(k):
                parts.append(fx[k])
        for c in fx.get("commits") or []:
            if c.get("message"):
                parts.append(c["message"])
            for f in c.get("files") or []:
                parts.append(f.get("filename", ""))
                parts.append(f.get("patch", ""))
    return "\n".join(parts)
