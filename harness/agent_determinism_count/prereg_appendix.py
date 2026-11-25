#!/usr/bin/env python3
"""The PREREG.md appendix (every query and regex verbatim), generated from rules.py.

Usage: prereg_appendix.py --write   (replaces everything after the appendix marker in PREREG.md)
A test checks that PREREG.md ends with exactly this text, so a later change to a query or regex in rules.py fails
until it is listed in CHANGES.md and the appendix is regenerated.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules as R  # noqa: E402

MARK = "<!-- generated: python3 prereg_appendix.py --write -->"


def appendix() -> str:
    L = [MARK, ""]
    L += ["### Regexes", ""]
    for name in ("PAIN_RE", "MODEL_RE", "MARKER_RE", "INSTALL_RE", "RUNNER_RE", "STRIPPED_RUNNER_RE", "PM_RE",
                 "HELP_RE", "ACTION_TEST_RE", "ACTION_NOT_RE", "RETRIEVAL_ONLY"):
        L.append(f"- `{name}`: `{getattr(R, name).pattern}`")
    L.append("- `STRIP_RES` (applied repeatedly, in order): " + ", ".join(f"`{x.pattern}`" for x in R.STRIP_RES))
    L += ["", "### §1 discovery queries (default probe outcome; the variants follow the §0.2b rules)", ""]
    for fam, title in (("code", "A / S1, search/code"), ("issues", "B / S2, search/issues"),
                       ("commits", "C / S3, search/commits")):
        qs = [d["q"] for d in R.discovery_queries() if d["family"] == fam]
        L += [f"#### {title} ({len(qs)} queries)", ""] + [f"- `{q}`" for q in qs] + [""]
    L += ["Plus, for each model-answer recording package `<pkg>` from §0.2d: " +
          ", ".join(f"`<pkg> {f}`" for f in R.PKG_FILES) + ".", ""]
    L += ["If the §0.2b OR check fails on issues, each S2 cost query `... <q> (llm OR openai OR agent)` becomes "
          "three queries `... <q> llm`, `... <q> openai`, `... <q> agent`. If GitHub requires `is:issue`/`is:pr`, "
          "every issues query gets ` is:issue` and ` is:pr` appended (two queries).", ""]
    L += ["### §3.2 repository queries (for repository `<r>`)", ""]
    L += [f"- `{q}`" for q in R.repo_text_queries("<r>", "issues")]
    L += [f"- `{q}`" for q in R.repo_text_queries("<r>", "commits")]
    L += ["", "Single-term split (OR check failed for that kind): each `(a OR b OR ...)` group becomes one query per "
          "term, e.g. `" + R.repo_text_queries("<r>", "issues", or_ok=False)[0] + "`.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = HERE / "PREREG.md"
    text = p.read_text()
    head = text.split("<!-- generated:", 1)[0]
    if "--write" in argv:
        p.write_text(head + appendix())
    else:
        print(appendix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
