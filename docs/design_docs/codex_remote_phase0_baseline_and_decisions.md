# Codex 远程控制 Phase 0 基线与架构决策

> 状态：仓库实现与统一回归已完成。本文保留 2026-08-07 初始基线并回写 2026-08-08 最终源码事实；clean Windows、真实签名、生产灾备/容量、外部渗透和 canary 仍按未验收处理。

## 1. 当前、目标与迁移阶段对照

| 能力 | 当前源码事实 | 目标契约 | 迁移阶段 |
| --- | --- | --- | --- |
| Agent frame | v1/v2 独立 codec；v2 使用公共头字段 + 强类型 detail、累计 ACK、epoch/seq replay、gap 与分页 snapshot | 未知 schema/method 的 mutation fail-closed；v1 仅保留有界迁移 | Phase 1、Phase 2 |
| 浏览器 realtime | owner 隔离的 Redis cursor stream 为事实源，本地 hub 只负责 fan-out；gap 后读取 snapshot | opaque cursor、typed event detail、容量/TTL 与重复 event id 去重 | Phase 5、Phase 6 |
| Host HTTP | 已提供设备授权、challenge/ticket、列表、重命名、撤销、轮换与 presence/compatibility/doctor/update 状态 | PostgreSQL owner 事实 + Redis fresh lease，禁止只看 DB online | Phase 3、Phase 4、Phase 5 |
| Thread HTTP | list/create/read/resume/turn/steer/interrupt 已存在 | method catalog 驱动、capability 校验、稳定 operation/outbox 和 cursor 恢复 | Phase 1、Phase 5、Phase 6 |
| Approval HTTP | list/resolve 与脱敏审计已存在 | command/file-change/permissions 三类强类型 detail、代次与过期校验 | Phase 1、Phase 6 |
| PostgreSQL | 20 张表，含 9 张 Codex host/device/workspace/thread/operation/approval/outbox 表；Alembic head `202608081000` | operation、审批与加密 outbox 同事务，Redis 不承担事实状态 | Phase 3、Phase 5 |
| Agent 身份 | v2 Ed25519 公钥 + current-user DPAPI 私钥 + 单次 challenge/ticket；旧 bearer 限于 v1 迁移 | revoke generation 与 heartbeat/lease renew 持续校验 | Phase 3、Phase 4 |
| Agent 安装 | setup/doctor/run、PyInstaller one-folder、WiX per-user MSI 与托管签名 workflow 已入库 | clean Windows 安装、真实 Authenticode/TUF 元数据和回滚仍待外部验收 | Phase 4 |

## 2. 架构决策

### 2.1 ADR-001：App Server 只允许 Agent 本地 stdio

- 决策：唯一生产接入方式为当前 Windows 用户会话内的 `codex app-server --stdio`。
- 禁止：浏览器、FastAPI、公网网关或局域网直接连接 App Server；experimental App Server WebSocket 不进入生产拓扑。
- 原因：Codex 登录、工作区权限和本机执行边界属于当前 Windows 用户；原始 JSON-RPC 不是产品公共协议。
- 回滚：停用远程控制入口并停止 Agent，不改变本机 Codex 桌面或 CLI 配置。

### 2.2 ADR-002：设备身份采用 Ed25519 与 current-user DPAPI

- 决策：Agent 首次启动生成 Ed25519 key pair；私钥使用 current-user DPAPI 封装，服务端只持有公钥、版本、状态和审计字段。
- 轮换：新 key 先进入 pending，旧 key 完成签名证明并经用户确认后切换；宽限期结束撤销旧 key，不覆盖历史行。
- 丢失设备：用户从网站撤销 host 与全部 device key；旧私钥不能再换取 challenge 或 ticket。
- 重放：challenge nonce、canonical message、key version、host id 和过期时间共同签名；challenge 与 ticket 均单次消费。
- 禁止：把私钥、device code、签名材料写入 TOML、日志、数据库或二维码。

### 2.3 ADR-003：PostgreSQL operation/outbox 与 Redis presence/Streams

