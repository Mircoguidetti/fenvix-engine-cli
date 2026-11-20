# fenvix

fenvix makes CI test runs deterministic: every flaky test becomes a reproducible defect with a replay command,
nightly exploration finds hidden bugs, and a test is skipped only when its result would provably be the same
(skip with proof).

This package is the Python side: the pytest plugin (`--det`), the runner shells (`python -m detpy unittest|django|nose2|ward|zope|doctest`)
and the `fenvix` command. It ships inside the engine artifact for our machines (docs/INSTALL.md of the source
repository), with the Node shells.

## Install

```bash
pip install wheels/fenvix-*.whl   # from the engine artifact; CPython 3.12, 3.13, 3.14 on Linux x86_64 (glibc 2.28+)
fenvix --version
```

## Use

```bash
pytest --det                          # fixed order, seeds, virtual clock, closed network; trace in .detpy/trace.jsonl
pytest --det --det-seed=42            # reproducible shuffle
pytest --det --det-cache=.fenvix-cache   # skip with proof
fenvix verify run1.jsonl run2.jsonl   # compare the fingerprints of two runs
fenvix doctor                         # check the installation
```

The import package is `detpy` (`python -m detpy`, plugin `detpy.plugin`). The unrelated PyPI project named
`detpy` installs a package with the same import name: do not install both (`fenvix doctor` reports it).

Changelog: CHANGELOG.md in the source repository.
