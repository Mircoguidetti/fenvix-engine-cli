#!/usr/bin/env python3
# usage (from the repository root): python3 harness/culprit/review_r019b/stale_d.py CLONE_DIR > harness/culprit/review_r019b/stale-d.jsonl
"""Reconstruct round-1 step-4 commit probes (orderdep.find_commit) from the verdict sequence, and check for each
consecutive probe pair whether a .py file differs between the two commits with the same size (the condition under
which a same-second checkout runs stale bytecode). Prints per-row results as JSON lines."""
import json, ast, glob, subprocess, sys, collections
SP = sys.argv[1]
rows = [json.loads(l) for l in open('harness/culprit/results/d.jsonl')]
rows = [r for r in rows if 'finder_correct' in r]
def git(repo, *a):
    return subprocess.run(['git', '-C', repo, *a], capture_output=True, text=True).stdout
def summ(n):
    return json.load(open(sorted(glob.glob(f'harness/results/*/{n}.summary.json'), reverse=True)[0]))
repos = {}
for r in rows:
    n = r['repo']
    if n not in repos:
        s = summ(n); d = f"{SP}/{n}"
        import os
        if not os.path.exists(d):
            subprocess.run(['git', 'clone', '-q', '--filter=blob:none', s['url'], d], check=True)
        repos[n] = d
def py_sizes(repo, sha):
    out = git(repo, 'ls-tree', '-r', '-l', sha)
    res = {}
    for line in out.splitlines():
        meta, path = line.split('\t', 1)
        f = meta.split()
        if path.endswith('.py') and f[1] == 'blob':
            res[path] = (f[2], f[3])
    return res
out = []
for r in rows:
    repo = repos[r['repo']]
    st = r['finder_steps']; st = ast.literal_eval(st) if isinstance(st, str) else st
    cs = [x for x in st if x['why'].startswith(('back', 'bisect', 'skip'))]
    chain = git(repo, 'rev-list', '--first-parent', '--max-count=513', r['red']).split()
    # simulate find_commit consuming verdicts
    it = iter(cs); probes = []
    def nxt(i):
        x = next(it); probes.append((i, x['verdict'], x['wall'])); return x['verdict']
    known = {0: 'fail'}; d = 1; good = None
    try:
        while d < len(chain):
            v = nxt(d); known[d] = v
            if v in ('pass', 'missing'):
                good = d; break
            d *= 2
        if good is not None:
            lo, hi = good, max(i for i, v in known.items() if i < good and v == 'fail')
            while lo - hi > 1:
                mid = (lo + hi) // 2
                v = nxt(mid); known[mid] = v
                if v == 'fail': hi = mid
                elif v in ('pass', 'missing'): lo = mid
                else:
                    j = mid + 1
                    while j < lo and known.get(j) is None:
                        vj = nxt(j); known[j] = vj
                        if vj != 'error': break
                        j += 1
                    if known.get(j) == 'fail': hi = j
                    elif known.get(j) in ('pass', 'missing'): lo = j
                    else: break
        ok = (len(probes) == len(cs)) and chain[hi] == r['finder_named']
    except StopIteration:
        ok = False
    pairs = 0; ss = 0; ss_short = 0; exp_pairs = []
    prev_sha = r['red']; prev_wall = None  # the red full run precedes the polluter steps (same commit)
    for i, v, w in probes:
        sha = chain[i]
        if prev_wall is not None:
            a, b = py_sizes(repo, prev_sha), py_sizes(repo, sha)
            same = [p for p in a if p in b and a[p][0] != b[p][0] and a[p][1] == b[p][1]]
            pairs += 1
            if same:
                ss += 1
                if prev_wall < 1.0: ss_short += 1; exp_pairs.append(1.0 - prev_wall)
        prev_sha, prev_wall = sha, w
    out.append({'repo': r['repo'], 'victim': r['victim'], 'reconstructed': ok, 'probes': len(probes),
                'pairs': pairs, 'same_size_pairs': ss, 'same_size_pairs_prev_under_1s': ss_short,
                "finder_correct": r["finder_correct"], "p_same_second": [round(x, 2) for x in exp_pairs]})
    print(json.dumps(out[-1]), flush=True)
