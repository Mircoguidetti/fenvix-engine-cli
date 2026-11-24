"""ENV_PATTERNS: a refused connection to a local service (127.x.x.x, localhost) names this container; a refused
connection to another host does not. `::1` is matched by the IPv6 loopback pattern that was already there."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify  # noqa: E402


def test_local_econnrefused_is_env():
    for msg in ("Error: connect ECONNREFUSED 127.0.0.1:5432",
                "connect ECONNREFUSED 127.0.0.53:6379",
                "Error: connect ECONNREFUSED localhost:8080"):
        assert classify.env_cause(msg) == "a local service (127.0.0.1/localhost) is not running in this container", msg


def test_ipv6_loopback_still_matched_by_the_existing_pattern():
    assert classify.env_cause("Error: connect ECONNREFUSED ::1:5432") == "no IPv6 loopback (::1) in this container"


def test_non_local_econnrefused_is_not_env():
    for msg in ("Error: connect ECONNREFUSED 10.0.0.7:5432",
                "connect ECONNREFUSED 192.168.1.20:443",
                "connect ECONNREFUSED 128.0.0.1:80",
                "Error: connect ECONNREFUSED db.internal:5432",
                "connect ECONNREFUSED localhostname.example:80"):
        assert classify.env_cause(msg) is None, msg


def test_no_message_is_not_env():
    assert classify.env_cause("") is None and classify.env_cause(None) is None
