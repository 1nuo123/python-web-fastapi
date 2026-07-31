# FastAPI 应用装配

## 1. 这是什么

详解组合根 `FastApiAppAssembler` 如何把配置、日志、资源门面、用例容器、异常呈现、中间件、指标出口、路由与 OpenAPI 装配成一个可运行的 FastAPI 应用；以及 `AsgiApplicationFactory`、`ApplicationContainer`、`TaskBindingSource` 三个配角的职责。改动任何"应用启动阶段"的行为时先读本文。

**最后更新范围**：覆盖 `src/api/fastapi_app_assembler.py`、`src/api/asgi_entry.py`、`src/api/task_binding_provider.py`、统一流路由组合器、流资源生命周期与测试装配工厂；不使用易过期的源码行数作为契约。

## 2. 设计思想与动机

- **装配与运行分离**：`FastApiAppAssembler.__call__` 会读取配置文件/环境变量、构建 logger 和进程内对象，因此不是“无任何 IO 的纯函数”；它不会在装配期连接 PostgreSQL、Redis、RabbitMQ 或出站 HTTP 客户端。真实运行时资源连接推迟到 lifespan 进入时由 `SharedResourceMount.startup()` 完成，所以无外部服务的测试仍可先构建应用对象。
- **显式容器而非 DI 框架**：`ApplicationContainer` 是一个逐字段声明的 dataclass（约 40 个用例字段），装配器手写 `_build_application_container` 完成注入。不用 DI 框架的原因：依赖图在本项目规模下完全可读，显式代码的失败模式（少传参数 = 启动 TypeError）比运行时容器解析错误更早、更清楚。
- **入参可覆盖**：`create_app(environment=..., config_root=..., settings_overrides=..., task_bindings=..., database_engine_factory=...)` 的每个入参都是测试/CLI 的替换点——测试注入 SQLite 引擎工厂与显式任务绑定，task-worker CLI 注入 `worker_enabled=true` 覆盖。

## 3. 关联源码

| 路径 | 作用 |
| --- | --- |
| `src/api/asgi_entry.py` | `AsgiApplicationFactory`（dataclass，`__call__` 转发装配器）；模块级 `create_app` 单例。 |
| `src/api/fastapi_app_assembler.py` | `FastApiAppAssembler`、`ApplicationContainer`、`TaskBindingSource`。 |
| `src/api/task_binding_provider.py` | `ApplicationTaskBindingProvider`：业务任务处理器绑定的显式扩展点（当前返回 `task_execution_probe` 绑定）。 |
| `src/api/fastapi_stream_route_composer.py` | `FastApiStreamRouteComposer`：校验并成对注册非流式 HTTP、SSE、WebSocket 路由。 |
| `src/infrastructure/streaming/streaming_runtime_factory.py` | 按 local/redis 运行时构建状态存储、会话注册表、票据服务和停机策略。 |
| `src/api/testing/test_app_factory.py` | 测试装配工厂，复用同一装配器。 |
| `src/infrastructure/fastapi_*.py` | 装配器直接使用的 6 个 FastAPI 粘合件。 |

## 4. 装配流程逐步拆解

`FastApiAppAssembler.__call__` 的 13 步（源码顺序）：

