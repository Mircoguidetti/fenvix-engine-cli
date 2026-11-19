"""Harness shim (not part of detpy): under xdist, give each worker its own --det-trace / --det-outcomes file,
and record which tests each worker ran, in order. Loaded with -p xd_pertrace."""
import json, os
import pytest

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    wid = getattr(config, "workerinput", {}).get("workerid")
    if not wid:
        return
    opt = config.option
    for name in ("det_trace", "det_outcomes", "det_cache_receipts"):
        v = getattr(opt, name, None)
        if v:
            root, ext = os.path.splitext(v)
            setattr(opt, name, f"{root}.{wid}{ext}")
    config._xd_wid = wid
    config._xd_ran = []

def pytest_runtest_logstart(nodeid, location):
    pass

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    cfg = item.config
    if hasattr(cfg, "_xd_ran"):
        cfg._xd_ran.append(item.nodeid)
    yield

def pytest_sessionfinish(session):
    cfg = session.config
    if hasattr(cfg, "_xd_ran") and getattr(cfg.option, "det_trace", None):
        with open(os.path.splitext(cfg.option.det_trace)[0] + ".ran.json", "w") as f:
            json.dump({"worker": cfg._xd_wid, "pid": os.getpid(), "ran": cfg._xd_ran,
                       "hashseed": os.environ.get("PYTHONHASHSEED")}, f)
