import json
import socket
import subprocess
import sys
import threading
import time

import pytest

from sshm.core import agent, mounts, netscan, sshcmd, sshconfig, status, telemetry, themes, tunnels, wol
from sshm.core.models import Server
from sshm.core.settings import Settings


# ------------------------------------------------------------------- sshcmd
def test_ssh_argv_never_uses_shell_strings(tmp_path):
    key = tmp_path / "id_test"
    key.write_text("x")
    srv = Server(name="n", host="h", user="u", port=2022, key=str(key), jump="bastion")
    argv = sshcmd.ssh_command(srv)
    assert argv == ["ssh", "-p", "2022", "-i", str(key), "-J", "bastion", "u@h"]
    tmux = sshcmd.ssh_command(srv, tmux=True)
    assert tmux[-3:-1] == ["u@h", "--"] and "tmux new-session -A -s sshm" in tmux[-1]
    assert sshcmd.sftp_command(srv)[:3] == ["sftp", "-P", "2022"]


def test_hold_wrapper_passes_args_verbatim():
    nasty = "it's \"quoted\"; $(rm -rf /)"
    out = subprocess.run(sshcmd.hold(["printf", "%s", nasty]), capture_output=True, text=True)
    assert nasty in out.stdout


def test_copy_id_prefers_matching_pubkey(tmp_path):
    key = tmp_path / "id_x"
    key.write_text("k")
    (tmp_path / "id_x.pub").write_text("p")
    srv = Server(name="n", host="h", key=str(key))
    assert sshcmd.copy_id_command(srv)[3:5] == ["-i", str(key) + ".pub"]


# ---------------------------------------------------------------- telemetry
def _v2(secret, **extra):
    msg = {"v": 2, "id": "nas", "port": 22, "ts": time.time(), "seq": 1, "cpu": 12.5,
           "mem_used": 2 * 1024**3, "mem_total": 8 * 1024**3, "ssh": 1, **extra}
    msg["sig"] = telemetry.sign(msg, secret)
    return json.dumps(msg).encode()


def test_signed_packets():
    keys, entry = telemetry.parse_packet(_v2("s3cret"), "10.0.0.5", "s3cret", accept_legacy=False)
    assert keys == ["10.0.0.5:22", "nas:22"] and entry["signed"] and entry["cpu"] == 12.5
    assert telemetry.parse_packet(_v2("wrong"), "10.0.0.5", "s3cret", False) is None
    old = _v2("s3cret", ts=time.time() - 3600)
    assert telemetry.parse_packet(old, "10.0.0.5", "s3cret", False) is None
    stopping = _v2("s3cret", state="stopping")
    assert telemetry.parse_packet(stopping, "1.2.3.4", "s3cret", False)[1]["ssh"] == 0


def test_legacy_packets():
    data = json.dumps({"host": "pi", "port": "22", "cpu": "7", "ram": "1.5/4G", "up": "3d 2h", "ssh": 1}).encode()
    assert telemetry.parse_packet(data, "10.0.0.9", "s", accept_legacy=False) is None
    _keys, entry = telemetry.parse_packet(data, "10.0.0.9", "s", accept_legacy=True)
    tel = telemetry.Telemetry.from_entry(entry)
    assert tel.mem_total == 4 * 1024**3 and tel.uptime_label == "3d 2h" and not tel.signed


def test_listener_end_to_end():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    got = threading.Event()
    lst = telemetry.TelemetryListener(port, "k", on_update=lambda keys, changed: got.set())
    assert lst.bind()
    lst.start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(_v2("k"), ("127.0.0.1", port))
    assert got.wait(3)
    lst.stop()
    lst.join(3)
    cache = telemetry.read_cache()
    tel = telemetry.lookup(cache, "nas", 22)
    assert tel and tel.cpu == 12.5 and tel.history == [12.5]


