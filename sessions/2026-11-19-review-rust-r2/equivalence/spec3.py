import os
FILES = {
    "pkg/__init__.py": "",
    "pkg/res.txt": "r\n",
    "pkg/helper.py": "import os\nCFG = open(os.path.join(os.path.dirname(__file__), 'res.txt')).read()\nENV = os.environ.get('R17_IMP')\n",
    "test_t.py": r'''
        import os, time, socket, sqlite3, inspect, threading, importlib.resources, datetime, locale
        from pathlib import Path
        HERE = Path(__file__).parent
        from pkg import helper

        def test_tz_name():
            assert time.tzname

        def test_localtime_str():
            assert time.strftime("%Z %z", time.localtime())

        def test_dt_astimezone():
            assert datetime.datetime.now().astimezone().tzinfo

        def test_locale_conv():
            assert locale.localeconv() is not None

        def test_dns_localhost():
            socket.getaddrinfo("localhost", 80)

        def test_dns_numeric():
            socket.getaddrinfo("127.0.0.1", 80)

        def test_sql_param():
            c = sqlite3.connect(":memory:")
            assert c.execute("select date(?)", ("now",)).fetchone()

        def test_getsource():
            assert "helper" in inspect.getsource(helper)

        def test_resources():
            assert importlib.resources.files("pkg").joinpath("res.txt").read_text()

        def test_thread_env():
            out = []
            t = threading.Thread(target=lambda: out.append(os.environ.get("R17_THR")))
            t.start(); t.join()

        def test_helper_import():
            assert helper.CFG

        def test_env_write():
            os.environ["R17_SET"] = "1"
            assert os.environ["R17_SET"] == "1"
            del os.environ["R17_SET"]
        ''',
    "test_u.py": """
        from pkg import helper
        def test_other():
            assert helper.ENV is None or helper.ENV
        """,
}

def m(root):
    (root / "pkg" / "res.txt").write_text("r2\n")

STEPS = [{"env": {"TZ": "UTC", "LANG": "C.UTF-8"}},
         {"env": {"TZ": "UTC", "LANG": "C.UTF-8"}},
         {"env": {"TZ": "Europe/Rome", "LANG": "C.UTF-8", "R17_THR": "1", "R17_IMP": "x"}},
         {"env": {"TZ": "Europe/Rome", "LANG": "C.UTF-8", "R17_THR": "1", "R17_IMP": "x"}, "mutate": m},
         {"env": {"TZ": "Europe/Rome", "LANG": "C.UTF-8", "R17_THR": "1", "R17_IMP": "x"}}]
