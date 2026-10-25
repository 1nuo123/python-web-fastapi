# Codex 连接与执行生命周期加固

日期：2026-10-24。范围：本地后端、Windows Agent、Nuxt 前端及隔离验收环境。

本轮实现了连接与执行生命周期分离、发送背压、查询总期限、历史窗口、健康隔离和前端恢复调度。**12 小时隔离长测已通过；部分环境故障及下述实现边界仍未闭环，不能据此宣称全部发布门禁通过。没有部署、安装或发布新 Agent，没有修改线上机器。**

## 统一执行链路

1. CLI 创建一个网络策略 owner 和可复用 HTTP client。挑战、签名、换票据、WebSocket 握手、hello、初次许可共享建链总期限，每次建链使用新票据。
2. `CodexDuplexConnectionSession` 负责唯一 socket 写入者、控制/响应/数据队列、编码字节上限、发送/关闭预算和结构化结束结果。
3. `AgentConnectionPolicy` 决定重连与执行保留。传输失败本身不构成停止执行的资格；许可有效、协商支持连续性、App Server 健康时保留原进程。
4. `AgentExecutionLease` 是执行资格权威。过期、撤销、活动主机切换、本机退出、执行故障显式停止；未确认进程树停止时保持准入关闭，不发送虚假停止确认。
5. 查询沿 API → usecase → facade → host actor → Agent → JSON-RPC 传递期限。写命令继续使用原 Outbox、Journal、command ID，不套用查询重试。
6. 浏览器只由 realtime composable 调度恢复。先恢复主机/执行/审批/当前任务状态，历史正文独立加载；历史失败不把已连接 socket 显示为断线。

## 实现落点

下列路径相对于后端 `E:/python_web_fastapi/work`；前端路径相对于 `E:/python_web_fastapi/typescript-web-nuxt`。

