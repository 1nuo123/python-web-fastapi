# Codex 远程控制 Phase 2 架构决策记录

基线：Codex CLI / App Server `0.145.0`，2026-07-31。

## ADR-002：App Server 使用 stdio，Agent 对外使用 WSS

- 状态：已接受并实现。
- 决策：Windows Agent 启动 `codex app-server --stdio`，通过单写者 JSONL 客户端关联 RPC；App Server 不监听 LAN 或公网端口。Agent 主动连接 FastAPI 的 `/internal/codex-agents/connect`。
- 原因：保留当前 Windows 用户的 Codex 身份、工作区权限与配置，同时避免暴露原始 JSON-RPC。

## ADR-005：Agent 设备认证与用户认证分离

- 状态：已接受并实现。
- 决策：v2 Agent 先以 current-user DPAPI 保护的 Ed25519 私钥签署一次性 challenge，再用单次 WSS ticket 建连；服务端只保存公钥、fingerprint、版本与撤销状态。旧设备 bearer 仅保留在 v1 有界迁移路径，普通用户 JWT 不能进入 Agent 验证链。
- 边界：ticket、设备 key 与 hello 都绑定唯一 `host_id + owner_subject_id`；snapshot、heartbeat 和 presence renew 必须再次匹配该 host 与 revocation generation。

## ADR-007：Windows Agent 重启不承诺活动 turn 恢复

- 状态：已接受并实现。
- 决策：FastAPI/WSS 短暂中断不停止仍存活的本地 App Server；Agent 重连先发送 hello，再发送 snapshot 和有界缓冲事件。Agent 进程重启时，journal 中非终态 `executing/accepted` command 必须收敛为 `unknown` 且 `recovery_required=true`；App Server 代次变化后旧 approval 与活动调用不得伪装为可继续。

## ADR-011：长期通道独立于单操作流式处理器

- 状态：已接受并实现。
- 决策：复用强类型帧、容量、frame 上限和慢消费者原则，但使用 `CodexDuplexConnectionSession`、`CodexConnectionRegistry` 和 `CodexHostActor`。现有有限时长 `WebSocketSessionHandler` 未加入 Agent 协议分支。

## ADR-012：本地 command journal 阻止重复副作用

- 状态：已接受并实现。
- 决策：控制面先提交固定 `operation_id + command_id + request_digest`，Agent 在调用 App Server 前写入 SQLite journal。重复的相同命令回放已保存状态；同 command id 不同 digest 被拒绝；结果未知的 executing 命令返回 `unknown/recovery_required`，不再次执行 `thread/start` 或 `turn/start`。

## ADR-013：审批决定与加密 command outbox 同事务

- 状态：已接受并实现。
- 决策：审批 claim、稳定 operation 和 AES-GCM 加密 command outbox 在同一 PostgreSQL UnitOfWork 提交，提交后才唤醒 dispatcher；Redis 只承载路由通知，不保存命令明文或事实状态。
- ACK 语义：对 `approval.decision`，v2 `executing` 表示 Agent 已应用审批副作用，因此控制面可把 approval 标记为 applied；该语义不代表任意 thread/turn command 已完成。

## 兼容性事实

- 真实通知 envelope 包含可选 `emittedAtMs`，客户端契约已显式建模。
- Windows 上显式解析 npm `codex.cmd` 为 Node.js 入口，避免 `CreateProcess` 误选 PATH 后方的桌面内置旧版本。
- 真实探针覆盖 initialize、model/list、thread/list/start/read/delete、turn/start 与 turn/completed；探针 thread 最终删除。
