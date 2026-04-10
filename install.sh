#!/bin/bash
set -euo pipefail

if [[ $# -gt 0 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  cat <<'EOF'
usage: install.sh [--config FILE] [--mihomo-home DIR] [--mihomo-bin PATH] [--systemd-unit-dir DIR] [--install-bin-dir DIR] [--skip-detect]

Install scripts, CLI wrappers, runtime config, and a rendered systemd unit.
EOF
  exit 0
fi

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${ROOT_DIR}/script/common.sh"
sidecar_load_config

install_config=""
systemd_unit_dir=""
install_bin_dir=""
skip_detect=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      install_config=$2
      shift 2
      ;;
    --mihomo-home)
      MIHOMO_HOME=$2
      shift 2
      ;;
    --mihomo-bin)
      MIHOMO_BIN=$2
      shift 2
      ;;
    --systemd-unit-dir)
      systemd_unit_dir=$2
      shift 2
      ;;
    --install-bin-dir)
      install_bin_dir=$2
      shift 2
      ;;
    --skip-detect)
      skip_detect=1
      shift
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -n "$install_config" ]]; then
  export MIHOMO_SIDECAR_CONFIG=$install_config
  sidecar_load_config
fi

MIHOMO_CONFIG_YAML="${MIHOMO_HOME}/config.yaml"
MIHOMO_STATE_DIR="${MIHOMO_HOME}/state"
MIHOMO_RUNTIME_ENV="${MIHOMO_STATE_DIR}/runtime.env"
MIHOMO_SETUP_SCRIPT="${MIHOMO_HOME}/setup-rules.sh"
MIHOMO_CLEANUP_SCRIPT="${MIHOMO_HOME}/cleanup-rules.sh"
MIHOMO_NODE_SCRIPT="${MIHOMO_HOME}/select_node.py"
MIHOMO_SUB2MIHOMO_SCRIPT="${MIHOMO_HOME}/sub2mihomo.py"

sidecar_apply_derived_defaults

mkdir -p "${MIHOMO_HOME}" "${MIHOMO_STATE_DIR}" "${MIHOMO_HOME}/bin"

cat > "${MIHOMO_HOME}/sidecar.env" <<EOF
MIHOMO_SIDECAR_NAME="${MIHOMO_SIDECAR_NAME}"
MIHOMO_SERVICE_NAME="${MIHOMO_SERVICE_NAME}"
MIHOMO_SIDECAR_GROUP="${MIHOMO_SIDECAR_GROUP}"
MIHOMO_TARGET_GID="${MIHOMO_TARGET_GID}"
MIHOMO_TARGET_UID="${MIHOMO_TARGET_UID}"
MIHOMO_TRANSPARENT_ENABLED="${MIHOMO_TRANSPARENT_ENABLED}"
MIHOMO_TRANSPARENT_UIDS="${MIHOMO_TRANSPARENT_UIDS}"
MIHOMO_BIN="${MIHOMO_BIN}"
MIHOMO_HOME="${MIHOMO_HOME}"
MIHOMO_CONFIG_YAML="${MIHOMO_CONFIG_YAML}"
MIHOMO_PROXY_GROUP="${MIHOMO_PROXY_GROUP}"
MIHOMO_API_HOST="${MIHOMO_API_HOST}"
MIHOMO_API_PORT="${MIHOMO_API_PORT}"
MIHOMO_DNS_PORT="${MIHOMO_DNS_PORT}"
MIHOMO_MIXED_PORT="${MIHOMO_MIXED_PORT}"
MIHOMO_TUN_DEV="${MIHOMO_TUN_DEV}"
MIHOMO_TUN_INET4="${MIHOMO_TUN_INET4}"
MIHOMO_FAKE_IP_RANGE="${MIHOMO_FAKE_IP_RANGE}"
MIHOMO_FWMARK="${MIHOMO_FWMARK}"
MIHOMO_ROUTE_TABLE="${MIHOMO_ROUTE_TABLE}"
MIHOMO_RULE_PRIORITY="${MIHOMO_RULE_PRIORITY}"
MIHOMO_CHAIN_MANGLE="${MIHOMO_CHAIN_MANGLE}"
MIHOMO_CHAIN_DNS="${MIHOMO_CHAIN_DNS}"
MIHOMO_DISCOVERY_DIRS="${MIHOMO_DISCOVERY_DIRS}"
EOF

for src in common.sh setup-rules.sh cleanup-rules.sh select_node.py sub2mihomo.py sidecar_config.py detect_runtime.py update_runtime_env.py transparent_mode.py verify.py; do
  install -m 0755 "${ROOT_DIR}/script/${src}" "${MIHOMO_HOME}/${src}"
done

for src in sidecar sidecar-node sidecar-validate sidecar-verify sidecar-on sidecar-off sidecar-status; do
  install -m 0755 "${ROOT_DIR}/bin/${src}" "${MIHOMO_HOME}/bin/${src}"
done

if [[ $skip_detect -eq 0 ]]; then
  MIHOMO_SIDECAR_CONFIG="${MIHOMO_HOME}/sidecar.env" \
    python3 "${ROOT_DIR}/script/detect_runtime.py" --write "${MIHOMO_STATE_DIR}/runtime.env"
fi

rendered_unit="${MIHOMO_HOME}/${MIHOMO_SERVICE_NAME}"
sed \
  -e "s|__MIHOMO_BIN__|${MIHOMO_BIN}|g" \
  -e "s|__MIHOMO_HOME__|${MIHOMO_HOME}|g" \
  "${ROOT_DIR}/systemd/mihomo-sidecar.service" > "${rendered_unit}"

if [[ -n "$systemd_unit_dir" ]]; then
  install -d "${systemd_unit_dir}"
  install -m 0644 "${rendered_unit}" "${systemd_unit_dir}/${MIHOMO_SERVICE_NAME}"
fi

if [[ -n "$install_bin_dir" ]]; then
  install -d "${install_bin_dir}"
  for src in sidecar sidecar-node sidecar-validate sidecar-verify sidecar-on sidecar-off sidecar-status; do
    install -m 0755 "${ROOT_DIR}/bin/${src}" "${install_bin_dir}/${src}"
  done
fi

echo "installed to ${MIHOMO_HOME}"
echo "runtime env: ${MIHOMO_STATE_DIR}/runtime.env"
echo "systemd unit: ${rendered_unit}"
