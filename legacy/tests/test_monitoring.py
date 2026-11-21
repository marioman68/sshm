import time

from sshm.core import agent, telemetry
from sshm.core.alerts import AlertEngine
from sshm.core.containers import Container, HostContainers
from sshm.core.history import Availability, Event, History
from sshm.core.models import Server
from sshm.core.settings import Settings
from sshm.core.status import HostStatus

T0 = 1_800_000_000.0


def tel(cpu=10.0, mem=(1, 10), disk=(1, 10), reboot=None):
    return telemetry.Telemetry(received=time.time(), cpu=cpu, mem_used=mem[0], mem_total=mem[1],
                               disk_used=disk[0], disk_total=disk[1], reboot_required=reboot)


# ------------------------------------------------------------------ history
def test_history_sampling_and_uptime():
    h = History()
    sid = "s1"
    assert h.record(sid, True, 5.0, now=T0)
    assert not h.record(sid, True, 5.0, now=T0 + 10)          # same state within a minute: skipped
    assert h.record(sid, False, now=T0 + 20)                   # state change: stored immediately
    for i in range(1, 30):                                     # 29 minutes down
        h.record(sid, False, now=T0 + 20 + i * 60)
    for i in range(30, 61):                                    # back up
        h.record(sid, True, 4.0, now=T0 + 20 + i * 60)
    up = h.uptime(sid, 3600, now=T0 + 3620)
    assert 45 < up < 55
    assert h.uptime("never-seen", 3600) is None
    series = h.latency_series(sid, 3600, 6, now=T0 + 3620)
    assert len(series) == 6 and series[0] == 0.0 and series[-1] == 4.0   # window starts while down
    assert Availability.label(99.999) == "100%" and Availability.label(99.5) == "99.50%"


def test_events_and_active_alerts():
    h = History()
    h.add_event(Event(T0, "a", "nas", "offline", "critical", "nas is down"))
    h.add_event(Event(T0 + 1, "a", "nas", "disk", "warning", "disk full"))
    assert {e.kind for e in h.active()} == {"offline", "disk"}
    h.add_event(Event(T0 + 2, "a", "nas", "offline", "info", "nas is back", resolved=True))
    assert [e.kind for e in h.active()] == ["disk"]
    assert [e.message for e in h.events()][:2] == ["nas is back", "disk full"]
    h.forget("a")
    assert h.events() == [] and h.active() == []


# ------------------------------------------------------------------- alerts
def run(engine, srv, statuses, now, hosts=None):
    return engine.evaluate([srv], statuses, hosts, now=now)


def test_offline_alert_needs_baseline_and_grace():
    s = Settings.load()
    s.alert_offline_grace = 60
    eng = AlertEngine(s)
    srv = Server(name="nas", host="h")
    down = {srv.id: HostStatus(False, error="timed out")}
    assert run(eng, srv, down, T0) == []                       # never seen up: no alert at startup
    up = {srv.id: HostStatus(True, 3.0)}
    assert run(eng, srv, up, T0 + 10) == []
    assert run(eng, srv, down, T0 + 20) == []                  # within grace
    fired = run(eng, srv, down, T0 + 90)
    assert [(e.kind, e.severity) for e in fired] == [("offline", "critical")]
    assert run(eng, srv, down, T0 + 200) == []                 # no repeats
    back = run(eng, srv, up, T0 + 300)
    assert back[0].resolved and back[0].message == "nas is back online"


def test_cpu_sustained_and_disk_and_reboot():
    s = Settings.load()
    s.alert_sustain_minutes = 5
    eng = AlertEngine(s)
    srv = Server(name="nas", host="h")

    def st(**kw):
        return {srv.id: HostStatus(True, 1.0, telemetry=tel(**kw))}

    assert run(eng, srv, st(reboot=False), T0) == []
    assert run(eng, srv, st(cpu=99), T0 + 60) == []
    assert run(eng, srv, st(cpu=99), T0 + 200) == []
    kinds = [e.kind for e in run(eng, srv, st(cpu=99, disk=(95, 100), reboot=True), T0 + 400)]
    assert sorted(kinds) == ["cpu", "disk", "reboot"]
    assert run(eng, srv, st(cpu=5), T0 + 500)[0].message == "nas: CPU back to normal"


def test_container_alerts_only_on_transition_and_unmonitored_servers_ignored():
    eng = AlertEngine(Settings.load())
    srv = Server(name="Homelab Node", host="h")
    ok = {srv.id: HostStatus(True, 1.0)}

    def hc(state, status="Up 1 hour"):
        return {srv.id: HostContainers(srv.id, [Container("1", "minecraft", state=state, status=status),
                                                 Container("2", "old-db", state="exited")])}

    assert run(eng, srv, ok, T0, hc("running")) == []          # old-db already stopped: no alert
    assert run(eng, srv, ok, T0 + 10, hc("exited", "Exited (1)")) == []   # 30s hold
    fired = run(eng, srv, ok, T0 + 60, hc("exited", "Exited (1)"))
    assert [e.kind for e in fired] == ["container:minecraft"] and "stopped" in fired[0].message
    fired = run(eng, srv, ok, T0 + 70, hc("running", "Up 5 seconds (unhealthy)"))
    assert fired[0].resolved
    quiet = Server(name="q", host="h", tray=False)
    assert eng.evaluate([quiet], {quiet.id: HostStatus(False)}, now=T0) == []


def test_alerts_can_be_disabled():
    s = Settings.load()
    s.alerts_enabled = False
    srv = Server(name="n", host="h")
    eng = AlertEngine(s)
    eng.evaluate([srv], {srv.id: HostStatus(True)}, now=T0)
    assert eng.evaluate([srv], {srv.id: HostStatus(False)}, now=T0 + 999) == []


# -------------------------------------------------------------------- agent
def test_agent_version_and_reboot_fields():
    assert agent.bundled_version().count(".") == 2
    assert agent.is_outdated("") and agent.is_outdated("3.2.9") and not agent.is_outdated(agent.bundled_version())
    import json

    msg = {"v": 2, "id": "x", "port": 22, "ts": time.time(), "cpu": 1.0, "ssh": 1, "agent": "3.3.0", "reboot": 1}
    msg["sig"] = telemetry.sign(msg, "k")
    _keys, entry = telemetry.parse_packet(json.dumps(msg).encode(), "1.1.1.1", "k", False)
    t = telemetry.Telemetry.from_entry(entry)
    assert t.agent_version == "3.3.0" and t.reboot_required is True


def test_agent_reboot_heuristic(monkeypatch):
    ns: dict = {}
    exec(agent.agent_source().replace('if __name__ == "__main__":\n    main()', ""), ns)
    assert ns["_kver"]("6.11.4-301.fc41.x86_64") == (6, 11, 4)
    assert ns["_kver"]("6.11.10-300.fc41.x86_64") > ns["_kver"]("6.11.4-301.fc41.x86_64")
