"""Which test runner do popular, active repositories use? (P-032 step 1)

Sample: GitHub repository search, `language:<L> stars:>500 pushed:>=<date> archived:false fork:false`, sorted by
stars, first 1,000 per language (the search API's maximum). Per repository: the git tree (one API call), then the
raw content of the files that name a test runner: every package.json (up to 40, outside node_modules), workflow
files, tox.ini, noxfile.py, pyproject.toml, setup.cfg, Makefile, runtests*.py, and config-file presence.
A repository counts for a runner if the runner is invoked (script, CI step, tox/nox/Makefile command) or
configured (config file / [tool.*] section). Multi-label. Raw per-repository evidence is written to repos.jsonl.
"""
import base64, concurrent.futures as cf, json, os, re, subprocess, sys, time, urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
SINCE = "2026-08-01"
os.makedirs(OUT, exist_ok=True)


def gh(path, **params):
    args = ["gh", "api", "-X", "GET", path] + sum([["-f", f"{k}={v}"] for k, v in params.items()], [])
    for attempt in range(6):
        p = subprocess.run(args, capture_output=True, text=True)
        if p.returncode == 0:
            return json.loads(p.stdout)
        print("gh error", path, params.get("page"), p.stderr[:200], file=sys.stderr, flush=True)
        if "rate limit" in p.stderr.lower() or "403" in p.stderr or "429" in p.stderr:
            time.sleep(30 * (attempt + 1)); continue
        if "404" in p.stderr or "409" in p.stderr:
            return None
        time.sleep(3)
    return None


