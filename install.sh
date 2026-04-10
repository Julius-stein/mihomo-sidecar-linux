#!/bin/bash
set -euo pipefail

show_help() {
  cat <<'EOF'
usage: install.sh [--config FILE] [--mihomo-home DIR] [--mihomo-bin PATH] [--systemd-unit-dir DIR] [--install-bin-dir DIR] [--subscription-url URL|--subscription-file FILE] [--skip-generate-config] [--skip-detect]

Install mihomo-sidecar-linux into one runtime directory.

Common path:
  sudo ./install.sh --mihomo-home /opt/mihomo-sidecar --subscription-url 'https://example.com/subscription'
EOF
}

if [[ $# -gt 0 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  show_help
  exit 0
fi

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${ROOT_DIR}/script/common.sh"
sidecar_load_config

install_config=""
systemd_unit_dir=""
install_bin_dir=""
subscription_url=""
subscription_file=""
skip_detect=0
skip_generate_config=0

resolve_mihomo_bin() {
  if [[ -n "${MIHOMO_BIN:-}" && -x "${MIHOMO_BIN}" ]]; then
    printf '%s\n' "${MIHOMO_BIN}"
    return 0
  fi

  local detected
  detected=$(command -v mihomo 2>/dev/null || true)
  if [[ -n "${detected}" ]]; then
    printf '%s\n' "${detected}"
    return 0
  fi

  return 1
}

detect_systemd_unit_dir() {
  local candidate
  if [[ -d /etc/systemd/system ]]; then
    printf '%s\n' "/etc/systemd/system"
    return 0
  fi
  candidate=$(pkg-config systemd --variable=systemdsystemunitdir 2>/dev/null || true)
  if [[ -n "${candidate}" ]]; then
    printf '%s\n' "${candidate}"
    return 0
  fi
  return 1
}

generate_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_hex(16))
PY
}

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
    --subscription-url)
      subscription_url=$2
      shift 2
      ;;
    --subscription-file)
      subscription_file=$2
      shift 2
      ;;
    --skip-generate-config)
      skip_generate_config=1
      shift
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

if [[ -n "${install_config}" ]]; then
  export MIHOMO_SIDECAR_CONFIG="${install_config}"
  sidecar_load_config
fi

if [[ -n "${subscription_url}" && -n "${subscription_file}" ]]; then
  echo "please use only one of --subscription-url or --subscription-file" >&2
  exit 2
fi

if resolved_mihomo_bin=$(resolve_mihomo_bin); then
  MIHOMO_BIN="${resolved_mihomo_bin}"
else
  cat >&2 <<'EOF'
mihomo binary not found.
Please install Mihomo first, then rerun install.sh.
Official releases:
https://github.com/MetaCubeX/mihomo/releases
EOF
  exit 1
fi

MIHOMO_CONFIG_YAML="${MIHOMO_HOME}/config.yaml"
MIHOMO_STATE_DIR="${MIHOMO_HOME}/state"
MIHOMO_RUNTIME_ENV="${MIHOMO_STATE_DIR}/runtime.env"
MIHOMO_SETUP_SCRIPT="${MIHOMO_HOME}/setup-rules.sh"
MIHOMO_CLEANUP_SCRIPT="${MIHOMO_HOME}/cleanup-rules.sh"
MIHOMO_NODE_SCRIPT="${MIHOMO_HOME}/select_node.py"
MIHOMO_SUB2MIHOMO_SCRIPT="${MIHOMO_HOME}/sub2mihomo.py"
MIHOMO_TRANSPARENT_MODE_SCRIPT="${MIHOMO_HOME}/transparent_mode.py"
MIHOMO_SECRET_FILE="${MIHOMO_STATE_DIR}/controller.secret"
sidecar_apply_derived_defaults

if [[ -z "${systemd_unit_dir}" ]] && command -v systemctl >/dev/null 2>&1; then
  detected_unit_dir=$(detect_systemd_unit_dir || true)
  if [[ -n "${detected_unit_dir}" && ( -w "${detected_unit_dir}" || ${EUID:-$(id -u)} -eq 0 ) ]]; then
    systemd_unit_dir="${detected_unit_dir}"
  fi
