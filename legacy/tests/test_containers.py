import json
import os
import socket
import threading

from sshm.core import containers, minecraft
from sshm.core.models import Server

PS = [
    {"ID": "a1b2c3d4e5f6" + "0" * 52, "Names": "mc", "Image": "itzg/minecraft-server:latest", "State": "running",
     "Status": "Up 3 days (healthy)", "Ports": "0.0.0.0:2222->22/tcp, :::2222->22/tcp, 0.0.0.0:25565->25565/tcp",
     "Labels": "com.docker.compose.project=games,foo=bar"},
    {"ID": "ffff" + "1" * 60, "Names": "old-db", "Image": "postgres:16", "State": "exited",
     "Status": "Exited (0) 2 weeks ago", "Ports": "", "Labels": ""},
]
STATS = [{"ID": "a1b2c3d4e5f6", "Name": "mc", "CPUPerc": "12.50%", "MemUsage": "2.5GiB / 15.5GiB"}]


def discovery_output(runtime="docker"):
    lines = [f"SSHM_RT {runtime}", *map(json.dumps, PS), "SSHM_STATS", *map(json.dumps, STATS)]
    return "\n".join(lines) + "\n"


def test_parse_discovery_docker():
    hc = containers.parse_discovery(discovery_output("sudo -n docker"))
    assert hc.runtime == "sudo -n docker" and not hc.error
    mc, db = hc.containers
    assert (mc.name, mc.state, mc.health, mc.project) == ("mc", "running", "healthy", "games")
    assert [p.label for p in mc.ports] == ["2222→22/tcp", "25565→25565/tcp"]
    assert mc.cpu == 12.5 and mc.mem == int(2.5 * 1024**3) and mc.mem_limit == int(15.5 * 1024**3)
    assert mc.cli == "sudo docker" and mc.ports[1].service == "Minecraft"
    assert not db.running and db.cpu is None
    assert hc.by_port(25565) is mc and hc.by_port(5432) is None


def test_parse_podman_shapes_and_errors():
    podman = [{"Id": "abc123", "Names": ["web"], "Image": "nginx", "State": "running", "Status": "Up 5 minutes",
               "Ports": [{"host_port": 8080, "container_port": 80, "protocol": "tcp", "host_ip": ""}]}]
    hc = containers.parse_discovery("SSHM_RT podman\n" + json.dumps(podman) + "\nSSHM_STATS\n")
    assert hc.containers[0].ports[0].label == "8080→80/tcp" and hc.containers[0].ports[0].is_web
    err = containers.parse_discovery("SSHM_NODOCKER docker found but permission denied\n")
    assert err.error.startswith("docker found but permission") and not err.containers


def test_link_minecraft_container_to_homelab_host():
    host = Server(name="Homelab Node", host="192.168.4.100", user="lucas")
    mc = Server(name="Minecraft_server", host="192.168.4.100", port=2222, user="lucas")
    other = Server(name="bazzite", host="192.168.4.53")
    hc = containers.parse_discovery(discovery_output())
    links = containers.link_servers([host, mc, other], {host.id: hc})
    assert set(links) == {mc.id}
    assert links[mc.id].host is host and links[mc.id].container.name == "mc"
    # linking also works when only the resolved addresses match
    named = Server(name="mc-by-name", host="homelab.lan", port=2222)
    links = containers.link_servers([host, named], {host.id: hc}, {host.id: "192.168.4.100", named.id: "192.168.4.100"})
    assert named.id in links


def test_candidate_hosts():
    host = Server(name="h", host="10.0.0.5")
    ctr = Server(name="c", host="10.0.0.5", port=2222)
    lone = Server(name="l", host="10.0.0.9")
    assert containers.candidate_hosts([ctr, host, lone]) == [host, ctr]   # port 22 asked first
    high = Server(name="h2", host="10.0.0.7", port=2200)
    low_ctr = Server(name="c2", host="10.0.0.7", port=2022)
    assert {s.name for s in containers.candidate_hosts([high, low_ctr])} == {"h2", "c2"}


