#!/usr/bin/env python3
"""Measurement A driver (spec steps 4-8). One repository per invocation, resumable.

Usage: python3 cs.py <repo-key> [--rounds N] [--max-prs N] [--only-full]
Needs data/<repo-key>/prs.json from history.py and an entry in repos.json.
Writes data/<repo-key>/full-<i>.json(.gz), data/<repo-key>/rows.jsonl, data/<repo-key>/log.txt.

States are processed round by round: round 1 = the final state of every PR, round 2 = the state before it, ...
so that cutting work (spec: code-PR states 5 -> 2) keeps whole rounds.
"""
import gzip, hashlib, json, os, re, shlex, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, 'repos.json')))
MANIFEST_RE = re.compile(r'(^|/)(package\.json|package-lock\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml|yarn\.lock|\.npmrc|\.pnpmfile\.cjs)$')
ENV_RE = re.compile(r'EAFNOSUPPORT|ECONNREFUSED|EADDRNOTAVAIL|ENETUNREACH|EAI_AGAIN|ENOTFOUND|getaddrinfo|EHOSTUNREACH|'
                    r"Executable doesn't exist|browserType\.launch|Cannot connect to the Docker|docker: not found")


class Ctx:
    def __init__(self, key):
        self.key = key
        self.c = CFG[key]
        self.clone = self.c['clone']
        self.cwd = os.path.join(self.clone, self.c.get('subdir', ''))
        self.out = os.path.join(HERE, 'data', key)
        self.tmp = os.path.join('/home/user/work/tmp', key)
        os.makedirs(self.tmp, exist_ok=True)
        self.env = dict(os.environ)
        for k, v in self.c.get('env', {}).items():
            self.env[k] = v.replace('$PATH', os.environ['PATH'])
        self.log = open(os.path.join(self.out, 'log.txt'), 'a')
        self.installed_key = None
        self.cur = None

    def L(self, *a):
        s = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + ' ' + ' '.join(str(x) for x in a)
        print(s, flush=True)
        self.log.write(s + '\n'); self.log.flush()

    def sh(self, cmd, cwd=None, timeout=None, log=True):
        t = time.time()
        try:
            p = subprocess.run(cmd, shell=True, cwd=cwd or self.cwd, env=self.env, capture_output=True, text=True,
                               timeout=timeout, errors='replace')
            rc, so, se = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            rc, so, se = 'timeout', (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or ''), \
                (e.stderr or b'').decode(errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or '')
        dt = time.time() - t
        if log:
            self.L(f'  $ {cmd[:400]}  -> exit {rc} in {dt:.1f}s')
        return rc, so, se, dt

    def git(self, *a):
        return subprocess.run(['git', '-C', self.clone] + list(a), capture_output=True, text=True, check=True).stdout

    def checkout(self, sha):
        if self.cur == sha:
            return None
        rc, so, se, _ = self.sh(f'git checkout -q -f --detach {sha} && git clean -fdxq -e node_modules', cwd=self.clone)
        if rc != 0:
            raise RuntimeError('checkout failed: ' + se[-500:])
        self.cur = sha
        listing = self.git('ls-tree', '-r', sha)
        mk = hashlib.sha1('\n'.join(l for l in listing.splitlines() if MANIFEST_RE.search(l.split('\t')[1])).encode()).hexdigest()
        note = None
        if mk != self.installed_key:
            rc, so, se, dt = self.sh(self.c['install'], cwd=self.clone, timeout=3600)
            if rc != 0:
                self.installed_key = None
                err = [l for l in (se + so).splitlines() if l.strip()]
                return 'INSTALL_FAILED: ' + (err[-1] if err else f'exit {rc}')[:300]
            self.installed_key = mk
            note = f'installed ({dt:.0f}s)'
        else:
            note = 'install reused: identical package manifests and lockfiles (key %s)' % mk[:12]
        if self.c.get('build'):
            rc, so, se, dt = self.sh(self.c['build'], cwd=self.clone, timeout=3600)
            if rc != 0:
                err = [l for l in (se + so).splitlines() if l.strip()]
                return 'BUILD_FAILED: ' + (err[-1] if err else f'exit {rc}')[:300]
        return note

    def rel(self, p):
        p = os.path.realpath(p) if os.path.isabs(p) else p
        if os.path.isabs(p):
            return os.path.relpath(p, os.path.realpath(self.cwd))
        return p

    # ---------- runner specific ----------
    def args(self):
        return ' '.join(shlex.quote(a) for a in self.c.get('args', []))

    def list_all(self):
        tmpf = os.path.join(self.tmp, 'list-all.json')
        if self.c['runner'] == 'vitest':
            cmd = f'npx --no-install vitest list {self.args()} --filesOnly --json={tmpf}'
            if os.path.exists(tmpf): os.remove(tmpf)
            rc, so, se, _ = self.sh(cmd, timeout=900)
            files = self._read_vitest_list(tmpf, so, se)
        else:
            cmd = f'npx --no-install jest {self.args()} --listTests'
            rc, so, se, _ = self.sh(cmd, timeout=900)
            files = [self.rel(l.strip()) for l in so.splitlines() if l.strip().startswith('/')]
        return cmd, rc, files

    def _read_vitest_list(self, tmpf, so, se):
        if os.path.exists(tmpf):
            return sorted({self.rel(x['file']) for x in json.load(open(tmpf))})
        if 'No test files found' in so + se:
            return []
        return None

    def select(self, base, changed):
        tmpf = os.path.join(self.tmp, 'list-sel.json')
        if self.c['runner'] == 'vitest':
            cmd = f'npx --no-install vitest list {self.args()} --changed {base} --filesOnly --json={tmpf}'
            if os.path.exists(tmpf): os.remove(tmpf)
            rc, so, se, _ = self.sh(cmd, timeout=900)
            files = self._read_vitest_list(tmpf, so, se)
            if files is None:
                self.L('    selection stderr tail: ' + (se + so)[-800:].replace('\n', ' | '))
        else:
            sub = self.c.get('subdir', '')
            ex = [os.path.relpath(f, sub) if sub else f for f in changed if os.path.exists(os.path.join(self.clone, f))]
            ex = [f for f in ex if not f.startswith('..')]
            if not ex:
                return f'(no changed file exists at this state; jest --findRelatedTests not run)', 0, []
            cmd = f'npx --no-install jest {self.args()} --listTests --findRelatedTests ' + ' '.join(shlex.quote(f) for f in ex)
            rc, so, se, _ = self.sh(cmd, timeout=900)
            files = [self.rel(l.strip()) for l in so.splitlines() if l.strip().startswith('/')] if rc == 0 else None
        return cmd, rc, files

    def run_json(self, files, mode, tag, timeout):
        """mode: 'serial' (step 5), 'own' (repo's own parallel mode, step 8), 'plain1' (one file, plain)."""
        outf = os.path.join(self.tmp, f'{tag}.json')
        if os.path.exists(outf): os.remove(outf)
        fl = ' '.join(shlex.quote(f) for f in files)
        if self.c['runner'] == 'vitest':
            extra = ' --no-file-parallelism --maxWorkers=1' if mode == 'serial' else ''
            cmd = f'npx --no-install vitest run {self.args()}{extra} --reporter=json --outputFile={outf} {fl}'.rstrip()
        else:
            extra = ' --runInBand' if mode == 'serial' else ''
            byp = ' --runTestsByPath' if files else ''
            cmd = f'npx --no-install jest {self.args()}{extra} --json --outputFile={outf}{byp} {fl}'.rstrip()
        rc, so, se, dt = self.sh(cmd, timeout=timeout)
        data = None
        if os.path.exists(outf):
            try:
                data = json.load(open(outf))
            except Exception:
                data = None
        return cmd, rc, data, dt, (se + so)

    def tests_of(self, data):
        """-> {test_id: (status, message, file)}, {file: (ms, status)}"""
        tests, files = {}, {}
        for tr in data.get('testResults', []):
            f = self.rel(tr['name'])
            st, en = tr.get('startTime'), tr.get('endTime')
            files[f] = ((en - st) if (st is not None and en is not None) else None, tr.get('status'))
            ars = tr.get('assertionResults', [])
            for a in ars:
                tid = f + ' > ' + (a.get('fullName') or ' '.join(a.get('ancestorTitles', []) + [a.get('title', '')]))
                tests[tid] = (a.get('status'), ' '.join(a.get('failureMessages') or [])[:2000], f)
            if tr.get('status') == 'failed' and not any(a.get('status') == 'failed' for a in ars):
                tests[f + ' > <file>'] = ('failed', (tr.get('message') or '')[:2000], f)
        return tests, files


