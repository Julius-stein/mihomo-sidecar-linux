#!/bin/bash
set -euo pipefail

show_help() {
  cat <<'EOF'
usage: install.sh [--config FILE] [--mihomo-bin PATH] [--systemd-unit-dir DIR] [--install-bin-dir DIR] [--skip-detect]

Install mihomo-sidecar-linux runtime files and system integration.

Common path:
  sudo ./install.sh

Default command wrapper directory:
  /usr/local/bin

Notes:
  - install.sh must be run as root
  - work dir is fixed to ./workdir under the cloned repository
EOF
}

if [[ $# -gt 0 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  show_help
  exit 0
fi

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  cat >&2 <<'EOF'
install.sh must be run as root.

Please rerun with sudo, for example:
  sudo ./install.sh
EOF
  exit 1
fi

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${ROOT_DIR}/script/common.sh"
sidecar_load_config

install_config=""
systemd_unit_dir=""
install_bin_dir=""
skip_detect=0

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

normalize_dir_path() {
  python3 - "$1" <<'PY'
import os
import sys

print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
}

write_bin_wrapper() {
  local target_dir=$1 cmd_name=$2 target_path=$3 wrapper_path
  wrapper_path="${target_dir}/${cmd_name}"
  cat > "${wrapper_path}" <<EOF
#!/bin/bash
exec "${target_path}" "\$@"
EOF
  chmod 0755 "${wrapper_path}"
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

if [[ -n "${install_config}" ]]; then
  export MIHOMO_SIDECAR_CONFIG="${install_config}"
  sidecar_load_config
fi

MIHOMO_HOME=$(normalize_dir_path "${ROOT_DIR}/workdir")

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

if [[ -z "${install_bin_dir}" ]]; then
  install_bin_dir="/usr/local/bin"
fi
install_bin_dir=$(normalize_dir_path "${install_bin_dir}")

if [[ -z "${systemd_unit_dir}" ]]; then
  cat >&2 <<'EOF'
failed to detect the systemd unit directory.

Please rerun with:
  --systemd-unit-dir /etc/systemd/system
EOF
  exit 1
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

for src in sidecar sidecar-node sidecar-subscribe sidecar-validate sidecar-verify sidecar-on sidecar-off sidecar-status; do
  install -m 0755 "${ROOT_DIR}/bin/${src}" "${MIHOMO_HOME}/bin/${src}"
done

if [[ ${skip_detect} -eq 0 ]]; then
  MIHOMO_SIDECAR_CONFIG="${MIHOMO_HOME}/sidecar.env" \
    python3 "${ROOT_DIR}/script/detect_runtime.py" --write "${MIHOMO_STATE_DIR}/runtime.env"
fi

if [[ ! -f "${MIHOMO_SECRET_FILE}" ]]; then
  generate_secret > "${MIHOMO_SECRET_FILE}"
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
  for src in sidecar sidecar-node sidecar-subscribe sidecar-validate sidecar-verify sidecar-on sidecar-off sidecar-status; do
    write_bin_wrapper "${install_bin_dir}" "${src}" "${MIHOMO_HOME}/bin/${src}"
  done
fi

cat <<EOF
Install completed.

Work dir:
  ${MIHOMO_HOME}

Installed:
  mihomo binary      ${MIHOMO_BIN}
  sidecar env        ${MIHOMO_HOME}/sidecar.env
  runtime env        ${MIHOMO_STATE_DIR}/runtime.env
  controller secret  ${MIHOMO_SECRET_FILE}
  systemd unit       ${systemd_unit_dir}/${MIHOMO_SERVICE_NAME}
  command wrappers   ${install_bin_dir}
EOF

if [[ -f "${MIHOMO_CONFIG_YAML}" ]]; then
  echo
  echo "Config status:"
  echo "  existing config.yaml detected at ${MIHOMO_CONFIG_YAML}"
else
  echo
  echo "Config status:"
  echo "  config.yaml not created yet"
fi

cat <<EOF

Next steps:
  1. Generate config:
     sidecar-subscribe --url 'https://example.com/subscription' --all-nodes
  2. Reload systemd:
     sudo systemctl daemon-reload
  3. Enable service:
     sudo systemctl enable --now ${MIHOMO_SERVICE_NAME}
  4. Verify:
     sudo sidecar-verify
EOF