def test_discovery_script_with_fake_docker(tmp_path, monkeypatch):
    """Run the real remote script under sh with a fake `docker` on PATH."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps_lines = "\n".join(json.dumps(x) for x in PS)
    stats_lines = "\n".join(json.dumps(x) for x in STATS)
    (bin_dir / "docker").write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = ps ]; then cat <<\'EOF\'\n{ps_lines}\nEOF\n'
        f'elif [ "$1" = stats ]; then cat <<\'EOF\'\n{stats_lines}\nEOF\n'
        'else echo "docker $*" >> "$LOG"; fi\n'
    )
    (bin_dir / "docker").chmod(0o755)
    (bin_dir / "ssh").write_text('#!/bin/sh\nfor a; do last=$a; done\nsh -c "$last"\n')
    (bin_dir / "ssh").chmod(0o755)
    log = tmp_path / "log"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("LOG", str(log))
    out = subprocess.run(containers.REMOTE_DISCOVERY, shell=True, capture_output=True, text=True).stdout
    assert out.startswith("SSHM_RT docker")
    host = Server(name="h", host="x")
    hc = containers.discover(host)
    assert [c.name for c in hc.containers] == ["mc", "old-db"] and hc.host_id == host.id
    assert containers.run_action(host, hc.containers[0], "restart") == "Restarted mc"
    assert "docker restart mc" in log.read_text()


def test_no_docker_reports_cleanly(tmp_path, monkeypatch):
    import subprocess

    empty = tmp_path / "empty"
    empty.mkdir()
    for tool in ("sh", "cat", "printf"):
        if os.path.exists(f"/bin/{tool}"):
            os.symlink(f"/bin/{tool}", empty / tool)
    env = {"PATH": str(empty)}
    out = subprocess.run(["/bin/sh", "-c", containers.DISCOVERY_SCRIPT], capture_output=True, text=True, env=env)
    assert out.stdout.startswith("SSHM_NODOCKER")


def test_agent_reads_docker_api_socket(tmp_path):
    from sshm.core import agent

    ns: dict = {}
    exec(agent.agent_source().replace('if __name__ == "__main__":\n    main()', ""), ns)
    sock_path = str(tmp_path / "docker.sock")
    body = json.dumps([{"Id": "abc" * 21 + "d", "Names": ["/mc"], "Image": "itzg/minecraft-server",
                        "State": "running", "Status": "Up 2 hours",
                        "Ports": [{"PrivatePort": 25565, "PublicPort": 25565, "Type": "tcp"},
                                  {"PrivatePort": 22, "PublicPort": 2222, "Type": "tcp"}],
                        "Labels": {"com.docker.compose.project": "games"}}]).encode()
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(sock_path)
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    ns["container_sockets"] = lambda: [("docker", sock_path)]
    ns["cgroup_usage"] = lambda cid: (10.0, 512 * 1024**2)
    runtime, rows, err, sample = ns["container_rows"]({}, 3.0, 16 * 1024**3)
    srv.close()
    assert runtime == "docker" and not err and sample
    ctr = containers.from_agent(rows)[0]
    assert ctr.name == "mc" and ctr.project == "games" and ctr.mem == 512 * 1024**2
    assert sorted(p.host_port for p in ctr.ports) == [2222, 25565]


def test_agent_socket_permission_error(tmp_path):
    from sshm.core import agent

    ns: dict = {}
    exec(agent.agent_source().replace('if __name__ == "__main__":\n    main()', ""), ns)
    ns["container_sockets"] = lambda: [("docker", str(tmp_path / "missing.sock"))]
    assert ns["list_containers"]() == (None, [], "")


def _fake_minecraft_server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    status = {"version": {"name": "1.21.1"}, "players": {"max": 20, "online": 2, "sample": [{"name": "Steve"}]},
              "description": {"text": "§aLucas's ", "extra": [{"text": "world"}]}}

    def varint(n):
        out = b""
        while True:
            b = n & 0x7F
            n >>= 7
            out += bytes([b | (0x80 if n else 0)])
            if not n:
                return out

    def serve():
        conn, _ = srv.accept()
        conn.recv(1024)
        payload = json.dumps(status).encode()
        pkt = b"\x00" + varint(len(payload)) + payload
        conn.sendall(varint(len(pkt)) + pkt)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv


def test_minecraft_ping():
    srv = _fake_minecraft_server()
    st = minecraft.ping("127.0.0.1", srv.getsockname()[1])
    srv.close()
    assert (st.online, st.max_players, st.version) == (2, 20, "1.21.1")
    assert st.motd == "Lucas's world" and st.players == ["Steve"] and st.summary == "2/20 players · 1.21.1"
