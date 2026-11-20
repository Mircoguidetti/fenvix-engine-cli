"""The pytest plugin as loaded on an interpreter fenvix does not support (see :mod:`detpy._support`).

It imports nothing of the engine. A run that asks for the engine (any ``--det*`` option on the command line, in
``PYTEST_ADDOPTS`` or ``DETPY=1``) stops at once with the message and exit code 4; any other pytest run goes on
unchanged, so an installed-but-unsupported plugin never breaks a plain ``pytest``.
"""

import os

from . import _support


def _asks_for_engine(args):
    words = list(args) + os.environ.get("PYTEST_ADDOPTS", "").split()
    return any(w == "--det" or w.startswith("--det-") or w.startswith("--det=") for w in words)


def pytest_load_initial_conftests(early_config, parser, args):
    if _asks_for_engine(args) or _asks_for_engine(early_config.invocation_params.args):
        import pytest

        raise pytest.UsageError(_support.message())


def pytest_report_header(config):
    return _support.message() + " (the plugin is inactive)"
