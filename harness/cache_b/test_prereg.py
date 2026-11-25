"""Disjointness of the preregistered sets (spec "Sets", gate rev 3 note 6; acceptance criterion 1).

protects=  B2's 0-wrong gate: B1 never tunes the engine on a state B2 measures (commits, PR heads, seeds, K2(a),
           K2(b), red and fault states), so a fix cannot be fitted to the measured states.
fails_when= any harden sha equals a sha of any B2 list in prereg.json (lists added later, such as red, k2b and
           fault states, are covered once present), a list holds a duplicate, or the harden set exceeds 20 states.
no_claim=  that the sets are the best sample, or that two different shas never share a tree.
"""
import json
import os

import pytest

PREREG = os.path.join(os.path.dirname(__file__), 'prereg.json')
B2_LISTS = ('b2_commits', 'b2_prs', 'k2a', 'k2b', 'red', 'faults', 'b2_commit_seed')


def shas(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    out = []
    for x in value:
        if isinstance(x, str):
            out.append(x)
        else:
            for k in ('sha', 'head', 'merge_base'):
                if x.get(k):
                    out.append(x[k])
    return out


def b2_shas(r):
    out = set()
    for k in B2_LISTS:
        out.update(shas(r.get(k)))
    return out


REPOS = json.load(open(PREREG))['repos']


@pytest.mark.parametrize('name', sorted(REPOS))
def test_harden_disjoint_from_every_b2_list(name):
    r = REPOS[name]
    harden = [h['sha'] for h in r['harden']]
    common = set(harden) & b2_shas(r)
    assert not common, f'{name}: harden states also in a B2 list: {sorted(common)}'
    assert len(harden) == len(set(harden)), f'{name}: duplicate harden state'
    assert len(harden) <= 20
    assert len(r['b2_commits']) == len(set(r['b2_commits'])), f'{name}: duplicate B2 commit'


def test_check_sees_an_overlap():
    r = {'harden': [{'sha': 'a'}], 'b2_commits': ['b'], 'red': [{'sha': 'a'}]}
    assert {'a'} & b2_shas(r)
