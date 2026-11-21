"""Container menus for the TUI: per-container actions and a host's container list."""

from __future__ import annotations

from typing import Any

from sshm.core import containers
from sshm.core.containers import Container
from sshm.core.models import Server
from sshm.tui.widgets import ChoiceModal, ConfirmModal, Option, ProgressModal


def state_dot(c: Container) -> tuple[str, str]:
    if c.running:
        return ("●", "warning") if c.health == "unhealthy" else ("●", "success")
    if c.state in ("paused", "restarting"):
        return "◐", "warning"
    return "○", "danger"


def describe(c: Container) -> str:
    bits = [c.image_short]
    if c.running and c.cpu is not None:
        bits.append(f"cpu {c.cpu:.1f}%")
    if c.mem:
        bits.append(f"mem {c.mem_label.split(' / ')[0]}")
    bits.append(c.status or c.state)
    return " · ".join(bits)


def container_menu(ui: Any, host: Server, c: Container, *, linked_server: Server | None = None) -> None:
    """Action picker for one container on *host*."""
    opts = []
    if c.running:
        opts += [Option("restart", "Restart", "stop and start again", "r", "warning"),
                 Option("stop", "Stop", "", "s", "danger")]
    else:
        opts.append(Option("start", "Start", "", "s", "success"))
    opts += [
        Option("logs", "Follow logs", "last 200 lines, then live (Ctrl+C to leave)", "l"),
        Option("shell", "Shell inside container", f"{c.cli} exec -it … bash/sh", "e"),
        Option("stats", "Live stats", f"{c.cli} stats", "t"),
    ]
    if linked_server is not None:
        opts.append(Option("host", f"Go to host: {host.name}", host.endpoint, "h", "info"))
    sub = f"{c.image_short} · {c.status or c.state} · on {host.name}"
    choice = ChoiceModal(ui, f"Container — {c.name}", opts, sub).run()
    if choice is None:
        return
    if choice == "host":
        ui.sel_id = host.id
        ui.query, ui.tag = "", "ALL"
        return
    if choice == "logs":
        ui.suspend_run(containers.logs_argv(host, c), f"logs · {c.name} on {host.name}")
        return
    if choice == "shell":
        ui.suspend_run(containers.shell_argv(host, c), f"shell · {c.name} on {host.name}")
        return
    if choice == "stats":
        ui.suspend_run(containers.stats_argv(host, c), f"stats · {c.name} on {host.name}")
        return
    if choice == "stop" and not ConfirmModal(ui, "Stop container", f"Stop '{c.name}' on {host.name}?",
                                             "Stop", danger=True).run():
        return
    res = ProgressModal(ui, f"{choice.capitalize()} {c.name}",
                        lambda _p, _cancel: containers.run_action(host, c, choice),
                        f"{c.runtime} {choice} {c.name}…").run()
    if isinstance(res, Exception):
        ui.notify(f"{choice} failed: {res}", "error")
    else:
        ui.notify(str(res), "success")
    ui.hub.discover_containers(host, force=True)


def host_menu(ui: Any, host: Server) -> None:
    """List a host's containers (discovering them first if needed) and act on one."""
    hc = ui.hub.host_containers().get(host.id)
    if hc is None or (not hc.containers and not hc.error):
        def discover(_p: object, _c: object) -> object:
            try:
                return containers.discover(host)
            except containers.ContainerError as exc:
                return exc

        res = ProgressModal(ui, "Detecting containers", discover, f"Asking {host.name} for docker / podman…").run()
        if isinstance(res, Exception):
            ui.notify(f"Container discovery failed: {res}", "error")
            return
        if res is None:
            return
        ui.hub.ssh_containers[host.id] = res
        hc = res
    if not hc.containers:
        ui.notify(hc.error or f"No containers on {host.name}", "warning")
        return
    links = ui.hub.links()
    by_ctr = {(lk.host.id, lk.container.name): sid for sid, lk in links.items()}
    opts = []
    for c in hc.containers:
        dot, role = state_dot(c)
        saved = by_ctr.get((host.id, c.name))
        label = f"{dot} {c.name}"
        desc = describe(c) + (f" · saved as {ui.store.get(saved).name}" if saved and ui.store.get(saved) else "")
        opts.append(Option(c.name, label, desc, style=role))
    running = sum(1 for c in hc.containers if c.running)
    sub = f"{running}/{len(hc.containers)} running · via {hc.source} · {hc.runtime}"
    choice = ChoiceModal(ui, f"Containers on {host.name}", opts, sub).run()
    if choice is None:
        return
    ctr = next(c for c in hc.containers if c.name == choice)
    container_menu(ui, host, ctr)
