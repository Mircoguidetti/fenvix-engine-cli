"""Item 5 (g0510): under the default controlled entropy a test that reads entropy is reused. Is every entropy path
controlled (same bytes every run), or refused? Reused + uncontrolled would report one random outcome forever."""
import os, pathlib, shutil, subprocess, sys, tempfile
P0 = {"os.urandom": "import os\nv = os.urandom(8)", "posix.urandom": "import posix\nv = posix.urandom(8)",
     "/dev/urandom": "v = open('/dev/urandom', 'rb').read(8)", "random.SystemRandom": "import random\nv = random.SystemRandom().getrandbits(64)",
     "uuid4": "import uuid\nv = uuid.uuid4()", "secrets": "import secrets\nv = secrets.token_bytes(8)",
     "os.getrandom": "import os\nv = os.getrandom(8)"}
P = {k: v for k, v in P0.items() if k in sys.argv[1:] or not sys.argv[1:]}
for name, code in P.items():
    root = pathlib.Path(tempfile.mkdtemp(prefix="r053e-"))
    (root / "tests").mkdir()
    (root / "tests/test_e.py").write_text("def test_e():\n" + "".join("    " + l + "\n" for l in code.splitlines()) + "    print('VALUE', v)\n")
    vals, summ = [], []
    for i in range(3):
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-s", "-p", "no:cacheprovider", "--det", f"--det-cache={root/'.c'}", "tests"],
                           cwd=root, capture_output=True, text=True)
        vals.append(next((l for l in p.stdout.splitlines() if l.startswith("VALUE")), "-"))
        summ.append(next((l for l in p.stdout.splitlines() if l.startswith(("reused", "not cacheable"))), ""))
    fresh = [next((l for l in subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "--det", "tests"],
             cwd=root, capture_output=True, text=True).stdout.splitlines() if l.startswith("VALUE")), "-") for _ in range(2)]
    print(f"{name}: cached runs {vals} | fresh --det {fresh} | {summ[-1][:60]}")
    shutil.rmtree(root)
