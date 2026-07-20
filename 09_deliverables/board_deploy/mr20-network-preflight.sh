#!/bin/sh
set -eu

IFACE=${IFACE:-eth1}
RADAR_IP=${RADAR_IP:-192.168.1.200}
HOST_IP=${HOST_IP:-192.168.1.102}

active=""
systemctl is-active --quiet systemd-networkd.service 2>/dev/null && active="$active systemd-networkd"
systemctl is-active --quiet NetworkManager.service 2>/dev/null && active="$active NetworkManager"
echo "active_network_managers=${active:-unknown}"
ip -details link show "$IFACE"
ip address show dev "$IFACE"
ip route get "$RADAR_IP"
route=$(ip route get "$RADAR_IP")
echo "$route" | grep -q "dev $IFACE" || { echo "MR20 route does not use $IFACE" >&2; exit 1; }
echo "$route" | grep -q "src $HOST_IP" || { echo "MR20 route source is not $HOST_IP" >&2; exit 1; }
ip route show default | grep -q "dev $IFACE" && { echo "eth1 must not own a default route" >&2; exit 1; } || true
command -v ethtool >/dev/null 2>&1 && ethtool "$IFACE" || true
ping -c 2 -I "$IFACE" "$RADAR_IP"
ss -ulnp | grep ':2368 ' || echo "WARN no process currently bound to UDP 2368"
