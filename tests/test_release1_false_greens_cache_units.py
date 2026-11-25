"""Unit tests of the Python cache fixes of spec "false greens on release-1" (Phase A-fix), one per channel family,
at the layer where each fix lives. The end-to-end proof of each is its R-056 attack test
(tests/test_review_r056_pycache.py, W3 W4 W5 W8), which failed before the fix.

W3 and W4 patch process-wide state (``posix``, ``os.environ``), so they run in a child interpreter against a stub
capture: what is asserted is what the patched callables report to the capture, nothing else.
"""
import json
import os
import random
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the cache gates run on Linux")


def _child(code, where):
    """Run ``code`` from a file in ``where`` (a project's own file: user code for the capture's frame rule)."""
    script = where / "user_code.py"
    script.write_text(textwrap.dedent(code))
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120, cwd=where)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_w3_posix_stat_lstat_access_are_recorded_and_import_probes_are_not(tmp_path):
    """protects=a direct ``posix.stat`` / ``lstat`` / ``access`` from user code reaches the capture's stat record
    (``_proof.Capture._patch_stat``), and a call from the import machinery does not; fails_when=``posix`` keeps the
    unwrapped builtins (release-1 6e79a62c: nothing recorded) or the import system's probes become test inputs;
    no_claim=what the capture does with the record (the Rust CaptureCore; end to end: the R-056 W3 attack tests).
    The capture is a stub with the methods the wrapper calls."""
    (tmp_path / "data.txt").write_text("abcd")
    out = _child(f"""
        import json, os, posix, sys
        sys.path.insert(0, {repr(str(tmp_path))})
        from detpy import _proof

        class Stub:
            def __init__(self):
                self.calls = []
                self._in_stat = False
            def stat_check(self, path, *a):
                self.calls.append(os.fsdecode(os.fspath(path)))
            def fields_check(self, *a): pass
            def time_check(self, *a): pass
            def flag(self, *a): pass
            def _cur(self): return 0

        cap = Stub()
        keep = [posix.stat]  # in a list: the capture rebinds module-level references to the builtin (LIMITS K3)
        _proof.Capture._patch_stat(cap)
        p = {repr(str(tmp_path / "data.txt"))}
        size = posix.stat(p).st_size
        posix.lstat(p)
        posix.access(p, posix.F_OK)
        user = list(cap.calls)
        cap.calls.clear()
        # the import system's own probe: a frame whose module is importlib._bootstrap_external
        exec("posix.stat(p)", {{"__name__": "importlib._bootstrap_external", "posix": posix, "p": p}})
        machinery = list(cap.calls)
        wrapped = posix.stat is not keep[0]
        for obj, name, v in reversed(cap._stat_saved):
            setattr(obj, name, v)
        print(json.dumps({{"user": user, "machinery": machinery, "size": size, "wrapped": wrapped,
                          "restored": posix.stat is keep[0]}}))
    """, tmp_path)
    p = str(tmp_path / "data.txt")
    assert out["wrapped"] and out["restored"]
    assert out["size"] == 4, "the real builtin answers"
    assert out["user"] == [p, p, p], out
    assert out["machinery"] == [], out


def test_w4_reads_through_posix_environ_are_noted_like_os_environ(tmp_path):
    """protects=a read of ``posix.environ`` (bytes keys: get, [], in, iteration) is noted to the cache's environment
    record (``_proof._patch_posix_environ`` -> ``_note_env``), and ``os.environ`` keeps sharing the same dict;
    fails_when=``posix.environ`` stays the plain dict (release-1 6e79a62c: PWD read that way is in no key and no
    record) or the patch splits ``os.environ._data`` from ``posix.environ`` (a write through one not seen by the other);
    no_claim=the frame rule of ``_note_env`` (Rust: user reads only; end to end: the R-056 W4 attack test).
    ``_note_env`` is replaced by a list."""
    out = _child("""
        import json, os, posix
        from detpy import _proof

        noted = []
        _proof._note_env = noted.append
        _proof._patch_posix_environ()
        posix.environ.get(b"PWD")
        posix.environ[b"PATH"]
        b"HOME" in posix.environ
        list(posix.environ)
        same = os.environ._data is posix.environ and os.environb._data is posix.environ
        os.environ["R1FG_W4"] = "x"
        seen = posix.environ.get(b"R1FG_W4")
        print(json.dumps({"noted": [n if isinstance(n, str) else n.decode() for n in noted], "same": same,
                          "seen": seen.decode() if seen else None}))
    """, tmp_path)
    assert out["same"] and out["seen"] == "x"
    for name in ("PWD", "PATH", "HOME", "*"):
        assert name in out["noted"], out


def test_w5_the_kernel_is_part_of_the_process_key(monkeypatch):
    """protects=``process_identity`` (part of every test's key) holds the kernel (uname sysname, release, version,
    machine) and changes when the release does; fails_when=the release is in no key (release-1 6e79a62c: a cached
    result reused under another kernel, ``platform.release()``); no_claim=the digest of the whole key (Rust)."""
    import posix

    from detpy import _proof

    u = posix.uname()
    before = _proof.process_identity()
    assert before["kernel"] == [u.sysname, u.release, u.version, u.machine]

    class Fake:
        sysname, nodename, release, version, machine = u.sysname, u.nodename, "2.6.40", u.version, u.machine

    monkeypatch.setattr(posix, "uname", lambda: Fake)
    after = _proof.process_identity()
    assert after["kernel"][1] == "2.6.40"
    assert after != before


def test_w8_an_unseeded_c_generator_is_a_gap_and_controlled_ones_are_not():
    """protects=the sensor's W8 rule (``provable._unseeded_c_random``) names the construction of ``_random.Random``
    without a seed (or with None), and of a subclass that does not go through ``random.Random``, as a gap; fails_when=
    it misses the C generator (release-1 6e79a62c: reused while fresh --det runs differ) or flags the generators --det
    seeds (``random.Random``, its subclasses) or a seeded one; no_claim=the gap's effect on the cache (end to end: the
    R-056 W8 attack test) and the sensor's call-event plumbing."""
    import _random

    from detpy import provable

    missing = getattr(sys.monitoring, "MISSING")

    class OwnC(_random.Random):
        pass

    class OwnPy(random.Random):
        pass

    gap = provable._unseeded_c_random
    assert gap(_random.Random, missing) and gap(_random.Random, None) and gap(OwnC, missing)
    assert not gap(_random.Random, 42)
    assert not gap(random.Random, missing) and not gap(OwnPy, missing) and not gap(random.SystemRandom, missing)
    assert not gap(int, missing) and not gap(dict, None)
