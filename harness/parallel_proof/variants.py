"""Run the variants of the parallel-proof measurement in one repository (P0; design 1.3, 5).

usage: python -m harness.parallel_proof.variants --repo DIR --python PY --out OUTDIR --label L -- PYTEST ARGS...
       [--variants plain-serial,plain-n4,det-serial-a,det-n4-a,det-serial-b,det-n4-b,cache-ser-cold,...]
       [--workers 4] [--dist load] [--timeout 3600]

Each variant runs ``PY -m pytest -p no:cacheprovider -q <PYTEST ARGS> <variant args>`` in DIR, one after another,
and appends one JSON line to OUTDIR/summary.jsonl: label, variant, wall seconds (MEASURED, wall clock around the
process), return code, the pytest summary line. ``--det`` variants write their trace to OUTDIR/<variant>.jsonl and
``-n`` variants copy ``.detpy/plan.json`` to OUTDIR/<variant>.plan.json. Cache variants share OUTDIR/cache-<mode>/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time

DEFAULT = ("plain-serial,plain-n,det-serial-a,det-n-a,det-serial-b,det-n-b,"
           "cache-ser-cold,cache-ser-warm,cache-n-cold,cache-n-warm,cache-n-warm2")


def variant_args(v: str, out: str, workers: int, dist: str) -> list[str]:
    par = ["-n", str(workers)] + (["--dist", dist] if dist else [])
    det = ["--det", f"--det-trace={os.path.join(out, v + '.jsonl')}"]
    if v == "plain-serial":
        return []
    if v == "plain-n":
        return par
    if v.startswith("det-serial"):
        return det
    if v.startswith("det-n"):
        return det + par
    if v.startswith("cache-ser"):
        return det + [f"--det-cache={os.path.join(out, 'cache-ser')}",
                      f"--det-cache-receipts={os.path.join(out, v + '.receipts.jsonl')}"]
    if v.startswith("cache-n"):
        return det + par + [f"--det-cache={os.path.join(out, 'cache-n')}",
                            f"--det-cache-receipts={os.path.join(out, v + '.receipts.jsonl')}"]
    if v.startswith("cache-x"):  # a parallel run on the serial store (cross-mode reuse)
        return det + par + [f"--det-cache={os.path.join(out, 'cache-ser')}",
                            f"--det-cache-receipts={os.path.join(out, v + '.receipts.jsonl')}"]
    if v.startswith("cache-y"):  # a serial run on the store written under -n (cross-mode reuse)
        return det + [f"--det-cache={os.path.join(out, 'cache-n')}",
                      f"--det-cache-receipts={os.path.join(out, v + '.receipts.jsonl')}"]
    raise SystemExit(f"unknown variant {v}")


def last_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if " in " in ln and ("passed" in ln or "failed" in ln or "error" in ln):
            return ln.strip("= ")
    return lines[-1] if lines else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--variants", default=DEFAULT)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dist", default="")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("pytest_args", nargs="*")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for v in a.variants.split(","):
        args = [a.python, "-m", "pytest", "-p", "no:cacheprovider", "-q", *a.pytest_args,
                *variant_args(v, os.path.abspath(a.out), a.workers, a.dist)]
        t0 = time.perf_counter()
        try:
            p = subprocess.run(args, cwd=a.repo, capture_output=True, text=True, timeout=a.timeout)
            rc, text = p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            rc, text = "timeout", (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else ""
        wall = round(time.perf_counter() - t0, 1)
        with open(os.path.join(a.out, f"{v}.log"), "w") as f:
            f.write(text)
        plan = os.path.join(a.repo, ".detpy", "plan.json")
        if "-n" in args and "--det" in args and os.path.exists(plan):
            shutil.copy(plan, os.path.join(a.out, f"{v}.plan.json"))
        rec = {"label": a.label, "variant": v, "wall_s": wall, "rc": rc, "summary": last_line(text),
               "cache": [ln for ln in text.splitlines() if ln.startswith(("reused ", "not reused", "parallel:"))],
               "plan": [ln for ln in text.splitlines() if ln.startswith(("plan ", "merged trace"))]}
        with open(os.path.join(a.out, "summary.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