| Owner / 文件 | 实际修改与边界 |
|---|---|
| `src/infrastructure/codex/codex_connection_session.py` | 入队、发送、关闭独立预算；发送超时先关闭再取消，禁止复用不确定连接；三类队列加权公平调度，类别内 FIFO；条数与编码字节双上限；控制消息保留容量；结束时释放排队者、发送任务和缓冲 |
| `src/core/codex_contract/connection_session_contract.py` | 明确发送超时类型、结束 phase/reason_code、队列观测合同；历史窗口子协议名称 |
| `src/api/endpoint_codex_agent/route_codex_agent_connect.py` | 从运行时注入预算和现有 metrics registry；消费 session 结束结果；预期断线异常按连接结束处理 |
| `src/infrastructure/codex_agent/agent_control_channel.py` | 清理连接不默认停止执行；显式停止原因；20 秒建链总期限；许可响应失联检测；快照失败有界重试；进程清理失败禁止重新准入；每次恢复使用当前代次 |
| `agent_connection_policy.py` / `agent_execution_lease.py` | 集中恢复决策；可注入时钟、剩余许可读取；旧代次与迟到响应不续期 |
| `app_server_process_supervisor.py` | stop 锁幂等；terminate/kill 的进程消失竞态可收尾；继续验证 Windows Job 子进程；确认停止后才清空 handle |
| `src/core/codex_contract/codex_runtime_contract.py` / `src/infrastructure/settings/raw_application_settings.py` | 配置字段全链路映射；查询预算大于 ACK、许可覆盖心跳、队列容量覆盖最大帧等约束 |
| `src/infrastructure/codex_agent/agent_configuration.py` / `src/infrastructure/codex/codex_agent_gateway.py` | Agent 明确默认参数；服务端按配置签发许可，协议兼容默认值不再决定线上许可 |
| `src/infrastructure/codex/codex_host_actor.py` / `codex_connection_registry.py` / `codex_runtime_facade.py` / `src/application/ports/codex_agent_command_dispatch_port.py` | ACK 和结果共享绝对期限；断线信号归属连接 epoch；查询取消/断线释放 pending Future；查询历史能力在当前连接上检查 |
| `src/infrastructure/codex_agent/app_server_jsonrpc_client.py` | 写入与结果等待共享预算，写入耗时不重新获得完整等待时间 |
| `src/application/codex/read_thread_snapshot_usecase.py` | UoW 在受控卸载线程中创建、使用、释放；任务来源统一失败语义；元数据请求可返回实时不可用；显式历史请求含首页超时返回 504 |
| `src/domain/codex/codex_error_code.py` / `agent_command_policy.py` / `src/infrastructure/codex_agent/agent_command_executor.py` | 稳定 query_timeout/query_overloaded 分类；查询忙返回 503；程序缺陷不伪装成正常离线 |
| `src/core/codex_contract/agent_history_window_contract.py` / `agent_protocol_v2_contract.py` / `src/infrastructure/codex/agent_protocol_codec.py` | 窗口请求与结果强类型；新可选字段未使用时不发送，避免旧 `extra=forbid` Agent 收到未知字段 |
| `src/infrastructure/codex_agent/agent_thread_history_reader.py` | 单次窗口 1–200 项、最多 8 个上游页、最多 2 MiB；不再无限拉取全历史；部分 turn 游标带摘要检查 |
| `agent_thread_history_window_cache.py` / `agent_timeline_store.py` / `app_server_protocol_adapter.py` | 缓存绑定窗口、游标、revision；复用原 timeline owner；有界 SQL 读取；窗口项刷新后获取 watermark，保留工具记录与稳定 item ID |
| `src/application/codex/codex_history_pagination.py` | 复用签名游标及用户/主机/任务/revision 校验，封装上游窗口游标；旧 Agent 保留受限旧读取路径 |
| `app_server_product_contract.py` / `thread_contract.py` / `realtime_event_contract.py` | `covered_item_ids` 表达部分窗口覆盖范围，不能把部分 turn 冒充完整 turn 后吞掉后续事件 |
| `src/infrastructure/codex_agent/agent_snapshot_builder.py` | 输出页同时限制条数与字节；控制状态过大不丢审批；索引读取不完整时拒绝假报同步成功 |
| `src/application/ports/settings_reader_port.py` / `src/infrastructure/resource_mount/shared_resource_lifecycle.py` | 生命周期更新不可变轻量健康快照，读取不复制完整资源状态、不等热重载锁 |
| `src/api/dependency_context_accessor.py` / `src/api/endpoint_health_probe/route_health_probe.py` / `src/application/health_probe_usecase.py` | 健康路由绕开业务线程池及完整认证上下文组装；未 ready 仍返回 503 |
| `agent_network_policy.py` / `agent_connection_ticket_provider.py` / `src/cli/run_codex_host_agent.py` | HTTP/WS 共享同一个代理策略实例；签名卸载；记录脱敏阶段耗时；复用 client；connect/read/pool 显式预算 |
| `src/core/http_contract/outbound_http_client_contract.py` / `src/infrastructure/resource_slot/shared_async_http_client.py` | 在既有 HTTP client 原语扩展分阶段超时，其他调用方保留原默认行为 |
| `src/core/codex_contract/agent_diagnostic_contract.py` | 类型化连接结束、恢复、执行停止诊断，含 attempt、epoch、phase、reason、耗时、剩余许可与保留状态 |
| `src/infrastructure/observability/prometheus_metrics_registry.py` | 复用现有 registry；低基数连接结束计数、按优先级排队等待直方图、队列字节直方图 |
| `deploy/caddy/Caddyfile.example` | 统一健康 snippet；10s/3s/连续失败3次/连续成功2次；WS stream_close_delay 5m；票据与认证日志脱敏 |

以上未写完整路径的 Agent 文件均位于 `src/infrastructure/codex_agent/`；产品合同文件位于 `src/core/codex_contract/`。

| 前端文件 | 实际修改 |
|---|---|
| `app/composables/useCodexRealtime.client.ts` | 单一恢复 owner；generation、AbortController 与任务选择绑定；旧任务不能完成新代次；认证恢复区分 success/retry/terminal |
| `app/stores/codex-session.ts` | 移除内部固定三次重试，保留 singleflight；不复用已 abort 的请求；关键状态与历史加载分离 |
| `app/stores/codex-realtime.ts` / `app/components/codex/CodexConnectionBanner.vue` / `app/layouts/codex.vue` | historyStatus 接入现有状态与 banner，分别表达重连、关键状态同步、历史失败 |
| `app/services/api/codex-threads.ts` | 查询专用 35 秒、retry:0、AbortSignal，不扩大普通 API 超时 |
| `app/stores/auth.ts` | 网络失败/status0/5xx 保留会话；明确认证终态仍退出，不弱化 TOKEN_REUSED 安全规则 |
| `app/utils/codex-event-reducer.ts` / `codex-event-validator.ts` / `app/types/codex-thread.ts` / `codex-realtime.ts` | 部分 item 覆盖、元数据快照保留历史窗口、不让恢复覆盖新数据 |
| `app/utils/client-performance-diagnostic.ts` / `app/types/app.ts` / 后端 `client_performance_contract.py` | 在原诊断目录区分连接恢复、关键状态恢复、历史加载耗时 |

