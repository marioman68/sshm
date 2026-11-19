"""File-manager integration: SFTP bookmarks and real SSHFS mounts.

*Bookmarks* add the server to the sidebar of Dolphin (KDE ``user-places.xbel``
and ``remoteview``), Nautilus / Thunar / Nemo / Caja (GTK bookmarks), plus a
``.desktop`` link in the mount folder. Nothing is mounted; the file manager
opens ``sftp://`` itself.

*SSHFS* performs an actual FUSE mount into ``<mount_dir>/<name>/`` so any
program can use the files. Requires the ``sshfs`` package.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from sshm.core import paths, sshcmd
from sshm.core.models import Server
from sshm.core.settings import Settings

XBEL_NS = {
    "bookmark": "http://www.freedesktop.org/standards/desktop-bookmarks",
    "mime": "http://www.freedesktop.org/standards/shared-mime-info",
    "kdepriv": "http://www.kde.org/kdepriv",
}
for _prefix, _uri in XBEL_NS.items():
    ET.register_namespace(_prefix, _uri)


def safe_filename(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "server"


def gtk_bookmarks_file() -> Path:
    return paths.home() / ".config/gtk-3.0/bookmarks"


def xbel_file() -> Path:
    return paths.home() / ".local/share/user-places.xbel"


def remoteview_dir() -> Path:
    return paths.home() / ".local/share/remoteview"


def _link_files(server: Server, settings: Settings) -> list[Path]:
    fname = f"{safe_filename(server.name)}.desktop"
    return [settings.mount_path / fname, remoteview_dir() / fname]


# --------------------------------------------------------------- bookmarks
def is_bookmarked(server: Server, settings: Settings) -> bool:
    if any(p.exists() for p in _link_files(server, settings)):
        return True
    prefix = server.sftp_url_prefix
    for f in (gtk_bookmarks_file(), xbel_file()):
        with contextlib.suppress(OSError):
            if prefix in f.read_text(errors="ignore"):
                return True
    return False


def add_bookmark(server: Server, settings: Settings) -> None:
    url = server.sftp_url
    desktop = (
        "[Desktop Entry]\n"
        "Type=Link\n"
        "Icon=folder-remote\n"
        f"Name={server.name} ({server.target})\n"
        f"URL[$e]={url}\n"
    )
    for link in _link_files(server, settings):
        paths.ensure_dir(link.parent, 0o755)
        paths.atomic_write_text(link, desktop, mode=0o755)

    gtk = gtk_bookmarks_file()
    lines = gtk.read_text(errors="ignore").splitlines() if gtk.exists() else []
    if not any(line.startswith(server.sftp_url_prefix) for line in lines):
        lines.append(f"{url} {server.name}")
        paths.atomic_write_text(gtk, "\n".join(lines) + "\n", mode=0o644)

    if xbel_file().exists():
        _xbel_edit(server, add=True)


def remove_bookmark(server: Server, settings: Settings) -> None:
    for link in _link_files(server, settings):
        link.unlink(missing_ok=True)
    gtk = gtk_bookmarks_file()
    if gtk.exists():
        lines = [ln for ln in gtk.read_text(errors="ignore").splitlines() if not ln.startswith(server.sftp_url_prefix)]
        paths.atomic_write_text(gtk, "\n".join(lines) + ("\n" if lines else ""), mode=0o644)
    if xbel_file().exists():
        _xbel_edit(server, add=False)


def toggle_bookmark(server: Server, settings: Settings) -> bool:
    """Returns the new state (True = bookmarked)."""
    if is_bookmarked(server, settings):
        remove_bookmark(server, settings)
        return False
    add_bookmark(server, settings)
    return True


def _xbel_edit(server: Server, add: bool) -> None:
    path = xbel_file()
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return  # never touch a file we cannot fully understand
    root = tree.getroot()
    prefix = server.sftp_url_prefix
    existing = [b for b in root.findall("bookmark") if b.get("href", "").startswith(prefix)]
    if add and existing:
        return
    if not add and not existing:
        return
    backup = path.with_suffix(".xbel.sshm-backup")
    if not backup.exists():
        shutil.copy2(path, backup)
    if add:
        bm = ET.SubElement(root, "bookmark", {"href": server.sftp_url})
        ET.SubElement(bm, "title").text = server.name
        info = ET.SubElement(bm, "info")
        fd = ET.SubElement(info, "metadata", {"owner": "http://freedesktop.org"})
        ET.SubElement(fd, f"{{{XBEL_NS['bookmark']}}}icon", {"name": "folder-remote"})
        kde = ET.SubElement(info, "metadata", {"owner": "http://www.kde.org"})
        ET.SubElement(kde, "ID").text = f"{int(time.time())}/sshm-{safe_filename(server.name)}"
        ET.SubElement(kde, "isSystemItem").text = "false"
    else:
        for b in existing:
            root.remove(b)
    ET.indent(tree, space=" ")
    body = ET.tostring(root, encoding="unicode")
    paths.atomic_write_text(path, f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xbel>\n{body}\n', mode=0o644)


# ------------------------------------------------------------------- SSHFS
def sshfs_available() -> bool:
    return shutil.which("sshfs") is not None


def sshfs_mountpoint(server: Server, settings: Settings) -> Path:
    return settings.mount_path / safe_filename(server.name)


def _mounted_paths() -> set[str]:
    try:
        text = Path("/proc/self/mounts").read_text()
    except OSError:
        return set()
    out = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) > 2 and "sshfs" in parts[2]:
            out.add(parts[1].replace("\\040", " "))
    return out


def is_sshfs_mounted(server: Server, settings: Settings) -> bool:
    return str(sshfs_mountpoint(server, settings)) in _mounted_paths()


def sshfs_mount(server: Server, settings: Settings) -> tuple[bool, str]:
    if not sshfs_available():
        return False, "sshfs is not installed"
    mp = sshfs_mountpoint(server, settings)
    paths.ensure_dir(mp, 0o755)
    opts = "reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,BatchMode=yes,follow_symlinks"
    argv = ["sshfs", f"{server.target}:{server.home_path}", str(mp), "-p", str(server.port), "-o", opts]
    if server.key_path:
        argv += ["-o", f"IdentityFile={server.key_path}"]
    if server.jump:
        argv += ["-o", f"ssh_command=ssh -J {server.jump}"]
    try:
        res = sshcmd.run_capture(argv, timeout=25)  # sshfs leaves a daemon holding stdio
    except subprocess.TimeoutExpired:
        return False, "sshfs timed out"
    if res.returncode != 0:
        msg = (res.stderr or res.stdout).strip().splitlines()
        return False, msg[-1] if msg else f"sshfs failed ({res.returncode})"
    return True, f"Mounted at {mp}"


def sshfs_unmount(server: Server, settings: Settings) -> tuple[bool, str]:
    mp = str(sshfs_mountpoint(server, settings))
    for tool in (["fusermount3", "-u"], ["fusermount", "-u"], ["umount"]):
        if shutil.which(tool[0]):
            res = subprocess.run([*tool, mp], capture_output=True, text=True)
            if res.returncode == 0:
                with contextlib.suppress(OSError):
                    Path(mp).rmdir()
                return True, "Unmounted"
            err = res.stderr.strip()
            return False, err or "unmount failed"
    return False, "no unmount tool found"


def open_in_file_manager(server: Server) -> bool:
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if not opener:
        return False
    argv = [opener, server.sftp_url] if opener.endswith("xdg-open") else [opener, "open", server.sftp_url]
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True
