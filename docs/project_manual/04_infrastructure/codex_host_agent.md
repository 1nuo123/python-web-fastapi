# Windows Codex Host Agent

## 本地 Docker 启动流程

`0.145.0` 是仓库保留的历史审核基线，不是运行时最高版本限制。Agent 启动后上报本机实际 Codex 版本，并由 App Server capability probe 决定 `compatible`、`read_only` 或 `blocked`。

1. 后端目录执行 `docker compose up -d`，确认 `app`、`postgres`、`redis`、`rabbitmq` 均为 healthy。
2. 前端目录执行 `docker compose up -d`，确认 `frontend` 为 healthy，浏览器打开 `http://127.0.0.1:3000`。
3. 运行 `codex --version` 记录实际版本；普通版本升级无需修改 Remote。未知版本会先执行隔离 capability probe。
4. 首次绑定或正式撤销后重新绑定时运行 `./scripts/codex/setup_local_agent.ps1`；不要手工把旧 `credential_id` 改成 `key_id`。
5. 保持 Agent 的 `run` 命令持续运行，电脑状态变为“在线”后才能创建任务。

服务就绪检查使用 `http://127.0.0.1:8000/health/ready`；`/health` 不是本项目路由，返回 404 不表示容器故障。批准设备时若页面显示“服务器内部错误”并提供 `request_id`，先查看后端日志中的同一 `request_id`，不要重复点击批准；当前版本已修复新主机批准时 PostgreSQL 外键写入顺序问题，需先重建 `app` 容器再重试。

## 本地文件与凭据

- 配置建议：`%LOCALAPPDATA%\CodexRemoteAgent\agent.toml`。
- 状态账本：配置中的 `agent.state_database`，默认 `%LOCALAPPDATA%\CodexRemoteAgent\state.sqlite`。
- v2 设备私钥：`keys/<key_id>.dpapi`，由 current-user DPAPI 加密并收紧当前用户 ACL；TOML 和控制面只保存 key id、公钥/fingerprint 与状态。
- v1 迁移凭据：仅在 `agent_schema_version = "1.0"` 的有界迁移配置中读取 Windows Credential Manager；v2 不再依赖长期 bearer。
- Agent 启动时通过 `icacls` 拒绝 Everyone/普通 Users 的写权限。工作区 root 必须是本地绝对路径，远端只能提交 workspace key。

最小配置结构：

```toml
[agent]
host_id = "<控制面分配的 host UUID>"
key_id = "<控制面激活的设备 key UUID>"
display_name = "ThinkPad"
control_plane_url = "wss://codex.example/internal/codex-agents/connect"
control_plane_api_url = "https://codex.example"
codex_binary = "codex"

[protocol]
agent_schema_version = "2.0"
expected_codex_version = "0.145.0" # legacy diagnostic field; no longer a hard runtime gate
app_server_schema_digest = "86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109"
allow_experimental_api = false

[app_server_security]
# 该策略由 Agent 强制注入，控制面与浏览器不得覆盖。
approval_policy = "untrusted"
approvals_reviewer = "user"
sandbox_mode = "workspace-write"

[[workspaces]]
key = "fastapi-work"
display_name = "FastAPI Backend"
root = "E:\\python_web_fastapi\\work"
allow_write = true
```

`app_server_security` 缺省时仍使用以上安全默认值。禁止改为 `never` 或
`danger-full-access`；Agent 会拒绝控制面在 thread/turn 命令中附带审批或沙箱覆盖。

## 启动与探针

### 首次绑定或重新绑定

日常使用不需要反复输入完整 `setup` 命令。首次绑定或正式撤销后重新绑定时，在仓库根目录运行一次：

```powershell
.\scripts\codex\setup_local_agent.ps1
```

脚本使用本地 Docker API、前端验证页和当前实际 Codex。已知 manifest 才携带对应 schema digest；未知版本不复用旧 digest，启动后必须通过 capability probe。浏览器批准设备后，脚本会保存 v2 配置和 current-user DPAPI 设备私钥。

