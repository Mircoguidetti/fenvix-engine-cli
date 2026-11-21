import sys; sys.path.insert(0, sys.argv[1]); from harness import scenario
VIC = "def test_victim():\n    try:\n        with open('flag.txt') as f:\n            assert f.read() != 'bad'\n    except FileNotFoundError:\n        pass\n"
A = "import subprocess, sys\n\ndef test_a():\n    subprocess.run([sys.executable, 'script.py'], check=True)\n"
scenario("C7 PY-08: earlier test's child runs script.py; only script.py changes (good -> bad)",
  {"script.py": "open('flag.txt','w').write('good')\n", "tests/test_a.py": A, "tests/test_b.py": VIC},
  {"script.py": "open('flag.txt','w').write('bad')\n"})
scenario("C8 PY-08: in-process write, same test file content change only in data it copies",
  {"src.txt": "good", "tests/test_a.py": "def test_a():\n    open('flag.txt','w').write(open('src.txt').read())\n", "tests/test_b.py": VIC},
  {"src.txt": "bad"})
