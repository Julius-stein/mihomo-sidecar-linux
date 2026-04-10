#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from sidecar_config import load_config


@dataclass
class CheckResult:
    status: str
    name: str
    detail: str


def run_cmd(cmd: List[str], *, sudo: bool = False) -> subprocess.CompletedProcess[str]:
    full_cmd = list(cmd)
    if sudo and os.geteuid() != 0 and shutil.which("sudo"):
        full_cmd = ["sudo", "-n"] + full_cmd
    return subprocess.run(full_cmd, capture_output=True, text=True, check=False)


def add_result(results: List[CheckResult], status: str, name: str, detail: str) -> None:
    results.append(CheckResult(status=status, name=name, detail=detail))


def systemctl_is_active(service_name: str) -> tuple[bool, str]:
    proc = run_cmd(["systemctl", "is-active", service_name])
    return proc.returncode == 0 and proc.stdout.strip() == "active", (proc.stdout or proc.stderr).strip()


def ip_link_exists(name: str) -> bool:
    proc = run_cmd(["ip", "link", "show", name])
    return proc.returncode == 0


def ip_rule_matches(fwmark: str, table: str, priority: str) -> bool:
    proc = run_cmd(["ip", "rule", "show"])
    if proc.returncode != 0:
        return False
    normalized_mark = fwmark.lower()
    for line in proc.stdout.splitlines():
        lowered = line.lower()
        if f"fwmark {normalized_mark}" not in lowered:
            continue
        if f"lookup {table}" not in lowered and f"table {table}" not in lowered:
            continue
        if lowered.startswith(f"{priority}:") or f" pref {priority}" in lowered or f" priority {priority}" in lowered:
            return True
    return False


def ip_route_matches(table: str, tun_dev: str) -> bool:
    proc = run_cmd(["ip", "route", "show", "table", table])
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        normalized = " ".join(line.split())
        if normalized.startswith(f"default dev {tun_dev}"):
            return True
    return False


def iptables_contains(table: str, expected: Iterable[str]) -> tuple[bool, str]:
    proc = run_cmd(["iptables", "-t", table, "-S"], sudo=True)
    output = (proc.stdout or proc.stderr).strip()
    if proc.returncode != 0:
        return False, output
    lines = proc.stdout.splitlines()
    ok = all(any(item in line for line in lines) for item in expected)
    return ok, output


def transparent_uid_list(config: dict) -> List[str]:
    raw = config.get("MIHOMO_TRANSPARENT_UIDS", "").strip()
    if raw:
        return [item for item in raw.split(",") if item.strip()]
    legacy_uid = config.get("MIHOMO_TARGET_UID", "").strip()
    return [legacy_uid] if legacy_uid else []


def build_dns_query(name: str, query_id: int) -> bytes:
    header = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    qname = b"".join(struct.pack("!B", len(part)) + part.encode("ascii") for part in name.split(".")) + b"\x00"
    question = qname + struct.pack("!HH", 1, 1)
    return header + question


def parse_name(packet: bytes, offset: int) -> tuple[str, int]:
    labels = []
    jumped = False
    original_offset = offset
    while True:
        length = packet[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            pointer = ((length & 0x3F) << 8) | packet[offset + 1]
            offset += 2
            jumped = True
            pointed_name, _ = parse_name(packet, pointer)
            labels.append(pointed_name)
            break
        offset += 1
        labels.append(packet[offset : offset + length].decode("ascii", errors="replace"))
        offset += length
    return ".".join(filter(None, labels)), (offset if not jumped else original_offset + 2)


def dns_query_udp(server: str, port: int, name: str, timeout: float = 3.0) -> List[str]:
    query_id = random.randint(0, 65535)
    payload = build_dns_query(name, query_id)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload, (server, port))
        data, _ = sock.recvfrom(4096)
    finally:
        sock.close()

    resp_id, flags, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", data[:12])
    if resp_id != query_id or flags & 0x000F:
        return []

    offset = 12
    for _ in range(qdcount):
        _, offset = parse_name(data, offset)
        offset += 4

    answers: List[str] = []
    for _ in range(ancount):
        _, offset = parse_name(data, offset)
        rtype, _, _, rdlength = struct.unpack("!HHIH", data[offset : offset + 10])
        offset += 10
        rdata = data[offset : offset + rdlength]
        offset += rdlength
        if rtype == 1 and rdlength == 4:
            answers.append(socket.inet_ntoa(rdata))
    return answers


