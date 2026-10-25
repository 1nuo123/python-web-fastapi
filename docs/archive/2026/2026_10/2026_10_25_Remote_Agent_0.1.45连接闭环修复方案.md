# Remote Agent 0.1.45 连接闭环修复方案

## 交付约束

仅交付 0.1.45，跳过 0.1.44。不使用技能或子代理，不运行单元/回归测试套件；允许真实端到端验收及构建所需检查。用户自行提交、更新服务器和发布版本。本文件先记录方案，再随实施补齐结果；未经验收的部分不记为通过。

## 已确认的问题

1. 公网 nuotop.xyz 仍解析到 Cloudflare。此前同域名保留 TLS 校验的对照中，边缘路径六次四次超时，源站三次均约 0.10 秒。当前 Agent 改走系统 HTTP 代理 127.0.0.1:7890 后能维持心跳，但不能把一次网络路径变化当作软件修复。不得自动改 DNS、代理或绕过证书。
2. 已部署的活动主机收尾修复已在服务器完成旧主机的许可到期收尾。当前新主机 6f4d589e… 已握手，持续得到 inactive_host；原始日志每十五秒重复执行停止并打印停止诊断，网络连接被显示成连接受阻。
3. 前端 reconcileSelections 自动选第一台电脑，restoreFromRoute 同样直接设置 selectedHostId；都没有激活服务器执行资格。唯一主机已显示为当前选项时，再选同项不会触发 change。设置页没有明确的启用按钮。
4. GET /codex/hosts 将 presence 与 active_host 求交集，已连接但未激活的主机被映射为 offline。网页实时服务连接、Agent 连接、执行资格的表现混淆。
5. 服务端 hello watchdog 仍复用 agent_rpc_ack_timeout_seconds=5，并用 1002 关闭超时连接；Agent 将其当协议不兼容而停留终态。WebSocket 关闭原因在客户端适配器和会话层丢失。
6. 建链总期限覆盖换票据、WebSocket、hello 和执行许可，但总超时从外层取消内部任务时，内部 finally 可能按 unexpected_failure 清理执行。执行许可等待没有同时观察会话退出。
7. 已绑定设备在设置/重新连接入口还存在 CLI 发现失败的日志。需要沿现有 CLI 解析与设置恢复路径定位，不应重新签发身份来处理本机 CLI 入口问题。

## 统一模型和实施范围

### 服务端连接与执行事实

保留 CodexActiveHostService 的唯一 CAS 权威。保留 status 的现有“可执行在线”语义以免放开写入保护，增加由 presence 派生的连接观测供展示，不能将它当执行许可。设置页明确显示已连接/待启用；主机选择与显式启用复用 session.selectHost，不另建 API 或入口。

### 握手与错误恢复

为服务端 hello 使用独立预算，原始配置、类型契约、基础配置完整接线。hello 超时用可重试关闭码和稳定原因；真实协议损坏仍保留终态。Agent 同时观察 hello/许可事件和会话结束，外层 deadline 的取消走传输恢复决策；有有效许可且进程健康时保留执行。关闭原因只传递有限允许枚举，不输出票据或任意对端内容。

在已有 autotuner 中用真实 HTTPS/WSS 故障场景比较握手预算，记录配置、来源、结果和结论；不凭感觉全局提高超时。公网永久不可达不由无限加大超时解决。

### Agent 本地生命周期

非活动主机是“已连接、待启用”，不是认证失败。相同 disabled 许可只在状态转换或尚未完成清理时停止进程，停止成功可重复发送当前代次确认，但不重复制造执行停止日志。协议、配置失败不得全部打印 device_revoked。CLI 发现复用已有解析 owner，避免重新绑定和修改工作区。

### 前端用户流程

设置页提供“使用这台电脑”按钮，唯一主机也能明确激活，展示等待、错误和重试。调用已有选择 action，保持现有 UI 组件风格。展示浏览器实时连接和主机连通性的区别；执行准入仍依据服务端资格及当前同步状态。异步选择任务有清晰的取消/并发边界，不让旧请求覆盖新选择。

### 发布产物

复用 build_internal_production_agent_installer.ps1，增强现有构建 owner 自动生成来源摘要与构建证据，避免手工伪造 provenance。0.1.45 目录恰好五个文件：CodexRemoteAgent.msi、internal-release.json、SHA256SUMS.json、build-evidence.json、source-files.sha256.json。发布说明和验收记录放文档/验收目录，不向版本目录加入第六个文件。同步后端版本、下载地址和实际 MSI SHA256。不覆盖 0.1.43，不创建 0.1.44。

## 端到端验收

扩展已有 Windows HTTPS/WSS 验收入口，使用真实产品路由、真实 Codex 子进程、隔离设备身份与临时数据库。覆盖：已连接未激活可见且不执行；显式激活到命令就绪；hello 延迟与超时恢复；旧协议错误终态不被放宽；总期限耗尽和会话关闭不误杀有效执行；撤销/收尾/重新选择；0.1.45 解包 EXE 的连接恢复、幂等与进程树回收。前端尽可能以真实浏览器到隔离服务验证启用路径；无法执行的验收须明确报告。

