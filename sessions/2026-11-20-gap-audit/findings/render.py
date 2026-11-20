#!/usr/bin/env python3
"""Render REPORT.md from out/ (build_report.py), lead-matrix.md, findings/*.matrix.md, findings/*.notes.md."""
import glob
import json
import os
import re

A = "/home/user/audit"
OUT = os.path.join(A, "out")
ids = dict(line.rstrip("\n").split("\t") for line in open(os.path.join(OUT, "ids-map.tsv")))
stats = json.load(open(os.path.join(OUT, "stats.json")))
AGENTS = {
    "PROC1": "process: Blocks 1-3, Node L0, L1 study, cache step 1, market test, head-to-head",
    "PROC2": "process: skip with proof lineage (shared cache, audit reruns, Rust port, parallel, culprit, dep verdict, all runners)",
    "PROC3": "process: Node cache, other JS runners, Go, JVM, browser/L2, release integration",
    "PROC4": "process: GitHub App, dashboard, API, deploy, customer mode, pricing",
    "BRANCH": "work on branches that did not reach claude/release-1 (engine) or main (app)",
    "SWEEP": "every limit, TODO, disabled test, CI hole, refusal and pin in engine and app",
    "PY1": "Python versions, packaging, first use, runners",
    "PY2": "Python pytest-xdist, plugins, concurrency, native code",
    "PY3": "Python engine features, matrix, levels",
    "ND1": "Node versions, TypeScript toolchains, runners, parallelism, monorepos",
    "ND2": "Node controls, features, cache, Bun/Deno, matrix",
    "FE": "front-end, browser runners, L2 browser lockstep",
    "GO": "Go",
    "JVM": "JVM (Java, Kotlin; Gradle, Maven)",
    "PLAT": "platforms, CI systems, GitHub Action, distribution, MCP, runner wrapper",
    "APP1": "service: GitHub App and API",
    "APP2": "service: Supabase, infra, deploy, security, billing, operations",
    "APP3": "service: dashboard front-end",
    "DOCS": "documentation site and in-repository docs",
    "LAND": "landing page",
    "LEAD": "lead: platform probes on GitHub Actions and re-verification",
}


def sub_ids(text):
    def rep(m):
        sid = m.group(1)
        return ids.get(sid, sid)
    return re.sub(r"\[\[([A-Z0-9]+-\d+)\]\]", rep, text)


def sub_plain_ids(text):
    """Map agent ids appearing in matrix/notes text to report ids, keeping the agent id in brackets."""
    def rep(m):
        sid = m.group(0)
        return f"{ids[sid]} ({sid})" if sid in ids else sid
    return re.sub(r"\b(?:PROC[1-4]|BRANCH|SWEEP|PY[1-3]|ND[12]|FE|GO|JVM|PLAT|APP[1-3]|DOCS|LAND|LEAD)-\d{2,4}\b", rep, text)


def sections(path, pat):
    """Extract every Markdown section whose heading matches pat."""
    if not os.path.exists(path):
        return ""
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    out, keep, lvl = [], False, 0
    for ln in lines:
        m = re.match(r"^(#+)\s+(.*)", ln)
        if m:
            level = len(m.group(1))
            if keep and level <= lvl:
                keep = False
            if not keep and re.search(pat, m.group(2), re.I):
                keep, lvl = True, level
                out.append("#### " + m.group(2).strip())
                continue
        if keep:
            out.append(re.sub(r"^(#+)", "#####", ln) if re.match(r"^#+\s", ln) else ln)
    return "\n".join(out).strip()


def demote(md, base=4):
    def rep(m):
        return "#" * min(6, len(m.group(1)) + base - 1) + " "
    return re.sub(r"^(#+)\s", rep, md, flags=re.M)


