#!/usr/bin/env python3
# usage (from the repository root): python3 harness/culprit/review_r019b/trivial_rules.py CLONE_DIR > harness/culprit/review_r019b/trivial-rules.json
"""Trivial rules on kind a2 (placed and reland) against the upstream window: largest diff (lines changed), the
commit touching the red test's file (newest such), and the newest commit touching any non-test .py file. The window
is the k first-parent commits after the (upstream) green commit; the planted commit is the original commit at
position p with the mutation folded in, so its diff size is the original one plus one line."""
import json, glob, subprocess, sys, os, collections, re
SP = sys.argv[1]
def summ(n):
    if n == 'cachetools': return {'url': 'https://github.com/tkem/cachetools'}
    return json.load(open(sorted(glob.glob(f'harness/results/*/{n}.summary.json'), reverse=True)[0]))
def git(repo, *a):
    return subprocess.run(['git', '-C', repo, *a], capture_output=True, text=True).stdout
rows = [json.loads(l) for f in sorted(glob.glob('harness/culprit/results/a-*.jsonl')) for l in open(f)]
rows = [r for r in rows if r.get('green_run') == 'pass' and r.get('red_run') == 'fail']
res = collections.Counter(); n = collections.Counter(); skipped = 0
for r in rows:
    name = r['repo']; d = f"{SP}/{name}"
    if not os.path.exists(d):
        subprocess.run(['git', 'clone', '-q', summ(name)['url'], d], check=True)
    k = int(r['k']); green = r.get('green')
    if not green or git(d, 'cat-file', '-t', green).strip() != 'commit':
        skipped += 1; continue
    chain = git(d, 'rev-list', '--first-parent', '--reverse', f'{green}..origin/HEAD').split()[:k]
    if len(chain) < k:
        skipped += 1; continue
    tp = int(r['truth_position']); shape = r['shape']
    test_file = r['red_test'].split('::')[0]
    sizes, touches_test, touches_src = [], [], []
    for c in chain:
        ns = git(d, 'show', '--numstat', '--format=', '--first-parent', c)
        tot = 0; files = []
        for line in ns.splitlines():
            p = line.split('\t')
            if len(p) == 3:
                a, b, f = p; files.append(f)
                tot += (int(a) if a.isdigit() else 0) + (int(b) if b.isdigit() else 0)
        sizes.append(tot); touches_test.append(test_file in files)
        touches_src.append(any(f.endswith('.py') and not re.search(r'(^|/)tests?/|test_', f) for f in files))
    n[shape] += 1
    if max(range(k), key=lambda i: sizes[i]) + 1 == tp: res[(shape, 'largest_diff')] += 1
    tt = [i + 1 for i in range(k) if touches_test[i]]
    if tt and tt[-1] == tp: res[(shape, 'newest_touching_test_file')] += 1
    if tt and tt[0] == tp: res[(shape, 'oldest_touching_test_file')] += 1
    ts = [i + 1 for i in range(k) if touches_src[i]]
    if ts and ts[-1] == tp: res[(shape, 'newest_touching_source')] += 1
    if ts and ts[0] == tp: res[(shape, 'oldest_touching_source')] += 1
print(json.dumps({'cases': dict(n), 'skipped': skipped, 'correct': {f'{a}:{b}': v for (a, b), v in sorted(res.items())}}, indent=1))