## 端到端定位补充：首次启用后的目录同步闭环

真实浏览器已登录且启用 API 返回成功、Agent 已命令就绪时，页面仍没有项目。核对发现 `_build_snapshot_observer` 仅提交 `accept_snapshot`，没有向既有浏览器总线发布 workspace.snapshot。现有 workspace.snapshot 是账号完整集合，不能发送单台主机集合而覆盖其它主机。

实施：将初始浏览器目录读取收敛到 CodexControlRuntime 的同一只读方法；数据库提交完成后通过已有 browser_event_hub 发布账号级完整工作区快照，初始连接也复用相同读取。前端任务首页区分“有效主机暂时没有项目”和错误路由；显式无效项目仍保留错误。主机重命名后重新读取同一实时投影，避免持久化元数据响应覆盖连接观测。新增 connected 字段的运行时严格白名单也完整接线。此组只改服务端和前端，不改变 Agent 线上协议。

## 实施结果

### 最终代码执行链路

网页设置「使用这台电脑」→ session.selectHost 单一 action → GET/PUT active-host（保留 CAS、draining 与许可到期规则）→ Agent 下一次续期获得执行资格 → 重建需要启动的本机执行进程并同步快照 → 服务端提交工作区目录 → browser_event_hub 发布账号完整 workspace.snapshot → 前端原有事件校验、reducer 更新唯一投影 → 项目可选择、任务页可进入。

网络恢复仍只有 Agent 连接循环拥有重试权。票据、WebSocket、hello、首次许可共享父级建链期限；普通传输失败及父级 deadline 只清理连接，执行是否保留继续由连续性协商、有效许可及进程健康共同决定。授权/协议终态不放宽。不存在后台第二套连接器或浏览器轮询补丁。

### 修改清单

| 范围 | 文件 | 具体结果 |
|---|---|---|
| Hello 合同 | `src/core/codex_contract/codex_runtime_contract.py`、`src/infrastructure/settings/raw_application_settings.py`、基础 TOML | 独立 hello 预算 10 秒，不再复用命令 ACK 的 5 秒 |
| 服务端连接入口 | `src/api/endpoint_codex_agent/route_codex_agent_connect.py` | watchdog 用 1013 + hello_timeout；快照提交后发布既有工作区事件 |
| 连接与执行 | `src/infrastructure/codex_agent/agent_control_channel.py` | 保留允许列表内关闭原因；hello/许可等待同时观察会话结束；父级取消的期限异常按传输恢复；无执行实例时不重复制造停止记录；终态诊断区分撤销与执行失败 |
| Agent 配置 | `src/infrastructure/codex_agent/agent_configuration.py` | hello/首次许可等待预算显式配置，仍受建链总期限约束 |
| 会话错误 | `src/infrastructure/codex/codex_connection_session.py` | 保留阶段和稳定原因码，传递给唯一重试决策 |
| 本机入口 | `src/infrastructure/codex_agent/app_server_process_supervisor.py` | 现有 resolve_command 在 Windows PATH 缺失时识别当前用户标准 npm 安装的 x64 Codex 原生入口；显式路径和版本校验不放宽 |
| 本机展示 | `src/infrastructure/codex_agent/agent_settings_ui.py` | inactive_host 显示「已连接，待启用」，明确指向网页启用操作 |
| 连接投影 | `src/core/codex_contract/host_contract.py`、`realtime_event_contract.py`、`route_codex_host.py`、`route_codex_realtime.py` | 增加从 presence 派生的 connected；维持 status 原有执行准入含义；初始快照和增量消息一致 |
| 目录总线 | `src/infrastructure/codex/codex_control_runtime.py` | 初始连接和后续快照复用 load_authority_snapshot；提交后发布账号完整目录，避免单主机覆盖其它主机 |
| 前端合同 | `app/types/codex-host.ts`、`codex-realtime.ts`、`app/utils/codex-event-validator.ts`、`codex-event-reducer.ts` | connected 的类型、严格字段白名单、校验、reducer 全部接线；不增加旧格式分支 |
| 前端启用与展示 | `app/pages/codex/settings/index.vue`、`app/components/codex/CodexHostBadge.vue` | 独立启用按钮、启用中/错误反馈、连接数、浏览器实时连接与 Agent 状态区分 |
| 前端生命周期 | `app/stores/codex-session.ts`、`codex-devices.ts`、`CodexProjectRail.vue`、`CodexMobileRemoteNavigator.vue`、`app/pages/codex/tasks/index.vue` | 同主机选择 singleflight、不同选择取消旧任务、重置回收；选择失败不导航；重命名后读取唯一实时投影；有效主机尚无项目时使用正常空状态，显式错误路由仍报错 |
| 发布入口 | `scripts/codex/build_internal_production_agent_installer.ps1`、`internal_release_evidence.py` | 同一入口生成五文件；记录实际源码、MSI、EXE、五个载荷哈希；附加验收时检查二进制哈希和解包文件一致；校验和覆盖其余四文件 |
| 发布元数据 | 基础和生产 `codex_control_runtime` TOML | 版本、下载 URL、manifest URL、MSI SHA256、父提交 revision 一起切换 0.1.45 |
| 端到端入口 | `scripts/codex/acceptance/windows_connection.py`、`connection_lifecycle.py`、`browser_task.py`、前端 `scripts/acceptance/codex-browser-task.cjs` | 真实 HTTPS/WSS、真实 CLI、生产 Nuxt 与浏览器；隔离身份/目录/数据库；故障注入和所有自建进程随验收结束回收 |
| 参数证据 | `scripts/codex/autotuner/connection/handshake_candidates.toml` | 复用现有 autotuner；比较 5/10 秒，记录失败与通过结果，未改其它网络参数 |

