import json
import time

import pytest

from sshm.core import procs, telemetry
from sshm.core.models import Server

GNU = """SSHM_GNU
    1 root        0.0  0.1  11320     86400 systemd         /usr/lib/systemd/systemd --switched-root
  812 lucas      42.5  3.2 524288       125 firefox         /usr/lib64/firefox/firefox -contentproc
  913 postgres    1.0 12.5 2097152     3600 postgres        postgres: checkpointer
"""
BUSYBOX = """SSHM_BB
PID   USER     VSZ  COMMAND          COMMAND
    1 root     1572 init             /sbin/init
  220 nobody   2040 dnsmasq          /usr/sbin/dnsmasq -C /var/etc/dnsmasq.conf
"""


def test_parse_gnu_and_busybox():
    ps = procs.parse(GNU)
    assert [p.pid for p in ps] == [1, 812, 913]
    ff = ps[1]
    assert ff.cpu == 42.5 and ff.mem == 3.2 and ff.rss == 524288 * 1024 and ff.elapsed == 125
    assert ff.command.endswith("-contentproc") and ff.rss_label == "512.0M"
    bb = procs.parse(BUSYBOX)
    assert [(p.pid, p.name, p.cpu) for p in bb] == [(1, "init", None), (220, "dnsmasq", None)]
    assert procs.parse("") == []


def test_sort_and_filter():
    ps = procs.parse(GNU)
    assert procs.sort(ps, "cpu")[0].name == "firefox"
    assert procs.sort(ps, "mem")[0].name == "postgres"
    assert procs.sort(ps, "time")[0].name == "systemd"
    assert [p.pid for p in procs.filter_procs(ps, "postgres")] == [913]
    assert [p.pid for p in procs.filter_procs(ps, "812")] == [812]


def test_remote_script_runs_locally():
    """The exact remote script must run under sh and produce parseable output."""
    import subprocess

    out = subprocess.run(procs.REMOTE_PS, shell=True, capture_output=True, text=True).stdout
    ps = procs.parse(out)
    assert ps and any(p.pid == 1 for p in ps)


def _fake_ssh(tmp_path, monkeypatch, script: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text("#!/bin/sh\n" + script)
    ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")


def test_fetch_and_kill_via_fake_ssh(tmp_path, monkeypatch):
    log = tmp_path / "calls"
    # last argument is the remote command; run it locally like a real sshd would
    _fake_ssh(tmp_path, monkeypatch, f'for a; do last=$a; done; echo "$last" >> {log}; sh -c "$last"\n')
    srv = Server(name="box", host="h")
    ps = procs.fetch(srv)
    assert any(p.pid == 1 for p in ps)
    calls = log.read_text()
    assert "ControlMaster" not in calls  # options go before the target, not in the command
    with pytest.raises(procs.ProcError):
        procs.kill(srv, 999999999)


def test_fetch_auth_failure_hint(tmp_path, monkeypatch):
    _fake_ssh(tmp_path, monkeypatch, 'echo "user@h: Permission denied (publickey)." >&2; exit 255\n')
    with pytest.raises(procs.ProcError, match="key-based login"):
        procs.fetch(Server(name="box", host="h"))


def test_telemetry_carries_top_processes():
    msg = {"v": 2, "id": "nas", "port": 22, "ts": time.time(), "cpu": 5.0, "ssh": 1,
           "procs": [["firefox", 812, 40.5, 500_000_000], ["bad"], ["sshd", "9", "0.1", "4096"]]}
    msg["sig"] = telemetry.sign(msg, "k")
    _keys, entry = telemetry.parse_packet(json.dumps(msg).encode(), "1.2.3.4", "k", False)
    tel = telemetry.Telemetry.from_entry(entry)
    assert [p.name for p in tel.top("cpu")] == ["firefox", "sshd"]
    assert tel.top("mem")[0].rss_label == "476.8M"


def test_agent_top_processes_skip_idle():
    from sshm.core import agent

    ns: dict = {}
    exec(agent.agent_source().replace('if __name__ == "__main__":\n    main()', ""), ns)
    prev = {1: ("idle", 100, 10), 2: ("busy", 100, 5), 3: ("fat", 100, 10**9)}
    cur = {1: ("idle", 100, 10), 2: ("busy", 300, 5), 3: ("fat", 100, 10**9)}
    rows = ns["top_processes"](prev, cur, 1.0)
    assert rows[0][0] == "busy" and rows[0][2] > 0
    assert {r[0] for r in rows} == {"busy", "fat", "idle"}  # idle only via the memory list


def test_fetch_does_not_wait_for_background_master(tmp_path, monkeypatch):
    """Regression: a ControlPersist master inherits stdout/stderr; fetch must not block on it."""
    _fake_ssh(tmp_path, monkeypatch, 'for a; do last=$a; done\n( sleep 30 ) &\nsh -c "$last"\n')
    started = time.monotonic()
    assert procs.fetch(Server(name="box", host="h"), timeout=8)
    assert time.monotonic() - started < 3