只有排查脚本或接入非默认环境时才需要使用完整命令：

```powershell
uv run python -m src.cli.run_codex_host_agent --config "$env:LOCALAPPDATA\CodexRemoteAgent\agent.toml" setup --api-url "http://127.0.0.1:8000" --websocket-url "ws://127.0.0.1:8000/internal/codex-agents/connect" --display-name "ThinkPad" --workspace-root "E:\python_web_fastapi\work" --workspace-key "fastapi-work" --workspace-name "FastAPI Backend"
```

### 日常启动

首次绑定完成后，日常只运行诊断和 Agent；无需再次运行 `setup`：

```powershell
uv run python -m src.cli.run_codex_host_agent --config "$env:LOCALAPPDATA\CodexRemoteAgent\agent.toml" doctor
uv run python -m src.cli.run_codex_host_agent --config "$env:LOCALAPPDATA\CodexRemoteAgent\agent.toml" run
```

`run` 是持续进程，终端必须保持运行。设置页显示电脑“在线”后，进入 Codex 任务页选择该电脑和工作区，创建任务并发送消息；控制面收到 `executing` ACK 后继续等待终态，完成后正文通过实时事件显示并可由 `thread.read` 在刷新后恢复。

### 独立 App Server 探针

```powershell
uv run python -m src.cli.probe_codex_app_server --codex-bin codex --workspace "E:\python_web_fastapi\work"
```

真实探针会创建一个只读 thread，发送明确禁止工具的固定消息，等待 `turn/completed`，最后删除该 thread。只验证无模型链路时增加 `--skip-turn`。

## 恢复与回滚

- FastAPI 短暂重启：不要重启 Agent/App Server；Agent 自动指数退避重连并上报 snapshot。
- ack 丢失：控制面只能使用数据库中的原 command id 重投；禁止生成新 command id。
- Agent 进程重启：journal 中非终态 `executing/accepted` command 统一收敛为 `unknown`、`recovery_required=true`，不自动重跑可能已产生副作用的 mutation。
- App Server 重启：旧 approval instance 失效并重建 snapshot，活动 turn 对外标记 unknown/interrupted。
- 回滚 Phase 2：先停止 Agent，再关闭 FastAPI 新操作入口；保留本地 `state.sqlite` 供原 command id 核对。不得删除 journal 后自动重试非幂等命令。

## 运行时与发布核对

- Python 运行依赖直接声明 `cryptography>=50.0.0` 与 `tuf>=6.0.0`；最终锁文件和 Docker 容器核对的 `cryptography` 版本为 `50.0.0`。
- Docker 生产镜像包含 `protocol/`，因此 App Server manifest、method catalog 与冻结 schema digest 在容器内可读取。
- JSON Schema bundle digest 为 `86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109`；TypeScript bundle digest 为 `125dea8051ad1d8ae9c9c527e30d1d6aada2965fd1e77771f7c18806c77a6724`。
重新绑定前先停止旧 Agent，并从设置页完成正式撤销，再删除旧配置并重新运行一键脚本。脚本不会删除密钥、数据库或服务端设备记录。

## 真实回归结果

### 环境与消息闭环

2026-08-08 的 `0.145.0` 运行记录保留为回归基线。后续验收应同时记录实际版本、可选 digest、capabilities 和 probe outcome；版本差异本身不再导致 BLOCKED。

浏览器任务 `019fe08e-2950-7e20-b377-0775243afcfd` 先后发送固定消息并收到 `REMOTE_CODEX_OK`、`REMOTE_CODEX_REGRESSION_OK`；刷新页面后两轮用户消息和 Agent 正文仍完整显示。对应 operation、command 和 outbox 均为 `completed`，首次投递成功，thread 最终为 `idle`。

### 自动化回归

