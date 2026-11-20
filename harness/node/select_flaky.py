#!/usr/bin/env python3
"""Build harness/node/flaky_candidates.json: Node/TypeScript projects with documented flaky tests.

Two sources, in this order:

1. The dataset of Hashemi, Tahir, Rasheed, "An Empirical Study of Flaky Tests in JavaScript"
   (ICSME 2022; Zenodo 10.5281/zenodo.6673741, fetched into harness/node/dataset/raw by the
   node-dataset workflow). Each entry is a commit that fixes (or disables) a flaky test; the
   project is pinned at the PARENT of that commit, where the flaky test was still present, and
   the test files changed by the fix are the documented flaky files. Only 18 projects, most of
   them not using Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites):
   the selection stage keeps those whose suite runs with Jest or Vitest.
2. GitHub issues that document a flaky Jest/Vitest test ("flaky" in the title) in popular
   projects. The project is pinned at the last commit of the default branch before the issue
   was opened (resolved by the prepare stage with `git rev-list -1 --before`); the issue title
   names the flaky test or file when it can.

Requires `gh` (GitHub search API) for source 2.
"""
import collections
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset" / "raw" / "replicationPackage" / "Data"

ISSUE_REPOS = [
    "vitejs/vite", "vuejs/core", "jestjs/jest", "babel/babel", "prettier/prettier", "webpack/webpack",
    "TanStack/query", "reduxjs/redux-toolkit", "pmndrs/zustand", "pmndrs/jotai", "mswjs/msw",
    "apollographql/apollo-client", "remix-run/react-router", "vercel/swr", "sveltejs/svelte", "vuejs/pinia",
    "vuejs/router", "colinhacks/zod", "date-fns/date-fns", "iamkun/dayjs", "moment/luxon", "immerjs/immer",
    "mobxjs/mobx", "jaredpalmer/formik", "react-hook-form/react-hook-form", "jquense/yup", "axios/axios",
    "koajs/koa", "mantinedev/mantine", "chakra-ui/chakra-ui", "tailwindlabs/tailwindcss",
    "styled-components/styled-components", "emotion-js/emotion", "floating-ui/floating-ui", "vueuse/vueuse",
    "element-plus/element-plus", "ant-design/ant-design", "recharts/recharts", "facebook/lexical",
    "excalidraw/excalidraw", "tldraw/tldraw", "strapi/strapi", "directus/directus", "redwoodjs/redwood",
    "prisma/prisma", "drizzle-team/drizzle-orm", "trpc/trpc", "honojs/hono", "tj/commander.js", "lerna/lerna",
    "changesets/changesets", "pnpm/pnpm", "yarnpkg/berry", "typescript-eslint/typescript-eslint",
    "stylelint/stylelint", "facebook/docusaurus", "getsentry/sentry-javascript", "PostHog/posthog-js",
    "aws-amplify/amplify-js", "supabase/supabase-js", "webdriverio/webdriverio",
    "testing-library/react-testing-library", "testing-library/dom-testing-library",
    "testing-library/user-event", "capricorn86/happy-dom", "unjs/h3", "unjs/ofetch", "nuxt/nuxt",
    "vitest-dev/vitest", "storybookjs/storybook", "facebook/react", "mui/material-ui", "vercel/next.js",
    "nestjs/nest", "typeorm/typeorm", "sequelize/sequelize", "knex/knex", "graphql/graphql-js",
    "socketio/socket.io", "statelyai/xstate", "reactjs/react-redux", "reduxjs/redux", "ReactiveX/rxjs",
    "lodash/lodash", "marmelab/react-admin", "react-navigation/react-navigation", "callstack/react-native-paper",
    "TanStack/table", "TanStack/router", "TanStack/form", "preactjs/signals", "solidjs/solid", "withastro/astro",
]

TEST_HINT = re.compile(r"(flaky|flakey|intermittent)", re.I)


def gh_search(q: str) -> list:
    for attempt in range(4):
        r = subprocess.run(["gh", "api", "-X", "GET", "search/issues", "-f", f"q={q}", "-f", "sort=created",
                            "-f", "order=desc", "-f", "per_page=10"], capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout).get("items", [])
        if "rate limit" in (r.stdout + r.stderr).lower():
            time.sleep(30 * (attempt + 1))
            continue
        print(f"search failed for {q}: {r.stderr.strip()[:200]}", file=sys.stderr)
        return []
    return []


def from_dataset() -> list:
    rows = list(csv.DictReader(open(DATASET / "JavaScript-flakyTests-classification.csv")))
    by_repo = collections.defaultdict(list)
    for r in rows:
        if r.get("change code", "").lower().startswith(("test", "cut/test")):
            by_repo[r["Repository name"]].append(r)
    out = []
    for repo, items in by_repo.items():
        commits = [{"fix_commit": i["Commit URL"].rsplit("/", 1)[-1], "cause": i["Cause of flakiness"],
                    "response": i["Response"], "commit_url": i["Commit URL"]} for i in items]
        out.append({"name": repo.split("/")[1].lower() + "-flaky", "repo": repo, "url": f"https://github.com/{repo}",
                    "source": "hashemi-icsme2022", "pin": "parent-of-fix", "commits": commits[:6]})
    return out


def from_issues(seen: set) -> list:
    out = []
    for repo in ISSUE_REPOS:
        if repo.lower() in seen:
            continue
        items = gh_search(f"repo:{repo} is:issue flaky in:title")
        time.sleep(2.5)
        issues = [i for i in items if TEST_HINT.search(i["title"]) and "pull_request" not in i
                  and i["created_at"] >= "2022-01-01"]
        if not issues:
            continue
        out.append({"name": repo.split("/")[1].lower() + "-flaky", "repo": repo, "url": f"https://github.com/{repo}",
                    "source": "github-issue", "pin": "before-issue",
                    "issues": [{"url": i["html_url"], "title": i["title"], "created_at": i["created_at"],
                                "state": i["state"]} for i in issues[:3]]})
        print(f"{repo}: {len(issues)} flaky issues, latest {issues[0]['created_at'][:10]}: {issues[0]['title'][:70]}")
    return out


def main() -> None:
    ds = from_dataset()
    issues = from_issues({c["repo"].lower() for c in ds})
    data = {"_comment": __doc__, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "candidates": ds + issues}
    (HERE / "flaky_candidates.json").write_text(json.dumps(data, indent=1))
    print(f"{len(ds)} dataset projects, {len(issues)} issue projects")


if __name__ == "__main__":
    main()
