# WebSocket 与 SSE 统一流式响应基建执行方案

## 任务目标

在当前 FastAPI 分层、统一契约、资源挂载、鉴权、安全、日志和指标体系内，新增一套可复用的统一响应基建：同一业务事件源可按非流式 HTTP、SSE、WebSocket 三种方式交付，业务逻辑不因传输协议重复实现。

最终交付包括强类型流事件契约、统一执行与聚合内核、SSE/WebSocket 适配器、连接准入与恢复机制、运行时配置、资源生命周期、指标日志、真实网络测试及维护文档。完成判定为三种交付方式语义一致，异常、取消、背压、断连、重连和优雅停机均有确定行为，并通过项目全部质量门禁。

## 全局约束

- 以当前源码、冻结契约和真实测试结果为准；历史文档、图谱或旧执行方案冲突时视为可能过期，并在文档回归中修正。
- 严格遵守 `docs/standard/编码规范.md`、`docs/standard/测试规范.md`、`docs/standard/命名规范.md`；使用 Python 3.11+、现代类型标注和中文文档/日志。
- 分层固定为：`core` 定义协议，`application` 编排事件源与交付语义，`infrastructure` 实现 SSE/WebSocket/Redis/生命周期，`api` 只绑定请求、鉴权、契约和响应。
- 同一流式能力必须注册非流式交付入口；非流式与流式入口复用同一 `StreamEventSourcePort`，禁止复制业务计算、权限判断和错误映射。
- 稳定结构禁止裸 `dict`；禁止 `dict[str, Any]`、`metadata`、`extra_payload`。原始 TOML 解析可继续使用现有结构化解析边界，但进入运行时前必须完成 Pydantic 校验。
- 所有公开流契约采用“公共头字段 + 强类型扩展字段”；扩展字段必须是 Pydantic 判别联合，必须包含 `kind`、`schema_version`，并启用 `ConfigDict(extra="forbid")`。
- 外层类型与内层扩展类型必须一致：`header.event_kind == detail.kind`、`header.delivery_kind == detail.kind`，且 envelope/header/detail 的 `schema_version` 必须一致。
- 业务模块必须显式声明自身事件判别联合；公共基建只提供 started/progress/heartbeat/completed/fault 等基础事件，禁止用任意 JSON 载荷绕过业务契约。
- 默认交付语义为有序、单会话内单调递增、至多一次实时发送；启用 Redis 恢复时提供有限窗口重放，不承诺跨过期窗口的无损恢复。
- 每个会话必须具备有界队列、发送超时、最大持续时间、最大事件大小、连接配额和取消清理；慢消费者默认断开，禁止静默丢弃关键事件。
- 非流式聚合必须有最大事件数、最大字节数和超时，禁止把无界流整体读入内存。
- `asyncio.CancelledError` 必须继续传播；生产者、队列、Redis、WebSocket 和生成器必须在 `finally` 或上下文管理器中释放。
- SSE 建议使用兼容当前 FastAPI/Starlette 的 `sse-starlette`，版本由 `uv.lock` 冻结；WebSocket 使用 FastAPI/Starlette 原生接口，不手写底层帧协议。
- 当前 `BaseHTTPMiddleware` 链不覆盖 WebSocket，且不能准确表达 SSE 结束时刻；必须新增协议级连接准入，并将请求作用域、耗时、访问日志和 HTTP 指标改为流完成感知的纯 ASGI 行为。
- WebSocket 不受 CORS 保护，必须独立校验 `Origin`；浏览器连接禁止在 URL 中携带长期 JWT，只允许 Bearer 头或短期、单次、绑定用途的访问票据。
- 票据只存摘要，必须绑定主体、操作、过期时间和可选客户端 IP；日志、指标、关闭原因不得输出令牌、票据、消息正文或高基数字段。
- 建连前错误使用统一 HTTP 错误信封；建连或开始发送后使用强类型 `stream_fault` 终止事件，并映射稳定 WebSocket close code。内部异常细节只进入脱敏结构化日志。
- 观测以会话为粒度创建 span；禁止默认逐事件创建 span。Prometheus 标签只使用受控 transport/outcome/event_kind/reason 集合。
- 连接池、恢复后端、配额、服务器 WebSocket 限制和停机等待属于重启生效配置；仅心跳、发送超时等经验证为安全的字段才允许热更新。

## 验收标准

- 任一已注册流操作至少提供非流式入口，并可按声明提供 SSE、WebSocket；三者复用同一事件源，成功数据、事件顺序、终止状态和错误码一致。
- 所有公开流事件、客户端控制帧、运行时配置、访问票据和聚合结果均通过判别联合校验，额外字段、类型不一致、版本不一致直接拒绝。
- SSE 正确输出 `text/event-stream`、事件 `id/event/data`、心跳、`Last-Event-ID` 恢复及禁止代理缓冲相关头。
- WebSocket 完成建连前认证、授权、Origin、IP 封禁、限流、票据和连接配额校验；非法二进制、超大消息、未知控制帧和慢消费者按稳定 close code 关闭。
- 客户端断开、主动取消、超时、生产者异常、Redis 不可用和应用停机均能终止生产者并释放会话资源，无后台任务、队列或连接泄漏。
- 开启 Redis 恢复时，同一主体和操作可在窗口内从最后事件继续；过期、越权、跨操作和伪造事件 ID 均被拒绝。
- 非流式聚合命中事件数、字节数或时间上限时返回稳定错误，不发生无界内存增长。
- 访问日志、耗时、指标记录在真实流结束后完成；指标无高基数标签，日志不泄漏令牌、票据或业务正文。
- `.\.venv\Scripts\python.exe -m nox -s static`、`.\.venv\Scripts\python.exe -m nox -s offline`、依赖型真实网络测试和 `.\.venv\Scripts\python.exe -m nox -s regression` 全部通过；全量回归无 skip/xfail，总覆盖率不低于 85%。
- 流式协议、配置、部署、代理要求、调用示例、关闭码和最终真实测试结果与源码一致。

