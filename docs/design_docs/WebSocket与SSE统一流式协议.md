# WebSocket 与 SSE 统一流式协议

## 1. 适用范围

本文冻结当前统一流式基建的公开语义。业务模块只实现一个
`StreamEventSourcePort[TCommand, TDetail]`，再通过
`StreamOperationBindingEnvelope` 声明非流式 HTTP、SSE 和 WebSocket 交付。
传输适配器不得复制业务计算、授权判断或错误映射。

测试专用的 `/testing/stream/*` 路径不属于生产 API。当前生产绑定是管理员任务执行观察流：

- `POST /admin/tasks/executions/watch/batch`：有界非流式聚合；
- `POST /admin/tasks/executions/watch/stream`：Bearer SSE；
- `/admin/tasks/executions/watch/ws`：WebSocket；
- `/admin/tasks/executions/watch/ticket`：仅在 `require_browser_ticket=true` 时注册。

部署设置了 `runtime.web.api_prefix` 时，上述路径统一带该前缀。

## 2. 三种交付的一致性

| 交付 | 输入 | 输出 | 适用场景 |
| --- | --- | --- | --- |
| 非流式 HTTP | 强类型命令 JSON | 现有 `ResponseEnvelope` 包裹的有界 `StreamBatchEnvelope` | 短任务、兼容普通 HTTP 客户端 |
| SSE | 同一强类型命令 | 标准 `text/event-stream`，每个数据帧携带完整事件信封 | 服务端单向增量推送、自动重连 |
| WebSocket | 新订阅首帧 `subscribe`，新连接恢复首帧 `resume` | 完整事件信封 JSON 文本帧，并支持双向控制 | 取消、有限窗口恢复、探活等双向场景 |

三种交付共享同一编排器，均先产生 `stream_started`，随后产生业务事件，最后产生
`stream_completed` 或 `stream_fault`。非流式交付只是有界收集这些事件，不是另一套业务实现。

## 3. 事件契约

公开契约统一采用“公共头字段 + 强类型扩展字段”。事件信封结构如下：

```json
{
  "envelope_kind": "stream_event_envelope",
  "schema_version": "1.0",
  "header": {
    "stream_id": "stream-1",
    "event_id": "event-1",
    "sequence": 0,
    "event_kind": "stream_started",
    "schema_version": "1.0",
    "request_id": "request-1",
    "trace_id": null,
    "emitted_at": "2026-07-30T10:00:00Z"
  },
  "detail": {
    "kind": "stream_started",
    "schema_version": "1.0",
    "operation_name": "report_generate",
    "transport": "sse",
    "resumable": true
  }
}
```

必须满足：

- `header.event_kind == detail.kind`；
- 信封、公共头和扩展字段的 `schema_version` 一致；
- `detail` 是业务显式声明的 Pydantic 判别联合，`extra="forbid"`；
- 基础设施只提供 `stream_started`、`stream_progress`、`stream_heartbeat`、
  `stream_completed`、`stream_fault`；业务事件必须由业务模块定义强类型模型。

### 3.1 顺序与交付保证

- `sequence` 在单个 `stream_id` 内从 `0` 开始严格递增；注释心跳不占用序号。
- 实时发送为至多一次，不承诺断线期间无损交付。
- Redis 模式保存带 TTL 和最大事件数的有限窗口；它提供窗口内重放，不是持久消息队列。
- 恢复请求绑定 `stream_id`、`last_event_id`、主体和操作。过期、越权、跨操作或伪造事件 ID
  均返回 `system.stream.replay_unavailable`。

## 4. 非流式 HTTP

非流式交付调用同一 `collect()`，同时执行三重限制：

- `collection_max_events`：最大事件数；
- `collection_max_bytes`：序列化后最大总字节数；
- `collection_timeout_seconds`：最大聚合时间。

任一限制命中即终止生产者、关闭异步生成器并返回稳定 HTTP 错误，不允许把无界流完整读入内存。
聚合结果保留事件顺序、最后序号、事件数、总字节数和终止原因。