| 步 | 动作 | 关键细节 |
| --- | --- | --- |
| 1 | `AppSettingsLoader(config_root)` 加载配置 | `_load_settings`：有 overrides 必须显式给 environment，否则 ValueError；无参时按 `APP_ENV` 环境变量选环境（默认 development）。 |
| 2 | `WebBundleCatalog()` 构建并 `validate_enabled_modules` | manifest 内五重一致性校验 + 配置启用模块必须存在于 manifest，错误消息列出全部可用模块名。 |
| 3 | `AppLoggerFactory().build(settings)` | 构建 runtime logger（级别来自 `runtime.logging.level`）。 |
| 4 | `SettingsStateHolder(current_settings=settings)` | 可变配置持有器，热更新时被替换内容。 |
| 5 | `FastApiOtelBridge(settings.runtime.otel)` | OTel 关闭时为 no-op 状态对象。 |
| 6 | `_build_resource_mount` | 构建 `SharedResourceMount` 并注册任务绑定（见第 5 节）。 |
| 7 | `_build_reload_coordinator` | `SettingsReloadCoordinator` + `SettingsSnapshotStore`，`initialize_snapshot()` 记录基线快照；`on_settings_applied=resource_mount.apply_settings` 完成协调器→资源门面的回调接线。 |
| 8 | `_build_application_container` | 集中 new 全部用例；几乎所有用例的端口实参都是同一个 `resource_mount`（它实现全部端口）；配置热更新用例经 `AdminSettingsReloadAdapter` 桥接 reload_coordinator。 |
| 9 | `_build_fastapi_app` | `FastAPI(title/version 来自配置, default_response_class=OrjsonDocumentResponse, lifespan=FastApiLifespanOrchestrator(resource_mount), openapi/docs/redoc 按 enable_openapi 三开关)`。 |
| 10 | `app.state.container = container; app.state.ready = False` | 容器上车；ready 初始 False。 |
| 11 | `telemetry_bridge.instrument_app(app)`；`FastApiExceptionPresenter(...).bind(app)` | OTel 仪表化（启用时，由库管理其 ASGI 中间件）；注册 `HttpFaultException`、`RequestValidationError`、`Exception` 三个处理器。后者在 Starlette 栈中作为最外层 server-error handler 使用。 |
| 12 | `_bind_middlewares` → `_bind_prometheus_metrics` | 中间件计划前插；指标启用时构建 `PrometheusMetricsRegistry`（按 4 个 include 开关裁剪指标族）→ `resource_mount.install_metrics_registry`（供日志缓冲/任务链/饱和度读取）→ 可选 HTTP 指标中间件 → `/metrics` 路由（不进 OpenAPI）。 |
| 13 | `FastApiRouteComposer().compose(...)` → `resource_mount.set_enabled_web_modules` → `FastApiOpenApiSurface.bind()` | 挂载启用模块路由（带 `runtime.web.api_prefix` 前缀）；把实际挂载的模块名回写资源门面（供 `/system/info` 展示）；OpenAPI 文档懒构建并缓存。 |

`ApplicationContainer.stream_route_composer` 是业务流操作的显式扩展点。生产业务模块应构造
`StreamOperationBinding` 并交给该组合器；测试应用由 `StreamingTestRouteBinder` 绑定测试专用操作，
测试路径不会进入生产模块目录。组合器强制每个操作至少声明非流式 HTTP，并按
`SseDeliveryDetail` 与 WebSocket 声明注册可选传输，重复 operation name、路径或 OpenAPI operation ID
会在装配期失败。

当前装配器在 stream runtime 启用且 `admin_task` 模块已挂载时，通过
`AdminTaskStreamBindingFactory` 注册生产任务执行观察流：

- `/admin/tasks/executions/watch/batch`；
- `/admin/tasks/executions/watch/stream`；
- `/admin/tasks/executions/watch/ws`；
- `/admin/tasks/executions/watch/ticket`，仅在 `require_browser_ticket=true` 时存在。

这些路径统一叠加 `runtime.web.api_prefix`。测试工厂注册的 `/testing/stream/*` 只服务测试。

## 5. 任务绑定解析规则

`_resolve_task_bindings` 决定任务处理器来源，产出 `TaskBindingSource(bindings, strict)`：

| 入参组合 | bindings | strict | 语义 |
| --- | --- | --- | --- |
| `task_bindings=[...]`（测试/调用方显式注入） | 原样 | True | 严格模式：逐个直接注册；未声明 job_kind 会由 `TaskRegistrationRegistry.register_binding` 抛 500/`system.config.invalid`，重复 handler 同样失败。 |
| 仅 `task_binding_provider`（生产默认） | provider.build() | False | 宽松模式：只注册配置 `modules.task.registrations` 中已声明 job_kind 的绑定，未声明的静默跳过。 |
| 两者皆无 | 空 | False | 无绑定（纯 Web 节点也能启动；消费者节点会因缺处理器拒绝启动）。 |

业务项目新增任务的接线点就是 `ApplicationTaskBindingProvider.build()`：返回 `RegisteredTaskBinding(job_kind=..., payload_model=..., handler=...)`，job_kind 必须与 `config/modules/task_module/*.toml` 中的注册项一致。

## 6. 怎么用

