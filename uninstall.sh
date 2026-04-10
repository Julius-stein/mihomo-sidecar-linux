#!/bin/bash
set -euo pipefail

if [[ $# -gt 0 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  cat <<'EOF'
usage: uninstall.sh [--config FILE] [--mihomo-home DIR] [--systemd-unit-dir DIR] [--purge]

Remove installed files and optionally purge the runtime directory.
EOF
  exit 0
fi

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${ROOT_DIR}/script/common.sh"
sidecar_load_config

systemd_unit_dir=""
purge=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      export MIHOMO_SIDECAR_CONFIG=$2
      sidecar_load_config
      shift 2
      ;;
    --mihomo-home)
      MIHOMO_HOME=$2
      sidecar_apply_derived_defaults
      shift 2
      ;;
    --systemd-unit-dir)
      systemd_unit_dir=$2
      shift 2
      ;;
    --purge)
      purge=1
      shift
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 2
      ;;
  esac
done

MIHOMO_CONFIG_YAML="${MIHOMO_HOME}/config.yaml"
MIHOMO_STATE_DIR="${MIHOMO_HOME}/state"
MIHOMO_RUNTIME_ENV="${MIHOMO_STATE_DIR}/runtime.env"
MIHOMO_SETUP_SCRIPT="${MIHOMO_HOME}/setup-rules.sh"
MIHOMO_CLEANUP_SCRIPT="${MIHOMO_HOME}/cleanup-rules.sh"
MIHOMO_NODE_SCRIPT="${MIHOMO_HOME}/select_node.py"
MIHOMO_SUB2MIHOMO_SCRIPT="${MIHOMO_HOME}/sub2mihomo.py"

if [[ -x "${MIHOMO_CLEANUP_SCRIPT}" ]]; then
  MIHOMO_SIDECAR_CONFIG="${MIHOMO_HOME}/sidecar.env" "${MIHOMO_CLEANUP_SCRIPT}" || true
fi

if [[ -n "$systemd_unit_dir" && -f "${systemd_unit_dir}/${MIHOMO_SERVICE_NAME}" ]]; then
  rm -f "${systemd_unit_dir}/${MIHOMO_SERVICE_NAME}"
fi

if [[ $purge -eq 1 ]]; then
  rm -f \
    "${MIHOMO_HOME}/common.sh" \
    "${MIHOMO_HOME}/setup-rules.sh" \
    "${MIHOMO_HOME}/cleanup-rules.sh" \
    "${MIHOMO_HOME}/select_node.py" \
    "${MIHOMO_HOME}/sub2mihomo.py" \
    "${MIHOMO_HOME}/sidecar_config.py" \
    "${MIHOMO_HOME}/detect_runtime.py" \
    "${MIHOMO_HOME}/update_runtime_env.py" \
    "${MIHOMO_HOME}/transparent_mode.py" \
    "${MIHOMO_HOME}/verify.py" \
    "${MIHOMO_HOME}/${MIHOMO_SERVICE_NAME}"
  rm -rf "${MIHOMO_HOME}/bin" "${MIHOMO_STATE_DIR}"
fi

echo "uninstall finished for ${MIHOMO_HOME}"
