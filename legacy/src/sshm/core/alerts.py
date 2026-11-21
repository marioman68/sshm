"""Alert rules evaluated on every status update.

Alerts fire on *observed transitions* only (good → bad), so a machine that is
always off, or a container that was stopped on purpose weeks ago, never alerts
just because sshm started. Each alert resolves (with an "info" event) when the
condition clears. Only servers with "Monitor in tray" enabled are watched.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sshm.core.containers import HostContainers
from sshm.core.history import Event
from sshm.core.models import Server
from sshm.core.settings import Settings
from sshm.core.status import HostStatus


@dataclass
class _Track:
    bad_since: float | None = None   # when the condition started (for sustain / grace periods)
    firing: bool = False
    seen_good: bool = False          # baseline: only alert after we have seen the healthy state


class AlertEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tracks: dict[tuple[str, str], _Track] = {}

    def _check(self, srv: Server, key: str, bad: bool | None, now: float, hold: float, severity: str,
               fire_msg: str, clear_msg: str) -> Event | None:
        """bad=None means "unknown" (no data): keep the current state."""
        if bad is None:
            return None
        tr = self._tracks.setdefault((srv.id, key), _Track())
        kind = key  # e.g. "cpu" or "container:minecraft" (unique per server in the active table)
        if not bad:
            tr.bad_since = None
            tr.seen_good = True
            if tr.firing:
                tr.firing = False
                return Event(now, srv.id, srv.name, kind, "info", clear_msg, resolved=True)
            return None
        if not tr.seen_good:
            return None
        if tr.bad_since is None:
            tr.bad_since = now
        if not tr.firing and now - tr.bad_since >= hold:
            tr.firing = True
            return Event(now, srv.id, srv.name, kind, severity, fire_msg)
        return None

    def evaluate(self, servers: list[Server], statuses: dict[str, HostStatus],
                 hosts: dict[str, HostContainers] | None = None, now: float | None = None) -> list[Event]:
        s = self.settings
        if not s.alerts_enabled:
            return []
        now = now or time.time()
        hosts = hosts or {}
        sustain = s.alert_sustain_minutes * 60
        events: list[Event] = []

        def add(ev: Event | None) -> None:
            if ev:
                events.append(ev)

        for srv in servers:
            if not srv.tray:
                continue
            st = statuses.get(srv.id)
            if st is None:
                continue
            add(self._check(srv, "offline", not st.online, now, s.alert_offline_grace, "critical",
                            f"{srv.name} is down ({st.error or 'unreachable'})", f"{srv.name} is back online"))
            tel = st.telemetry if st.online else None
            if tel is not None:
                add(self._check(srv, "cpu", None if tel.cpu is None else tel.cpu >= s.alert_cpu, now, sustain,
                                "warning", f"{srv.name}: CPU at {tel.cpu or 0:.0f}% for {s.alert_sustain_minutes} min",
                                f"{srv.name}: CPU back to normal"))
                add(self._check(srv, "mem", None if tel.mem_pct is None else tel.mem_pct >= s.alert_mem, now, sustain,
                                "warning", f"{srv.name}: memory at {tel.mem_pct or 0:.0f}%",
                                f"{srv.name}: memory back to normal"))
                add(self._check(srv, "disk", None if tel.disk_pct is None else tel.disk_pct >= s.alert_disk, now, 0,
                                "warning", f"{srv.name}: disk / is {tel.disk_pct or 0:.0f}% full",
                                f"{srv.name}: disk usage back under {s.alert_disk}%"))
                add(self._check(srv, "reboot", tel.reboot_required, now, 0, "info",
                                f"{srv.name} needs a reboot (updated kernel)", f"{srv.name} was rebooted"))

            hc = hosts.get(srv.id)
            for ctr in hc.containers if hc else []:
                key = f"container:{ctr.name}"
                add(self._check(srv, key, not ctr.running, now, 30, "warning",
                                f"Container {ctr.name} on {srv.name} stopped ({ctr.status or ctr.state})",
                                f"Container {ctr.name} on {srv.name} is running again"))
                if ctr.running:
                    unhealthy = ctr.health == "unhealthy" if ctr.health else None
                    add(self._check(srv, f"unhealthy:{ctr.name}", unhealthy, now, 0, "warning",
                                    f"Container {ctr.name} on {srv.name} is unhealthy",
                                    f"Container {ctr.name} on {srv.name} is healthy again"))
        return events
