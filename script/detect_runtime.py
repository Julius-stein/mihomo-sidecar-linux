#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Set, Tuple

from sidecar_config import dump_env_file, load_config


def run_lines(cmd: Sequence[str]) -> List[str]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0 and not proc.stdout:
        return []
    return proc.stdout.splitlines()


def collect_used_tun_names() -> Set[str]:
    names: Set[str] = set()
    pattern = re.compile(r"^\d+:\s+([^:]+):")
    for line in run_lines(["ip", "-o", "link", "show"]):
        match = pattern.match(line)
        if match:
            names.add(match.group(1))
    return names


def collect_used_ports() -> Set[int]:
    used: Set[int] = set()
    for line in run_lines(["ss", "-H", "-ltnu"]):
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[4]
        if local.startswith("[") and "]:" in local:
            port_str = local.rsplit("]:", 1)[1]
        elif ":" in local:
            port_str = local.rsplit(":", 1)[1]
        else:
            continue
        if port_str.isdigit():
            used.add(int(port_str))
    return used


def collect_iptables_chains(table: str) -> Set[str]:
    chains: Set[str] = set()
    chain_pattern = re.compile(r"^-N\s+(\S+)$")
    for line in run_lines(["iptables", "-t", table, "-S"]):
        match = chain_pattern.match(line.strip())
        if match:
            chains.add(match.group(1))
    return chains


def collect_route_tables_from_rules() -> Tuple[Set[int], Set[int], Set[int]]:
    marks: Set[int] = set()
    tables: Set[int] = set()
    priorities: Set[int] = set()
    priority_pattern = re.compile(r"^\s*(\d+):")
    mark_pattern = re.compile(r"\bfwmark\s+(0x[0-9a-fA-F]+|\d+)\b")
    table_pattern = re.compile(r"\blookup\s+(\d+)\b")

    for line in run_lines(["ip", "rule", "show"]):
        priority_match = priority_pattern.match(line)
        if priority_match:
            priorities.add(int(priority_match.group(1)))
        mark_match = mark_pattern.search(line)
        if mark_match:
            marks.add(int(mark_match.group(1), 0))
        table_match = table_pattern.search(line)
        if table_match:
            tables.add(int(table_match.group(1)))
    return marks, tables, priorities


def collect_named_route_tables() -> Set[int]:
    tables: Set[int] = set()
    for file_path in [Path("/etc/iproute2/rt_tables"), Path("/usr/lib/iproute2/rt_tables")]:
        if not file_path.is_file():
            continue
        for raw_line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if parts and parts[0].isdigit():
                tables.add(int(parts[0]))
    return tables


def collect_local_networks() -> Set[ipaddress.IPv4Network]:
    nets: Set[ipaddress.IPv4Network] = set()
    pattern = re.compile(r"\binet\s+([0-9./]+)\b")
    for line in run_lines(["ip", "-o", "-4", "addr", "show"]):
        match = pattern.search(line)
        if not match:
            continue
        iface = ipaddress.ip_interface(match.group(1))
        nets.add(iface.network)
    return nets


def walk_candidate_files(scan_dirs: Iterable[Path]) -> Iterator[Path]:
    seen: Set[Path] = set()
    allowed_names = {"config.yaml", "config.yml", "runtime.env", "sidecar.env"}
    for root in scan_dirs:
        if not root.exists():
            continue
        if root.is_file():
            if root.name in allowed_names and root not in seen:
                seen.add(root)
                yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel_depth = len(Path(dirpath).relative_to(root).parts)
            if rel_depth >= 3:
                dirnames[:] = []
            dirnames[:] = [name for name in dirnames if name not in {"docs", "examples", ".git", "__pycache__"}]
            for name in filenames:
                if name in allowed_names:
                    file_path = Path(dirpath) / name
                    if file_path not in seen:
                        seen.add(file_path)
                        yield file_path


