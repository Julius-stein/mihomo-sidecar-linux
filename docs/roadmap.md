# Roadmap

本文档基于当前 4 个实现文件的实际行为，给出把项目升级为可发布开源工具的分阶段路线图。

原则：

- 先产品化，再重写底层
- 先参数化，再做自动探测
- 先补安装与验证闭环，再扩展功能面
- 尽量不引入不必要的新依赖

## 目标定义

项目主题：

在多用户 Linux 共享服务器上部署基于 Mihomo 的代理，并同时支持：

1. `sidecar <cmd>` 形式的进程级代理
2. `sidecar-on` 形式的当前用户透明代理

## 里程碑 0：把现状文档化

目标：

- 把现有 4 个文件的职责、耦合和假设写清楚
- 明确哪些行为已经存在，哪些只是目标

交付：

- `docs/current-architecture.md`
- `docs/roadmap.md`
- `PROJECT_PLAN.md`

## 里程碑 1：参数收敛，不改核心规则语义

当前最大风险不是“规则不工作”，而是“所有关键参数都硬编码且分散”。

建议先做：

1. 定义统一配置文件格式。
2. 让 shell/Python/service 模板从同一份配置读参数。
3. 把当前固定值迁移为默认值，而不是直接删掉。

本阶段至少覆盖：

- Mihomo binary path
- Mihomo workdir
- TUN device name
- fwmark
- route table
- rule priority
- DNS redirect port
- sidecar GID
- transparent UID
- API listen host/port
- API secret source
- proxy group name
- 自定义链名前缀

验收标准：

- 不改当前默认行为时，效果与现状一致
- 安装后的产物不再写死 `/home/duxin/.mihomo`
- `setup` 和 `cleanup` 不再各自维护一份重复常量

## 里程碑 2：资源自动探测与冲突规避

这是把脚本变成开源工具的关键能力之一。

当前缺失的自动探测至少包括：

1. TUN 名称占用检查与命名策略
2. `fwmark` 冲突检测
3. 路由表号冲突检测
4. `ip rule priority` 冲突检测
5. Mihomo API 端口与 DNS 端口冲突检测
6. fake-ip-range 冲突检测
7. tun subnet 冲突检测

建议策略：

- 优先允许显式配置
- 未显式配置时自动选择空闲值
- 生成安装状态文件，记录最终分配结果
- 卸载时基于状态文件精确回收，而不是依赖“猜测”

建议输出：

- `state/runtime.env` 或等效状态文件
- `sidecar doctor` / `sidecar validate` 子命令

验收标准：

- 同一台共享服务器上多实例安装时，能显式拒绝冲突或自动避让
- 用户能看到最终实际使用的 TUN、端口、mark、table、priority

## 里程碑 3：安装、卸载与 systemd 自动注册

当前 `创建服务` 只是一个手工复制 unit 的命令片段，还不是安装流程。

应补齐：

1. 一键安装
2. 一键卸载
3. systemd unit 自动生成与注册
4. systemd reload / enable / start 流程
5. 卸载时的 stop / disable / remove / cleanup 流程

建议新增但保持轻量：

- `install.sh`
- `uninstall.sh`
- `systemd/mihomo-sidecar.service.template`

验收标准：

- 从空机器到可运行服务不需要手工编辑 unit
- 卸载后不遗留路由规则、iptables 链和错误的 unit

## 里程碑 4：CLI 产品层

当前仓库已有“规则机制”和“节点切换脚本”，但没有正式 CLI。

建议形成统一入口：

- `sidecar <cmd...>`
- `sidecar-on`
- `sidecar-off`
- `sidecar-node list`
- `sidecar-node use <name>`
- `sidecar validate`
- `sidecar doctor`
- `sidecar status`

其中：

- `sidecar <cmd...>` 聚焦 GID sidecar 模式
- `sidecar-on` / `sidecar-off` 聚焦 UID 透明代理模式

验收标准：

- 用户无需理解 `newgrp`、`sg`、`iptables`、`ip rule` 的细节
- 失败时能给出面向用户的诊断信息

## 里程碑 5：GID sidecar 模式与 UID 透明代理模式双支持

