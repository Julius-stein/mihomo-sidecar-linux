# Troubleshooting

本文档围绕当前仓库已经存在的实现编写，默认你正在使用：

- `script/setup-rules.sh`
- `script/cleanup-rules.sh`
- `script/select_node.py`
- `mihomo-sidecar.service`

## 快速诊断清单

先跑这一组命令，通常就能缩小问题范围：

```bash
sudo systemctl status mihomo-sidecar.service --no-pager
sudo journalctl -u mihomo-sidecar.service -n 100 --no-pager
ip link show Meta-sidecar
ip rule show
ip route show table 101
sudo iptables -t mangle -S
sudo iptables -t nat -S
```

如果节点切换异常，再补：

```bash
echo "$MIHOMO_API_SECRET"
curl -H "Authorization: Bearer $MIHOMO_API_SECRET" \
  http://127.0.0.1:9091/proxies
python script/select_node.py
```

## 常见问题

## 1. `Meta-sidecar not found after 30s`

含义：

- `script/setup-rules.sh` 在 30 秒内没有看到名为 `Meta-sidecar` 的 TUN。

排查方向：

- Mihomo 是否已成功启动
- Mihomo 配置里 `tun.enable` 是否为 `true`
- `tun.device` 是否仍然是 `Meta-sidecar`
- systemd unit 的 `ExecStart` 是否指向了正确的运行目录

建议命令：

```bash
sudo journalctl -u mihomo-sidecar.service -n 200 --no-pager
grep -n "device:" /path/to/config.yaml
ip link show Meta-sidecar
```

## 2. sidecar 命令执行了，但流量没有走代理

常见原因：

- 进程实际 effective GID 不是 `1026`
- `mangle OUTPUT` 没有匹配到 `--gid-owner 1026`
- `fwmark` / route table / priority 规则没装上

建议命令：

```bash
id
getent group sidecar
ip rule show | grep 1001
ip route show table 101
sudo iptables -t mangle -S MIHOMO_SIDECAR
```

如果你修改过 GID，但没有同步改两个脚本，规则和 shell 包装就会失配。

## 3. DNS 解析异常或解析很慢

当前实现会把 sidecar GID 的 DNS 请求重定向到 `127.0.0.1:1054`。

排查方向：

- Mihomo `dns.listen` 是否为 `127.0.0.1:1054`
- `MIHOMO_DNS_SIDECAR` 链是否存在
- fake-ip-range 是否与本机或其他实例冲突

建议命令：

```bash
sudo iptables -t nat -S MIHOMO_DNS_SIDECAR
ss -lntup | grep 1054
grep -n "fake-ip-range" /path/to/config.yaml
```

## 4. `script/select_node.py` 提示缺少 `MIHOMO_API_SECRET`

含义：

- 当前 shell 环境没有导出 `MIHOMO_API_SECRET`。

修复方式：

- 在 shell 配置里导出环境变量
- 或临时执行：

```bash
export MIHOMO_API_SECRET="<REPLACE_WITH_REAL_SECRET>"
python script/select_node.py
```

不要把真实 secret 写进示例文件或提交到仓库。

## 5. `select_node.py` 提示没有找到 `PROXY` 组

含义：

- Mihomo 配置里没有 `proxy-groups: - name: PROXY`

当前脚本是硬编码读取 `PROXY` 的，所以需要让配置与脚本保持一致。

建议命令：

```bash
grep -n "name: PROXY" /path/to/config.yaml
curl -H "Authorization: Bearer $MIHOMO_API_SECRET" \
  http://127.0.0.1:9091/proxies
```

## 6. service 能启动，但停止后规则没清干净

排查方向：

- `setup-rules.sh` 和 `cleanup-rules.sh` 的硬编码参数是否一致
- 是否手工改过 `TARGET_GID`、`FWMARK`、`TABLE`、`PRIORITY`
- 是否存在多份同名链或多实例共享同一组资源

建议命令：

```bash
diff -u script/setup-rules.sh script/cleanup-rules.sh
ip rule show
sudo iptables -t mangle -S
sudo iptables -t nat -S
```

## 7. 多实例部署后，偶发出现访问异常、个别域名行为诡异

高概率是地址空间冲突，而不是节点本身坏了。

重点检查：

- `dns.fake-ip-range`
- `tun.inet4-address`
- `fwmark`
- route table
- rule priority
- controller / DNS 端口

经验上，下面两项最容易被忽略：

- fake-ip-range 重叠
- TUN 子网重叠

## 8. `iptables` 命令存在，但规则行为和预期不一致

当前项目还没有抽象 `iptables-nft` / legacy 差异。

排查方向：

- 宿主机使用的是哪一套 `iptables`
- 机器上是否已有其他系统级防火墙管理工具
- 共享服务器管理员是否已有统一网络策略

建议命令：

```bash
iptables --version
sudo iptables -t mangle -S
sudo iptables -t nat -S
```

## 定位顺序建议

遇到问题时，建议按这个顺序排：

1. 先看 systemd 是否启动成功。
2. 再看 TUN 是否出现。
3. 再看 `ip rule` / `ip route` 是否存在。
4. 再看 `iptables` 两张表里的链和跳转。
5. 最后看 Mihomo controller、DNS 和节点选择。

## 提交 issue 时建议附带的信息

为了提高排障效率，建议附带：

- Linux 发行版与内核版本
- `iptables --version`
- `systemctl status` 摘要
- `journalctl -u mihomo-sidecar.service -n 100`
- `ip link show`
- `ip rule show`
- `ip route show table 101`
- `iptables -t mangle -S`
- `iptables -t nat -S`

提交前请务必去掉：

- 订阅地址
- controller secret
- 节点密码
- 任何真实 token