- **生产/开发启动**：`python -m src.cli.run_web_server`，环境由 `APP_ENV` 决定；该入口会把 `runtime.stream` 的 WebSocket 大小、ping 和停机参数投影给 Uvicorn。
- **测试构建**：优先用 `TestAppFactory`（自动注入 SQLite 引擎工厂、测试覆盖与显式任务绑定），不要在测试里手工拼 `create_app` 参数。
- **CLI 复用**：`src/cli/run_task_worker.py` 展示了非 Web 进程复用装配器的方式——构建 app 后手动驱动 `resource_mount.startup()`/`shutdown()`；具体覆盖项以该 CLI 当前实现和生产配置为准，不应把示意 mapping 当作稳定调用签名。
- **新增用例接线**：`ApplicationContainer` 加字段 → `_build_application_container` 实例化 → `RouteDependencyContext` 加字段 → `read_route_context` 传值 → 补 `read_xxx_usecase` 读取器。五处缺一不可（漏了是启动期 TypeError）。
- **新增流操作接线**：定义命令和业务事件判别联合 → 实现 `StreamEventSourcePort` → 构造 `StreamOperationBindingEnvelope` 与传输适配器 → 通过 `container.stream_route_composer.compose()` 注册。三种交付必须复用同一事件源。
- **WebSocket 控制状态**：新连接首帧只允许 `subscribe` 或 `resume`；订阅运行中只允许 `cancel`、`ping`，中途恢复必须建立新连接。

## 7. 注意事项

- 装配阶段允许读取配置和初始化必要的本地对象，但禁止提前建立受 lifespan 管理的外部连接；若在 `__call__` 内加数据库、缓存、消息或出站 HTTP 连接，会破坏启动失败回收与测试隔离。
- `app.state.container` 是应用级长生命周期容器；`DependencyContextAccessor.read_route_context()` 每次请求从它取用例和 `resource_mount`，并通过 `resource_mount` 读取当前 runtime bundle。热更新后不要在路由对象中缓存 bridge/settings 快照。
- `app.state.ready` 只由 lifespan 翻转；不要在别处赋值，`/health/ready` 与 `/metrics` 的 `fastapi_runtime_ready` 都依赖它。
- `settings_overrides` 是深度合并（`SettingsMappingMerger`）——只覆盖给出的叶子键；但仍需通过全量 Pydantic 校验，覆盖出非法组合同样启动失败。
- `enable_openapi` 关闭时 `openapi_url/docs/redoc` 全为 None，`FastApiOpenApiSurface.bind()` 也直接返回；生产默认关闭（见 `config/app_production.toml`）。
- native EventSource 绑定必须提供与已认证票据签发路由相同的 `StreamAccessTicketService`；GET 只接受短期单次票据和 URL 编码强类型 command，禁止长期 JWT 查询参数。

## 8. 流资源 lifespan 顺序

进入 lifespan 时先执行 `resource_mount.startup()`，再执行异步
`resource_mount.startup_streaming()`；两者全部成功后才把 `app.state.ready` 置为 `True`。流运行时按
`runtime.stream.detail.kind` 构建内存或 Redis 状态存储，并创建四级配额会话注册表和单次票据服务。

退出或启动失败时先把 ready 置为 `False`，然后执行：

1. 会话注册表进入 draining，拒绝新连接；
2. 通知现有会话服务即将关闭；
3. 在 `shutdown_grace_seconds` 内等待租约清空；
4. 取消剩余会话并回收生成器/任务；
5. 关闭流状态存储；
6. 调用同步 `resource_mount.shutdown()` 释放其余共享资源。

该顺序保证 Redis 不会在仍有会话写入重放窗口时提前关闭，也保证应用 readiness 在排空开始前撤销。

## 9. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_fastapi_app_assembler_unit.py` | 默认/显式/provider 三种任务绑定行为。 |
| path | `test/path_test/test_fast_development_skeleton_path.py` | 测试工厂显式任务绑定与快速开发骨架路径。 |
| initialization | `test/initialization_test/test_runtime_initialization.py` | lifespan 与资源启动衔接。 |
| path | `test/path_test/test_runtime_path.py` | 中间件计划、容器资源与热更新运行路径。 |
| interface | `test/interface_test/test_http_interface.py` | 装配产物的 HTTP 表面与配置前缀。 |
| contract/interface | `test/contract_test/test_stream_contract.py`、`test/interface_test/test_streaming_*` | 流契约、三种交付、native EventSource 票据与 WebSocket 控制。 |
| initialization/integration | `test/initialization_test/test_streaming_runtime_initialization.py`、`test/integration_test/test_streaming_*` | local/Redis 初始化、真实 Redis、真实 Uvicorn SSE/WS 与资源回收。 |

## 10. 相关文档

- [项目文档总览](../README.md)
- [架构总览](../01_architecture/architecture_overview.md)
- [API 模块注册](api_module_registration.md)
- [运行时资源生命周期](../01_architecture/runtime_resource_lifecycle.md)
- [WebSocket 与 SSE 统一流式协议](../../design_docs/WebSocket与SSE统一流式协议.md)
