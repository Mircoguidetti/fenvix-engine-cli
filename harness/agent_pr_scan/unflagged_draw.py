#!/usr/bin/env python3
"""Draw the 20 unflagged, test-touching autonomous pull requests for the miss check:
random.Random(1).sample over the URL-sorted primary-denominator rows with tier NONE and >=1 test file changed."""
import json, random
from common import HERE, read_jsonl
def draw():
    rows = [r for r in read_jsonl(HERE / "count1_rows.jsonl") if r["phase"] == "autonomous"
            and r["n_base_test_files"] > 0 and r["tier"] == "NONE" and r["n_test_files_changed"] > 0]
    rows.sort(key=lambda r: r["url"])
    return len(rows), random.Random(1).sample(rows, 20)
if __name__ == "__main__":
    n, s = draw()
    print("eligible", n)
    for r in s: print(json.dumps({"url": r["url"]}))
