# mihomo-sidecar-linux

一个面向多用户 Linux 共享服务器的 Mihomo sidecar 工具。

法律与合规提示：
本项目仅用于 Linux 网络、策略路由与代理隔离的学习交流、研究和合规测试。请务必遵守你所在地以及目标网络环境的法律法规、单位制度与服务条款。请勿将本项目用于绕过监管、未授权访问、批量代理转售或任何违法违规用途。

这个项目的目标不是“把整台共享服务器切成全局代理机”，而是提供两种更克制、更适合多人环境的能力：

- `sidecar <cmd...>`：让单个命令走代理
- `sidecar-on` / `sidecar-off`：让单个用户进入透明代理模式

当前仓库已经具备统一配置、资源自动探测、安装脚本、节点选择、验证脚本和多 UID 透明代理状态管理。推荐使用方式是：

1. `git clone`
2. `sudo ./install.sh`
3. 用 `sidecar-subscribe` 导入订阅生成 `config.yaml`
4. 把需要使用进程级代理的用户加入 `sidecar` 组
5. 普通场景优先使用 `sidecar <cmd>`
6. 需要整用户透明代理时，再用 `sidecar-on`

当前版本已经去掉了几个原型期的强假设：

- 不再默认使用 `~/.mihomo`
- 不再假设 `mihomo` 固定安装在 `/usr/local/bin/mihomo`
- 不再默认扫描用户家目录里的 Mihomo 运行目录

如果没有显式传 `--mihomo-home`，安装器会使用仓库内的 `./.runtime` 作为默认运行目录，便于开发机试装；面向正式部署时，仍建议显式指定例如 `/opt/mihomo-sidecar`。

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

### 2. 安装运行环境

安装器只负责把运行环境、自动探测结果、systemd unit、secret 和脚本骨架装好，不负责要求你当场提供订阅。

最常见的安装方式：

```bash
sudo ./install.sh --mihomo-home /opt/mihomo-sidecar
```

如果你只是想先在当前仓库里快速装一份运行目录，也可以省略 `--mihomo-home`，这时默认落在：

```bash
./.runtime
```

安装器会做这些事：

- 优先使用显式配置的 `MIHOMO_BIN`
- 如果没配置，再自动 `which mihomo`
- 还找不到时，直接报错并给出官方 release 链接
- 安装脚本和 CLI
- 生成 `${MIHOMO_HOME}/sidecar.env`
- 自动探测共享资源并生成 `${MIHOMO_HOME}/state/runtime.env`
- 生成 `${MIHOMO_HOME}/state/controller.secret`
- 渲染 systemd unit

如果当前环境能检测到 systemd 且目标 unit 目录可写，安装器也会顺手把 unit 拷进去。

### 3. 导入订阅 / 生成配置

大多数用户只有一个订阅 URL，或者一个本地保存的 base64 / trojan 订阅内容。

这一步不再耦合在 `install.sh` 里，而是由单独命令完成。这样后续更新订阅、切换单节点、重生成配置时，不需要重新安装环境。

支持两种入口：

- `sidecar-subscribe --url URL`
- `sidecar-subscribe --file FILE`

内部会调用 [script/sub2mihomo.py](script/sub2mihomo.py)：

- 拉取或读取订阅
- 自动 base64 解码
- 解析 trojan 节点
- 生成 `config.yaml`
- 生成并保存 controller secret

常见示例：

```bash
/opt/mihomo-sidecar/bin/sidecar-subscribe --url 'https://example.com/subscription' --all-nodes
```

```bash
/opt/mihomo-sidecar/bin/sidecar-subscribe --file ./sub.txt --keyword HK
```

如果希望写完配置后立即重启服务，可以追加：

```bash
--restart
```

### 4. 按需准备静态配置

默认情况下，不改任何文件也能直接运行安装器，但正式部署仍建议显式传入 `--mihomo-home`，不要依赖开发态默认目录。

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

如果你已经有手写的 `config.yaml`，也可以不传订阅参数，直接把它放到：

```bash
${MIHOMO_HOME}/config.yaml
```

但这已经不是推荐主路径。

再次强调：
本项目仅供学习交流、实验验证与合规测试使用。是否可以访问外部网络、是否可以建立代理、是否可以转发流量，取决于你所在地区和所在单位的规则。请不要把“能用”误解成“可以随意用”。

### 5. 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-sidecar.service
```

如果安装器没有自动把 unit 放进 systemd 目录，可以手动执行：

```bash
sudo cp /opt/mihomo-sidecar/mihomo-sidecar.service /etc/systemd/system/
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

当前会尽量为每个实例自动分配唯一的：

- TUN 名
- `fwmark`
- route table
- rule priority
- API / DNS / mixed 端口
- mangle / nat chain 名
- `fake-ip-range`
- TUN `inet4-address`

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

如果你需要更新订阅或重建配置，而不是只切 Mihomo controller 里的当前节点，使用：

```bash
sidecar-subscribe --url 'https://example.com/subscription' --all-nodes --restart
```

它默认操作 `PROXY` 组，controller 鉴权 secret 默认从环境变量或 `config.yaml` 读取。

## 已知限制

当前已经能作为“可安装、可验证、可多人使用进程级 sidecar”的工具继续推进，但还有边界：

- 透明代理仍然共享同一套 mangle/nat chain，只是 UID 集合已经支持多人并存。
- 透明代理的回环规避和更细粒度隔离还可以继续增强。
- 自动探测依赖于可见资源与可扫描配置，不是绝对完备的全局发现。
- 当前规则仍以 `iptables` 为主，没有抽象 `nftables` 差异。

## Mihomo 安装说明

安装器不会替你下载 Mihomo 二进制，但会优先自动发现系统里的 `mihomo`。

逻辑是：

1. 如果配置里的 `MIHOMO_BIN` 可执行，就用它
2. 否则尝试 `which mihomo`
3. 还找不到就报错并提示官方 release 页面

官方 release：

- [MetaCubeX/mihomo releases](https://github.com/MetaCubeX/mihomo/releases)

一个常见部署方式是：

1. 先从官方 release 下载适合你系统架构的 `mihomo`
2. 把二进制放到系统 `PATH` 中，例如 `/usr/local/bin/mihomo`
3. 运行 `which mihomo` 确认可被发现
4. 再执行本项目的 `install.sh`

如果你不想改系统 `PATH`，也可以直接传：

```bash
sudo ./install.sh \
  --mihomo-home /opt/mihomo-sidecar \
  --mihomo-bin /path/to/mihomo
```

## 安全说明

最重要的安全建议只有几条，但每条都别省：

- `external-controller` 只监听 `127.0.0.1`
- 不要把真实 `secret`、订阅、节点密码提交进 Git
- 只把需要使用进程级代理的用户加入 `sidecar` 组
- 多实例部署时，确保 TUN / mark / table / priority / ports / chain / fake-ip / TUN 子网都唯一

第三次强调法律与合规边界：
本项目不是“翻墙工具打包器”，而是一个面向 Linux 多用户环境的网络隔离与 sidecar 原型工程。请仅在合法、合规、获得授权的网络环境中使用它；由误用、滥用或违法使用引发的后果，应由实际使用者自行承担。

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
