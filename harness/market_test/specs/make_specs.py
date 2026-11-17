"""Writes the repository specs of the market test (harness/market_test/). The JSON files are what the workflow reads.

    python3 harness/market_test/specs/make_specs.py [--smoke]

Every spec pins the head commit (``seq.head``) so that all shards walk the same window (the v2 Home Assistant
lesson in harness/skip_study2/REPORT.md). ``--smoke`` writes a 3-commit variant of every spec into
``specs/smoke/`` with a small sample, to check install, discovery and unit runs before the full walk.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GH = "https://github.com/"

# default-branch heads pinned on 2026-11-17 (git ls-remote <url> HEAD)
HEADS = {
    "airflow": "56bbac12ad9853865c7fff24230994643d91c168",
    "integrations-core": "5bedd04ea3a726071903a753be0b265b70e4a539",
    "moto": "96f50b1aa902eccb0a3763b80f37d7af265d9130",
    "transformers": "a2a53c3be2828dfb0c4f89648a406e58d31d1230",
    "mlflow": "c365f861ff68cd85d8be17103748d60c3d14c63e",
    "pydantic-ai": "62e7b66c9f4da5c788eb360e49522a98e8fa0c86",
    "prefect": "5e8ca118fc514ffe9ab3355ea5cf1c28c347de11",
    "esphome": "141789d2400fb9f465d95263167c367a79aa8277",
    "litellm": "17e6ea8cb7d4bf1c090e2aaa35d94116ef5ecd6c",
    "community-general": "63fe14d2aa6ac026825ffb805a5c8a08a97855ba",
    "haystack": "050a979caca073da3b6d62662b766fb804575ebf",
}

PYTEST = ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "s2_report"]


def venv(py="3.12"):
    return f"test -x {{py}} || uv venv -q --python {py} {{venv}}"


def uvsync(args, py="3.12"):
    """uv sync into the walker's virtualenv; falls back to an unlocked sync when the lock does not resolve."""
    e = "UV_PROJECT_ENVIRONMENT={venv}"
    return f"{e} uv sync -q --python {py} --frozen {args} || {e} uv sync -q --python {py} {args}"


