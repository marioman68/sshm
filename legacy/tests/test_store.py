import json

import pytest

from sshm.core.models import CustomCommand, Server, normalize_mac
from sshm.core.settings import Settings
from sshm.core.store import ServerStore, StoreError


def test_roundtrip(isolated_home):
    store = ServerStore()
    srv = store.add(Server(name="nas", host="10.0.0.5", user="me", port=2222, tag="Homelab",
                           commands=[CustomCommand("Update", "sudo dnf upgrade -y")]))
    again = ServerStore()
    loaded = again.get(srv.id)
    assert loaded == srv
    assert loaded.commands[0].command == "sudo dnf upgrade -y"
    assert (isolated_home / ".config/sshm/servers.json").stat().st_mode & 0o777 == 0o600


def test_duplicate_names_and_validation():
    store = ServerStore()
    store.add(Server(name="web", host="web.lan"))
    with pytest.raises(StoreError):
        store.add(Server(name="WEB", host="other"))
    with pytest.raises(StoreError):
        store.add(Server(name="bad", host="x", port=70000))
    with pytest.raises(StoreError):
        store.add(Server(name="bad", host="x", mac="zz"))
    assert store.unique_name("web") == "web-2"


def test_find():
    store = ServerStore()
    for name in ("proxmox", "pihole", "printer"):
        store.add(Server(name=name, host=f"{name}.lan"))
    assert store.find("PROXMOX").name == "proxmox"
    assert store.find("pih").name == "pihole"
    with pytest.raises(StoreError, match="ambiguous"):
        store.find("p")
    with pytest.raises(StoreError, match="No server"):
        store.find("zzz")


def test_legacy_migration(isolated_home):
    (isolated_home / ".ssh_servers").write_text(
        "# comment\n"
        "Main Server|lucas|192.168.4.10|22|Homelab|AA-BB-CC-DD-EE-FF|~/.ssh/id_ed25519\n"
        "Pi|pi|192.168.4.20||Lab||\n"
        "broken line without host\n"
    )
    (isolated_home / ".ssh_custom_commands.json").write_text(
        json.dumps({"Main Server": [{"label": "Topgrade", "cmd": "topgrade"}]})
    )
    (isolated_home / ".ssh_tray_hidden.json").write_text(json.dumps(["Pi"]))
    (isolated_home / ".ssh_hub_theme").write_text("5\n")

    store = ServerStore()
    assert store.migrated_from_legacy
    main, pi = store.servers
    assert main.mac == "aa:bb:cc:dd:ee:ff"
    assert main.commands[0].label == "Topgrade"
    assert main.tray and not pi.tray
    assert pi.port == 22
    assert Settings.load().theme == "Oceanic Blue"
    # legacy file is left untouched
    assert "Main Server" in (isolated_home / ".ssh_servers").read_text()


def test_reload_if_changed():
    a = ServerStore()
    b = ServerStore()
    a.add(Server(name="x", host="x"))
    assert b.reload_if_changed()
    assert [s.name for s in b.servers] == ["x"]
    assert not b.reload_if_changed()


def test_mac_and_urls():
    assert normalize_mac("AABB.CCDD.EEFF") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac("") == ""
    s = Server(name="r", host="h", user="root", port=2200)
    assert s.sftp_url == "sftp://root@h:2200/root"
    assert Server(name="u", host="h", user="bob").home_path == "/home/bob"
    assert Server(name="u", host="h", remote_path="srv/data").home_path == "/srv/data"


def test_settings_secret_persisted():
    s1 = Settings.load()
    assert len(s1.telemetry_secret) == 48
    assert Settings.load().telemetry_secret == s1.telemetry_secret
