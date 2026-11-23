#!/usr/bin/env python3
"""Draw the 20 pull requests per family for the hand rules check (random.Random(1).sample of the family pool
after the family rule; pool sorted by URL). Prints them for reading; verdicts go to rules_check.jsonl by hand."""
import random
import sys

from count1_run import load_pool


def draw(fam: str) -> list[dict]:
    pool = sorted(load_pool(fam), key=lambda r: r["url"])
    return random.Random(1).sample(pool, 20)


if __name__ == "__main__":
    for fam in sys.argv[1:]:
        print(f"##### {fam}: pool {len(load_pool(fam))}")
        for r in draw(fam):
            print(f"--- {r['url']} | author={r['author']} ({r['author_type']}) | {r['merged_at']}")
            print(f"    TITLE: {r['title'][:150]}")
            print(f"    BODY: {r['body_head'][:420]!r}")
