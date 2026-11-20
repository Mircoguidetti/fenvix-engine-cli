"""Aggregate the repository sample (repos-<Lang>.jsonl) into usage shares per runner."""
import json, os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
JS = ["jest", "vitest", "mocha", "node_test", "ava", "jasmine", "tap", "uvu", "bun_test", "deno_test", "karma",
      "playwright", "cypress", "tsx", "ts_node", "swc_register", "esbuild_register", "strip_types"]
PY = ["pytest", "unittest", "django", "runtests_script", "doctest", "pytest_doctest", "nose2", "nose", "zope_testrunner", "ward",
      "hypothesis", "green", "stestr", "trial"]


import re
GREEN = re.compile(r"-m\s+green\b|(^|run:|&&|;|commands\s*=)\s*(\w+\s+run\s+)?green(\s+-{1,2}[\w-]+|\s+[\w./]+)+\s*$")
DJANGO = re.compile(r"manage\.py\s+test|django-admin\s+test")


def refine(r):
    """Post-hoc filters of the line regexes (measured false positives): `green` must be a command; Django counts
    only `manage.py test` / `django-admin test`; a bare `runtests.py` is its own category (Django's own, DRF and
    Wagtail use one around Django's runner, mypy and luigi do not)."""
    if "error" in r: return r
    hits = set(r["hits"]); ev = r["evidence"]
    if "green" in hits and not any(GREEN.search(e.split(": ", 1)[-1].strip()) for e in ev.get("green", [])):
        hits.discard("green")
    if "django" in hits:
        dj = [e for e in ev["django"] if DJANGO.search(e)]
        if any("runtests" in e for e in ev["django"]): hits.add("runtests_script"); ev["runtests_script"] = [e for e in ev["django"] if "runtests" in e]
        if not dj: hits.discard("django")
    if "tap" in hits:  # `brew tap ...` in workflow files: tap counts only from package.json scripts and .taprc
        keep = [e for e in ev["tap"] if " script " in e or e.startswith("config ")]
        if keep: ev["tap"] = keep
        else: hits.discard("tap")
    r["hits"] = sorted(hits)
    return r


def load(lang):
    p = os.path.join(OUT, f"repos-{lang}.jsonl")
    if not os.path.exists(p): return []
    rows = {}
    for line in open(p):
        r = refine(json.loads(line)); rows[r["full"]] = r
    return list(rows.values())


def table(rows, names, title):
    ok = [r for r in rows if "error" not in r]
    any_runner = [r for r in ok if set(r["hits"]) & set(names) - {"hypothesis", "tsx", "ts_node", "swc_register", "esbuild_register", "strip_types"}]
    lines = [f"### {title}: {len(ok)} repositories analysed ({len(rows) - len(ok)} not cloned), {len(any_runner)} with at least one runner found", "",
             "| runner | repositories | share of analysed | share of those with a runner | only runner found |", "|---|---:|---:|---:|---:|"]
    stats = []
    for n in names:
        c = [r for r in ok if n in r["hits"]]
        only = [r for r in c if not (set(r["hits"]) & (set(names) - {n, "hypothesis", "tsx", "ts_node", "swc_register", "esbuild_register", "strip_types", "pytest_doctest", "playwright", "cypress"}))]
        stats.append((n, len(c), len(only)))
    for n, c, only in sorted(stats, key=lambda x: -x[1]):
        lines.append(f"| {n} | {c} | {100*c/max(1,len(ok)):.1f}% | {100*c/max(1,len(any_runner)):.1f}% | {only} |")
    return "\n".join(lines), {n: c for n, c, _ in stats}, len(ok)


def examples(rows, name, k=12):
    c = sorted([r for r in rows if "error" not in r and name in r["hits"]], key=lambda r: -r["stars"])
    return [(r["full"], r["stars"], (r["evidence"].get(name) or [""])[0]) for r in c[:k]]


if __name__ == "__main__":
    py = load("Python"); js = load("JavaScript") + load("TypeScript")
    res = {}
    for rows, names, title in [(py, PY, "Python"), (load("JavaScript"), JS, "JavaScript"), (load("TypeScript"), JS, "TypeScript"), (js, JS, "JavaScript + TypeScript")]:
        md, counts, n = table(rows, names, title)
        res[title] = {"analysed": n, "counts": counts}
        print(md, "\n")
    for lang in ["TypeScript", "JavaScript"]:
        p = os.path.join(OUT, f"testscript-{lang}.jsonl")
        if not os.path.exists(p): continue
        import collections
        rows = [json.loads(l) for l in open(p)]
        with_test = [r for r in rows if r.get("test")]
        c = collections.Counter(h for r in with_test for h in r.get("hits", []))
        deleg = sum(1 for r in with_test if r.get("delegated"))
        res[f"root-test-{lang}"] = {"repos": len(rows), "with_test_script": len(with_test), "delegated": deleg, "counts": dict(c)}
        print(f"### Root `test` script, {lang}: {len(rows)} repositories, {len(with_test)} with a root test script, {deleg} delegate to a monorepo tool\n")
        print("| runner or loader in the root test script | repositories | share of those with a test script |\n|---|---:|---:|")
        for k, v in c.most_common():
            print(f"| {k} | {v} | {100*v/max(1,len(with_test)):.1f}% |")
        print()
    ex = {n: examples(py, n) for n in PY}
    ex.update({n: examples(js, n) for n in JS})
    json.dump({"summary": res, "examples": ex}, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
