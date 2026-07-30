#!/bin/sh
set -eu

INTERFACE=""
ADDRESS=""
PREFIX=24
APPLY=0
BACKUP_ROOT=/var/lib/smartbag/network-backups

while [ "$#" -gt 0 ]; do
    case "$1" in
        --interface) INTERFACE=$2; shift 2 ;;
        --address) ADDRESS=$2; shift 2 ;;
        --prefix) PREFIX=$2; shift 2 ;;
        --backup-root) BACKUP_ROOT=$2; shift 2 ;;
        --apply) APPLY=1; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

[ -n "$INTERFACE" ] && [ -n "$ADDRESS" ] || {
    echo "usage: mr20-network-setup.sh --interface eth0 --address 192.168.1.168 [--prefix 24] [--apply]" >&2
    exit 2
}
case "$ADDRESS" in
    */*) PREFIX=${ADDRESS#*/}; ADDRESS=${ADDRESS%/*} ;;
esac
ip link show "$INTERFACE" >/dev/null 2>&1 || { echo "interface not found: $INTERFACE" >&2; exit 1; }

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$BACKUP_ROOT/$STAMP"
mkdir -p "$BACKUP"
ip address show >"$BACKUP/ip-address.txt"
ip route show >"$BACKUP/ip-route.txt"
if [ -d /etc/netplan ]; then
    cp -a /etc/netplan "$BACKUP/netplan"
fi

if [ "$APPLY" -eq 0 ]; then
    echo "Backup created at $BACKUP"
    echo "Dry run. Re-run with --apply to execute: ip address replace $ADDRESS/$PREFIX dev $INTERFACE"
    exit 0
fi

ip link set "$INTERFACE" up
ip address replace "$ADDRESS/$PREFIX" dev "$INTERFACE"
echo "Applied runtime MR20 address $ADDRESS/$PREFIX to $INTERFACE. Backup: $BACKUP"
echo "This command does not silently rewrite persistent netplan configuration."
