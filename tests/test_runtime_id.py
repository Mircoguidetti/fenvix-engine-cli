"""Runtime identity (detpy.runtime_id): equal on equivalent machines, different whenever behaviour can differ.

Every identity here is computed in a separate interpreter process, as the engine computes it at the start of a
session. "Equivalent machine" is played by copies of the same interpreter and the same packages at other paths,
installed by different installers (different RECORD, INSTALLER, direct_url.json, bytecode), and by the same libc
loaded from another directory. The changes that must change the identity are real: another patch release of
Python, a libc with other bytes actually loaded by the process, another version of an installed package, the same
version with one file changed, a changed standard-library file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

import pytest

import detpy

DETPY_PARENT = str(Path(detpy.__file__).resolve().parents[1])
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ELF/glibc identity tested on Linux")


# ---------------------------------------------------------------------------------------------------------------------
def identity(python: str, root: Path, env_extra: dict | None = None) -> dict:
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": DETPY_PARENT, "FENVIX_RUNTIME_MEMO": "off", "LANG": "C.UTF-8",
           "HOME": str(root)}
    env.update(env_extra or {})
    code = ("import json, sys; from detpy import runtime_id; d = runtime_id.describe(sys.argv[1]); "
            "m = [l.split()[-1] for l in open('/proc/self/maps') if 'libc.so' in l or 'libc-' in l]; "
            "d['details']['mapped_libc'] = sorted(set(m)); print(json.dumps(d))")
    r = subprocess.run([python, "-c", code, str(root)], cwd=root, env=env, capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def changed(a: dict, b: dict) -> list[str]:
    return sorted(k for k in a if k not in ("digest", "details") and a[k] != b.get(k))


def make_wheel(out: Path, name: str, version: str, files: dict[str, str]) -> Path:
    dist = f"{name}-{version}.dist-info"
    entries = {k: v.encode() for k, v in files.items()}
    entries[f"{dist}/METADATA"] = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
    entries[f"{dist}/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: fenvix-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    rec = []
    for k, v in entries.items():
        h = base64.urlsafe_b64encode(hashlib.sha256(v).digest()).rstrip(b"=").decode()
        rec.append(f"{k},sha256={h},{len(v)}")
    rec.append(f"{dist}/RECORD,,")
    entries[f"{dist}/RECORD"] = ("\n".join(rec) + "\n").encode()
    out.mkdir(parents=True, exist_ok=True)
    whl = out / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)
    return whl


def venv(path: Path, base: str | None = None) -> str:
    subprocess.run([base or sys.executable, "-m", "venv", "--without-pip", str(path)], check=True, timeout=120)
    return str(path / "bin" / "python")


def site_packages(py: str) -> Path:
    out = subprocess.run([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], capture_output=True,
                         text=True, check=True).stdout.strip()
    return Path(out)


def install(py: str, whl: Path, installer: str, compile_pyc: bool = False) -> None:
    """A minimal wheel installer that writes its own INSTALLER, direct_url.json and RECORD (with or without bytecode
    entries), as different real installers do."""
    sp = site_packages(py)
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
        z.extractall(sp)
    dist = next(n.split("/")[0] for n in names if n.endswith(".dist-info/METADATA"))
    (sp / dist / "INSTALLER").write_text(installer + "\n")
    (sp / dist / "direct_url.json").write_text(json.dumps({"url": whl.resolve().as_uri(), "archive_info": {}}))
    rec = (sp / dist / "RECORD").read_text().splitlines()
    rec += [f"{dist}/INSTALLER,,", f"{dist}/direct_url.json,,"]
    if compile_pyc:
        import py_compile

        for n in names:
            if n.endswith(".py"):
                c = py_compile.compile(str(sp / n), doraise=True)
                rec.append(f"{os.path.relpath(c, sp)},,")
    (sp / dist / "RECORD").write_text("\n".join(rec) + "\n")


@pytest.fixture
def wheels(tmp_path):
    w = tmp_path / "wheels"
    return {
        "1.0": make_wheel(w / "a", "fenvixdemo", "1.0", {"fenvixdemo/__init__.py": "VALUE = 1\n"}),
        "1.0-copy": make_wheel(w / "b", "fenvixdemo", "1.0", {"fenvixdemo/__init__.py": "VALUE = 1\n"}),
        "1.1": make_wheel(w / "c", "fenvixdemo", "1.1", {"fenvixdemo/__init__.py": "VALUE = 1\n"}),
        "1.0-patched": make_wheel(w / "d", "fenvixdemo", "1.0", {"fenvixdemo/__init__.py": "VALUE = 2\n"}),
    }


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "project"
    r.mkdir()
    return r


# ---------------------------------------------------------------------------------------------------------------------
def test_same_packages_at_other_paths_by_other_installers_give_the_same_identity(tmp_path, wheels, root):
    """Two machines from one image: same interpreter, same packages, different venv paths, different installers
    (RECORD with and without bytecode entries, another INSTALLER, direct_url.json naming another wheel path)."""
    py1 = venv(tmp_path / "machine-1" / "venv")
    py2 = venv(tmp_path / "machine-2" / "work" / "venv")
    install(py1, wheels["1.0"], "uv")
    install(py2, wheels["1.0-copy"], "pip", compile_pyc=True)
    a, b = identity(py1, root), identity(py2, root)
    assert a["digest"] == b["digest"], changed(a, b)
    assert a["details"]["dist_list"] == b["details"]["dist_list"]
    # the RECORD files really differ: an identity built on RECORD bytes (the previous one) would differ
    r1 = (site_packages(py1) / "fenvixdemo-1.0.dist-info" / "RECORD").read_bytes()
    r2 = (site_packages(py2) / "fenvixdemo-1.0.dist-info" / "RECORD").read_bytes()
    assert r1 != r2


def test_another_version_of_an_installed_package_changes_the_identity(tmp_path, wheels, root):
    py1 = venv(tmp_path / "v1")
    py2 = venv(tmp_path / "v2")
    install(py1, wheels["1.0"], "uv")
    install(py2, wheels["1.1"], "uv")
    a, b = identity(py1, root), identity(py2, root)
    assert a["digest"] != b["digest"]
    assert changed(a, b) == ["distributions", "site_tree"]


def test_same_version_with_a_changed_file_changes_the_identity(tmp_path, wheels, root):
    py1 = venv(tmp_path / "v1")
    py2 = venv(tmp_path / "v2")
    install(py1, wheels["1.0"], "uv")
    install(py2, wheels["1.0-patched"], "uv")
    a, b = identity(py1, root), identity(py2, root)
    assert changed(a, b) == ["distributions", "site_tree"]
    # and an installed file edited in place (RECORD untouched) is seen too
    py3 = venv(tmp_path / "v3")
    install(py3, wheels["1.0"], "uv")
    (site_packages(py3) / "fenvixdemo" / "__init__.py").write_text("VALUE = 3\n")
    assert changed(a, identity(py3, root)) == ["distributions", "site_tree"]


def test_a_loose_pth_file_in_site_packages_changes_the_identity(tmp_path, root):
    py1 = venv(tmp_path / "v1")
    py2 = venv(tmp_path / "v2")
    (site_packages(py2) / "zz_startup.pth").write_text("import os\n")
    assert changed(identity(py1, root), identity(py2, root)) == ["site_tree"]


def _python_patch_pair() -> tuple[str, str] | None:
    """Two installed CPython interpreters with the same minor version and different patch versions."""
    seen: dict[tuple, dict[str, str]] = {}
    cands = {sys.executable, *(shutil.which(f"python3.{m}") or "" for m in range(9, 16))}
    uv = shutil.which("uv")
    if uv:
        r = subprocess.run([uv, "python", "list", "--only-installed", "--output-format", "json"], capture_output=True,
                           text=True)
        try:
            cands |= {d["path"] for d in json.loads(r.stdout) if d.get("path")}
        except ValueError:
            pass
    for c in sorted(x for x in cands if x):
        r = subprocess.run([c, "-c", "import sys, platform; print(sys.implementation.name, platform.python_version(), "
                               "sys.version_info >= (3, 9), hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled())"],
                           capture_output=True, text=True)
        try:
            impl, ver, ok, ft = r.stdout.split()
        except ValueError:
            continue
        if impl != "cpython" or ok != "True" or ft == "True":
            continue
        major, minor, patch = ver.split(".")[:3]
        seen.setdefault((major, minor), {}).setdefault(patch, c)
    for (_, _), patches in sorted(seen.items(), reverse=True):
        if len(patches) >= 2:
            p = sorted(patches, key=lambda x: int("".join(ch for ch in x if ch.isdigit()) or 0))
            return patches[p[0]], patches[p[-1]]
    return None


def test_another_python_patch_release_changes_the_identity(tmp_path, root):
    pair = _python_patch_pair()
    if pair is None:
        pytest.skip("needs two CPython interpreters of one minor version (e.g. `uv python install 3.13.14`)")
    py1 = venv(tmp_path / "v1", pair[0])
    py2 = venv(tmp_path / "v2", pair[1])
    a, b = identity(py1, root), identity(py2, root)
    assert a["details"]["python_version"] != b["details"]["python_version"]
    assert a["digest"] != b["digest"]
    assert {"python", "executable", "stdlib"} <= set(changed(a, b))


def _relocatable_copy(dest: Path) -> str:
    """A copy of this interpreter (binary, libpython, standard library) under another prefix: the same image
    unpacked at another path."""
    base = Path(sys.base_prefix)
    ver = f"python{sys.version_info[0]}.{sys.version_info[1]}"
    exe = Path(os.path.realpath(sys.executable))
    if not exe.is_relative_to(base):
        exe = base / "bin" / ver
    (dest / "bin").mkdir(parents=True)
    shutil.copy2(exe, dest / "bin" / ver)
    std = Path(sysconfig.get_paths()["stdlib"])
    shutil.copytree(std, dest / "lib" / ver, symlinks=True,
                    ignore=shutil.ignore_patterns("site-packages", "dist-packages", "__pycache__", "test", "tests",
                                                  "idlelib", "tkinter", "turtledemo"))
    (dest / "lib" / ver / "site-packages").mkdir(exist_ok=True)
    for lib in base.glob("lib/libpython*.so*"):
        shutil.copy2(lib, dest / "lib" / lib.name, follow_symlinks=False)
    return str(dest / "bin" / ver)


def test_a_relocated_copy_of_the_interpreter_keeps_the_identity_and_a_changed_stdlib_file_changes_it(tmp_path, root):
    if not sys.base_prefix or sysconfig.get_config_var("PYTHONFRAMEWORK"):
        pytest.skip("framework builds are not relocatable this way")
    py1 = _relocatable_copy(tmp_path / "image-at-a")
    py2 = _relocatable_copy(tmp_path / "somewhere" / "else" / "image-at-b")
    a, b = identity(py1, root), identity(py2, root)
    assert a["details"]["sys_path"] == b["details"]["sys_path"]
    assert a["digest"] == b["digest"], changed(a, b)
    std = Path(py2).parents[1] / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}"
    with open(std / "string" / "__init__.py" if (std / "string").is_dir() else std / "string.py", "a") as fh:
        fh.write("\n# patched\n")
    assert changed(a, identity(py2, root)) == ["stdlib"]


def _loaded_libc() -> Path | None:
    for line in open("/proc/self/maps"):
        p = line.split()[-1]
        if os.path.basename(p).startswith("libc.so") or os.path.basename(p).startswith("libc-"):
            return Path(p)
    return None


def test_libc_is_keyed_on_the_bytes_actually_loaded_not_on_its_path(tmp_path, root):
    libc = _loaded_libc()
    if libc is None:
        pytest.skip("no glibc mapped")
    same, other = tmp_path / "same-libc", tmp_path / "other-libc"
    same.mkdir()
    other.mkdir()
    shutil.copy2(libc, same / "libc.so.6")
    shutil.copy2(libc, other / "libc.so.6")
    with open(other / "libc.so.6", "ab") as fh:  # another build of the same release: other bytes, still loadable
        fh.write(b"\0fenvix-test-other-libc-build\0")
    base = identity(sys.executable, root)
    a = identity(sys.executable, root, {"LD_LIBRARY_PATH": str(same)})
    b = identity(sys.executable, root, {"LD_LIBRARY_PATH": str(other)})
    assert a["details"]["mapped_libc"] == [str(same / "libc.so.6")]
    assert b["details"]["mapped_libc"] == [str(other / "libc.so.6")]
    assert a["digest"] == base["digest"], changed(base, a)  # same bytes from another directory: same identity
    assert b["digest"] != base["digest"]
    assert set(changed(base, b)) == {"libc", "native"}


def test_identity_is_stable_and_memo_does_not_change_it(tmp_path, root):
    memo = tmp_path / "memo.json"
    a = identity(sys.executable, root)
    b = identity(sys.executable, root, {"FENVIX_RUNTIME_MEMO": str(memo)})
    c = identity(sys.executable, root, {"FENVIX_RUNTIME_MEMO": str(memo)})
    assert a["digest"] == b["digest"] == c["digest"]
    assert memo.exists()
    assert b["details"]["hashed_files"] > 0 and c["details"]["hashed_files"] == 0


def test_interpreter_flags_change_the_identity(tmp_path, root):
    base = identity(sys.executable, root)
    env = {"PYTHONOPTIMIZE": "1"}  # asserts are stripped: tests can behave differently
    assert changed(base, identity(sys.executable, root, env)) == ["python"]


def test_project_installed_in_editable_mode_is_not_part_of_the_identity(tmp_path, wheels):
    """The project's own files are per-test inputs; its editable install records its path, so it stays out."""
    root = tmp_path / "proj"
    root.mkdir()
    py = venv(tmp_path / "venv")
    sp = site_packages(py)
    info = sp / "myproj-0.0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: myproj\nVersion: 0.0.1\n")
    (info / "direct_url.json").write_text(json.dumps({"url": root.as_uri(), "dir_info": {"editable": True}}))
    (sp / "_myproj.pth").write_text(str(root) + "\n")
    (info / "RECORD").write_text("myproj-0.0.1.dist-info/METADATA,,\nmyproj-0.0.1.dist-info/RECORD,,\n_myproj.pth,,\n")
    d = identity(py, root)
    assert not any(x.startswith("myproj==") for x in d["details"]["dist_list"])
    # the same project checked out elsewhere (another machine path) gives the same identity
    root2 = tmp_path / "elsewhere" / "proj"
    root2.mkdir(parents=True)
    py2 = venv(tmp_path / "elsewhere" / "venv")
    sp2 = site_packages(py2)
    shutil.copytree(info, sp2 / info.name)
    (sp2 / info.name / "direct_url.json").write_text(json.dumps({"url": root2.as_uri(), "dir_info": {"editable": True}}))
    (sp2 / "_myproj.pth").write_text(str(root2) + "\n")
    assert identity(py2, root2)["digest"] == d["digest"]


def test_time_zone_and_instruction_set_level_are_keyed(tmp_path, root):
    base = identity(sys.executable, root, {"TZ": "UTC"})
    if Path("/usr/share/zoneinfo/Europe/Rome").exists():
        assert "tz" in changed(base, identity(sys.executable, root, {"TZ": "Europe/Rome"}))
    # the ISA level is part of the identity unless explicitly switched off
    off = identity(sys.executable, root, {"TZ": "UTC", "FENVIX_RUNTIME_ISA": "off"})
    assert changed(base, off) == ["cpu"]
    assert base["details"]["cpu"]["isa"] != "not keyed (FENVIX_RUNTIME_ISA=off)"