def main():
    s = stats
    gl = open(os.path.join(OUT, "gaplist.md")).read()
    pl = open(os.path.join(OUT, "proclist.md")).read()
    lead_matrix = sub_ids(open(os.path.join(A, "lead-matrix.md")).read())
    verified = open(os.path.join(A, "lead-verified.md")).read()
    partial = open(os.path.join(A, "partial-line.txt")).read().strip()
    summary = sub_ids(open(os.path.join(A, "summary.md")).read())
    notcov_lead = open(os.path.join(A, "notcovered-lead.md")).read()
    parts = [partial, "", "# P-036: complete gap audit of the whole product", "",
             "Session 2026-11-20 (claude.ai/code session_01YAF6DjRmmukUFojCgZKdEf). Audit only: no product code was changed.",
             "Audited: fenvix-engine-cli `claude/release-1` @ 529c1609 (plus every other branch), fenvix-app `main` @ c59d913 "
             "(moved from ce69a6b during the audit when `claude/dashboard-vercel` was merged), fenvix-docs `main` @ 4cc4129, "
             "fenvix-landing `main` @ f4d16e3, fenvix-brain-cli `main` @ 1a955a7. Probe workflows: fenvix-engine-cli branch "
             "`claude/gap-audit` (runs 44703540913, 44703690223, 44705292795).",
             "",
             "Delivered in two places: fenvix-engine-cli branch `claude/gap-audit` (this report, the numbered list "
             "`gaps.jsonl`, every agent's findings, notes and matrices under `sessions/2026-11-20-gap-audit/findings/`, and "
             "the probe workflows) and fenvix-brain-cli `main` (this report only).",
             "",
             "Labels: numbers are MEASURED, ESTIMATED, DECLARED (with source) or UNKNOWN. Each gap says how it is known: "
             "RAN (something was executed and showed it), READ (code or config, unambiguous), DOC (only a document or report "
             "says so; not verified).", "",
             "## 0. Summary", "", summary, "",
             "## 1. The matrix", "", lead_matrix, ""]
    for name, title in (("PY3", "Python (agent PY3)"), ("ND2", "Node back-end (agent ND2)"), ("FE", "Front-end and browser (agent FE)"),
                        ("GO", "Go (agent GO)"), ("JVM", "JVM (agent JVM)")):
        p = os.path.join(A, "findings", f"{name}.matrix.md")
        parts.append(f"### 1.{['PY3','ND2','FE','GO','JVM'].index(name) + 2} {title}")
        parts.append("")
        if os.path.exists(p):
            parts.append(sub_plain_ids(demote(open(p).read(), 4)))
        else:
            parts.append(f"Not delivered: the {name} agent was stopped by the budget limit before writing its per-runner matrix. "
                         "The overview (1.1) holds the language-level cells; see section 4.")
        parts.append("")
    parts += ["## 2. The gap list", "",
              f"{s['prod']} product gaps, numbered by severity (WRONG-RESULT, then BLOCKS-USE, DEGRADES, MINOR), then by area. "
              f"Severity counts: " + ", ".join(f"{k} {v}" for k, v in s['prod_sev'].items()) + ". Class: " +
              ", ".join(f"{k} {v}" for k, v in s['prod_cls'].items()) + ". "
              "`source ids` are the auditing agents' ids (evidence detail in their notes files on fenvix-engine-cli branch `claude/gap-audit`, "
              "`sessions/2026-11-20-gap-audit/findings/`); `also found by` lists a duplicate found by another agent "
              "that was merged into the line. DECIDE lines carry the reason for and the reason against.", "", gl, "",
              "## 3. Process gaps (section 12 of the prompt)", "",
              f"{s['proc']} process gaps: a prompt whose \"Done means\" asked for less than the promise, a NOTE, risk, FIX "
              "item or \"not done\" of a report or review that was never fixed or decided, a CLOSED block that is not in "
              "the release, a rule contradicted by what was built. Each names its prompt and block. Severity counts: " +
              ", ".join(f"{k} {v}" for k, v in s['proc_sev'].items()) + ". Class: " +
              ", ".join(f"{k} {v}" for k, v in s['proc_cls'].items()) + ". "
              "Every limit in `docs/LIMITS.md` and the per-language docs, every skipped/xfail test and every CI hole are in "
              "section 2 (area prefixes `Limits /`, `Disabled test /`, `CI /`, `Refusal /`, `Pins /`).", "", pl, "",
              "## 4. What could not be checked, and why", "", notcov_lead, ""]
    for ag in AGENTS:
        if ag == "LEAD":
            continue
        p = os.path.join(A, "findings", f"{ag}.notes.md")
        sec = sections(p, r"could not|not covered|not checked|not finished|not done|left|unverified")
        parts.append(f"### 4.{list(AGENTS).index(ag) + 1} {ag}: {AGENTS[ag]}")
        parts.append("")
        parts.append(sub_plain_ids(sec) if sec else ("No notes file was delivered (agent stopped by the budget limit); "
                                                      "its gaps file is complete up to the stop." if not os.path.exists(p)
                                                      else "The agent reported nothing it could not check."))
        parts.append("")
    parts += ["## 5. Method and lead verification", "",
              "Twenty audit agents worked in parallel, one per area, on a common brief (`findings/BRIEF.md`); the lead "
              "built every engine artifact of release-1 once (`release/install-image.sh`), ran the platform probes on "
              "GitHub Actions, merged the findings, removed cross-agent duplicates (token similarity of the claim ≥ 0.4, "
              "the stronger evidence kept, the other cited under `also found by`), and re-ran a sample of the gravest "
              "claims. Agents were told never to merge their own similar gaps, so no deduplication was done inside one agent. "
              f"Input: {s['in'][0]} product and {s['in'][1]} process entries; after deduplication {s['prod']} and {s['proc']}. "
              f"How known (all lines): RAN {s['how']['RAN']}, READ {s['how']['READ']}, DOC {s['how']['DOC']}.", "",
              "| agent | area |", "|---|---|"] + [f"| {k} | {v} |" for k, v in AGENTS.items()] + ["", "### Lead re-verification log", "",
                                                                                          demote(verified, 4), ""]
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "REPORT.md"), "w").write("\n".join(parts) + "\n")
    print("written", os.path.getsize(os.path.join(OUT, "REPORT.md")))


if __name__ == "__main__":
    main()
