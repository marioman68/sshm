"""Command-line interface. ``sshm`` with no arguments opens the terminal UI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from sshm import APP_TITLE, __version__
from sshm.core import agent, containers, fleet, minecraft, netscan, procs, sshcmd, sshconfig, status, wol
from sshm.core.models import CustomCommand, Server, normalize_mac
from sshm.core.settings import Settings
from sshm.core.store import ServerStore, StoreError
from sshm.core.tunnels import TunnelError, TunnelManager, TunnelSpec


# ------------------------------------------------------------------ output
class Style:
    def __init__(self, enabled: bool) -> None:
        self.on = enabled

    def __call__(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text

    def ok(self, t: str) -> str:
        return self(t, "32")

    def bad(self, t: str) -> str:
        return self(t, "31")

    def dim(self, t: str) -> str:
        return self(t, "2")

    def bold(self, t: str) -> str:
        return self(t, "1")

    def accent(self, t: str) -> str:
        return self(t, "36")


S = Style(sys.stdout.isatty() and not os.environ.get("NO_COLOR"))


def table(rows: list[list[str]], header: list[str]) -> str:
    import re

    def vis(s: str) -> int:
        return len(re.sub(r"\033\[[0-9;]*m", "", s))

    widths = [max(vis(r[i]) for r in [header, *rows]) for i in range(len(header))]
    lines = ["  ".join(S.bold(h.ljust(w)) for h, w in zip(header, widths, strict=True))]
    for r in rows:
        lines.append("  ".join(c + " " * (w - vis(c)) for c, w in zip(r, widths, strict=True)))
    return "\n".join(lines)


def exec_or_die(argv: list[str]) -> int:
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        return die(f"'{argv[0]}' is not installed (install the openssh client package)", 127)
    return 0  # pragma: no cover


def die(msg: str, code: int = 1) -> int:
    print(f"{S.bad('error:')} {msg}", file=sys.stderr)
    return code


# --------------------------------------------------------------- commands
def cmd_list(args: argparse.Namespace, store: ServerStore) -> int:
    servers = [s for s in store.servers if not args.tag or s.tag.lower() == args.tag.lower()]
    statuses = status.probe_many(servers, timeout=Settings.load().probe_timeout) if args.status else {}
    if args.json:
        out = []
        for s in servers:
            d = s.to_dict()
            if s.id in statuses:
                st = statuses[s.id]
                d["status"] = {"online": st.online, "latency_ms": st.latency_ms, "banner": st.banner}
            out.append(d)
        print(json.dumps(out, indent=2))
        return 0
    if not servers:
        print("No servers. Add one with 'sshm add', 'sshm scan' or 'sshm import'.")
        return 0
    rows = []
    for s in servers:
        row = [("★ " if s.favorite else "  ") + s.name, s.endpoint, s.tag or S.dim("-")]
        if args.status:
            st = statuses.get(s.id)
            if st and st.online:
                cpu = f" cpu {st.telemetry.cpu:.0f}%" if st.telemetry and st.telemetry.cpu is not None else ""
                row.append(S.ok(f"● {st.latency_label}") + S.dim(cpu))
            else:
                row.append(S.bad("○ offline") + (S.dim(f" ({st.error})") if st and st.error else ""))
        rows.append(row)
    print(table(rows, ["NAME", "ENDPOINT", "TAG", *(["STATUS"] if args.status else [])]))
    return 0


def cmd_connect(args: argparse.Namespace, store: ServerStore) -> int:
    srv = store.find(args.name)
    settings = Settings.load()
    remote = " ".join(args.command) if args.command else None
    tmux = True if args.tmux else (False if args.no_tmux else None)
    argv = sshcmd.ssh_command(srv, tmux=tmux, remote_command=remote, tmux_session=settings.tmux_session)
    if args.print:
        print(sshcmd.display(argv))
        return 0
    store.mark_connected(srv.id)
    return exec_or_die(argv)


def cmd_sftp(args: argparse.Namespace, store: ServerStore) -> int:
    argv = sshcmd.sftp_command(store.find(args.name))
    return exec_or_die(argv)


def cmd_add(args: argparse.Namespace, store: ServerStore) -> int:
    host, user, port = args.host, args.user or "", args.port
    if "@" in host:
        user, host = host.split("@", 1)
    if host.count(":") == 1:
        host, p = host.split(":")
        port = int(p)
    srv = Server(name=args.name or host, host=host, user=user or os.environ.get("USER", ""), port=port,
                 tag=args.tag or "", key=args.key or "", jump=args.jump or "", tmux=args.tmux)
    try:
        srv.mac = normalize_mac(args.mac or "")
    except ValueError as exc:
        return die(str(exc))
    store.add(srv)
    print(f"{S.ok('✔')} added {S.bold(srv.name)} ({srv.endpoint})")
    return 0


def cmd_remove(args: argparse.Namespace, store: ServerStore) -> int:
    srv = store.find(args.name)
    if not args.yes:
        if not sys.stdin.isatty():
            return die("refusing to delete without --yes in a non-interactive shell")
        if input(f"Delete '{srv.name}' ({srv.endpoint})? [y/N] ").strip().lower() != "y":
            return 1
    store.remove(srv.id)
    print(f"{S.ok('✔')} removed {srv.name}")
    return 0


def cmd_status(args: argparse.Namespace, store: ServerStore) -> int:
    args.status = True
    return cmd_list(args, store)


def cmd_wake(args: argparse.Namespace, store: ServerStore) -> int:
    srv = store.find(args.name)
    if not srv.mac:
        return die(f"{srv.name} has no MAC address (sshm edit it, or rescan with 'sshm scan')")
    wol.wake(srv.mac, args.broadcast)
    print(f"{S.ok('✔')} magic packet sent to {srv.name} ({srv.mac})")
    if args.wait:
        print(S.dim(f"waiting up to {args.wait}s for SSH…"), end="", flush=True)
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline:
            if status.probe(srv.host, srv.port, 1.0).online:
                print(f"\r{S.ok('●')} {srv.name} is up after {args.wait - int(deadline - time.monotonic())}s   ")
                return 0
            time.sleep(2)
        print()
        return die("timed out waiting for SSH")
    return 0


def cmd_scan(args: argparse.Namespace, store: ServerStore) -> int:
    try:
        targets = netscan.parse_targets(args.network or netscan.local_network())
        ports = netscan.parse_ports(args.ports)
    except ValueError as exc:
        return die(str(exc))
    tty = sys.stderr.isatty()

    def progress(done: int, total: int) -> None:
        if tty:
            print(f"\r{S.dim(f'scanning {done}/{total}')}", end="", file=sys.stderr, flush=True)

    found = netscan.scan(targets, ports, progress=progress)
    if tty:
        print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
    existing = {(s.host, s.port): s for s in store.servers}
    if args.json:
        print(json.dumps([d.__dict__ for d in found], indent=2))
        return 0
    if not found:
        print("No SSH servers found.")
        return 0
    rows = []
    for d in found:
        saved = existing.get((d.ip, d.port))
        rows.append([f"{d.ip}:{d.port}", d.hostname or S.dim("-"), d.banner, d.mac or S.dim("-"),
                     S.dim(f"saved: {saved.name}") if saved else S.ok("new")])
    print(table(rows, ["ADDRESS", "HOSTNAME", "SSH", "MAC", ""]))
    if args.add:
        added = 0
        for d in found:
            if (d.ip, d.port) in existing:
                continue
            store.add(Server(name=store.unique_name(d.suggested_name), host=d.ip, port=d.port,
                             user=args.user or os.environ.get("USER", ""), tag=args.tag, mac=d.mac))
            added += 1
        print(f"{S.ok('✔')} added {added} server(s)")
    return 0


def cmd_import(args: argparse.Namespace, store: ServerStore) -> int:
    from pathlib import Path

    candidates = sshconfig.import_servers(store.servers, Path(args.file).expanduser() if args.file else None)
    if not candidates:
        print("Nothing new to import.")
        return 0
    for srv in candidates:
        print(f"  {S.ok('+')} {srv.name:<24} {srv.endpoint}{' via ' + srv.jump if srv.jump else ''}")
        if not args.dry_run:
            srv.name = store.unique_name(srv.name)
            store.add(srv)
    print(("would import" if args.dry_run else "imported") + f" {len(candidates)} host(s)")
    return 0


def cmd_export(args: argparse.Namespace, store: ServerStore) -> int:
    servers = [s for s in store.servers if not args.tag or s.tag.lower() == args.tag.lower()]
    sys.stdout.write(sshconfig.export(servers))
    return 0


def cmd_tunnel(args: argparse.Namespace, store: ServerStore) -> int:
    mgr = TunnelManager()
    if args.action == "list" or args.action is None:
        tunnels = mgr.list()
        if not tunnels:
            print("No active tunnels.")
            return 0
        print(table([[t.id[:8], t.server_name, f"-{t.kind} {t.spec}", str(t.pid),
                      time.strftime("%H:%M", time.localtime(t.started))] for t in tunnels],
                    ["ID", "SERVER", "FORWARD", "PID", "SINCE"]))
        return 0
    if args.action == "stop":
        if args.target == "all":
            print(f"stopped {mgr.stop_all()} tunnel(s)")
            return 0
        return 0 if mgr.stop(args.target) else die(f"no tunnel '{args.target}'")
    srv = store.find(args.target)
    kind, spec_text = ("L", args.local) if args.local else ("R", args.remote) if args.remote else ("D", args.socks)
    if not spec_text:
        return die("give one of -L port:host:port, -R port:host:port or -D port")
    try:
        spec = TunnelSpec.parse(kind, spec_text)
        t = mgr.start(srv, spec)
    except TunnelError as exc:
        return die(str(exc))
    print(f"{S.ok('✔')} {spec.describe(srv.name)}  {S.dim(f'(id {t.id[:8]}, pid {t.pid})')}")
    return 0


def cmd_run(args: argparse.Namespace, store: ServerStore) -> int:
    srv = store.find(args.name)
    if args.add:
        if not args.label:
            return die("usage: sshm run NAME --add 'command' LABEL")
        srv.commands.append(CustomCommand(" ".join(args.label), args.add))
        store.update(srv)
        print(f"{S.ok('✔')} saved command '{' '.join(args.label)}' for {srv.name}")
        return 0
    if not args.label:
        if not srv.commands:
            print(f"{srv.name} has no saved commands. Add one: sshm run {srv.name} --add 'uptime' Uptime")
        for i, c in enumerate(srv.commands, 1):
            print(f"  {S.accent(str(i))}. {S.bold(c.label)}  {S.dim(c.command)}")
        return 0
    label = " ".join(args.label)
    cmd = next((c for i, c in enumerate(srv.commands, 1) if c.label.lower() == label.lower() or str(i) == label), None)
    if not cmd:
        return die(f"no command '{label}' on {srv.name}")
    argv = sshcmd.ssh_command(srv, remote_command=cmd.command)
    return exec_or_die(argv)


def cmd_agent(args: argparse.Namespace, store: ServerStore) -> int:
    srv = store.find(args.name)
    settings = Settings.load()
    if args.action == "status":
        argv = sshcmd.ssh_command(srv, remote_command=agent.STATUS_COMMAND)
        return subprocess.call(argv)
    script = agent.build_installer(srv, settings, hub=args.hub or "") if args.action == "deploy" \
        else agent.build_remover()
    if args.action == "deploy":
        hub = args.hub or agent.hub_address_for(srv.host)
        print(S.dim(f"agent will report to {hub}:{settings.telemetry_port}/udp"))
    return subprocess.run(agent.remote_script_argv(srv), input=script, text=True).returncode


def cmd_ps(args: argparse.Namespace, store: ServerStore) -> int:
    srv = store.find(args.name)
    if args.kill:
        try:
            print(f"{S.ok('✔')} {procs.kill(srv, args.kill, force=args.force)}")
        except procs.ProcError as exc:
            return die(str(exc))
        return 0

    def render() -> int:
        try:
            items = procs.sort(procs.filter_procs(procs.fetch(srv), args.filter or ""), args.sort)
        except procs.ProcError as exc:
            return die(str(exc))
        if args.json:
            print(json.dumps([p.to_dict() for p in items[: args.limit or None]], indent=2))
            return 0
        width = shutil.get_terminal_size((120, 24)).columns
        rows = []
        for p in items[: args.limit or None]:
            cpu = "--" if p.cpu is None else f"{p.cpu:.1f}"
            if p.cpu is not None and p.cpu >= 25:
                cpu = S.bad(cpu) if p.cpu >= 80 else S(cpu, "33")
            rows.append([str(p.pid), p.user[:12], cpu, "--" if p.mem is None else f"{p.mem:.1f}",
                         p.rss_label, p.elapsed_label, p.command[: max(20, width - 60)]])
        print(table(rows, ["PID", "USER", "CPU%", "MEM%", "RSS", "TIME", "COMMAND"]))
        shown = len(rows)
        print(S.dim(f"{shown} of {len(items)} processes on {srv.name} · sorted by {args.sort}"))
        return 0

    if not args.watch:
        return render()
    try:
        while True:
            sys.stdout.write("\033[H\033[2J")
            print(S.bold(f"{srv.name} — every {args.watch}s (Ctrl+C to stop)"))
            if render():
                return 1
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


def cmd_top(args: argparse.Namespace, store: ServerStore) -> int:
    return exec_or_die(procs.top_argv(store.find(args.name)))


def cmd_docker(args: argparse.Namespace, store: ServerStore) -> int:
    srv = store.find(args.name)
    # Is NAME itself a container (published port on a sibling host)? Then resolve its host.
    host, target = srv, args.container
    hosts = containers.candidate_hosts(store.servers)
    for cand in hosts:
        if cand.id != srv.id and cand.host.lower() == srv.host.lower():
            try:
                hc = containers.discover(cand)
            except containers.ContainerError:
                continue
            ctr = hc.by_port(srv.port)
            if ctr:
                host, target = cand, target or ctr.name
                if args.action == "list":
                    args.action = "info"
                break
    try:
        hc = containers.discover(host)
    except containers.ContainerError as exc:
        return die(str(exc))
    if hc.error and not hc.containers:
        return die(f"{host.name}: {hc.error}")
    if args.action == "list":
        if args.json:
            print(json.dumps([{"name": c.name, "image": c.image, "state": c.state, "status": c.status,
                               "cpu": c.cpu, "mem": c.mem, "ports": [p.label for p in c.ports]}
                              for c in hc.containers], indent=2))
            return 0
        rows = [[(S.ok("●") if c.running else S.bad("○")) + " " + c.name, c.image_short[:40], c.status or c.state,
                 "" if c.cpu is None else f"{c.cpu:.1f}%", c.mem_label.split(" / ")[0] if c.mem else "",
                 c.ports_label if c.ports else ""] for c in hc.containers]
        print(table(rows, ["CONTAINER", "IMAGE", "STATUS", "CPU", "MEM", "PORTS"]))
        print(S.dim(f"{host.name} · {hc.runtime}"))
        return 0
    if not target:
        return die(f"which container? e.g. sshm docker {host.name} {args.action} <container>")
    ctr = next((c for c in hc.containers if c.name == target or c.id.startswith(target)), None)
    if ctr is None:
        return die(f"no container '{target}' on {host.name}")
    if args.action == "info":
        print(f"{S.bold(ctr.name)} on {host.name}  ({ctr.short_id})")
        for label, value in (("image", ctr.image), ("status", ctr.status or ctr.state), ("ports", ctr.ports_label),
                             ("cpu", "--" if ctr.cpu is None else f"{ctr.cpu:.1f}%"), ("memory", ctr.mem_label),
                             ("compose", ctr.project or "-"), ("runtime", ctr.runtime)):
            print(f"  {label:<8} {value}")
        for p in ctr.ports:
            if p.service == "Minecraft":
                try:
                    mc = minecraft.ping(host.host, p.host_port)
                    print(f"  {'minecraft':<8} {mc.summary} · {mc.motd}")
                except (OSError, ValueError) as exc:
                    print(f"  {'minecraft':<8} not answering ({exc})")
        return 0
    if args.action in containers.ACTIONS:
        try:
            print(f"{S.ok('✔')} {containers.run_action(host, ctr, args.action)}")
        except containers.ContainerError as exc:
            return die(str(exc))
        return 0
    argv = {"logs": containers.logs_argv, "shell": containers.shell_argv,
            "stats": containers.stats_argv}[args.action](host, ctr)
    return exec_or_die(argv)


def _targets(args: argparse.Namespace, store: ServerStore) -> list[Server]:
    if args.all:
        return store.servers
    picked: list[Server] = []
    if args.tag:
        picked += [s for s in store.servers if s.tag.lower() == args.tag.lower()]
    for name in args.servers or []:
        srv = store.find(name)
        if srv not in picked:
            picked.append(srv)
    return picked


def cmd_exec(args: argparse.Namespace, store: ServerStore) -> int:
    command = " ".join(args.command).strip()
    if not command:
        return die("nothing to run — usage: sshm exec -t Homelab -- uptime")
    targets = _targets(args, store)
    if not targets:
        return die("no servers selected (use names, -t TAG or --all)")
    tty = sys.stdout.isatty()
    done = 0

    def progress(res: fleet.RunResult) -> None:
        nonlocal done
        done += 1
        if args.stream:
            mark = S.ok("✔") if res.ok else S.bad("✖")
            print(f"{mark} {S.bold(res.server.name)}  {S.dim(f'{res.seconds:.1f}s')}  {res.summary}")
        elif tty:
            print(f"\r{S.dim(f'{done}/{len(targets)} finished')}", end="", file=sys.stderr, flush=True)

    results = fleet.run_many(targets, command, timeout=args.timeout, parallel=args.parallel, on_result=progress)
    if tty and not args.stream:
        print("\r" + " " * 30 + "\r", end="", file=sys.stderr)
    if args.json:
        print(json.dumps([{"server": r.server.name, "returncode": r.returncode, "stdout": r.stdout,
                           "stderr": r.stderr, "seconds": round(r.seconds, 2)} for r in results], indent=2))
    elif not args.stream:
        for r in results:
            mark = S.ok("✔") if r.ok else S.bad("✖")
            rc = "" if r.ok else S.bad(f" (exit {r.returncode})" if r.returncode is not None else " (did not run)")
            print(f"{mark} {S.bold(r.server.name)}{rc}  {S.dim(f'{r.seconds:.1f}s')}")
            body = (r.stdout + (r.stderr if not r.ok else "")).rstrip()
            for line in body.splitlines()[-args.lines:] if args.lines else body.splitlines():
                print(f"  {S.dim('│')} {line}")
    ok = sum(r.ok for r in results)
    print(S.dim(f"{ok}/{len(results)} succeeded"), file=sys.stderr)
    return 0 if ok == len(results) else 1


def cmd_history(args: argparse.Namespace, store: ServerStore) -> int:
    from sshm.core.history import Availability, History

    hist = History()
    servers = [store.find(args.name)] if args.name else store.servers
    rows = []
    for s in servers:
        a = hist.availability(s.id)
        lat = [x for x in a.latency if x]
        avg = f"{sum(lat) / len(lat):.0f} ms" if lat else "--"
        rows.append([s.name, Availability.label(a.uptime_24h), Availability.label(a.uptime_7d), avg])
    print(table(rows, ["SERVER", "UPTIME 24H", "UPTIME 7D", "AVG LATENCY 24H"]))
    print(S.dim("History is recorded while the sshm tray (or another sshm window) is running."))
    return 0


def cmd_events(args: argparse.Namespace, store: ServerStore) -> int:
    from sshm.core.history import History

    hist = History()
    if args.clear:
        hist.clear_events()
        print("event log cleared")
        return 0
    sid = store.find(args.name).id if args.name else None
    active = hist.active()
    if active and not args.name:
        print(S.bold(f"Active alerts ({len(active)})"))
        for ev in active:
            print(f"  {S.bad('●') if ev.severity == 'critical' else S('●', '33')} {ev.message}")
        print()
    events = hist.events(args.limit, sid)
    if not events:
        print("No events recorded yet.")
        return 0
    for ev in events:
        color = {"critical": S.bad, "warning": lambda t: S(t, "33")}.get(ev.severity, S.ok)
        icon = "✔" if ev.resolved else {"critical": "✖", "warning": "⚠"}.get(ev.severity, "ℹ")
        print(f"{S.dim(ev.time_label):>16}  {color(icon)} {ev.message}")
    return 0


def cmd_backup(args: argparse.Namespace, store: ServerStore) -> int:
    from pathlib import Path

    path = Path(args.file or f"sshm-backup-{time.strftime('%Y%m%d')}.json").expanduser()
    n = fleet.export_backup(store, path)
    print(f"{S.ok('✔')} saved {n} server(s) to {path}  {S.dim('(no keys or secrets included)')}")
    return 0


def cmd_restore(args: argparse.Namespace, store: ServerStore) -> int:
    from pathlib import Path

    try:
        added, updated = fleet.import_backup(store, Path(args.file).expanduser(), replace=args.replace)
    except ValueError as exc:
        return die(str(exc))
    print(f"{S.ok('✔')} restored: {added} added, {updated} updated")
    return 0


def cmd_gui(args: argparse.Namespace, _store: ServerStore) -> int:
    try:
        from sshm.gui.app import main as gui_main
    except ImportError as exc:
        return die(f"the desktop app needs PyQt6 ({exc}). Install python3-pyqt6 from your distribution.")
    return gui_main(["--tray"] if args.tray else ["--gui"])


def cmd_paths(_args: argparse.Namespace, _store: ServerStore) -> int:
    from sshm.core import paths

    for label, p in (("servers", paths.servers_file()), ("settings", paths.settings_file()),
                     ("history", paths.history_file()),
                     ("telemetry", paths.telemetry_cache_file()), ("tunnels", paths.tunnels_file())):
        print(f"{label:<10} {p}")
    return 0


# ----------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sshm",
        description=f"{APP_TITLE} — run without arguments for the terminal UI.",
        epilog="Server names can be abbreviated: 'sshm c nas' connects to 'nas-backup' if unique.",
    )
    p.add_argument("-V", "--version", action="version", version=f"sshm {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name: str, func, help_: str, aliases: tuple[str, ...] = ()) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_, aliases=list(aliases), description=help_)
        sp.set_defaults(func=func)
        return sp

    add("tui", None, "open the terminal UI (default)")
    sp = add("gui", cmd_gui, "open the desktop app")
    sp.add_argument("--tray", action="store_true", help="start minimised to the system tray")

    sp = add("list", cmd_list, "list servers", ("ls",))
    sp.add_argument("-t", "--tag")
    sp.add_argument("-s", "--status", action="store_true", help="probe each server")
    sp.add_argument("--json", action="store_true")

    sp = add("status", cmd_status, "probe all servers and show reachability", ("st",))
    sp.add_argument("-t", "--tag")
    sp.add_argument("--json", action="store_true")

    sp = add("connect", cmd_connect, "ssh into a server", ("c",))
    sp.add_argument("name")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("-m", "--tmux", action="store_true", help="attach/create a tmux session")
    g.add_argument("--no-tmux", action="store_true", help="ignore the server's tmux default")
    sp.add_argument("-p", "--print", action="store_true", help="print the ssh command instead of running it")
    sp.add_argument("command", nargs="*", help="optional remote command (put it after --)")

    sp = add("sftp", cmd_sftp, "open an SFTP shell")
    sp.add_argument("name")

    sp = add("add", cmd_add, "add a server")
    sp.add_argument("host", help="host, user@host or user@host:port")
    sp.add_argument("-n", "--name")
    sp.add_argument("-u", "--user")
    sp.add_argument("-p", "--port", type=int, default=22)
    sp.add_argument("-t", "--tag")
    sp.add_argument("-i", "--key", help="identity file")
    sp.add_argument("-J", "--jump", help="ProxyJump host")
    sp.add_argument("--mac")
    sp.add_argument("--tmux", action="store_true", help="connect with tmux by default")

    sp = add("remove", cmd_remove, "delete a server profile", ("rm",))
    sp.add_argument("name")
    sp.add_argument("-y", "--yes", action="store_true")

    sp = add("wake", cmd_wake, "send a Wake-on-LAN packet")
    sp.add_argument("name")
    sp.add_argument("-b", "--broadcast", default="255.255.255.255")
    sp.add_argument("-w", "--wait", type=int, nargs="?", const=120, default=0,
                    help="wait until SSH answers (default 120s)")

    sp = add("scan", cmd_scan, "discover SSH servers on the network")
    sp.add_argument("network", nargs="?", help="CIDR, a.b.c or a.b.c.d-e (default: local network)")
    sp.add_argument("-p", "--ports", default=netscan.DEFAULT_PORTS)
    sp.add_argument("--add", action="store_true", help="add every new server found")
    sp.add_argument("-u", "--user")
    sp.add_argument("-t", "--tag", default="LAN")
    sp.add_argument("--json", action="store_true")

    sp = add("import", cmd_import, "import hosts from ~/.ssh/config")
    sp.add_argument("-f", "--file")
    sp.add_argument("-n", "--dry-run", action="store_true")

    sp = add("export", cmd_export, "print servers as ssh_config Host blocks")
    sp.add_argument("-t", "--tag")

    sp = add("tunnel", cmd_tunnel, "manage background port forwards")
    sp.add_argument("action", nargs="?", choices=["start", "list", "stop"], default="list")
    sp.add_argument("target", nargs="?", help="server (start) or tunnel id / 'all' (stop)")
    sp.add_argument("-L", "--local", metavar="PORT:HOST:PORT")
    sp.add_argument("-R", "--remote", metavar="PORT:HOST:PORT")
    sp.add_argument("-D", "--socks", metavar="PORT")

    sp = add("run", cmd_run, "list or run a server's saved commands")
    sp.add_argument("name")
    sp.add_argument("label", nargs="*", help="command label or number")
    sp.add_argument("--add", metavar="COMMAND", help="save COMMAND under LABEL")

    sp = add("agent", cmd_agent, "deploy, inspect or remove the telemetry agent")
    sp.add_argument("action", choices=["deploy", "status", "remove"])
    sp.add_argument("name")
    sp.add_argument("--hub", help="IP the agent should report to (default: auto)")

    sp = add("ps", cmd_ps, "list (or kill) processes on a server")
    sp.add_argument("name")
    sp.add_argument("-s", "--sort", choices=procs.SORT_KEYS, default="cpu")
    sp.add_argument("-n", "--limit", type=int, default=25, help="rows to show (0 = all)")
    sp.add_argument("-f", "--filter", help="substring of the command, user or exact PID")
    sp.add_argument("-w", "--watch", type=int, nargs="?", const=3, default=0, metavar="SECONDS",
                    help="refresh continuously (default every 3s)")
    sp.add_argument("--kill", type=int, metavar="PID", help="send SIGTERM to PID")
    sp.add_argument("--force", action="store_true", help="with --kill: send SIGKILL")
    sp.add_argument("--json", action="store_true")

    sp = add("docker", cmd_docker, "list and control docker/podman containers", ("containers",))
    sp.add_argument("name", help="docker host, or a saved server that is a container")
    sp.add_argument("action", nargs="?", default="list",
                    choices=["list", "info", "start", "stop", "restart", "pause", "unpause", "logs", "shell", "stats"])
    sp.add_argument("container", nargs="?", help="container name or id prefix")
    sp.add_argument("--json", action="store_true")

    sp = add("top", cmd_top, "open htop (or top) on a server")
    sp.add_argument("name")

    sp = add("exec", cmd_exec, "run a command on many servers at once", ("x",))
    sp.add_argument("servers", nargs="*", help="server names (or use -t / --all)")
    sp.add_argument("-t", "--tag", help="every server with this tag")
    sp.add_argument("-a", "--all", action="store_true", help="every server")
    sp.add_argument("-p", "--parallel", type=int, default=8)
    sp.add_argument("--timeout", type=float, default=120)
    sp.add_argument("-n", "--lines", type=int, default=0, help="show only the last N output lines per server")
    sp.add_argument("-s", "--stream", action="store_true", help="one summary line per server as they finish")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(command=[])
    sp.epilog = "Put the command after --, e.g.  sshm exec -t Homelab -- sudo dnf -y upgrade"

    sp = add("history", cmd_history, "uptime and latency history")
    sp.add_argument("name", nargs="?")

    sp = add("events", cmd_events, "alerts and the event log")
    sp.add_argument("name", nargs="?")
    sp.add_argument("-n", "--limit", type=int, default=30)
    sp.add_argument("--clear", action="store_true")

    sp = add("backup", cmd_backup, "save all servers to a JSON file")
    sp.add_argument("file", nargs="?")

    sp = add("restore", cmd_restore, "load servers from a backup (merge by default)")
    sp.add_argument("file")
    sp.add_argument("--replace", action="store_true", help="delete current servers first")

    add("paths", cmd_paths, "show where sshm keeps its files")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    remote: list[str] = []
    if argv and argv[0] in ("exec", "x") and "--" in argv:  # everything after -- is the remote command
        cut = argv.index("--")
        argv, remote = argv[:cut], argv[cut + 1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if remote:
        args.command = remote
    if args.cmd in (None, "tui"):
        from sshm.tui import run

        return run()
    if args.cmd == "tunnel" and args.action in ("start", "stop") and not args.target:
        usage = "SERVER -L 8080:localhost:80" if args.action == "start" else "ID|all"
        return die(f"usage: sshm tunnel {args.action} {usage}")
    try:
        store = ServerStore()
        return args.func(args, store)
    except StoreError as exc:
        return die(str(exc))
    except FileNotFoundError as exc:
        return die(f"{exc.filename or 'a required program'} is not installed")
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
