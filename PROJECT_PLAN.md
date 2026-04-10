# PROJECT_PLAN

本文档给出一个“只做最小增量、逐步把原型升级成开源工具”的执行计划。

分析依据仅来自当前 4 个实现文件：

- `创建服务`
- `script/setup-rules.sh`
- `script/cleanup-rules.sh`
- `script/select_node.py`

## 当前事实总结

当前仓库已经验证了两件事：

1. 可以通过 Mihomo TUN + `iptables` + `ip rule` 实现基于 GID 的进程级代理基础设施。
2. 可以通过 Mihomo REST API 做节点切换。

但当前仓库还没有形成一个正式产品：

- 没有 CLI
- 没有安装器
- 没有配置层
- 没有资源探测
- 没有透明代理模式
- 没有验证与排障入口

## 设计目标

把当前原型升级为一个面向多用户 Linux 共享服务器的开源工具，并满足：

- 支持 `sidecar <cmd...>` 进程级代理
- 支持 `sidecar-on` / `sidecar-off` 用户级透明代理
- 提供安装、卸载、启停、诊断、节点选择能力
- 尽量复用现有底层规则逻辑
- 不引入没有必要的新依赖

## 非目标

第一阶段不追求：

- 一开始就重写全部 shell 逻辑
- 引入复杂的配置管理框架
- 引入数据库、守护进程总线或大型第三方 Python 依赖

## 建议目录演进

在不大改逻辑前提下，后续可以逐步演进为：

```text
.
├── bin/
│   ├── sidecar
│   ├── sidecar-on
│   └── sidecar-node
├── script/
│   ├── setup-rules.sh
│   ├── cleanup-rules.sh
│   ├── validate.sh
│   └── common.sh
├── systemd/
│   └── mihomo-sidecar.service.template
├── config/
│   └── sidecar.env.example
├── docs/
│   ├── current-architecture.md
│   ├── roadmap.md
│   ├── install.md
│   └── troubleshooting.md
├── install.sh
├── uninstall.sh
└── PROJECT_PLAN.md
```

这只是演进方向，不代表现在立刻要实现全部文件。

## 分阶段执行计划

## 阶段 1：冻结当前行为，抽出统一参数源

目标：

- 先把所有硬编码值集中起来
- 保持当前行为不变

最小任务：

1. 盘点所有硬编码参数。
2. 设计一份轻量配置文件，例如 `sidecar.env`。
3. 让 service 模板、setup、cleanup、node 选择共享这份参数。

完成标志：

- 不再出现 `/home/duxin/.mihomo`、`1026`、`9091`、`1054` 等值散落多处。

## 阶段 2：做安装闭环

目标：

- 从“手工复制片段”升级到“可安装工具”

最小任务：

1. 新增 `install.sh`。
2. 新增 `uninstall.sh`。
3. 新增 systemd unit 模板。
4. 安装时落地脚本、配置、unit 和状态文件。

完成标志：

- 用户不再手工执行 `sudo tee /etc/systemd/system/...`
- 卸载后规则和 unit 都能正确回收

## 阶段 3：做资源探测与状态记录

目标：

- 避免共享服务器上因硬编码资源而冲突

最小任务：

1. 检查 TUN 名称是否已存在。
2. 检查 `fwmark` / `table` / `priority` 是否冲突。
3. 检查 API 端口与 DNS 端口是否被占用。
4. 检查 fake-ip-range 与 tun subnet 是否冲突。
5. 把最终分配结果写入状态文件。

完成标志：

- 安装器能够给出“自动选择结果”或“明确冲突原因”

## 阶段 4：补正式 CLI

目标：

- 让用户通过稳定命令使用现有能力

最小任务：

1. 提供 `sidecar <cmd...>` 封装 GID 模式。
2. 提供 `sidecar-node list/use/current`。
3. 提供 `sidecar status`。

完成标志：

- 普通用户不需要手工理解脚本内部细节

## 阶段 5：补透明代理

目标：

- 实现 `sidecar-on` / `sidecar-off`

最小任务：

1. 设计 UID 匹配规则。
2. 明确如何排除 Mihomo 自身流量，避免回环。
3. 明确透明代理的启停状态存储。
4. 把 GID 模式与 UID 模式的规则命名、优先级和清理路径区分开。

完成标志：

- 当前用户能开启/关闭自己的透明代理

## 阶段 6：补验证与排障

目标：

- 让开源用户能自行定位问题

最小任务：

1. 新增 `sidecar validate`。
2. 新增 `sidecar doctor`。
3. 新增安装文档与故障排查文档。

完成标志：

- 常见问题可以通过命令与文档定位，而不是靠阅读源码

## 风险清单

这些风险都直接来自当前 4 个文件的实现方式：

1. 路径硬编码风险：当前 service 片段只适用于 `/home/duxin/.mihomo`。
2. 资源冲突风险：`fwmark=0x2`、`table=101`、`priority=1001`、`DNS port=1054` 均可能与宿主机现有规则冲突。
3. TUN 耦合风险：规则脚本默认 TUN 名必须是 `Meta-sidecar`。
4. 配置耦合风险：`select_node.py` 假定 controller 在 `127.0.0.1:9091` 且组名为 `PROXY`。
5. 生命周期风险：规则安装在 `ExecStartPost`，若 Mihomo 启动不稳定，状态可能介于“服务失败”和“规则部分遗留”之间。
6. 可移植性风险：当前只考虑了 `iptables` 路径，没有显式处理 `nftables` 生态差异。

## 成功标准

达到“可发布开源软件”的最小标准时，至少应满足：

1. 一键安装、一键卸载可用。
2. 默认配置可运行，关键资源可自动探测或冲突时报错。
3. `sidecar <cmd...>` 可稳定工作。
4. `sidecar-on` / `sidecar-off` 可对单用户透明代理。
5. 节点选择可脚本化，不仅限交互式输入。
6. 有基本验证命令和排障文档。

## 建议先做的最小增量步骤

如果要以最低风险开始推进，我建议先只做下面 5 件事：

1. 把所有硬编码参数整理成一份统一配置。
2. 把 `创建服务` 改造成 systemd 模板文件，而不是手工命令片段。
3. 补 `install.sh` 和 `uninstall.sh`，先把安装/清理流程闭环。
4. 给当前 GID 模式包一层最薄的 `sidecar` 命令入口。
5. 给 `select_node.py` 增加非交互选择和基础过滤能力。

这样做能最快把当前原型推进到“别人可以安装、运行、切换节点、卸载”的状态，同时不需要立刻重写底层规则逻辑。
