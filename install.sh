#!/bin/sh
# Installs (or updates) circle-scroll.  Run from this folder:  sudo sh install.sh
#
# What it does:
#   1. installs any missing Debian packages (apt asks before installing)
#   2. builds the System Settings page (as your user, in kcm/build)
#   3. installs:
#        /usr/local/bin/circle-scroll           the service program (a root-owned copy,
#                                               so the root service never runs a file
#                                               your user account could edit)
#        /usr/local/bin/circle-scroll-xsync     settings-copy helper (runs as you, X11)
#        /etc/circle-scroll.json                touchpad circle + advanced settings
#                                               (only if it doesn't exist yet)
#        /etc/systemd/system/circle-scroll.service
#        /etc/xdg/autostart/circle-scroll-xsync.desktop
#        the System Settings page (Mouse & Touchpad > Circle Scroll)
#   4. (re)starts the service
set -e
cd "$(dirname "$0")"

if [ "$(id -u)" != 0 ]; then
    echo "Please run with sudo:  sudo sh install.sh"; exit 1
fi
USER_NAME="${SUDO_USER:-}"
if [ -z "$USER_NAME" ] || [ "$USER_NAME" = root ]; then
    echo "Run this with sudo from your own account (not as root directly)."; exit 1
fi
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)

echo "== 1/4 Packages"
RUNTIME="python3 python3-evdev xinput"
BUILD="cmake extra-cmake-modules g++ make qt6-base-dev qt6-declarative-dev libkf6kcmutils-dev libkf6config-dev libkf6coreaddons-dev libkf6i18n-dev"
MISSING=""
for p in $RUNTIME $BUILD; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || MISSING="$MISSING $p"
done
if [ -n "$MISSING" ]; then
    echo "Missing:$MISSING"
    # shellcheck disable=SC2086
    apt install $MISSING
else
    echo "All present."
fi

echo "== 2/4 Building the System Settings page"
sudo -u "$USER_NAME" cmake -B kcm/build -S kcm -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_BUILD_TYPE=Release -DKDE_INSTALL_USE_QT_SYS_PATHS=ON > /dev/null
sudo -u "$USER_NAME" cmake --build kcm/build -j"$(nproc)"

echo "== 3/4 Installing"
install -o root -g root -m 755 circle-scroll.py /usr/local/bin/circle-scroll
install -o root -g root -m 755 circle-scroll-xsync.py /usr/local/bin/circle-scroll-xsync
if [ -f /etc/circle-scroll.json ]; then
    echo "Keeping your existing /etc/circle-scroll.json"
else
    install -o root -g root -m 644 circle-scroll.json /etc/circle-scroll.json
    echo "Installed /etc/circle-scroll.json (CF-SV1 calibration)"
fi

cat > /etc/systemd/system/circle-scroll.service <<EOF
[Unit]
Description=Circle scroll (iPod-style rim scrolling for the touchpad)
After=systemd-udevd.service

[Service]
ExecStart=/usr/bin/python3 -I /usr/local/bin/circle-scroll --user-config $USER_HOME/.config/circlescrollrc
Restart=always
RestartSec=2
RuntimeDirectory=circle-scroll
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/xdg/autostart/circle-scroll-xsync.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Circle scroll settings sync
Comment=Keeps circle-scroll's virtual touchpad on your touchpad settings
Exec=/usr/bin/python3 -I /usr/local/bin/circle-scroll-xsync
NoDisplay=true
X-KDE-autostart-phase=2
EOF

cmake --install kcm/build
chown -R "$USER_NAME": kcm/build

echo "== 4/4 Starting the service"
systemctl daemon-reload
systemctl enable circle-scroll.service
systemctl restart circle-scroll.service      # restart, so an update takes effect
sleep 2
systemctl --no-pager --lines=5 status circle-scroll.service || true

echo
echo "Done.  Settings: System Settings > Mouse & Touchpad > Circle Scroll"
if ! pgrep -u "$USER_NAME" -f circle-scroll-xsync > /dev/null; then
    echo "Log out and back in once, so your touchpad settings (pointer speed etc.)"
    echo "also apply while circle-scroll is running."
fi
