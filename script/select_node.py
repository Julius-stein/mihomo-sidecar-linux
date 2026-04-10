#!/usr/bin/env python3
import json
import os
import sys
import urllib
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from sidecar_config import load_config, read_mihomo_secret

CONFIG = load_config(Path(__file__).resolve(), explicit_config=os.environ.get("MIHOMO_SIDECAR_CONFIG"))
API_SECRET = read_mihomo_secret(CONFIG)
API_BASE = f"http://{CONFIG['MIHOMO_API_HOST']}:{CONFIG['MIHOMO_API_PORT']}"
PROXY_GROUP = CONFIG["MIHOMO_PROXY_GROUP"]


def api_request(path: str, method: str = "GET", data: dict | None = None):
    if not API_SECRET:
        print("缺少环境变量 MIHOMO_API_SECRET", file=sys.stderr)
        sys.exit(2)

    body = None
    headers = {
        "Authorization": f"Bearer {API_SECRET}",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        API_BASE + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if raw:
                return json.loads(raw)
            return None
    except urllib.error.HTTPError as e:
        print(f"HTTP 错误: {e.code} {e.reason}", file=sys.stderr)
        try:
            print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        except Exception:
            pass
        if e.code == 401:
            print(f"controller: {API_BASE}", file=sys.stderr)
            print(f"secret file: {CONFIG['MIHOMO_SECRET_FILE']}", file=sys.stderr)
            print(f"config file: {CONFIG['MIHOMO_CONFIG_YAML']}", file=sys.stderr)
            print("这通常表示 controller secret 不一致，或命令和 service 读取的不是同一套 workdir。", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ConnectionRefusedError):
            print(f"无法连接 Mihomo controller: {API_BASE}", file=sys.stderr)
            print("这通常表示 Mihomo service 还没有启动。", file=sys.stderr)
            print(f"请先执行: sudo systemctl enable --now {CONFIG['MIHOMO_SERVICE_NAME']}", file=sys.stderr)
            sys.exit(1)
        print(f"请求失败: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"请求失败: {e}", file=sys.stderr)
        sys.exit(1)


def get_proxy_group_info():
    data = api_request("/proxies")
    proxies = data.get("proxies", {})
    group = proxies.get(PROXY_GROUP)
    if not group:
        print(f"没有找到 {PROXY_GROUP} 组。请确认 config.yaml 里有 proxy-groups: {PROXY_GROUP}", file=sys.stderr)
        sys.exit(1)
    return group


def list_nodes(group: dict, keyword: str | None = None, *, emit: bool = True):
    all_names = group.get("all", [])
    now = group.get("now", "")
    if keyword:
        all_names = [name for name in all_names if keyword.lower() in name.lower()]
    if emit:
        print("可选节点：")
        for i, name in enumerate(all_names):
            mark = "  *当前" if name == now else ""
            print(f"[{i:02d}] {name}{mark}")
    return all_names, now


def switch_node(name: str):
    api_request(f"/proxies/{PROXY_GROUP}", method="PUT", data={"name": name})
    print(f"已切换到: {name}")


def main():
    args = sys.argv[1:]
    if args and args[0] in {"-h", "--help"}:
        print("usage: select_node.py [--list] [--current] [--filter KEYWORD] [--use NAME] [--index N]")
        return
    keyword = None
    selected_name = None
    selected_index = None
    show_current = False
    list_only = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--list":
            list_only = True
        elif arg == "--current":
            show_current = True
        elif arg == "--filter":
            i += 1
            if i >= len(args):
                print("--filter 需要关键字参数。", file=sys.stderr)
                sys.exit(2)
            keyword = args[i]
        elif arg == "--use":
            i += 1
            if i >= len(args):
                print("--use 需要节点名参数。", file=sys.stderr)
                sys.exit(2)
            selected_name = args[i]
        elif arg == "--index":
            i += 1
            if i >= len(args):
                print("--index 需要编号参数。", file=sys.stderr)
                sys.exit(2)
            try:
                selected_index = int(args[i])
            except ValueError:
                print("--index 需要整数编号。", file=sys.stderr)
                sys.exit(2)
        else:
            print(f"未知参数: {arg}", file=sys.stderr)
            sys.exit(2)
        i += 1

    group = get_proxy_group_info()
    emit_list = not show_current
    all_names, now = list_nodes(group, keyword=keyword, emit=emit_list)

    if not all_names:
        print(f"{PROXY_GROUP} 组里没有节点。", file=sys.stderr)
        sys.exit(1)

    if show_current:
        print(now)
        return

    if selected_name is not None:
        if selected_name not in all_names:
            print(f"没有找到节点: {selected_name}", file=sys.stderr)
            sys.exit(1)
        if selected_name == now:
            print(f"当前已经是: {selected_name}")
            return
        switch_node(selected_name)
        return

    if selected_index is not None:
        if selected_index < 0 or selected_index >= len(all_names):
            print("编号越界。", file=sys.stderr)
            sys.exit(1)
        selected = all_names[selected_index]
        if selected == now:
            print(f"当前已经是: {selected}")
            return
        switch_node(selected)
        return

    if list_only:
        return

    print()
    choice = input("输入要切换的节点编号（直接回车退出）: ").strip()
    if not choice:
        print("未切换。")
        return

    if not choice.isdigit():
        print("请输入数字编号。", file=sys.stderr)
        sys.exit(1)

    idx = int(choice)
    if idx < 0 or idx >= len(all_names):
        print("编号越界。", file=sys.stderr)
        sys.exit(1)

    selected = all_names[idx]
    if selected == now:
        print(f"当前已经是: {selected}")
        return

    switch_node(selected)


if __name__ == "__main__":
    main()
