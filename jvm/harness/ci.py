#!/usr/bin/env python3
"""CI helpers for the JVM rounds: candidate matrix and selection after prepare."""
import glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from jvm_harness import name_of  # noqa: E402


def out(k, v):
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
        f.write(f"{k}={v}\n")


def main():
    cmd = sys.argv[1]
    cands = json.load(open(os.path.join(HERE, "idoft_candidates.json")))
    if cmd == "candidates":
        n, names = int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else ""
        sel = [name_of(c) for c in cands]
        sel = [x for x in sel if x in names.split(",")] if names else sel[:n]
        out("matrix", json.dumps(sel))
        print(sel)
    elif cmd == "select":
        k, d = int(sys.argv[2]), sys.argv[3]
        ok = []
        rows = []
        for c in cands:
            p = os.path.join(d, f"prepare-{name_of(c)}", name_of(c), "prepare.json")
            if os.path.exists(p):
                r = json.load(open(p))
                rows.append(r)
                if r["status"] == "ok" and len(ok) < k:
                    ok.append(name_of(c))
        os.makedirs("jvm/harness/results/idoft", exist_ok=True)
        json.dump(rows, open("jvm/harness/results/idoft/prepare.json", "w"), indent=1)
        out("matrix", json.dumps(ok))
        print(len(rows), "prepared;", len(ok), "selected:", ok)


if __name__ == "__main__":
    main()
