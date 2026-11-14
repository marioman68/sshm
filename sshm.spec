Name:           sshm
Version:        2.2.0
Release:        1%{?dist}
Summary:        SSH Connection Hub, SFTP Mounter, and Live Telemetry Control Center
License:        MIT
URL:            https://github.com/YOUR_GITHUB_USERNAME/sshm
BuildArch:      noarch

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
# Copy source files from git repository root into build directory
cp -a %{_sourcedir}/* . 2>/dev/null || true

%build
# Pure Python/Bash scripts — no compilation required

%install
install -d %{buildroot}%{_datadir}/sshm
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -d %{buildroot}%{_sysconfdir}/xdg/autostart

# 1. Install core Python scripts
install -m 0755 sshm.py %{buildroot}%{_datadir}/sshm/sshm.py
install -m 0755 sshm-tray.py %{buildroot}%{_datadir}/sshm/sshm-tray.py

# 2. Create SVG Icon
cat << 'IEOF' > %{buildroot}%{_datadir}/sshm/sshm-hub.svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e1e2e"/>
      <stop offset="100%" stop-color="#11111b"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#b48ead"/>
      <stop offset="100%" stop-color="#89b4fa"/>
    </linearGradient>
  </defs>
  <rect x="8" y="8" width="112" height="112" rx="24" fill="url(#bg)" stroke="url(#accent)" stroke-width="5"/>
  <rect x="24" y="28" width="80" height="26" rx="6" fill="#313244" stroke="#45475a" stroke-width="2"/>
  <circle cx="38" cy="41" r="5" fill="#52ff52"/>
  <rect x="52" y="38" width="40" height="6" rx="3" fill="#cdd6f4"/>
  <rect x="24" y="64" width="80" height="36" rx="6" fill="#181825" stroke="#45475a" stroke-width="2"/>
  <path d="M 34 76 L 44 82 L 34 88" fill="none" stroke="#52ff52" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="50" y1="88" x2="66" y2="88" stroke="#89b4fa" stroke-width="3.5" stroke-linecap="round"/>
  <circle cx="100" cy="100" r="14" fill="#1e1e2e" stroke="#11111b" stroke-width="3"/>
  <circle cx="100" cy="100" r="9" fill="#52ff52"/>
</svg>
IEOF
install -m 0644 %{buildroot}%{_datadir}/sshm/sshm-hub.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/sshm-hub.svg

# 3. Create /usr/bin CLI launchers
cat << 'WEOF' > %{buildroot}%{_bindir}/sshm
#!/usr/bin/env bash
printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l'
exec /usr/bin/python3 /usr/share/sshm/sshm.py "$@"
WEOF
chmod 0755 %{buildroot}%{_bindir}/sshm

cat << 'GEOF' > %{buildroot}%{_bindir}/sshm-gui
#!/usr/bin/env bash
exec /usr/bin/python3 /usr/share/sshm/sshm-tray.py --gui "$@"
GEOF
chmod 0755 %{buildroot}%{_bindir}/sshm-gui

ln -sf ../share/sshm/sshm-tray.py %{buildroot}%{_bindir}/sshm-tray

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
%{_datadir}/sshm/
%{_bindir}/sshm
%{_bindir}/sshm-gui
%{_bindir}/sshm-tray
%{_datadir}/applications/sshm-gui.desktop
%{_datadir}/icons/hicolor/scalable/apps/sshm-hub.svg
%config(noreplace) %{_sysconfdir}/xdg/autostart/sshm-tray.desktop

%changelog
* Sat Nov 14 2026 Lucas Dunham - 2.2.0-1
- Migrate terminal TUI to Python curses with mouse hover and modal overlays
- Package GUI, System Tray, and TUI for Fedora COPR
