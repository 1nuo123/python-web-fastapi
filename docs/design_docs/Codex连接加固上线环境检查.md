# Codex 连接加固上线环境检查

检查日期：2026-10-25，北京时间。目标：`root@39.96.201.189`，公网入口 `https://nuotop.xyz`。

## 结论

当前环境具备受控发布基础，但当前交付还不是可直接全量上线的完整发布包。12 小时隔离长测通过，检查时本地源码摘要与长测摘要一致。新后端/前端镜像、新 Agent 安装包与发布清单、生产依赖组合下的关键路径验收尚未闭环，不能将隔离验收当作这些环节的替代。

本次服务器检查仅执行读取、日志汇总、健康 GET、Docker inspect/stats、Caddy admin GET 及备份文件校验。没有上传文件、改配置、拉取镜像、重启、发布、迁移或故障注入。远端没有输出密码、令牌、完整环境变量或票据查询串。

## 线上实况

| 项目 | 实测 |
|---|---|
| 容器 | 前端、后端、task-worker、Caddy、Redis、Postgres、RabbitMQ 共 7 个，均 healthy，RestartCount=0，未标记 OOMKilled |
| 后端镜像 | `ghcr.io/1nuo123/python-web-fastapi:14dd31d29d093e4ef62093d11d0d55152fd23547`，10 月 20 日构建 |
| 后端 digest | `sha256:be2ffdcc79b9c4990caaeab9e841412b2485b2b3b784a83b735811b6856ae89d` |
| 前端镜像 | `ghcr.io/1nuo123/typescript-web-nuxt:10a43e26343abbe1a41a9c87ca1d1f9cb2a1badf`，10 月 23 日构建 |
| 前端 digest | `sha256:8229ddef8200eadd4cb493510fee261a05a77e05901df6ad5b3ecd884a0c28a3` |
| 工作目录 | 后端 `/opt/web/python-web-fastapi`，前端 `/opt/web/typescript-web-nuxt`；tracked 工作区干净，HEAD 与对应镜像 tag 一致 |
| 拓扑 | 单 app 服务，实际一个 Python Web 主进程；task-worker 是独立业务任务进程，不是第二个 Web worker |
| Caddy | 2.10.2；运行中 admin 配置确认仍是旧健康检查 30s/5s，无显式连续失败/成功阈值，无 stream_close_delay |
| 公网 HTTPS | 首页、`/health/ready` 均 200，TLS 校验成功；本机单次总耗时分别约 13.83s / 5.76s，含网络建链，不能等同服务端执行耗时 |
| 源站健康 | 容器内直连 `/health/ready` 连续三次 200，约 74 / 30 / 35ms |
| 配置文件 | 线上镜像 presence30s、ACK10s、Ping/Pong20s/20s；没有新增发送/关闭/查询/许可配置字段，源码也未包含本次拆分发送预算实现 |
| Agent 发布配置 | production 文件仍指向 0.1.38；本地候选配置也未更新安装包版本和下载摘要 |
| 历史窗口 | 当前 production 文件 `allow_experimental_app_server_api=false`；新 Agent 仅在其 profile 允许实验 API 且子协议协商成功时启用窗口，不能宣称普通升级后所有用户自动得到窗口路径 |
| 资源 | 2 CPU，物理内存约 1.6 GiB；检查初始 available 约 593 MiB，swap 已使用约 902 MiB；磁盘已用48%，可用约20 GiB |
| 内存压力 | PSI avg10 很低，短样本无持续 swap-out；不能仅凭 swap 占用证明正在内存抖动，但并行构建/新旧容器重叠空间有限 |
| 资源配置 | app 与 task-worker 各可达1 GiB、frontend512 MiB、Caddy256 MiB；Redis/Postgres/RabbitMQ 未设 Docker 内存上限，所有上限之和并不代表物理资源保障 |
| 备份 | `/var/backups/fastapi-web/postgres-20261023T061440Z.dump`，约68.4 MB，SHA256 与旁路校验文件一致；未执行恢复验证 |

配置读取针对镜像内 TOML、有限环境变量及 Caddy 已加载配置；未读取数据库动态覆盖全量内容，因此不将文件值冒充所有运行时覆盖后的最终值。

## 与本次改动直接相关的线上异常

最近24小时的 Caddy 日志中，存在健康检查等待响应头超过5秒、约25秒后恢复的记录。**2026-10-25 05:26:35（北京时间）**，`/internal/codex-agents/device-challenges` 返回503，Caddy 明确记录 `no upstreams available`。这证明 Agent 建链曾因代理认为源站不可用而失败，不能简单归咎于用户电脑断网。

