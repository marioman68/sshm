# sshm — Rust desktop app + tray monitor. Built offline from a vendored dependency tarball
# (see packaging/vendor.py and .copr/Makefile).
%global forgeurl https://github.com/marioman68/sshm
%global app_id   io.github.marioman68.sshm
# the release profile strips the binary; there is no useful debuginfo to split out
%global debug_package %{nil}

Name:           sshm
Version:        4.0.0
Release:        1%{?dist}
Summary:        SSH Connection Hub: desktop app and tray monitor for your SSH servers
# sshm itself is MIT; the bundled Rust crates are MIT, Apache-2.0, BSD, Zlib, ISC, Unicode-3.0 and MPL-2.0 licensed
License:        MIT AND Apache-2.0 AND BSD-3-Clause AND Zlib AND ISC AND Unicode-3.0 AND MPL-2.0
URL:            %{forgeurl}
Source0:        %{name}-%{version}.tar.gz
Source1:        %{name}-%{version}-vendor.tar.xz
ExclusiveArch:  x86_64 aarch64 ppc64le s390x

BuildRequires:  cargo >= 1.80
BuildRequires:  rust >= 1.80
BuildRequires:  gcc
BuildRequires:  desktop-file-utils

Requires:       openssh-clients
# loaded at run time (not seen by the automatic dependency scan)
Requires:       libxkbcommon
Requires:       libwayland-client
Requires:       libwayland-egl
Requires:       libglvnd-egl
Requires:       hicolor-icon-theme
# X11 sessions
Recommends:     libX11
Recommends:     libXcursor
Recommends:     libXrandr
Recommends:     libXi
Recommends:     libxkbcommon-x11
Recommends:     tmux
Suggests:       fuse-sshfs

%description
One place for every server you SSH into. A desktop window and a tray monitor:
live status and latency, CPU / memory / disk from a tiny signed-telemetry agent,
one-click connect (plain or tmux), file manager bookmarks and SSHFS mounts, a
live process viewer, Docker/Podman awareness, port forwards, alerts with uptime
history, running one command on many servers, LAN scan and ~/.ssh/config
import/export. The tray icon follows the desktop's panel style.

Run sshm-gui to open the window (it starts the tray monitor too);
sshm-gui --tray runs only the monitor and starts at login.

%prep
%autosetup -n %{name}-%{version} -a 1
mkdir -p .cargo
cat > .cargo/config.toml <<'CEOF'
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
CEOF

%build
export CARGO_HOME="$PWD/.cargo-home"
cargo build --release --frozen --offline

%install
install -Dm 0755 target/release/sshm-gui %{buildroot}%{_bindir}/sshm-gui
# compatibility for older autostart entries and scripts that call sshm-tray
cat > %{buildroot}%{_bindir}/sshm-tray <<'TEOF'
#!/bin/sh
exec /usr/bin/sshm-gui --tray "$@"
TEOF
chmod 0755 %{buildroot}%{_bindir}/sshm-tray
install -Dm 0644 assets/%{app_id}.desktop %{buildroot}%{_datadir}/applications/%{app_id}.desktop
install -Dm 0644 assets/%{app_id}.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg
install -d %{buildroot}%{_sysconfdir}/xdg/autostart
cat > %{buildroot}%{_sysconfdir}/xdg/autostart/sshm-tray.desktop <<'AEOF'
[Desktop Entry]
Type=Application
Name=sshm tray monitor
Comment=Watch your SSH servers from the system tray
Exec=/usr/bin/sshm-gui --tray
Icon=io.github.marioman68.sshm
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
X-KDE-autostart-after=panel
AEOF

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{app_id}.desktop
export CARGO_HOME="$PWD/.cargo-home"
cargo test --release --frozen --offline

%files
%license LICENSE
%doc README.md CHANGELOG.md
%{_bindir}/sshm-gui
%{_bindir}/sshm-tray
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg
%config(noreplace) %{_sysconfdir}/xdg/autostart/sshm-tray.desktop

%changelog
* Sat Nov 21 2026 Lucas Dunham - 4.0.0-1
- Rewritten in Rust: desktop window and native tray monitor in one program (sshm-gui)
- Tray icon matches the desktop (panel colour on KDE, white on GNOME-style bars, colour tile elsewhere)
- The Python terminal UI and CLI are retired (kept in the source tree under legacy/)