def raw(full, ref, path):
    url = f"https://raw.githubusercontent.com/{full}/{ref}/{path}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "runner-usage"}), timeout=30) as r:
                return r.read(400_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404: return ""
            time.sleep(2)
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return ""


def repos(lang):
    out = []
    for page in range(1, 11):
        r = gh("search/repositories", q=f"language:{lang} stars:>500 pushed:>={SINCE} archived:false fork:false",
               sort="stars", order="desc", per_page=100, page=page)
        print(lang, "page", page, bool(r), flush=True)
        if not r: break
        out += [{"full": x["full_name"], "ref": x["default_branch"], "stars": x["stargazers_count"], "lang": lang} for x in r["items"]]
        if len(r["items"]) < 100: break
        time.sleep(2.5)
    return out

SKIP_DIR = re.compile(r"(^|/)(node_modules|vendor|third_party|thirdparty|\.yarn|dist|build|fixtures?|__fixtures__|examples?|test-fixtures|testdata)/")

JS_CFG = {
    "vitest": re.compile(r"(^|/)vitest\.(config|workspace)\.[cm]?[jt]s$"),
    "jest": re.compile(r"(^|/)jest\.config\.[cm]?[jt]s(on)?$"),
    "mocha": re.compile(r"(^|/)\.mocharc(\.[a-z]+)?$"),
    "ava": re.compile(r"(^|/)ava\.config\.[cm]?js$"),
    "jasmine": re.compile(r"(^|/)spec/support/jasmine\.(json|js|mjs)$"),
    "tap": re.compile(r"(^|/)\.taprc$"),
    "karma": re.compile(r"(^|/)karma\.conf\.[cm]?[jt]s$"),
    "playwright": re.compile(r"(^|/)playwright\.config\.[cm]?[jt]s$"),
    "cypress": re.compile(r"(^|/)cypress\.config\.[cm]?[jt]s$"),
}
JS_CMD = {
    "vitest": re.compile(r"(^|[\s;&|\"'(/])vitest(\s|$|[\"';&|])"),
    "jest": re.compile(r"(^|[\s;&|\"'(/])jest(\s|$|[\"';&|])"),
    "mocha": re.compile(r"(^|[\s;&|\"'(/])(mocha|_mocha|nyc mocha|c8 mocha)(\s|$|[\"';&|])"),
    "node_test": re.compile(r"node(\s+--[\w-]+(=\S+)?)*\s+--test(\s|$|[\"';&|=])|(^|[\s\"'])borp(\s|$)"),
    "ava": re.compile(r"(^|[\s;&|\"'(/])ava(\s|$|[\"';&|])"),
    "jasmine": re.compile(r"(^|[\s;&|\"'(/])jasmine(\s|$|[\"';&|])"),
    "tap": re.compile(r"(?<!--reporter)(?<!\s-R)(?<!--test-reporter)(^|[\s;&|\"'(/])tap(\s|$|[\"';&|])"),
    "uvu": re.compile(r"(^|[\s;&|\"'(/])uvu(\s|$|[\"';&|])"),
    "bun_test": re.compile(r"(^|[\s;&|\"'(])bun\s+(run\s+)?test(\s|$|[\"';&|])"),
    "deno_test": re.compile(r"(^|[\s;&|\"'(])deno\s+test(\s|$|[\"';&|])"),
    "karma": re.compile(r"(^|[\s;&|\"'(/])karma\s+(start|run)"),
    "playwright": re.compile(r"playwright\s+test"),
    "cypress": re.compile(r"cypress\s+run"),
    "tsx": re.compile(r"(^|[\s;&|\"'(=/])tsx(\s|$|[\"';&|])|--(import|loader|require)[ =]tsx"),
    "ts_node": re.compile(r"ts-node|--(import|loader|require)[ =]ts-node"),
    "swc_register": re.compile(r"@swc(-node)?/register"),
    "esbuild_register": re.compile(r"esbuild-register"),
    "strip_types": re.compile(r"--experimental-strip-types|--experimental-transform-types"),
}
JS_DEP = {"vitest": "vitest", "jest": "jest", "mocha": "mocha", "ava": "ava", "jasmine": "jasmine", "tap": "tap",
          "uvu": "uvu", "karma": "karma", "tsx": "tsx", "ts_node": "ts-node", "playwright": "@playwright/test",
          "cypress": "cypress"}

PY_CMD = {
    "pytest": re.compile(r"(^|[\s;&|\"'(\[,])(py\.test|pytest)(\s|$|[\"';&|\],])|-m\s+pytest"),
    "unittest": re.compile(r"-m\s+unittest|unittest\s+discover|unittest\.main\(|setup\.py\s+test(\s|$)"),
    "django": re.compile(r"manage\.py\s+test|django-admin\s+test|runtests\.py|django\.test\.utils\.get_runner"),
    "nose2": re.compile(r"(^|[\s;&|\"'(])nose2(\s|$|[\"';&|])|-m\s+nose2"),
    "nose": re.compile(r"(^|[\s;&|\"'(])nosetests(\s|$)|-m\s+nose(\s|$)"),
    "doctest": re.compile(r"-m\s+doctest|doctest\.testmod|doctest\.testfile|doctest\.DocTestSuite|DocFileSuite"),
    "pytest_doctest": re.compile(r"--doctest-modules|--doctest-glob"),
    "zope_testrunner": re.compile(r"zope[.-]testrunner"),
    "ward": re.compile(r"(^|[\s;&|\"'(])ward(\s+test)?(\s|$|[\"';&|])|\[tool\.ward\]"),
    "hypothesis": re.compile(r"(^|[\s\"'\[,])hypothesis([\s\"'=<>~!\],;]|$)"),
    "green": re.compile(r"(^|[\s;&|\"'(])green\s"),
    "stestr": re.compile(r"(^|[\s;&|\"'(])stestr(\s|$)"),
    "trial": re.compile(r"(^|[\s;&|\"'(])trial\s|-m\s+twisted\.trial"),
}
PY_CFG = {"pytest": re.compile(r"(^|/)(pytest\.ini|conftest\.py)$"), "nose2": re.compile(r"(^|/)(nose2\.cfg|unittest\.cfg)$")}
PY_SECT = {"pytest": re.compile(r"\[(tool:pytest|tool\.pytest[.\w]*)\]"), "nose2": re.compile(r"\[unittest\]")}


def scripts_text(pkg_text):
    try:
        j = json.loads(pkg_text)
    except Exception:  # noqa: BLE001
        return "", set()
    s = j.get("scripts") or {}
    deps = set((j.get("devDependencies") or {}).keys()) | set((j.get("dependencies") or {}).keys())
    return "\n".join(f"{k}: {v}" for k, v in s.items() if isinstance(v, str)), deps


def analyse(r):
    # file list from a blobless, depth-1 clone (git protocol; the REST tree endpoint is not reachable here)
    import shutil, tempfile
    d = tempfile.mkdtemp(prefix="ru_", dir=os.environ.get("RU_TMP", OUT))
    try:
        p = subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--depth", "1", "--no-checkout",
                            f"https://github.com/{r['full']}", d], capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            return dict(r, error="clone " + p.stderr[-200:])
        paths = subprocess.run(["git", "-C", d, "ls-tree", "-r", "HEAD", "--name-only"], capture_output=True,
                               text=True, timeout=300).stdout.splitlines()
    except Exception as e:  # noqa: BLE001
        return dict(r, error="clone " + str(e)[:200])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    r["truncated"] = False
    r["files"] = len(paths)
    keep = [p for p in paths if not SKIP_DIR.search(p)]
    want = []
    pk = sorted([p for p in keep if p.endswith("package.json")], key=lambda p: (p.count("/"), p))[:40]
    want += pk
    want += [p for p in keep if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))][:30]
    py_want = [p for p in keep if p.count("/") <= 1 and re.search(r"(^|/)(tox\.ini|noxfile\.py|pyproject\.toml|setup\.cfg|Makefile|runtests\w*\.py|setup\.py|justfile|hatch\.toml|deno\.jsonc?|bunfig\.toml)$", p)]
    want += py_want[:20]
    texts = {p: raw(r["full"], r["ref"], p) for p in want}
    hits, ev = {}, {}
    def hit(name, why):
        hits[name] = True; ev.setdefault(name, []).append(why[:160])
    for name, rx in JS_CFG.items():
        m = [p for p in keep if rx.search(p)]
        if m: hit(name, "config " + m[0])
    for name, rx in PY_CFG.items():
        m = [p for p in keep if rx.search(p)]
        if m: hit(name, "config " + m[0])
    if any(p.endswith("manage.py") for p in keep) and any(re.search(r"(^|/)tests?(\.py|/)", p) for p in keep):
        r["has_manage_py"] = True
    for p, txt in texts.items():
        if not txt: continue
        if p.endswith("package.json"):
            s, deps = scripts_text(txt)
            for name, rx in JS_CMD.items():
                for line in s.splitlines():
                    if rx.search(line): hit(name, f"{p} script {line}"); break
            for name, dep in JS_DEP.items():
                if dep in deps: ev.setdefault(name + "_dep", []).append(p)
            continue
        if p.endswith(("deno.json", "deno.jsonc")) and '"test"' in txt: hit("deno_test", p)
        if p.endswith("bunfig.toml") and "[test]" in txt: hit("bun_test", p)
        lines = [ln for ln in txt.splitlines() if not ln.strip().startswith("#")]
        body = "\n".join(lines)
        for name, rx in JS_CMD.items():
            if p.startswith(".github/workflows/"):
                for ln in lines:
                    if rx.search(ln): hit(name, f"{p}: {ln.strip()}"); break
        for name, rx in PY_CMD.items():
            for ln in lines:
                if rx.search(ln): hit(name, f"{p}: {ln.strip()}"); break
        for name, rx in PY_SECT.items():
            if rx.search(body): hit(name, f"{p} section")
    r["hits"] = sorted(hits); r["evidence"] = ev
    return r


def main():
    langs = sys.argv[2].split(",") if len(sys.argv) > 2 else ["Python", "TypeScript", "JavaScript"]
    for lang in langs:
        path = os.path.join(OUT, f"repos-{lang}.jsonl")
        done = set()
        if os.path.exists(path):
            done = {json.loads(l)["full"] for l in open(path)}
        lst = repos(lang)
        json.dump({"query": f"language:{lang} stars:>500 pushed:>={SINCE} archived:false fork:false sort:stars",
                   "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(lst)},
                  open(os.path.join(OUT, f"query-{lang}.json"), "w"))
        todo = [r for r in lst if r["full"] not in done]
        with open(path, "a") as f, cf.ThreadPoolExecutor(int(os.environ.get("RU_THREADS", "12"))) as ex:
            for i, res in enumerate(ex.map(analyse, todo)):
                f.write(json.dumps(res) + "\n"); f.flush()
                if i % 50 == 0: print(lang, i, len(todo), flush=True)


if __name__ == "__main__":
    main()