- 决策：PostgreSQL 是 operation、command outbox、host、workspace、thread index 和 audit 的事实源；Redis 只承载短期原子状态、presence lease、一次性 ticket 与有界 Streams。
- RabbitMQ 边界：RabbitMQ/Funboost 继续用于普通后台任务，不进入 Agent command、审批回复、delta 或浏览器 realtime 路径。
- 故障语义：Redis 丢失时设备临时离线、ticket/challenge 失效、浏览器通过 snapshot 恢复；不允许认证 fail-open。

### 2.4 ADR-004：Windows 使用 per-user MSI 与 Task Scheduler

- 决策：安装目标为当前用户目录，使用 Task Scheduler logon trigger 启动稳定 launcher。
- 不默认 LocalSystem：LocalSystem 不拥有用户的 Codex 登录、工作区 ACL、DPAPI user scope 或交互审批上下文；强行使用会扩大权限并破坏用户隔离。
- 禁止：保存 Windows 用户密码、要求管理员权限作为默认路径、在安装日志输出敏感材料。

### 2.5 ADR-005：Authenticode、TUF 与对象存储/CDN

- 决策：MSI/launcher 使用 Authenticode；Agent/Codex 制品通过 TUF 元数据解析并从 allowlist 对象存储或 CDN 下载。
- key custody：root 与 targets 采用阈值签名和离线/托管隔离；timestamp/snapshot 使用受限在线密钥；CI 只获得最小签名权限。
- 禁止：自研 TUF metadata parser、证书链算法、SHA-256 或回滚/freeze 状态机；禁止安装时下载未经 manifest 审核的 `latest`。

## 3. 统一基建复用审计

| 需求语义 | `rg` 源码命中 | 成熟候选 | 结论 | 第二使用方或协议无关 fixture | 旧实现退出条件 |
| --- | --- | --- | --- | --- | --- |
| sync/async Redis resource | `RedisCacheStore`、`RedisStreamStateStore` 各自 `Redis.from_url` | `redis-py` pool | `extract` | cache、stream、distributed state | 两个私有 pool owner 删除，生命周期只保留 shared resource |
| atomic state/script executor | cache、stream ticket、distributed lock | `redis-py` Lua/script | `extend` | enrollment 与 challenge/revocation | Codex 不持有通用 Lua executor |
| one-time ticket | `StreamAccessTicketService`、`CodexRealtimeTicketService` | 现有 stream ticket | `extend` | admin/task stream、browser、Agent | Codex ticket 摘要/签发/消费实现删除 |
| step-up grant | `CodexStepUpGrantService` 进程内字典 | generic ticket operation | `extract` | host revoke 与其他高风险操作 | Codex 进程内 grant 删除 |
| signature verifier | 无通用 verifier | `cryptography` Ed25519 | `extract` | Codex enrollment 与协议无关签名 fixture | Codex use case 不导入 `cryptography` |
| cursor/replay | `StreamStateStorePort`、memory/Redis/deferred stores | Redis Streams | `extend` | 普通 streaming 与 Codex events | 禁止第二个 cursor port/store/resource slot |
| async fenced lease | 同步 `DistributedLockProvider` | `redis-py` + 原子脚本；成熟库评估后定 | `extract` | presence 与协议无关 fixture | 同步 lock 保留原调用方，Codex 不拥有 lease 算法 |
| AEAD envelope | `KeyManagementService` | `cryptography` HKDF/AESGCM | `extract` | task/协议无关密文 fixture 与 Codex outbox | Codex 不直接调用 AESGCM |
| reliable outbox runner | `TaskExecutionOutboxPublisher` | 当前实现抽取 | `extract` | task outbox 与 Codex command outbox | task publisher 只保留业务 adapter |
| outbound HTTP | shared sync/async HTTP client 与 URL safety | 现有 `httpx` | `reuse` | 普通 outbound 与 artifact downloader | 禁止第二套 HTTP client |
| artifact release | 当前无实现 | `python-tuf`、PyInstaller、WiX、WinVerifyTrust | `extract` | Agent bundle、Codex bundle、fake third-party target | 业务 coordinator 不实现下载/验证/激活循环 |
| worktree | `AgentWorkspaceRegistry` 路径边界，无 worktree | 系统 Git CLI | `specific` | 仅 Phase 7 可选能力 | 默认关闭且 managed marker/containment 完整 |