另有两次任务快照 GET 502，发生于10月24日13:37。没有凭这些日志确认全部底层原因；健康共享执行池与进程调度压力都需要上线后对照观测。本次健康隔离与 Caddy 连续失败阈值正好针对其中已确认的耦合路径。

后端检查使用24小时内最多15000行日志，未见 Traceback/TimeoutError/ERROR；因为达到读取上限，不能宣称覆盖完整24小时无异常。Caddy日志较少，完整读取了该窗口。RabbitMQ一次CPU样本偏高、后续降至0.24%，不把瞬时采样当成持续瓶颈。

## 发布前必须补齐

1. **封装本次源码。** 当前本地 HEAD 与线上相同，本次实现仍在工作区，单纯 `git pull` 不会部署这些修复。冻结并核对本次变更，生成新的可追溯修订、前后端镜像和不可变 digest；不要把原有文档迁移等无关工作区变化混入发布。
2. **完成 Agent 安装发布闭包。** 已验收的是 `test-results/connection-hardening/binary-final/dist/codex-remote-agent.exe`，SHA256 `a7fc0dd37518b5828cae240ad93494ec1457e430697a4c785d9d03ccad99fea4`。尚不是新的可分发 MSI/manifest。复用 `scripts/codex/build_internal_production_agent_installer.ps1`，选择未占用发布版本，生成安装包、校验和、来源记录，更新 `config/runtime/codex_control_runtime/codex_control_runtime_production.toml` 中版本、下载地址及摘要，再验证实际安装/升级后的 Agent。不能只替换服务端就声称 Windows 进程竞态也已修复。
3. **候选镜像跑生产依赖关键 E2E。** 使用隔离 PostgreSQL/Redis/RabbitMQ、Caddy 和生产构建前端，与实际新 Agent 走一次登录、连接、执行、断线恢复、审批和历史读取。已有长测使用 SQLite/local bus；浏览器现有连接用例使用受控边界，二者不能合称完整生产栈验收。无需重跑已通过的12小时门禁来替代这项缺口。
4. **准备新鲜回滚点。** 当前备份为10月23日，发布前创建并校验新备份，至少验证其可读取，理想为隔离恢复；保留本文已核实的旧镜像 digest、旧 Caddy 配置和旧 Agent 发布清单。本次未创建备份，避免将环境检查变成生产写操作。

以上是本次发布的直接缺口，不要求先完成多实例高可用或另做第二套监控平台。中央离线生命周期指标、超大索引容量以及真实休眠等剩余边界仍按实现报告保留，不伪装成已经解决。

## 推荐发布顺序与现场验收

1. 在本地或CI构建镜像，避免在1.6 GiB线上主机并行构建前后端。采用既有 Compose 单实例拓扑，不增加 Web worker/副本。
2. 前端先支持新增可选覆盖字段；服务端随后发布兼容新旧Agent的版本。app/task-worker使用同一后端镜像，避免代码版本漂移。
3. 更新并校验 Caddy 配置后受控 reload：健康10s/3s、fails3/passes2，WS stream_close_delay5m。新配置不能追溯保护原配置下已经建立的所有连接，首次切换仍按可能断连处理。
4. 在没有正在执行的用户任务时升级首台 Agent，再扩大发布。旧服务端停止或旧 Agent 升级期间不能承诺零中断；保留执行许可、主机互斥和停止确认。
5. 现场核对真实生效参数：presence90、许可60、ACK5、查询25、发送10、关闭3、Ping15/Pong30；浏览器查询35秒。出现环境覆盖时按生效值复核，不只看源码默认。
6. 使用隔离测试任务验证一次真实公网断线恢复，确认相同 App Server 实例、任务无重复执行、审批状态正确；记录连接恢复、关键状态恢复、历史加载三阶段。观察 Caddy 5xx、health上下线、Agent许可过期、进程重启与宿主内存压力。
7. 出现任务误停、重复执行、许可失效后仍执行、持续5xx或健康抖动时停止扩大发布并按既有镜像/配置回滚。不能为压住告警关闭租约或认证判定。

12小时长测的源码摘要与本次检查时源码相同：`63fea1fb8dbffb12969960a6d0fc98e268baa4342acd7fcbc8be1986da108832`。这证明检查对象未偏离已测源码，不证明新的镜像、MSI和生产组合已验收。
