"""The 20-test synthetic project of P0: one polluter/victim pair, one file writer/reader pair (the file outside the
repository), one fixed-port pair, plus plain tests.

usage: python -m harness.parallel_proof.synth DIR [--shared PATH] [--port N]"""

from __future__ import annotations

import argparse
import os
import tempfile
import textwrap

FILES = {
    "pytest.ini": "[pytest]\n",
    "pkg/__init__.py": "",
    "pkg/state.py": "FLAG = False\n",
    "tests/test_pollute.py": """
        import random
        from pkg import state
        def test_polluter():
            state.FLAG = True      # left behind for later tests in the same process
        def test_p2(): random.random()
        def test_p3(): pass
        def test_p4(): random.randint(0, 3)
        """,
    "tests/test_victim.py": """
        import random, time
        from pkg import state
        def test_victim():
            # its events depend on whether the polluter ran earlier in this process
            if state.FLAG:
                random.random()
            else:
                time.time()
        def test_v2(): pass
        def test_v3(): time.time()
        def test_v4(): pass
        """,
    "tests/test_writer.py": """
        import pathlib
        SHARED = pathlib.Path({shared!r})
        def test_writer():
            SHARED.write_text((pathlib.Path(__file__).parent / "value.txt").read_text())
        def test_w2(): pass
        def test_w3(): pass
        def test_w4(): pass
        """,
    "tests/test_reader.py": """
        import pathlib
        SHARED = pathlib.Path({shared!r})
        def test_reader():
            text = SHARED.read_text() if SHARED.exists() else "x"
            assert text.strip() == "x"
        def test_r2(): pass
        def test_r3(): pass
        def test_r4(): pass
        """,
    "tests/test_port.py": """
        import socket
        PORT = {port}
        def _bind():
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", PORT))
            s.listen()
            s.close()
        def test_port_1(): _bind()
        def test_port_2(): _bind()
        def test_o3(): pass
        def test_o4(): pass
        """,
    "tests/value.txt": "x\n",
}


def write(root: str, shared: str | None = None, port: int = 47321) -> str:
    shared = shared or os.path.join(tempfile.gettempdir(), f"detpy-synth-shared-{os.getpid()}.txt")
    for name, text in FILES.items():
        p = os.path.join(root, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(textwrap.dedent(text).replace("{shared!r}", repr(shared)).replace("{port}", str(port)))
    return shared


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--shared")
    ap.add_argument("--port", type=int, default=47321)
    a = ap.parse_args(argv)
    print(write(a.dir, a.shared, a.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