## 5. SSE

### 5.1 帧映射与响应头

每个业务事件映射为：

```text
id: event-1
event: stream_started
data: {"envelope_kind":"stream_event_envelope","schema_version":"1.0","header":{...},"detail":{...}}
retry: 3000
```

响应固定包含：

- `Content-Type: text/event-stream; charset=utf-8`；
- `Cache-Control: no-cache, no-transform`；
- `X-Accel-Buffering: no`。

心跳使用 `: heartbeat` 注释帧，由 `sse_heartbeat_seconds` 控制，不进入业务事件联合，
也不改变 `sequence`。恢复时同时提供 `Last-Event-ID` 请求头和 `stream_id` 查询参数；缺少任意一项
都会被拒绝。

### 5.2 浏览器认证模式

`SseDeliveryDetail.mode` 是封闭集合：

- `bearer_post`：只注册 POST，浏览器使用 `fetch` streaming 并在
  `Authorization: Bearer ...` 中发送长期凭证；
- `ticket_get`：只注册 GET，native `EventSource` 必须原子消费短期单次票据；
- `dual`：同时允许 Bearer POST 与票据 GET。

native `EventSource` 不能设置自定义 Authorization 头，因此先调用业务操作提供的已认证票据签发
入口，再创建 GET 连接。GET 查询参数为 `ticket`、`subject_id` 和 URL 编码后的 `command` JSON；
票据只在签发响应出现一次，存储侧仅保存 SHA-256 摘要，并绑定主体、操作、到期时间和可选客户端 IP。
重复消费或 Redis 校验失败按 fail-closed 处理，返回 `system.stream.ticket_invalid`。禁止把长期 JWT
放入 URL。

```javascript
const ticketResponse = await fetch("/reports/generate/ticket", {
  method: "POST",
  headers: { Authorization: `Bearer ${accessToken}` },
});
const ticketEnvelope = await ticketResponse.json();
const query = new URLSearchParams({
  ticket: ticketEnvelope.detail.ticket,
  subject_id: ticketEnvelope.header.subject_id,
  command: JSON.stringify({
    kind: "report_generate_command",
    schema_version: "1.0",
    report_id: "r-1",
  }),
});
const source = new EventSource(`/reports/generate/stream?${query}`);
```

票据签发路由属于业务认证边界；绑定 native EventSource 时，签发路由与
`FastApiStreamRouteComposer` 必须复用同一个 `StreamAccessTicketService`。

## 6. WebSocket

### 6.1 建连前准入

`WebSocketConnectionGuard` 在 `accept()` 前依次执行 Origin、凭证、授权、IP 封禁、限流和四级会话
配额校验。WebSocket 不受 CORS 保护，浏览器发来的 `Origin` 必须在 `allowed_origins` 中。

非浏览器客户端可发送 Bearer 头。生产配置 `require_browser_ticket=true` 时，只要存在浏览器
`Origin` 就必须使用短期单次票据；URL 中不得携带长期 JWT。票据消费失败不会降级为匿名连接。

### 6.2 客户端控制帧

新订阅连接的首个文本帧必须是 `subscribe`；新连接恢复时，首帧可以是 `resume`。两者都必须携带
完整外层控制信封。`subscribe` 示例：

```json
{
  "envelope_kind": "stream_client_control_envelope",
  "schema_version": "1.0",
  "header": {
    "kind": "stream_client_control_header",
    "schema_version": "1.0",
    "control_kind": "subscribe"
  },
  "detail": {
    "kind": "subscribe",
    "schema_version": "1.0",
    "command": {
      "kind": "report_generate_command",
      "schema_version": "1.0",
      "report_id": "r-1"
    }
  }
}
```

订阅运行中只支持：

- `cancel`：设置取消信号，并以 `stream_fault/client_cancelled` 收束；
- `ping`：携带 `nonce`，服务端返回强类型 `{"event":"pong","nonce":"..."}`。