原 `useAuthenticatedApi` 的单次 refresh/重放锁继续复用；原 write guard 读取关键同步状态，拆开历史后无需另建写入入口。没有为列出的每个文件机械增加无效修改。

## 参数与实验结论

| 参数 | 当前本地配置 |
|---|---:|
| 入队 / 实际发送 / 受控关闭 | 1 / 10 / 3 秒 |
| 队列编码字节上限 | 16 MiB |
| 应用心跳 / Ping / Pong | 15 / 15 / 30 秒 |
| 续期响应连续缺失检测 | 30 秒 |
| presence TTL / 执行许可 | 90 / 60 秒 |
| 单次建链总期限 | 20 秒 |
| 重连退避上限 | 5 秒，加随机抖动 |
| ACK / 服务端查询 / 浏览器查询 | 5 / 25 / 35 秒，ACK 包含在查询总期限内 |
| 浏览器应用无响应阈值 | 60 秒 |

配置来源：`config/runtime/codex_control_runtime/codex_control_runtime_base.toml`；生产 Codex 配置继承它，避免复制第二套值。Ping/Pong 在 stream base 与 production 中对齐。有效 Retry-After 优先于快速恢复目标，不能为保执行绕过限流。

不是把拟定参数直接当最优：close5/cap5 在一次恢复中达到 10.156 秒，未通过 P95≤10 秒门槛；close3/cap5/lease60 的首轮及两个复验分别为 7.891、8.078、8.297 秒，传输专项最慢恢复为 9.657 秒。它是**当前本机故障样本中通过筛选的候选**，小样本百分位不代表生产 P95/P99。

35 秒与 60 秒初筛见 `autotuner/`。早期包含网关注入期的延迟统计仅作探索记录；后续 `autotuner-final/`、`autotuner-close3/`、`autotuner-replicates/`、`autotuner-transport/` 分离故障期与恢复期。原始证据不覆写。

Autotuner 唯一入口：`scripts/codex/autotuner/connection/run.py`；候选、真实场景、淘汰标准、报告分别归属 `candidates.toml`、`scenarios.py`、`evaluate.py`、`report.py`。超时/非零退出/源码变更判失败，禁止复用已有 acceptance 文件。记录完整有效参数、源码摘要、种子、CLI 版本、资源和结论。源代码 Agent 不伪造二进制哈希；打包验收单独记录实际 EXE SHA256。重连抖动用系统熵，种子只固定场景顺序。

延长执行许可同时延长断网时撤销生效的最坏等待，当前上限 60 秒。presence90 秒只是在线投影，不授予执行资格。旧主机未确认停止前不让新主机执行的约束保留。

## 已完成的验收证据

统一证据目录：`E:/python_web_fastapi/work/test-results/connection-hardening`。运行环境为真实 Windows CLI、TLS/WSS、产品 ASGI 路由、隔离 SQLite/local bus；不是生产 Redis/Cloudflare 环境。