SPECS = [
    {
        "name": "airflow", "url": GH + "apache/airflow", "lang": "pytest",
        "apt": ["libkrb5-dev", "libldap2-dev", "libsasl2-dev", "unixodbc-dev", "default-libmysqlclient-dev",
                "pkg-config", "libpq-dev", "freetds-dev", "libxmlsec1-dev", "libxml2-dev", "libxslt1-dev",
                "libgraphviz-dev", "libffi-dev"],
        "install": [venv("3.12"), uvsync("--all-packages")],
        "install_files": ["uv.lock", "pyproject.toml", "*/pyproject.toml", "providers/*/pyproject.toml",
                          "shared/*/pyproject.toml"],
        # a template AIRFLOW_HOME with an initialised sqlite DB per commit; every unit runs on its own copy
        # (path fixed per unit), so parallel units never share a database. The DB is built from the migration
        # files, which are therefore an input of every unit (db_inputs_always).
        "build": ["rm -rf {work}/afhome {work}/afh && mkdir -p {work}/afhome {work}/afh && "
                  "AIRFLOW_HOME={work}/afhome AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:///{work}/afhome/unittests.db "
                  "{py} -m pytest -q -p no:cacheprovider --with-db-init "
                  "airflow-core/tests/unit/utils/test_helpers.py -x > {work}/afbuild.log 2>&1; "
                  "tail -5 {work}/afbuild.log; test -f {work}/afhome/.airflow_db_initialised"],
        "env": {"AIRFLOW_HOME": "{work}/afh", "BACKEND": "sqlite"},
        "db_inputs": ["airflow-core/src/airflow/migrations/**/*.py"], "db_inputs_always": True,
        "units": {"include": ["airflow-core/tests/unit/**/test_*.py", "providers/*/tests/unit/**/test_*.py",
                              "task-sdk/tests/**/test_*.py"],
                  "exclude": ["*/tests/system/*", "*/tests/integration/*"], "sample": 0.06, "seed": "s2"},
        "cmd": ["bash", "-c", "h={work}/afh/$(printf %s '{unit}' | md5sum | cut -c1-12); rm -rf $h; "
                "cp -r {work}/afhome $h; AIRFLOW_HOME=$h AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:///$h/unittests.db "
                "exec {py} " + " ".join(PYTEST) + " {unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "assumed 4 vCPU per test job (Airflow CI splits test types over many jobs)"},
    },
    {
        "name": "integrations-core", "url": GH + "DataDog/integrations-core", "lang": "pytest",
        "apt": ["unixodbc-dev", "libkrb5-dev", "libsasl2-dev", "libpq-dev", "freetds-dev", "libssl-dev"],
        "install": [venv("3.13"),
                    "python3 {harness}/pyinstall.py --python {py} -r agent_requirements.in",
                    "uv pip install -q --python {py} pytest pytest-asyncio pytest-mock mock freezegun requests-mock "
                    "pytest-benchmark pytest-cov",
                    "uv pip install -q --python {py} --no-deps -e ./datadog_checks_base -e ./datadog_checks_dev "
                    "$(for d in */; do test -f $d/pyproject.toml && test -d $d/datadog_checks && "
                    "test $d != datadog_checks_base/ && test $d != datadog_checks_dev/ && echo -e ./$d; done)",
                    "uv pip install -q --python {py} -e ./datadog_checks_dev || true",
                    "uv pip install -q --python {py} -e ./datadog_checks_tests_helper || true"],
        "install_files": ["agent_requirements.in", "*/pyproject.toml"],
        "units": {"include": ["*/tests/**/test_*.py", "*/tests/test_*.py"],
                  "exclude": ["datadog_checks_dev/*", "ddev/*", ".builders/*", "*/tests/e2e/*"],
                  "sample": 1.0, "seed": "s2"},
        # ddev sets each integration's hatch environment variables: ddenv.py does the same, then execs pytest
        "cmd": ["{py}", "{harness}/ddenv.py", "{py}", "{unit}", *PYTEST[2:], "-m", "not e2e and not integration"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "one test job per changed integration in CI; 4 vCPU assumed"},
    },
    {
        "name": "moto", "url": GH + "getmoto/moto", "lang": "pytest",
        "install": [venv("3.12"),
                    "uv pip install -q --python {py} -e '.[all,server]' -r requirements-tests.txt"],
        "install_files": ["setup.cfg", "setup.py", "pyproject.toml", "requirements*.txt"],
        "units": {"include": ["tests/**/test_*.py"], "sample": 0.25, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "Makefile test-only: serial pytest plus one -n 4 group, one runner"},
    },
    {
        "name": "transformers", "url": GH + "huggingface/transformers", "lang": "pytest",
        "apt": ["ffmpeg"],
        "install": [venv("3.12"),
                    "uv pip install -q --python {py} torch torchvision --index-url https://download.pytorch.org/whl/cpu",
                    "uv pip install -q --python {py} -e '.[testing,sentencepiece,tokenizers,vision,tiktoken]' || "
                    "uv pip install -q --python {py} -e '.[testing,sentencepiece,vision]'",
                    # torchaudio from PyPI does not load against the CPU torch build: tests skip audio without it
                    "uv pip uninstall -q --python {py} torchaudio || true"],
        "install_files": ["setup.py", "pyproject.toml"],
        "units": {"include": ["tests/**/test_*.py"], "exclude": ["tests/sagemaker/*", "tests/quantization/*"],
                  "sample": 0.05, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "-o", "addopts=", "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 8, "source": "CircleCI tests_torch: parallel containers; 8 workers assumed"},
    },
    {
        "name": "mlflow", "url": GH + "mlflow/mlflow", "lang": "pytest",
        "install": [venv("3.11"), uvsync("--group test --group build --all-extras", "3.11") + " || " + uvsync("--group test --group build", "3.11")],
        "install_files": ["uv.lock", "pyproject.toml", "requirements/*.txt", "requirements/*.yaml"],
        "units": {"include": ["tests/**/test_*.py"], "exclude": ["tests/examples/*", "tests/db/*"],
                  "sample": 0.1, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "GitHub Actions python job groups, 4 vCPU each assumed"},
    },
    {
        "name": "pydantic-ai", "url": GH + "pydantic/pydantic-ai", "lang": "pytest",
        "install": [venv("3.12"), uvsync("--all-extras --no-extra mcp-tasks --all-packages")],
        "install_files": ["uv.lock", "pyproject.toml", "*/pyproject.toml"],
        "env": {"PYTEST_TEST_BUDGET_SECONDS": "100000"},
        "units": {"include": ["tests/**/test_*.py"], "sample": 0.3, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "Makefile test: pytest -n auto --dist=loadgroup on one runner"},
    },
    {
        "name": "prefect", "url": GH + "PrefectHQ/prefect", "lang": "pytest",
        "install": [venv("3.12"), uvsync("")],
        "install_files": ["uv.lock", "pyproject.toml"],
        "units": {"include": ["tests/**/test_*.py"], "sample": 0.12, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "python-tests.yaml: -n auto per job, 4 vCPU assumed"},
    },
    {
        "name": "esphome", "url": GH + "esphome/esphome", "lang": "pytest",
        "install": [venv("3.12"),
                    "uv pip install -q --python {py} -r requirements.txt -r requirements_test.txt -e ."],
        "install_files": ["requirements*.txt", "pyproject.toml", "setup.py"],
        "units": {"include": ["tests/**/test_*.py"], "exclude": ["tests/integration/*", "tests/benchmarks/*"],
                  "sample": 0.5, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "--no-cov", "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "ci.yml pytest job: -n auto on one runner"},
    },
    {
        "name": "litellm", "url": GH + "BerriAI/litellm", "lang": "pytest",
        # --all-groups pulls litellm-admin-mcp from a GitHub archive that can be unreachable (403): fall back to
        # every extra plus the dev group, which holds the unit-test dependencies
        "install": [venv("3.12"), uvsync("--all-groups --all-extras") + " || " + uvsync("--all-extras --group dev")],
        "install_files": ["uv.lock", "pyproject.toml"],
        "units": {"include": ["tests/unit/**/test_*.py"], "sample": 0.1, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "Makefile test-unit-* groups: pytest -n 4 per group"},
    },
    {
        "name": "community-general", "url": GH + "ansible-collections/community.general", "lang": "pytest",
        "install": [venv("3.12"),
                    "uv pip install -q --python {py} ansible-core pytest pytest-mock pytest-xdist",
                    "python3 {harness}/pyinstall.py --python {py} -r tests/unit/requirements.txt",
                    # tests/unit/requirements.yml: community.internal_test_tools (from GitHub, not Galaxy)
                    "mkdir -p {work}/ac/ansible_collections/community && "
                    "(test -d {work}/ac/ansible_collections/community/internal_test_tools || git clone -q --depth 1 "
                    "https://github.com/ansible-collections/community.internal_test_tools "
                    "{work}/ac/ansible_collections/community/internal_test_tools)"],
        "install_files": ["tests/unit/requirements.txt", "tests/unit/requirements.yml"],
        # the checkout itself lives at ansible_collections/community/general (walker option src_dir), as
        # ansible-test lays it out; the tests load through ansible-test's collection pytest plugin
        "src_dir": "ac/ansible_collections/community/general",
        "env": {"PYTHONPATH": "{work}/ac", "ANSIBLE_COLLECTIONS_PATH": "{work}/ac",
                "ANSIBLE_CONTROLLER_MIN_PYTHON_VERSION": "3.12"},
        "roots": ["{work}/ac"],
        "units": {"include": ["tests/unit/**/test_*.py"], "sample": 1.0, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "-p", "ansible_test._util.target.pytest.plugins.ansible_pytest_collections",
                "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "ansible-test units: one runner per Python version, 4 vCPU assumed"},
    },
    {
        "name": "haystack", "url": GH + "deepset-ai/haystack", "lang": "pytest",
        "install": [venv("3.12"),
                    "uv pip install -q --python {py} torch --index-url https://download.pytorch.org/whl/cpu",
                    "python3 {harness}/hatchdeps.py pyproject.toml test > {work}/hs-reqs.txt && "
                    "python3 {harness}/pyinstall.py --python {py} -r {work}/hs-reqs.txt",
                    "uv pip install -q --python {py} -e ."],
        "install_files": ["pyproject.toml"],
        "units": {"include": ["test/**/test_*.py"], "sample": 0.5, "seed": "s2"},
        "cmd": ["{py}", *PYTEST, "-m", "not integration", "{unit}"],
        "unit_timeout": 900, "verify": 0.08,
        "ci": {"workers": 4, "source": "tests.yml unit job: hatch run test:unit on one runner"},
    },
]

# mlflow in developer mode: with CI=true (the walker's default, as in mlflow's CI) a session fixture of every test
# process builds a wheel of the whole source tree (--serve-wheel), so every test reads every file; CI=false turns
# it off. Both are measured: "mlflow" (CI mode) and "mlflow-dev".
_mlflow = next(s for s in SPECS if s["name"] == "mlflow")
SPECS.append(dict(json.loads(json.dumps(_mlflow)), name="mlflow-dev", ci_env="false", untracked_exists_are_outputs=True))
HEADS["mlflow-dev"] = HEADS["mlflow"]

SMOKE_SAMPLE = {"mlflow-dev": 0.04, "airflow": 0.02, "integrations-core": 0.03, "moto": 0.05, "transformers": 0.03, "mlflow": 0.04,
                "pydantic-ai": 0.05, "prefect": 0.06, "esphome": 0.06, "litellm": 0.015,
                "community-general": 0.15, "haystack": 0.2}


# a warm bytecode cache in the virtualenv, as a cached CI environment has: without it the first runs write
# __pycache__ directories into site-packages and the next commit sees "appeared" paths in every unit
COMPILE = "{py} -m compileall -q -j 4 {venv}/lib > /dev/null 2>&1 || true"


def main():
    smoke = "--smoke" in sys.argv
    for s in SPECS:
        s = json.loads(json.dumps(s))
        s["install"].append(COMPILE)
        s["seq"] = {"kind": "first-parent", "n": 51, "head": HEADS[s["name"]]}
        if smoke:
            s["seq"]["n"] = 3
            s["units"]["sample"] = SMOKE_SAMPLE[s["name"]]
            out = HERE / "smoke" / f"{s['name']}.json"
        else:
            out = HERE / f"{s['name']}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(s, indent=1) + "\n")
        print(out)


if __name__ == "__main__":
    main()
