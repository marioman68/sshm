"""End-to-end TUI tests in a pseudo-terminal."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from sshm.core.models import Server
from sshm.core.store import ServerStore
from tui_harness import TUIProcess

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs a Linux pty")


def _env():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(os.path.dirname(__file__), "..", "src")
    return env


def test_empty_state_and_help():
    p = TUIProcess(_env(), rows=30, cols=110)
    screen = p.pump(2.0)
    assert "No servers yet" in screen and "scan your network" in screen
    assert "keyboard reference" in p.send("?", 0.8)
    assert p.close() == 0


def test_add_search_delete_flow():
    ServerStore().add(Server(name="alpha", host="192.0.2.1", tag="Lab"))
    p = TUIProcess(_env(), rows=34, cols=120)
    screen = p.pump(2.0)
    assert "alpha" in screen and "Servers (1)" in screen
    p.send("a", 0.6)
    screen = p.send("bravo\t192.0.2.2\r", 1.0)
    assert "Added bravo" in screen and "Servers (2)" in screen
    screen = p.send("/brav\r", 0.8)
    assert "Servers (1/2)" in screen
    p.send("\x1b", 0.4)
    p.send("d", 0.6)
    screen = p.send("y", 0.8)
    assert "Deleted" in screen
    assert p.close() == 0
    assert len(ServerStore()) == 1


def test_narrow_terminal_and_tiny_terminal():
    ServerStore().add(Server(name="alpha", host="192.0.2.1"))
    p = TUIProcess(_env(), rows=24, cols=70)
    assert "alpha" in p.pump(2.0)
    assert p.close() == 0
    p = TUIProcess(_env(), rows=10, cols=40)
    assert "too small" in p.pump(1.5)
    assert p.close() == 0


def test_process_viewer_lists_and_kills(tmp_path):
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text('#!/bin/sh\nfor a; do last=$a; done\nsh -c "$last"\n')  # runs the remote command locally
    ssh.chmod(0o755)
    ServerStore().add(Server(name="box", host="192.0.2.1"))
    victim = subprocess.Popen(["sleep", "300"])
    env = _env()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    try:
        p = TUIProcess(env, rows=32, cols=120)
        p.pump(1.5)
        screen = p.send("P", 2.5)
        assert "Processes — box" in screen and "processes · updated" in screen
        screen = p.send(f"/{victim.pid}\r", 1.0)
        assert "sleep 300" in screen and "1/" in screen
        p.send("k", 0.8)
        screen = p.send("y", 2.0)
        assert "Sent SIGTERM" in screen
        assert victim.wait(5) is not None
        assert p.close() == 0
    finally:
        victim.kill()


def test_container_detected_and_restarted(tmp_path):
    """A saved server on a sibling port of a docker host shows up as that container."""
    import json
    import socket
    import threading

    listeners = []
    for _ in range(2):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(20)
        listeners.append(s)

    def serve(sock):
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            conn.sendall(b"SSH-2.0-OpenSSH_10.0\r\n")
            conn.close()

    for s in listeners:
        threading.Thread(target=serve, args=(s,), daemon=True).start()
    host_port, ctr_port = (s.getsockname()[1] for s in listeners)
    ps = {"ID": "abc123" + "0" * 58, "Names": "minecraft", "Image": "itzg/minecraft-server", "State": "running",
          "Status": "Up 3 days", "Ports": f"0.0.0.0:{ctr_port}->22/tcp", "Labels": ""}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    (bin_dir / "docker").write_text(
        f"#!/bin/sh\nif [ \"$1\" = ps ]; then echo '{json.dumps(ps)}'; elif [ \"$1\" = stats ]; then :; "
        f"else echo \"docker $*\" >> {log}; fi\n")
    (bin_dir / "ssh").write_text('#!/bin/sh\nfor a; do last=$a; done\nsh -c "$last"\n')
    for f in ("docker", "ssh"):
        (bin_dir / f).chmod(0o755)
    store = ServerStore()
    store.add(Server(name="Homelab Node", host="127.0.0.1", port=host_port))
    store.add(Server(name="Minecraft_server", host="127.0.0.1", port=ctr_port))
    env = _env()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    try:
        p = TUIProcess(env, rows=40, cols=130)
        screen = p.pump(1.0)
        for _ in range(20):
            screen = p.pump(0.5)
            if "⬢" in screen:
                break
        assert "⬢ Minecraft_server" in screen
        p.send("j", 0.5)   # Homelab Node
        screen = p.send("j", 0.8)   # Minecraft_server
        assert "CONTAINER" in screen and "itzg/minecraft-server" in screen and "Homelab Node · docker" in screen
        p.send("D", 0.8)
        p.send("\r", 2.0)  # first option: Restart
        assert p.close() == 0
        assert "docker restart minecraft" in log.read_text()
    finally:
        for s in listeners:
            s.close()
