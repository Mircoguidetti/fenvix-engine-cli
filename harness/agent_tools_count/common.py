"""``seeded_order`` copied verbatim from origin/claude/agent-pr-scan:harness/agent_pr_scan/common.py (line 84)."""
from __future__ import annotations

import random


def seeded_order(pools: dict[str, list[dict]], seed: int = 1) -> list[dict]:
    """Shuffle each month's pool with random.Random(seed) (one generator, months in sorted order), then take
    one per month in turn, so every month contributes equally until it runs out."""
    rng = random.Random(seed)
    lists = []
    for month in sorted(pools):
        lst = sorted(pools[month], key=lambda r: r["url"])
        rng.shuffle(lst)
        lists.append(lst)
    out, i = [], 0
    while any(i < len(l) for l in lists):
        for l in lists:
            if i < len(l):
                out.append(l[i])
        i += 1
    return out
