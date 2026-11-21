"""posix.urandom: a test whose outcome depends on it; the cache reuses the first pass, fresh --det runs differ."""
import pathlib, shutil, subprocess, sys, tempfile
root = pathlib.Path(tempfile.mkdtemp(prefix="r053eo-")); (root / "tests").mkdir()
(root / "tests/test_e.py").write_text("import posix\n\ndef test_e():\n    assert posix.urandom(1)[0] % 2 == 0\n")
def go(*a):
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det", *a, "tests"], cwd=root, capture_output=True, text=True)
    return p.returncode, next((l for l in p.stdout.splitlines() if l.startswith("reused")), "")
c = f"--det-cache={root/'.c'}"
while go(c)[0] != 0:
    shutil.rmtree(root / ".c", ignore_errors=True)
cached = [go(c) for _ in range(5)]
fresh = [go()[0] for _ in range(10)]
print("cached exit codes:", [x[0] for x in cached], cached[-1][1][:40])
print("fresh --det exit codes:", fresh)
shutil.rmtree(root)
