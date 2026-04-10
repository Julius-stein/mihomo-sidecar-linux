#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"
sidecar_load_config

transparent_uids="${MIHOMO_TRANSPARENT_UIDS:-}"
if [[ -z "${transparent_uids}" && -n "${MIHOMO_TARGET_UID:-}" ]]; then
  transparent_uids="${MIHOMO_TARGET_UID}"
fi

# 等待 TUN 接口出现（最多 30s）
for i in $(seq 1 30); do
  ip link show "$MIHOMO_TUN_DEV" &>/dev/null && break
  sleep 1
done
ip link show "$MIHOMO_TUN_DEV" &>/dev/null || { echo "$MIHOMO_TUN_DEV not found after 30s" >&2; exit 1; }

# 防止 systemd-resolved 把该 TUN 当成系统 DNS 链路
resolvectl dns "$MIHOMO_TUN_DEV" "" 2>/dev/null || true
resolvectl domain "$MIHOMO_TUN_DEV" "" 2>/dev/null || true
resolvectl flush-caches 2>/dev/null || true

# 先清理旧的同名规则，保证幂等
while ip rule del fwmark "$MIHOMO_FWMARK" table "$MIHOMO_ROUTE_TABLE" priority "$MIHOMO_RULE_PRIORITY" 2>/dev/null; do :; done
ip route flush table "$MIHOMO_ROUTE_TABLE" 2>/dev/null || true

# 只给本方案自己的 table 加默认路由
ip route add default dev "$MIHOMO_TUN_DEV" table "$MIHOMO_ROUTE_TABLE"
ip rule add fwmark "$MIHOMO_FWMARK" table "$MIHOMO_ROUTE_TABLE" priority "$MIHOMO_RULE_PRIORITY"

# mangle：只标记 effective GID = sidecar 的进程
iptables -t mangle -N "$MIHOMO_CHAIN_MANGLE" 2>/dev/null || iptables -t mangle -F "$MIHOMO_CHAIN_MANGLE"
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -d 127.0.0.0/8    -j RETURN
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -d 10.0.0.0/8     -j RETURN
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -d 172.16.0.0/12  -j RETURN
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -d 192.168.0.0/16 -j RETURN
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -d 169.254.0.0/16 -j RETURN
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -d 224.0.0.0/4    -j RETURN
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -d 240.0.0.0/4    -j RETURN
iptables -t mangle -A "$MIHOMO_CHAIN_MANGLE" -j MARK --set-mark "$MIHOMO_FWMARK"

iptables -t mangle -C OUTPUT -m owner --gid-owner "$MIHOMO_TARGET_GID" -j "$MIHOMO_CHAIN_MANGLE" 2>/dev/null || \
  iptables -t mangle -A OUTPUT -m owner --gid-owner "$MIHOMO_TARGET_GID" -j "$MIHOMO_CHAIN_MANGLE"
if [[ "${MIHOMO_TRANSPARENT_ENABLED}" == "1" && -n "${transparent_uids}" ]]; then
  IFS=',' read -r -a transparent_uid_array <<< "${transparent_uids}"
  for transparent_uid in "${transparent_uid_array[@]}"; do
    [[ -z "${transparent_uid}" ]] && continue
    iptables -t mangle -C OUTPUT -m owner --uid-owner "$transparent_uid" -j "$MIHOMO_CHAIN_MANGLE" 2>/dev/null || \
      iptables -t mangle -A OUTPUT -m owner --uid-owner "$transparent_uid" -j "$MIHOMO_CHAIN_MANGLE"
  done
fi

# nat：只把 GID=sidecar 进程的 DNS 查询转到 mihomo DNS
iptables -t nat -N "$MIHOMO_CHAIN_DNS" 2>/dev/null || iptables -t nat -F "$MIHOMO_CHAIN_DNS"
iptables -t nat -A "$MIHOMO_CHAIN_DNS" -p udp --dport 53 -j REDIRECT --to-ports "$MIHOMO_DNS_PORT"
iptables -t nat -A "$MIHOMO_CHAIN_DNS" -p tcp --dport 53 -j REDIRECT --to-ports "$MIHOMO_DNS_PORT"

iptables -t nat -C OUTPUT -m owner --gid-owner "$MIHOMO_TARGET_GID" -j "$MIHOMO_CHAIN_DNS" 2>/dev/null || \
  iptables -t nat -A OUTPUT -m owner --gid-owner "$MIHOMO_TARGET_GID" -j "$MIHOMO_CHAIN_DNS"
if [[ "${MIHOMO_TRANSPARENT_ENABLED}" == "1" && -n "${transparent_uids}" ]]; then
  IFS=',' read -r -a transparent_uid_array <<< "${transparent_uids}"
  for transparent_uid in "${transparent_uid_array[@]}"; do
    [[ -z "${transparent_uid}" ]] && continue
    iptables -t nat -C OUTPUT -m owner --uid-owner "$transparent_uid" -j "$MIHOMO_CHAIN_DNS" 2>/dev/null || \
      iptables -t nat -A OUTPUT -m owner --uid-owner "$transparent_uid" -j "$MIHOMO_CHAIN_DNS"
  done
fi

echo "mihomo sidecar rules applied for GID $MIHOMO_TARGET_GID"
