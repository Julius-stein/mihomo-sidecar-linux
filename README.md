# mihomo-sidecar-linux

一个面向多用户 Linux 共享服务器的 Mihomo sidecar 工具。

这个项目的目标不是“把整台共享服务器切成全局代理机”，而是提供两种更克制、更适合多人环境的能力：

- `sidecar <cmd...>`：让单个命令走代理
- `sidecar-on` / `sidecar-off`：让单个用户进入透明代理模式

当前仓库已经具备统一配置、资源自动探测、安装脚本、节点选择、验证脚本和多 UID 透明代理状态管理。推荐的使用方式就是你说的那种：

1. `git clone`
2. 准备 `config.yaml`
3. `./install.sh`
4. 把需要使用进程级代理的用户加入 `sidecar` 组
5. 普通场景优先使用 `sidecar <cmd>`
6. 需要整用户透明代理时，再用 `sidecar-on`

## 项目目标

这个项目要解决的是共享服务器上最典型的代理矛盾：

- 代理要可用
- 影响范围要尽量小
- 多个用户要能共存
- 服务要能被 systemd 管理
- 安装后要能知道自己到底有没有成功

因此项目设计上优先保证：

- 进程级 sidecar 模式稳定可用
- 多实例资源不互相踩踏
- 安装和验证路径尽量标准化

## 为什么不是直接全局 TUN

在个人机器上，全局 TUN 往往简单；在共享服务器上，全局 TUN 往往是问题来源。

原因很直接：

- 会改变整机或整用户默认路由
- 会把 DNS / fake-ip 语义扩散到更大范围
- 容易影响其他人的任务、守护进程和定时任务
- 同机多实例时，`fwmark`、table、priority、端口、TUN、fake-ip、TUN 子网都可能冲突

所以本项目优先采用 sidecar 路径，而不是默认改整机网络。

## 架构概览

当前实现仍然尽量少动 Mihomo 的核心运行逻辑，底层链路是：

1. Mihomo 以 systemd 服务运行
2. Mihomo 创建 TUN，提供 controller 和 DNS
3. `iptables mangle` 匹配目标流量并打 `fwmark`
4. `ip rule` + `ip route` 让被标记流量进入 Mihomo TUN
5. `iptables nat` 把目标 DNS 请求转到 Mihomo DNS

区分两种使用模式：

- GID sidecar 模式：
  - 通过 `--gid-owner`
  - 给 `sidecar` 组里的命令做进程级代理
- UID 透明代理模式：
  - 通过 `--uid-owner`
  - 现在已经支持多个 UID 同时开启，不再是单 UID 全局开关

统一配置与运行态分层：

- 静态配置：`sidecar.env`
- 自动探测后的运行态：`state/runtime.env`

## git clone 后怎么安装

可以，目标就是让你在 Linux 上直接 `git clone` 下来后安装。

最小流程如下。

### 1. 克隆仓库

```bash
git clone <YOUR_REPO_URL>
cd mihomo-sidecar-linux
```

### 2. 准备 Mihomo 配置

参考 [examples/config.template.yaml](examples/config.template.yaml) 生成你的 `config.yaml`。

你至少要保证下面这些概念存在：

- `external-controller`
- `secret`
- `dns.listen`
- `dns.fake-ip-range`
- `tun.device`
- `tun.inet4-address`
- `proxy-groups: PROXY`

如果你准备让安装器自动探测资源并写入运行态参数，建议先把 `config.yaml` 也放进最终运行目录，便于一起核对。

### 3. 按需准备静态配置

默认情况下，不改任何文件也能直接运行安装器，因为脚本内置默认值。

如果你想显式指定路径和组信息，可以先复制模板：

```bash
cp config/sidecar.env.example config/sidecar.env
```

常见需要调整的静态项：

- `MIHOMO_HOME`
- `MIHOMO_BIN`
- `MIHOMO_TARGET_GID`
- `MIHOMO_SIDECAR_GROUP`
- `MIHOMO_DISCOVERY_DIRS`

### 4. 安装

```bash
sudo ./install.sh --mihomo-home /opt/mihomo-sidecar
```

如果你还想把 systemd unit 直接拷到系统目录：

```bash
sudo ./install.sh \
  --mihomo-home /opt/mihomo-sidecar \
  --systemd-unit-dir /etc/systemd/system
```

安装器会做这些事：

- 安装脚本和 CLI
- 生成 `/opt/mihomo-sidecar/sidecar.env`
- 自动探测共享资源并生成 `/opt/mihomo-sidecar/state/runtime.env`
- 渲染 systemd unit