def test_agent_signature_matches_hub():
    """The agent's sign() and the hub's verify() must agree byte-for-byte."""
    src = agent.agent_source()
    ns: dict = {}
    exec(compile(src.replace('if __name__ == "__main__":\n    main()', ""), "agent", "exec"), ns)
    payload = {"v": 2, "id": "x", "port": 22, "ts": 1.5, "cpu": 3.0, "load": [0.1, 0.2, 0.3]}
    payload["sig"] = ns["sign"](payload, "abc")
    assert telemetry.verify(json.loads(json.dumps(payload)), "abc")


def test_installer_script_is_valid_bash(tmp_path):
    srv = Server(name="n", host="10.1.1.1", port=22)
    script = agent.build_installer(srv, Settings.load(), hub="10.1.1.2")
    f = tmp_path / "i.sh"
    f.write_text(script)
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0
    assert '"secret"' in script and "SSHM_AGENT_EOF" in script
    f.write_text(agent.build_remover())
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0


def test_agent_runs_and_reports(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(8)
        cfg = tmp_path / "agent.json"
        cfg.write_text(json.dumps({"hub": "127.0.0.1", "port": rx.getsockname()[1], "id": "me",
                                   "ssh_port": 1, "secret": "zz", "interval": 1}))
        agent_file = tmp_path / "a.py"
        agent_file.write_text(agent.agent_source())
        proc = subprocess.Popen([sys.executable, str(agent_file), str(cfg)])
        try:
            data, _ = rx.recvfrom(4096)
        finally:
            proc.terminate()
            proc.wait(5)
    _keys, entry = telemetry.parse_packet(data, "127.0.0.1", "zz", accept_legacy=False)
    assert entry["mem_total"] > 0 and entry["disk_total"] > 0 and entry["ssh"] == 0


# ------------------------------------------------------------------ status
def test_probe_reads_ssh_banner():
    srv_sock = socket.socket()
    srv_sock.bind(("127.0.0.1", 0))
    srv_sock.listen(1)
    port = srv_sock.getsockname()[1]

    def serve():
        conn, _ = srv_sock.accept()
        conn.sendall(b"SSH-2.0-OpenSSH_9.6 Test\r\n")
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    st = status.probe("127.0.0.1", port, timeout=2)
    srv_sock.close()
    assert st.online and st.banner == "OpenSSH_9.6 Test" and st.latency_ms is not None
    closed = status.probe("127.0.0.1", port, timeout=0.5)
    assert not closed.online and closed.state == "offline"


# ----------------------------------------------------------------- netscan
def test_port_and_target_parsing():
    assert netscan.parse_ports("22, 2200-2202,abc") == [22, 2200, 2201, 2202]
    with pytest.raises(ValueError):
        netscan.parse_ports("nope")
    assert len(netscan.parse_targets("192.168.1")) == 254
    assert netscan.parse_targets("10.0.0.5-7") == ["10.0.0.5", "10.0.0.6", "10.0.0.7"]
    assert netscan.parse_targets("10.0.0.9") == ["10.0.0.9"]
    with pytest.raises(ValueError):
        netscan.parse_targets("10.0.0.0/8")


# --------------------------------------------------------------- sshconfig
def test_ssh_config_import(isolated_home):
    ssh = isolated_home / ".ssh"
    ssh.mkdir()
    (ssh / "extra.conf").write_text("Host db\n  HostName 10.0.0.30\n  User postgres\n")
    (ssh / "config").write_text(
        "Include extra.conf\n"
        "Host *\n  ServerAliveInterval 30\n"
        "Host web web-alias\n  HostName 10.0.0.20\n  Port 2222\n  User=deploy\n"
        "  IdentityFile ~/.ssh/id_web\n  ProxyJump bastion\n"
        "Match host foo\n  User ignored\n"
    )
    found = {s.name: s for s in sshconfig.import_servers([])}
    assert set(found) == {"db", "web"}  # web-alias is the same endpoint
    assert found["web"].port == 2222 and found["web"].user == "deploy" and found["web"].jump == "bastion"
    assert sshconfig.import_servers([Server(name="x", host="10.0.0.30")])[0].name == "web"
    text = sshconfig.export([found["web"]])
    assert "Host web\n    HostName 10.0.0.20\n    User deploy\n    Port 2222" in text


# ------------------------------------------------------------------- mounts
def test_bookmarks_gtk_and_kde(isolated_home):
    xbel = isolated_home / ".local/share/user-places.xbel"
    xbel.parent.mkdir(parents=True)
    xbel.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xbel>\n'
        '<xbel xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks" '
        'xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info" '
        'xmlns:kdepriv="http://www.kde.org/kdepriv">\n'
        ' <bookmark href="file:///home/me"><title>Home</title></bookmark>\n</xbel>\n'
    )
    settings = Settings.load()
    srv = Server(name="My NAS", host="10.0.0.5", user="me")
    assert not mounts.is_bookmarked(srv, settings)
    assert mounts.toggle_bookmark(srv, settings) is True
    assert mounts.is_bookmarked(srv, settings)
    gtk = (isolated_home / ".config/gtk-3.0/bookmarks").read_text()
    assert gtk.strip() == "sftp://me@10.0.0.5:22/home/me My NAS"
    text = xbel.read_text()
    assert "sftp://me@10.0.0.5:22/home/me" in text and "bookmark:icon" in text and "ns0" not in text
    assert "file:///home/me" in text
    assert (settings.mount_path / "My_NAS.desktop").exists()
    assert mounts.toggle_bookmark(srv, settings) is False
    assert not mounts.is_bookmarked(srv, settings)
    assert "sftp://" not in xbel.read_text() and "file:///home/me" in xbel.read_text()