fi

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
MIHOMO_STATE_DIR="${MIHOMO_STATE_DIR}"
MIHOMO_RUNTIME_ENV="${MIHOMO_RUNTIME_ENV}"
MIHOMO_SETUP_SCRIPT="${MIHOMO_SETUP_SCRIPT}"
MIHOMO_CLEANUP_SCRIPT="${MIHOMO_CLEANUP_SCRIPT}"
MIHOMO_NODE_SCRIPT="${MIHOMO_NODE_SCRIPT}"
MIHOMO_SUB2MIHOMO_SCRIPT="${MIHOMO_SUB2MIHOMO_SCRIPT}"
MIHOMO_TRANSPARENT_MODE_SCRIPT="${MIHOMO_TRANSPARENT_MODE_SCRIPT}"
MIHOMO_SECRET_FILE="${MIHOMO_SECRET_FILE}"
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

if [[ ${skip_detect} -eq 0 ]]; then
  MIHOMO_SIDECAR_CONFIG="${MIHOMO_HOME}/sidecar.env" \
    python3 "${ROOT_DIR}/script/detect_runtime.py" --write "${MIHOMO_STATE_DIR}/runtime.env"
fi

if [[ ! -f "${MIHOMO_SECRET_FILE}" ]]; then
  generate_secret > "${MIHOMO_SECRET_FILE}"
fi
controller_secret=$(tr -d '\r\n' < "${MIHOMO_SECRET_FILE}")

subscription_source=""
if [[ -n "${subscription_url}" ]]; then
  subscription_source="${subscription_url}"
elif [[ -n "${subscription_file}" ]]; then
  subscription_source="${subscription_file}"
fi

if [[ -n "${subscription_source}" ]]; then
  MIHOMO_SIDECAR_CONFIG="${MIHOMO_HOME}/sidecar.env" \
    python3 "${ROOT_DIR}/script/sub2mihomo.py" \
      --source "${subscription_source}" \
      --all-nodes \
      --output "${MIHOMO_CONFIG_YAML}" \
      --secret "${controller_secret}" \
      --controller-secret-output "${MIHOMO_SECRET_FILE}"
elif [[ ${skip_generate_config} -eq 0 && ! -f "${MIHOMO_CONFIG_YAML}" ]]; then
  cat >&2 <<EOF
config.yaml not found and no subscription source was provided.
Provide one of:
  --subscription-url URL
  --subscription-file FILE
Or place an existing config at:
  ${MIHOMO_CONFIG_YAML}
EOF
  exit 1
fi

rendered_unit="${MIHOMO_HOME}/${MIHOMO_SERVICE_NAME}"
sed \
  -e "s|__MIHOMO_BIN__|${MIHOMO_BIN}|g" \
  -e "s|__MIHOMO_HOME__|${MIHOMO_HOME}|g" \
  "${ROOT_DIR}/systemd/mihomo-sidecar.service" > "${rendered_unit}"

if [[ -n "${systemd_unit_dir}" ]]; then
  install -d "${systemd_unit_dir}"
  install -m 0644 "${rendered_unit}" "${systemd_unit_dir}/${MIHOMO_SERVICE_NAME}"
fi

if [[ -n "${install_bin_dir}" ]]; then
  install -d "${install_bin_dir}"
  for src in sidecar sidecar-node sidecar-validate sidecar-verify sidecar-on sidecar-off sidecar-status; do
    install -m 0755 "${ROOT_DIR}/bin/${src}" "${install_bin_dir}/${src}"
  done
fi

echo "installed to ${MIHOMO_HOME}"
echo "mihomo binary: ${MIHOMO_BIN}"
echo "config: ${MIHOMO_CONFIG_YAML}"
echo "runtime env: ${MIHOMO_STATE_DIR}/runtime.env"
echo "controller secret: ${MIHOMO_SECRET_FILE}"
echo "systemd unit: ${rendered_unit}"
if [[ -n "${systemd_unit_dir}" ]]; then
  echo "installed unit copy: ${systemd_unit_dir}/${MIHOMO_SERVICE_NAME}"
fi