## 生命周期

1. 执行修改
2. 新增或修改测试
3. 真实测试
4. 回归修复
5. 文档回归

## 总任务清单

- [x] 执行修改
- [x] 新增或修改测试
- [x] 真实测试
- [x] 回归修复
- [x] 文档回归

## 阶段依赖关系

- Phase 1 冻结公共契约、运行时配置和错误/关闭语义，无前置 Phase。
- Phase 2 依赖 Phase 1，建立协议无关的事件源、会话、聚合、恢复和访问票据内核。
- Phase 3 依赖 Phase 2，落地 SSE 与非流式 HTTP 交付。
- Phase 4 依赖 Phase 2；与 Phase 3 可并行开发，落地 WebSocket 准入、双向控制和关闭语义。
- Phase 5 依赖 Phase 3、Phase 4，完成应用装配、纯 ASGI 生命周期观测、资源挂载、服务器参数和部署收口。
- 全部 Phase 完成后，按固定生命周期进入测试、真实测试、回归修复和文档回归。

## 文件层次图

```text
pyproject.toml                                      # 修改：增加 SSE 直接依赖并冻结测试依赖
uv.lock                                             # 修改：锁定兼容版本
Dockerfile                                          # 修改：统一 Web Server 启动入口
compose.yml                                         # 修改：开发环境停机与流式运行参数
compose.production.yml                              # 修改：生产停机窗口与资源限制
config/
  app_base.toml                                     # 修改：登记 stream 重启/热更新字段
  runtime/
    stream_runtime/
      stream_runtime_base.toml                      # 新增：公共流式运行时
      stream_runtime_production.toml                # 新增：Redis 恢复与严格安全策略
      stream_runtime_test.toml                      # 新增：短超时、小配额测试策略

src/
  core/
    exception_contract/
      error_code_catalog_contract.py                # 修改：补充必要流式错误码
    stream_contract/
      __init__.py                                   # 新增
      stream_event_contract.py                      # 新增：事件公共头与基础事件联合
      stream_control_contract.py                    # 新增：WebSocket 客户端控制联合
      stream_delivery_contract.py                   # 新增：操作绑定与非流式结果契约
      stream_access_contract.py                     # 新增：访问票据契约
      stream_runtime_contract.py                    # 新增：local/redis 判别运行时
  application/
    ports/
      stream_event_source_port.py                   # 新增：业务事件源端口
      stream_state_store_port.py                    # 新增：恢复、票据状态端口
    streaming/
      __init__.py                                   # 新增
      stream_execution_orchestrator.py              # 新增：事件、取消、超时、聚合编排
      stream_access_ticket_service.py               # 新增：短期单次票据签发/消费
  infrastructure/
    streaming/
      __init__.py                                   # 新增
      stream_event_codec.py                         # 新增：强类型序列化与大小校验
      stream_session_registry.py                    # 新增：会话配额与优雅停机
      memory_stream_state_store.py                  # 新增：开发/测试状态存储
      redis_stream_state_store.py                   # 新增：生产票据与有限重放
      sse_response_presenter.py                     # 新增：SSE 适配
      websocket_connection_guard.py                 # 新增：WS 建连前安全准入
      websocket_session_handler.py                  # 新增：WS 发送/接收/取消编排
      streaming_runtime_factory.py                  # 新增：按运行时构建资源
    settings/
      application_settings.py                      # 修改：挂载 stream runtime
      raw_application_settings.py                  # 修改：补充原始强类型映射
      app_settings_loader.py                        # 修改：加载 stream 配置及 REDIS_URL 覆盖
      parsers/runtime_settings_parser.py            # 修改：识别 stream_runtime
      settings_security_validator.py                # 修改：生产安全组合校验
    resource_mount/
      runtime_resource_bootstrapper.py              # 修改：启动流资源
      runtime_resource_releaser.py                  # 修改：排空并关闭流资源
      shared_resource_accessor.py                   # 修改：暴露流式依赖
      shared_resource_lifecycle.py                  # 修改：挂载会话注册表/状态存储
      shared_resource_models.py                     # 修改：补充流资源集合
      shared_resource_constants.py                  # 修改：补充资源名与错误文本
    middleware_chain/
      request_scope_middleware.py                   # 修改：纯 ASGI，覆盖 HTTP/WS 完整生命周期
      elapsed_probe_middleware.py                   # 修改：在最后一帧/关闭后记录耗时
      access_log_middleware.py                      # 修改：流结束后写访问/连接日志
    observability/
      prometheus_metrics_registry.py                # 修改：会话、事件、断连、背压指标
      prometheus_metrics_route.py                   # 修改：流完成感知 HTTP 指标
    fastapi_middleware_plan.py                      # 修改：调整纯 ASGI 中间件顺序
  api/
    fastapi_app_assembler.py                        # 修改：装配流式内核与适配器
    streaming_context_accessor.py                   # 新增：统一读取 HTTP/WS 流上下文
    fastapi_stream_route_composer.py                # 新增：保证非流式/SSE/WS 成对注册
    evidence/public_contract_snapshot_builder.py    # 修改：纳入流契约 JSON Schema
    testing/
      streaming_test_route_binder.py                # 新增：测试专用强类型流操作
  cli/
    run_web_server.py                               # 新增：从配置启动 Uvicorn WS 参数

test/
  unit_test/                                        # 新增/修改：编解码、聚合、配额、票据、存储
  contract_test/                                    # 新增：判别联合与版本/类型一致性
  boundary_test/                                    # 新增：大小、队列、配额、序列、超时边界
  exception_test/                                   # 新增：前后置异常、断连、取消、慢消费者
  interface_test/                                   # 新增：非流式、SSE、WebSocket 接口
  path_test/                                        # 新增：装配到事件源的完整路径
  initialization_test/                              # 新增：环境配置、启动失败和关闭排空
  integration_test/                                 # 新增：真实 Uvicorn、Redis 恢复与票据
  performance/                                      # 新增：并发长连接和慢消费者场景

docs/
  design_docs/FastAPI统一Web基础设施实现规格.md       # 修改：补充统一流式主链路
  design_docs/WebSocket与SSE统一流式协议.md          # 新增：协议、错误、关闭码、代理约束
  project_manual/02_backend/fastapi_app_assembly.md # 修改：补充装配与生命周期
  Docker启动运行指南.md                             # 修改：补充 Web Server 与反向代理要求
```

