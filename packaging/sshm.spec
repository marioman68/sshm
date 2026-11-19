Name:           sshm
Version:        3.3.0
Release:        1%{?dist}
Summary:        SSH connection hub: terminal UI and CLI for managing SSH servers
License:        MIT
URL:            https://github.com/marioman68/sshm
# COPR SCM builds create this tarball from the checkout (.copr/Makefile);
# for manual builds, download the GitHub tag archive.
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
# test suite (%%check): pty-driven TUI tests, ps parsing, installer syntax check
BuildRequires:  python3-pytest
BuildRequires:  procps-ng
BuildRequires:  ncurses-base
BuildRequires:  bash

Requires:       openssh-clients
Recommends:     %{name}-gui = %{version}-%{release}
Recommends:     tmux
Recommends:     fuse-sshfs
Suggests:       wl-clipboard
Suggests:       htop

%description
sshm manages your SSH servers from one place: a fast curses terminal UI that
also works over SSH and a scriptable CLI, sharing one config with the optional
desktop app (sshm-gui). Fuzzy search, tags and favourites, tmux sessions,
background port forwards, a live process viewer, Docker/Podman container
awareness, SFTP bookmarks and SSHFS mounts, Wake-on-LAN, LAN discovery,
~/.ssh/config import/export and an HMAC-signed telemetry agent.

Install with --setopt=install_weak_deps=False on servers to skip the GUI.

%package gui
Summary:        Desktop app and system tray monitor for sshm
Requires:       %{name} = %{version}-%{release}
Requires:       python3-pyqt6
Recommends:     xdg-utils

%description gui
PyQt6 desktop control center and system tray monitor for sshm: live server
metrics, container controls, process viewer, tunnels and up/down notifications.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files sshm
install -Dpm 0644 src/sshm/data/sshm.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/sshm.svg
desktop-file-install --dir=%{buildroot}%{_datadir}/applications packaging/io.github.marioman68.sshm.desktop

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.marioman68.sshm.desktop
%pyproject_check_import -e 'sshm.gui*'
# GUI tests need PyQt6 and a display; the core, CLI and TUI suites run headless
%pytest -k "not gui" -p no:cacheprovider

%files -f %{pyproject_files}
%license LICENSE
%doc README.md CHANGELOG.md
%{_bindir}/sshm
%exclude %{python3_sitelib}/sshm/gui/

%files gui
%{python3_sitelib}/sshm/gui/
%{_bindir}/sshm-gui
%{_bindir}/sshm-tray
%{_datadir}/applications/io.github.marioman68.sshm.desktop
%{_datadir}/icons/hicolor/scalable/apps/sshm.svg

%changelog
* Wed Nov 18 2026 Lucas Dunham - 3.3.0-1
- Alerts, uptime history, run on many servers, backup/restore

* Wed Nov 18 2026 Lucas Dunham - 3.2.1-1
- README and RELEASING point to the lucasdunham85/sshm COPR project; COPR build badge

* Wed Nov 18 2026 Lucas Dunham - 3.2.0-1
- COPR-ready packaging and release pipeline

* Wed Nov 18 2026 Lucas Dunham - 3.1.0-1
- Process viewer, Docker/Podman awareness, Minecraft status, larger remembered window
- Fix process-window freeze and SSH ControlPersist stalls

* Wed Nov 18 2026 Lucas Dunham - 3.0.0-1
- Rewrite around a shared core used by GUI, tray, TUI and the new CLI
- Signed telemetry (HMAC-SHA256), SSHFS mounts, background tunnels,
  ssh_config import/export, ProxyJump, fuzzy search and favourites
- Automatic migration of ~/.ssh_servers and other 2.x settings
- No longer installs a system-wide autostart entry; enable it in Settings

* Sat Nov 14 2026 Lucas Dunham - 2.2.0-1
- Migrate terminal TUI to Python curses with mouse hover and modal overlays
- Package GUI, System Tray, and TUI for Fedora COPR