def full_runs(ctx, prs):
    idxs = list(range(0, len(prs), 5))
    for i in idxs:
        fn = os.path.join(ctx.out, f'full-{i:02d}.json')
        if os.path.exists(fn):
            continue
        base = prs[i]['base']
        ctx.L(f'FULL RUN pr-index {i} PR #{prs[i]["pr"]} base {base}')
        note = ctx.checkout(base)
        rec = dict(repo=ctx.key, pr_index=i, pr=prs[i]['pr'], commit=base, install=note)
        if note and note.split(':')[0] in ('INSTALL_FAILED', 'BUILD_FAILED'):
            rec.update(status='UNKNOWN', reason=note)
        else:
            cmd, rc, data, dt, tail = ctx.run_json([], 'serial', f'full-{i:02d}', timeout=4 * 3600)
            rec.update(cmd=cmd, cwd=ctx.cwd, exit=rc, wall_s=round(dt, 1))
            if data is None:
                rec.update(status='UNKNOWN', reason='no JSON report: ' + tail[-300:])
            else:
                tests, files = ctx.tests_of(data)
                from collections import Counter
                rec.update(status='ok', outcome_counts=dict(Counter(v[0] for v in tests.values())),
                           files={f: {'ms': ms, 'status': s} for f, (ms, s) in sorted(files.items())},
                           failed_tests=sorted(t for t, v in tests.items() if v[0] == 'failed'))
                raw = os.path.join(ctx.tmp, f'full-{i:02d}.json')
                with open(raw, 'rb') as fi, gzip.open(fn + '.raw.gz', 'wb') as fo:
                    fo.write(fi.read())
        json.dump(rec, open(fn, 'w'), indent=1)
        ctx.L(f'  full run {i}: {rec.get("status")} exit {rec.get("exit")} {rec.get("wall_s")}s {rec.get("outcome_counts")}')


