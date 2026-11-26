"""Offline: stored raw files -> ``results/table.jsonl`` (one row per repository) and ``results/items.jsonl``.

No network. Deterministic: the same ``raw/`` gives byte-identical output (Testing plan, integration identity).

    python3 harness/db_copies_read/build.py [--results DIR] [--repos repos.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import rules as R  # noqa: E402

COUNTED = ("P1", "P3-revert", "P3-closed", "P3-text", "P4")


def _first_line(s: str) -> str:
    return (s or "").splitlines()[0] if s else ""


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def locate(text: str | None, runner_line: str) -> dict | None:
    """The file line holding the runner command: the longest token prefix of the runner line found on one line."""
    if not text:
        return None
    toks = runner_line.split()
    lines = text.splitlines()
    for k in range(len(toks), min(len(toks), 3) - 1, -1):
        pre = " ".join(toks[:k])
        word, _ = R.command_word(pre)
        if not word:
            continue
        for i, ln in enumerate(lines):
            if pre in _ws(ln):
                return {"line": i + 1, "text": ln}
    return None


def stated_reason(text: str | None, ev: dict | None, reason: str) -> str:
    if text and ev:
        lines = text.splitlines()
        lo, hi = max(ev["line"] - 11, 0), min(ev["line"] + 10, len(lines))
        got = []
        for i in range(lo, hi):
            s = lines[i].strip()
            if s.startswith("#") or s.startswith("//"):
                got.append(f"L{i + 1}: {s[:200]}")
        if got:
            return " | ".join(got[:5])
    return "none stated (runner default)" if reason == "default-serial" else "none stated"


def contributors(stage: dict | None):
    if not stage:
        return None
    if stage.get("count") == "unknown":
        return "unknown"
    e = (stage.get("responses") or [None])[0]
    if not e:
        return None
    if e["status"] == 204:
        return 0
    m = re.search(r'[?&]page=(\d+)>; rel="last"', (e.get("headers") or {}).get("link") or "")
    if m:
        return int(m.group(1))
    return len(e.get("data") or [])


def build_repo(results: Path, row: dict, cp_state: dict | None) -> tuple[dict, list[dict]]:
    repo = row["repo"]
    base = results / "raw" / J.slug(repo)

    def load(stage):
        p = base / f"{stage}.json.gz"
        return J.jload(p) if p.exists() else None

    out = {"repo": repo, "html_url": row["html_url"], "runner": row["kind"], "runner_line": row["runner_line"],
           "runner_src": row["runner_src"], "file": row["file"], "job": row["job"], "wd": row["wd"],
           "median_s": row["median_s"], "median_min": round(row["median_s"] / 60.0, 1), "reason": row["reason"],
           "other_ge10_pairs": row["other_ge10_pairs"]}
    state = (cp_state or {}).get("state") or "missing"
    meta_st = load("meta")
    if state == "unavailable" or (meta_st and meta_st["responses"][0]["status"] in (404, 451)):
        m = (meta_st or {"responses": [{}]})["responses"][0]
        out.update(status="unavailable", unavailable_reason=f"status {m.get('status')}"
                   + (" archived" if (m.get("data") or {}).get("archived") else ""),
                   level="n/a", state="n/a", free_off="no", truncated={})
        return out, []
    stages = {s: load(s) for s in J.STAGES}
    missing = [s for s in J.STAGES if stages[s] is None]
    if state != "done" or missing:
        out.update(status="incomplete", missing_stages=missing, level="n/a", state="n/a", free_off="no", truncated={})
        return out, []
    out["status"] = "done"
    meta = stages["meta"]["responses"][0]["data"]
    files = stages["files"]
    texts = J.file_texts(files)
    tree_files, tree_dirs = J.Reader(None, results).tree_paths(stages["tree"])
    dep_paths = [p for p in texts if R.DEP_FILE.search(p)]
    dep_texts = [texts[p] for p in dep_paths]
    dsm_texts = [t for p, t in texts.items() if p == row["file"] or re.search(r"(pytest\.ini|pyproject\.toml|setup\.cfg)$", p)]
    is_dj, dj_why = R.django_project(dep_texts, dsm_texts, sorted(tree_files))
    level = R.level_for(row["kind"], is_dj, dep_texts)
    cfg = {p: t for p, t in texts.items() if re.search(r"(^|/)(pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini)$", p)}
    addopts = R.addopts_lines(cfg) + [
        (row["file"], n + 1, ln) for n, ln in enumerate((texts.get(row["file"]) or "").splitlines())
        if re.search(r"PYTEST_ADDOPTS", ln)]
    settings_path = (files.get("info") or {}).get("settings_module")
    st, why = R.state_for(level, row["kind"], row["runner_line"], addopts, texts.get(settings_path) if settings_path else None)
    ev = locate(texts.get(row["runner_src"]), row["runner_line"])
    off_ev = None
    if st == "off":
        if ev:
            off_ev = {"file": row["runner_src"], "line": ev["line"], "text": ev["text"]}
        else:
            st, why = "unknown", "runner line not found in the stored file"
    on_ev = None
    if st == "on":
        on_ev = [{"file": a[0], "line": a[1], "text": a[2]} for a in addopts
                 if any(p == "parallel" for p, _ in R.flag_tokens(a[2]))] or (
            [{"file": row["runner_src"], "line": ev["line"], "text": ev["text"]}] if ev else [])
    free_off = "yes" if level in ("built-in", "plugin-installed") and st == "off" else "no"
    plugin_dep = None
    if level == "plugin-installed":
        plugin_dep = {n: [p for p in dep_paths if R.has_dep([texts[p]], n)] for n in ("pytest-django", "pytest-xdist")}
    out.update(
        level=level, state=st, state_why=why, free_off=free_off, off_evidence=off_ev, on_evidence=on_ev,
        plugin_deps=plugin_dep, building_block=R.has_testcontainers(dep_texts),
        django_project=is_dj, django_why=dj_why, orms=R.orms_in(dep_texts), dependency_files=dep_paths,
        files_fetched=files.get("paths"), files_not_fetched=files.get("not_fetched"),
        test_dir=(files.get("info") or {}).get("test_dir"), settings_module=settings_path,
        per_test_notes=R.per_test_notes({p: t for p, t in texts.items() if p.rsplit("/", 1)[-1] in
                                         ("conftest.py",) or p == settings_path}),
        stated_reason=stated_reason(texts.get(row["runner_src"]), ev, row["reason"]),
        runner_evidence=ev,
    )
    issues = stages["issues"]
    iitems = J.issue_items(issues)
    citems = J.commit_items(stages["commits"])
    out["context"] = {
        "stars": meta.get("stargazers_count"), "forks": meta.get("forks_count"), "created_at": meta.get("created_at"),
        "pushed_at": meta.get("pushed_at"), "owner_type": (meta.get("owner") or {}).get("type"),
        "contributors": contributors(stages["contributors"]), "open_issues_count": meta.get("open_issues_count"),
        "has_issues": meta.get("has_issues"), "issues_mode": issues.get("mode"),
        "n_issues": sum(1 for i in iitems if i["kind"] == "issue"), "n_pulls": sum(1 for i in iitems if i["kind"] == "pull"),
        "n_commits": len(citems)}
    d = stages["diffs"]
    out["truncated"] = {k: v for k, v in {
        "issues": bool(issues.get("truncated")), "commits": bool(stages["commits"].get("truncated")),
        "diffs": bool(d.get("truncated")), "comments": bool(stages["comments"].get("truncated")),
        "pullfiles": bool(stages["pullfiles"].get("truncated")), "files": bool(files.get("not_fetched")),
        "tree": bool((stages["tree"]["responses"][0].get("data") or {}).get("truncated"))}.items() if v}
    out["diffs_left_out"] = {"message_matched": d.get("left_out_message_matched", 0),
                             "path_listed": d.get("left_out_path_listed", 0)}
    out["window"] = R.WINDOW_START
    items = build_items(repo, iitems, citems, stages)
    out["n_items"] = len(items)
    out["n_counted_candidates"] = sum(1 for i in items if i["counted"])
    return out, items


def build_items(repo: str, iitems: list[dict], citems: list[dict], stages: dict) -> list[dict]:
    items = []
    diffs = {}
    for e in stages["diffs"].get("responses") or []:
        dd = e.get("data") or {}
        if isinstance(dd, dict) and dd.get("sha"):
            diffs[dd["sha"]] = dd.get("files") or []
    pfiles = {}
    for e in stages["pullfiles"].get("responses") or []:
        m = re.search(r"pulls/(\d+)/files", e["path"])
        if m:
            pfiles[int(m.group(1))] = e.get("data") or []

    def add(kind, url, date, user, title, text, raw_text, extra_rules=(), changes=None, number=None, sha=None,
            state=None, merged_at=None):
        rules = R.text_rules(kind, text)
        if changes is not None:
            rules += R.diff_rules(changes)
        rules += list(extra_rules)
        rules = sorted(set(rules))
        if not rules:
            return None
        rec = {"repo": repo, "kind": kind, "url": url, "date": date, "author": (user or {}).get("login"),
               "author_type": "Bot" if R.is_bot(user) else ((user or {}).get("type") or "unknown"), "title": title,
               "number": number, "sha": sha, "state": state, "merged_at": merged_at, "rules": rules,
               "changes": {k: v for k, v in (changes or {}).items() if v} or None}
        rec["excluded_reason"] = R.exclusion(kind, user, title, text, date, rules)
        rec["quote"] = quote(rules, text, changes, raw_text)
        items.append(rec)
        return rec

    for it in iitems:
        text = it["title"] + "\n" + it["body"]
        ch = R.diff_changes(pfiles[it["number"]]) if it["number"] in pfiles else None
        add(it["kind"], it["html_url"], it["created_at"], it["user"], it["title"], text, text, changes=ch,
            number=it["number"], state=it["state"], merged_at=it["merged_at"])
    for c in citems:
        ch = R.diff_changes(diffs[c["sha"]]) if c["sha"] in diffs else None
        user = J._commit_user(c)
        add("commit", c["html_url"], c["date"], user, _first_line(c["message"]), c["message"], c["message"],
            changes=ch, sha=c["sha"])
    for e in stages["comments"].get("responses") or []:
        for cm in e.get("data") or []:
            if isinstance(cm, dict):
                add("comment", cm.get("html_url"), cm.get("created_at"), cm.get("user") or {}, "",
                    cm.get("body") or "", cm.get("body") or "")
    # P3: P2 later reverted, or a P2 pull closed unmerged
    for rec in items:
        if not any(r in ("P2-text", "P2-diff") for r in rec["rules"]):
            continue
        if rec["kind"] == "pull" and rec["state"] == "closed" and not rec["merged_at"]:
            rec["rules"] = sorted(set(rec["rules"]) | {"P3-closed"})
        toks = {x["token"] for x in ((rec.get("changes") or {}).get("added_parallel") or [])}
        for c in citems:
            if (c["date"] or "") <= (rec["date"] or ""):
                continue
            msg = c["message"]
            hit = "revert" in msg.lower() and (
                (rec.get("sha") and rec["sha"][:7] in msg) or (rec["title"] and rec["title"] in msg))
            if not hit and toks and c["sha"] in diffs:
                ch = R.diff_changes(diffs[c["sha"]])
                rem = {x["token"] for x in ch["removed_parallel"]}
                flag = lambda t: t.split(" ")[0]  # noqa: E731
                readded = {flag(x["token"]) for x in ch["added_parallel"]}
                hit = bool({t for t in toks & rem if flag(t) not in readded})
            if hit:
                rec["rules"] = sorted(set(rec["rules"]) | {"P3-revert"})
                rec["revert_evidence"] = c["html_url"]
                break
    for i, rec in enumerate(sorted(items, key=lambda r: (r["date"] or "", r["url"] or ""))):
        rec["id"] = f"{repo}#{i + 1}"
    for rec in items:
        rec["counted_rules"] = [r for r in rec["rules"] if r in COUNTED]
        rec["p1_db"] = "P1-db" in rec["rules"]
        rec["p2"] = any(r in ("P2-text", "P2-diff") for r in rec["rules"])
        rec["counted"] = bool(rec["counted_rules"]) and not rec["excluded_reason"]
    items.sort(key=lambda r: r["id"].split("#")[0] + "#" + r["id"].split("#")[1].zfill(6))
    return items


def quote(rules: list[str], text: str, changes: dict | None, raw_text: str) -> str:
    textual = [r for r in rules if r in ("P1", "P1-db", "P2-text", "P3-text")]
    if textual:
        order = [r for r in ("P3-text", "P1", "P2-text", "P1-db") if r in textual]
        return R.quote_for(text, order)
    if changes:
        for k in ("added_serial", "added_parallel"):
            for x in changes.get(k) or []:
                return x["line"].strip()[:300]
    return _first_line(raw_text)[:300]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results"))
    ap.add_argument("--repos", default=str(HERE / "repos.json"))
    a = ap.parse_args()
    results = Path(a.results)
    rows = json.loads(Path(a.repos).read_text())["repos"]
    cp = J.load_checkpoint(results) or J.new_checkpoint()
    table, items = [], []
    for row in rows:
        t, it = build_repo(results, row, cp["repos"].get(row["repo"]))
        table.append(t)
        items += it
    (results / "table.jsonl").write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in table))
    (results / "items.jsonl").write_text("".join(json.dumps(i, sort_keys=True) + "\n" for i in items))
    print(f"table {len(table)} rows ({sum(1 for t in table if t['status'] == 'done')} done); items {len(items)} "
          f"({sum(1 for i in items if i['counted'])} counted candidates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
