#!/usr/bin/env python3
"""E1 lower bound (spec step 9) from the 4 per-test verify outputs on the trunk.
Usage: python3 harness/cache_selection/e1.py > harness/cache_selection/e1.json"""
import gzip, json, os, re, collections
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'parallel_measure', 'data')
out = {}
for r in ['agentsys', 'codex-multi-auth', 'ironcurtain', 'nestjs-pino']:
    f = f'verify-{r}-round2-w4.json.gz'
    d = json.load(gzip.open(os.path.join(D, f)))
    c = collections.Counter()
    for t in d['tests']:
        dv = t.get('divergence')
        if not dv:
            continue
        reason, desc = dv.get('reason'), dv.get('description') or ''
        if reason == 'env':
            c['env_run_level' if desc.startswith('outside any test the run read') else 'env_in_test'] += 1
        elif reason == 'fs':
            c['fs_all'] += 1
            if desc.startswith('before the test started: run input'):
                c['fs_of_which_run_input_before_test'] += 1
        elif reason == 'io':
            if 'concurrent I/O' in desc:
                c['io_race_concurrent'] += 1
            elif re.search(r'\b(read|reads|reading)\b', desc):
                c['io_read'] += 1
            else:
                c['io_not_read_not_race'] += 1
        else:
            c['not_counted_' + str(reason)] += 1
    row = {k: c.get(k, 0) for k in ['env_in_test', 'env_run_level', 'fs_all', 'fs_of_which_run_input_before_test',
                                     'io_read', 'io_race_concurrent', 'io_not_read_not_race']}
    row['tests_total'] = len(d['tests'])
    row['not_counted'] = {k[len('not_counted_'):]: v for k, v in c.items() if k.startswith('not_counted_')}
    row['source'] = 'harness/parallel_measure/data/' + f
    out[r] = row
print(json.dumps(out, indent=1))
