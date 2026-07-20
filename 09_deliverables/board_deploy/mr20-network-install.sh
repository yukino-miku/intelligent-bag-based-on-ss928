#!/bin/sh
set -eu

[ "${1:-}" = --apply ] || { echo "usage: $0 --apply" >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
networkd=0
nm=0
systemctl is-active --quiet systemd-networkd.service 2>/dev/null && networkd=1 || true
systemctl is-active --quiet NetworkManager.service 2>/dev/null && nm=1 || true
[ "$networkd" -eq 1 ] && [ "$nm" -eq 1 ] && {
    echo "both systemd-networkd and NetworkManager are active; refusing to configure eth1" >&2
    exit 1
}

if [ "$networkd" -eq 1 ]; then
    install -m 0644 "$SCRIPT_DIR/systemd-networkd/20-mr20-radar.network" /etc/systemd/network/20-mr20-radar.network
    networkctl reload
    networkctl reconfigure eth1
elif [ "$nm" -eq 1 ]; then
    command -v nmcli >/dev/null 2>&1 || { echo "nmcli missing" >&2; exit 1; }
    nmcli connection delete smartbag-mr20 2>/dev/null || true
    nmcli connection add type ethernet ifname eth1 con-name smartbag-mr20 \
        ipv4.method manual ipv4.addresses 192.168.1.102/32 \
        ipv4.routes "192.168.1.200/32" ipv4.never-default yes ipv6.method disabled
    nmcli connection up smartbag-mr20
else
    echo "no supported active network manager found; configure eth1 manually without a gateway/default route" >&2
    exit 1
fi

"$SCRIPT_DIR/mr20-network-preflight.sh"