| 证据 | 结果 / 实际覆盖 |
|---|---|
| `initial-e2e.json` | 真实 CONNECT 断开，重新换票据并恢复，实例保留 |
| `lifecycle-e2e.json` | 9 场景通过：520/522、票据消耗后重试、慢 RPC 不阻断许可、Journal 去重、在途结果断线、短断网保实例、许可到期停进程树、长断网恢复、未协商保守停止、撤销停止；部分断言合并为一个场景 |
| `mutation-e2e.json` | 真实 thread.start 只调用一次，重复 ID 回放；隔离任务已清理 |
| `history-window-e2e.json` | 真实 CLI 创建文本 turn，经签名 HTTP 游标读取 2 页/2 个不同项；篡改游标 409；隔离任务已清理 |
| `health-e2e.json` | 实际业务池 4 个 worker 饱和时健康响应约 47ms；未 ready 返回 503 |
| `autotuner-replicates/report.json` | 两轮重复通过，恢复 8.078 / 8.297 秒，无执行误停、票据复用或采样缺口 |
| `autotuner-transport/report.json` | TCP reset、真实 ASGI send 延迟 1.2 秒、超过发送预算、8 KiB/s 链路、520/522/429；进程保留；最大恢复 9.657 秒 |
| `caddy/validate.log` | 与项目部署一致的 Caddy 2.10.2 官方二进制验证配置成功，下载包按官方 SHA512 校验 |
| `caddy-reload-e2e.json` | 实际 Caddy admin reload 前后同一 WebSocket 能继续收发 |
| `binary-e2e.json` | 首次隔离 EXE：网关/票据恢复、doctor、单实例拒绝、Agent 真实崩溃清理 7 个归属子进程通过；不是已签名安装发布 |
| `binary-final-e2e.json` | 最终源码重构建 EXE 的 5 项验收全部通过；本轮真实崩溃清理 3 个归属子进程，无票据复用；与首次构建证据分开保存 |
| `soak-final-smoke-e2e.json` | 最终源码 60 秒长测入口通过，source_unchanged=true；不是 12 小时结果 |
| 前端 `tests/e2e/codex-connection.spec.ts` | Playwright 真实浏览器，HTTP/WS 边界受控；离线/恢复与 refresh502 保留任务页通过；**不是浏览器到真实 Agent 的全链端到端证明** |

Python 变更经过语法编译与 Ruff I/F、格式检查；Nuxt typecheck 通过。按本轮要求不运行单元测试、不运行包含单测的 nox offline/regression 或 pnpm release:check。此前健康夹具错误假设 8 个 worker 的失败结果未作为产品失败；改用实际池容量后通过。

## 发布兼容与仍待完成项

窗口能力以 WebSocket 子协议 `codex-agent.v2.history-window` 协商，不向旧 hello 强加字段。部署先让前端识别可选 item 覆盖字段，再部署支持新旧协议的服务端，最后发布新 Agent。仅能力确认且实验 API 配置允许的连接启用窗口；否则使用有界旧路径。没有自动启用实验 API，没有提升版本号或发布 MSI。

必须如实区分下列事项：

- **12 小时隔离长测已通过（2026-10-25 07:40:37，北京时间）。** 长测每分钟真实只读命令、每 10 分钟受控重连，记录任务/Future/队列/RSS、正常期与注入期。机器休眠、采样间断、源码/配置变化使证据无效；不修改电源策略。运行状态以 `soak-12h.json` 为准，未出现 completed/通过不能宣布长测完成。
- **完整环境矩阵尚未跑完。** Redis 延迟、真实 Windows 休眠唤醒、Cloudflare 实际边缘切换、持续大历史与事件洪峰组合尚无完整实测。已有 520/522 是真实 HTTP 故障注入，不是访问 Cloudflare 边缘的证据。
- **Windows 精确 ProcessLookupError 竞态未逐指令故障注入。** 实现捕获并保留进程树确认；真实进程退出/崩溃清树通过。用户不要求单测，因此不把这些 E2E 扩张成“准确复现了每个竞态步骤”。
- **没有另引入 Toxiproxy。** 复用现有 CONNECT 代理实现真实双向/单向暂停、限速和 TCP 断开；避免维护第二套代理故障入口。Docker daemon 当前未启动；这不影响现有真实传输注入，但也不构成 Redis 环境验收。
- **中央 Prometheus 尚不具备可靠的 Agent 离线许可过期/进程重启计数和完整恢复直方图。** 本轮保留类型化本机生命周期事实，服务端统计自己实际观察到的连接和队列。离线事实若要集中计数，需要持久遥测回放及去重；仅在恢复后发一条消息会丢失离线退出，不应伪装为准确指标。本轮没有为此新增独立 exporter 或第二条事实链，此项未完整落地。
- **任务索引不是流式枚举。** 快照输出已按条数/字节分页，读取仍先枚举工作区索引，在同步总期限内重试；超过上游单帧容量时拒绝假报完整。没有以截断旧任务换取看似成功的同步。超大索引的全程流式收敛仍是已知容量边界，不能声称已解决。
- **当前单进程连接归属保持不变。** 不增 Uvicorn worker 或后端副本；跨实例归属与命令转发不在本轮擅自引入。
- 没有移除 Cloudflare、强制绕过系统代理、取消执行许可或弱化刷新令牌复用判定。当前证据不能支持这些做法。

