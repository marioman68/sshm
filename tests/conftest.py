import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own HOME, config and runtime directories."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SSHM_CONFIG_DIR", str(home / ".config/sshm"))
    monkeypatch.setenv("SSHM_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("SSHM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home
