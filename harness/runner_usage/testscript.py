"""Second measure: the runner named by the root package.json `test` script (following `npm run x` / `pnpm x` /
`yarn x` references inside the same package.json, depth 3). Monorepo delegation (turbo, nx, lerna, pnpm -r,
npm -ws, yarn workspaces) is its own class. Input: the repositories of the sample (repos-*.jsonl)."""
import concurrent.futures as cf, json, os, re, sys, urllib.request
import sample

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
RUN = re.compile(r"(?:npm\s+run|pnpm(?:\s+run)?|yarn(?:\s+run)?|bun\s+run)\s+([\w:.\-]+)")
DELEG = re.compile(r"\b(turbo|nx\s+(run|run-many|affected)|lerna\s+run|pnpm\s+(-r|--recursive|-w\s+-r|--filter)|npm\s+(-ws|--workspaces)|yarn\s+workspaces|wireit|rush\s+test|moon\s+run)\b")
RUNNERS = ["vitest", "jest", "mocha", "node_test", "ava", "jasmine", "tap", "uvu", "bun_test", "deno_test", "karma", "playwright", "cypress"]
LOADERS = ["tsx", "ts_node", "swc_register", "esbuild_register", "strip_types"]


def classify(pkg):
    try:
        s = json.loads(pkg).get("scripts") or {}
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(s, dict) or "test" not in s:
        return {"test": None}
    seen, todo, lines = set(), ["test"], []
    for _ in range(4):
        nxt = []
        for k in todo:
            if k in seen or not isinstance(s.get(k), str): continue
            seen.add(k); lines.append(s[k])
            nxt += [m for m in RUN.findall(s[k]) if m in s]
        todo = nxt
    text = "\n".join(lines)
    hits = [n for n in RUNNERS + LOADERS if sample.JS_CMD[n].search(text)]
    return {"test": s["test"][:200], "hits": hits, "delegated": bool(DELEG.search(text)) and not [h for h in hits if h in RUNNERS]}


def one(r):
    return dict(full=r["full"], lang=r["lang"], stars=r["stars"], **(classify(sample.raw(r["full"], r["ref"], "package.json")) or {"test": None, "nopkg": True}))


if __name__ == "__main__":
    for lang in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["TypeScript", "JavaScript"]):
        rows = [json.loads(l) for l in open(os.path.join(OUT, f"repos-{lang}.jsonl"))]
        with cf.ThreadPoolExecutor(16) as ex, open(os.path.join(OUT, f"testscript-{lang}.jsonl"), "w") as f:
            for res in ex.map(one, rows):
                f.write(json.dumps(res) + "\n")
