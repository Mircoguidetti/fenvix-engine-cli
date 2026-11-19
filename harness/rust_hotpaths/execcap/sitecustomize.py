"""Profiling aid (harness only): with ``DETPY_EXEC_CAPTURE=path`` set, detpy's re-exec writes the command line and
environment it would exec to ``path`` and exits, so a profiler can launch that single process itself."""
import os

_out = os.environ.get("DETPY_EXEC_CAPTURE")
if _out:
    import json

    def _execve(path, argv, env):
        with open(_out, "w") as fh:
            json.dump({"path": path, "argv": list(argv), "env": dict(env)}, fh)
        os._exit(0)

    os.execve = _execve