- 后端离线全量：`981 passed, 1 deselected`。
- 后端真实依赖全量：`1137 passed`，覆盖率 `85.72830230993496%`，通过 85% 门禁。
- `uv run nox -s static`：compileall、Ruff、mypy、import-linter、Bandit、pip-audit、detect-secrets、锁文件和 Compose 校验全部通过。
- 前端 `pnpm verify`：Prettier、ESLint、typecheck、Vitest `142 passed`、覆盖率、Nuxt production build 和 Playwright `7 passed`。

### 已修复故障

控制面此前只接受旧 `accepted/completed/failed` ACK，把 v2 Agent 的 `executing` 错误解释为未确认，导致已经执行成功的 `thread.read` 在任务详情页表现为 500。当前实现以 `AgentCommandJournalState` 为协议事实，接受 `received/executing/accepted/completed/failed`，未知状态仍 fail-closed。

## 主机撤销与重新绑定

### 正式撤销流程

1. 在浏览器打开 `http://127.0.0.1:3000/codex/settings`，选择目标电脑并点击“撤销电脑”。
2. 输入当前登录账号的真实密码。前端显式申请用途为 `codex.host.revoke` 的一次性增强授权；高风险审批用途 `codex.high_risk_approval` 不能用于撤销主机。
3. 点击“确认撤销”。密码错误属于可恢复失败，错误会保留在当前弹窗内，修正密码后可直接重试。
4. 成功后电脑状态变为“已撤销”，重命名和再次撤销入口不可用；刷新页面后状态仍从服务端恢复。
5. 停止该电脑上仍在运行的旧 Agent。旧设备公钥已经失效，后续 challenge、一次性连接 ticket 和 WebSocket 重连均会被拒绝。

撤销请求必须携带登录访问令牌、主机当前 `version` 和一次性增强授权。增强授权与当前主体、`codex.host.revoke` 用途绑定且消费一次即失效；版本已变化时应刷新电脑列表后重新操作，不复用旧 grant。

### 数据保留语义

正式撤销是安全状态迁移，不是物理删除。后端在同一 UoW 事务中把主机标记为 `revoked`，并撤销该主机的全部设备公钥；事务提交后再关闭本实例连接并发布跨实例撤销信号。workspace、thread、operation 和审批审计继续保留，确保历史任务、审计和关联关系可追溯。

不要直接执行数据库 `DELETE`，也不要通过删除 `state.sqlite`、DPAPI 密钥文件或 `agent.toml` 冒充服务端撤销。这些本地操作不能替代服务端设备公钥失效，并可能破坏恢复与审计证据。没有历史关联但停留在 `enrolling` 的旧记录也应从设置页走同一正式撤销流程；过期 pending key 由授权清理用例收敛，不进行人工级联删除。

### 重新绑定流程

1. 确认旧主机已经显示“已撤销”，并停止旧 Agent 进程。
2. 删除旧 `agent.toml` 仅用于移除本地启动配置；不要复用旧 `host_id`、`key_id` 或私钥。
3. 运行 `./scripts/codex/setup_local_agent.ps1`，或使用上文完整 `setup` 命令创建新的 v2 设备授权。日常重新绑定优先使用一键脚本，不需要重复输入长命令。
4. 在浏览器核对显示名称和指纹后批准设备，随后运行 `doctor`。
5. `doctor` 通过后持续运行 `run`；新电脑显示“在线”后再创建任务。旧撤销记录继续保留，不会与新设备身份合并。

### 撤销失败排查

- “缺少访问令牌”：刷新登录会话后重试。`/auth/step-up` 是受保护接口，必须发送 bearer；不得把它加入公开接口清单。
- “增强验证失败”：当前密码不正确。留在弹窗内重新输入，不要删除设备记录或绕过增强授权。
- `412 Precondition Failed`：电脑版本已经变化，刷新设置页后使用新版本再次撤销。
- `403 Forbidden`：增强授权用途不匹配、已经消费或过期，重新输入密码签发新的 `codex.host.revoke` grant。
- `request_id` 已显示：使用同一标识检索后端日志，先确认 `/auth/step-up` 与 `/codex/hosts/{host_id}/revoke` 的实际状态，不重复提交未知结果。
