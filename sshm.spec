Name:           sshm
Version:        3.2.1
Release:        1%{?dist}
Summary:        SSH Connection Hub, SFTP Mounter, and Live Telemetry Control Center
License:        MIT
URL:            https://github.com/marioman68/sshm
BuildArch:      noarch

Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel
Requires:       python3
Requires:       python3-pyqt6
Requires:       openssh-clients
Recommends:     tmux

%description
A unified hybrid Linux desktop utility for managing SSH servers, mounting remote
SFTP folders, scanning local networks, and monitoring live server CPU/RAM telemetry.
Includes a PyQt6 Desktop GUI Control Center, a persistent System Tray Monitor,
and a 256-color Python Curses Split-Pane Terminal TUI.

%prep
%autosetup -n %{name}-%{version}

%build
# Pure Python package — no compilation required

%install
install -d %{buildroot}%{python3_sitelib}/sshm
install -d %{buildroot}%{_datadir}/sshm
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -d %{buildroot}%{_sysconfdir}/xdg/autostart

# 1. Install the sshm Python package tree from src/sshm
cp -a src/sshm/. %{buildroot}%{python3_sitelib}/sshm/

# 2. Install SVG Icon
if [ -f src/sshm/data/sshm.svg ]; then
    install -m 0644 src/sshm/data/sshm.svg %{buildroot}%{_datadir}/sshm/sshm-hub.svg
fi
install -m 0644 %{buildroot}%{_datadir}/sshm/sshm-hub.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/sshm-hub.svg

# 3. Create /usr/bin launchers targeting the installed sshm package
cat << 'WEOF' > %{buildroot}%{_bindir}/sshm
#!/usr/bin/env bash
printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l'
exec /usr/bin/python3 -m sshm "$@"
WEOF
chmod 0755 %{buildroot}%{_bindir}/sshm

cat << 'GEOF' > %{buildroot}%{_bindir}/sshm-gui
#!/usr/bin/env bash
exec /usr/bin/python3 -m sshm.gui.app "$@"
GEOF
chmod 0755 %{buildroot}%{_bindir}/sshm-gui

cat << 'TEOF' > %{buildroot}%{_bindir}/sshm-tray
#!/usr/bin/env bash
exec /usr/bin/python3 -m sshm.gui.tray "$@"
TEOF
chmod 0755 %{buildroot}%{_bindir}/sshm-tray

# 4. Create Application Menu Launcher
cat << 'DEOF' > %{buildroot}%{_datadir}/applications/sshm-gui.desktop
[Desktop Entry]
Version=1.0
Type=Application
Name=SSH Connection Hub
GenericName=SSH Server Manager & Telemetry Hub
Comment=Manage SSH servers, mount SFTP folders, scan LAN, and monitor live CPU/RAM telemetry
Exec=/usr/bin/sshm-gui
Icon=sshm-hub
Terminal=false
Categories=System;Network;RemoteAccess;
Keywords=ssh;sftp;server;homelab;terminal;tray;telemetry;sshm;
StartupNotify=false
DEOF

# 5. Create System-Wide XDG Autostart Entry
cat << 'AEOF' > %{buildroot}%{_sysconfdir}/xdg/autostart/sshm-tray.desktop
[Desktop Entry]
Name=SSH Hub Tray Monitor
Comment=System Tray Monitor for SSH Connection Hub
Exec=/usr/bin/sshm-tray
Icon=sshm-hub
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
StartupNotify=false
AEOF

%files
%{python3_sitelib}/sshm/
%{_datadir}/sshm/
%{_bindir}/sshm
%{_bindir}/sshm-gui
%{_bindir}/sshm-tray
%{_datadir}/applications/sshm-gui.desktop
%{_datadir}/icons/hicolor/scalable/apps/sshm-hub.svg
%config(noreplace) %{_sysconfdir}/xdg/autostart/sshm-tray.desktop

%changelog
* Wed Nov 18 2026 Lucas Dunham - 3.2.1-1
- Add python3-devel BuildRequires and package from Source0 archive
