#!/usr/bin/env python3
"""Rebuild harden rows lost from a rows file (slice 1 of engine 9753874d: a checkpoint of a process started after
the --out change copied an older rows folder over the repository's, truncating codex-multi-auth, drydock and
lerna-lite). Each missing state's row is rebuilt from its run folder (summary.json, written by the engine) and the
state line of the campaign log (exit code, wall time), and marked "reconstructed": true. Rows still present are kept
as they are.

  rebuild_rows.py <rows.jsonl> <work/<engine12>/<repo>> <campaign log>
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(rows_path, work, log):
    rows = [json.loads(l) for l in open(rows_path)] if os.path.exists(rows_path) else []
    have = {r['i'] for r in rows}
    repo = os.path.basename(work.rstrip('/'))
    engine12 = os.path.basename(os.path.dirname(work.rstrip('/')))
    pre = json.load(open(os.path.join(HERE, 'prereg.json')))['repos'][repo]
    lines = {}
    for l in open(log):
        m = re.match(rf'{re.escape(repo)} \[(\d+)/\d+\] (\w+) exit (\S+) ([\d.]+)s', l)
        if m:
            lines[int(m.group(1))] = (m.group(2), m.group(3), float(m.group(4)))
    added = 0
    for i, st in enumerate(pre['harden']):
        if i in have:
            continue
        sp = os.path.join(work, 'runs', f'{i:02d}', 'summary.json')
        if not os.path.exists(sp) or i not in lines:
            continue
        sha10, ex, wall = lines[i]
        assert st['sha'].startswith(sha10), (i, sha10, st['sha'])
        s = json.load(open(sp))
        mism = s.get('verify_mismatches') or []
        rows.append({'repo': repo, 'i': i, 'n_states': len(pre['harden']), 'sha': st['sha'], 'kind': st['kind'],
                     'pr': st.get('pr'), 'engine_commit_prefix': engine12, 'mode': 'url', 'node': pre['node'],
                     'role': 'seed' if i == 0 else 'verify', 'reconstructed': True,
                     'exit': int(ex) if ex.lstrip('-').isdigit() else ex, 'wall_s': wall, 'status': 'ok',
                     'reused_files': s.get('reused_files'), 'reused_tests': s.get('reused_tests'),
                     'ran_files': len(s.get('ran_files') or {}), 'recorded': s.get('recorded'),
                     'verified': s.get('verified'), 'verified_tests': s.get('verified_tests'),
                     'verify_mismatches_tests': s.get('verify_mismatches_tests'), 'verify_mismatches': mism,
                     'verify_unchecked': s.get('verify_unchecked'), 'miss_reasons': s.get('miss_reasons'),
                     'not_cached': s.get('not_cached'), 'disabled': s.get('disabled'),
                     'remote': {k: (s.get('remote') or {}).get(k) for k in ('error', 'requests', 'pull_proven', 'pull_files_with_candidates', 'push_entry_docs_new', 'push_entries_unresolved')} if s.get('remote') else None,
                     'error': s.get('error'), 'classified': [], 'wrong_reuse': 0 if not mism else None})
        added += 1
    rows.sort(key=lambda r: r['i'])
    with open(rows_path, 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    print(f'{repo}: {added} rows rebuilt, {len(rows)} rows')


if __name__ == '__main__':
    main(*sys.argv[1:])
