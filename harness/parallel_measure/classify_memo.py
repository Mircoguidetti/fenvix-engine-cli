#!/usr/bin/env python3
"""classify.py with measure.trace_tests memoised (Lane A, 2026-11-23). Same arguments and output as classify.py.

classify.reported() re-reads every S*/P* trace for each THEIRS test; with agentic-qe's 1.2 GB traces and many
not-identical tests that took hours. trace_tests(path) is a pure function of the file, so caching it per path changes
no result. classify.py, measure.py stay byte-identical (spec AC1); this wrapper only patches the function at runtime.
Usage: classify_memo.py --out DIR --name REPO [--spec specs.json] [--bugs DIR]
"""
import functools

import classify
import measure

_cached = functools.lru_cache(maxsize=None)(measure.trace_tests)
measure.trace_tests = _cached
classify.M.trace_tests = _cached

if __name__ == "__main__":
    classify.main()
