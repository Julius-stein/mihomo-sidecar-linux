#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from sidecar_config import load_config

DEFAULT_NAMESERVERS = ["1.1.1.1", "8.8.8.8"]


def fetch_text(source: str, timeout: int = 20) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        req = urllib.request.Request(
            source,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return data.decode("utf-8", errors="replace")
    return Path(source).read_text(encoding="utf-8", errors="replace")


def maybe_b64_decode(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped

    # 已经是 trojan 链接/YAML/JSON 的情况，直接返回
    if (
        "trojan://" in stripped
        or stripped.startswith("proxies:")
        or stripped.startswith("{")
        or stripped.startswith("mixed-port:")
        or stripped.startswith("port:")
    ):
        return stripped

    # 粗略判断是否像 base64
    compact = "".join(stripped.split())
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        return stripped

    padded = compact + "=" * (-len(compact) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False)
        text2 = decoded.decode("utf-8", errors="replace")
        if "trojan://" in text2 or "proxies:" in text2 or "mixed-port:" in text2:
            return text2
    except Exception:
        pass
    return stripped


def parse_trojan_url(line: str) -> Optional[Dict]:
    line = line.strip()
    if not line or not line.startswith("trojan://"):
        return None

    u = urllib.parse.urlsplit(line)
    if u.scheme != "trojan":
        return None

    password = urllib.parse.unquote(u.username or "")
    server = u.hostname or ""
    port = u.port or 443
    query = urllib.parse.parse_qs(u.query)
    frag = urllib.parse.unquote(u.fragment or "")

    sni = ""
    if "sni" in query and query["sni"]:
        sni = query["sni"][0]
    elif "peer" in query and query["peer"]:
        sni = query["peer"][0]

    allow_insecure = query.get("allowInsecure", ["0"])[0]
    skip_cert_verify = allow_insecure == "1"

    name = frag if frag else f"{server}:{port}"

    return {
        "name": name,
        "type": "trojan",
        "server": server,
        "port": int(port),
        "password": password,
        "sni": sni,
        "skip-cert-verify": skip_cert_verify,
        "udp": True,
    }


def extract_trojan_nodes(text: str) -> List[Dict]:
    nodes = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("trojan://"):
            continue
        node = parse_trojan_url(line)
        if node:
            nodes.append(node)
    return nodes


def dedupe_nodes(nodes: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for n in nodes:
        key = (
            n["server"],
            n["port"],
            n["password"],
            n.get("sni", ""),
            n["name"],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def yaml_quote(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def build_config(
    nodes: List[Dict],
    secret: str,
    mixed_port: int,
    api_host: str,
    api_port: int,
    dns_port: int,
    tun_device: str,
    fake_ip_range: str,
    inet4: str,
    proxy_group: str,
    nameservers: List[str],
) -> str:
    lines = []
    lines.append(f"mixed-port: {mixed_port}")
    lines.append("allow-lan: false")
    lines.append("mode: rule")
    lines.append("log-level: info")
    lines.append("ipv6: true")
    lines.append("")
    lines.append(f"external-controller: {api_host}:{api_port}")
    lines.append(f"secret: {yaml_quote(secret)}")
    lines.append("")
    lines.append("dns:")
    lines.append("  enable: true")
    lines.append(f"  listen: 127.0.0.1:{dns_port}")
    lines.append("  enhanced-mode: fake-ip")
    lines.append(f"  fake-ip-range: {fake_ip_range}")
    lines.append("  ipv6: true")
    lines.append("  nameserver:")
    for nameserver in nameservers:
        lines.append(f"    - {nameserver}")
    lines.append("")
    lines.append("tun:")
    lines.append("  enable: true")
    lines.append("  stack: mixed")
    lines.append(f"  device: {tun_device}")
    lines.append("  inet4-address:")
    lines.append(f"    - {inet4}")
    lines.append("  auto-route: false")
    lines.append("  auto-detect-interface: false")
    lines.append("  dns-hijack:")
    lines.append("    - any:53")
    lines.append("  strict-route: false")
    lines.append("")
    lines.append("proxies:")
    for n in nodes:
        lines.append(f"  - name: {yaml_quote(n['name'])}")
        lines.append("    type: trojan")
        lines.append(f"    server: {n['server']}")
        lines.append(f"    port: {n['port']}")
        lines.append(f"    password: {yaml_quote(n['password'])}")
        if n.get("sni"):
            lines.append(f"    sni: {n['sni']}")
        lines.append(
            f"    skip-cert-verify: {'true' if n.get('skip-cert-verify') else 'false'}"
        )
        lines.append(f"    udp: {'true' if n.get('udp', True) else 'false'}")
    lines.append("")
    lines.append("proxy-groups:")
    lines.append(f"  - name: {proxy_group}")
    lines.append("    type: select")
    lines.append("    proxies:")
    for n in nodes:
        lines.append(f"      - {yaml_quote(n['name'])}")
    lines.append("")
    lines.append("rules:")
    lines.append(f"  - MATCH,{proxy_group}")
    lines.append("")
    lines.append("profile:")
    lines.append("  store-selected: true")
    lines.append("  store-fake-ip: true")
    return "\n".join(lines)


def choose_nodes(
    nodes: List[Dict],
    select_index: Optional[int],
    select_keyword: Optional[str],
    include_all: bool,
) -> List[Dict]:
    if include_all:
        return nodes

    if select_index is not None:
        if select_index < 0 or select_index >= len(nodes):
            raise ValueError(f"节点编号越界: {select_index}")
        return [nodes[select_index]]

    if select_keyword:
        key = select_keyword.lower()
        matched = [n for n in nodes if key in n["name"].lower()]
        if not matched:
            raise ValueError(f"没有找到关键字匹配的节点: {select_keyword}")
        return [matched[0]]

    if not nodes:
        raise ValueError("没有可用节点")
    return [nodes[0]]


def print_nodes(nodes: List[Dict]) -> None:
    for i, n in enumerate(nodes):
        print(f"[{i}] {n['name']}  |  {n['server']}:{n['port']}  |  sni={n.get('sni','')}")


def main():
    config_defaults = load_config(Path(__file__).resolve(), explicit_config=os.environ.get("MIHOMO_SIDECAR_CONFIG"))
    ap = argparse.ArgumentParser(
        description="从 trojan/base64 订阅生成 mihomo config.yaml，并支持列出/选择节点"
    )
    ap.add_argument("--source", required=True, help="订阅 URL 或本地文件路径")
    ap.add_argument("--list", action="store_true", help="只列出节点，不生成配置")
    ap.add_argument("--select-index", type=int, help="按编号选择单个节点")
    ap.add_argument("--select-keyword", help="按关键字选择单个节点")
    ap.add_argument(
        "--all-nodes",
        action="store_true",
        help="把全部节点写入 proxies，并在 PROXY 组里手动选择",
    )
    ap.add_argument(
        "--output",
        default=str(Path(config_defaults["MIHOMO_CONFIG_YAML"]).expanduser()),
        help="输出 config.yaml 路径",
    )
    ap.add_argument(
        "--secret",
        default=os.environ.get("MIHOMO_API_SECRET"),
        help="external-controller 的 secret，默认从环境变量 MIHOMO_API_SECRET 读取",
    )
    ap.add_argument("--mixed-port", type=int, default=int(config_defaults["MIHOMO_MIXED_PORT"]))
    ap.add_argument("--api-host", default=config_defaults["MIHOMO_API_HOST"])
    ap.add_argument("--api-port", type=int, default=int(config_defaults["MIHOMO_API_PORT"]))
    ap.add_argument("--dns-port", type=int, default=int(config_defaults["MIHOMO_DNS_PORT"]))
    ap.add_argument("--tun-device", default=config_defaults["MIHOMO_TUN_DEV"])
    ap.add_argument("--fake-ip-range", default=config_defaults["MIHOMO_FAKE_IP_RANGE"])
    ap.add_argument("--inet4", default=config_defaults["MIHOMO_TUN_INET4"])
    ap.add_argument("--group-name", default=config_defaults["MIHOMO_PROXY_GROUP"])
    ap.add_argument(
        "--nameserver",
        action="append",
        default=[],
        help="可重复指定上游 DNS；默认使用 1.1.1.1 和 8.8.8.8",
    )
    ap.add_argument(
        "--save-raw-dir",
        default=str(Path(config_defaults["MIHOMO_HOME"]).expanduser() / "sub"),
        help="保存原始订阅和解码结果的目录",
    )
    ap.add_argument(
        "--controller-secret-output",
        help="把实际使用的 controller secret 单独写入文件",
    )
    args = ap.parse_args()

    if not args.secret:
        print("缺少 controller secret，请使用 --secret 或设置环境变量 MIHOMO_API_SECRET。", file=sys.stderr)
        sys.exit(2)

    save_dir = Path(args.save_raw_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    raw = fetch_text(args.source)
    (save_dir / "sub.raw").write_text(raw, encoding="utf-8")

    decoded = maybe_b64_decode(raw)
    (save_dir / "sub.decoded").write_text(decoded, encoding="utf-8")

    nodes = dedupe_nodes(extract_trojan_nodes(decoded))
    if not nodes:
        print("没有解析到 trojan 节点。请检查订阅内容。", file=sys.stderr)
        sys.exit(2)

    if args.list:
        print_nodes(nodes)
        return

    chosen = choose_nodes(
        nodes,
        select_index=args.select_index,
        select_keyword=args.select_keyword,
        include_all=args.all_nodes,
    )

    config = build_config(
        nodes=chosen if not args.all_nodes else nodes,
        secret=args.secret,
        mixed_port=args.mixed_port,
        api_host=args.api_host,
        api_port=args.api_port,
        dns_port=args.dns_port,
        tun_device=args.tun_device,
        fake_ip_range=args.fake_ip_range,
        inet4=args.inet4,
        proxy_group=args.group_name,
        nameservers=args.nameserver or DEFAULT_NAMESERVERS,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(config, encoding="utf-8")
    if args.controller_secret_output:
        secret_out = Path(args.controller_secret_output)
        secret_out.parent.mkdir(parents=True, exist_ok=True)
        secret_out.write_text(args.secret + "\n", encoding="utf-8")

    print(f"已写入: {out}")
    print(f"节点数: {len(nodes)}")
    if args.all_nodes:
        print("已写入全部节点，可在 PROXY 组中选择。")
    else:
        print(f"当前选中: {chosen[0]['name']}")


if __name__ == "__main__":
    main()