def system_dns_lookup(domain: str) -> List[str]:
    infos = socket.getaddrinfo(domain, 80, family=socket.AF_INET, type=socket.SOCK_STREAM)
    return sorted({item[4][0] for item in infos})


def fetch_public_ip(url: str) -> str:
    with urllib.request.urlopen(url, timeout=8) as resp:
        return resp.read().decode("utf-8", errors="replace").strip()


def sidecar_fetch_public_ip(sidecar_bin: Path, url: str) -> str:
    py_code = (
        "import urllib.request;"
        f"print(urllib.request.urlopen('{url}', timeout=8).read().decode().strip())"
    )
    proc = subprocess.run(
        [str(sidecar_bin), "python3", "-c", py_code],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "sidecar command failed")
    return proc.stdout.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 mihomo-sidecar-linux 安装结果")
    parser.add_argument("--config", help="sidecar.env 路径")
    parser.add_argument("--network-check", action="store_true", help="执行可选联网检测，比较普通出口 IP 和 sidecar 出口 IP")
    parser.add_argument("--dns-domain", default="example.com", help="用于 DNS 检测的域名")
    parser.add_argument(
        "--public-ip-url",
        default="https://api.ipify.org",
        help="用于可选联网检测的公网 IP 服务",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(Path(__file__).resolve(), explicit_config=args.config or os.environ.get("MIHOMO_SIDECAR_CONFIG"))
    results: List[CheckResult] = []
    fake_ip_net = ipaddress.ip_network(config["MIHOMO_FAKE_IP_RANGE"], strict=False)

    active, detail = systemctl_is_active(config["MIHOMO_SERVICE_NAME"])
    add_result(results, "PASS" if active else "FAIL", "service_active", detail or "service is active")

    tun_ok = ip_link_exists(config["MIHOMO_TUN_DEV"])
    add_result(results, "PASS" if tun_ok else "FAIL", "tun_exists", config["MIHOMO_TUN_DEV"])

    rule_ok = ip_rule_matches(config["MIHOMO_FWMARK"], config["MIHOMO_ROUTE_TABLE"], config["MIHOMO_RULE_PRIORITY"])
    route_ok = ip_route_matches(config["MIHOMO_ROUTE_TABLE"], config["MIHOMO_TUN_DEV"])
    add_result(results, "PASS" if rule_ok and route_ok else "FAIL", "policy_route", f"fwmark={config['MIHOMO_FWMARK']} table={config['MIHOMO_ROUTE_TABLE']} priority={config['MIHOMO_RULE_PRIORITY']}")

    mangle_ok, mangle_out = iptables_contains(
        "mangle",
        [
            f"-N {config['MIHOMO_CHAIN_MANGLE']}",
            f"-A OUTPUT -m owner --gid-owner {config['MIHOMO_TARGET_GID']} -j {config['MIHOMO_CHAIN_MANGLE']}",
        ],
    )
    nat_ok, nat_out = iptables_contains(
        "nat",
        [
            f"-N {config['MIHOMO_CHAIN_DNS']}",
            f"-A OUTPUT -m owner --gid-owner {config['MIHOMO_TARGET_GID']} -j {config['MIHOMO_CHAIN_DNS']}",
            f"--to-ports {config['MIHOMO_DNS_PORT']}",
        ],
    )
    transparent_uids = transparent_uid_list(config)
    transparent_missing = []
    if config.get("MIHOMO_TRANSPARENT_ENABLED") == "1":
        mangle_lines = mangle_out.splitlines()
        nat_lines = nat_out.splitlines()
        for uid in transparent_uids:
            if not any(f"--uid-owner {uid} -j {config['MIHOMO_CHAIN_MANGLE']}" in line for line in mangle_lines):
                transparent_missing.append(f"mangle uid {uid}")
            if not any(f"--uid-owner {uid} -j {config['MIHOMO_CHAIN_DNS']}" in line for line in nat_lines):
                transparent_missing.append(f"nat uid {uid}")
    iptables_status = "PASS" if mangle_ok and nat_ok and not transparent_missing else "FAIL"
    iptables_detail = "mangle/nat rules present"
    if transparent_missing:
        iptables_detail = "missing transparent rules: " + ", ".join(transparent_missing)
    elif not (mangle_ok and nat_ok):
        iptables_detail = mangle_out or nat_out or "iptables rules missing"
    add_result(results, iptables_status, "iptables_rules", iptables_detail)

    try:
        system_ips = system_dns_lookup(args.dns_domain)
        if not system_ips:
            add_result(results, "WARN", "system_dns_real_ip", f"{args.dns_domain} returned no A record")
        elif any(ipaddress.ip_address(ip) in fake_ip_net for ip in system_ips):
            add_result(results, "FAIL", "system_dns_real_ip", f"system resolver returned fake-ip addresses: {', '.join(system_ips)}")
        else:
            add_result(results, "PASS", "system_dns_real_ip", ", ".join(system_ips))
    except Exception as exc:
        add_result(results, "WARN", "system_dns_real_ip", f"lookup failed: {exc}")

    try:
        sidecar_dns_ips = dns_query_udp(config["MIHOMO_API_HOST"], int(config["MIHOMO_DNS_PORT"]), args.dns_domain)
        if not sidecar_dns_ips:
            add_result(results, "FAIL", "sidecar_dns_fake_ip", "mihomo dns returned no A record")
        elif any(ipaddress.ip_address(ip) in fake_ip_net for ip in sidecar_dns_ips):
            add_result(results, "PASS", "sidecar_dns_fake_ip", ", ".join(sidecar_dns_ips))
        else:
            add_result(results, "FAIL", "sidecar_dns_fake_ip", f"mihomo dns returned non fake-ip addresses: {', '.join(sidecar_dns_ips)}")
    except Exception as exc:
        add_result(results, "FAIL", "sidecar_dns_fake_ip", f"dns query failed: {exc}")

    if args.network_check:
        sidecar_bin = Path(config["MIHOMO_HOME"]).expanduser() / "bin" / "sidecar"
        if not sidecar_bin.is_file():
            sidecar_bin = Path(__file__).resolve().parent.parent / "bin" / "sidecar"
        try:
            direct_ip = fetch_public_ip(args.public_ip_url)
            sidecar_ip = sidecar_fetch_public_ip(sidecar_bin, args.public_ip_url)
            if direct_ip and sidecar_ip and direct_ip != sidecar_ip:
                add_result(results, "PASS", "egress_ip_difference", f"direct={direct_ip} sidecar={sidecar_ip}")
            elif direct_ip and sidecar_ip:
                add_result(results, "WARN", "egress_ip_difference", f"direct={direct_ip} sidecar={sidecar_ip}")
            else:
                add_result(results, "WARN", "egress_ip_difference", "empty response from public IP service")
        except Exception as exc:
            add_result(results, "WARN", "egress_ip_difference", f"network check failed: {exc}")
    else:
        add_result(results, "WARN", "egress_ip_difference", "skipped; rerun with --network-check")

    pass_count = sum(1 for item in results if item.status == "PASS")
    warn_count = sum(1 for item in results if item.status == "WARN")
    fail_count = sum(1 for item in results if item.status == "FAIL")

    for item in results:
        print(f"[{item.status}] {item.name}: {item.detail}")
    print()
    print(f"SUMMARY PASS={pass_count} WARN={warn_count} FAIL={fail_count}")
    raise SystemExit(1 if fail_count else 0)


if __name__ == "__main__":
    main()
