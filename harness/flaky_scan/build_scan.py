#!/usr/bin/env python3
"""Merge candidates.jsonl + meta.jsonl + raw_scan.jsonl + skip_dates.jsonl into scan.jsonl (one line per repo).

The raw regexes are deliberately wide; this step removes what is not a project's own test infrastructure, with
every rule written here so a reader can disagree with it:
  * paths that are documentation, examples, blog posts, templates, vendored copies or fixtures (PATH_EXCLUDE);
  * line rules per mechanism (a call that is mentioned in a string/expect() is not a call);
  * a test runner's own repository testing its own retry feature (SELF_TOOL);
  * repositories found vendoring another project's test-suite (VENDORED, decided by reading the paths).
Excluded signals are kept per repo as a count, so nothing disappears silently.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

PATH_EXCLUDE = re.compile(
    r"(^|/)(examples?|docs?|documentation|blog|posts|templates?|skeletons?|samples?|website|__typetests__|"
    r"lambda-layer|repos|skills|assets|tutorials?|courses?|vendored|externals?)/|fixture|site-packages|"
    r"\.template\.", re.I)
LINE_RULES = {
    "jest_retryTimes": re.compile(r"^\s*(await\s+)?jest\.retryTimes\(|[;{]\s*jest\.retryTimes\(|=>\s*jest\.retryTimes\("),
    "pytest_mark_flaky": re.compile(r"^\s*@pytest\.mark\.flaky|pytestmark\s*=.*flaky"),
    "pytest_retry": re.compile(r"--retries[= ]+[1-9]|@pytest\.mark\.retry"),
    "quarantine_ci": re.compile(r"test|spec", re.I),
}
QUARANTINE_CI_FILE = re.compile(r"(\.ya?ml|(^|/)package\.json|(^|/)makefile)$", re.I)
QUARANTINE_LIST_FILE = re.compile(r"(^|/)(flaky|quarantine)[\w-]*\.(txt|json|ya?ml|toml|csv)$", re.I)
SELF_TOOL = {
    "jestjs/jest": {"jest_retryTimes"}, "mochajs/mocha": {"mocha_retries"}, "vitest-dev/vitest": {"vitest_retry"},
    "cypress-io/cypress": {"cypress_retries"}, "pytest-dev/pytest-rerunfailures": {"pytest_reruns", "pytest_mark_flaky"},
    "box/flaky": {"flaky_plugin"},
}
# Decided by reading the matched paths (see REPORT.md "Exclusions"): the matches are inside a copied third-party
# project, not the repository's own tests.
VENDORED = {
    "Ingkarat/PoTo": "bokeh test-suite copied under orig_pro_dynamic/",
    "Web-Dev-Collaborative/npm-package-testing": "copies of npm packages under REPOS/",
    "perottofederico/Tesi": "diffusers copied under GWIT/src/diffusers/",
    "cal-poly-dxhub/genomics-lab-result-mapper": "numpy copied under lambda-layer/python/numpy/",
    "Classy-Closets/Snap-Update-Testing": "pandas and psutil copied under python_lib/",
    "artyom-gaibovich/rentall": "node_modules copied under old_mod/",
    "WillyBilly06/ESP32-A2DP-SINK-WITH-CODECS-UPDATED": "esp-idf copied under esp-idf/",
    "WillyBilly06/ESP32-S31-A2DP-Codecs": "esp-idf copied under esp-idf-v6.1-codecs/",
    "WillyBilly06/esp32-hifi-a2dp-sink": "esp-idf copied under esp-idf/",
    "Walton711/ESP32S3forAISoundBox": "esp-idf copied under esp-idf-v5.1.3/ (and its .gitlab/ci)",
    "FAOEOYI/WT-EXPAND-HW": "esp-idf .gitlab/ci copied at the root",
    "paulaglez/ESP": "copy of esp-idf (not a GitHub fork)",
    "RogoSolutions/rogo-esp32-sdk": "copy of esp-idf (not a GitHub fork)",
    "kj9955/01": "copy of esp-idf (not a GitHub fork)",
    "mayi-hub/ESP-IDF": "copy of esp-idf (not a GitHub fork)",
    "arturo393/esp-idf": "copy of esp-idf (not a GitHub fork)",
    "atulhiralkar68/Cypres": "copy of the cypress repository (not a GitHub fork)",
    "imranmsoft/cypress-qaops": "copy of the cypress repository (not a GitHub fork)",
    "nfsprogramming/NFS-Learning-Hub": "responsible-ai-toolbox copied under responsible-ai-toolbox/",
    "dongkale/nestjs_src": "nest copied under nest/",
    "Jeetaksh25/Penpot-Desktop": "penpot copied under penpot-source/",
    "Onilok/Julien_Projects": "penpot copied under penpot-v3/",
    "albertotrunk/ue-stable-diffusion": "caffe2/matplotlib/pandas/scipy copied under Content/Python/",
    "fabecode/GraphML-FHE": "concrete-ml copied under concrete-ml/",
    "GSM2017PMK-OSV/main-trunk": "several third-party projects copied under their own folders",
    "cqf7419/Cosmos_SingelGPU_Infer": "cosmos-transfer2 sources copied under cosmos_transfer2/_src/",
    "nicolasdickenmann/DreamWorld": "cosmos-predict2.5 copied under cosmos-predict2.5/",
    "karan0802/CMPT479-project": "a dataset of third-party code under dataset/",
}
# A product whose own integration tests exercise its flaky-test FEATURE (not its own flakiness).
REPO_PATH_EXCLUDE = {"DataDog/dd-trace-js": re.compile(r"integration-tests/ci-visibility/|ci/vitest-|packages/datadog-plugin-")}
STRICT_WORDS = {"flaky", "flakiness", "flake", "flakes", "intermittent", "intermittently", "unstable",
                "sometimes fails", "sometimes fail"}


def keep_signal(repo: str, s: dict) -> bool:
    if PATH_EXCLUDE.search(s["file"]):
        return False
    if repo in REPO_PATH_EXCLUDE and REPO_PATH_EXCLUDE[repo].search(s["file"]):
        return False
    rule = LINE_RULES.get(s["mechanism"])
    if rule and not rule.search(s["text"]):
        return False
    if s["mechanism"] == "pytest_retry" and s["text"].lstrip().startswith("@retry"):
        return False
    if s["mechanism"] == "quarantine_ci" and not QUARANTINE_CI_FILE.search(s["file"]):
        return False
    if s["mechanism"] == "quarantine_list" and not QUARANTINE_LIST_FILE.search(s["file"]):
        return False
    if s["mechanism"] in SELF_TOOL.get(repo, ()):
        return False
    return True


UNCOND = re.compile(r"\b(?:it|test|describe|context|suite|bench)\.(?:skip|fixme)\s*\(\s*(?:['\"`]|\)|async|\(|function|$)|"
                    r"\bx(?:it|test|describe)\s*\(|@pytest\.mark\.(?:skip|xfail)\b(?!if)|\bpytest\.(?:skip|xfail)\s*\(|"
                    r"@unittest\.(?:skip|expectedFailure)\b(?!If|Unless)|\bself\.skipTest\s*\(|@skip\s*\(|"
                    r"\b(?:test|it)\.(?:skip|fixme)\s*\(\s*true\b")
MODIFIER = re.compile(r"^\s*(?:test|it)\.(?:skip|fixme)\s*\((?!\s*['\"`])")
AGE_ORDER = ["over 12", "6-12", "1-6", "under 1"]


def group_skips(skips: list[dict]) -> list[dict]:
    """One entry per skipped TEST: a Python decorator stack, or consecutive in-body modifiers, is one test."""
    out: list[dict] = []
    for s in sorted(skips, key=lambda x: (x["file"], x["line"])):
        prev = out[-1] if out else None
        if prev and prev["file"] == s["file"]:
            gap = s["line"] - prev["lines"][-1]
            py = prev["text"].startswith("@") and s["text"].startswith("@") and gap <= 6
            js = MODIFIER.search(prev["text"]) and MODIFIER.search(s["text"]) and gap <= 2
            if py or js:
                prev["lines"].append(s["line"]); prev["members"].append(s); continue
        out.append({"file": s["file"], "lines": [s["line"]], "text": s["text"], "members": [s]})
    groups = []
    for g in out:
        m = g["members"]
        words = sorted({w for x in m for w in x["words"]})
        dated = [x for x in m if x.get("age_months") is not None]
        oldest = max(dated, key=lambda x: x["age_months"]) if dated else None
        refs = [r for x in m for r in x["issue_ref"]]
        st = {r.get("state") for r in refs}
        issue_state = ("none" if not refs else "open" if "open" in st else
                       "closed" if st <= {"closed", "pr_closed", "pr_open"} and st & {"closed", "pr_closed"} else "UNKNOWN")
        groups.append({"file": g["file"], "line": g["lines"][0], "lines": g["lines"], "text": g["text"],
                       "words": words, "strict_stated": strict_stated(words),
                       "skip_kind": "unconditional" if any(UNCOND.search(x["text"]) for x in m) else "conditional",
                       "added_date": oldest and oldest["added_date"], "added_commit": oldest and oldest["added_commit"],
                       "age_months": oldest and oldest["age_months"],
                       # True: the line is older than the fetched history, added_date is the history's edge
                       "added_date_is_lower_bound": bool(oldest and oldest["boundary"]),
                       "age_bucket": oldest["age_bucket"] if oldest else "UNKNOWN",
                       "issue_ref": refs, "issue_state": issue_state})
    return groups


def strict_stated(words: list[str]) -> bool:
    return any(w in STRICT_WORDS or w.startswith("quarantin") for w in words)


def main() -> None:
    cands = {j["repo"]: j for j in map(json.loads, (HERE / "candidates.jsonl").open())}
    meta = {j["repo"]: j for j in map(json.loads, (HERE / "meta.jsonl").open())}
    raw = {j["repo"]: j for j in map(json.loads, (HERE / "raw_scan.jsonl").open())}
    dates = {}
    p = HERE / "skip_dates.jsonl"
    if p.exists():
        dates = {(j["repo"], j["file"], j["line"]): j for j in map(json.loads, p.open())}
    with open(HERE / "scan.jsonl", "w") as f:
        for repo, c in cands.items():
            r = raw.get(repo)
            m = meta[repo]
            rec = {"repo": repo, "commit": r and r["commit"], "stars": m["stars"], "language": m["language"],
                   "archived": m["archived"], "frame": c["frame"], "lang_bucket": c["lang_bucket"],
                   "query": c["query"], "also_found_by": c["also_found_by"],
                   "scan_status": (r["scan_status"] if r else "not_scanned"),
                   "files_read": r and r["files_read"], "truncated": r and r["truncated"],
                   "vendored_exclusion": VENDORED.get(repo)}
            sigs, skips, excluded = [], [], 0
            if r and not rec["vendored_exclusion"]:
                for s in r["signals"]:
                    if keep_signal(repo, s):
                        sigs.append(s)
                    else:
                        excluded += 1
                for s in r["skipped_flaky_tests"]:
                    if PATH_EXCLUDE.search(s["file"]) or (
                            repo in REPO_PATH_EXCLUDE and REPO_PATH_EXCLUDE[repo].search(s["file"])):
                        excluded += 1
                        continue
                    d = dates.get((repo, s["file"], s["line"]), {})
                    skips.append({**s, "strict_stated": strict_stated(s["words"]),
                                  "added_date": d.get("added_date"), "added_commit": d.get("added_commit"),
                                  "age_months": d.get("age_months"), "boundary": d.get("boundary"), "age_bucket": d.get("age_bucket", "UNKNOWN"),
                                  "issue_ref": d.get("refs", s["refs"])})
            elif r:
                excluded = len(r["signals"]) + len(r["skipped_flaky_tests"])
            skips = group_skips(skips)
            for s in sigs:
                s["strict_stated"] = s["stated"] and strict_stated(s["words"])
                s["scaffold_default"] = s["value"].startswith("scaffold-default")
            mechs = sorted({s["mechanism"] for s in sigs} | ({"skip_flaky"} if skips else set()))
            stated = any(s["stated"] for s in sigs) or bool(skips)
            strict = any(s["strict_stated"] for s in sigs) or any(s["strict_stated"] for s in skips)
            rec.update(signals=sigs, excluded_signals=excluded, skipped_flaky_tests=skips, mechanisms=mechs,
                       lives_with_flaky=bool(sigs or skips),
                       classification=("stated" if stated else "implied" if sigs else "none"),
                       classification_strict=("stated" if strict else "implied" if (sigs or skips) else "none"),
                       only_scaffold_default=bool(sigs) and not skips and all(s["scaffold_default"] for s in sigs))
            f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    main()