## 复跑入口

在 `E:/python_web_fastapi/work` 执行，使用新输出目录保留旧证据：

```powershell
.venv/Scripts/python.exe -X utf8 -B scripts/codex/autotuner/connection/run.py --only=continuity-60-close3 --output=test-results/connection-hardening/new-screening
.venv/Scripts/python.exe -X utf8 -B scripts/codex/acceptance/windows_connection.py --proxy=http --soak-seconds=43200 --acceptance-report=test-results/connection-hardening/new-soak-12h.json
.venv/Scripts/python.exe -X utf8 -B scripts/codex/acceptance/windows_connection.py --history-window --acceptance-report=test-results/connection-hardening/new-history.json
.venv/Scripts/python.exe -X utf8 -B scripts/codex/acceptance/windows_connection.py --health-isolation --acceptance-report=test-results/connection-hardening/new-health.json
.venv/Scripts/python.exe -X utf8 -B scripts/codex/acceptance/windows_connection.py --caddy-reload --acceptance-report=test-results/connection-hardening/new-caddy.json
```

Caddy 验收读取证据目录内经校验的本机 caddy.exe；不是通用自动下载器。长测报告中的 sampled availability 只描述该隔离进程的采样结果，不能换算成生产 99.9% 可用性承诺。

## 当前长测归属

按用户最新要求，长测验收目标调整为 **12 小时（43200 秒）**。原进程不能热改启动时长，原 72 小时及 24 小时轮次均已取消；`soak-72h.json`、`soak-24h.json` 保留部分观测数据，不能合并计入新轮次。新轮次使用 `soak-12h.json`，从新启动时间连续计满 12 小时；实际开始时间、PID 与预计结束时间以报告及 `soak-12h-launch.json` 为准。venv 启动器与子进程 PID 不同是正常的，检查归属须核对启动时间和命令行。

`soak-12h-launch.json` 保存启动归属，`soak-12h.json` 保存动态状态，stdout/stderr 分文件保存。自动跟进 ID 为 `72`。最终核验发现其配置重新指向旧 72 小时报告，未按预期完成通知；本次手工读取真实 12 小时报告确认结果，并修正、暂停该跟进。配置回退原因尚未确认，不据此推断测试本身异常。

最终源码与独立构建产物摘要见同目录 `delivery-manifest.json`。本轮参数只能称为本机筛选通过，仍未晋升为已完成全部验收的发布版本。

最终 EXE：`test-results/connection-hardening/binary-final/dist/codex-remote-agent.exe`。SHA256：`a7fc0dd37518b5828cae240ad93494ec1457e430697a4c785d9d03ccad99fea4`。它是隔离验收产物，没有替换安装目录、签名或发布。

本次只调整验收时长，故障注入频率、资源与恢复阈值、休眠/采样缺口及源码变化失效规则均保持不变。此前 autotuner 历史报告中的 72 小时要求保留为当时记录，当前门禁以本文及新脚本的 12 小时要求为准。

本轮于北京时间 2026-10-24 19:40:35 启动，2026-10-25 07:40:37 完成；原验收进程 PID 206428 已退出，无收尾错误。

## 12 小时最终验收结果

真实报告：`test-results/connection-hardening/soak-12h.json`。`status=completed`、`passed=true`、`source_unchanged=true`，无 error/shutdown_error，测试进程已退出。

| 指标 | 结果 |
|---|---:|
| 实际观测时长 | 43201.609 秒（约 12 小时） |
| 真实只读查询 | 668 次 |
| 查询失败 | 0 |
| 受控重连 | 71 次 |
| 恢复 P95 / P99 | 1.406 / 1.453 秒 |
| 采样缺口 | 0 |
| 非注入期记录到的不可用时长 | 0 秒 |
| 注入恢复总时长 | 87.578 秒 |
| 进程树 RSS 峰值 | 278265856 字节（约 265.4 MiB） |
| 最近资源窗口 RSS 增长 | 约 1.70 MiB/小时，低于 8 MiB/小时门槛 |
| 最后资源样本 pending ACK / result | 0 / 0 |

以上结论限于本次隔离环境及既定采样/门槛。保留前文未完成的真实 Redis/Cloudflare/休眠环境矩阵、中央生命周期指标和超大索引容量边界；不将本轮通过解释为零内存增长或生产可用性证明。用户无需继续为这一轮保持电脑开机。
