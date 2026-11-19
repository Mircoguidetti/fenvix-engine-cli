"""Differential driver: run the same project under the reference Python capture and the Rust capture."""
import json, os, re, shutil, subprocess, sys, textwrap, importlib.util
from pathlib import Path

REPO = Path("/home/user/fenvix-engine-cli")
REF = REPO / "tests/rust_hotpaths_ref"
VOL = re.compile(rb'"(run|duration)": ?("[^"]*"|[0-9.e-]+)')

def write(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(textwrap.dedent(text))

def run(root, cache, mode, tag, extra_env=None, args=()):
    flag = root.parent / f"{root.name}-capref"
    flag.write_text("1" if mode == "ref" else "0")
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(REF), "DETPY_CAPTURE_REF": "@" + str(flag),
                "DETPY_PYC_CACHE": str(root.parent / "pyc")})
    for k in ("DETPY_REEXEC", "PYTHONHASHSEED"):
        env.pop(k, None)
    env.update(extra_env or {})
    o = root.parent / f"{root.name}-o-{mode}-{tag}.json"
    r = subprocess.run([sys.executable, "-m", "pytest", "--det", "-p", "no:cacheprovider", "-p", "_capref",
                        f"--det-cache={cache}", f"--det-outcomes={o}", *args], cwd=root, env=env,
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    if "INTERNALERROR" in out or not o.exists():
        print(out[-4000:])
        raise SystemExit("internal error")
    d = json.loads(o.read_text())
    cp = d.get("cache") or {}
    return {"store": VOL.sub(rb'"\1": 0', (cache / "proof-cache.json").read_bytes()),
            "receipts": [VOL.sub(b"", x.encode()) for x in (cache / "receipts.jsonl").read_text().splitlines()],
            "outcomes": d.get("outcomes"),
            "summary": {k: v for k, v in cp.items() if not k.endswith("seconds") and k not in ("receipts", "config", "runtime")},
            "out": out}

def diff_json(a, b):
    a, b = json.loads(a), json.loads(b)
    ta, tb = a.get("tests", {}), b.get("tests", {})
    for k in sorted(set(ta) | set(tb)):
        if ta.get(k) != tb.get(k):
            print("  TEST", k)
            ea, eb = ta.get(k) or {}, tb.get(k) or {}
            for f in sorted(set(ea) | set(eb)):
                if ea.get(f) != eb.get(f):
                    print("    ", f, "ref=", json.dumps(ea.get(f))[:400], "\n     ", f, "new=", json.dumps(eb.get(f))[:400])
    for k in sorted(set(a) | set(b)):
        if k != "tests" and a.get(k) != b.get(k):
            print("  TOP", k, str(a.get(k))[:300], "|||", str(b.get(k))[:300])

def main(spec_path, base):
    spec = importlib.util.spec_from_file_location("spec", spec_path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    base = Path(base)
    res = {}
    for mode in ("ref", "new"):
        root = base / "proj"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        cache = base / "proj-cache"
        shims = [p.read_bytes() for p in cache.glob("clockshim-*")] if cache.exists() else []
        names = [p.name for p in cache.glob("clockshim-*")] if cache.exists() else []
        if cache.exists(): shutil.rmtree(cache)
        cache.mkdir()
        for n, b in zip(names, shims): (cache / n).write_bytes(b)
        write(root, m.FILES)
        if hasattr(m, "setup"): m.setup(root)
        out = []
        for i, step in enumerate(m.STEPS):
            if step.get("mutate"): step["mutate"](root)
            out.append(run(root, cache, mode, str(i), step.get("env"), step.get("args", ())))
        res[mode] = out
        shutil.copytree(cache, base / f"keep-cache-{mode}", dirs_exist_ok=True)
    ok = True
    for i in range(len(m.STEPS)):
        r, n = res["ref"][i], res["new"][i]
        for k in ("store", "receipts", "outcomes", "summary"):
            if r[k] != n[k]:
                ok = False
                print(f"session {i+1}: {k} differ")
                if k == "store": diff_json(r[k], n[k])
                elif k == "summary":
                    for kk in sorted(set(r[k]) | set(n[k])):
                        if r[k].get(kk) != n[k].get(kk): print("   ", kk, "ref=", r[k].get(kk), "\n    ", kk, "new=", n[k].get(kk))
                else:
                    print("   ref", str(r[k])[:1500]); print("   new", str(n[k])[:1500])
    for i in range(len(m.STEPS)):
        print(f"session {i+1}: new summary reused={res['new'][i]['summary'].get('reused')} recorded={res['new'][i]['summary'].get('recorded')} nc={res['new'][i]['summary'].get('not_cached')}")
    print("EQUAL" if ok else "DIFFER")
    return res

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