### 已完成的端到端证据

- 源码：`test-results/connection-0.1.45/source-lifecycle.json`。已连接未激活不可执行、真实启用 API、hello 超时可重试、6 秒延迟、父级总期限恢复均通过。
- 参数：`test-results/connection-0.1.45/handshake-tuning-r2` 保存 5 秒候选拒绝 6 秒 hello 的失败证据；`handshake-tuning-r3/report.json` 中两轮 10 秒候选恢复为 7.078 秒、7.437 秒，执行误停 0。先建立一次正常续期再注入延迟；此前未建立稳定续期的场景恢复 11.672 秒，也保留在 r2，未伪装成满足 10 秒要求。样本量不足以证明生产 P95/P99/SLO。
- 浏览器：`test-results/connection-0.1.45/browser-activation-final-browser.json`。真实登录→唯一主机启用→工作区通过事件自动出现→选择项目→页面无错误→重命名后仍显示连接→移动视口显示正确，全部通过。截图为隔离源码 Agent；不是用户当前安装状态。
- 安装包：最终结果绑定 `build-evidence.json` 的 `extracted_binary_e2e.executable_sha256`；涵盖 520/522、新票据、未激活到启用、6 秒 hello、父级总期限、doctor、单实例锁、崩溃回收原子进程树。父级期限场景额外要求日志明确出现 `reason_code=attempt_timeout`，不能以更早的 HTTP 读取超时冒充该验收。
- 没有运行单元、回归或覆盖率测试；执行了端到端验收、生产前端构建和编译类型检查。

### 发布与使用

最终版本固定 0.1.45，不创建 0.1.44。版本目录只放 `CodexRemoteAgent.msi`、`internal-release.json`、`SHA256SUMS.json`、`build-evidence.json`、`source-files.sha256.json`。旧的未发布中间构建仅保存在忽略的 `test-results/connection-0.1.45/superseded-build`，不进入发布仓库。

由用户提交前后端源码、手动发布 v0.1.45 五个附件及更新服务器。前后端应一起更新，因为 connected 是本次完整合同的一部分；随后安装新 Agent。保留已有效绑定的设备，无需反复撤销、重装或生成新身份。进入电脑设置，点击对应电脑「使用这台电脑」，等待工作区同步；有旧主机收尾时继续遵守原执行许可期限。

### 未实施与证据边界

1. 不自动改 Cloudflare、DNS、系统代理、TLS 校验或服务器配置。此前公网边缘路径确有超时，而源站对照正常；本轮代码修复不能保证公共网络不再中断。实际公网连接须在用户部署后确认。
2. 不增加 worker/副本、不取消执行许可、不添加第二套认证或重试入口。当前证据不支持这些改动，且会破坏连接归属或执行唯一性。
3. 本轮没有重新运行 12 小时长测，也没有执行完整 Redis/PostgreSQL/Cloudflare/Windows 休眠故障矩阵。0.1.43 的长测结论不移植到 0.1.45；自动调参报告没有将候选晋升为生产 SLO 已达标。
4. 没有覆盖安装用户当前的 0.1.43，没有推送仓库、部署服务器或创建线上 Release。最终 EXE 验收使用 MSI 解包文件和隔离配置。签名方式保持现有内部手动分发方式。
5. 来源清单保存构建时实际文件字节及父提交、dirty 状态；它不是“仓库已提交且干净”的声明。最终文件哈希以发布目录中的 SHA256SUMS.json 为准。


### 最终构建标识

- MSI：`0.1.45`，`33284096` 字节，SHA256 `df47e164a2ac187b366d6e523205be202ef466dbb05a84bd0707075ba64c7c09`。
- 解包 EXE SHA256：`6bb6455c0ab147e1e70ea4cb07bb1e88fe0c634860850f230354f69dfafbdf50`；Windows 文件资源为 `0.1.45.0`。
- 最终安装包验收记录：`test-results/connection-0.1.45/extracted-binary-final.json`。
- 前端生产构建：`typescript-web-nuxt/test-results/connection-0.1.45/build-final-r3.log`；类型检查：`typecheck-final.log`，退出码 0。

最终安装包 9 项端到端验收全部通过，完成时间：2026-10-25T05:47:45.375365+00:00。验收 EXE 哈希与最终 MSI 载荷一致，五个载荷逐一匹配；发布目录恰好五个文件，四项 SHA256 校验和全部一致，基础/生产版本及下载校验值与最终 manifest 一致。未创建 0.1.44。
