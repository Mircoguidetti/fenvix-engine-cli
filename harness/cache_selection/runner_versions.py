#!/usr/bin/env python3
"""Spec step 6 evidence: runner version and the --help line of the list-only selection flag.

Usage: python3 runner_versions.py <repo-key> [...]
At each repository's default head (prs.json default_head): fresh install with the repos.json
command, then `<runner> --version` and `<runner> list --help` (vitest) or `jest --help` (jest),
keeping the lines that name the flags used by cs.py. Appends to runner_versions.json.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, 'repos.json')))


def sh(cmd, cwd, env):
    p = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main(keys):
    path = os.path.join(HERE, 'runner_versions.json')
    out = json.load(open(path)) if os.path.exists(path) else {}
    for key in keys:
        c = CFG[key]
        head = json.load(open(os.path.join(HERE, 'data', key, 'prs.json')))['default_head']
        clone = c['clone']
        cwd = os.path.join(clone, c.get('subdir', '') or '')
        env = dict(os.environ)
        for k, v in (c.get('env') or {}).items():
            env[k] = os.path.expandvars(v)
        rec = dict(commit=head, cmds=[])
        steps = [f'git checkout -q -f --detach {head} && git clean -fdxq -e node_modules',
                 'find . -name node_modules -type d -prune -exec rm -rf {} +', c['install']]
        for s in steps:
            rc, o = sh(s, clone, env)
            rec['cmds'].append(f'{s} -> exit {rc}')
            if rc:
                rec['error'] = o[-500:]
                break
        if 'error' not in rec:
            if c['runner'] == 'vitest':
                rc, o = sh('npx --no-install vitest --version', cwd, env)
                rec['cmds'].append(f'npx --no-install vitest --version -> exit {rc}')
                rec['version'] = o.strip().splitlines()[-1] if o.strip() else None
                rc, o = sh('npx --no-install vitest list --help', cwd, env)
                rec['cmds'].append(f'npx --no-install vitest list --help -> exit {rc}')
                rec['help_lines'] = [l.strip() for l in o.splitlines() if '--filesOnly' in l or '--changed' in l]
            else:
                rc, o = sh('npx --no-install jest --version', cwd, env)
                rec['cmds'].append(f'npx --no-install jest --version -> exit {rc}')
                rec['version'] = o.strip().splitlines()[-1] if o.strip() else None
                rc, o = sh('npx --no-install jest --help', cwd, env)
                rec['cmds'].append(f'npx --no-install jest --help -> exit {rc}')
                rec['help_lines'] = [l.strip() for l in o.splitlines() if '--listTests' in l or '--findRelatedTests' in l]
        out[key] = rec
        json.dump(out, open(path, 'w'), indent=1)
        print(key, rec.get('version'), rec.get('help_lines'), rec.get('error', '')[-200:])


if __name__ == '__main__':
    main(sys.argv[1:])