## Phase 1 契约与运行时冻结

### 目标

冻结协议无关的事件、客户端控制、操作绑定、非流式结果、访问票据、恢复策略及运行时配置，形成后续实现的唯一事实源。

阶段完成后，业务模块能用明确类型声明“输入命令、事件联合、可用传输、非流式入口和恢复策略”，且无法通过任意字典扩展协议。

### 依赖

- 当前 `ResponseEnvelope`、`RequestScope`、`CoreErrorCode`。
- 当前 `ApplicationSettings`、TOML 分层加载和生产安全校验。
- 当前 Pydantic v2 判别联合模式。

### 模拟用法

```python
ReportStreamDetailUnion = Annotated[
    StreamStartedDetail
    | ReportProgressDetail
    | ReportRowDetail
    | StreamCompletedDetail
    | StreamFaultDetail,
    Field(discriminator="kind"),
]

ReportStreamEnvelope = StreamEventEnvelope[ReportStreamDetailUnion]
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| `StreamEventHeader` | 流事件公共头 | 包含 `stream_id`、`event_id`、`sequence`、`event_kind`、`schema_version`、`request_id`、`trace_id`、`emitted_at`。 |
| `StreamEventDetailUnion` | 流事件扩展联合 | 业务显式联合基础生命周期事件与业务事件；以 `kind` 判别，所有成员禁止额外字段。 |
| `StreamStartedDetail` | 流开始事件 | 冻结操作名、传输模式和恢复能力，不包含业务任意载荷。 |
| `StreamProgressDetail` | 流进度事件 | 表达可选总量、当前量和阶段名；不用于承载业务正文。 |
| `StreamCompletedDetail` | 流完成事件 | 表达正常完成、最后序号和汇总计数。 |
| `StreamFaultDetail` | 流故障事件 | 只暴露稳定错误码、客户端可读消息和可重试性，不暴露内部 detail。 |
| `StreamClientControlUnion` | 客户端控制扩展联合 | 包含 `subscribe`、`resume`、`cancel`、`ping` 强类型控制帧。 |
| `StreamOperationBindingEnvelope` | 流操作绑定信封 | 公共头声明操作名和 `delivery_kind`，扩展联合区分命令流、订阅流及启用的传输集合。 |
| `StreamBatchEnvelope` | 非流式聚合结果 | 返回同一事件源的有界成功结果、终止状态和序列摘要。 |
| `StreamAccessTicketEnvelope` | 流访问票据信封 | 票据明文只在签发响应出现一次，存储侧只保留摘要及绑定约束。 |
| `StreamRuntimeEnvelope` | 流运行时信封 | `header.mode` 与 `detail.kind` 一致，扩展联合区分 `local_stream_runtime`、`redis_stream_runtime`。 |
| `StreamCloseReason` | 流关闭原因 | 封闭枚举，统一正常完成、客户端取消、超时、过载、策略拒绝、服务停机和内部异常。 |

### 任务清单

- [x] 新建 `src/core/stream_contract`，定义公共头、基础生命周期事件和泛型事件信封。
- [x] 为事件信封增加 event kind、schema version、sequence 单调性所需校验入口。
- [x] 定义 WebSocket 客户端控制帧判别联合，禁止未知 kind 和额外字段。
- [x] 定义操作绑定信封，强制存在非流式交付定义，并显式声明 SSE/WS 支持范围。
- [x] 定义非流式聚合结果、访问票据、关闭原因和恢复请求契约。
- [x] 定义 local/redis 流运行时判别联合及全部正值、上限和组合校验。
- [x] 在 `ApplicationSettings`、原始映射、加载器和分节解析器中接入 `runtime.stream`。
- [x] 在生产安全校验中拒绝通配 Origin、无界配额、明文长期票据和不兼容恢复后端。
- [x] 优先复用现有错误码，仅补充无法由 request/capacity/auth 错误准确表达的流式错误码。
- [x] 将全部 stream 资源、池大小、恢复后端字段加入 `restart_required`，只开放经验证安全的热更新字段。
- [x] 为全部公开流信封补齐外层 `schema_version`，并校验 envelope/header/detail 三层版本一致。
- [x] 将包含业务 `subscribe` 的完整客户端控制联合改为带 discriminator 的判别联合，并冻结 JSON Schema。
- [x] 校验 transport 声明与 SSE/WS 路径、交付细节双向一致，拒绝未启用 transport 的幽灵路径。
- [x] 为 `StreamBatchEnvelope` 增加 stream ID、事件数、末序号、字节摘要和终止事件一致性校验。
- [x] 将访问票据与聚合结果迁移为“公共头 + 强类型判别扩展”公开契约。
- [x] 为配额、事件大小、会话持续时间、票据/重放 TTL、Redis 池大小定义并测试生产安全上界。
- [x] 为每个 `runtime.stream` 字段增加 restart/hot 分类测试，并验证热更新后新连接真实读取新值。
- [x] 增加超长期票据、超大配额和错误恢复组合的生产启动拒绝测试。

### 关键代码片段

```python
class StreamEventEnvelope(BaseModel, Generic[T_StreamDetail]):
    model_config = ConfigDict(extra="forbid")

    header: StreamEventHeader
    detail: T_StreamDetail

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.header.event_kind != self.detail.kind:
            raise ValueError("流事件公共头类型必须与扩展字段类型一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("流事件 schema_version 必须一致。")
        return self
```

### 校验

- 使用 `TypeAdapter` 验证合法业务联合可通过，未知 kind、额外字段和版本漂移被拒绝。
- development/test/production 配置均可加载；非法 Origin、零配额、错误 mode/detail 组合启动失败。
- 运行时配置中不存在 `dict[str, Any]`、`metadata`、`extra_payload`。

## Phase 2 统一执行、聚合与状态内核

### 目标

建立不依赖 HTTP/SSE/WebSocket 的事件源端口和执行编排器，统一处理序列、超时、背压、取消、非流式聚合、访问票据和有限恢复。

阶段完成后，传输层只消费规范化事件，不参与业务计算；本地与 Redis 状态后端可替换。

### 依赖

- Phase 1 已冻结事件、控制、运行时、票据和关闭契约。
- 当前 `SharedResourceMount`、Redis 配置、结构化日志和取消语义。

### 模拟用法

```python
events = orchestrator.iter_events(
    source=report_stream_source,
    command=command,
    context=stream_context,
)

batch = await orchestrator.collect(
    source=report_stream_source,
    command=command,
    context=stream_context,
)
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| `StreamEventSourcePort[TCommand, TDetail]` | 流事件源端口 | 业务实现只负责异步产生强类型事件，不感知 SSE/WS。 |
| `StreamExecutionContext` | 流执行上下文 | 冻结 request/trace/subject/operation/deadline/transport，不传入过大的 Request 或 WebSocket。 |
| `StreamExecutionOrchestrator` | 流执行编排器 | 负责 started/terminal 补齐、序列校验、超时、取消和资源清理。 |
| `StreamStateStorePort` | 流状态存储端口 | 统一访问票据消费、事件追加、窗口重放和过期清理。 |
| `StreamSessionLease` | 流会话租约 | 表达进程内配额占用、释放责任和关闭状态。 |
| `StreamReplayWindow` | 流恢复窗口 | 返回可重放事件、最早/最新事件 ID 和窗口是否过期。 |
| `StreamCollectionLimit` | 非流式聚合限制 | 强类型定义最大事件数、字节数和超时。 |

### 任务清单

- [x] 定义泛型 `StreamEventSourcePort`，输入命令和输出事件联合必须显式类型化。
- [x] 实现 `StreamExecutionOrchestrator`，统一生成 stream/event ID、sequence 和 started/completed 事件。
- [x] 对生产者输出执行 TypeAdapter 校验、事件大小校验和 sequence 单调校验。
- [x] 使用有界队列连接生产与发送；入队或发送超时转为慢消费者终止，不静默丢事件。
- [x] 实现 `collect()`，复用同一事件源并执行事件数、字节数、时间三重上限。
- [x] 在取消、断连和超时时调用异步生成器 `aclose()`，继续传播 `CancelledError`。
- [x] 实现进程内会话注册表，执行全局、主体、IP、操作四级配额。
- [x] 实现 memory 状态存储，供单进程开发和确定性单元测试使用。
- [x] 实现 Redis 状态存储，原子消费单次票据并按 stream/event ID 保存有限重放窗口。
- [x] 实现票据签发与消费服务：随机高熵、短 TTL、摘要存储、主体/操作/可选 IP 绑定。
- [x] 明确 Redis 故障语义：安全票据消费 fail-closed；已建连实时发送可继续但关闭恢复能力并记录告警。
- [x] 在 `StreamExecutionContext` 中补齐并强类型化执行截止时间 `deadline`。
- [x] 保证 `collect()` 命中事件数、字节数或时间上限时关闭事件迭代器、取消并等待生产者，无后台任务泄漏。
- [x] 将 started 后的非法业务 detail、TypeAdapter 失败和单事件超限统一收束为 `stream_fault` 并关闭生产者。
- [x] 修复饱和队列取消时终态入队无界等待，保证 `aclose()` 可在限定时间内完成。
- [x] 增加聚合字节/时间超限、饱和队列取消、非法/超大事件和 Redis 故障语义的自动化回归测试。

### 关键代码片段

```python
class StreamEventSourcePort(Protocol[T_Command, T_StreamDetail]):
    def open(
        self,
        *,
        command: T_Command,
        context: StreamExecutionContext,
    ) -> AsyncIterator[StreamEventEnvelope[T_StreamDetail]]: ...


async def collect(...) -> StreamBatchEnvelope[T_StreamDetail]:
    async for event in self.iter_events(...):
        limits.accept(event)
        events.append(event)
    return batch_factory.build(events)
```

### 校验

- 相同 fake source 经 `iter_events()` 与 `collect()` 得到相同业务事件顺序和终止语义。
- 队列满、事件超大、聚合超限、生产者取消和 Redis 异常均得到稳定结果并释放租约。
- 票据重复消费、跨主体、跨操作、过期和摘要伪造全部失败。

## Phase 3 SSE 与非流式 HTTP 交付

### 目标

将统一事件内核映射为标准 SSE，并为同一操作生成非流式 HTTP 入口；处理心跳、客户端断开、恢复、代理缓冲和开始发送后的故障。

阶段完成后，业务模块只需注册一个操作绑定即可获得一致的非流式与 SSE 行为。

### 依赖

- Phase 2 已提供事件迭代、聚合、恢复和票据能力。
- 当前 HTTP 鉴权、授权依赖、统一错误信封和 API prefix 规则。

### 模拟用法

```bash
curl -N -X POST "http://127.0.0.1:8000/reports/generate/stream" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"kind":"report_generate_command","schema_version":"1.0","report_id":"r-1"}'
```

```text
id: 01J...
event: report_progress
data: {"header":{...},"detail":{"kind":"report_progress","schema_version":"1.0",...}}
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| `SseDeliveryDetail` | SSE 交付扩展 | 定义 POST/GET 模式、心跳间隔、retry 值、恢复策略和票据要求。 |
| `SseEventMapping` | SSE 事件映射 | `id=event_id`、`event=detail.kind`、`data=完整事件信封 JSON`。 |
| `SseResumeRequest` | SSE 恢复请求 | 优先读取 `Last-Event-ID`，并与主体、操作和 stream ID 校验。 |
| `StreamBatchCompletedDetail` | 非流式完成扩展 | 返回有界业务事件集合、最后序号和完成摘要。 |
| `StreamBatchRejectedDetail` | 非流式拒绝扩展 | 表达聚合超限或不允许聚合的有限错误语义。 |

### 任务清单

- [x] 在 `pyproject.toml` 增加 `sse-starlette`，更新并校验 `uv.lock`。
- [x] 实现 `StreamEventCodec`，使用 Pydantic/orjson 序列化完整信封并执行最大字节校验。
- [x] 实现 `SseResponsePresenter`，映射 `id/event/data/retry`，使用注释心跳避免污染业务事件序列。
- [x] 固定响应头：`Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`，并保持 UTF-8 `text/event-stream`。
- [x] 在发送前完成认证、授权、票据和恢复参数校验；失败继续走统一 HTTP 错误信封。
- [x] 发送开始后，将可处理异常转换为 `stream_fault` 终止事件；不可恢复内部异常记录后关闭。
- [x] 客户端断开时取消生产者、关闭生成器、释放租约，不把正常断连记录为服务端错误。
- [x] 实现非流式 presenter，调用 `collect()` 并返回现有 `ResponseEnvelope`。
- [x] 实现流操作路由组合器的 HTTP/SSE 部分，校验路径、operation name、OpenAPI operation ID 唯一。
- [x] 对 native `EventSource` 场景使用短期单次票据；Bearer 场景推荐 fetch streaming，禁止长期 JWT 查询参数。
- [x] 在响应头发送前完成恢复窗口存在性、过期、主体、操作和事件 ID 校验，并保证恢复后的 stream ID 与 sequence 连续。
- [x] 为 HTTP/SSE 操作绑定增加强类型授权 requirement，并接入既有授权守卫与统一 401/403 信封。
- [x] 为 SSE 获取并在 `finally` 释放共享会话租约，覆盖配额、提前断连、生产者取消和 active session 归零。
- [x] 将事件过大、联合校验、codec 与重放解码等发送后异常映射为稳定 `stream_fault`。
- [x] 补齐非流式 completed/rejected 强类型结果，生产 fault 不得以外层 `system.success.ok` 返回。
- [x] 校验 composer 与应用既有 path/operation ID 冲突，并完成至少一个生产业务流绑定接入。
- [x] 补齐或修订 `SseEventMapping`、`SseResumeRequest`、batch completed/rejected 与 `SseDeliveryDetail` 契约，使阶段文档与源码一致。
- [x] 增加真实心跳、多行/中文、失效/越权恢复、断连清理、三种交付故障一致性和路由冲突测试。

### 关键代码片段

```python
return EventSourceResponse(
    presenter.iter_sse_events(events),
    ping=runtime.sse.heartbeat_seconds,
    send_timeout=runtime.send_timeout_seconds,
    headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    },
)
```

### 校验

- 首帧、业务事件、心跳、完成帧的格式符合 SSE；多行和中文数据不破坏边界。
- `Last-Event-ID` 在窗口内正确重放，过期/越权恢复返回稳定错误。
- 非流式响应和 SSE 的业务事件内容、顺序、错误码一致，且聚合上限生效。

## Phase 4 WebSocket 连接与双向控制

### 目标

实现 WebSocket 建连前安全准入、强类型客户端控制、并发收发、取消/恢复、慢消费者处理和稳定关闭码。

阶段完成后，WebSocket 不依赖 HTTP-only 中间件即可获得与现有 HTTP 安全主链路等价的认证、授权、IP、限流和日志语义。

### 依赖

- Phase 2 已提供统一事件、会话、票据、配额和恢复能力。
- 当前 JWT 服务、授权策略、`ClientIpResolver`、IP block、RateLimitGuard 和安全事件构建器。

### 模拟用法

```python
with client.websocket_connect(
    "/reports/generate/ws?ticket=<single-use-ticket>",
    headers={"origin": "https://console.example.com"},
) as websocket:
    websocket.send_json(
        {
            "header": {
                "kind": "stream_client_control_header",
                "schema_version": "1.0",
                "control_kind": "subscribe",
            },
            "detail": {
                "kind": "subscribe",
                "schema_version": "1.0",
                "command": {
                    "kind": "report_generate_command",
                    "schema_version": "1.0",
                    "report_id": "r-1",
                },
            },
        }
    )
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| `WebSocketAdmissionRequest` | WS 准入请求 | 冻结 path、origin、客户端 IP、凭证来源、操作和连接配额维度。 |
| `WebSocketAdmissionResult` | WS 准入结果 | 返回主体快照、票据绑定、会话租约和凭证过期时间。 |
| `SubscribeControlDetail[TCommand]` | 订阅控制扩展 | 携带业务强类型命令，必须是首次有效控制帧。 |
| `ResumeControlDetail` | 恢复控制扩展 | 指定 stream ID 与最后事件 ID，不允许跨主体或跨操作。 |
| `CancelControlDetail` | 取消控制扩展 | 客户端主动终止当前流，服务端回终止事件后正常关闭。 |
| `WebSocketCloseMapping` | WS 关闭码映射 | 统一使用 1000 正常、1001 停机、1008 策略、1009 过大、1011 内部异常、1013 过载。 |