这是功能目标的核心扩展。

### 5.1 GID sidecar 模式

基于现有 `--gid-owner` 机制延伸，优先做到：

- 提供正式 `sidecar <cmd>` 命令
- 自动检查目标 GID 是否存在
- 自动生成 shell snippet，减少用户手工操作

### 5.2 UID 透明代理模式

当前 4 个文件里完全没有 UID 模式实现，需要新增设计。

建议方向：

- 为指定 UID 建立单独的 `OUTPUT` 匹配规则
- 区分 root、service 用户和目标普通用户
- 避免把 Mihomo 自身流量再次代理导致回环
- 定义 `sidecar-on` / `sidecar-off` 的启停与状态切换机制

验收标准：

- 两种模式共存但互不干扰
- 文档中明确说明适用场景和安全边界

## 里程碑 6：节点过滤与选择

当前 `select_node.py` 已能列出并切换 `PROXY` 组，但还不够产品化。

建议增强方向：

1. 支持非交互选择
2. 支持按关键字过滤
3. 支持显示当前节点
4. 支持失败时给出 controller 不可用、secret 缺失、group 不存在等分类错误
5. 支持代理组名配置化

保持无新依赖的实现方式：

- 继续使用 Python 标准库
- 或改写为 shell + `curl`，但 Python 标准库版本更清晰

验收标准：

- 用户可通过命令完成 `list/filter/use/current`
- 不再强依赖交互式输入

## 里程碑 7：验证与故障排查

要成为开源工具，必须内建验证与诊断。

建议补齐：

1. 安装后自检
2. 网络规则自检
3. Mihomo API 自检
4. DNS 重定向自检
5. 路由命中与 TUN 状态自检
6. 常见故障排查文档

建议最小诊断集合：

- `ip link show <tun>`
- `ip rule show`
- `ip route show table <table>`
- `iptables -t mangle -S`
- `iptables -t nat -S`
- controller API 探活
- 当前节点与组信息读取

验收标准：

- 用户遇到问题时，不必直接阅读脚本源码才能定位错误

## 当前项目距离“可发布开源软件”还缺哪些能力

下面这份清单直接对应当前 4 个文件尚未覆盖的能力面。

### 资源自动探测与冲突规避

- 缺少 TUN 自动命名和占用检测
- 缺少 `fwmark`、`table`、`priority` 的冲突检测与自动分配
- 缺少 API 端口、DNS 端口占用检测
- 缺少 fake-ip-range 冲突检查
- 缺少 tun subnet 冲突检查

### 一键安装 / 卸载

- 缺少安装脚本
- 缺少卸载脚本
- 缺少安装状态记录
- 缺少升级路径

### systemd 自动注册

- 目前只有一个 unit 创建片段
- 没有模板化 unit
- 没有 enable/start/stop/disable 的自动流程

### bashrc/snippet 自动生成

- 当前 4 个文件中没有自动生成 shell snippet 的逻辑
- 没有把 `sidecar` 命令接入用户 shell

### 配置文件化

- 当前参数全部硬编码在 shell/Python/unit 片段中
- 没有统一配置源

### GID sidecar 与 UID 透明代理双支持

- 已有 GID 路由规则雏形
- 尚无正式 `sidecar` 命令
- 完全没有 UID 透明代理的规则和生命周期管理

### 节点过滤与选择

- 当前仅支持交互式编号选择
- 不支持过滤、脚本化调用、默认组配置

### 验证与故障排查

- 没有 `validate`/`doctor` 命令
- 没有错误分级
- 没有面向用户的排障文档

## 推荐实施顺序

为了保持最小风险，建议按下面顺序推进：

1. 配置文件化
2. 安装/卸载 + systemd 模板化
3. 资源自动探测与状态记录
4. GID 模式正式 CLI 化
5. 节点过滤与非交互切换
6. UID 透明代理模式
7. 验证与故障排查体系

这个顺序的好处是：

- 能尽快把原型变成“别人可装、可跑、可删”的工具
- 避免在基础参数仍然散落时就扩展透明代理，导致复杂度失控
