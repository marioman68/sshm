"""The version must agree everywhere it appears."""

import re
import subprocess
import sys
from pathlib import Path

import sshm

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_consistent():
    v = sshm.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", v)
    assert re.search(rf"^Version:\s+{re.escape(v)}$", (ROOT / "packaging/sshm.spec").read_text(), re.M)
    assert re.search(rf"- {re.escape(v)}-1$", (ROOT / "packaging/sshm.spec").read_text(), re.M)
    first = re.search(r"^## (\S+)", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
    assert first == v, "newest CHANGELOG section must match __version__"
    assert 'dynamic = ["version"]' in (ROOT / "pyproject.toml").read_text()


def test_cli_reports_version():
    out = subprocess.run([sys.executable, "-m", "sshm", "--version"], capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})
    assert out.stdout.strip() == f"sshm {sshm.__version__}"


def test_bump_script(tmp_path):
    import shutil

    for rel in ("src/sshm/__init__.py", "packaging/sshm.spec", "CHANGELOG.md", "scripts/bump_version.py"):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, dest)
    major, minor, patch = map(int, sshm.__version__.split("."))  # noqa: RUF048 - enforced X.Y.Z above
    out = subprocess.run([sys.executable, str(tmp_path / "scripts/bump_version.py"), "patch", "Test fix"],
                         capture_output=True, text=True, check=True).stdout
    new = f"{major}.{minor}.{patch + 1}"
    assert out.strip().endswith(new)
    assert f'__version__ = "{new}"' in (tmp_path / "src/sshm/__init__.py").read_text()
    spec = (tmp_path / "packaging/sshm.spec").read_text()
    assert f"Version:        {new}" in spec and "- Test fix" in spec
    assert (tmp_path / "CHANGELOG.md").read_text().split("\n")[2].startswith(f"## {new} ")


def test_release_notes_extracts_current_section():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/release_notes.py"), sshm.__version__],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() and not any(line.startswith("## ") for line in out.splitlines())


def test_copr_tarball_matches_spec(tmp_path):
    """COPR's make_srpm tarball must have the name and top directory the spec expects."""
    import tarfile

    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "rpmbuild").write_text("#!/bin/sh\nexit 0\n")
    (fake / "rpmbuild").chmod(0o755)
    env = {"PATH": f"{fake}:/usr/bin:/bin"}
    subprocess.run(["make", "-s", "-f", str(ROOT / ".copr/Makefile"), "srpm", f"outdir={tmp_path}"],
                   check=True, env=env, capture_output=True)
    tarball = tmp_path / "src" / f"sshm-{sshm.__version__}.tar.gz"
    spec = (ROOT / "packaging/sshm.spec").read_text()
    assert "%{name}-%{version}.tar.gz" in spec and "%autosetup -n %{name}-%{version}" in spec
    with tarfile.open(tarball) as tf:
        names = tf.getnames()
    top = f"sshm-{sshm.__version__}"
    assert all(n == top or n.startswith(top + "/") for n in names)
    assert f"{top}/packaging/sshm.spec" in names and f"{top}/scripts/bump_version.py" in names
    assert not any("__pycache__" in n or "/.git/" in n for n in names)