### 任务清单

- [x] 实现 `WebSocketConnectionGuard`，在 `accept()` 前执行 Origin、认证、授权、IP block、限流、票据和配额校验。
- [x] 复用当前 JWT、授权策略和客户端 IP 事实源，禁止复制一套弱化版鉴权逻辑。
- [x] 支持 Bearer 头和单次票据两种凭证来源；生产浏览器默认票据模式。
- [x] 使用业务提供的 `TypeAdapter` 校验首次 subscribe 命令和后续控制帧。
- [x] 仅接收 UTF-8 JSON 文本；二进制帧、未知 kind、额外字段和超大消息按协议拒绝。
- [x] 使用任务组并发执行发送循环与接收循环；任一侧结束必须取消另一侧并统一清理。
- [x] 实现 cancel、resume、ping 控制；重复 subscribe、无效状态转换和越权恢复返回 fault 后关闭。
- [x] 将凭证过期时间作为连接硬截止时间；到期前发送可重连终止事件并关闭。
- [x] 发送超时或队列持续饱和时发出 slow-consumer fault，并以 1013 关闭。
- [x] 实现路由组合器的 WebSocket 部分；WebSocket 协议通过独立文档/JSON Schema 描述，不伪装为普通 OpenAPI 响应。
- [x] 记录建连拒绝、正常断连、策略关闭、过载和内部异常安全事件，所有敏感字段脱敏。
- [x] 定义并接入 `WebSocketAdmissionRequest`，补齐准入结果的票据绑定、凭证到期、租约和 subprotocol 语义。
- [x] 实现终止原因到 WebSocket close code 的统一映射，覆盖 1000/1001/1008/1009/1011/1013。
- [x] 消费 `lease.shutdown_event` 并登记真实取消回调，将服务排空稳定映射为 1001。
- [x] 将配额耗尽和 draining 转换为稳定的建连前拒绝/过载语义，禁止泄漏裸 `RuntimeError`。
- [x] 将生产 JWT、授权、IP block、限流与安全事件端口接入 guard，替换测试专用空实现事实源。
- [x] 增加重复 subscribe、越权/过期 resume、凭证截止、慢消费者、断连回收、配额和安全事件专项测试。

