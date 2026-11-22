"""The attack suite's registry must cover every attack file in the tree.

``tests/attacks.py`` is the one entry point that runs every attack on the verifier. It is only worth having if it
cannot fall behind, so this file fails when an attack file exists that the registry does not name. That is what
stops a seventh place from quietly appearing, which is how the attacks ended up in six to begin with.

The attacks themselves are not run here: that would run them twice in the engine's own suite. ``attacks.py`` runs
them, and CI calls it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from attacks import NODE_ATTACKS, PYTHON_ATTACKS, ROOT

#: A file is an attack file when its name says so, or when its text asserts on a `fenvix verify` verdict while
#: changing something between two runs. The patterns are deliberately wide: a false hit is one line of registry,
#: a miss is an attack nobody runs.
_NAME_HINTS = ("verifier", "verify_inputs", "verify-inputs", "attacks", "review_r05", "review-r05",
                "pycache", "review_r023c")


def _candidates() -> dict[str, list[str]]:
    """Attack files found in the tree, by language."""
    out: dict[str, list[str]] = {"python": [], "node": []}
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        if any(h in p.name for h in _NAME_HINTS):
            out["python"].append(str(p.relative_to(ROOT)))
    for p in sorted((ROOT / "node" / "test").glob("*.test.js")):
        if any(h in p.name for h in _NAME_HINTS):
            out["node"].append(str(p.relative_to(ROOT)))
    return out


def test_the_registry_names_every_attack_file_in_the_tree():
    found = _candidates()
    missing_py = [f for f in found["python"] if f not in PYTHON_ATTACKS]
    missing_node = [f for f in found["node"] if f not in NODE_ATTACKS]
    assert not missing_py and not missing_node, (
        "tests/attacks.py does not run these attack files, so a change can be made without them:\n  "
        + "\n  ".join(missing_py + missing_node)
        + "\nAdd each one to PYTHON_ATTACKS or NODE_ATTACKS with a line saying what it attacks."
    )


def test_every_registered_attack_file_exists():
    gone = [f for f in list(PYTHON_ATTACKS) + list(NODE_ATTACKS) if not (ROOT / f).exists()]
    assert not gone, f"the registry names files that are not in the tree (renamed? deleted?): {gone}"


def test_every_registered_attack_file_says_what_it_attacks():
    for f, why in {**PYTHON_ATTACKS, **NODE_ATTACKS}.items():
        assert why and len(why) > 20, f"{f}: the registry entry must say what the file attacks, got {why!r}"


def test_the_general_rules_own_file_is_registered_first():
    """The general rule is the one attack that covers the channels nobody has thought of, so it runs first: when
    it fails, every channel-specific result below it is beside the point."""
    assert list(PYTHON_ATTACKS)[0] == "tests/test_provable_general_rule.py"


@pytest.mark.parametrize("half", ["python", "node"])
def test_the_entry_point_can_list_each_half(half):
    """`--list` must work without running anything: it is how CI and a reader see the registry."""
    from attacks import main

    assert main(["--list", "--only", half]) == 0


def test_the_registry_has_no_duplicate_entries():
    both = list(PYTHON_ATTACKS) + list(NODE_ATTACKS)
    assert len(both) == len(set(both))


def test_the_attack_files_really_assert_on_a_verify_verdict():
    """A file in the registry that never looks at a verdict is not an attack, and the registry would be lying.

    There are two verdicts the engine can state falsely, and an attack file must look at one of them: the
    verifier's ("identical", NOT PROVEN) and the cache's ("reused", a test reported passed from the cache). The
    second was added with Block 2's files: a wrong reuse is the same defect as a false IDENTICAL, so refusing it
    a place here would leave the cache's attacks with no entry point. Neither half is a weaker test than the
    other: a file matching neither is still rejected.
    """
    verify_verdict = re.compile(r"verify|IDENTICAL|NOT PROVEN|returncode|identical", re.I)
    cache_verdict = re.compile(r"reuse|reused|cache_run|det-cache|det_cache|assert_outcomes", re.I)
    for f in list(PYTHON_ATTACKS) + list(NODE_ATTACKS):
        text = (ROOT / f).read_text(errors="replace")
        assert verify_verdict.search(text) or cache_verdict.search(text), (
            f"{f} never looks at a verifier verdict or a cache reuse: is it really an attack file?"
        )