def classify_failures(ctx, pr, state, fails, base):
    """fails: {tid: (status,msg,file)} from the excluded run at `state`. Reruns 3x at state, 3x at base, one file at a time."""
    byfile = {}
    for tid, (_, msg, f) in fails.items():
        byfile.setdefault(f, []).append(tid)
    res = {t: dict(test=t, state_fail_count=0, base_fail_count=0, first_failure_line=(fails[t][1].strip().splitlines() or [''])[0][:300],
                   state_cmds=[], base_cmds=[]) for t in fails}

    def runs(at, which):
        note = ctx.checkout(at)
        if note and note.split(':')[0] in ('INSTALL_FAILED', 'BUILD_FAILED'):
            for t in res.values():
                t[which + '_fail_count'] = 'UNKNOWN: ' + note
            return
        for f, tids in byfile.items():
            if not os.path.exists(os.path.join(ctx.cwd, f)):
                for t in tids:
                    res[t][which + '_fail_count'] = 'absent'
                continue
            for k in range(3):
                cmd, rc, data, dt, tail = ctx.run_json([f], 'plain1', f'rerun-{which}', timeout=1800)
                tests = ctx.tests_of(data)[0] if data else {}
                for t in tids:
                    res[t][which + '_cmds'].append(f'(cd {ctx.cwd} && git checkout {at} && {cmd}) -> exit {rc}, test status {tests.get(t, ("missing",))[0]}')
                    if tests.get(t, ('missing',))[0] != 'passed':
                        if isinstance(res[t][which + '_fail_count'], int):
                            res[t][which + '_fail_count'] += 1
    runs(state, 'state')
    runs(base, 'base')
    out = []
    for t, r in res.items():
        s, b = r['state_fail_count'], r['base_fail_count']
        if isinstance(s, int) and b == 0 and s >= 2:
            cls = 'SELECTION_MISS'
        elif isinstance(b, int) and b >= 1:
            cls = 'PREEXISTING'
        else:
            cls = 'FLAKY'
        if ENV_RE.search(fails[t][1]):
            r['env_pattern'] = ENV_RE.search(fails[t][1]).group(0)
            if cls != 'SELECTION_MISS':
                cls = 'ENV'
        r['class'] = cls
        r['pr'], r['state_sha'], r['base'] = pr, state, base
        out.append(r)
    return out