### 关键代码片段

```python
admission = await guard.authorize(websocket=websocket, binding=binding)
await websocket.accept(subprotocol=admission.subprotocol)

async with asyncio.TaskGroup() as task_group:
    task_group.create_task(handler.send_events(websocket, admission))
    task_group.create_task(handler.receive_controls(websocket, admission))
```

### 校验

- 缺失/非法凭证、非法 Origin、IP 封禁、限流和配额超限均在建连前拒绝。
- 正常完成、客户端取消、服务停机、消息过大、慢消费者和内部异常映射到预定关闭码。
- 发送/接收任一侧退出后无悬挂任务，票据和会话租约只释放一次。

## Phase 5 装配、生命周期、观测与部署收口

### 目标

将流式能力接入应用组合根、共享资源生命周期、纯 ASGI 中间件、Prometheus、OTel、Uvicorn 启动和容器停机流程，完成生产运行闭环。

阶段完成后，流资源只在 lifespan 内启动，应用停机可先拒绝新连接、排空存量会话，再关闭状态存储和其他资源。

### 依赖

- Phase 3、Phase 4 已提供完整交付适配器。
- 当前 `FastApiAppAssembler`、`SharedResourceMount`、lifespan、指标注册表、Docker/Compose。

### 模拟用法

```python
binding = StreamOperationBinding(
    operation_name="report_generate",
    command_adapter=TypeAdapter(ReportGenerateCommand),
    event_adapter=TypeAdapter(ReportStreamEnvelope),
    source=report_stream_source,
    delivery=delivery_contract,
    authorization_requirement=REPORT_GENERATE_REQUIREMENT,
)

FastApiStreamRouteComposer(runtime=stream_runtime).compose(
    router=router,
    bindings=[binding],
)
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| `StreamingRuntimeResourceSet` | 流运行时资源集 | 包含编排器、会话注册表、状态存储、票据服务和传输适配器。 |
| `StreamShutdownPolicy` | 流停机策略 | 定义拒绝新连接、通知存量会话、排空等待和强制取消顺序。 |
| `StreamSessionMetric` | 流会话指标 | 只使用 transport/outcome/reason 低基数标签。 |
| `StreamEventMetric` | 流事件指标 | 记录受控 event kind、发送结果、字节数和耗时，不含 stream ID。 |
| `StreamAccessLogDetail` | 流访问日志扩展 | 记录操作、传输、持续时间、事件数、关闭原因和脱敏主体摘要。 |
| `WebServerRuntimeProjection` | Web Server 参数投影 | 将流配置投影为 Uvicorn ws max size、ping、graceful timeout 等启动参数。 |

### 任务清单

- [x] 在 `FastApiAppAssembler` 和 `ApplicationContainer` 装配流执行内核、适配器和路由组合器依赖。
- [x] 在 `SharedResourceMount` 启动 memory/Redis 状态存储与会话注册表，启动失败按现有资源回滚顺序释放。
- [x] 停机顺序固定为：标记 draining、拒绝新连接、发送停机终止事件、等待 grace、强制取消、关闭状态存储。
- [x] 将 `RequestScopeMiddleware` 改为纯 ASGI，使上下文覆盖最后一个 HTTP body 帧或 WebSocket close。
- [x] 将 elapsed/access log/HTTP metrics 改为 send 包装器，在真实流结束后记录状态、耗时和字节。
- [x] 保持认证、限流等 HTTP 中间件现有语义；WebSocket 只通过专用 guard 接入，不假设 HTTP middleware 生效。
- [x] 增加 active sessions、session total/duration、event total/bytes、disconnect、slow consumer、resume、queue saturation 指标。
- [x] OTel 仅创建会话级 span 和关键异常 event，不逐 chunk 采样。
- [x] 扩展公开契约快照，输出操作绑定、事件联合、客户端控制和运行时 JSON Schema。
- [x] 新增 `run_web_server.py`，从配置启动 Uvicorn 并设置 ws max size、ping interval/timeout、graceful shutdown。
- [x] 更新 Dockerfile/Compose，使容器 stop grace 大于应用排空时间，并保留内存/PID 边界。
- [x] 在测试应用工厂中提供测试专用流操作绑定，不向生产模块暴露 demo 接口。
- [x] 实现并接入 `StreamAccessLogDetail`，记录操作、传输、事件数、关闭原因和脱敏主体摘要。
- [x] 实现 `WebServerRuntimeProjection`，并用初始化测试冻结 Uvicorn、应用 drain 与 Compose stop grace 的大小关系。
- [x] 让 `StreamingRuntimeResourceSet` 纳入 orchestrator、codec/presenter、guard/handler，并让生产绑定复用同一共享资源集。
- [x] 为 SSE/WS 统一申请共享租约、消费 shutdown event 并登记真实任务取消回调。
- [x] 增加流资源启动中途失败、SIGTERM、grace 超时取消、最后帧上下文和日志/指标恰好一次的专项测试。
- [x] 将测试 binder 的 memory store 纳入测试应用生命周期并显式关闭，避免与生产资源模型分叉。

### 关键代码片段

```python
async def shutdown_streaming_runtime(resources: StreamingRuntimeResourceSet) -> None:
    resources.session_registry.begin_draining()
    await resources.session_registry.notify_shutdown()
    await resources.session_registry.wait_until_empty(
        timeout_seconds=resources.shutdown_policy.grace_seconds,
    )
    await resources.session_registry.cancel_remaining()
    await resources.state_store.close()
