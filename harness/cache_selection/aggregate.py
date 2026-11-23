#!/usr/bin/env python3
"""Spec steps 7-9 and outputs: results.jsonl, summary.json, tables.md.

Usage: python3 aggregate.py
Reads data/<repo>/prs.json and rows.jsonl (written by cs.py), statusquo.json and e1.json.
ENV relabelling: a failure whose first_failure_line matches ENV_RE and is not SELECTION_MISS
is labelled ENV (the original label is kept in orig_class). The same regex is in cs.py; rows
written before cs.py had all patterns are relabelled here.
"""
import json, os, re, statistics
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ['codex-multi-auth', 'ironcurtain', 'yalc', 'nestjs-pino', 'agentsys', 'lerna-lite', 'drydock', 'agentlang', 'alakajam']
ENV_RE = re.compile(r'No native build was found|EAFNOSUPPORT|ECONNREFUSED|EADDRNOTAVAIL|ENETUNREACH|EAI_AGAIN|ENOTFOUND|getaddrinfo|EHOSTUNREACH|'
                    r"Executable doesn't exist|browserType\.launch|Cannot connect to the Docker|docker: not found")


def med(xs):
    return round(statistics.median(xs), 4) if xs else None


def pct(x):
    return 'UNKNOWN' if x is None else f'{100 * x:.1f}%'


def main():
    sq = json.load(open(os.path.join(HERE, 'statusquo.json')))
    e1 = json.load(open(os.path.join(HERE, 'e1.json'))) if os.path.exists(os.path.join(HERE, 'e1.json')) else {}
    out_rows, summ = [], {}
    for key in ORDER:
        d = os.path.join(HERE, 'data', key)
        prs = json.load(open(os.path.join(d, 'prs.json')))['kept'] if os.path.exists(os.path.join(d, 'prs.json')) else []
        rows = [json.loads(l) for l in open(os.path.join(d, 'rows.jsonl'))] if os.path.exists(os.path.join(d, 'rows.jsonl')) else []
        planned = sum(len(p['states']) for p in prs)
        fc = Counter()
        miss = Counter()  # per class
        miss_prs = {'code': set(), 'dependency': set()}
        for r in rows:
            for f in r.get('failures') or []:
                if f.get('class') != 'SELECTION_MISS' and f.get('class') != 'ENV' and ENV_RE.search(f.get('first_failure_line') or ''):
                    f['orig_class'] = f['class']
                    f['class'] = 'ENV'
                    f['env_pattern'] = ENV_RE.search(f['first_failure_line']).group(0)
                fc[f['class']] += 1
                if f['class'] == 'SELECTION_MISS':
                    miss[r['class']] += 1
                    miss_prs[r['class']].add(r['pr'])
            out_rows.append(r)
        finals = [r for r in rows if r.get('is_final_state')]
        share = {'code': [], 'dependency': []}
        for r in finals:
            if r['status'] == 'ok' and r.get('share') is not None:
                share[r['class']].append(r['share'])
        allsh = share['code'] + share['dependency']
        n_code_prs = sum(1 for p in prs if p['klass'] == 'code')
        s = dict(
            prs_kept=len(prs), code_prs=n_code_prs, dependency_prs=len(prs) - n_code_prs,
            states_planned=planned, states_done=len(rows),
            states_ok=sum(1 for r in rows if r['status'] == 'ok'),
            states_unknown=sum(1 for r in rows if r['status'] != 'ok'),
            unknown_reasons=dict(Counter(r['status'][:90] for r in rows if r['status'] != 'ok')),
            final_states_measured={c: len(v) for c, v in share.items()},
            median_share_all=med(allsh),
            median_share_code=med(share['code']) if len(share['code']) >= 5 else None,
            median_share_code_note=None if len(share['code']) >= 5 else f'UNKNOWN: {len(share["code"])} code PRs measured (<5)',
            median_share_dependency=med(share['dependency']),
            failure_classes=dict(fc),
            selection_miss=dict(miss), selection_miss_prs={c: sorted(v) for c, v in miss_prs.items()},
            excluded_minutes_run=round(sum((r.get('minutes_excluded') or 0) for r in rows if r['status'] == 'ok'), 2),
            files_unknown_minutes=sum(len(r.get('files_unknown_minutes') or []) for r in rows),
            failures_not_classified=sum(r.get('failures_not_classified') or 0 for r in rows),
            skips_tests_in_ci=sq[key]['skips_tests_in_ci'], ci_skip_tool=sq[key]['tool'],
            e1=e1.get(key),
        )
        summ[key] = s
    with open(os.path.join(HERE, 'results.jsonl'), 'w') as fo:
        for r in out_rows:
            fo.write(json.dumps(r) + '\n')
    measured_code = {k: v['median_share_code'] for k, v in summ.items() if v['median_share_code'] is not None}
    kill = dict(
        repos_code_median_below_30pct=sorted(k for k, v in measured_code.items() if v < 0.30),
        repos_with_code_median_measured=sorted(measured_code),
        repos_already_skipping_in_ci=sorted(k for k, v in summ.items() if v['skips_tests_in_ci']),
        selection_miss_total_code=sum(v['selection_miss'].get('code', 0) for v in summ.values()),
        selection_miss_total_dependency=sum(v['selection_miss'].get('dependency', 0) for v in summ.values()),
    )
    json.dump(dict(repos=summ, kill_line=kill), open(os.path.join(HERE, 'summary.json'), 'w'), indent=1)

    L = ['| repository | PRs kept (code/dep) | states done/planned | UNKNOWN states | median share all | median share code | median share dependency | SELECTION_MISS code | SELECTION_MISS dep | PREEXISTING | FLAKY | ENV |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k, s in summ.items():
        if not s['states_done']:
            L.append(f'| {k} | {s["prs_kept"]} ({s["code_prs"]}/{s["dependency_prs"]}) | 0/{s["states_planned"]} | – | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | – | – | – |')
            continue
        fc = s['failure_classes']
        L.append(f'| {k} | {s["prs_kept"]} ({s["code_prs"]}/{s["dependency_prs"]}) | {s["states_done"]}/{s["states_planned"]} | {s["states_unknown"]} '
                 f'| {pct(s["median_share_all"])} (n={sum(s["final_states_measured"].values())}) '
                 f'| {pct(s["median_share_code"])} (n={s["final_states_measured"]["code"]}) '
                 f'| {pct(s["median_share_dependency"])} (n={s["final_states_measured"]["dependency"]}) '
                 f'| {s["selection_miss"].get("code", 0)} | {s["selection_miss"].get("dependency", 0)} '
                 f'| {fc.get("PREEXISTING", 0)} | {fc.get("FLAKY", 0)} | {fc.get("ENV", 0)} |')
    open(os.path.join(HERE, 'tables.md'), 'w').write('\n'.join(L) + '\n\n' + json.dumps(kill, indent=1) + '\n')
    print('\n'.join(L))
    print(json.dumps(kill, indent=1))


if __name__ == '__main__':
    main()
