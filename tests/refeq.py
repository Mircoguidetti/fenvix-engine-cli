"""Comparing a trace or a store written by the ROUND-1 REFERENCE loop with one written by the current path.

Several tests run the same project twice, once with the frozen Python reference implementation and once with
the current one, and compare what the two recorded byte for byte. That comparison is about the engine's
ACCOUNTING -- the inputs, the events, the keys, the outcomes -- and the general rule's findings cannot be part
of it, for two measured reasons:

1. the reference loop is PYTHON code sitting between the standard library and the sensor, so the frame the
   sensor resolves as "whose call is it" is the reference's own. MEASURED on `test_network_rust.py`: the same
   `select.poll` is reported at `socketserver.py:231` by one path and at `selectors.py:338` by the other;
2. an operation the current path performs in Rust is performed by the reference in Python, where a Python
   sensor can see it. MEASURED on the same test: the reference refuses two `_socket` names the current path
   never sees, and nothing else differs.

So these comparisons strip the rule's findings and compare everything else, and in their place they assert the
VERDICT: the same tests must come out refused in both paths. That is what would break if one implementation
proved a test the other refuses, which is the only difference that would matter.

Nothing here is used by a test of the rule itself: `tests/test_provable_general_rule.py` and
`tests/attacks.py` assert the findings directly, on one implementation.
"""
from __future__ import annotations

import json
import re

#: the header's precompile duration is the only wall-clock value in a trace
PRECOMPILE = re.compile(rb'"precompile_s":[0-9.]+,')

_GAP_PREFIX = "unaccounted."


def strip_gaps(raw: bytes) -> tuple[bytes, dict]:
    """A trace without the rule's findings, and which tests had one.

    Removed: the `unaccounted.*` EVENTS, the per-test list of refused names, the header's
    `not_proven_outside_tests`, and the three per-test values that are hashes over the events (`fingerprint`,
    `counts`, `n_events`) -- every remaining event is still compared one by one, which is what the fingerprint
    covers.
    """
    out, refused = [], {}
    for line in PRECOMPILE.sub(b"", raw).decode().splitlines():
        d = json.loads(line)
        if d.get("type") == "test":
            events = d.get("events") or []
            d["events"] = [e for e in events if not str(e.get("o", "")).startswith(_GAP_PREFIX)]
            if len(d["events"]) != len(events):
                d.pop("fingerprint", None)
                d.pop("counts", None)
                d.pop("n_events", None)
            if d.pop("unaccounted", None):
                refused[d["nodeid"]] = True
        elif d.get("type") == "header":
            meta = d.get("meta") or {}
            meta.pop("not_proven_outside_tests", None)
        out.append(json.dumps(d, sort_keys=True))
    return ("\n".join(out)).encode(), refused


def same_but_the_rules_findings(ref: bytes, new: bytes) -> None:
    """Assert the two traces agree on everything but the rule's findings, and on which tests were refused."""
    cr, rr = strip_gaps(ref)
    cn, rn = strip_gaps(new)
    lines_ref, lines_new = cr.decode().splitlines(), cn.decode().splitlines()
    assert len(lines_ref) == len(lines_new), (len(lines_ref), len(lines_new))
    for a, b in zip(lines_ref, lines_new):
        assert a == b
    assert cr == cn
    assert rr == rn, ("one path refused a test the other did not", rr, rn)
