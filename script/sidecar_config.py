#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable


DEFAULTS: Dict[str, str] = {
    "MIHOMO_SIDECAR_NAME": "mihomo-sidecar",
    "MIHOMO_SERVICE_NAME": "mihomo-sidecar.service",
    "MIHOMO_SIDECAR_GROUP": "sidecar",
    "MIHOMO_TARGET_GID": "1026",
    "MIHOMO_TARGET_UID": "",
    "MIHOMO_TRANSPARENT_ENABLED": "0",
    "MIHOMO_TRANSPARENT_UIDS": "",
    "MIHOMO_BIN": "",
    "MIHOMO_PROXY_GROUP": "PROXY",
    "MIHOMO_API_HOST": "127.0.0.1",
    "MIHOMO_API_PORT": "9091",
    "MIHOMO_DNS_PORT": "1054",
    "MIHOMO_MIXED_PORT": "7891",
    "MIHOMO_TUN_DEV": "Meta-sidecar",
    "MIHOMO_TUN_INET4": "198.19.0.1/30",
    "MIHOMO_FAKE_IP_RANGE": "198.19.0.1/16",
    "MIHOMO_FWMARK": "0x2",
    "MIHOMO_ROUTE_TABLE": "101",
    "MIHOMO_RULE_PRIORITY": "1001",
    "MIHOMO_CHAIN_MANGLE": "MIHOMO_SIDECAR",
    "MIHOMO_CHAIN_DNS": "MIHOMO_DNS_SIDECAR",
}

DERIVED_DEFAULTS: Dict[str, str] = {
    "MIHOMO_CONFIG_YAML": "${MIHOMO_HOME}/config.yaml",
    "MIHOMO_STATE_DIR": "${MIHOMO_HOME}/state",
    "MIHOMO_RUNTIME_ENV": "${MIHOMO_STATE_DIR}/runtime.env",
    "MIHOMO_SETUP_SCRIPT": "${MIHOMO_HOME}/setup-rules.sh",
    "MIHOMO_CLEANUP_SCRIPT": "${MIHOMO_HOME}/cleanup-rules.sh",
    "MIHOMO_NODE_SCRIPT": "${MIHOMO_HOME}/select_node.py",
    "MIHOMO_SUB2MIHOMO_SCRIPT": "${MIHOMO_HOME}/sub2mihomo.py",
    "MIHOMO_TRANSPARENT_MODE_SCRIPT": "${MIHOMO_HOME}/transparent_mode.py",
    "MIHOMO_SECRET_FILE": "${MIHOMO_STATE_DIR}/controller.secret",
    "MIHOMO_DISCOVERY_DIRS": "",
}

_VAR_PATTERN = re.compile(r"\$(\w+)|\$\{([^}]+)\}")


def _expand(value: str, env: Dict[str, str]) -> str:
    merged = dict(os.environ)
    merged.update(env)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2) or ""
        return merged.get(key, match.group(0))

    return _VAR_PATTERN.sub(repl, value)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env_file(path: Path, env: Dict[str, str] | None = None) -> Dict[str, str]:
    env = dict(env or {})
    parsed: Dict[str, str] = {}
    if not path.is_file():
        return parsed

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value.strip())
        local_env = dict(env)
        local_env.update(parsed)
        parsed[key] = _expand(value, local_env)
    return parsed


def apply_defaults(config: Dict[str, str], explicit_keys: set[str] | None = None) -> Dict[str, str]:
    explicit_keys = explicit_keys or set()
    out = dict(config)
    for key, value in DEFAULTS.items():
        out.setdefault(key, _expand(value, out))
    for key, value in DERIVED_DEFAULTS.items():
        raw_value = config[key] if key in explicit_keys and key in config else value
        out[key] = _expand(raw_value, out)
    for key in list(out):
        out[key] = _expand(out[key], out)
    return out


def default_mihomo_home(script_path: Path, explicit_config: str | None = None) -> str:
    resolved = script_path.resolve()
    script_dir = resolved.parent
    if explicit_config:
        return str(Path(explicit_config).expanduser().resolve().parent)
    if (script_dir / "sidecar.env").is_file():
        return str(script_dir)
    if (script_dir.parent / "sidecar.env").is_file():
        return str(script_dir.parent)
    if script_dir.name == "script" and (script_dir.parent / "install.sh").is_file():
        return str(script_dir.parent / "workdir")
    return str(script_dir)


def _candidate_config_paths(script_path: Path, explicit_config: str | None) -> Iterable[Path]:
    if explicit_config:
        yield Path(explicit_config).expanduser()
    return


def load_config(script_path: Path, explicit_config: str | None = None) -> Dict[str, str]:
    config: Dict[str, str] = {}
    explicit_keys: set[str] = set()
    fallback_home = default_mihomo_home(script_path, explicit_config)
    config["MIHOMO_HOME"] = fallback_home
    config.update(apply_defaults(config, explicit_keys))

    for candidate in _candidate_config_paths(script_path, explicit_config):
        parsed = parse_env_file(candidate, config)
        explicit_keys.update(parsed)
        config.update(parsed)
        if not config.get("MIHOMO_HOME"):
            config["MIHOMO_HOME"] = fallback_home
        config = apply_defaults(config, explicit_keys)

    home_config = Path(config["MIHOMO_HOME"]).expanduser() / "sidecar.env"
    parsed_home = parse_env_file(home_config, config)
    explicit_keys.update(parsed_home)
    config.update(parsed_home)
    if not config.get("MIHOMO_HOME"):
        config["MIHOMO_HOME"] = fallback_home
    config = apply_defaults(config, explicit_keys)

    runtime_env = Path(config["MIHOMO_RUNTIME_ENV"]).expanduser()
    parsed_runtime = parse_env_file(runtime_env, config)
    explicit_keys.update(parsed_runtime)
    config.update(parsed_runtime)
    if not config.get("MIHOMO_HOME"):
        config["MIHOMO_HOME"] = fallback_home
    return apply_defaults(config, explicit_keys)


def dump_env_file(config: Dict[str, str], path: Path, header: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if header:
        for line in header.splitlines():
            lines.append(f"# {line}".rstrip())
    for key in sorted(config):
        value = config[key].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{value}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_mihomo_secret(config: Dict[str, str]) -> str | None:
    env_secret = os.environ.get("MIHOMO_API_SECRET")
    if env_secret:
        return env_secret

    config_yaml = Path(config["MIHOMO_CONFIG_YAML"]).expanduser()
    if not config_yaml.is_file():
        return None

    secret_pattern = re.compile(r'^\s*secret:\s*"?([^"\n#]+)"?\s*$')
    for line in config_yaml.read_text(encoding="utf-8", errors="replace").splitlines():
        match = secret_pattern.match(line)
        if match:
            return match.group(1).strip()
    return None
