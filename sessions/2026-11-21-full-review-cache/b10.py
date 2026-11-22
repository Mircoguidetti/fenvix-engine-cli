import sys, os; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
S = []
W = "import warnings\n\ndef test_victim():\n    warnings.warn('x', UserWarning)\n"
for m in ("serial", "n2"):
    S.append(dict(name="I1 pytest.ini filterwarnings=error added", mode=m, v1={"tests/b/test_b.py": W}, v2={"pytest.ini": "[pytest]\npythonpath = .\nfilterwarnings = error\n"}))
    S.append(dict(name="I2 pyproject.toml ini options changed (no pytest.ini)", mode=m, v1={"pytest.ini": None, "pyproject.toml": "[tool.pytest.ini_options]\npythonpath = ['.']\n", "tests/b/test_b.py": W}, v2={"pyproject.toml": "[tool.pytest.ini_options]\npythonpath = ['.']\nfilterwarnings = ['error']\n"}))
    S.append(dict(name="I3 setup.cfg [tool:pytest] changed", mode=m, v1={"pytest.ini": None, "setup.cfg": "[tool:pytest]\npythonpath = .\n", "tests/b/test_b.py": W}, v2={"setup.cfg": "[tool:pytest]\npythonpath = .\nfilterwarnings = error\n"}))
    S.append(dict(name="I4 tox.ini [pytest] addopts changed", mode=m, v1={"pytest.ini": None, "tox.ini": "[pytest]\npythonpath = .\n", "tests/b/test_b.py": W}, v2={"tox.ini": "[pytest]\npythonpath = .\naddopts = -W error\n"}))
    S.append(dict(name="L1 LANG", mode=m, v1={"tests/b/test_b.py": "import locale\n\ndef test_victim():\n    locale.setlocale(locale.LC_ALL, '')\n    assert locale.getlocale()[1] == 'UTF-8'\n"}, ctx1={"env": {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}}, ctx2={"env": {"LANG": "C", "LC_ALL": "C"}}))
    S.append(dict(name="T1 TZ", mode=m, v1={"tests/b/test_b.py": "import time\n\ndef test_victim():\n    assert time.localtime(0).tm_hour == 0\n"}, ctx1={"env": {"TZ": "UTC"}}, ctx2={"env": {"TZ": "Asia/Tokyo"}}))
run_all(S, workers=8)
