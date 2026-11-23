#!/bin/bash
# Spec step 3 helper: list the CI/config files read and grep them for test-skipping mechanisms.
# Usage: statusquo_scan.sh <clone-dir> <ref>   (reads files from <ref> with git show, no checkout)
d=$1; ref=$2
files=$(git -C "$d" ls-tree -r --name-only "$ref" | grep -E '^\.github/workflows/.*\.ya?ml$|(^|/)nx\.json$|(^|/)turbo\.json$|(^|/)package\.json$|^\.circleci/|^\.gitlab-ci\.yml$|^azure-pipelines|^\.buildkite/|^Jenkinsfile|^bitbucket-pipelines|(^|/)(vitest|jest)\.config\.|^lefthook|^\.husky/' | grep -v node_modules)
echo "FILES READ:"; echo "$files" | sed 's/^/  /'
pat='affected|--changed|changedSince|findRelatedTests|onlyChanged|\brelated\b|remoteCache|remote-cache|nx-cloud|nxCloud|TURBO_TOKEN|TURBO_TEAM|turbo run|datadog|dd-trace|DD_CIVISIBILITY|test.?impact|launchable|develocity|predictive|circleci tests|tests run|test-selection|--shard|vitest related|jest.*-o\b'
echo "MATCHES:"
for f in $files; do git -C "$d" show "$ref:$f" | grep -n -i -E "$pat" | sed "s|^|  $f:|"; done
echo "TEST COMMANDS IN WORKFLOWS:"
for f in $(echo "$files" | grep -E '^\.github/workflows|^\.circleci|^\.gitlab'); do git -C "$d" show "$ref:$f" | grep -n -E '\b(npm|pnpm|yarn|npx|bun) (run )?(test|vitest|jest)|vitest|jest|test:' | sed "s|^|  $f:|"; done
