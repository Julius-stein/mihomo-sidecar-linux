#!/bin/bash
set +e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"
sidecar_load_config

transparent_uids="${MIHOMO_TRANSPARENT_UIDS:-}"
if [[ -z "${transparent_uids}" && -n "${MIHOMO_TARGET_UID:-}" ]]; then
  transparent_uids="${MIHOMO_TARGET_UID}"
fi

while iptables -t mangle -D OUTPUT -m owner --gid-owner "$MIHOMO_TARGET_GID" -j "$MIHOMO_CHAIN_MANGLE" 2>/dev/null; do :; done
if [[ -n "${transparent_uids}" ]]; then
  IFS=',' read -r -a transparent_uid_array <<< "${transparent_uids}"
  for transparent_uid in "${transparent_uid_array[@]}"; do
    [[ -z "${transparent_uid}" ]] && continue
    while iptables -t mangle -D OUTPUT -m owner --uid-owner "$transparent_uid" -j "$MIHOMO_CHAIN_MANGLE" 2>/dev/null; do :; done
  done
fi
iptables -t mangle -F "$MIHOMO_CHAIN_MANGLE" 2>/dev/null
iptables -t mangle -X "$MIHOMO_CHAIN_MANGLE" 2>/dev/null

while ip rule del fwmark "$MIHOMO_FWMARK" table "$MIHOMO_ROUTE_TABLE" priority "$MIHOMO_RULE_PRIORITY" 2>/dev/null; do :; done
ip route flush table "$MIHOMO_ROUTE_TABLE" 2>/dev/null

while iptables -t nat -D OUTPUT -m owner --gid-owner "$MIHOMO_TARGET_GID" -j "$MIHOMO_CHAIN_DNS" 2>/dev/null; do :; done
if [[ -n "${transparent_uids}" ]]; then
  IFS=',' read -r -a transparent_uid_array <<< "${transparent_uids}"
  for transparent_uid in "${transparent_uid_array[@]}"; do
    [[ -z "${transparent_uid}" ]] && continue
    while iptables -t nat -D OUTPUT -m owner --uid-owner "$transparent_uid" -j "$MIHOMO_CHAIN_DNS" 2>/dev/null; do :; done
  done
fi
iptables -t nat -F "$MIHOMO_CHAIN_DNS" 2>/dev/null
iptables -t nat -X "$MIHOMO_CHAIN_DNS" 2>/dev/null

echo "mihomo sidecar rules cleaned for GID $MIHOMO_TARGET_GID"
