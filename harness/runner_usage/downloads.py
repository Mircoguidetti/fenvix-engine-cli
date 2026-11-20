"""Package download statistics for the test runners (P-032 step 1).

Run on GitHub Actions (the session container cannot reach api.npmjs.org or pypistats.org).
Writes raw responses to <out>/raw/ and a summary to <out>/downloads.json.
"""
import json, os, sys, time, urllib.parse, urllib.request

NPM = ["vitest", "jest", "mocha", "ava", "jasmine", "jasmine-core", "tap", "uvu", "karma", "bun", "deno",
       "tsx", "ts-node", "@swc/register", "@swc-node/register", "esbuild-register", "ts-jest", "@swc/jest",
       "borp", "c8", "@playwright/test", "cypress", "node-tap", "tape", "qunit", "@japa/runner", "zora", "baretest",
       "@cucumber/cucumber", "lab", "@hapi/lab", "jest-cli", "mocha-junit-reporter", "nyc", "@types/mocha",
       "@types/jest", "@types/jasmine", "@types/node"]
PYPI = ["pytest", "nose2", "nose", "django", "zope-testrunner", "ward", "hypothesis", "pytest-django", "green",
        "unittest-xml-reporting", "testtools", "stestr", "twisted", "pytest-xdist", "tox", "nox", "coverage"]


def get(url):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "runner-usage-measurement"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except Exception as e:  # noqa: BLE001
            err = str(e)
            time.sleep(5 * (attempt + 1))
    return 0, err


def main(out):
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    res = {"measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "npm": {}, "pypi": {}}
    for p in NPM:
        url = "https://api.npmjs.org/downloads/point/last-month/" + urllib.parse.quote(p, safe="@")
        st, body = get(url)
        open(os.path.join(out, "raw", "npm_" + p.replace("/", "__") + ".json"), "w").write(body)
        try:
            j = json.loads(body); res["npm"][p] = {"downloads": j.get("downloads"), "start": j.get("start"), "end": j.get("end"), "url": url}
        except Exception:  # noqa: BLE001
            res["npm"][p] = {"error": body[:200], "status": st, "url": url}
    for p in PYPI:
        url = f"https://pypistats.org/api/packages/{p}/recent"
        st, body = get(url)
        open(os.path.join(out, "raw", "pypi_" + p + ".json"), "w").write(body)
        try:
            j = json.loads(body); res["pypi"][p] = dict(j.get("data", {}), url=url)
        except Exception:  # noqa: BLE001
            res["pypi"][p] = {"error": body[:200], "status": st, "url": url}
        time.sleep(2)
    json.dump(res, open(os.path.join(out, "downloads.json"), "w"), indent=1, sort_keys=True)
    print(json.dumps(res, indent=1, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "harness/runner_usage/results")
