import json
import subprocess
import sys
from pathlib import Path

import pytest

from sshm.core import fleet
from sshm.core.models import CustomCommand, Server
from sshm.core.store import ServerStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text('#!/bin/sh\nfor a; do last=$a; done\nsh -c "$last"\n')
    (bin_dir / "ssh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return bin_dir


def test_run_many_collects_results_in_server_order(fake_ssh):
    servers = [Server(name=f"s{i}", host="h") for i in range(5)]
    seen = []
    results = fleet.run_many(servers, "echo out; echo err >&2; exit 0", on_result=seen.append)
    assert [r.server.name for r in results] == [s.name for s in servers]
    assert all(r.ok and r.stdout == "out\n" for r in results) and len(seen) == 5
    bad = fleet.run_one(servers[0], "echo boom; exit 7")
    assert bad.returncode == 7 and not bad.ok and bad.summary == "boom"
    slow = fleet.run_one(servers[0], "sleep 5", timeout=0.5)
    assert slow.returncode is None and "timed out" in slow.summary


def test_backup_roundtrip(tmp_path):
    store = ServerStore()
    a = store.add(Server(name="nas", host="10.0.0.5", tag="Homelab", mac="aa:bb:cc:dd:ee:ff",
                         commands=[CustomCommand("Update", "sudo dnf -y upgrade")]))
    store.add(Server(name="pi", host="10.0.0.6"))
    path = tmp_path / "b.json"
    assert fleet.export_backup(store, path) == 2
    data = json.loads(path.read_text())
    assert data["format"] == "sshm-backup" and "secret" not in path.read_text()
    store.remove(a.id)
    pi = store.by_name("pi")
    pi.port = 2222
    store.update(pi)
    assert fleet.import_backup(store, path) == (1, 1)
    assert store.by_name("nas").commands[0].command == "sudo dnf -y upgrade"
    assert store.by_name("pi").port == 22
    store.add(Server(name="extra", host="x"))
    assert fleet.import_backup(store, path, replace=True) == (2, 0)
    assert sorted(s.name for s in store.servers) == ["nas", "pi"]
    (tmp_path / "junk.json").write_text("[]")
    with pytest.raises(ValueError):
        fleet.import_backup(store, tmp_path / "junk.json")


def test_cli_exec_splits_on_double_dash(fake_ssh):
    store = ServerStore()
    store.add(Server(name="alpha", host="h", tag="Lab"))
    store.add(Server(name="beta", host="h", tag="Lab"))
    env = {"PATH": str(fake_ssh) + ":/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")}
    import os

    env.update({k: os.environ[k] for k in ("HOME", "SSHM_CONFIG_DIR", "SSHM_RUNTIME_DIR", "SSHM_STATE_DIR")})
    out = subprocess.run([sys.executable, "-m", "sshm", "exec", "-t", "Lab", "--json", "--", "echo", "hi"],
                         capture_output=True, text=True, env=env)
    data = json.loads(out.stdout)
    assert [d["server"] for d in data] == ["alpha", "beta"] and all(d["stdout"] == "hi\n" for d in data)
    out = subprocess.run([sys.executable, "-m", "sshm", "exec", "alpha", "--", "exit 4"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 1 and "exit 4" in out.stdout
