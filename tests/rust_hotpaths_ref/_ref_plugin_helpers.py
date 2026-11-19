"""Pure helpers of ``python/detpy/plugin.py`` before they moved to Rust (round 2 of rust-hotpaths), verbatim."""


def _final_outcome(parts: dict) -> str:
    setup, call, teardown = parts.get("setup"), parts.get("call"), parts.get("teardown")
    if setup is not None and setup != "passed":
        main = setup if setup in ("skipped", "xfailed") else "error"
    elif call is not None:
        main = call
    else:
        main = "unknown"
    if teardown not in (None, "passed", "skipped"):
        main += "+teardown-error"
    return main
