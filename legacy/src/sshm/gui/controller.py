"""Qt bridge around :class:`sshm.core.hub.Hub`: signals, timers and actions.

Shared by the main window and the tray. Every blocking operation runs on a
worker thread; results come back to the GUI thread through a queued signal.
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from sshm.core import agent, mounts, sshcmd, terminal, wol
from sshm.core.hub import Hub
from sshm.core.models import Server
from sshm.core.status import HostStatus
from sshm.core.tunnels import Tunnel, TunnelError, TunnelSpec


class Controller(QObject):
    statuses_changed = pyqtSignal()
    servers_changed = pyqtSignal()
    settings_changed = pyqtSignal()
    tunnels_changed = pyqtSignal()
    message = pyqtSignal(str, str)                 # text, level: info|success|warning|error
    server_state_changed = pyqtSignal(str, bool)   # server id, online
    show_window_requested = pyqtSignal()
    events_raised = pyqtSignal(object)             # list[history.Event] from the alert engine
    _task_done = pyqtSignal(int, object)
    _bg_statuses = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.hub = Hub()
        self.listening = self.hub.start_listener(on_update=self._on_telemetry)
        self._callbacks: dict[int, Callable[[Any], None]] = {}
        self._ids = itertools.count(1)
        self._known_state: dict[str, bool] = {}
        self._task_done.connect(self._dispatch_done)
        self._bg_statuses.connect(self._statuses_arrived)
        self.hub.on_statuses = self._bg_statuses.emit
        self.hub.on_containers = self._bg_statuses.emit
        self.hub.on_events = self.events_raised.emit
        self._last_store_sig = self._store_sig()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.hub.refresh()

    # ---------------------------------------------------------- properties
    @property
    def store(self):
        return self.hub.store

    @property
    def settings(self):
        return self.hub.settings

    @property
    def servers(self) -> list[Server]:
        return self.hub.store.servers

    def status(self, srv: Server) -> HostStatus | None:
        return self.hub.status_of(srv)

    # --------------------------------------------------------------- loop
    def _store_sig(self) -> tuple:
        return tuple((s.id, s.name, s.host, s.port, s.tag, s.favorite, s.tray, len(s.commands)) for s in self.servers)

    def _tick(self) -> None:
        self.hub.tick()
        sig = self._store_sig()
        if sig != self._last_store_sig:
            self._last_store_sig = sig
            self.servers_changed.emit()
        self.statuses_changed.emit()

    def _on_telemetry(self, _keys: list[str], changed: bool) -> None:
        # runs on the listener thread; a state flip deserves an immediate re-probe
        if changed:
            self._bg_statuses.emit()

    def _statuses_arrived(self) -> None:
        self.hub.reattach_telemetry()
        for srv in self.servers:
            st = self.hub.status_of(srv)
            if st is None:
                continue
            prev = self._known_state.get(srv.id)
            self._known_state[srv.id] = st.online
            if prev is not None and prev != st.online:
                self.server_state_changed.emit(srv.id, st.online)
        self.statuses_changed.emit()

    def refresh(self, servers: list[Server] | None = None) -> None:
        if self.hub.refresh(servers):
            self.message.emit("Refreshing server status…", "info")

    def saved(self) -> None:
        """Call after mutating the store so every view updates immediately."""
        self._last_store_sig = self._store_sig()
        self.servers_changed.emit()
        self.hub.refresh()

    # -------------------------------------------------------------- async
    def run_async(self, fn: Callable[[], Any], done: Callable[[Any], None] | None = None) -> None:
        task_id = next(self._ids)
        if done:
            self._callbacks[task_id] = done

        def work() -> None:
            try:
                result = fn()
            except Exception as exc:  # delivered to the callback
                result = exc
            self._task_done.emit(task_id, result)

        threading.Thread(target=work, daemon=True, name=f"sshm-task-{task_id}").start()

    def _dispatch_done(self, task_id: int, result: object) -> None:
        cb = self._callbacks.pop(task_id, None)
        if cb:
            cb(result)

    # ------------------------------------------------------------ actions
    def launch(self, argv: list[str], title: str, pause: bool = False) -> bool:
        try:
            terminal.launch(sshcmd.hold(argv, title, pause), self.settings.terminal)
        except terminal.TerminalNotFound as exc:
            self.message.emit(str(exc), "error")
            return False
        except OSError as exc:
            self.message.emit(f"Could not start terminal: {exc}", "error")
            return False
        return True

    def connect(self, srv: Server, tmux: bool | None = None) -> None:
        argv = sshcmd.ssh_command(srv, tmux=tmux, tmux_session=self.settings.tmux_session)
        if self.launch(argv, f"{srv.name} · {srv.endpoint}"):
            self.store.mark_connected(srv.id)
            self.message.emit(f"Opening terminal for {srv.name}", "info")

    def sftp(self, srv: Server) -> None:
        self.launch(sshcmd.sftp_command(srv), f"SFTP · {srv.name}")

    def push_key(self, srv: Server) -> None:
        self.launch(sshcmd.copy_id_command(srv), f"Push SSH key · {srv.name}", pause=True)

    def run_command(self, srv: Server, label: str, command: str) -> None:
        self.launch(sshcmd.ssh_command(srv, remote_command=command), f"{label} · {srv.name}", pause=True)

    def copy_command(self, srv: Server) -> None:
        text = sshcmd.display(sshcmd.ssh_command(srv, tmux_session=self.settings.tmux_session))
        QApplication.clipboard().setText(text)
        self.message.emit(f"Copied: {text}", "success")

    def open_files(self, srv: Server) -> None:
        if mounts.open_in_file_manager(srv):
            self.message.emit(f"Opening {srv.sftp_url}", "info")
        else:
            self.message.emit("xdg-open is not available", "error")

    def toggle_bookmark(self, srv: Server) -> None:
        try:
            state = mounts.toggle_bookmark(srv, self.settings)
        except OSError as exc:
            self.message.emit(f"Bookmark failed: {exc}", "error")
            return
        self.message.emit(f"{'Bookmarked' if state else 'Removed bookmark for'} {srv.name}", "success")
        self.statuses_changed.emit()

    def toggle_sshfs(self, srv: Server) -> None:
        mounted = mounts.is_sshfs_mounted(srv, self.settings)
        self.message.emit(("Unmounting " if mounted else "Mounting ") + srv.name + "…", "info")
        fn = mounts.sshfs_unmount if mounted else mounts.sshfs_mount

        def done(res: object) -> None:
            if isinstance(res, Exception):
                self.message.emit(f"SSHFS error: {res}", "error")
            else:
                ok, msg = res  # type: ignore[misc]
                if not ok and not mounted and mounts.sshfs_available():
                    msg += " — SSHFS needs key-based login (use Push SSH key)"
                self.message.emit(msg, "success" if ok else "error")
                if ok and not mounted:
                    _xdg_open(str(mounts.sshfs_mountpoint(srv, self.settings)))
            self.statuses_changed.emit()

        self.run_async(lambda: fn(srv, self.settings), done)

    def wake(self, srv: Server) -> None:
        if not srv.mac:
            self.message.emit(f"{srv.name} has no MAC address — edit it and use Detect", "warning")
            return
        try:
            wol.wake(srv.mac)
        except (OSError, ValueError) as exc:
            self.message.emit(f"Wake-on-LAN failed: {exc}", "error")
            return
        self.message.emit(f"Magic packet sent to {srv.name} ({srv.mac})", "success")

    def start_tunnel(self, srv: Server, spec: TunnelSpec, done: Callable[[object], None] | None = None) -> None:
        def finished(res: object) -> None:
            if isinstance(res, TunnelError):
                self.message.emit(f"Tunnel failed: {res}", "error")
            elif isinstance(res, Exception):
                self.message.emit(f"Tunnel error: {res}", "error")
            else:
                self.message.emit(f"Tunnel up: {spec.describe(srv.name)}", "success")
            self.tunnels_changed.emit()
            if done:
                done(res)

        self.run_async(lambda: self.hub.tunnels.start(srv, spec), finished)

    def stop_tunnel(self, tunnel: Tunnel) -> None:
        self.hub.tunnels.stop(tunnel.id)
        self.message.emit(f"Stopped tunnel -{tunnel.kind} {tunnel.spec}", "success")
        self.tunnels_changed.emit()

    def deploy_agent(self, srv: Server, remove: bool = False) -> None:
        """Try key-based (non-interactive) first; fall back to a terminal for passwords/sudo prompts."""
        script = agent.build_remover() if remove else agent.build_installer(srv, self.settings)
        verb = "Removing agent from" if remove else "Deploying agent to"
        self.message.emit(f"{verb} {srv.name}…", "info")

        def done(res: object) -> None:
            if isinstance(res, Exception) or getattr(res, "returncode", 1) == 255:
                path = agent.write_script(script)
                if self.launch(sshcmd.with_stdin_file(agent.remote_script_argv(srv), path), f"{verb} {srv.name}",
                               pause=True):
                    self.message.emit("Key login unavailable — continuing in a terminal", "info")
                else:
                    os.unlink(path)
                return
            rc = getattr(res, "returncode", 1)
            out = (getattr(res, "stdout", "") or getattr(res, "stderr", "")).strip().splitlines()
            if rc == 0:
                self.message.emit(out[-1] if out else "Done", "success")
            else:
                err = (getattr(res, "stderr", "") or "").strip().splitlines()
                self.message.emit(f"Agent {'removal' if remove else 'install'} failed: {err[-1] if err else rc}",
                                  "error")

        self.run_async(lambda: agent.run_noninteractive(srv, script), done)

    # ---------------------------------------------------------- containers
    def container_action(self, host: Server, ctr, action: str) -> None:
        from sshm.core import containers

        self.message.emit(f"{action.capitalize()} {ctr.name}…", "info")

        def done(res: object) -> None:
            if isinstance(res, Exception):
                self.message.emit(f"{action} {ctr.name} failed: {res}", "error")
            else:
                self.message.emit(str(res), "success")
            self.hub.discover_containers(host, force=True)

        self.run_async(lambda: containers.run_action(host, ctr, action), done)

    def container_logs(self, host: Server, ctr) -> None:
        from sshm.core import containers

        self.launch(containers.logs_argv(host, ctr), f"logs · {ctr.name} on {host.name}")

    def container_shell(self, host: Server, ctr) -> None:
        from sshm.core import containers

        self.launch(containers.shell_argv(host, ctr), f"shell · {ctr.name} on {host.name}")

    def container_stats(self, host: Server, ctr=None) -> None:
        from sshm.core import containers

        self.launch(containers.stats_argv(host, ctr), f"stats · {host.name}")

    def detect_containers(self, host: Server) -> None:
        if self.hub.discover_containers(host, force=True):
            self.message.emit(f"Looking for docker / podman containers on {host.name}…", "info")

    def agent_status(self, srv: Server) -> None:
        self.launch(sshcmd.ssh_command(srv, remote_command=agent.STATUS_COMMAND), f"Agent status · {srv.name}",
                    pause=True)

    def launch_tui(self) -> None:
        exe = shutil.which("sshm")
        self.launch([exe] if exe else [sys.executable, "-m", "sshm"], "sshm")

    def shutdown(self) -> None:
        self.timer.stop()
        self.hub.close()


def _xdg_open(target: str) -> None:
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