```

### 校验

- 应用未进入 lifespan 时不连接 Redis；启动失败后已创建流资源全部释放。
- SIGTERM 期间新连接被拒绝，存量连接在 grace 内收到终止语义，超时连接被强制取消。
- SSE/WS 完成后访问日志、耗时与指标只记录一次，且无 stream ID、token、ticket 高敏/高基数字段。
- Uvicorn、应用 runtime、Docker stop grace 的大小与超时关系通过初始化校验。

## 新增或修改测试

覆盖新增行为：统一事件源、非流式聚合、SSE、WebSocket、票据、有限恢复、配额、背压、优雅停机和流完成观测。

覆盖变更行为：请求作用域、耗时、访问日志和 HTTP 指标由响应对象返回时刻改为真实流结束时刻，现有普通 HTTP 行为不得回归。

任务清单：

- [x] 单元测试：事件/控制/运行时 TypeAdapter、codec、sequence、事件大小、聚合三重上限。
- [x] 单元测试：会话注册表全局/主体/IP/操作配额、幂等释放、draining 状态。
- [x] 单元测试：memory/Redis store、票据单次消费、重放窗口、过期与越权。
- [x] 契约测试：所有 detail 为判别联合，包含 kind/schema_version，`extra="forbid"`，内外类型/版本一致。
- [x] 契约测试：操作绑定存在非流式入口，路径、operation name 和 event kind 唯一。
- [x] 接口测试：非流式成功/失败、SSE headers/事件/心跳/恢复、WebSocket subscribe/cancel/resume/close code。
- [x] 异常测试：生产者在首帧前/后失败、序列错误、未知事件、Redis 故障、客户端断开、慢消费者。
- [x] 边界测试：0/1/上限/超上限事件数、字节、队列、连接数、消息大小、TTL、超时和持续时间。
- [x] 路径测试：路由组合器 -> 鉴权 -> 事件源 -> orchestrator -> 三种 presenter -> 日志/指标。
- [x] 初始化测试：三环境配置、非法生产 Origin、错误 Redis 组合、lifespan 启停和失败回滚。
- [x] 集成测试：真实 Redis 原子票据消费、跨连接恢复、过期清理和多客户端竞争。
- [x] 集成测试：真实 Uvicorn 端口上用 `httpx.AsyncClient.stream()` 和 WebSocket 客户端验证网络断连/重连。
- [x] 回归测试：现有普通 HTTP 响应、中间件轨迹、异常信封、OpenAPI、metrics、lifespan 和热更新。
- [x] 性能测试：并发 SSE/WS、慢消费者、长时间心跳、反复连接/断开后的任务数和内存回落。
- [x] ASGI 流完成观测测试：分别验证 SSE 最终 body、WebSocket close 和客户端断开后，request scope、elapsed、access log、HTTP/流指标均在真实结束时记录且只记录一次。

## 真实测试

任务清单：

- [x] 当前源码执行 `compileall` 及流式定向 unit/contract/interface/exception/boundary/path/initialization 测试，无 skip/xfail。
- [x] 当前代码基线执行 `.\.venv\Scripts\python.exe -m nox -s offline`，结构化证据为 `786 passed, 1 deselected, 5 warnings`、退出码 0。
- [x] 当前代码基线执行 `.\.venv\Scripts\python.exe -m nox -s static`，compileall、Ruff、Mypy、import-linter、Bandit、pip-audit、detect-secrets、锁文件和 Compose 校验退出码均为 0。
- [x] 真实 Redis 与真实 Uvicorn 定向测试可执行且通过，无 skip/xfail。
- [x] 当前代码基线执行 `.\.venv\Scripts\python.exe -m nox -s regression`：`921 passed, 241 warnings`，无 skip/xfail，总覆盖率 `90.07%`，退出码 0。
- [x] 完成真实 SSE/WS 并发、慢消费者、长心跳、反复断连/重连和内存回落的性能/稳定性验收；独立性能测试 `2 passed, 16 warnings`，任务增长不超过 4，RSS 增长不超过 12 MiB。

执行顺序：

1. 最小静态和定向失败集

   ```powershell
   .\.venv\Scripts\python.exe -m compileall -q src test
   .\.venv\Scripts\python.exe -m pytest -q `
     test/unit_test/test_stream_event_codec_unit.py `
     test/unit_test/test_stream_execution_orchestrator_unit.py `
     test/unit_test/test_stream_session_registry_unit.py `
     test/contract_test/test_stream_contract.py
   ```

2. 阶段相关离线测试

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q `
     test/interface_test/test_streaming_http_interface.py `
     test/interface_test/test_streaming_websocket_interface.py `
     test/exception_test/test_streaming_exception.py `
     test/boundary_test/test_streaming_boundary.py `
     test/path_test/test_streaming_delivery_path.py `
     test/initialization_test/test_streaming_runtime_initialization.py
   .\.venv\Scripts\python.exe -m nox -s offline
   ```

