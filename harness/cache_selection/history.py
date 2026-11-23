#!/usr/bin/env python3
"""Spec steps 1-2: merged PRs from plain git, their base, states and class.

Usage: python3 history.py <repo-key> <clone-dir>
Writes harness/cache_selection/data/<repo-key>/prs.json and prints a summary.
No GitHub API: PR heads come from `git ls-remote origin 'refs/pull/*/head'`.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPECS = json.load(open(os.path.join(HERE, '..', 'parallel_measure', 'specs.json')))
LOCKFILES = {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'npm-shrinkwrap.json', 'bun.lockb', 'bun.lock'}
DEP_KEYS = {'version', 'dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies',
            'overrides', 'resolutions', 'packageManager'}
BOT_RE = re.compile(r'(renovate|dependabot|github-actions|\[bot\]$)', re.I)


def git(d, *a, check=True):
    p = subprocess.run(['git', '-C', d] + list(a), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f'git {a}: {p.returncode} {p.stderr[-2000:]}')
    return p.stdout


def ensure_clone(key, d):
    url = SPECS[key]['repo']
    if not os.path.isdir(os.path.join(d, '.git')):
        subprocess.run(['git', 'clone', '--quiet', url, d], check=True)
    git(d, 'fetch', '--quiet', 'origin')
    head = git(d, 'symbolic-ref', 'refs/remotes/origin/HEAD').strip()
    default = head.split('/')[-1]
    ls = git(d, 'ls-remote', 'origin', 'refs/pull/*/head')
    nums = sorted({int(m) for m in re.findall(r'refs/pull/(\d+)/head', ls)}, reverse=True)[:150]
    specs = [f'+refs/pull/{n}/head:refs/remotes/pr/{n}' for n in nums]
    for i in range(0, len(specs), 50):
        git(d, 'fetch', '--quiet', 'origin', *specs[i:i + 50])
    return 'origin/' + default, nums, len(re.findall(r'refs/pull/(\d+)/head', ls))


def patch_id(d, rev):
    p1 = subprocess.run(['git', '-C', d, 'show', '--format=', '-p', rev], capture_output=True)
    p2 = subprocess.run(['git', '-C', d, 'patch-id', '--stable'], input=p1.stdout, capture_output=True)
    return p2.stdout.decode().split()[0] if p2.stdout.strip() else None


def pkg_only_dep_change(d, base, head, path):
    try:
        a = json.loads(git(d, 'show', f'{base}:{path}'))
        b = json.loads(git(d, 'show', f'{head}:{path}'))
    except Exception:
        return False
    strip = lambda o: {k: v for k, v in o.items() if k not in DEP_KEYS} if isinstance(o, dict) else o
    return strip(a) == strip(b)


def main(key, d):
    default, nums, n_all = ensure_clone(key, d)
    fp = git(d, 'rev-list', '--first-parent', default).split()
    fpset = set(fp)
    fpidx = {c: i for i, c in enumerate(fp)}  # 0 = newest
    subj = {}
    for line in git(d, 'log', '--first-parent', '--format=%H%x09%s', default).splitlines():
        h, s = line.split('\t', 1)
        subj[h] = s
    # patch-ids of first-parent commits (non-merge), newest 3000
    p1 = subprocess.run(['git', '-C', d, 'log', '--first-parent', '--no-merges', '-p', '--format=commit %H',
                         '-n', '3000', default], capture_output=True)
    p2 = subprocess.run(['git', '-C', d, 'patch-id', '--stable'], input=p1.stdout, capture_output=True)
    pid2c = {}
    for line in p2.stdout.decode().splitlines():
        pid, c = line.split()
        pid2c.setdefault(pid, c)
    prs = []
    for n in nums:
        ref = f'refs/remotes/pr/{n}'
        try:
            head = git(d, 'rev-parse', ref).strip()
        except RuntimeError:
            continue
        method = landing = None
        if subprocess.run(['git', '-C', d, 'merge-base', '--is-ancestor', head, default]).returncode == 0:
            desc = git(d, 'rev-list', '--ancestry-path', f'{head}..{default}').split()
            cands = [c for c in desc if c in fpset]
            if cands:
                landing = max(cands, key=lambda c: fpidx[c])  # oldest first-parent descendant
                method = 'merge'
            elif head in fpset:
                landing, method = head, 'merge(fast-forward)'
        if not method:
            hits = [c for c, s in subj.items() if f'(#{n})' in s]
            if hits:
                landing = max(hits, key=lambda c: fpidx[c])
                method = 'squash'
        if not method:
            pid = patch_id(d, head)
            if pid and pid in pid2c:
                landing, method = pid2c[pid], 'rebase'
        if not method:
            continue
        parent = git(d, 'rev-parse', f'{landing}^1', check=False).strip() or None
        if not parent:
            continue
        base = git(d, 'merge-base', parent, head, check=False).strip()
        if not base:
            continue
        land_date = git(d, 'show', '-s', '--format=%cI', landing).strip()
        commits = git(d, 'rev-list', f'{base}..{head}').split()
        if not commits:
            continue
        authors = sorted(set(git(d, 'log', f'{base}..{head}', '--format=%an%x09%ae').splitlines()))
        changed = [f for f in git(d, 'diff', '--name-only', base, head).splitlines() if f]
        bot = all(BOT_RE.search(a.split('\t')[0]) or BOT_RE.search(a.split('\t')[1].split('@')[0]) for a in authors)
        deponly = bool(changed) and all(
            os.path.basename(f) in LOCKFILES or (os.path.basename(f) == 'package.json' and pkg_only_dep_change(d, base, head, f))
            for f in changed)
        klass = 'dependency' if (bot or deponly) else 'code'
        states = [head] if klass == 'dependency' else git(d, 'rev-list', '--max-count=5', f'{base}..{head}').split()
        prs.append(dict(pr=n, method=method, landing=landing, landing_date=land_date, head=head, base=base,
                        authors=authors, klass=klass, class_reason=('bot author' if bot else 'lockfile/package.json deps only' if deponly else 'other files changed'),
                        changed_files=changed, states=states, n_commits=len(commits)))
    prs.sort(key=lambda p: p['landing_date'])
    kept = prs[-30:]
    out = dict(repo=key, url=SPECS[key]['repo'], default=default, default_head=git(d, 'rev-parse', default).strip(),
               pr_refs_total=n_all, pr_numbers_fetched=[nums[-1], nums[0]] if nums else None,
               merged_found_in_fetched=len(prs), kept=kept)
    od = os.path.join(HERE, 'data', key)
    os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, 'prs.json'), 'w'), indent=1)
    from collections import Counter
    print(key, 'default', default, out['default_head'][:10], 'refs', n_all, 'merged in top150', len(prs), 'kept', len(kept),
          Counter(p['klass'] for p in kept), Counter(p['method'] for p in kept))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
