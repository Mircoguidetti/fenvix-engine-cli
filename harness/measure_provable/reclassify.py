"""Re-classify the retained raw sensor output, without running the tests again.

Every run keeps its strace output (gzipped), the engine's trace and the audit log under
<root>/raw/<project>/tNNNNN/, so the accounting can be changed and re-applied offline.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import buckets  # noqa: E402
import classify as C  # noqa: E402
from run import env_dirs  # noqa: E402


def paths_cfg_for(project: str, root: Path, node: bool) -> dict:
    meta = json.loads((root / "out" / f"{project}.prepared.json").read_text())
    engine = [str(HERE), str(root / "out"), str(root / "work"), str(root / "raw")]
    if node:
        src = meta["src"]
        return {"project_src": meta.get("repo_root", src), "site_dirs": [], "stdlib_dirs": [],
                "venv": "/nonexistent-venv",
                "engine_dirs": ["/home/user/fenvix-engine-cli",
                                str(Path(src) / "__fenvix_marker.mjs"), *engine]}
    d = env_dirs(meta["python"])
    return {"project_src": str(root / "src" / project), "site_dirs": d["site"],
            "stdlib_dirs": d["stdlib"], "venv": d["prefix"], "engine_dirs": engine}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", nargs="+", required=True)
    ap.add_argument("--node", nargs="*", default=["valibot"])
    ap.add_argument("--root", default="/home/user/measure")
    ap.add_argument("--infra-baseline", default=None,
                    help="JSON file with the Node runner baseline channel names")
    a = ap.parse_args()
    root = Path(a.root)
    infra = frozenset(json.loads(Path(a.infra_baseline).read_text())) if a.infra_baseline \
        else frozenset()

    for project in a.projects:
        node = project in a.node
        paths = C.Paths(paths_cfg_for(project, root, node))
        old = {r["index"]: r for r in
               (json.loads(ln) for ln in (root / "out" / f"{project}.jsonl").open())
               if "index" in r}
        out = root / "out" / f"{project}.jsonl"
        recs = []
        for d in sorted((root / "raw" / project).glob("t*")):
            idx = int(d.name[1:])
            gz = d / "strace.txt.gz"
            if not gz.exists():
                continue
            with gzip.open(gz, "rb") as fi, tempfile.NamedTemporaryFile(
                    suffix=".txt", delete=False) as tf:
                shutil.copyfileobj(fi, tf)
                tmp = Path(tf.name)
            try:
                parsed = C.parse_strace(tmp, paths, spawns_before_test=not node,
                                        infra_collection=infra if node else frozenset(),
                                        infra_outside_test=node)
            finally:
                tmp.unlink(missing_ok=True)
            nodeid = (d / "nodeid.txt").read_text().strip()
            trace = d / "trace.jsonl"
            if node:
                from run_node import load_engine_ran
                engine = load_engine_ran(trace, nodeid)
            else:
                engine = C.load_engine(trace, nodeid)
                engine["n_ran"] = 1 if engine["found"] else 0
            audit = C.load_audit(d / "audit.tsv")
            allch: dict = {}
            for ph in ("collection", "test", "after"):
                for k, v in parsed["phases"][ph].items():
                    allch[k] = allch.get(k, 0) + v
            testch = dict(parsed["phases"]["test"])
            nat = [] if node else buckets.native_reads(
                parsed, audit, lambda p: paths.cat(p) in buckets.CONTROLLED_E)
            prev = old.get(idx, {})
            rec = {"project": project, "nodeid": nodeid, "index": idx,
                   "exit": prev.get("exit"), "timed_out": prev.get("timed_out"),
                   "wall_s": prev.get("wall_s"),
                   "engine_found": engine["found"], "engine_outcome": engine["outcome"],
                   "engine_sources": engine["sources"],
                   "engine_uncontrolled": engine["uncontrolled"],
                   "engine_n_events": engine["n_events"], "engine_n_ran": engine.get("n_ran"),
                   "channels_all": allch, "channels_test": testch,
                   "native_reads_test": nat[:20], "n_native_reads_test": len(nat),
                   "engine_bootstrap": parsed["engine_bootstrap"],
                   "infra_suppressed": parsed["infra_suppressed"]}
            for rule in ("E", "S"):
                b, c = buckets.classify(allch, engine, nat, rule=rule)
                rec[f"bucket_{rule}"], rec[f"causes_{rule}"] = b, c
            bt, ct = buckets.classify(testch, engine, nat, rule="E")
            rec["bucket_testphase_E"], rec["causes_testphase_E"] = bt, ct
            rec["bucket"], rec["causes"] = rec["bucket_E"], rec["causes_E"]
            if node:
                rec["status"] = "ok" if engine.get("n_ran") == 1 else (
                    "no-test-ran" if engine.get("n_ran") == 0 else "several-tests-ran")
            else:
                rec["status"] = "ok" if engine["found"] else "no-engine-record"
            recs.append(rec)
        with out.open("w") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        print(f"{project}: re-classified {len(recs)} runs -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
