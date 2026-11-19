import os
from pathlib import Path

FILES = {
    "pytest.ini": "[pytest]\naddopts = --doctest-modules --doctest-glob=*.rst\n",
    "pkg/__init__.py": "",
    "pkg/mod.py": '''
        import os
        def f(x):
            """
            >>> f(2)
            4
            """
            return x * 2
        ''',
    "pkg/late.py": "def g():\n    return 1\n",
    "doc.rst": ">>> 1 + 1\n2\n",
    "in.txt": "in\n",
    "child_in.txt": "child\n",
    "test_w.py": r'''
        import os, shutil, tempfile, threading, subprocess, sys
        from pathlib import Path
        HERE = Path(__file__).parent

        def test_a_writer():
            (HERE / "shared.txt").write_text("w\n")
            os.makedirs(HERE / "made", exist_ok=True)
            (HERE / "made" / "f.txt").write_text("f")

        def test_b_reader():
            assert (HERE / "shared.txt").read_text()

        def test_c_lister():
            assert os.listdir(HERE / "made")

        def test_d_excl_open():
            p = HERE / "lock.pid"
            try:
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                os.unlink(p)
            except FileExistsError:
                pass

        def test_e_mkstemp():
            fd, name = tempfile.mkstemp(dir=HERE, prefix="r17")
            os.close(fd)
            os.unlink(name)

        def test_f_mode_x():
            p = HERE / "x.out"
            with open(p, "x") as fh:
                fh.write("x")
            os.unlink(p)

        def test_g_thread_read():
            out = []
            t = threading.Thread(target=lambda: out.append((HERE / "in.txt").read_text()))
            t.start(); t.join()
            assert out

        def test_h_child_reads():
            r = subprocess.run([sys.executable, "-c", "print(open(%r).read())" % str(HERE / "child_in.txt")],
                               capture_output=True, text=True)
            assert r.returncode == 0

        def test_i_child_shell_cat():
            r = subprocess.run("cat child_in.txt", shell=True, cwd=HERE, capture_output=True)
            assert r.returncode == 0

        def test_j_rename_then_read():
            (HERE / "tmp1.txt").write_text("1")
            os.replace(HERE / "tmp1.txt", HERE / "tmp2.txt")
            assert (HERE / "tmp2.txt").read_text()
            os.remove(HERE / "tmp2.txt")

        def test_l_import_late():
            from pkg import late
            assert late.g() == 1

        def test_m_append():
            with open(HERE / "app.log", "a") as fh:
                fh.write("x\n")

        def test_n_read_appended():
            assert (HERE / "app.log").exists()
        ''',
}


def m3(root):
    (root / "child_in.txt").write_text("child2\n")
    (root / "in.txt").write_text("in2\n")


STEPS = [{}, {}, {"mutate": m3}, {}]
