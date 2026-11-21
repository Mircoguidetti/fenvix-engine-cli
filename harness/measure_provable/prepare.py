"""Clone and install a measurement project, following harness/detpy_harness.py conventions."""
import json, os, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, "/home/user/fenvix-engine-cli/harness")
from detpy_harness import detect_install  # noqa: E402

ROOT = Path("/home/user/measure")
WHEEL = sorted(Path("/home/user/fenvix-engine-cli/dist").glob("fenvix-*.whl"))[-1]
PYVER = "3.13"


def sh(cmd, cwd=None, timeout=2400):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def main(name, url, extra_install, pytest_args):
    src = ROOT / "src" / name
    venv = ROOT / "venvs" / name
    logs = ROOT / "logs"
    if not (src / ".git").exists():
        shutil.rmtree(src, ignore_errors=True)
        code, out = sh(["git", "clone", "--depth", "1", "--quiet", url, str(src)])
        if code != 0:
            print(f"{name}: clone-failed: {out[-300:]}"); return 1
    commit = sh(["git", "rev-parse", "HEAD"], cwd=src)[1].strip()[:12]
    commit_date = sh(["git", "log", "-1", "--format=%cs"], cwd=src)[1].strip()

    shutil.rmtree(venv, ignore_errors=True)
    code, out = sh(["uv", "venv", "--quiet", "--python", PYVER, str(venv)])
    if code != 0:
        print(f"{name}: venv failed: {out[-300:]}"); return 1
    py = venv / "bin" / "python"
    base = ["uv", "pip", "install", "--quiet", "--python", str(py)]
    tools = [str(WHEEL), "pytest>=7", "pytest-randomly", "pytest-xdist"]
    args, groups, reqs = detect_install(src)
    attempts = [args + groups + reqs + extra_install, args + groups + extra_install,
                args + reqs + extra_install, args + extra_install, ["-e", "."] + extra_install]
    install_cmd = None
    for attempt in attempts:
        code, out = sh(base + attempt + tools, cwd=src)
        (logs / f"{name}.install.log").write_text(" ".join(attempt) + "\n" + out)
        if code == 0:
            install_cmd = " ".join(attempt); break
    if install_cmd is None:
        print(f"{name}: install-failed: {out[-500:]}"); return 1

    env = dict(os.environ); env.pop("PYTHONHASHSEED", None)
    code, out = sh([str(py), "-m", "pytest", "-p", "no:randomly", "--collect-only", "-q", *pytest_args],
                   cwd=src, timeout=1200)
    (logs / f"{name}.collect.log").write_text(out)
    n = sum(1 for ln in out.splitlines() if "::" in ln)
    if code != 0 and n == 0:
        print(f"{name}: collect-failed: {out[-500:]}"); return 1
    meta = {"name": name, "url": url, "commit": commit, "commit_date": commit_date,
            "install": install_cmd, "python": str(py), "python_version": PYVER,
            "pytest_args": pytest_args, "collected": n}
    (ROOT / "out" / f"{name}.prepared.json").write_text(json.dumps(meta, indent=1))
    print(f"{name}: ok commit={commit} ({commit_date}) collected={n}")
    return 0


if __name__ == "__main__":
    spec = json.loads(sys.argv[1])
    sys.exit(main(spec["name"], spec["url"], spec.get("install", []), spec.get("pytest_args", [])))