def process_state(ctx, prs, i, si, fulls):
    p = prs[i]
    state = p['states'][si]
    base = p['base']
    row = dict(repo=ctx.key, pr=p['pr'], author=sorted({a.split('\t')[0] for a in p['authors']}), **{'class': p['klass']},
               base=base, state_sha=state, is_final_state=(si == 0), state_index=si, n_states=len(p['states']),
               merge_method=p['method'], runner=ctx.c['runner'])
    t0 = time.time()
    ctx.L(f'STATE PR #{p["pr"]} ({p["klass"]}) state {si + 1}/{len(p["states"])} {state[:10]} base {base[:10]}')
    note = ctx.checkout(state)
    row['install'] = note
    changed = [f for f in ctx.git('diff', '--name-only', f'{base}...{state}').splitlines() if f]
    row['changed_files'] = changed
    if note and note.split(':')[0] in ('INSTALL_FAILED', 'BUILD_FAILED'):
        row.update(status='UNKNOWN: ' + note)
        return row
    acmd, arc, allf = ctx.list_all()
    scmd, src, sel = ctx.select(base, changed)
    row.update(list_all_cmd=f'{acmd} -> exit {arc}', selection_cmd=f'{scmd} -> exit {src}')
    if allf is None or sel is None:
        row.update(status='UNKNOWN: list-only command failed (exit %s / %s)' % (arc, src))
        return row
    allset, selset = set(allf), set(sel)
    excl = sorted(allset - selset)
    row.update(n_all_files=len(allf), selected_files=sorted(selset), excluded_files=excl,
               selected_not_in_all=sorted(selset - allset))
    # step 7: minutes from the nearest earlier full run
    fi = (i // 5) * 5
    full = fulls.get(fi)
    row['duration_source'] = f'harness/cache_selection/data/{ctx.key}/full-{fi:02d}.json'
    if not full or full.get('status') != 'ok':
        row.update(minutes_total=None, minutes_excluded=None, minutes_unknown=None, share=None,
                   share_status='UNKNOWN: full run %d not available (%s)' % (fi, (full or {}).get('reason')))
    else:
        fm = full['files']
        known = [f for f in allf if f in fm and fm[f]['ms'] is not None]
        unk = [f for f in allf if f not in fm or fm[f]['ms'] is None]
        tot = sum(fm[f]['ms'] for f in known) / 60000
        ex = sum(fm[f]['ms'] for f in known if f not in selset) / 60000
        row.update(minutes_total=round(tot, 4), minutes_excluded=round(ex, 4), minutes_unknown=len(unk),
                   files_unknown_minutes=unk, share=round(ex / tot, 4) if tot > 0 else None, share_status='MEASURED')
    # step 8: run excluded files with the repo's own parallel mode
    if not excl:
        row.update(excluded_run_cmd='(nothing excluded: no run)', excluded_run_exit=None, failures=[], status='ok')
    else:
        tag = f'excl-{p["pr"]}-{state[:8]}'
        cmd, rc, data, dt, tail = ctx.run_json(excl, 'own', tag, timeout=4 * 3600)
        row.update(excluded_run_cmd=f'(cd {ctx.cwd} && git checkout {state} && {cmd})', excluded_run_exit=rc,
                   excluded_run_wall_s=round(dt, 1))
        if data is None:
            row.update(failures=[], status='UNKNOWN: excluded run produced no JSON report: ' + tail[-300:].replace('\n', ' | '))
            return row
        tests, files = ctx.tests_of(data)
        fails = {t: v for t, v in tests.items() if v[0] == 'failed' and v[2] in set(excl)}
        from collections import Counter
        row['excluded_run_outcomes'] = dict(Counter(v[0] for t, v in tests.items() if v[2] in set(excl)))
        row['excluded_files_not_reported'] = sorted(set(excl) - set(files))
        if len(fails) > 40:
            ctx.L(f'  {len(fails)} failures: classifying the first 40 only')
            row['failures_not_classified'] = sorted(fails)[40:]
            fails = {t: fails[t] for t in sorted(fails)[:40]}
        row['failures'] = classify_failures(ctx, p['pr'], state, fails, base) if fails else []
        row['status'] = 'ok'
    row['elapsed_s'] = round(time.time() - t0, 1)
    return row


def main():
    key = sys.argv[1]
    rounds = int(sys.argv[sys.argv.index('--rounds') + 1]) if '--rounds' in sys.argv else 5
    max_prs = int(sys.argv[sys.argv.index('--max-prs') + 1]) if '--max-prs' in sys.argv else 30
    ctx = Ctx(key)
    prs = json.load(open(os.path.join(ctx.out, 'prs.json')))['kept']
    prs = prs[-max_prs:] if max_prs < len(prs) else prs
    full_runs(ctx, prs)
    if '--only-full' in sys.argv:
        return
    fulls = {int(f[5:7]): json.load(open(os.path.join(ctx.out, f))) for f in os.listdir(ctx.out)
             if re.fullmatch(r'full-\d\d\.json', f)}
    rows_f = os.path.join(ctx.out, 'rows.jsonl')
    done = set()
    if os.path.exists(rows_f):
        for l in open(rows_f):
            r = json.loads(l)
            done.add((r['pr'], r['state_sha']))
    for si in range(rounds):
        for i, p in enumerate(prs):
            if si >= len(p['states']) or (p['pr'], p['states'][si]) in done:
                continue
            try:
                row = process_state(ctx, prs, i, si, fulls)
            except Exception as e:
                import traceback
                ctx.L('  ERROR ' + traceback.format_exc()[-1500:])
                row = dict(repo=key, pr=p['pr'], state_sha=p['states'][si], is_final_state=(si == 0),
                           status='UNKNOWN: harness error ' + repr(e)[:300])
            with open(rows_f, 'a') as fo:
                fo.write(json.dumps(row) + '\n')
            ctx.L(f'  -> {row.get("status")} share={row.get("share")} sel={len(row.get("selected_files") or [])} '
                  f'excl={len(row.get("excluded_files") or [])} failures={[ (f["test"][:80], f["class"]) for f in row.get("failures") or []]}')
    ctx.L('DONE rounds', rounds)


if __name__ == '__main__':
    main()
