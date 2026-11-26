"""Print REPORT.md from committed files only, with the acceptance checks (AC 3, 4, 7).

    python3 harness/db_copies_read/report.py [--partial] [--results DIR] [--out REPORT.md]

Fails (exit 1) when a counted quote is not in the stored raw text, an "off" evidence line is not in the stored
file, a plugin-installed row lacks pytest-django or pytest-xdist in a stored dependency file, or the per-stack
summary does not sum to 20.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import lines as LN  # noqa: E402
import rules as R  # noqa: E402

LEVELS = ["built-in", "plugin-installed", "plugin-partial", "plugin-not-installed", "none", "n/a"]


class CheckFailed(Exception):
    pass


def stored_file_text(results: Path, repo: str, path: str) -> str | None:
    p = results / "raw" / J.slug(repo) / "files.json.gz"
    if not p.exists():
        return None
    return J.file_texts(J.jload(p)).get(path)


def item_texts(results: Path, repo: str) -> dict[str, str]:
    """The stored text of every item of a repository, by html_url: title+body, message or comment body, plus the
    patches of its fetched commit diff or pull files."""
    base = results / "raw" / J.slug(repo)
    out: dict[str, str] = {}
    issues = J.jload(base / "issues.json.gz")
    for it in J.issue_items(issues):
        out[it["html_url"]] = f"{it['title']}\n{it['body']}"
    for c in J.commit_items(J.jload(base / "commits.json.gz")):
        out[c["html_url"]] = c["message"]
    for e in J.jload(base / "comments.json.gz").get("responses") or []:
        for cm in e.get("data") or []:
            if isinstance(cm, dict):
                out[cm.get("html_url")] = cm.get("body") or ""
    by_num = {it["number"]: it["html_url"] for it in J.issue_items(issues)}
    for e in J.jload(base / "pullfiles.json.gz").get("responses") or []:
        n = int(e["path"].split("/pulls/")[1].split("/")[0])
        url = by_num.get(n)
        if url:
            out[url] = out.get(url, "") + "\n" + "\n".join(f.get("patch") or "" for f in e.get("data") or [])
    for e in J.jload(base / "diffs.json.gz").get("responses") or []:
        d = e.get("data") or {}
        if isinstance(d, dict) and d.get("html_url"):
            out[d["html_url"]] = out.get(d["html_url"], "") + "\n" + "\n".join(
                f.get("patch") or "" for f in d.get("files") or [])
    return out


def check_quotes(results: Path, passed: list[dict]) -> None:
    cache: dict[str, dict[str, str]] = {}
    for i in passed:
        if i["repo"] not in cache:
            cache[i["repo"]] = item_texts(results, i["repo"])
        text = cache[i["repo"]].get(i["url"])
        if not i["quote"] or text is None or i["quote"] not in text:
            raise CheckFailed(f"quote not in the item's stored text: {i['url']}: {i['quote'][:80]!r}")


def check_off(results: Path, table: list[dict]) -> None:
    for t in table:
        if t.get("free_off") != "yes":
            continue
        ev = t.get("off_evidence") or {}
        text = stored_file_text(results, t["repo"], ev.get("file") or "")
        lines = (text or "").splitlines()
        n = ev.get("line") or 0
        if not text or n < 1 or n > len(lines) or lines[n - 1] != ev.get("text"):
            raise CheckFailed(f"off evidence not in stored file: {t['repo']} {ev}")
        if t["level"] == "plugin-installed":
            deps = t.get("plugin_deps") or {}
            for name in ("pytest-django", "pytest-xdist"):
                paths = deps.get(name) or []
                if not any(R.has_dep([stored_file_text(results, t["repo"], p) or ""], name) for p in paths):
                    raise CheckFailed(f"plugin-installed without {name} in a stored dependency file: {t['repo']}")


def per_stack(table: list[dict], pain: set[str]) -> tuple[list[str], str]:
    groups: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for t in table:
        groups[(t["runner"], t.get("level") or "n/a")].append(t)
    runners = sorted({k[0] for k in groups})
    rows = ["| runner | level | repositories | pain yes | free_off yes | building-block | median of median_s (min) |",
            "|---|---|---|---|---|---|---|"]
    total = 0
    for rn in runners:
        for lv in LEVELS:
            g = groups.get((rn, lv))
            if not g:
                continue
            total += len(g)
            rows.append(f"| {rn} | {lv} | {len(g)} | {sum(1 for t in g if t['repo'] in pain)} | "
                        f"{sum(1 for t in g if t.get('free_off') == 'yes')} | "
                        f"{sum(1 for t in g if t.get('building_block'))} | "
                        f"{statistics.median(t['median_s'] for t in g) / 60:.1f} |")
    rows.append(f"| total | | {total} | {len(pain)} | {sum(1 for t in table if t.get('free_off') == 'yes')} | "
                f"{sum(1 for t in table if t.get('building_block'))} | "
                f"{statistics.median(t['median_s'] for t in table) / 60:.1f} |")
    if total != LN.DENOM:
        raise CheckFailed(f"per-stack summary sums to {total}, not {LN.DENOM}")
    hits = collections.Counter((t["runner"], t.get("level") or "n/a") for t in table
                               if t["repo"] in pain or t.get("free_off") == "yes")
    if hits:
        top = max(hits.values())
        names = sorted(f"{rn}/{lv}" for (rn, lv), n in hits.items() if n == top)
        line = f"Most common stack among `pain` or `free_off` rows: {', '.join(names)} ({top} repositories" + \
               (" each)" if len(names) > 1 else ")")
    else:
        line = "Most common stack among `pain` or `free_off` rows: none (0 repositories)"
    return rows, line


def desk_summary(path: Path) -> list[str]:
    if not path.exists():
        return ["desk_survey.md not written yet."]
    out = []
    for ln in path.read_text().splitlines():
        if ln.startswith("| ") and not ln.startswith("| tool") and not ln.startswith("|---"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            out.append(f"- {cells[0]}: {cells[1]}, {cells[-1]}")
    return out


def md(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def build(results: Path, partial: bool) -> str:
    table = LN.jl(results / "table.jsonl")
    items = LN.jl(results / "items.jsonl")
    hand = LN.jl(results / "handcheck.jsonl")
    recheck = LN.jl(results / "recheck.jsonl")
    cp = J.load_checkpoint(results) or J.new_checkpoint()
    res = LN.compute(table, items, hand, recheck)
    passed = LN.passed_items(items, hand, recheck)
    check_quotes(results, passed)
    check_off(results, table)
    pain = set(res["pain"])
    stack_rows, stack_line = per_stack(table, pain)
    head = LN.render(res)
    if partial and res["outcome"] != "INCOMPLETE":
        head = head.replace(res["outcome"], "INCOMPLETE", 1)
    out = [head.rstrip("\n"), ""]
    if res.get("unchecked"):
        out += [f"Counted items without a hand-check decision in: {', '.join(res['unchecked'])}.", ""]
    if partial or res["outcome"] == "INCOMPLETE":
        left = [t["repo"] for t in table if t["status"] not in ("done", "unavailable")]
        out += [f"Partial report: {len(left)} repositories not read yet: {', '.join(left) or 'none'}.", ""]
    ch = HERE / "CHANGES.md"
    out += ["## 2. Changes after PREREG", "", ch.read_text().strip() if ch.exists() else "None.", ""]
    out += ["## 3. Per-repository table", "",
            "| repo | runner | median min | level | state | free_off | counted pain passed (n, first) | P2 apart | stated reason | stars / contributors / owner | truncated |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    order = sorted(table, key=lambda t: (t["status"] != "unavailable", t["repo"].lower()))
    hmap = {(h["repo"], h["url"]): h for h in hand}
    for t in order:
        pi = [i for i in passed if i["repo"] == t["repo"]]
        p2 = [i for i in items if i["repo"] == t["repo"] and i["p2"] and not i["excluded_reason"]
              and hmap.get((i["repo"], i["url"]), {}).get("decision") == "pass"]
        c = t.get("context") or {}
        first = pi[0]["url"] if pi else ""
        out.append(f"| {t['html_url']} | {t['runner']} | {t['median_min']} | {t.get('level')} | {t.get('state')} | "
                   f"{t.get('free_off')} | {len(pi)} {first} | {len(p2)} | {md(t.get('stated_reason'))} | "
                   f"{c.get('stars')} / {c.get('contributors')} / {c.get('owner_type')} | "
                   f"{', '.join(sorted(t.get('truncated') or {})) or '-'} |"
                   + (f" **{t['status']}**" if t["status"] != "done" else ""))
    out += ["", "## 4. Pain items", "", "### Counted, passed", ""]
    for i in sorted(passed, key=lambda i: (i["repo"].lower(), i["date"] or "")):
        out.append(f"- {i['url']} ({(i['date'] or '')[:10]}, {', '.join(i['counted_rules'])}"
                   f"{', P1-db' if i['p1_db'] else ''}): \"{md(i['quote'])}\"")
    out += ["", "### P2 parallel attempts (reported apart, not counted)", ""]
    for i in items:
        h = hmap.get((i["repo"], i["url"]))
        if i["p2"] and not i["counted"] and h and h.get("decision") == "pass":
            out.append(f"- {i['url']} ({(i['date'] or '')[:10]}, {', '.join(i['rules'])}): \"{md(i['quote'])}\"")
    out += ["", "### Failed hand check", ""]
    for h in hand:
        if h.get("decision") == "fail":
            out.append(f"- {h['url']} ({h['rule']}): {md(h['reason'])}")
    rm = results / "rulemiss.json"
    out += ["", "### Rule-miss read (never counted)", ""]
    if rm.exists():
        d = json.loads(rm.read_text())
        out.append(f"Seeded sample (random.Random(20261126).sample over {d.get('population')} no-pain repositories, 3): "
                   f"{', '.join(d.get('sample') or [])}; titles read: {d.get('titles_read')}.")
        for m in d.get("misses") or []:
            out.append(f"- {m['url']}: {md(m['why'])}")
        if not d.get("misses"):
            out.append("- none found")
    else:
        out.append("Not done yet.")
    out += ["", "### Coordinator re-check (§3.5)", ""]
    if recheck:
        kept = sum(1 for r in recheck if r.get("answer") == "keep")
        local = sum(1 for r in recheck if "local-machine" in (r.get("reason") or ""))
        out.append(f"{kept} of {len(recheck)} kept, {len(recheck) - kept} rejected; {local} of the {len(recheck)} "
                   "re-checked items are local-machine durations, not CI.")
        for r in recheck:
            out.append(f"- {r['url']}: {r['answer']}" + (f" ({md(r.get('reason'))})" if r.get("reason") else ""))
    else:
        out.append("Not done yet.")
    out += ["", "### Context notes (failed or apart, never counted)", ""]
    for h in hand:
        if "context" in (h.get("reason") or "") or (h.get("decision") == "pass" and not h.get("counted")):
            out.append(f"- {h['url']} ({h['rule']}, {h['decision']}): {md(h['reason'])}")
    out += ["", "## 5. Counted apart", ""]
    for t in table:
        notes = []
        if t.get("level") in ("plugin-partial", "plugin-not-installed"):
            notes.append(f"{t['level']} (state {t.get('state')})")
        if t.get("building_block"):
            notes.append("building-block (Testcontainers)")
        if t.get("per_test_notes"):
            notes.append("per-test isolation notes: " + "; ".join(
                f"{n['file']}:{n['line']} {md(n['text'][:80])}" for n in t["per_test_notes"][:3]))
        if t.get("state") == "on":
            notes.append(f"option ON (db-serial-count rule miss): {t.get('on_evidence')}")
        if t.get("state") == "unknown":
            notes.append(f"state unknown: {t.get('state_why')}")
        if notes:
            out.append(f"- {t['repo']}: " + " | ".join(notes))
    out += ["", "## 6. Per-stack summary", ""] + stack_rows + ["", stack_line, ""]
    out += ["## 7. Desk survey", ""] + desk_summary(HERE / "desk_survey.md") + [""]
    out += ["## 8. Limits", "",
            "- Listings are capped (10 pages of issues/pulls and of commits, 40 diffs, 15 comment threads, 15 pull "
            "file lists per repository) and start at 2024-01-01; truncated fields are flagged in the table, so pain "
            "is a lower bound.",
            "- Comments are read only for items matched by title/body; pain stated only in comments of unmatched "
            "items is missed.",
            "- Keyword rules miss pain written in other words or other languages; the rule-miss read sizes this "
            "only for 3 seeded repositories.",
            "- The 20 are db-serial-count's qualifying list: a lower-bound sample of its frame, not the market; the "
            "11 per_worker exclusions are not read.",
            "- Context fields (stars, contributors, owner type) are not demand.",
            "- No GitHub search request of any kind was sent; fields that would need search are not filled.",
            "- Hand-check method: 1,023 counted candidates plus the P2 items were too many to read in full one by one. "
            "The session read every item's title and quote; read in full every item with a speed term and a test "
            "term on the same prose line, a P2-diff, P3 or P4 match, or a CI/test/parallel title; and failed the rest "
            "with that stated reason (`handcheck.jsonl`). A pain signal written only deep in a long body, away from "
            "any such line, can be missed.",
            "- The pre-registered failure-term list has no timeout wording, so a parallel attempt that failed by "
            "timing out on a shared database (Deodat-Lawson/LaunchStack #567) is reported apart as P2, not counted "
            "as P3.",
            "- One request file per push, pushed only after the previous run's results commit was pulled: the "
            "workflow's concurrency group keeps one pending run and cancels older pending ones, and a run whose push "
            "is no longer the branch tip refuses to start.", ""]
    out += ["## 9. Budget", "", "| run | request | status | attempts | limit | remaining at end |", "|---|---|---|---|---|---|"]
    for r in cp.get("runs") or []:
        out.append(f"| {r['run']} | {r['request']} | {r['status']} | {r['attempts']} | {r.get('limit')} | {r.get('remaining')} |")
    out.append(f"\nGitHub API attempts in all: {cp.get('attempts_total')}.")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results"))
    ap.add_argument("--out", default=str(HERE / "REPORT.md"))
    ap.add_argument("--partial", action="store_true")
    a = ap.parse_args()
    try:
        text = build(Path(a.results), a.partial)
    except CheckFailed as e:
        print(f"report check failed: {e}")
        return 1
    Path(a.out).write_text(text)
    print(text.splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