3. 真实依赖与真实网络测试

   ```powershell
   docker compose -f compose.yml up -d
   .\.venv\Scripts\python.exe -m pytest -q -m "redis or integration" `
     test/integration_test/test_streaming_redis_integration.py `
     test/integration_test/test_streaming_network_integration.py
   ```

4. 静态质量门禁

   ```powershell
   .\.venv\Scripts\python.exe -m nox -s static
   ```

5. 全量回归

   ```powershell
   .\.venv\Scripts\python.exe -m nox -s regression
   ```

6. 受控性能与稳定性测试

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q -m performance `
     test/performance/test_streaming_capacity.py
   ```

通过标准：

- 全部命令退出码为 0；全量回归无 skip/xfail，总覆盖率不低于 85%。
- 真实 Redis 票据只成功消费一次，恢复事件无重复、无越权、顺序单调。
- 真实网络测试可观察到 SSE 增量到达和 WebSocket 双向控制，不允许一次性缓冲到结束。
- 并发基线使用测试配置冻结的连接数与事件速率；无意外断连、无悬挂任务，关闭后 active session 归零。
- 稳定性测试结束并完成 GC/资源回收后，进程内存与任务数回到基线允许区间；具体阈值写入性能测试配置和最终报告。

## 回归修复

修复原则：先修源码事实源和资源释放，再修契约/测试断言，最后修文档；禁止通过扩大队列、吞异常、移除超时、放宽类型或增加 skip 掩盖问题。