`resume` 只允许作为新连接首帧，携带 `stream_id` 和 `last_event_id`，重放鉴权后的有限窗口后正常关闭。
运行中的连接发送 `resume`、重复 `subscribe` 或其他非法状态转换时，服务端发送 `stream_fault`，随后
以 `1008` 关闭。

只允许 UTF-8 JSON 文本帧。二进制帧、额外字段、头与扩展 kind 不一致、未知控制类型均被拒绝。
凭证存在到期时间时，连接以该时间作为硬截止时间，不因 WebSocket 已建立而无限续期。

### 6.3 关闭码

| 关闭码 | 稳定语义 |
| --- | --- |
| `1000` | 正常完成 |
| `1001` | 服务重启或排空 |
| `1008` | Origin、认证、授权、控制契约或其他策略拒绝 |
| `1009` | 控制消息超过 `websocket_max_message_bytes` |
| `1011` | 不可恢复内部错误 |
| `1013` | 慢消费者、发送超时或容量过载 |

## 7. 背压、取消与资源回收

- 每个会话使用 `queue_capacity` 有界队列；生产者在 `send_timeout_seconds` 内无法入队时产生
  `system.stream.slow_consumer`，不静默丢弃事件。
- `max_duration_seconds` 是会话硬上限，`max_event_bytes` 是单事件硬上限。
- WebSocket 发送端、控制接收端和凭证截止任务任一结束后，其他任务都会取消并统一回收。
- `asyncio.CancelledError` 继续传播；事件源、SSE、WebSocket 和重放生成器都在 `finally` 中执行
  `aclose()`；会话租约幂等释放。
- Redis 在已建连实时发送期间写重放窗口失败时记录中文告警并关闭该会话的恢复能力，实时事件继续；
  票据消费失败则始终 fail-closed。

## 8. 生命周期、观测与部署

请求作用域、耗时和访问日志使用纯 ASGI 中间件覆盖 HTTP、SSE 与 WebSocket 的完整生命周期。
指标只使用受控的 `transport`、`outcome`、`reason`、`event_kind` 标签，不记录票据、令牌、
`stream_id` 或消息正文等高基数/敏感值。会话级创建一个 OTel span，不逐事件创建 span。

收到 SIGTERM 后的顺序固定为：停止接收新会话 → 通知现有会话关闭 → 在
`shutdown_grace_seconds` 内等待 → 取消剩余任务 → 关闭状态存储。Uvicorn 的优雅停机时间比流排空
窗口多 5 秒；Compose `stop_grace_period` 必须更长，当前开发配置为 40 秒。

反向代理必须关闭 SSE buffering 和响应转换，读超时必须大于 SSE 心跳间隔及预期最长空闲时间；
WebSocket 必须转发 Upgrade/Connection、Authorization 与 Origin，且代理消息大小不得小于应用
`websocket_max_message_bytes`。

## 9. 当前验证基线

2026-07-31 使用项目 `.venv` 与已启动的 Compose 环境完成最终验证：

- `nox -s offline`：`786 passed, 1 deselected, 5 warnings`；
- `nox -s static`：compileall、Ruff、mypy、import-linter、Bandit、pip-audit、
  detect-secrets、锁文件和 Compose 配置全部通过；
- `nox -s regression`：`921 passed, 241 warnings`，无 skip/xfail，总覆盖率 `90.07%`；
- 真实 Redis 与真实 Uvicorn 定向测试：`3 passed, 4 warnings`；
- 流容量与真实网络稳定性测试：`2 passed, 16 warnings`；覆盖 16 个并发编排流，以及 SSE/WS
  各 4 个真实并发连接、3 轮反复连接和断开；GC 后任务增长不超过 4，RSS 增长不超过 12 MiB；
- `docker compose -f compose.yml up -d`：app、PostgreSQL、Redis、RabbitMQ 均 healthy，
  app 入口为 `python -m src.cli.run_web_server`。

告警来自 Starlette TestClient/httpx 迁移、passlib 读取 argon2 版本、funboost 使用 Pydantic 旧接口及
websockets legacy API；当前均不改变断言与退出码。
