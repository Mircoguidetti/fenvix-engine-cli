#!/usr/bin/env python3
"""Runner-time estimate per repository for B2 and the drops the 8 h cap forces (spec B2.12). ESTIMATED: every run
costs A's median plain wall (prereg.json plain_wall_s_median_A); a replay state is 4 runs; seeds 1 run (+1 for the
URL-form probe of the commit seed); red-state search 1 plain run per candidate; a red or K2 replay 4 runs; cs.py on a
K2 state 2 runs (full + selection); a fault job 1 run. Mismatch reproduction (10 plain runs of one file) is not
estimated (only on a mismatch).
"""
import json
import sys

CAP_S = 8 * 3600
DROPS = ['k2b_replays', 'k2a_replays', 'red_search_beyond_5', 'faults_covered_elsewhere', 'prs_beyond_5',
         'commits_beyond_10']


def plan(r):
    return {'commits': len(r['b2_commits']), 'prs': len(r['b2_prs']), 'k2a': len(r['k2a']), 'k2b': 10,
            'red_search': 10, 'red_replays': 10, 'faults': 6, 'k2a_replays': True, 'k2b_replays': True}


def cost(p, P):
    runs = 0
    runs += 2 + p['prs']                     # commit seed + URL probe, one seed per PR merge-base
    runs += 4 * (p['commits'] + p['prs'])    # replays
    runs += p['red_search'] + 4 * p['red_replays']
    runs += p['faults']
    runs += 2 * (p['k2a'] + p['k2b'])        # cs.py free-tool count (always kept)
    runs += 4 * p['k2a'] * p['k2a_replays'] + 4 * p['k2b'] * p['k2b_replays'] + 2 * (p['k2b'] * p['k2b_replays'])  # + K2(b) seeds
    return runs * P


def estimate(r):
    P = r['plain_wall_s_median_A'] or 60.0
    p = plan(r)
    applied = []
    for d in DROPS:
        if cost(p, P) <= CAP_S:
            break
        if d == 'k2b_replays':
            p['k2b_replays'] = False
        elif d == 'k2a_replays':
            p['k2a_replays'] = False
        elif d == 'red_search_beyond_5':
            p['red_search'] = min(p['red_search'], 5); p['red_replays'] = min(p['red_replays'], 5)
        elif d == 'faults_covered_elsewhere':
            continue  # known only once channels are exercised on another repository: not applied in the estimate
        elif d == 'prs_beyond_5':
            p['prs'] = min(p['prs'], 5)
        elif d == 'commits_beyond_10':
            p['commits'] = min(p['commits'], 10)
        applied.append(d)
    under = False
    while cost(p, P) > CAP_S and p['commits'] > 5:
        p['commits'] -= 1
        under = True
    return {'plain_s': P, 'full_estimate_h': round(cost(plan(r), P) / 3600, 2), 'after_drops_h': round(cost(p, P) / 3600, 2),
            'drops': applied, 'plan': p, 'under_sampled': under or p['commits'] < 20 or p['prs'] < min(10, len(r['b2_prs'])),
            'over_cap_at_minimum': cost(p, P) > CAP_S}


if __name__ == '__main__':
    pre = json.load(open(sys.argv[1]))
    out = {n: estimate(r) for n, r in pre['repos'].items()}
    json.dump(out, sys.stdout, indent=1)
    print()