任务清单：

- [x] 契约失败时，优先检查判别联合、外内 kind、schema_version、额外字段和业务事件联合声明。
- [x] 非流式/SSE/WS 语义不一致时，检查是否绕过同一事件源或在 presenter 中混入业务判断。
- [x] SSE 聚合、断流或延迟到达时，检查代理缓冲、响应头、纯 ASGI 中间件和生成器取消路径。
- [x] WebSocket 失败时，检查 accept 前准入、Origin、票据原子消费、控制状态机和关闭码映射。
- [x] 恢复失败时，检查 Redis 原子操作、TTL、事件 ID 所属主体/操作和窗口边界。
- [x] 泄漏或停机超时时，检查任务组取消、`aclose()`、租约幂等释放、draining 顺序和 Docker grace。
- [x] 指标/日志重复时，检查最终 body/close 帧拦截与 presenter 是否重复记录结束事件。
- [x] 每次修复后先回跑最小失败集，再回跑所属阶段测试、真实依赖测试、`.\.venv\Scripts\python.exe -m nox -s static` 和 `.\.venv\Scripts\python.exe -m nox -s regression`。
- [x] 修复聚合超限和饱和队列取消导致的生产者/终态入队泄漏，并增加稳定回归。
- [x] 修复 SSE 恢复响应启动后报错、跨 stream 拼接与 sequence 重置，并增加过期/越权/伪造恢复回归。
- [x] 修复非流式 fault 外层成功、WebSocket 重复 subscribe 无 fault、慢消费者未同时 fault+1013 和停机未通知连接的问题。
- [x] 完成生产流绑定、真实准入/授权/限流、安全事件、流指标和访问日志主流程接线后回跑全量门禁。

## 文档回归

文档必须与最终源码、契约 JSON Schema、运行时配置和真实测试结果一致；历史说明冲突时标注旧内容可能过期并以本次实现覆盖。

任务清单：

- [x] 更新 `FastAPI统一Web基础设施实现规格.md`：补充统一事件源、三种交付、纯 ASGI 生命周期和错误边界。
- [x] 新增 `WebSocket与SSE统一流式协议.md`：记录事件/控制联合、序列、恢复窗口、票据、关闭码和示例。
- [x] 更新 `fastapi_app_assembly.md`：记录 container、resource mount、stream route composer 和 lifespan 顺序。
- [x] 更新 `Docker启动运行指南.md`：记录 Uvicorn WS 参数、SIGTERM 排空、反向代理 SSE buffering/timeout 要求。
- [x] 记录浏览器 Bearer/fetch streaming、native EventSource 单次票据和 WebSocket Origin 策略。
- [x] 记录非流式聚合上限、慢消费者策略、实时至多一次与 Redis 有限恢复语义。
- [x] 写入最终真实测试命令、通过数量、覆盖率、性能基线、警告和环境前提。
- [x] 重新生成并核对公开契约快照，确保文档示例可被当前 TypeAdapter 校验通过。
- [x] 按当前源码修正文档中对生产绑定、完整客户端控制 Schema、连续恢复、停机通知、关闭码、安全事件、流指标和访问日志的过度声明。
- [x] 将最终回归与覆盖率记录绑定当前代码基线，并补充真实 SSE/WS 性能和内存回落数据。