# ------------------------------------------------------------------ tunnels
def test_tunnel_spec_parsing():
    s = tunnels.TunnelSpec.parse("L", "8080:localhost:80")
    assert s.arg == "8080:localhost:80" and "localhost:8080" in s.describe("web")
    assert tunnels.TunnelSpec.parse("D", "1080").arg == "1080"
    assert tunnels.TunnelSpec.parse("R", "0.0.0.0:9000:127.0.0.1:3000").bind == "0.0.0.0"
    for kind, bad in (("L", "8080"), ("D", "1:h:2"), ("X", "1"), ("L", "99999:h:1")):
        with pytest.raises(tunnels.TunnelError):
            tunnels.TunnelSpec.parse(kind, bad)


def test_tunnel_manager_prunes_dead(tmp_path):
    mgr = tunnels.TunnelManager()
    proc = subprocess.Popen(["sleep", "30"])
    mgr._write([tunnels.Tunnel("abc", "s", "srv", "L", "1:h:2", proc.pid, 0.0)])
    assert mgr.list() == []  # "sleep" is not ssh -> treated as stale
    proc.kill()
    proc.wait()


# --------------------------------------------------------------- misc core
def test_wol_packet():
    pkt = wol.magic_packet("aa:bb:cc:dd:ee:ff")
    assert len(pkt) == 102 and pkt[:6] == b"\xff" * 6 and pkt[6:12] == bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError):
        wol.magic_packet("")


def test_theme_xterm_mapping():
    assert themes.hex_to_xterm256("#000000") == 16
    assert themes.hex_to_xterm256("#ffffff") == 231
    assert themes.hex_to_xterm256("#808080") in range(232, 256)
    assert themes.get_theme("nope").name == themes.THEMES[0].name


def test_terminal_launch_with_fake_emulator(tmp_path, monkeypatch):
    from sshm.core import terminal

    record = tmp_path / "argv"
    fake = tmp_path / "bin" / "konsole"
    fake.parent.mkdir()
    # behaves like konsole: "-e" followed by the command to run
    fake.write_text(f'#!/bin/sh\n[ "$1" = "-e" ] && shift\n"$@" > {record} 2>&1\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:/usr/bin:/bin")
    monkeypatch.setenv("TERMINAL", "")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "")
    assert terminal.resolve() == ["konsole", "-e"]
    assert terminal.resolve("konsole --hold -e")[1:] == ["--hold", "-e"]
    terminal.launch(sshcmd.hold(["printf", "ran:%s", "a b"], "Title"))
    for _ in range(50):
        if record.exists() and "ran:" in record.read_text():
            break
        time.sleep(0.05)
    out = record.read_text()
    assert "Title" in out and "ran:a b" in out
