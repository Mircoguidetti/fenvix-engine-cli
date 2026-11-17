"""R-002c: variants of the R-002b loopback-proxy network guard (fix aac1b11).

Each test runs a pytest unit that needs https://github.com/ through the loopback proxy of this container, written
in a different way (lower case only, ALL_PROXY only, the name "localhost", another /etc/hosts name for 127.0.0.1),
records it with the walker under strace and asks ``decide()`` whether ``closure`` would reuse the PASS.

    WT=<worktree> python3 -m pytest -q test_r002c_proxy_variants.py
Needs git, strace, uv, curl and a loopback HTTPS proxy in the environment (skipped otherwise).
"""
import os, socket, subprocess, sys
from pathlib import Path
from urllib.parse import urlsplit
import pytest

WT = Path(os.environ.get("WT", str(Path(__file__).resolve().parents[3])))
sys.path.insert(0, str(WT / "harness" / "market_test"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_r002_capture as t  # noqa: E402

t.WT = WT

PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
PORT = urlsplit(PROXY).port if PROXY else None
PROXY_VARS = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"]


def loopback_alias():
    """A name other than localhost that /etc/hosts maps to a loopback address (Debian maps the machine name to
    127.0.1.1; this container maps "runsc" and "vm" to 127.0.0.1)."""
    for line in Path("/etc/hosts").read_text().splitlines():
        f = line.split("#")[0].split()
        if len(f) >= 2 and f[0].startswith("127."):
            for name in f[1:]:
                if name != "localhost" and not name.startswith("localhost"):
                    return name
    return None


needs_proxy = pytest.mark.skipif(not PORT or urlsplit(PROXY).hostname not in ("127.0.0.1", "localhost"),
                                 reason="needs a loopback HTTPS proxy")

TEST_URLLIB = ("import urllib.error, urllib.request\n\ndef test_external_service():\n"
               "    try:\n        urllib.request.urlopen('https://github.com/', timeout=20).close()\n"
               "    except urllib.error.HTTPError:\n        pass  # the service answered\n")
# curl honours ALL_PROXY (urllib and Go do not)
TEST_CURL = ("import subprocess\n\ndef test_external_service():\n"
             "    subprocess.run(['curl', '-sS', '-o', '/dev/null', '--max-time', '20', 'https://github.com/'],"
             " check=True)\n")


def run_variant(tmp_path, monkeypatch, env, body):
    for k in PROXY_VARS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    w, c0, c1 = t.make_walker(tmp_path)
    (w.src / "tests" / "test_http.py").write_text(body)
    t.g(w.src, "add", "-A"); t.g(w.src, "commit", "-qm", "c2: a test that needs github.com")
    c2 = t.g(w.src, "rev-parse", "HEAD")
    w.checkout(c2)
    rec = w.run_unit("tests/test_http.py"); rec["sha"] = c2
    assert rec["code"] == 0, rec.get("tail")                 # it really reached github.com through the proxy
    assert rec["deps"]["net"] >= 1
    decision, _ = w.decide("tests/test_http.py", rec, c2, [c0, c1, c2])
    assert decision["closure"] == "network", (
        f"closure reuses the PASS of a test that needs github.com via {env} "
        f"(net={rec['deps']['net']} net_ext={rec['deps']['net_ext']}): {decision}")


@needs_proxy
def test_lowercase_https_proxy_only(tmp_path, monkeypatch):
    run_variant(tmp_path, monkeypatch, {"https_proxy": f"http://127.0.0.1:{PORT}"}, TEST_URLLIB)


@needs_proxy
def test_localhost_name(tmp_path, monkeypatch):
    run_variant(tmp_path, monkeypatch, {"HTTPS_PROXY": f"http://localhost:{PORT}"}, TEST_URLLIB)


@needs_proxy
def test_all_proxy_only_curl(tmp_path, monkeypatch):
    run_variant(tmp_path, monkeypatch, {"ALL_PROXY": f"http://127.0.0.1:{PORT}"}, TEST_CURL)


@needs_proxy
def test_no_proxy_does_not_hide_the_proxy(tmp_path, monkeypatch):
    # NO_PROXY exempts loopback (as in this container); github.com still goes through the proxy
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,127.0.0.0/8")
    run_variant(tmp_path, monkeypatch, {"HTTPS_PROXY": f"http://127.0.0.1:{PORT}"}, TEST_URLLIB)


ALIAS = loopback_alias()


@needs_proxy
@pytest.mark.skipif(not ALIAS, reason="no non-localhost loopback name in /etc/hosts")
def test_proxy_named_by_another_loopback_hostname(tmp_path, monkeypatch):
    """FAILS on e939c1b: proxy_endpoints() drops any proxy host name other than "localhost" as "a named non-local
    host: its connect is already external". A name /etc/hosts maps to loopback is not external: the unit
    connects only to 127.0.0.1:<port>, net_ext = 0 and closure reuses the PASS."""
    assert socket.gethostbyname(ALIAS).startswith("127.")
    run_variant(tmp_path, monkeypatch, {"HTTPS_PROXY": f"http://{ALIAS}:{PORT}"}, TEST_URLLIB)
