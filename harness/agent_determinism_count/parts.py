#!/usr/bin/env python3
"""Discovery leaf files outside git (a leaf file passes GitHub's 100 MB per-file push limit within an hour).

Each process writes its leaves to results/discovery/leaves_<family>/<family>-<run>.jsonl.gz (<run> = GITHUB_RUN_ID, or
``local``). The workflow uploads that file as the artifact ``agent-determinism-count-leaves-<run>``; git holds only the
index results/discovery/leaf_parts_<family>.json ({file: {run_id, artifact, sha256, bytes, lines}}), refreshed by
commit_results.sh. ``fetch`` downloads every indexed part that is missing locally and checks its sha256.
``restore`` (results/discovery/restore_<family>.json = {"run_id": N}) takes a run's discovery state, splits, pre-pass
and leaf file from its results artifact (run 45603465040 wrote its leaves before this scheme existed).

Usage: parts.py index | fetch --family F | restore --family F | candidates
Every request is GET (Actions artifacts of this repository, GITHUB_TOKEN with actions: read).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
DISC = RES / "discovery"
CACHE = HERE / ".artifacts"
UA = "fenvix-research"
FAMILIES = ("code", "text")


def run_id() -> str:
    """GITHUB_RUN_ID in a workflow; ADC_PART_ID (e.g. ``session``) for the work session's own discovery, whose leaf
    file is committed to git (S1 code leaves are small), not uploaded as an artifact."""
    return os.environ.get("GITHUB_RUN_ID") or os.environ.get("ADC_PART_ID") or "local"


def part_dir(family: str, disc: Path | None = None) -> Path:
    return (disc or DISC) / f"leaves_{family}"


def part_path(family: str, disc: Path | None = None) -> Path:
    return part_dir(family, disc) / f"{family}-{run_id()}.jsonl.gz"


def index_path(family: str) -> Path:
    return DISC / f"leaf_parts_{family}.json"


def _load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def _save(p: Path, d) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    tmp.replace(p)


def file_facts(p: Path) -> dict:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    lines = 0
    try:
        with gzip.open(p, "rt") as f:
            lines = sum(1 for x in f if x.strip())
    except (EOFError, OSError):  # a file being appended to: count what is readable
        pass
    return {"sha256": h.hexdigest(), "bytes": p.stat().st_size, "lines": lines}


def index(family: str) -> dict:
    """Refresh the index from the part files present here (entries of parts not present are kept)."""
    ix = _load(index_path(family), {})
    d = part_dir(family)
    for p in sorted(d.glob("*.jsonl.gz")) if d.exists() else []:
        e = ix.get(p.name) or {"run_id": p.name[len(family) + 1:-len(".jsonl.gz")],
                               "artifact": f"agent-determinism-count-leaves-{p.name[len(family) + 1:-len('.jsonl.gz')]}",
                               "artifact_path": p.name}
        if not e["run_id"].isdigit():  # a work-session part: committed to git, no artifact
            e.update(artifact=None, artifact_path=None, in_git=f"results/discovery/leaves_{family}/{p.name}")
        e.update(file_facts(p))
        ix[p.name] = e
    if ix:
        index_path(family).parent.mkdir(parents=True, exist_ok=True)
        _save(index_path(family), ix)
    return ix


def part_files(family: str, disc: Path | None = None) -> list[Path]:
    d = part_dir(family, disc)
    return sorted(d.glob("*.jsonl.gz")) if d.exists() else []


# ---------------------------------------------------------------------------------------------- artifacts (GET)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url: str, auth: bool, stream_to: Path | None = None):
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if auth:
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    req = urllib.request.Request(url, headers=h, method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(req, timeout=600)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return _get(e.headers["Location"], False, stream_to)  # signed storage URL: no token
        raise
    with r:
        if stream_to is None:
            return json.loads(r.read())
        with open(stream_to, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        return stream_to


def artifact_zip(run: str, name: str) -> Path:
    CACHE.mkdir(exist_ok=True)
    z = CACHE / f"{name}.zip"
    if z.exists() and zipfile.is_zipfile(z):
        return z
    repo = os.environ["GITHUB_REPOSITORY"]
    lst = _get(f"https://api.github.com/repos/{repo}/actions/runs/{run}/artifacts?per_page=100", True)
    hit = [a for a in lst.get("artifacts") or [] if a.get("name") == name and not a.get("expired")]
    if not hit:
        raise SystemExit(f"artifact {name} of run {run} not found")
    _get(hit[0]["archive_download_url"], True, z)
    meta = CACHE / f"{name}.json"
    meta.write_text(json.dumps({k: hit[0].get(k) for k in ("id", "name", "size_in_bytes", "created_at", "expires_at")}))
    return z


def artifact_meta(name: str) -> dict:
    return _load(CACHE / f"{name}.json", {})


def _extract(z: Path, member: str, dest: Path) -> bool:
    with zipfile.ZipFile(z) as zf:
        names = [n for n in zf.namelist() if n == member or n.endswith("/" + member)]
        if not names:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(sorted(names, key=len)[0]) as src, open(dest.with_suffix(dest.suffix + ".tmp"), "wb") as out:
            shutil.copyfileobj(src, out, 1 << 20)
        dest.with_suffix(dest.suffix + ".tmp").replace(dest)
        return True


def fetch(family: str) -> int:
    """Download every indexed part missing here; a sha256 mismatch is an error."""
    bad = 0
    for fn, e in sorted(_load(index_path(family), {}).items()):
        p = part_dir(family) / fn
        if p.exists() and file_facts(p)["sha256"] == e["sha256"]:
            continue
        if e.get("in_git"):
            print(f"{fn}: committed part {e['in_git']} missing or sha256 differs from the index")
            bad += 1
            continue
        z = artifact_zip(e["run_id"], e["artifact"])
        if not _extract(z, e["artifact_path"], p):
            print(f"{fn}: {e['artifact_path']} not in {e['artifact']}")
            bad += 1
            continue
        got = file_facts(p)
        if got["sha256"] != e["sha256"]:
            print(f"{fn}: sha256 {got['sha256']} != index {e['sha256']}")
            bad += 1
        else:
            print(f"{fn}: {got['lines']} leaves from {e['artifact']}")
    return 1 if bad else 0


def fetch_candidates() -> int:
    """results/candidates.jsonl.gz from the build run's artifact, by results/candidates_index.json (sha256 checked);
    0 when present and matching or when no build has run yet."""
    ix = _load(RES / "candidates_index.json", None)
    p = RES / "candidates.jsonl.gz"
    if not ix:
        return 0
    if p.exists() and file_facts(p)["sha256"] == ix["sha256"]:
        return 0
    if not _extract(artifact_zip(ix["run_id"], ix["artifact"]), ix["artifact_path"], p):
        print(f"candidates: {ix['artifact_path']} not in {ix['artifact']}")
        return 1
    got = file_facts(p)["sha256"]
    if got != ix["sha256"]:
        print(f"candidates: sha256 {got} != index {ix['sha256']}")
        return 1
    print(f"candidates: {ix['lines']} rows from {ix['artifact']}")
    return 0


def _nodes(st: dict) -> int:
    return sum(q.get("nodes", 0) for q in (st.get("queries") or {}).values())


def restore(family: str) -> int:
    """Once: take discovery state, splits, pre-pass and leaf file of results/discovery/restore_<family>.json's run
    from its results artifact, unless the local state is already as far."""
    spec = _load(DISC / f"restore_{family}.json", None)
    if not spec or spec.get("restored_at"):
        return 0
    run = str(spec["run_id"])
    z = artifact_zip(run, f"agent-determinism-count-results-{run}")
    tmp = CACHE / f"restore-{run}"
    files = {f"discovery_state_{family}.json": RES / f"discovery_state_{family}.json",
             f"discovery/splits_{family}.jsonl": DISC / f"splits_{family}.jsonl",
             f"prepass_{family}.json": RES / f"prepass_{family}.json"}
    got = {}
    for member in files:
        if _extract(z, member, tmp / member):
            got[member] = tmp / member
    leaf = part_dir(family) / f"{family}-{run}.jsonl.gz"
    have_leaf = _extract(z, f"discovery/leaves_{family}.jsonl.gz", tmp / "leaves.jsonl.gz")
    st_new = _load(got.get(f"discovery_state_{family}.json", tmp / "none"), {})
    st_old = _load(RES / f"discovery_state_{family}.json", {})
    if not have_leaf or _nodes(st_new) < _nodes(st_old):
        print(f"restore {run}: not used (leaf file {have_leaf}, nodes {_nodes(st_new)} < local {_nodes(st_old)})")
        return 1
    for member, src in got.items():
        files[member].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, files[member])
    leaf.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp / "leaves.jsonl.gz"), leaf)
    ix = _load(index_path(family), {})
    ix[leaf.name] = {"run_id": run, "artifact": f"agent-determinism-count-results-{run}",
                     "artifact_path": f"discovery/leaves_{family}.jsonl.gz", **file_facts(leaf),
                     "expires_at": artifact_meta(f"agent-determinism-count-results-{run}").get("expires_at")}
    _save(index_path(family), ix)
    import datetime as dt
    spec["restored_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    spec["nodes"] = _nodes(st_new)
    spec["leaves"] = ix[leaf.name]["lines"]
    _save(DISC / f"restore_{family}.json", spec)
    print(f"restored run {run}: {spec['nodes']} nodes, {spec['leaves']} leaves")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["index", "fetch", "restore", "candidates"])
    ap.add_argument("--family", choices=FAMILIES)
    a = ap.parse_args(argv)
    if a.cmd == "index":
        for fam in FAMILIES:
            index(fam)
        return 0
    if a.cmd == "candidates":
        return fetch_candidates()
    return fetch(a.family) if a.cmd == "fetch" else restore(a.family)


if __name__ == "__main__":
    sys.exit(main())