禁止依赖方向：`src.infrastructure.distributed_state`、`streaming`、`concurrency`、`cryptography`、`outbox`、`artifact_release` 不得导入 `src.core.codex_contract`、`src.application.codex` 或 `src.infrastructure.codex`。

## 4. 生产实现职责 allowlist

| 职责 | 允许的生产 owner | 禁止平行实现 |
| --- | --- | --- |
| streaming state store | `MemoryStreamStateStore`、`RedisStreamStateStore`、`DeferredStreamStateStore` | 新 cursor store 或第二 resource slot |
| Redis client/pool | `SharedRedisResource` | cache、stream、Codex adapter 私建 client |
| ticket | `StreamAccessTicketService` + state store | Codex 专用 digest/store/service |
| sync distributed lock | 现有 `DistributedLockProvider` | 为迁移 fenced lease 破坏同步调用方 |
| async fenced lease | 通用 concurrency adapter | Codex presence 私有 lease 算法 |
| cipher | 通用 cryptography adapter + `KeyManagementService` | Codex 直接 AESGCM/HKDF |
| outbox runner | `ReliableOutboxRunner` | task/Codex 各自后台循环 |
| HTTP client | shared HTTP resource | downloader 私建 `httpx` client |
| artifact downloader | 通用 artifact release adapter | Agent/Codex coordinator 自行下载 |

边界测试必须使用 AST/import graph 与装配入口枚举检测职责、直接 client 构造和重复 resource slot；仅按类名字符串匹配不构成门禁。

## 5. Redis 连接与生命周期结果

| 调用方 | 最终连接 | 同步边界 | shutdown owner | 已冻结约束 |
| --- | --- | --- | --- | --- |
| cache | 注入 `SharedRedisResource` sync client | 同步 | shared runtime | store 不关闭 client |
| streaming | 注入 `SharedRedisResource` async client | 异步 | shared runtime | v1/v2 共用现有 state store 与 resource slot |
| atomic state / fenced lease | 注入同一 shared async client | 异步 | shared runtime | adapter 不创建或关闭 client |
| distributed lock | 通过共享 cache/Redis 能力装配 | 同步 | shared runtime | 保留既有同步契约 |

最终生产源码中的两个 `Redis.from_url` 命中都位于 `SharedRedisResource`，分别创建 sync/async client；cache、stream、atomic state、fenced lease 与 Codex adapter 均不拥有连接关闭权。

## 6. 进程局部事实与离线幂等基线

- `CodexPairingService` 与旧 credential 仅服务 v1 有界迁移；v2 enrollment/challenge/revocation 使用共享 Redis atomic state。
- 生产 step-up 使用 `StreamStepUpGrantAdapter` 与通用单次 ticket；旧 `CodexStepUpGrantService` 不在最终 runtime 装配路径。
- `CodexConnectionRegistry`：只知道本实例 socket 与递增 epoch。
- `CodexBrowserEventHub`：只保存本实例浏览器 fan-out 队列，持久 replay/cursor 由 `CodexRealtimeStreamAdapter` 写入现有 stream state store。
- socket registry 与 fan-out 仍不得被文档、UI 或指标描述为 distributed；跨实例 route/presence/event 分别由 PG outbox、Redis fenced lease 和 Redis cursor stream 承担。
- host 离线时，原 `Idempotency-Key` 重试必须读取同一 PostgreSQL operation，保持稳定 `operation_id + command_id + request_digest`；只允许增加 `dispatch_attempt`，禁止生成新 command id 重试未知 mutation。

## 7. 威胁模型

| 威胁 | 主要控制 | 失败语义 |
| --- | --- | --- |
| user_code/device_code 被盗 | 短 TTL、摘要存储、用户/IP 限流、指纹核对、一次消费 | 拒绝或过期，不创建最终 owner |
| 二维码泄露 | 只承载验证地址和 user_code，不承载 device_code/私钥 | 用户可拒绝，过期后不可恢复 |
| 签名重放 | nonce、host/key/version/expiry canonical message、原子消费 | fail-closed 并记录安全事件 |
| Redis 劫持/丢失 | TLS/认证、shared resource、业务 Lua、PG 事实源 | 设备离线，ticket/challenge 失效 |
| 旧 key | version、grace window、revocation generation、heartbeat 校验 | 不能申请新 ticket，主动断开 |
| 恶意 workspace path | canonical path、realpath、symlink/junction containment、workspace key | 命令拒绝，不回显本机路径 |
| 事件泄露 | owner 写入/读取双校验、opaque cursor、payload 脱敏 | 拒绝读取并记录审计 |
| 更新供应链 | TUF、Authenticode、digest、allowlist、rollback/freeze 防护 | 不激活并恢复 last-known-good |
| 租户越权 | 每条 host/workspace/thread/operation/approval 查询校验 owner | 统一返回无权限/不存在，不泄露实体 |