### 5. 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-sidecar.service
```

### 6. 给需要用进程级代理的用户加组

```bash
sudo groupadd -g 1026 sidecar
sudo usermod -aG sidecar alice
sudo usermod -aG sidecar bob
```

如果你改了 `MIHOMO_TARGET_GID` 或 `MIHOMO_SIDECAR_GROUP`，这里也要对应调整。

## 进程级 sidecar 的推荐用法

这是推荐主路径。

只要用户在 `sidecar` 组里，就可以直接运行：

```bash
sidecar curl -I https://example.com
sidecar git clone https://github.com/example/repo.git
sidecar pip install -r requirements.txt
```

这个模式最适合共享服务器，因为：

- 只影响这一个命令
- 用户之间不会互相抢透明代理状态
- 出问题时更容易回退

## 多人透明代理模式

`sidecar-on` 现在已经不再是“只能有一个 UID”的实现，而是“多个 UID 可同时开启”的模型。

现在的语义是：

- `sidecar-on`
  - 默认把当前 UID 加入透明代理 UID 集合
- `sidecar-on 1002`
  - 把 UID 1002 加入透明代理 UID 集合
- `sidecar-off`
  - 默认移除当前 UID
- `sidecar-off 1002`
  - 移除 UID 1002
- `sidecar-off --all`
  - 清空所有透明代理 UID

也就是说，多人同时开 `sidecar-on` 时，不会再像旧实现那样互相覆盖单个 `MIHOMO_TARGET_UID`。

当前状态是持久化到运行态配置里的，内部带锁串行化更新，避免并发写文件互相冲掉。

不过我仍然建议：

- 默认把 `sidecar` 进程级模式当主路径
- 只有确实需要“该用户所有命令都透明走代理”时再用 `sidecar-on`

## 资源自动探测与冲突规避

这是当前项目最重要的开源化能力之一。

安装器会调用探测脚本，为当前实例尽量自动选择不冲突的值。

当前已覆盖：

- TUN 名称
- `fwmark`
- route table
- rule priority
- API 端口
- DNS 端口
- mixed-port
- mangle chain 名
- nat chain 名
- `fake-ip-range`
- TUN `inet4-address`

对应实现见：

- [script/detect_runtime.py](script/detect_runtime.py)

这正是为了解决你提到的那类问题：同机已有另一套 Mihomo 在使用默认 fake-ip 或默认 TUN 子网时，新实例不能再盲目复用默认值。

### 一个现实边界

自动探测不是“神谕”。

它能探测两类东西：

- 当前内核里可见的 live 资源
- 你显式让它扫描到的其他实例配置

因此，多实例场景里建议把其他运行目录加入：

- `MIHOMO_DISCOVERY_DIRS`

如果另一套实例的配置完全不可见，而冲突信息又不在内核可见资源里，那就仍然需要人工复核。

## 核心参数

最重要的配置项都在：

- [config/sidecar.env.example](config/sidecar.env.example)

其中最关键的是：

- `MIHOMO_HOME`
- `MIHOMO_BIN`
- `MIHOMO_SIDECAR_GROUP`
- `MIHOMO_TARGET_GID`
- `MIHOMO_TUN_DEV`
- `MIHOMO_FWMARK`
- `MIHOMO_ROUTE_TABLE`
- `MIHOMO_RULE_PRIORITY`
- `MIHOMO_API_PORT`
- `MIHOMO_DNS_PORT`
- `MIHOMO_CHAIN_MANGLE`
- `MIHOMO_CHAIN_DNS`
- `MIHOMO_FAKE_IP_RANGE`
- `MIHOMO_TUN_INET4`
- `MIHOMO_DISCOVERY_DIRS`

透明代理相关：

- `MIHOMO_TRANSPARENT_ENABLED`
- `MIHOMO_TRANSPARENT_UIDS`

## 验证

安装完后，先不要猜，先验证。

推荐先跑：

```bash
sudo /opt/mihomo-sidecar/bin/sidecar-verify
```

如果你还想比较普通出口 IP 和 sidecar 出口 IP：

```bash
sudo /opt/mihomo-sidecar/bin/sidecar-verify --network-check
```

它会检查：

1. Mihomo service 是否 active
2. TUN 设备是否存在
3. policy route 是否存在
4. iptables mangle / nat 规则是否存在
5. 普通 DNS 是否仍返回真实 IP
6. sidecar DNS 是否返回 fake-IP
7. 普通出口 IP 与 sidecar 出口 IP 是否不同
8. PASS / WARN / FAIL 汇总

详细说明见 [docs/verification.md](docs/verification.md)。

## 节点选择

当前节点选择命令：

```bash
sidecar-node --list
sidecar-node --current
sidecar-node --filter HK --list
sidecar-node --use "Example-Node"
sidecar-node --index 3
```

它默认操作 `PROXY` 组，controller 鉴权 secret 默认从环境变量或 `config.yaml` 读取。

## 已知限制

当前已经能作为“可安装、可验证、可多人使用进程级 sidecar”的工具继续推进，但还有边界：

- 透明代理仍然共享同一套 mangle/nat chain，只是 UID 集合已经支持多人并存。
- 透明代理的回环规避和更细粒度隔离还可以继续增强。
- 自动探测依赖于可见资源与可扫描配置，不是绝对完备的全局发现。
- 当前规则仍以 `iptables` 为主，没有抽象 `nftables` 差异。

## 安全说明

最重要的安全建议只有几条，但每条都别省：

- `external-controller` 只监听 `127.0.0.1`
- 不要把真实 `secret`、订阅、节点密码提交进 Git
- 只把需要使用进程级代理的用户加入 `sidecar` 组
- 多实例部署时，确保 TUN / mark / table / priority / ports / chain / fake-ip / TUN 子网都唯一

更多细节见 [docs/security.md](docs/security.md)。

## 多实例 fake-ip / TUN 冲突经验

同机双实例时，最容易被忽视的不是端口，而是地址空间。

要点很简单：

- `fake-ip-range` 必须唯一
- `tun.inet4-address` 必须唯一
- 不能只改端口，不改地址空间

如果这两项复用，现象通常不是“服务完全起不来”，而是：

- 某些域名解析结果诡异
- 某些透明代理连接偶发失败
- 日志里看起来像节点问题，实际上是本机资源冲突

这个项目现在已经把这部分纳入自动探测，但在共享环境里，仍建议你把最终分配结果记账。
