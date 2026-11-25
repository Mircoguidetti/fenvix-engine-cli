#!/usr/bin/env python3
"""B1 harden campaign runner (cache measurement B, spec B1.3-B1.5, PREREG "B1 harden campaign").

One repository per process, its harden states (prereg.json) in history order, the repository switched in place at
its fixed path (/home/runner/work/pool/<repo>). State 0 seeds the cache (`serial` command + --det-cache); every
later state runs the same command + --det-cache-verify. Every mismatch of the summary JSON (`verify_mismatches`, tests
and file-level) is classified by the B1.3 rule with 10 plain runs of its test file on this machine.

Resumable: rows go to <out>/<engine12>/<repo>.jsonl; a state already there for this engine commit is skipped (the
cache store under <work>/<engine12>/<repo>/ is kept between processes). A new engine commit starts from the seed.

  harden.py --repo yalc --engine /home/runner/work/engine/<sha> [--mode url|dir] [--max-seconds 6000]

URL form (gate note 9): `python -m detpy.cache_service serve` on loopback with a token of its own (FENVIX_CACHE_TOKEN),
runs use --det-cache=http://127.0.0.1:<port>/<repo>, each run with a new empty FENVIX_CACHE_LOCAL.
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
POOL = '/home/runner/work/pool'
VENV_PY = '/home/runner/work/venv-detpy/bin/python'
NODE_BIN = {'24.22.3': '/opt/node24/bin', '22.23.5': '/opt/node22/bin'}
# A's install lines (harness/cache_selection/repos.json) plus the specs.json post-install steps the suites need
INSTALL = {
    'codex-multi-auth': 'npm ci --ignore-scripts --no-audit --no-fund',
    'ironcurtain': 'npm ci --ignore-scripts --no-audit --no-fund',
    'yalc': 'npx -y pnpm@10.30.3 install --frozen-lockfile --ignore-scripts && if [ -f web/package.json ]; then (cd web && npx -y pnpm@10.30.3 install --frozen-lockfile --ignore-scripts --ignore-workspace); fi',
    'nestjs-pino': 'npm ci --ignore-scripts --no-audit --no-fund',
    'agentsys': 'npm ci --ignore-scripts --no-audit --no-fund',
    'lerna-lite': 'npx -y pnpm@11.28.5 install --frozen-lockfile --ignore-scripts && npx -y pnpm@11.28.5 build',
    'drydock': 'npm ci --ignore-scripts --no-audit --no-fund && (cd app && npm ci --ignore-scripts --no-audit --no-fund)',
    'agentlang': 'npx -y pnpm@10.28.2 install --frozen-lockfile --ignore-scripts && npx -y pnpm@10.28.2 rebuild better-sqlite3',
    'alakajam': 'npm ci --ignore-scripts --no-audit --no-fund && npm rebuild sqlite3',
}
GIT_LOCK = '/home/runner/work/cacheb/git.lock'
CHECKPOINT_S = 1800


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def sh(cmd, cwd, env, timeout, log=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str), capture_output=True, text=True,
                           timeout=timeout, start_new_session=True)
        rc, out = p.returncode, (p.stdout or '') + (p.stderr or '')
    except subprocess.TimeoutExpired as e:
        rc, out = 'timeout', f'{e.stdout or ""}{e.stderr or ""}'
        if isinstance(out, bytes):
            out = out.decode('utf8', 'replace')
    if log:
        with open(log, 'w') as f:
            f.write(out if isinstance(out, str) else str(out))
    return rc, round(time.time() - t0, 2), out if isinstance(out, str) else str(out)


def git_checkpoint(out_dir, name, message):
    """Copy this repository's result files (<name>.jsonl, <name>-*) into the repository, then commit and push them
    (one process at a time: the campaign runs several repositories at once). Only this process's own files are
    copied: copying the whole rows folder overwrote other processes' rows (slice 1, rebuilt by rebuild_rows.py)."""
    repo = os.path.abspath(os.path.join(HERE, '..', '..'))
    os.makedirs(os.path.dirname(GIT_LOCK), exist_ok=True)
    with open(GIT_LOCK, 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = os.path.join(HERE, 'data', 'harden', os.path.basename(out_dir.rstrip('/')))
        os.makedirs(d, exist_ok=True)
        paths = []
        for n in sorted(os.listdir(out_dir)):
            if n == f'{name}.jsonl' or n.startswith(f'{name}-'):
                shutil.copy2(os.path.join(out_dir, n), os.path.join(d, n))
                paths.append(os.path.join(d, n))
        if not paths:
            return
        subprocess.run(['git', '-C', repo, 'add', '--', *paths], capture_output=True)
        r = subprocess.run(['git', '-C', repo, 'commit', '-q', '-m', message, '--', *paths], capture_output=True, text=True)
        if r.returncode == 0:
            for i in range(4):
                p = subprocess.run(['git', '-C', repo, 'push', '-q', 'origin', 'HEAD'], capture_output=True, text=True)
                if p.returncode == 0:
                    break
                time.sleep(2 ** (i + 1))


class Service:
    def __init__(self, work, repo):
        self.data = os.path.join(work, 'service')
        os.makedirs(self.data, exist_ok=True)
        tok = os.path.join(work, 'token.txt')
        if not os.path.exists(tok):
            out = subprocess.run([VENV_PY, '-m', 'detpy.cache_service', 'token', '--data', self.data, '--org', 'b'],
                                 capture_output=True, text=True, check=True).stdout
            token = re.findall(r'[A-Za-z0-9_\-]{20,}', out)[-1]
            with open(tok, 'w') as f:
                f.write(token)
            os.chmod(tok, 0o600)
        self.token = open(tok).read().strip()
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        self.port = s.getsockname()[1]
        s.close()
        self.log = open(os.path.join(work, 'service.log'), 'a')
        self.p = subprocess.Popen([VENV_PY, '-m', 'detpy.cache_service', 'serve', '--data', self.data, '--host', '127.0.0.1',
                                   '--port', str(self.port)], stdout=self.log, stderr=self.log, start_new_session=True)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', self.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        self.url = f'http://127.0.0.1:{self.port}/{repo}'

    def stop(self):
        try:
            os.killpg(self.p.pid, signal.SIGTERM)
            self.p.wait(10)
        except Exception:
            pass


def plain_cmd(r, file):
    runner = r['runner']
    if runner == 'vitest':
        return ['npx', '--no-install', 'vitest', 'run', *r['args'], '--no-file-parallelism', file]
    return ['npx', '--no-install', 'jest', *r['args'], '--runInBand', '--runTestsByPath', file]


def classify(r, cwd, env, file, rundir, timeout):
    """B1.3: 10 plain runs of the test file at this state on this machine."""
    fails = 0
    exits = []
    for i in range(10):
        rc, _, _ = sh(plain_cmd(r, file), cwd, env, timeout, log=os.path.join(rundir, f'plain-{re.sub(r"[^A-Za-z0-9]", "_", file)[-80:]}-{i}.log'))
        exits.append(rc)
        if rc != 0:
            fails += 1
    cls = 'instability' if 0 < fails < 10 else 'wrong-reuse'
    return {'file': file, 'plain_fails': fails, 'plain_runs': 10, 'exits': exits, 'class': cls,
            'kind': None if cls == 'instability' else ('plain fails' if fails == 10 else 'engine only')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True)
    ap.add_argument('--engine', required=True, help='engine checkout (a worktree at a fixed commit, addon built)')
    ap.add_argument('--mode', choices=['url', 'dir'], default='url')
    ap.add_argument('--work', default='/home/runner/work/cacheb')
    # rows are written outside the repository and copied into harness/cache_b/data/harden at each checkpoint
    ap.add_argument('--out', default='/home/runner/work/cacheb/rows')
    ap.add_argument('--max-seconds', type=float, default=6000, help='stop cleanly before this (tracked task < 2 h)')
    ap.add_argument('--checkpoint', action='store_true', help='commit and push the rows every 30 minutes')
    o = ap.parse_args()
    t_start = time.time()
    pre = json.load(open(os.path.join(HERE, 'prereg.json')))['repos'][o.repo]
    engine_commit = subprocess.run(['git', '-C', o.engine, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', o.engine, 'status', '--porcelain', '--untracked-files=no'], capture_output=True, text=True).stdout.strip()
    if dirty:
        sys.exit(f'engine checkout {o.engine} has uncommitted changes: rows must name an engine commit')
    e12 = engine_commit[:12]
    work = os.path.join(o.work, e12, o.repo)
    os.makedirs(work, exist_ok=True)
    out_dir = os.path.join(o.out, e12)
    os.makedirs(out_dir, exist_ok=True)
    rows_path = os.path.join(out_dir, f'{o.repo}.jsonl')
    done = set()
    if os.path.exists(rows_path):
        for line in open(rows_path):
            try:
                done.add(json.loads(line)['i'])
            except (ValueError, KeyError):
                pass
    repo_dir = os.path.join(POOL, o.repo)
    cwd = os.path.join(repo_dir, pre['cwd']) if pre['cwd'] else repo_dir
    # NODE_PATH: this container's global module folder (its own tools update themselves between runs, which changed
    # the runtime identity's NODE_PATH root on drydock); CI runners have none and the pool repositories do not use it
    env = {k: v for k, v in os.environ.items() if k not in ('CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_PATH')}
    env['PATH'] = f"{NODE_BIN[pre['node']]}:{env['PATH']}"
    env.update({k: os.path.expandvars(v) for k, v in pre.get('env', {}).items() if k != 'PATH'})
    timeout = 3 * (pre['plain_wall_s_median_A'] or 300) + 900
    svc = Service(work, o.repo) if o.mode == 'url' else None
    last_ckpt = time.time()
    states = pre['harden']
    try:
        for i, st in enumerate(states):
            if i in done:
                continue
            if time.time() - t_start > o.max_seconds:
                print(f'{o.repo}: stopping before state {i} (time budget)', file=sys.stderr)
                break
            rundir = os.path.join(work, 'runs', f'{i:02d}')
            shutil.rmtree(rundir, ignore_errors=True)
            os.makedirs(rundir)
            row = {'repo': o.repo, 'i': i, 'n_states': len(states), 'sha': st['sha'], 'kind': st['kind'],
                   'pr': st.get('pr'), 'engine_commit': engine_commit, 'mode': o.mode, 'node': pre['node'],
                   'role': 'seed' if i == 0 else 'verify', 'ts': now(), 'nproc': os.cpu_count()}
            rc, dt, out = sh(f"git checkout -q -f --detach {st['sha']} && git clean -fdxq -e node_modules", repo_dir, env, 600)
            if rc != 0:
                row.update(status='ENV', error=f'checkout: {out.strip()[-500:]}')
                write_row(rows_path, row)
                continue
            rc, dt, out = sh(INSTALL[o.repo], repo_dir, env, 1800, log=os.path.join(rundir, 'install.log'))
            row.update(install_rc=rc, install_s=dt)
            if rc != 0:
                lines = [l for l in out.splitlines() if l.strip()]
                first = next((l for l in lines if re.search(r' error: |ERR_|ERR!|npm error code|ENOENT|EBADENGINE', l)), None)
                row.update(status='ENV', error=f'install: {(first or (lines[-1] if lines else "")).strip()[:400]}')
                write_row(rows_path, row)
                continue
            # runner caches inside the tree start empty (git clean keeps node_modules)
            sh("find . -path '*/node_modules/.vite*' -prune -exec rm -rf {} + ; find . -path '*/node_modules/.vitest*' -prune -exec rm -rf {} +",
               repo_dir, env, 600)
            cache = svc.url if svc else os.path.join(work, 'store')
            renv = dict(env)
            if svc:
                renv['FENVIX_CACHE_TOKEN'] = svc.token
                renv['FENVIX_CACHE_LOCAL'] = os.path.join(rundir, 'local')
            cmd = ['node', os.path.join(o.engine, 'node', 'bin', 'detjs.js'), pre['runner'], *(['run'] if pre['runner'] == 'vitest' else []),
                   *pre['args'], '--det', '--det-workers=1', f'--det-trace={rundir}/trace.jsonl', f'--det-cache={cache}',
                   f'--det-cache-summary={rundir}/summary.json', f'--det-cache-receipts={rundir}/receipts.jsonl']
            if pre['runner'] == 'jest':
                # a fixed path, emptied before every run: the engine keys Jest's command-line options, so a
                # per-run path would change the configuration digest and nothing could ever be reused
                jc = os.path.join(o.work, 'jest-cache', o.repo)
                shutil.rmtree(jc, ignore_errors=True)
                os.makedirs(jc)
                cmd.append(f'--cacheDirectory={jc}')
            if i > 0:
                cmd.append('--det-cache-verify')
            rc, dt, out = sh(cmd, cwd, renv, timeout, log=os.path.join(rundir, 'run.log'))
            row.update(exit=rc, wall_s=dt, cmd=' '.join(cmd))
            try:
                s = json.load(open(os.path.join(rundir, 'summary.json')))
            except (OSError, ValueError):
                s = None
            if s is None:
                row.update(status='NO-SUMMARY', error=[l for l in out.splitlines() if l.strip()][-5:])
                write_row(rows_path, row)
                continue
            mism = s.get('verify_mismatches') or []
            row.update(status='ok', reused_files=s.get('reused_files'), reused_tests=s.get('reused_tests'),
                       ran_files=len(s.get('ran_files') or {}), recorded=s.get('recorded'), verified=s.get('verified'),
                       verified_tests=s.get('verified_tests'), verify_mismatches_tests=s.get('verify_mismatches_tests'),
                       verify_mismatches=mism, verify_unchecked=s.get('verify_unchecked'),
                       miss_reasons=s.get('miss_reasons'), not_cached=s.get('not_cached'), disabled=s.get('disabled'),
                       remote={k: (s.get('remote') or {}).get(k) for k in ('error', 'requests', 'pull_proven', 'pull_files_with_candidates', 'push_entry_docs_new', 'push_entries_unresolved')} if s.get('remote') else None,
                       error=s.get('error'))
            files = sorted({m['nodeid'].split('::', 1)[0].split('@@', 1)[0] for m in mism if m.get('cached') == 'passed'})
            row['mismatch_inputs_file'] = None
            if mism:
                keep = os.path.join(out_dir, f'{o.repo}-{i:02d}-mismatch-inputs.json')
                with open(keep, 'w') as f:
                    json.dump(s.get('verify_mismatch_inputs'), f)
                row['mismatch_inputs_file'] = os.path.relpath(keep, HERE)
            row['classified'] = [classify(pre, cwd, env, f, rundir, timeout) for f in files]
            row['wrong_reuse'] = sum(c['class'] == 'wrong-reuse' for c in row['classified'])
            # traces are large: kept only for a state with a mismatch or a verify gap
            if not mism and not row.get('verify_unchecked'):
                for n in ('trace.jsonl',):
                    try:
                        os.remove(os.path.join(rundir, n))
                    except OSError:
                        pass
            write_row(rows_path, row)
            print(f"{o.repo} [{i}/{len(states)}] {st['sha'][:10]} exit {rc} {dt}s reused {row['reused_files']} "
                  f"mismatches {len(mism)} wrong {row['wrong_reuse']} unchecked {len(row.get('verify_unchecked') or [])}", file=sys.stderr)
            if o.checkpoint and time.time() - last_ckpt > CHECKPOINT_S:
                git_checkpoint(out_dir, o.repo, f'cache B1 harden checkpoint: {o.repo} through state {i} (engine {e12})')
                last_ckpt = time.time()
    finally:
        if svc:
            svc.stop()
        if o.checkpoint:
            git_checkpoint(out_dir, o.repo, f'cache B1 harden checkpoint: {o.repo} (engine {e12})')


def write_row(path, row):
    with open(path, 'a') as f:
        f.write(json.dumps(row) + '\n')


if __name__ == '__main__':
    main()
