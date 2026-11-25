#!/usr/bin/env python3
"""Build the preregistered state sets of cache measurement B (PREREG): the B2 commit and PR sets, K2(a) states,
and the B1 harden set, per pool repository, from A's prs.json and the repositories' first-parent history.

Usage: prereg.py --a-data DIR --pool DIR --out harness/cache_b/prereg.json
  --a-data  A's harness/cache_selection directory (origin/claude/cache-measure-a 6c4ee3d)
  --pool    directory holding one clone per pool repository (/home/runner/work/pool), PR refs fetched

Rules (spec "Sets (PREREG, disjoint)", gate rev 3 note 6), applied in this order:
  B2 commits  the 20 most recent merged-PR landing commits of A's prs.json (by landing_date); fewer -> filled with
              the most recent first-parent commits of the specs.json commit not already taken
  B2 PRs      10 code PRs of A's prs.json (klass code), most recent landing first; fewer -> all
  B2 seeds    parent of the oldest B2 commit (first-parent order), the merge-base of every B2 PR
  K2(a)       per code PR of A's prs.json (most recent first): `git rev-list --first-parent --no-merges base..head`
              minus A's states, at most 10 per PR, 30 per repository
  harden      10 first-parent commits strictly older than the oldest B2 commit, plus up to 10 intermediate states
              (A's states other than the head) of PRs not in the B2 PR set, most recent first; any sha that is in a
              B2 list (commits, PR heads, seeds, K2(a) and its merge-bases) is dropped
"""
import argparse
import json
import os
import subprocess
import sys
import time

POOL = ['codex-multi-auth', 'ironcurtain', 'yalc', 'nestjs-pino', 'agentsys', 'lerna-lite', 'drydock', 'agentlang',
        'alakajam']
# Node per repository (spec B2.1): drydock as specs.json, agentsys 22.23.5 (gate note 12), others the version A used
# (runner_versions.json "version" field: "<runner>/<v> linux-x64 node-v<node>")
NODE_OVERRIDE = {'drydock': '24.22.3', 'agentsys': '22.23.5'}


def git(repo, *args):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f'git {" ".join(args)} in {repo}: {r.stderr.strip()}')
    return r.stdout.strip()


def has(repo, sha):
    return subprocess.run(['git', '-C', repo, 'cat-file', '-e', f'{sha}^{{commit}}'], capture_output=True).returncode == 0


def ensure(repo, sha):
    if not has(repo, sha):
        subprocess.run(['git', '-C', repo, 'fetch', '-q', '--filter=blob:none', 'origin', sha], capture_output=True)
    return has(repo, sha)


