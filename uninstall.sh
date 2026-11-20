#!/bin/sh
# Removes everything install.sh put in place.  Run from this folder:  sudo sh uninstall.sh
# (Leaves /etc/circle-scroll.json and ~/.config/circlescrollrc, your settings.)
cd "$(dirname "$0")"
if [ "$(id -u)" != 0 ]; then
    echo "Please run with sudo:  sudo sh uninstall.sh"; exit 1
fi
systemctl disable --now circle-scroll.service 2>/dev/null
rm -f /etc/systemd/system/circle-scroll.service
systemctl daemon-reload
pkill -f /usr/local/bin/circle-scroll-xsync 2>/dev/null
rm -f /usr/local/bin/circle-scroll /usr/local/bin/circle-scroll-xsync
rm -f /etc/xdg/autostart/circle-scroll-xsync.desktop
rm -f /usr/lib/x86_64-linux-gnu/qt6/plugins/plasma/kcms/systemsettings/kcm_circlescroll.so
rm -f /usr/share/applications/kcm_circlescroll.desktop
echo "circle-scroll removed; the touchpad is back to stock."
