"""UI-agnostic controller: owns the store, settings, status cache and telemetry.

Front-ends poll :meth:`Hub.tick` (TUI) or connect callbacks (GUI). All network
work happens on worker threads so no front-end ever blocks on a slow host.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from collections.abc import Callable

from sshm.core import containers, status, telemetry
from sshm.core.alerts import AlertEngine
from sshm.core.containers import ContainerLink, HostContainers
from sshm.core.history import Event, History
from sshm.core.models import Server
from sshm.core.settings import Settings
from sshm.core.status import HostStatus
from sshm.core.store import ServerStore
from sshm.core.tunnels import TunnelManager


class Hub:
    def __init__(self, store: ServerStore | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self.store = store or ServerStore()
        self.tunnels = TunnelManager()
        self.statuses: dict[str, HostStatus] = {}
        self.listener: telemetry.TelemetryListener | None = None
        self.last_probe = 0.0
        self.on_statuses: Callable[[], None] | None = None
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="sshm-hub")
        self._probe: concurrent.futures.Future | None = None
        self._lock = threading.Lock()
        self._last_tel = 0.0
        self._last_store_check = 0.0
        # containers discovered over SSH: host id -> result; plus scheduling state
        self.ssh_containers: dict[str, HostContainers] = {}
        self.on_containers: Callable[[], None] | None = None
        self._disc_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="sshm-docker")
        self._disc_next: dict[str, float] = {}
        self._disc_running: set[str] = set()
        self._last_disc_check = 0.0
        self.alerts = AlertEngine(self.settings)
        self.on_events: Callable[[list[Event]], None] | None = None
        self._history: History | None = None
        self._observe_lock = threading.Lock()
        self._mc: dict[str, tuple[float, object]] = {}   # "host:port" -> (checked, MinecraftStatus | error str)
        self._mc_running: set[str] = set()

    # ------------------------------------------------------------ telemetry
    def start_listener(
        self,
        on_update: Callable[[list[str], bool], None] | None = None,
        on_command: Callable[[dict], None] | None = None,
    ) -> bool:
        """Receive telemetry in-process. False if another sshm process already does."""
        if self.listener:
            return True
        lst = telemetry.TelemetryListener(
            self.settings.telemetry_port,
            self.settings.telemetry_secret,
            self.settings.accept_legacy_agents,
            on_update=on_update,
            on_command=on_command,
        )
        if not lst.bind():
            return False
        lst.start()
        self.listener = lst
        try:  # fresh owner: stale "active alerts" from a previous run are re-derived from scratch
            self.history.clear_active()
            self.history.prune()
        except Exception:
            logging.getLogger(__name__).exception("history maintenance failed")
        return True

    def telemetry_cache(self) -> dict:
        return dict(self.listener.cache) if self.listener else telemetry.read_cache()

    def reattach_telemetry(self) -> None:
        with self._lock:
            status.attach_telemetry(self.store.servers, self.statuses, self.telemetry_cache())

    # --------------------------------------------------------------- probing
    @property
    def probing(self) -> bool:
        return self._probe is not None and not self._probe.done()

    def refresh(self, servers: list[Server] | None = None) -> bool:
        """Start a background probe. Returns False if one is already running."""
        if self.probing:
            return False
        targets = servers if servers is not None else self.store.servers
        timeout = self.settings.probe_timeout

        def work() -> None:
            results = status.probe_many(targets, timeout=timeout)
            status.attach_telemetry(targets, results, self.telemetry_cache())
            with self._lock:
                self.statuses.update(results)
                known = {s.id for s in self.store.servers}
                for sid in list(self.statuses):
                    if sid not in known:
                        del self.statuses[sid]
            self.last_probe = time.monotonic()
            try:
                self._observe()
            except Exception:  # history/alerts must never break status updates
                logging.getLogger(__name__).exception("recording history failed")
            if self.on_statuses:
                self.on_statuses()

        self._probe = self._pool.submit(work)
        return True

    def tick(self) -> bool:
        """Housekeeping for polling front-ends. Returns True if anything changed."""
        now = time.monotonic()
        changed = False
        if now - self._last_store_check > 1.5:
            self._last_store_check = now
            if self.store.reload_if_changed():
                changed = True
                self.refresh()
        interval = self.settings.refresh_interval
        if interval > 0 and now - self.last_probe >= interval and not self.probing:
            self.refresh()
        if now - self._last_disc_check > 5.0 and self.statuses:
            self._last_disc_check = now
            self._auto_discover()
        if now - self._last_tel > 1.0:
            self._last_tel = now
            self.reattach_telemetry()
            changed = True
        return changed

    # --------------------------------------------------------------- history
    @property
    def history(self) -> History:
        if self._history is None:
            self._history = History()
        return self._history

    @property
    def recording(self) -> bool:
        """Only the process that owns the telemetry listener writes history and raises alerts."""
        return self.listener is not None

    def _observe(self) -> None:
        if not self.recording:
            return
        with self._observe_lock:
            servers = self.store.servers
            for srv in servers:
                st = self.statuses.get(srv.id)
                if st is None:
                    continue
                tel = st.telemetry
                self.history.record(srv.id, st.online, st.latency_ms,
                                    tel.cpu if tel else None, tel.mem_pct if tel else None,
                                    tel.disk_pct if tel else None)
            events = self.alerts.evaluate(servers, self.statuses, self.host_containers())
            for ev in events:
                self.history.add_event(ev)
        if events and self.on_events:
            self.on_events(events)

    # ------------------------------------------------------------ containers
    def addresses(self) -> dict[str, str]:
        return {sid: st.address for sid, st in self.statuses.items() if st.address}

    def host_containers(self) -> dict[str, HostContainers]:
        """Per-host container lists: live agent data wins over (older) SSH discovery."""
        out: dict[str, HostContainers] = {}
        for srv in self.store.servers:
            st = self.statuses.get(srv.id)
            tel = st.telemetry if st else None
            if tel is not None and tel.containers is not None:
                out[srv.id] = HostContainers(srv.id, containers.from_agent(tel.containers, tel.runtime or "docker"),
                                             runtime=tel.runtime or "docker", source="agent", fetched=tel.received)
                ssh = self.ssh_containers.get(srv.id)
                if ssh and ssh.runtime:  # keep the runtime prefix SSH found (e.g. "sudo -n docker")
                    for c in out[srv.id].containers:
                        c.runtime = ssh.runtime
            elif srv.id in self.ssh_containers:
                out[srv.id] = self.ssh_containers[srv.id]
        return out

    def links(self) -> dict[str, ContainerLink]:
        hosts = {k: v for k, v in self.host_containers().items() if v.containers}
        return containers.link_servers(self.store.servers, hosts, self.addresses())

    def discover_containers(self, host: Server, force: bool = False) -> bool:
        """Ask *host* for its containers over SSH in the background."""
        if host.id in self._disc_running:
            return False
        if not force and time.monotonic() < self._disc_next.get(host.id, 0):
            return False
        self._disc_running.add(host.id)

        def work() -> None:
            try:
                result = containers.discover(host)
                self._disc_next[host.id] = time.monotonic() + 60
            except containers.ContainerError as exc:
                result = HostContainers(host.id, [], error=str(exc), fetched=time.time())
                self._disc_next[host.id] = time.monotonic() + 600  # back off: probably no key auth
            if result.error and not result.containers:
                self._disc_next[host.id] = time.monotonic() + 600
            self.ssh_containers[host.id] = result
            self._disc_running.discard(host.id)
            try:
                self._observe()
            except Exception:
                logging.getLogger(__name__).exception("recording history failed")
            if self.on_containers:
                self.on_containers()

        self._disc_pool.submit(work)
        return True

    def _auto_discover(self) -> None:
        # One discovery at a time: the likeliest host is asked first, and its answer usually
        # identifies the sibling profiles as containers, so they never get asked at all.
        if self._disc_running:
            return
        agent_hosts = {sid for sid, hc in self.host_containers().items() if hc.source == "agent"}
        linked = set(self.links())
        for host in containers.candidate_hosts(self.store.servers, self.addresses()):
            st = self.statuses.get(host.id)
            if host.id in agent_hosts or host.id in linked or st is None or not st.online:
                continue
            if self.discover_containers(host):
                return

    def minecraft_status(self, host: str, port: int):
        """Cached Minecraft status for host:port (MinecraftStatus, error string, or None while checking).

        Refreshes in the background every 20 seconds while something keeps asking.
        """
        from sshm.core import minecraft

        key = f"{host}:{port}"
        checked, value = self._mc.get(key, (0.0, None))
        if time.monotonic() - checked > 20 and key not in self._mc_running:
            self._mc_running.add(key)

            def work() -> None:
                try:
                    result: object = minecraft.ping(host, port)
                except (OSError, ValueError) as exc:
                    result = str(exc) or exc.__class__.__name__
                self._mc[key] = (time.monotonic(), result)
                self._mc_running.discard(key)

            self._disc_pool.submit(work)
        return value

    def service_ports(self, link: ContainerLink) -> list[tuple[str, int, containers.PortMap]]:
        """(public host, public port, mapping) for each published port of a linked container."""
        return [(link.host.host, p.host_port, p) for p in link.container.ports]

    def status_of(self, server: Server) -> HostStatus | None:
        return self.statuses.get(server.id)

    def summary(self, servers: list[Server] | None = None) -> tuple[int, int]:
        servers = self.store.servers if servers is None else servers
        online = sum(1 for s in servers if (st := self.statuses.get(s.id)) and st.online)
        return online, len(servers)

    def close(self) -> None:
        if self.listener:
            self.listener.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._disc_pool.shutdown(wait=False, cancel_futures=True)