def build(name, a_dir, pool, specs, versions):
    prs = json.load(open(os.path.join(a_dir, 'data', name, 'prs.json')))
    repo = os.path.join(pool, name)
    spec = specs[name]
    tip = spec['commit']
    launch = git(repo, 'rev-parse', 'origin/HEAD')
    fp = git(repo, 'rev-list', '--first-parent', tip).split('\n')  # newest first
    pos = {s: i for i, s in enumerate(fp)}
    kept = sorted(prs['kept'], key=lambda x: (x['landing_date'], pos.get(x['landing'], -1)), reverse=True)
    notes = []
    # B2 commit set
    commits = []
    for p in kept:
        if p['landing'] not in commits:
            commits.append(p['landing'])
        if len(commits) == 20:
            break
    filled = 0
    for s in fp:
        if len(commits) >= 20:
            break
        if s not in commits:
            commits.append(s)
            filled += 1
    if filled:
        notes.append(f'B2 commits: {20 - filled} landing commits, {filled} filled from first-parent history of {tip[:12]}')
    off = [c for c in commits if c not in pos]
    if off:
        notes.append(f'B2 commits not on first-parent history of {tip[:12]}: {len(off)} (ordered by landing date)')
    # history order (oldest first): first-parent position, else landing date
    landing_date = {p['landing']: p['landing_date'] for p in kept}
    def age(c):
        return (-pos[c], '') if c in pos else (None, landing_date.get(c, ''))
    on_fp = sorted([c for c in commits if c in pos], key=lambda c: -pos[c])
    commits_hist = on_fp + sorted(off, key=lambda c: landing_date.get(c, ''))
    oldest = on_fp[0] if on_fp else None
    for c in commits:
        if not ensure(repo, c):
            notes.append(f'B2 commit {c} not fetchable')
    seed_commit = git(repo, 'rev-parse', f'{oldest}^1') if oldest else None
    # B2 PR set
    code = [p for p in kept if p['klass'] == 'code']
    b2prs = []
    for p in code[:10]:
        ok = ensure(repo, p['head']) and ensure(repo, p['base'])
        mb = git(repo, 'merge-base', p['base'], p['head']) if ok else None
        b2prs.append({'pr': p['pr'], 'head': p['head'], 'base': p['base'], 'merge_base': mb, 'landing': p['landing'],
                      'landing_date': p['landing_date']})
    if len(code) < 10:
        notes.append(f'B2 PRs: {len(code)} code PRs available (fewer than 10)')
    b2pr_nums = {p['pr'] for p in b2prs}
    # K2(a)
    k2a = []
    for p in code:
        if len(k2a) >= 30:
            break
        if not (ensure(repo, p['head']) and ensure(repo, p['base'])):
            notes.append(f'K2(a) PR {p["pr"]}: head or base not fetchable')
            continue
        revs = [s for s in git(repo, 'rev-list', '--first-parent', '--no-merges', f'{p["base"]}..{p["head"]}').split('\n') if s]
        unread = [s for s in revs if s not in set(p['states'])][:10]
        for s in unread[:30 - len(k2a)]:
            k2a.append({'pr': p['pr'], 'sha': s, 'base': p['base'],
                        'merge_base': git(repo, 'merge-base', p['base'], p['head'])})
    seeds = ([seed_commit] if seed_commit else []) + [p['merge_base'] for p in b2prs if p['merge_base']]
    b2_all = (set(commits) | {p['head'] for p in b2prs} | set(seeds) | {x['sha'] for x in k2a}
              | {x['merge_base'] for x in k2a})  # K2(a) states replay from their PR's merge-base
    # harden set
    harden = []
    dropped = []
    if oldest:
        older = fp[pos[oldest] + 1:]
        for s in older:
            if len([h for h in harden if h['kind'] == 'commit']) >= 10:
                break
            if s in b2_all:
                dropped.append(s)
                continue
            harden.append({'kind': 'commit', 'sha': s})
    inter = []
    for p in kept:
        if p['pr'] in b2pr_nums:
            continue
        for s in p['states'][1:]:
            inter.append((p, s))
    n_inter = 0
    for p, s in inter:
        if n_inter >= 10:
            break
        if s in b2_all or any(h['sha'] == s for h in harden):
            dropped.append(s)
            continue
        if not ensure(repo, s):
            notes.append(f'harden state {s} (PR {p["pr"]}) not fetchable: skipped')
            continue
        harden.append({'kind': 'pr-state', 'sha': s, 'pr': p['pr'], 'base': p['base'],
                       'date': git(repo, 'show', '-s', '--format=%cI', s)})
        n_inter += 1
    # history order for the campaign: by committer date, oldest first (the commits are already first-parent ordered)
    for h in harden:
        if 'date' not in h:
            h['date'] = git(repo, 'show', '-s', '--format=%cI', h['sha'])
    harden.sort(key=lambda h: h['date'])
    v = versions.get(name, {}).get('version', '')
    node = NODE_OVERRIDE.get(name) or (v.rsplit('node-v', 1)[1] if 'node-v' in v else None)
    walls = []
    import glob
    for f in sorted(glob.glob(os.path.join(a_dir, 'data', name, 'full-*.json'))):
        try:
            w = json.load(open(f)).get('wall_s')
            if w:
                walls.append(w)
        except ValueError:
            pass
    walls.sort()
    plain = walls[len(walls) // 2] if walls else None
    return {
        'repo': name, 'url': spec['repo'], 'specs_commit': tip, 'launch_sha': launch, 'runner': spec['runner'],
        'args': spec.get('args', []), 'env': spec.get('env', {}), 'install': spec.get('install'),
        'cwd': 'app' if name == 'drydock' else '', 'node': node, 'a_runner_version': v,
        'plain_wall_s_median_A': plain,
        'b2_commits': commits_hist, 'b2_commit_seed': seed_commit, 'b2_prs': b2prs, 'k2a': k2a,
        'harden': harden, 'harden_dropped_as_b2': dropped, 'notes': notes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a-data', required=True)
    ap.add_argument('--pool', required=True)
    ap.add_argument('--specs', default=os.path.join(os.path.dirname(__file__), '..', 'parallel_measure', 'specs.json'))
    ap.add_argument('--out', required=True)
    o = ap.parse_args()
    specs = json.load(open(o.specs))
    versions = json.load(open(os.path.join(o.a_data, 'runner_versions.json')))
    out = {'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'a_source': 'origin/claude/cache-measure-a 6c4ee3d harness/cache_selection', 'repos': {}}
    for name in POOL:
        out['repos'][name] = build(name, o.a_data, o.pool, specs, versions)
        r = out['repos'][name]
        print(f"{name}: b2 commits {len(r['b2_commits'])}, b2 PRs {len(r['b2_prs'])}, k2a {len(r['k2a'])}, "
              f"harden {len(r['harden'])} ({sum(h['kind'] == 'commit' for h in r['harden'])} commits), "
              f"node {r['node']}, plain {r['plain_wall_s_median_A']} s; {'; '.join(r['notes'])}", file=sys.stderr)
    with open(o.out, 'w') as f:
        json.dump(out, f, indent=1)
        f.write('\n')


if __name__ == '__main__':
    main()
