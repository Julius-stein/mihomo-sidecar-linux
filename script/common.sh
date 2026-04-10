#!/bin/bash
# Shared config loading for mihomo-sidecar-linux.

sidecar_source_env_file() {
  local env_file=${1:-}
  if [[ -z "$env_file" || ! -f "$env_file" ]]; then
    return 0
  fi

  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

sidecar_set_defaults() {
  : "${MIHOMO_SIDECAR_NAME:=mihomo-sidecar}"
  : "${MIHOMO_SERVICE_NAME:=mihomo-sidecar.service}"
  : "${MIHOMO_SIDECAR_GROUP:=sidecar}"
  : "${MIHOMO_TARGET_GID:=1026}"
  : "${MIHOMO_TARGET_UID:=}"
  : "${MIHOMO_TRANSPARENT_ENABLED:=0}"
  : "${MIHOMO_TRANSPARENT_UIDS:=}"

  : "${MIHOMO_BIN:=/usr/local/bin/mihomo}"
  : "${MIHOMO_HOME:=${HOME}/.mihomo}"

  : "${MIHOMO_PROXY_GROUP:=PROXY}"
  : "${MIHOMO_API_HOST:=127.0.0.1}"
  : "${MIHOMO_API_PORT:=9091}"
  : "${MIHOMO_DNS_PORT:=1054}"
  : "${MIHOMO_MIXED_PORT:=7891}"

  : "${MIHOMO_TUN_DEV:=Meta-sidecar}"
  : "${MIHOMO_TUN_INET4:=198.19.0.1/30}"
  : "${MIHOMO_FAKE_IP_RANGE:=198.19.0.1/16}"

  : "${MIHOMO_FWMARK:=0x2}"
  : "${MIHOMO_ROUTE_TABLE:=101}"
  : "${MIHOMO_RULE_PRIORITY:=1001}"
  : "${MIHOMO_CHAIN_MANGLE:=MIHOMO_SIDECAR}"
  : "${MIHOMO_CHAIN_DNS:=MIHOMO_DNS_SIDECAR}"
}

sidecar_apply_derived_defaults() {
  : "${MIHOMO_CONFIG_YAML:=${MIHOMO_HOME}/config.yaml}"
  : "${MIHOMO_STATE_DIR:=${MIHOMO_HOME}/state}"
  : "${MIHOMO_RUNTIME_ENV:=${MIHOMO_STATE_DIR}/runtime.env}"
  : "${MIHOMO_SETUP_SCRIPT:=${MIHOMO_HOME}/setup-rules.sh}"
  : "${MIHOMO_CLEANUP_SCRIPT:=${MIHOMO_HOME}/cleanup-rules.sh}"
  : "${MIHOMO_NODE_SCRIPT:=${MIHOMO_HOME}/select_node.py}"
  : "${MIHOMO_SUB2MIHOMO_SCRIPT:=${MIHOMO_HOME}/sub2mihomo.py}"
  : "${MIHOMO_TRANSPARENT_MODE_SCRIPT:=${MIHOMO_HOME}/transparent_mode.py}"
  : "${MIHOMO_SECRET_FILE:=${MIHOMO_STATE_DIR}/controller.secret}"
  : "${MIHOMO_DISCOVERY_DIRS:=${MIHOMO_HOME}:${PWD}}"
}

sidecar_load_config() {
  local script_dir repo_root repo_config explicit_config home_config runtime_config

  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
  repo_root=$(cd -- "${script_dir}/.." && pwd -P 2>/dev/null || true)
  repo_config="${repo_root}/config/sidecar.env"
  explicit_config=${MIHOMO_SIDECAR_CONFIG:-}

  sidecar_set_defaults
  sidecar_source_env_file "$repo_config"
  sidecar_source_env_file "$explicit_config"

  sidecar_apply_derived_defaults
  home_config="${MIHOMO_HOME}/sidecar.env"
  sidecar_source_env_file "$home_config"

  sidecar_apply_derived_defaults
  runtime_config=${MIHOMO_RUNTIME_ENV:-"${MIHOMO_HOME}/state/runtime.env"}
  sidecar_source_env_file "$runtime_config"
  sidecar_apply_derived_defaults
}
