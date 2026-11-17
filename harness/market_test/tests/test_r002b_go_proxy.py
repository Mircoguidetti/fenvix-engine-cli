"""R-002b: the v3 Go network guard (R-002 error 3 fix) does not fire when the external service is reached through
an HTTP(S) proxy on loopback (HTTPS_PROXY=http://127.0.0.1:<port>, as in this container and in many corporate CI
runners). The test needs github.com to answer; the walker's Go closure still reuses its PASS.

    python3 -m pytest -q harness/market_test/tests/test_r002b_go_proxy.py   (copied from review R-002b)
Needs git, strace, go and a loopback HTTPS proxy in the environment (skipped otherwise).
"""
import os, subprocess, sys
from pathlib import Path
import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
import walk  # noqa: E402

GO_HTTP_TEST = """package httppkg

import (
\t"net/http"
\t"testing"
)

// like terraform internal/cloud (tfe.NewClient -> app.terraform.io): the test needs an external HTTPS service
func TestExternalService(t *testing.T) {
\tresp, err := http.Get("https://github.com/")
\tif err != nil {
\t\tt.Fatal(err)
\t}
\tresp.Body.Close()
}
"""


def g(src, *a):
    return subprocess.run(["git", *a], cwd=src, check=True, capture_output=True, text=True).stdout.strip()


proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""


@pytest.mark.skipif("127.0.0.1" not in proxy and "localhost" not in proxy, reason="needs a loopback HTTPS proxy")
def test_go_external_service_through_loopback_proxy_is_never_skipped(tmp_path):
    src = tmp_path / "w" / "src"
    (src / "httppkg").mkdir(parents=True)
    (src / "httppkg" / "httppkg_test.go").write_text(GO_HTTP_TEST)
    (src / "go.mod").write_text("module example.com/r002b\n\ngo 1.22\n")
    g(src, "init", "-q", "-b", "main"); g(src, "config", "user.email", "r@x"); g(src, "config", "user.name", "r")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c0")
    c0 = g(src, "rev-parse", "HEAD")
    (src / "README").write_text("unrelated\n")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c1")
    c1 = g(src, "rev-parse", "HEAD")
    spec = {"name": "r002b-go", "lang": "go", "seq": {"kind": "list", "commits": [c0, c1]},
            "units": {"patterns": ["./..."]}, "install_files": ["go.mod"], "verify": 0.0}
    w = walk.Walker(spec, tmp_path / "w", tmp_path / "out.json", 0, 1, 30, "r002b")
    w.push = False
    os.environ.setdefault("GOFLAGS", "-mod=mod")
    w.walk()
    info = w.result["unit_info"]["example.com/r002b/httppkg"]
    assert info["net"] >= 1                                   # it did connect (to the proxy)
    # the walker writes only units some rule reruns: absent = every rule skipped it
    dec = w.result["transitions"][0]["decisions"].get("example.com/r002b/httppkg", {"go-cache": None, "closure": None})
    assert dec.get("go-cache", "absent") is None              # go test cache hit at c1: the recorded run PASSED
    assert dec.get("closure") == "network", (
        f"Go closure reuses the PASS of a test that needs github.com (connects only to the loopback proxy: "
        f"net={info['net']} net_ext={info['net_ext']}); decision={dec}")


TEST_HTTP_PY = ("import urllib.error, urllib.request\n\ndef test_external_service():\n"
                "    try:\n        urllib.request.urlopen('https://github.com/', timeout=20).close()\n"
                "    except urllib.error.HTTPError:\n        pass  # the service answered\n")


@pytest.mark.skipif("127.0.0.1" not in proxy and "localhost" not in proxy, reason="needs a loopback HTTPS proxy")
def test_pytest_external_service_through_loopback_proxy_is_never_skipped(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_r002_capture as t
    w, c0, c1 = t.make_walker(tmp_path)
    (w.src / "tests" / "test_http.py").write_text(TEST_HTTP_PY)
    g(w.src, "add", "-A"); g(w.src, "commit", "-qm", "c2: add a test that needs github.com")
    c2 = g(w.src, "rev-parse", "HEAD")
    w.checkout(c2)
    rec = w.run_unit("tests/test_http.py"); rec["sha"] = c2
    assert rec["code"] == 0, rec.get("tail")
    assert rec["deps"]["net"] >= 1
    decision, _ = w.decide("tests/test_http.py", rec, c2, [c0, c1, c2])
    assert decision["closure"] == "network", (
        f"closure reuses the PASS of a test that needs github.com via the loopback proxy "
        f"(net={rec['deps']['net']} net_ext={rec['deps']['net_ext']}): {decision}")


def test_proxy_connect_is_external_without_network():
    """Unit check of the R-002b guard (no proxy or network needed): upper and lower case, localhost, default ports."""
    import strace_deps as sd
    net = [["127.0.0.1", 3128], ["127.0.0.1", 5432], ["::1", 8080], ["127.0.0.53", 53]]
    assert sd.external(net) == [["127.0.0.53", 53]]
    assert sd.external(net, {"HTTPS_PROXY": "http://127.0.0.1:3128"}) == [["127.0.0.1", 3128], ["127.0.0.53", 53]]
    assert sd.external(net, {"http_proxy": "http://localhost:8080"}) == [["::1", 8080], ["127.0.0.53", 53]]
    assert sd.external(net, {"all_proxy": "socks5://user:pw@127.0.0.1:3128"})[0] == ["127.0.0.1", 3128]
    assert sd.external([["127.0.0.1", 80]], {"HTTP_PROXY": "127.0.0.1"}) == [["127.0.0.1", 80]]
    assert sd.external(net, {"HTTPS_PROXY": "http://10.0.0.5:3128"}) == [["127.0.0.53", 53]]
