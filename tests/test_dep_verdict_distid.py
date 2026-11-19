"""Prototype --det-cache-dists (detpy.distid): identity files and path -> distribution mapping."""

import os

import pluggy
import pytest

from detpy import distid, proofcache


def test_top_of():
    assert distid._top_of("pkg/__init__.py") == "pkg"
    assert distid._top_of("mod.py") == "mod"
    assert distid._top_of("_ext.cpython-312-x86_64-linux-gnu.so") == "_ext"
    assert distid._top_of("pkg-1.0.dist-info/METADATA") is None
    assert distid._top_of("../../bin/tool") is None


def test_index_maps_files_and_writes_identity(tmp_path):
    ix = distid.Index(str(tmp_path))
    assert ix.dist_of(os.path.realpath(pytest.__file__)) == "pytest"
    assert ix.dist_of(os.path.realpath(pluggy.__file__)) == "pluggy"
    assert "pytest" in ix.tops.get("_pytest", set())
    assert any(line.startswith("detpy:") for line in ix.groups.get("pytest11", []))
    out = tmp_path / "ident"
    ix.write(str(out))
    assert (out / "d" / "pytest").read_text().startswith("pytest==")
    assert (out / "m" / "_pytest").read_text().strip() == "pytest"
    assert (out / distid.ALL).exists() and (out / distid.EP_ALL).exists()
    # a stale identity file (a distribution uninstalled since) is removed
    (out / "d" / "gone").write_text("x")
    ix.write(str(out))
    assert not (out / "d" / "gone").exists()


def test_runtime_identity_per_dist_leaves_distributions_out(tmp_path):
    d1, info1, _ = proofcache.runtime_identity(str(tmp_path))
    d2, info2, _ = proofcache.runtime_identity(str(tmp_path), per_dist=True)
    assert info1["distributions"] != "per-test"
    assert info2["distributions"] == "per-test" and info2["n_distributions"] is None
    assert d1 != d2