def extract_networks_from_yaml(path: Path) -> Tuple[Set[ipaddress.IPv4Network], Set[ipaddress.IPv4Network]]:
    fake_ip_nets: Set[ipaddress.IPv4Network] = set()
    tun_nets: Set[ipaddress.IPv4Network] = set()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    inet4_block = False

    for line in lines:
        fake_match = re.search(r"\bfake-ip-range:\s*([0-9./]+)", line)
        if fake_match:
            fake_ip_nets.add(ipaddress.ip_network(fake_match.group(1), strict=False))
        if re.match(r"^\s*inet4-address:\s*$", line):
            inet4_block = True
            continue
        if inet4_block:
            addr_match = re.match(r"^\s*-\s*([0-9./]+)\s*$", line)
            if addr_match:
                tun_nets.add(ipaddress.ip_interface(addr_match.group(1)).network)
                continue
            if line.strip() and not line.startswith(" "):
                inet4_block = False
    return fake_ip_nets, tun_nets


def extract_runtime_values_from_env(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def collect_config_conflicts(
    scan_dirs: Iterable[Path],
    ignored_files: Set[Path],
) -> Tuple[Set[ipaddress.IPv4Network], Set[ipaddress.IPv4Network], Set[str], Set[int], Set[int], Set[int], Set[int], Set[str], Set[str]]:
    fake_ip_nets: Set[ipaddress.IPv4Network] = set()
    tun_nets: Set[ipaddress.IPv4Network] = set()
    tun_names: Set[str] = set()
    api_ports: Set[int] = set()
    dns_ports: Set[int] = set()
    marks: Set[int] = set()
    tables: Set[int] = set()
    mangle_chains: Set[str] = set()
    nat_chains: Set[str] = set()

    for path in walk_candidate_files(scan_dirs):
        if path.resolve() in ignored_files:
            continue
        if path.suffix in {".yaml", ".yml"}:
            fake_nets, local_tun_nets = extract_networks_from_yaml(path)
            fake_ip_nets.update(fake_nets)
            tun_nets.update(local_tun_nets)
            continue
        if path.suffix != ".env":
            continue
        values = extract_runtime_values_from_env(path)
        if "MIHOMO_FAKE_IP_RANGE" in values:
            fake_ip_nets.add(ipaddress.ip_network(values["MIHOMO_FAKE_IP_RANGE"], strict=False))
        if "MIHOMO_TUN_INET4" in values:
            tun_nets.add(ipaddress.ip_interface(values["MIHOMO_TUN_INET4"]).network)
        if "MIHOMO_TUN_DEV" in values:
            tun_names.add(values["MIHOMO_TUN_DEV"])
        if values.get("MIHOMO_API_PORT", "").isdigit():
            api_ports.add(int(values["MIHOMO_API_PORT"]))
        if values.get("MIHOMO_DNS_PORT", "").isdigit():
            dns_ports.add(int(values["MIHOMO_DNS_PORT"]))
        if values.get("MIHOMO_FWMARK"):
            marks.add(int(values["MIHOMO_FWMARK"], 0))
        if values.get("MIHOMO_ROUTE_TABLE", "").isdigit():
            tables.add(int(values["MIHOMO_ROUTE_TABLE"]))
        if values.get("MIHOMO_CHAIN_MANGLE"):
            mangle_chains.add(values["MIHOMO_CHAIN_MANGLE"])
        if values.get("MIHOMO_CHAIN_DNS"):
            nat_chains.add(values["MIHOMO_CHAIN_DNS"])
    return fake_ip_nets, tun_nets, tun_names, api_ports, dns_ports, marks, tables, mangle_chains, nat_chains


def choose_name(preferred: str, used: Set[str]) -> str:
    if preferred not in used:
        return preferred
    for idx in range(1, 256):
        candidate = f"{preferred}-{idx}"
        if candidate not in used:
            return candidate
    raise RuntimeError(f"找不到可用的 TUN 名称，起始值为 {preferred}")


def choose_chain_name(preferred: str, used: Set[str]) -> str:
    if preferred not in used:
        return preferred
    base = preferred[:22]
    for idx in range(1, 1000):
        candidate = f"{base}_{idx}"
        if candidate not in used:
            return candidate
    raise RuntimeError(f"找不到可用的 chain 名称，起始值为 {preferred}")


def choose_int(preferred: int, used: Set[int], lower_bound: int = 1) -> int:
    candidate = max(preferred, lower_bound)
    while candidate in used:
        candidate += 1
    return candidate


def choose_mark(preferred: str, used: Set[int]) -> str:
    mark_value = choose_int(int(preferred, 0), used, lower_bound=1)
    return hex(mark_value)


def overlaps_any(target: ipaddress.IPv4Network, others: Iterable[ipaddress.IPv4Network]) -> bool:
    return any(target.overlaps(other) for other in others)


def iter_same_prefix_candidates(preferred: ipaddress.IPv4Network, parent: ipaddress.IPv4Network) -> Iterator[ipaddress.IPv4Network]:
    if preferred.subnet_of(parent):
        for subnet in parent.subnets(new_prefix=preferred.prefixlen):
            if subnet == preferred:
                continue
            yield subnet


def choose_fake_ip_range(
    preferred: str,
    used_fake_ip: Set[ipaddress.IPv4Network],
    used_local: Set[ipaddress.IPv4Network],
    used_tun_nets: Set[ipaddress.IPv4Network],
) -> str:
    preferred_net = ipaddress.ip_network(preferred, strict=False)
    used = used_fake_ip | used_local | used_tun_nets
    if not overlaps_any(preferred_net, used):
        return preferred

    reserved_supernet = ipaddress.ip_network("198.18.0.0/15")

    # 先尝试同等前缀长度的其他候选，再逐步细分到更小网段，避免因为一小段 TUN 子网占用就整片 /16 不可用。
    max_prefixlen = 24
    preferred_parents = []
    if preferred_net.subnet_of(ipaddress.ip_network("198.19.0.0/16")):
        preferred_parents.append(ipaddress.ip_network("198.19.0.0/16"))
    preferred_parents.append(reserved_supernet)
    for candidate_prefix in range(preferred_net.prefixlen, max_prefixlen + 1):
        for parent in preferred_parents:
            if candidate_prefix < parent.prefixlen:
                continue
            for candidate in parent.subnets(new_prefix=candidate_prefix):
                if candidate_prefix == preferred_net.prefixlen and candidate == preferred_net:
                    continue
                if overlaps_any(candidate, used):
                    continue
                return f"{candidate.network_address + 1}/{candidate.prefixlen}"
    raise RuntimeError(f"找不到可用的 fake-ip-range，起始值为 {preferred}")


def choose_tun_inet4(
    preferred: str,
    used_tun_nets: Set[ipaddress.IPv4Network],
    used_local: Set[ipaddress.IPv4Network],
    used_fake_ip: Set[ipaddress.IPv4Network],
) -> str:
    preferred_iface = ipaddress.ip_interface(preferred)
    preferred_net = preferred_iface.network
    used = used_tun_nets | used_local | used_fake_ip
    if not overlaps_any(preferred_net, used):
        return preferred

    first_parent = ipaddress.ip_network("198.19.0.0/16")
    second_parent = ipaddress.ip_network("198.18.0.0/15")
    for parent in [first_parent, second_parent]:
        for candidate in iter_same_prefix_candidates(preferred_net, parent):
            if overlaps_any(candidate, used):
                continue
            first_host = candidate.network_address + 1
            return f"{first_host}/{candidate.prefixlen}"
    raise RuntimeError(f"找不到可用的 tun subnet，起始值为 {preferred}")


def build_runtime_config(config: Dict[str, str], scan_dirs: List[Path]) -> Dict[str, str]:
    used_tun_names = collect_used_tun_names()
    used_ports = collect_used_ports()
    used_marks, used_rule_tables, used_priorities = collect_route_tables_from_rules()
    used_named_tables = collect_named_route_tables()
    used_local_nets = collect_local_networks()
    used_mangle_chains = collect_iptables_chains("mangle")
    used_nat_chains = collect_iptables_chains("nat")
    ignored_files = {
        Path(config["MIHOMO_CONFIG_YAML"]).expanduser().resolve(),
        Path(config["MIHOMO_RUNTIME_ENV"]).expanduser().resolve(),
        (Path(config["MIHOMO_HOME"]).expanduser() / "sidecar.env").resolve(),
    }
    scan_fake_ip, scan_tun_nets, scan_tun_names, scan_api_ports, scan_dns_ports, scan_marks, scan_tables, scan_mangle_chains, scan_nat_chains = collect_config_conflicts(
        scan_dirs,
        ignored_files=ignored_files,
    )

    desired_tun = config["MIHOMO_TUN_DEV"]
    resolved_tun = choose_name(desired_tun, used_tun_names | scan_tun_names)

    resolved_api_port = choose_int(int(config["MIHOMO_API_PORT"]), used_ports | scan_api_ports)
    used_ports.add(resolved_api_port)
    resolved_dns_port = choose_int(int(config["MIHOMO_DNS_PORT"]), used_ports | scan_dns_ports)
    resolved_mixed_port = choose_int(int(config["MIHOMO_MIXED_PORT"]), used_ports | {resolved_api_port, resolved_dns_port})

    resolved_mark = choose_mark(config["MIHOMO_FWMARK"], used_marks | scan_marks)
    resolved_table = choose_int(
        int(config["MIHOMO_ROUTE_TABLE"]),
        used_rule_tables | used_named_tables | scan_tables,
    )
    resolved_priority = choose_int(int(config["MIHOMO_RULE_PRIORITY"]), used_priorities)
    resolved_fake_ip = choose_fake_ip_range(config["MIHOMO_FAKE_IP_RANGE"], scan_fake_ip, used_local_nets, scan_tun_nets)
    resolved_tun_inet4 = choose_tun_inet4(
        config["MIHOMO_TUN_INET4"],
        scan_tun_nets,
        used_local_nets,
        scan_fake_ip | {ipaddress.ip_network(resolved_fake_ip, strict=False)},
    )
    resolved_mangle_chain = choose_chain_name(config["MIHOMO_CHAIN_MANGLE"], used_mangle_chains | scan_mangle_chains)
    resolved_nat_chain = choose_chain_name(config["MIHOMO_CHAIN_DNS"], used_nat_chains | scan_nat_chains)

    runtime = dict(config)
    runtime.update(
        {
            "MIHOMO_TUN_DEV": resolved_tun,
            "MIHOMO_API_PORT": str(resolved_api_port),
            "MIHOMO_DNS_PORT": str(resolved_dns_port),
            "MIHOMO_MIXED_PORT": str(resolved_mixed_port),
            "MIHOMO_FWMARK": resolved_mark,
            "MIHOMO_ROUTE_TABLE": str(resolved_table),
            "MIHOMO_RULE_PRIORITY": str(resolved_priority),
            "MIHOMO_FAKE_IP_RANGE": resolved_fake_ip,
            "MIHOMO_TUN_INET4": resolved_tun_inet4,
            "MIHOMO_CHAIN_MANGLE": resolved_mangle_chain,
            "MIHOMO_CHAIN_DNS": resolved_nat_chain,
        }
    )
    return runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检测 Mihomo sidecar 运行时资源并输出 runtime.env")
    parser.add_argument(
        "--config",
        help="sidecar.env 路径；默认按仓库 config/sidecar.env 和当前运行目录的 sidecar.env 自动发现",
    )
    parser.add_argument(
        "--write",
        help="把结果写入指定 runtime.env 文件；默认打印到 stdout",
    )
    parser.add_argument(
        "--scan-dir",
        action="append",
        default=[],
        help="额外扫描目录，用于检测 fake-ip-range / tun subnet / ports 冲突；默认不会扫描当前工作目录",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve()
    config = load_config(script_path, explicit_config=args.config)

    scan_dirs: List[Path] = []
    for raw in config.get("MIHOMO_DISCOVERY_DIRS", "").split(":"):
        if raw:
            scan_dirs.append(Path(raw).expanduser())
    for raw in args.scan_dir:
        scan_dirs.append(Path(raw).expanduser())
    config_yaml = Path(config["MIHOMO_CONFIG_YAML"]).expanduser()
    scan_dirs.extend([config_yaml.parent, Path(config["MIHOMO_HOME"]).expanduser()])

    runtime = build_runtime_config(config, scan_dirs)
    output = Path(args.write).expanduser() if args.write else None

    if output:
        dump_env_file(runtime, output, header="Generated by script/detect_runtime.py")
    else:
        for key in sorted(runtime):
            print(f'{key}="{runtime[key]}"')


if __name__ == "__main__":
    main()
