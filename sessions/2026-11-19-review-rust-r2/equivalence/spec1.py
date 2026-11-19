import os
from pathlib import Path

FILES = {
    "conftest.py": """
        import os, pytest
        from pathlib import Path
        HERE = Path(__file__).parent

        @pytest.fixture(scope="session")
        def sess_cfg():
            return (HERE / "sess.txt").read_text() + os.environ.get("R17_SESS", "-")

        @pytest.fixture(scope="package")
        def pkg_cfg():
            return (HERE / "pkgfx.txt").read_text()
        """,
    "sess.txt": "s\n",
    "pkgfx.txt": "p\n",
    "uni/é.txt": "e-acute\n",
    "data.txt": "d\n",
    "linkdir_target/x.txt": "x\n",
    "test_paths.py": r'''
        import os, sys, locale, time
        from pathlib import Path
        import pytest
        HERE = Path(__file__).parent

        class TestC:
            @pytest.fixture(scope="class")
            def cls_cfg(self):
                return (HERE / "data.txt").read_text()

            def test_class_fx(self, cls_cfg, sess_cfg, pkg_cfg):
                assert cls_cfg and sess_cfg and pkg_cfg

        def test_unicode_nfc():
            assert (HERE / "uni" / "é.txt").read_text()

        def test_unicode_nfd():
            p = str(HERE / "uni" / "é.txt")
            try:
                open(p).read()
            except FileNotFoundError:
                pass

        def test_surrogate_name():
            p = os.path.join(os.fsencode(HERE), b"bad\xff.txt")
            try:
                open(p).read()
            except FileNotFoundError:
                pass

        def test_surrogate_str_name():
            p = str(HERE) + "/bad\udcff2.txt"
            try:
                open(p).read()
            except FileNotFoundError:
                pass

        def test_bytes_path():
            assert open(os.path.join(os.fsencode(HERE), b"data.txt"), "rb").read()
            assert os.listdir(os.fsencode(HERE / "uni"))

        def test_double_slash():
            p = "/" + str(HERE) + "//./data.txt"
            assert open(p).read()

        def test_dotdot_through_link():
            # linkdir -> linkdir_target ; linkdir/../data.txt : normpath vs kernel differ
            p = str(HERE / "linkdir") + "/../data.txt"
            assert open(p).read()

        def test_symlink_file():
            assert (HERE / "lnk.txt").read_text()

        def test_listing_link_dir():
            assert os.listdir(HERE / "linkdir")

        def test_fspath_bytes():
            class P:
                def __fspath__(self):
                    return os.fsencode(HERE / "data.txt")
            assert open(P(), "rb").read()

        def test_env_variants():
            os.getenv("R17_A")
            os.environ.get("R17_B")
            "R17_C" in os.environ
            os.environb.get(b"R17_D")
            os.environ.setdefault("R17_E", "1")
            os.environ.pop("R17_F", None)

        def test_env_copy():
            assert os.environ.copy()

        def test_env_nonutf8():
            v = os.environb.get(b"R17_BYTES")
            w = os.environ.get("R17_BYTES")

        def test_env_unicode_name():
            os.environ.get("R17_É")

        def test_tz():
            os.environ.get("TZ")
            time.tzset()
            assert time.localtime()

        def test_locale():
            try:
                locale.setlocale(locale.LC_ALL, "")
            except locale.Error:
                pass
            assert locale.getlocale()

        def test_zoneinfo():
            import zoneinfo
            try:
                z = zoneinfo.ZoneInfo("Europe/Rome")
            except Exception:
                z = None

        def test_open_fd():
            fd = os.open(HERE / "data.txt", os.O_RDONLY)
            with open(fd) as fh:
                fh.read()

        def test_dir_fd():
            d = os.open(HERE, os.O_RDONLY)
            try:
                fd = os.open("data.txt", os.O_RDONLY, dir_fd=d)
                os.close(fd)
            finally:
                os.close(d)

        def test_stat_mtime():
            assert os.path.getmtime(HERE / "data.txt") > 0
        ''',
    "sub/__init__.py": "",
    "sub/test_pkg.py": """
        def test_pkg_fx(pkg_cfg):
            assert pkg_cfg
        """,
}


def setup(root):
    os.symlink("linkdir_target", root / "linkdir")
    os.symlink("data.txt", root / "lnk.txt")
    (Path(os.fsencode(root)) .joinpath(b"bad\xff.txt")).write_bytes(b"bad\n") if False else None
    with open(os.path.join(os.fsencode(root), b"bad\xff.txt"), "wb") as fh:
        fh.write(b"bad\n")


def m2(root):
    (root / "uni" / "é.txt").write_text("changed\n")
    os.unlink(root / "lnk.txt")
    (root / "other.txt").write_text("o\n")
    os.symlink("other.txt", root / "lnk.txt")
    (root / "linkdir_target" / "y.txt").write_text("y\n")
    with open(os.path.join(os.fsencode(root), b"bad\xff.txt"), "wb") as fh:
        fh.write(b"bad2\n")


ENV = {"R17_BYTES": "caf\udce9", "R17_SESS": "a"}
STEPS = [
    {"env": ENV},
    {"env": ENV},
    {"env": {**ENV, "R17_A": "x", "R17_É": "y"}, "mutate": m2},
    {"env": {**ENV, "R17_A": "x", "R17_É": "y"}},
]
