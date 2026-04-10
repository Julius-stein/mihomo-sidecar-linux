# Verification

本文档描述安装后如何用尽量不破坏系统状态的方式验证 `mihomo-sidecar-linux`。

推荐先执行只读验证：

```bash
sudo sidecar-verify
```

如果需要额外比较普通出口 IP 和 sidecar 出口 IP，再执行：

```bash
sudo sidecar-verify --network-check
```

## 检查项

`sidecar-verify` 当前会输出这 8 类结果：

1. `service_active`
2. `tun_exists`
3. `policy_route`
4. `iptables_rules`
5. `system_dns_real_ip`
6. `sidecar_dns_fake_ip`
7. `egress_ip_difference`
8. `SUMMARY PASS=... WARN=... FAIL=...`

其中第 7 项默认跳过，只有加 `--network-check` 时才执行。

## 结果解释

- `PASS`：该项通过。
- `WARN`：该项没有完全确认，或者被显式跳过。
- `FAIL`：该项明确不符合预期。

脚本最后会输出汇总行，并在存在 `FAIL` 时返回非零退出码。

## 每一项具体在检查什么

### 1. Mihomo service 是否 active

通过 `systemctl is-active` 检查 `MIHOMO_SERVICE_NAME`。

### 2. TUN 设备是否存在

通过 `ip link show <MIHOMO_TUN_DEV>` 检查。

### 3. policy route 是否存在

同时检查：

- `ip rule` 中是否存在 `fwmark + lookup table + priority`
- `ip route show table <table>` 中是否存在 `default dev <tun>`

### 4. iptables mangle / nat 规则是否存在

同时检查：

- 自定义 mangle chain 是否存在
- `OUTPUT` 中是否存在 GID 跳转
- 自定义 nat chain 是否存在
- DNS REDIRECT 是否仍指向 `MIHOMO_DNS_PORT`

如果启用了透明模式，建议再手工检查 UID 规则是否出现。

### 5. 普通 DNS 是否仍是系统 DNS

脚本会用系统 resolver 查询一个测试域名，并检查返回结果是否落在 `fake-ip-range` 内。

预期：

- 普通 resolver 返回真实公网 IP
- 不应返回 Mihomo fake-IP

### 6. sidecar DNS 是否返回 fake-IP

脚本会直接向 Mihomo DNS 监听地址发起 UDP 查询，检查返回结果是否落在配置的 `fake-ip-range` 内。

预期：

- sidecar DNS 返回 fake-IP

### 7. 普通出口 IP 与 sidecar 出口 IP 是否不同

该项默认不执行。

启用 `--network-check` 后，脚本会：

- 直接访问公网 IP 服务一次
- 再通过 `sidecar` 包装访问同一个服务一次

预期：

- 大多数代理场景下，两次结果应不同

如果两者相同，不一定代表故障，也可能是：

- 你的节点就是本机出口
- 目标网络策略没有做出口区分

因此这项更适合作为 `WARN/PASS` 参考，而不是唯一判据。

## 参数

```bash
sidecar-verify -h
```

支持参数：

- `--network-check`
- `--dns-domain DOMAIN`
- `--public-ip-url URL`

## 建议执行顺序

推荐按下面顺序验证：

1. `sudo sidecar-verify`
2. `sidecar-node --list`
3. `sidecar curl -I https://example.com`
4. `sudo sidecar-verify --network-check`

## 多实例场景的额外建议

如果同机有多个 Mihomo 实例，验证时请特别注意：

- `MIHOMO_TUN_DEV`
- `MIHOMO_FWMARK`
- `MIHOMO_ROUTE_TABLE`
- `MIHOMO_RULE_PRIORITY`
- `MIHOMO_CHAIN_MANGLE`
- `MIHOMO_CHAIN_DNS`
- `MIHOMO_FAKE_IP_RANGE`
- `MIHOMO_TUN_INET4`

这些值应该全部唯一；否则即便服务表面启动成功，仍可能出现 fake-IP 冲突、规则串扰或透明代理异常。