## 8. Agent 当前启动条件

仓库验证路径仍需 Python 3.11+、`uv`、已登录且版本匹配的 Codex CLI、控制面 HTTPS/WSS URL 与允许工作区。首次 `setup` 自动生成 Ed25519 key、完成设备授权、用 DPAPI 保存私钥并写入不含密钥材料的 TOML；`doctor` 覆盖版本、schema digest、登录、initialize、网络、时钟、DPAPI、SQLite 与 workspace policy。PyInstaller/WiX 源码已入库，但无 Python 的 clean Windows 最终用户路径尚未完成外部 VM 验收。

## 9. 初始 SLI/SLO 与隐私分类

### 9.1 初始 SLI/SLO

| 指标 | 初始验收值 |
| --- | --- |
| heartbeat 到 online | p95 ≤ 3 秒 |
| operation commit 到 durable ACK | 同区 p95 ≤ 1 秒 |
| 30 秒断线后的 replay 恢复 | p95 ≤ 5 秒 |
| 首 token | 记录 p50/p95；Phase 0 不预设未经测量的发布阈值 |
| event gap | 正常运行 0；trim/故障必须 snapshot |
| 审批往返 | 记录 p50/p95 与过期率 |
| Agent/App Server 崩溃恢复 | 不重复 mutation；unknown 必须可见并可核对 |

### 9.2 隐私数据分类与保留

| 存储 | 允许字段 | 禁止字段 | 初始保留策略 |
| --- | --- | --- | --- |
| PostgreSQL | IDs、owner、状态、digest、公钥、脱敏摘要、审计时间 | prompt/delta、私钥、device code、原始命令/diff | operation/audit 按产品审计期；ciphertext 由后续策略清理 |
| Redis | digest、nonce、ticket binding、presence、command reference、typed event | 私钥、长期 bearer、完整 prompt/命令明文 | 全部 TTL/有界 trim |
| Agent SQLite | command identity/state、epoch/ACK、必要恢复元数据 | prompt/delta 正文、私钥 | 有界清理；卸载/账户删除策略在 Phase 7 固化 |
| 日志/指标 | request/operation/command/epoch、结果码、计数、耗时 | token、code、signature、private key、prompt/delta、绝对路径 | 按现有日志策略；高基数 owner/host/thread 不作指标标签 |
| 安装遥测 | 版本、channel、结果码、耗时、签名/更新结果 | 用户文件、Codex 内容、凭据 | 默认最小化并提供 opt-in/opt-out |

## 10. Phase 0 证据状态

2026-08-08 最终仓库证据：

- JSON Schema bundle digest：`86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109`；TypeScript bundle digest：`125dea8051ad1d8ae9c9c527e30d1d6aada2965fd1e77771f7c18806c77a6724`。
- `uv run nox -s static` 通过；offline 为 `926 passed, 5 warnings`；regression 为 `1077 passed, 241 warnings`，合并覆盖率 `85.35257049984318%`。
- 前端 `pnpm verify`、Nuxt production build 通过；Vitest 为 `28 files / 138 tests`，Playwright 为 `7 passed`。
- `docker compose -f compose.yml up -d --build` 成功；app、PostgreSQL、Redis、RabbitMQ healthy，Alembic head `202608081000`，容器 `cryptography` 为 `50.0.0`，镜像包含 `protocol/`。
- 未取得的 clean Windows、真实生产签名、第二台 Windows 电脑、外部渗透、CDN/TUF 故障、生产容量/soak/canary 与 30 天 v1 使用率证据继续保持未完成，不以本地替身改写。
