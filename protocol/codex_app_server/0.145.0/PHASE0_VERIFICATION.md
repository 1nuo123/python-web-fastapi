# Codex Remote Phase 0 核心验证记录

初始执行日期：2026-07-31  
最终回归日期：2026-08-08  
目标CLI：`codex-cli 0.145.0`

## 结论

本轮要求的四项核心验证均已通过：

1. 长期双向连接使用独立 `CodexDuplexConnectionSession`，支持同一连接连续处理多类消息、单写者发送、有界队列、frame限制、慢消费者失败和显式停机；不复用单操作 `WebSocketSessionHandler` 的300秒执行语义。
2. Agent command journal 使用SQLite持久化，在调用App Server前登记命令；相同 `command_id + request_digest` 跨连接与进程重启回放原状态/结果，不再次执行。崩溃时停在 `executing` 的命令保持未知并等待核对，不自动重跑。
3. Agent内部HTTP使用 `Authorization: CodexAgent <token>`，现有用户Bearer解析器不会提取；Agent WebSocket虽使用Bearer，但必须通过专用设备凭据验证器，用户JWT不能通过。
4. 本机0.145.0生成schema确认稳定审批为三个App Server发起的server request；客户端回复原JSON-RPC id后不期待第二确认response。

## 冻结结果

- Approval schema digest：`8d105abcf752cc043509651d78f3d1b6d89a71779a353066e0dcaaa363b041bf`
- `item/commandExecution/requestApproval` → response required: `decision`
- `item/fileChange/requestApproval` → response required: `decision`
- `item/permissions/requestApproval` → response required: `permissions`
- Manifest：[manifest.json](manifest.json)
- Generated schemas：[json-schema](json-schema)
- Generated TypeScript：[typescript](typescript)
- JSON Schema bundle：273 files，`86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109`
- TypeScript bundle：617 files，`125dea8051ad1d8ae9c9c527e30d1d6aada2965fd1e77771f7c18806c77a6724`

## 验证命令与结果

- `uv run nox -s static`：通过，静态证据为 0 warnings。
- `uv run nox -s offline`：`925 passed, 1 deselected, 5 warnings`。
- `uv run nox -s regression`：`1076 passed, 241 warnings`；合并覆盖率 `85.35500427715996%`，Auth `93.33%`、Security `91.16%`、Task `92.35%`、Persistence `91.08%`。
- 最终增量显式 mypy：5 个文件均为 `Success: no issues found`。
- 前端 `pnpm verify`、Nuxt production build 通过；Vitest `28 files / 138 tests`，Playwright `7 passed`，statement coverage `73.42%`、branch coverage `65.98%`。
- `docker compose -f compose.yml up -d --build`：成功；app、PostgreSQL、Redis、RabbitMQ 均 healthy，Alembic head 为 `202608081000`，容器 `cryptography` 为 `50.0.0`。
- 生产 Docker image 显式复制 `protocol/`，容器内使用本页记录的 manifest 与两项 bundle digest。

探针启动子Codex进程时会移除父Codex桌面进程注入的嵌套运行变量，但保留 `CODEX_HOME`。否则当前桌面会把npm 0.145.0入口重定向到内置 `0.144.0-alpha.4`，导致冻结错误schema。
