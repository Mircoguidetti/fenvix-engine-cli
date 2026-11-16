"""Writes the repository specs of the skip study 2 (run once; the JSON files are what the workflow reads)."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GH = "https://github.com/"

ha = {
    "name": "home-assistant", "url": GH + "home-assistant/core", "lang": "pytest",
    "seq": {"kind": "first-parent", "n": 51},
    "apt": ["bluez", "ffmpeg", "libturbojpeg0", "libxml2-utils", "libudev-dev", "libpcap-dev", "libgammu-dev",
            "portaudio19-dev", "libavformat-dev", "libavcodec-dev", "libavdevice-dev", "libavutil-dev",
            "libswscale-dev", "libswresample-dev", "libavfilter-dev", "libyaml-dev", "libxml2-dev", "libxslt1-dev"],
    "install": ["test -x {py} || uv venv -q --python 3.14 {venv}",
                "uv pip install -q --python {py} -r requirements.txt",
                "python3 {harness}/pyinstall.py --python {py} -r requirements_all.txt -r requirements_test.txt",
                "uv pip install -q --python {py} -e . $(for d in packages/hassfest packages/pytest-homeassistant; "
                "do test -d $d && echo -e $d; done) --config-settings editable_mode=compat"],
    "install_files": ["requirements*.txt", "pyproject.toml", "homeassistant/package_constraints.txt",
                      "packages/*/pyproject.toml"],
    "build": ["{py} -m script.translations develop --all > /dev/null"],
    "units": {"include": ["tests/*.py", "tests/**/test_*.py"],
              "exclude": ["tests/e2e/*", "tests/conftest.py", "tests/common.py", "tests/typing.py", "tests/syrupy.py",
                          "tests/patch_*.py", "tests/__init__.py", "tests/ignore_uncaught_exceptions.py",
                          "tests/pylint/*", "tests/mypy_plugins/*", "tests/non_packaged_scripts/*"],
              "sample": 0.12, "seed": "s2"},
    "cmd": ["{py}", "-b", "-X", "dev", "-m", "pytest", "-qq", "--timeout=9", "-p", "no:sugar", "-p",
            "no:cacheprovider", "-p", "s2_report", "{unit}"],
    "unit_timeout": 900, "verify": 0.08,
    "ci": {"workers": 40, "source": ".github/workflows/ci.yaml pytest-full: 10 groups x --numprocesses logical "
                                    "(4 vCPU), --dist=loadfile; dev-branch pushes always run the full suite"},
}
saleor = {
    "name": "saleor", "url": GH + "saleor/saleor", "lang": "pytest",
    "seq": {"kind": "first-parent", "n": 51},
    "services": ["postgres", "valkey"], "apt": ["libpq-dev"],
    "install": ["test -x {py} || uv venv -q --python 3.12 {venv}",
                "UV_PROJECT_ENVIRONMENT={venv} uv sync -q --locked || UV_PROJECT_ENVIRONMENT={venv} uv sync -q"],
    "install_files": ["uv.lock", "pyproject.toml"],
    "build": ["{py} -m pytest -q -p no:cacheprovider -n 0 --create-db saleor/core/tests/test_core.py "
              "-k nothing_matches_this > /dev/null 2>&1 || true"],
    "env": {"DATABASE_URL": "postgres://saleor:saleor@localhost:5432/saleor", "CACHE_URL": "redis://localhost:6379/0",
            "SECRET_KEY": "ci-test"},
    "db_inputs": ["saleor/**/migrations/*.py"],
    "units": {"include": ["saleor/**/test_*.py"], "sample": 0.35, "seed": "s2"},
    "cmd": ["{py}", "-m", "pytest", "-q", "-n", "0", "--reuse-db", "-p", "no:cacheprovider", "-p", "s2_report",
            "{unit}"],
    "unit_timeout": 900, "verify": 0.08, "workers": 3,
    "ci": {"workers": 4, "source": ".github/workflows/tests.yaml unit_tests: one ubuntu-latest job, "
                                   "pytest -n=auto --dist=loadgroup"},
}
vue = {
    "name": "vue-core", "url": GH + "vuejs/core", "lang": "vitest", "node": "lts/*",
    "seq": {"kind": "first-parent", "n": 51},
    "install": ["corepack enable >/dev/null 2>&1; pnpm install --frozen-lockfile --reporter=silent "
                "|| pnpm install --reporter=silent"],
    "install_files": ["pnpm-lock.yaml", "package.json", "packages/*/package.json", "pnpm-workspace.yaml"],
    "units": {"include": ["packages/**/__tests__/**/*.spec.ts", "packages/**/__tests__/**/*.spec.tsx",
                          "packages-private/**/__tests__/**/*.spec.ts"], "sample": 1.0},
    "cmd": ["pnpm", "exec", "vitest", "run", "--project", "unit*", "--reporter=json", "--outputFile={out}", "{unit}"],
    "unit_timeout": 600, "verify": 0.1,
    "ci": {"workers": 4, "source": ".github/workflows/test.yml unit-test: one ubuntu-latest job, "
                                   "pnpm run test-unit (vitest threads)"},
}
docu = {
    "name": "docusaurus", "url": GH + "facebook/docusaurus", "lang": "vitest", "node": "26",
    "seq": {"kind": "first-parent", "n": 51},
    "install": ["corepack enable >/dev/null 2>&1; pnpm install --frozen-lockfile --reporter=silent "
                "|| pnpm install --reporter=silent"],
    "install_files": ["pnpm-lock.yaml", "package.json", "packages/*/package.json", "pnpm-workspace.yaml"],
    "build": ["pnpm build:packages > /dev/null 2>&1"],
    "units": {"include": ["packages/**/*.test.ts", "packages/**/*.test.tsx", "website/**/*.test.ts",
                          "admin/**/*.test.ts", "__tests__/**/*.test.ts"],
              "exclude": ["**/__fixtures__/**", "**/lib/**", "**/node_modules/**"], "sample": 1.0},
    "cmd": ["pnpm", "exec", "vitest", "run", "--reporter=json", "--outputFile={out}", "{unit}"],
    "unit_timeout": 600, "verify": 0.1,
    "ci": {"workers": 4, "source": ".github/workflows/tests.yml: one ubuntu-latest job per Node version, "
                                   "pnpm test (vitest run)"},
}
tf = {
    "name": "terraform", "url": GH + "hashicorp/terraform", "lang": "go",
    "seq": {"kind": "first-parent", "n": 51},
    "install_files": ["go.mod", "go.sum"],
    "units": {"patterns": ["./..."], "sample": 1.0}, "go_args": [], "verify": 0.08,
    "ci": {"workers": 4, "source": ".github/workflows/checks.yml unit-tests: go test ./... on one ubuntu-latest job"},
}
prom = {
    "name": "prometheus", "url": GH + "prometheus/prometheus", "lang": "go",
    "seq": {"kind": "first-parent", "n": 51},
    "install_files": ["go.mod", "go.sum"],
    "units": {"patterns": ["./..."], "sample": 1.0}, "go_args": [], "verify": 0.08,
    "ci": {"workers": 4, "source": ".github/workflows/ci.yml test_go: make test GO_ONLY=1 on one ubuntu-latest job"},
}

# the project's own CI test step (flaky-rerun measurement): shell, run in the checkout after install and build
ha["ci_groups"] = 10
ha["ci_cmd"] = ("{py} -m script.split_tests {groups} tests > /dev/null && "
                "{py} -b -X dev -m pytest -qq --timeout=9 --durations=0 --durations-min=1 --numprocesses logical "
                "--snapshot-details --dist=loadfile -o console_output_style=count -p no:sugar "
                "--exclude-warning-annotations --junitxml={report} -o junit_family=legacy "
                "$(sed -n \"{group},1p\" pytest_buckets.txt)")
ha["ci_report"] = "junit"
saleor["ci_cmd"] = "{py} -m pytest --junitxml={report}"
saleor["ci_report"] = "junit"
vue["ci_cmd"] = "pnpm run test-unit --run --reporter=default --reporter=json --outputFile={report}"
vue["ci_report"] = "vitest"
docu["ci_cmd"] = "pnpm test --reporter=default --reporter=json --outputFile={report}"
docu["ci_report"] = "vitest"
tf["ci_cmd"] = "go test -json ./... > {report}"
tf["ci_report"] = "go"
prom["ci_cmd"] = "go test -json ./... > {report}"
prom["ci_report"] = "go"

for d in (ha, saleor, vue, docu, tf, prom):
    (HERE / f"{d['name']}.json").write_text(json.dumps(d, indent=1) + "\n")
