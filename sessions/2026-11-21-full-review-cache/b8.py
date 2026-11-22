import sys, os; sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from h56 import run_all
S = []
BIND = lambda src, dst: ("unshare", "-m", "sh", "-c", f'mount --bind {src} {dst} && exec "$@"', "sh")
for m in ("serial", "n2"):
    S.append(dict(name="E12 conftest reads an allowlisted env var at import (GITHUB_JOB)", mode=m,
        v1={"helper.py": "STATE = {}\n", "tests/conftest.py": "import os, helper\nhelper.STATE['job'] = os.environ.get('GITHUB_JOB')\n",
            "tests/b/test_b.py": "import helper\n\ndef test_victim():\n    assert helper.STATE['job'] == 'job1'\n"},
        ctx1={"env": {"GITHUB_JOB": "job1"}}, ctx2={"env": {"GITHUB_JOB": "job2"}}))
    S.append(dict(name="E12b test module reads an allowlisted env var at import (GITHUB_RUN_ID)", mode=m,
        v1={"tests/b/test_b.py": "import os\nRUN = os.environ.get('GITHUB_RUN_ID')\n\ndef test_victim():\n    assert RUN == '1'\n"},
        ctx1={"env": {"GITHUB_RUN_ID": "1"}}, ctx2={"env": {"GITHUB_RUN_ID": "2"}}))
    S.append(dict(name="E12c test reads an allowlisted env var (GITHUB_RUN_ID) via os.environ", mode=m,
        v1={"tests/b/test_b.py": "import os\n\ndef test_victim():\n    assert os.environ.get('GITHUB_RUN_ID') == '1'\n"},
        ctx1={"env": {"GITHUB_RUN_ID": "1"}}, ctx2={"env": {"GITHUB_RUN_ID": "2"}}))
    S.append(dict(name="H1 /etc/passwd read by C (pwd.getpwuid)", mode=m,
        v1={"tests/b/test_b.py": "import pwd\n\ndef test_victim():\n    assert pwd.getpwuid(0).pw_dir == '/root'\n"},
        ctx1={}, ctx2={"prefix": BIND("HERE/passwd2", "/etc/passwd")}))
run_all(S, workers=8)
