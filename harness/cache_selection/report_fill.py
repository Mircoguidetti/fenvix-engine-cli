#!/usr/bin/env python3
"""Fill REPORT.tmpl.md placeholders {{TABLE}} {{DETAIL}} {{KILL}} {{SQ}} from summary.json and statusquo.json.

Usage: python3 report_fill.py <first line> <skipped.md> <verify.md>   (writes REPORT.md)
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, 'summary.json')))
SQ = json.load(open(os.path.join(HERE, 'statusquo.json')))
R = S['repos']


def pct(x):
    return f'{100 * x:.1f}%' if x is not None else None


def share_cell(v, cls):
    n = v['final_states_measured'].get(cls, 0)
    m = v['median_share_code'] if cls == 'code' else v['median_share_dependency']
    if cls == 'code' and m is None:
        nc = v['code_prs']
        why = 'no code PR with a measured share' if n == 0 else f'fewer than 5 code PRs measured (n={n} of {nc})'
        return f'UNKNOWN: {why}'
    if m is None:
        return 'UNKNOWN: no dependency PR' + (' with a measured share' if v['dependency_prs'] else '')
    return f'{pct(m)} (n={n}) MEASURED'


def e1_cell(k):
    e = R[k]['e1']
    if not e:
        return 'UNKNOWN: no verify output'
    return (f"env in-test {e['env_in_test']}, env run-level {e['env_run_level']}, fs {e['fs_all']}, io read {e['io_read']}, "
            f"io race {e['io_race_concurrent']} (of {e['tests_total']} tests) MEASURED")


def miss_cell(v, cls):
    n_states = v['states_with_excluded_run_by_class'].get(cls, 0)
    if not v['states_ok_by_class'].get(cls):
        return 'UNKNOWN: no measured state' if (v['code_prs'] if cls == 'code' else v['dependency_prs']) else '– (no PR)'
    return f"{v['selection_miss'].get(cls, 0)} over {n_states} states with excluded files MEASURED"


T = ['| repository | PRs kept (code / dependency) | PRs with measured final-state share (code / dependency) | skips tests in CI today | median selection share, code | median selection share, dependency | SELECTION_MISS, code | SELECTION_MISS, dependency | E1 lower bound |',
     '|---|---|---|---|---|---|---|---|---|']
for k, v in R.items():
    fm = v['final_states_measured']
    T.append(f"| {k} | {v['code_prs']} / {v['dependency_prs']} | {fm.get('code', 0)} / {fm.get('dependency', 0)} | "
             f"{'yes: ' + v['ci_skip_tool'] if v['skips_tests_in_ci'] else 'no (none found)'} | {share_cell(v, 'code')} | {share_cell(v, 'dependency')} | "
             f"{miss_cell(v, 'code')} | {miss_cell(v, 'dependency')} | {e1_cell(k)} |")

D = ['### Detail per repository', '']
for k, v in R.items():
    fc = v['failure_classes']
    D.append(f"- **{k}**: states measured {v['states_ok']} of {v['states_done']} run / {v['states_planned']} planned "
             f"(UNKNOWN states: {v['states_unknown']}{'; ' + '; '.join(f'{c}x {r}' for r, c in v['unknown_reasons'].items()) if v['unknown_reasons'] else ''}). "
             f"Excluded test files run: {sum(v['excluded_test_files_run_by_class'].values())} "
             f"({', '.join(f'{c} {n}' for c, n in v['excluded_test_files_run_by_class'].items()) or 'none'}). "
             f"Failing tests classified: SELECTION_MISS {fc.get('SELECTION_MISS', 0)}, PREEXISTING {fc.get('PREEXISTING', 0)}, FLAKY {fc.get('FLAKY', 0)}, "
             f"ENV {fc.get('ENV', 0)}, UNKNOWN {fc.get('UNKNOWN', 0)}; not classified (cap) {v['failures_not_classified']}. "
             f"Median share over all PRs: {pct(v['median_share_all']) or 'UNKNOWN'}. "
             f"Final states with share UNKNOWN: {v['final_states_share_unknown']}. "
             + (f"Final states where more than 10% of test files have UNKNOWN minutes: PRs {v['final_states_over10pct_files_unknown_minutes']}; "
                f"code median over the remaining code PRs: {pct(v['median_share_code_le10pct_unknown']) or 'UNKNOWN (fewer than 5)'}. "
                if v['final_states_over10pct_files_unknown_minutes'] else ''))

K = S['kill_line']
measured = K['repos_with_code_median_measured']
KL = [f"(a) **{len(K['repos_code_median_below_30pct'])} of {len(measured)}** repositories with a measured code median have a median selection share for code PRs below 30% "
      f"({', '.join(f'{r} {pct(R[r]["median_share_code"])}' for r in K['repos_code_median_below_30pct']) or 'none'}). "
      f"Measured: {', '.join(f'{r} {pct(R[r]["median_share_code"])}' for r in measured)}. "
      f"UNKNOWN for {', '.join(r for r in R if r not in measured)} (see table). MEASURED.",
      '',
      f"(b) **{len(K['repos_already_skipping_in_ci'])} of {len(R)}** repositories already skip tests in CI with one of the listed tools (`statusquo.json`). MEASURED (read of CI files).",
      '',
      f"(c) **{K['selection_miss_total_code']}** SELECTION_MISS over all code PRs. Checked: "
      f"{sum(v['states_with_excluded_run_by_class'].get('code', 0) for v in R.values())} code-PR states where the free selection excluded at least one test file, "
      f"{sum(v['excluded_test_files_run_by_class'].get('code', 0) for v in R.values())} excluded test files run in total. MEASURED. "
      f"(Dependency PRs: {K['selection_miss_total_dependency']}.)",
      '',
      'Caveat for (c): "measured on the last 5 commits of merged PRs; breakages fixed before a commit was made, and PRs never merged, are not seen, so the count is a lower bound".']

Q = []
for k in R:
    q = SQ[k]
    Q.append(f"| {k} | {q['ci_test_command']} | {'yes: ' + q['tool'] if q['skips_tests_in_ci'] else 'no: ' + q['tool']} | {q.get('notes') or ''} |")

t = open(os.path.join(HERE, 'REPORT.tmpl.md')).read()
first, skipped, verify = sys.argv[1], open(sys.argv[2]).read().strip(), open(sys.argv[3]).read().strip()
t = t.replace('NOT DONE\n', first + '\n', 1)
for a, b in (('{{TABLE}}', '\n'.join(T)), ('{{DETAIL}}', '\n'.join(D)), ('{{KILL}}', '\n'.join(KL)), ('{{SQ}}', '\n'.join(Q)),
             ('{{SKIPPED}}', skipped), ('{{VERIFY}}', verify)):
    t = t.replace(a, b)
open(os.path.join(HERE, 'REPORT.md'), 'w').write(t)
print('ok')
