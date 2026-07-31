# FastAPI 统一 Web 基础设施实现规格

## 1. 文档定位
本规格用于 `E:\python_web_fastapi\work`，目标是为当前项目落地一套适合单机部署、便于后续快速扩展的 FastAPI Web 基础设施。

本规格覆盖以下内容：
- FastAPI 应用统一装配
- 生命周期统一管理
- Web 模块统一挂载
- 中间件统一接入
- 请求上下文统一管理
- 全局异常统一输出
- OpenTelemetry 统一接入方式
- Prometheus `/metrics` 指标出口
- Grafana 基于 Prometheus 数据源的接入说明
- 项目内配置、日志能力对接
- 测试代码与测试框架
- OAuth、鉴权、统一错误码
- ORM、缓存、MQ、任务队列实现
- 配置失败回滚、热更新失败治理、复杂异常策略

本规格采用“单机优先、接口先行、渐进扩展”的原则：
- 默认实现必须能在单机进程内直接运行，不依赖分布式治理平台。
- 对数据库、缓存、消息、任务、鉴权、观测性等能力保留扩展接口。
- 首版优先保证开发效率、可测试性、可观测性和清晰边界，不为了未来分布式场景提前引入过重抽象。

## 2. 目录命名修正

### 2.1 最终目录方案
Web 基建及相关运行时能力统一收口到：

`src/infrastructure`

其中 FastAPI Web 装配实现仍位于：

`src/infrastructure`

本规格固定以 `src/infrastructure` 作为基础设施总入口，Web 基建直接落在该目录下，不再增加 `web` 子目录。

### 2.2 采用原因
- `src/infrastructure` 更符合当前项目的真实边界，因为 Web、鉴权、持久化、缓存、消息、任务、测试支撑都属于基础设施层。
- Web 基建虽然是首批重点，但不应在顶层结构上凌驾于其他基础设施能力之上。
- Web 装配实现直接放在 `src/infrastructure`，可以减少无意义目录层级，符合当前项目从零搭建、单机优先的实际需求。
- 该目录体系适合统一收纳应用装配、路由编排、中间件链、生命周期、异常呈现、OpenAPI 控制、观测性接入以及外部依赖适配能力。

## 3. 文件命名约束
新增文件必须遵守以下规则：

- 禁止主文件名只使用单个泛词。
- 禁止以下命名作为主文件名：
  - `router.py`
  - `schemas.py`
  - `models.py`
  - `service.py`
  - `manager.py`
  - `middleware.py`
  - `utils.py`
- 文件名必须体现“场景 + 职责”或“领域 + 职责”。
- `__init__.py` 属于包约定，不受此限制。

推荐命名模式：
- API 入口：`asgi_entry.py`
- Web 模块清单：`web_bundle_catalog.py`
- 依赖访问器：`dependency_context_accessor.py`
- 路由文件：`route_<模块语义>.py`
- 契约文件：`contract_<模块语义>.py`
- 用例文件：`<模块语义>_usecase.py`
- Core 契约：`<对象语义>_contract.py`
- FastAPI 装配：`fastapi_<职责>.py`
- 中间件：`<职责>_middleware.py`
- 错误码目录：`<领域>_error_code.py`
- 鉴权策略：`<领域>_authorization_policy.py`
- 持久化映射：`<实体>_orm_model.py`
- 仓储实现：`<聚合>_repository_impl.py`
- 任务执行器：`<场景>_task_handler.py`

## 4. 配置文件命名修正

### 4.1 总原则
配置文件不再统一使用 `settings.*` 命名。

配置目录按三层拆分：

- 应用级配置：描述应用启动、模块启用、全局默认策略。
- 模块级配置：描述业务模块自身参数。
- 运行时配置：描述 Web、鉴权、数据库、缓存、消息、任务、观测性等技术运行时参数。

命名统一采用“语义前缀 + 环境后缀”方式，避免多个目录下出现大量重复的 `settings.toml`。

### 4.2 命名规则
基础命名规则如下：

- 应用级配置：
  - `app_base.toml`
  - `app_development.toml`
  - `app_production.toml`
  - `app_test.toml`
- 模块级配置：
  - `<module_name>_base.toml`
  - `<module_name>_development.toml`
  - `<module_name>_production.toml`
  - `<module_name>_test.toml`
- 运行时配置：
  - `<runtime_name>_base.toml`
  - `<runtime_name>_development.toml`
  - `<runtime_name>_production.toml`
  - `<runtime_name>_test.toml`

示例：
- `app_base.toml`
- `app_development.toml`
- `auth_module_base.toml`
- `system_module_development.toml`
- `web_runtime_base.toml`
- `database_runtime_production.toml`
- `task_runtime_test.toml`

### 4.3 配置目录层次图
```text
E:\python_web_fastapi\work
+---config
|   +---.env.example              # 已废弃，仅提示使用仓库根 .env.docker.example / .env.production.example
|   +---app_base.toml
|   +---app_development.toml
|   +---app_production.toml
|   +---app_test.toml
|   +---modules
|   |   +---system_module
|   |   |   +---system_module_base.toml
|   |   |   +---system_module_development.toml
|   |   |   +---system_module_production.toml
|   |   |   \---system_module_test.toml
|   |   +---auth_module
|   |   |   +---auth_module_base.toml
|   |   |   +---auth_module_development.toml
|   |   |   +---auth_module_production.toml
|   |   |   \---auth_module_test.toml
|   |   \---task_module
|   |       +---task_module_base.toml
|   |       +---task_module_development.toml
|   |       +---task_module_production.toml
|   |       \---task_module_test.toml
|   \---runtime
|       +---web_runtime
|       |   +---web_runtime_base.toml
|       |   +---web_runtime_development.toml
|       |   +---web_runtime_production.toml
|       |   \---web_runtime_test.toml
|       +---auth_runtime
|       |   +---auth_runtime_base.toml
|       |   +---auth_runtime_development.toml
|       |   +---auth_runtime_production.toml
|       |   \---auth_runtime_test.toml
|       +---database_runtime
|       |   +---database_runtime_base.toml
|       |   +---database_runtime_development.toml
|       |   +---database_runtime_production.toml
|       |   \---database_runtime_test.toml
|       +---cache_runtime
|       |   +---cache_runtime_base.toml
|       |   +---cache_runtime_development.toml
|       |   +---cache_runtime_production.toml
|       |   \---cache_runtime_test.toml
|       +---message_runtime
|       |   +---message_runtime_base.toml
|       |   +---message_runtime_development.toml
|       |   +---message_runtime_production.toml
|       |   \---message_runtime_test.toml
|       +---task_runtime
|       |   +---task_runtime_base.toml
|       |   +---task_runtime_development.toml
|       |   +---task_runtime_production.toml
|       |   \---task_runtime_test.toml
|       \---otel_runtime
|           +---otel_runtime_base.toml
|           +---otel_runtime_development.toml
|           +---otel_runtime_production.toml
|           \---otel_runtime_test.toml
```

### 4.4 使用原则
- 配置加载由项目内轻量配置组件负责，推荐基于 `pydantic-settings`、`tomllib` 和类型化配置对象实现。
- 配置解析顺序建议为 `.env` / 环境变量覆盖 `app_*`，再由应用级配置决定加载哪些模块级和运行时配置。
- 模块级配置只描述业务模块参数，不承载数据库连接、消息 broker 地址、缓存后端等运行时细节。
- 运行时配置只描述技术能力参数，不反向耦合具体业务模块。
- 单机场景默认采用 `base + 环境文件` 的静态装载方式，并允许在应用启动时一次性完成组合。
- 配置热更新只允许作用于安全项，例如日志级别、开关类特性、限流阈值、缓存 TTL。
- 涉及连接串、密钥、进程级资源池大小、ORM engine 初始化参数等高风险项时，默认要求重启生效。
- 热更新执行顺序必须为“读取 -> 校验 -> 构造候选配置 -> 预检查 -> 原子切换 -> 失败回滚 -> 记录事件”。
- 回滚目标必须是最近一次已验证通过的配置快照。
- 配置中的密码、密钥等敏感字段应使用秘密类型承载；对外展示可以脱敏，但热更新差异比对与配置摘要计算必须基于真实值。
- 推荐由 `app_base.toml` 控制模块启停和运行时后端选择。当前源码中数据库后端已冻结为 `postgresql`，缓存支持 `memory` / `redis`，消息总线支持 `local` / `rabbitmq`。
- 逻辑命名空间应清晰区分为：
  - `app`
  - `modules/*`
  - `runtime/*`

## 5. 推荐文件层次图
```text
E:\python_web_fastapi\work
+---config
|   +---.env.example              # 已废弃，仅提示使用仓库根 .env.docker.example / .env.production.example
|   +---app_base.toml
|   +---app_development.toml
|   +---app_production.toml
|   +---app_test.toml
|   +---modules
|   |   +---system_module
|   |   +---auth_module
|   |   \---task_module
|   \---runtime
|       +---web_runtime
|       +---auth_runtime
|       +---database_runtime
|       +---cache_runtime
|       +---message_runtime
|       +---task_runtime
|       \---otel_runtime
+---docs
|   \---design_docs
|       \---FastAPI统一Web基础设施实现规格.md
+---src
|   +---__init__.py
|   +---main.py
|   +---api
|   |   +---__init__.py
|   |   +---asgi_entry.py
|   |   +---web_bundle_catalog.py
|   |   +---dependency_context_accessor.py
|   |   +---endpoint_health_probe
|   |   |   +---__init__.py
|   |   |   +---route_health_probe.py
|   |   |   \---contract_health_probe.py
|   |   +---endpoint_system_overview
|   |   |   +---__init__.py
|   |   |   +---route_system_overview.py
|   |   |   \---contract_system_overview.py
|   |   \---endpoint_auth_access
|   |       +---__init__.py
|   |       +---route_auth_access.py
|   |       \---contract_auth_access.py
|   +---application
|   |   +---__init__.py
|   |   +---health_probe_usecase.py
|   |   +---system_overview_usecase.py
|   |   +---issue_access_token_usecase.py
|   |   +---refresh_access_token_usecase.py
|   |   +---revoke_access_token_usecase.py
|   |   \---dispatch_background_job_usecase.py
|   +---core
|   |   +---__init__.py
|   |   +---http_contract
|   |   |   +---__init__.py
|   |   |   +---request_scope_contract.py
|   |   |   +---response_envelope_contract.py
|   |   |   +---runtime_resource_contract.py
|   |   |   \---web_bundle_contract.py
|   |   +---exception_contract
|   |   |   +---__init__.py
|   |   |   +---http_fault_contract.py
|   |   |   \---error_code_catalog_contract.py
|   |   +---auth_contract
|   |   |   +---__init__.py
|   |   |   +---authenticated_principal_contract.py
|   |   |   +---token_payload_contract.py
|   |   |   \---authorization_policy_contract.py
|   |   +---persistence_contract
|   |   |   +---__init__.py
|   |   |   +---unit_of_work_contract.py
|   |   |   +---repository_contract.py
|   |   |   \---transaction_scope_contract.py
|   |   +---cache_contract
|   |   |   +---__init__.py
|   |   |   \---cache_store_contract.py
|   |   \---task_contract
|   |       +---__init__.py
|   |       +---message_bus_contract.py
|   |       +---task_dispatcher_contract.py
|   |       \---task_handler_contract.py
|   +---domain
|   |   +---__init__.py
|   |   \---auth
|   |       +---__init__.py
|   |       +---auth_error_code.py
|   |       \---access_token_policy.py
|   \---infrastructure
|       +---__init__.py
|       +---settings
|       |   +---__init__.py
|       |   +---app_settings_loader.py
|       |   +---settings_snapshot_store.py
|       |   \---settings_reload_coordinator.py
|       +---logging
|       |   +---__init__.py
|       |   \---app_logger_factory.py
|       +---context
|       |   +---__init__.py
|       |   \---request_context_manager_impl.py
|       +---auth
|       |   +---__init__.py
|       |   +---jwt_token_service.py
|       |   +---oauth2_scheme_provider.py
|       |   +---authorization_policy_evaluator.py
|       |   \---password_hasher.py
|       +---persistence
|       |   +---__init__.py
|       |   +---sqlalchemy_engine_factory.py
|       |   +---sqlalchemy_session_factory.py
|       |   +---alembic_runner.py
|       |   \---repository_impl
|       +---cache
|       |   +---__init__.py
|       |   +---memory_cache_store.py
|       |   \---redis_cache_store.py
|       +---task
|       |   +---__init__.py
|       |   +---local_message_bus.py
|       |   +---local_task_dispatcher.py
|       |   +---failed_task_recorder.py
|       |   \---task_worker_supervisor.py
|       +---fastapi_app_assembler.py
|       +---fastapi_route_composer.py
|       +---fastapi_middleware_plan.py
|       +---fastapi_exception_presenter.py
|       +---fastapi_lifespan_orchestrator.py
|       +---fastapi_openapi_surface.py
|       +---fastapi_otel_bridge.py
|       +---shared_resource_mount.py
|       +---middleware_chain
|       |   +---__init__.py
|       |   +---access_log_middleware.py
|       |   +---elapsed_probe_middleware.py
|       |   +---payload_guard_middleware.py
|       |   +---request_scope_middleware.py
|       |   +---security_header_middleware.py
|       |   \---authentication_binding_middleware.py
|       +---resource_slot
|       |   +---__init__.py
|       |   +---shared_http_client.py
|       |   \---shared_db_session_manager.py
|       \---testing
|           +---__init__.py
|           +---test_app_factory.py
|           +---fake_clock.py
|           +---fake_message_bus.py
|           \---fake_cache_store.py
\---test
    +---__init__.py
    +---conftest.py
    +---boundary_test
    +---class_inheritance_test
    +---contract_test
    +---convention_usage_test
    +---exception_test
    +---initialization_test
    +---integration_test
    +---interface_test
    +---path_test
    \---unit_test
```

## 6. 分层职责

### 6.1 api 层
职责：
- 提供 HTTP 路由入口
- 定义请求响应契约
- 进行参数绑定、鉴权依赖绑定、响应模型约束
- 调用 application 用例
- 导出 Web 模块清单

约束：
- 不初始化基础设施资源
- 不直接装配应用生命周期
- 不直接读取配置文件
- 不直接访问 ORM engine、缓存客户端、任务队列实例

### 6.2 application 层
职责：
- 提供健康探针、系统概览、认证、任务派发等用例
- 处理 Web 层之上的应用编排
- 统一事务边界、鉴权结果消费、错误码映射

约束：
- 不依赖 FastAPI `Request`、`Response`
- 不依赖 `app.state`
- 不直接依赖具体 ORM、缓存、MQ 框架

### 6.3 core 层
职责：
- 定义请求上下文契约
- 定义统一响应契约
- 定义共享资源契约
- 定义 Web 模块契约
- 定义 HTTP 故障契约
- 定义错误码目录契约
- 定义鉴权、持久化、缓存、任务分发相关契约
- 定义可观测性运行时契约

约束：
- 不放 FastAPI 运行时代码
- 不放 OpenTelemetry 初始化代码
- 不放 Prometheus 指标采集实现
- 不放具体第三方框架适配实现

### 6.4 infrastructure 层
职责：
- 实现配置加载、热更新协调与日志初始化
- 实现 RequestContextManager
- 实现 FastAPI Web 基建装配
- 实现中间件链、异常呈现、生命周期、OpenAPI 控制、OTel 接入、Prometheus 指标出口
- 实现 JWT/OAuth2 适配、ORM engine/session、缓存存储、消息与任务调度
- 实现测试替身、测试工厂和基础 fixture

约束：
- 不承载业务规则
- 不引入与单机场景不匹配的分布式基础设施前提
- 默认实现必须可在本机直接运行；当前源码要求 PostgreSQL 可用，Redis 与 RabbitMQ 仍为按运行时后端选择的可选适配

## 7. 关键组件

### 7.1 RequestContextManager
位置：
- `src/infrastructure/context/request_context_manager_impl.py`

职责：
- 从请求提取上下文
- 生成或透传 `request_id`
- 在启用观测性时读取 `trace_id`
- 写入 `ContextVar`
- 写入 `request.state`
- 请求结束后清理上下文

### 7.2 FastAPI App Assembler
位置：
- `src/infrastructure/fastapi_app_assembler.py`

职责：
- 创建 FastAPI 应用
- 装配配置对象与日志能力
- 装配共享资源
- 装配中间件
- 装配异常处理器
- 装配路由
- 按 `runtime.metrics.header.enabled` 装配 Prometheus `/metrics` 路由与 HTTP 指标中间件
- 将 `runtime.web.api_prefix` 传入路由装配器
- 向健康探针、系统概览、签发令牌等公共用例注入窄 `Protocol` 运行时端口
- 装配生命周期
- 返回最终 `app`

### 7.3 Route Composer
位置：
- `src/infrastructure/fastapi_route_composer.py`

职责：
- 接收显式 Web 模块清单
- 按 `app.modules.enabled` 过滤模块
- 统一应用 `runtime.web.api_prefix`
- 对 `""`、`"/"`、尾随斜杠做归一化后再挂载
- 挂载路由并返回实际已装配模块清单

### 7.4 Middleware Plan
位置：
- `src/infrastructure/fastapi_middleware_plan.py`

职责：
- 统一中间件接入顺序
- 按配置启用可选中间件
- 仅在 `runtime.web.enable_access_log = true` 时装配 `AccessLogMiddleware`
- 统一插入认证绑定、请求体限制、安全头、访问日志等横切能力

### 7.5 Exception Presenter
位置：
- `src/infrastructure/fastapi_exception_presenter.py`

职责：
- 输出统一错误结构
- 附带 `trace_id`
- 附带统一错误码
- 控制错误 detail 暴露
- 将领域异常、应用异常、基础设施异常映射到稳定 HTTP 响应

### 7.6 Lifespan Orchestrator
位置：
- `src/infrastructure/fastapi_lifespan_orchestrator.py`

职责：
- 启动阶段初始化共享资源
- 关闭阶段释放共享资源
- 共享资源默认限定为单进程内可管理对象，例如 HTTP Client、数据库连接池、缓存客户端、任务 worker
- 当资源初始化失败时阻止应用进入 ready 状态

### 7.7 OTel Bridge
位置：
- `src/infrastructure/fastapi_otel_bridge.py`

职责：
- 在启用时初始化 OpenTelemetry
- 提供 trace 读取桥接
- 与请求上下文联动
- 在未启用时提供 no-op 实现，避免将观测性变成项目启动硬依赖

### 7.8 Prometheus Metrics
位置：
- `src/core/observability_contract/metrics_runtime_contract.py`
- `src/infrastructure/observability/prometheus_metrics_registry.py`
- `src/infrastructure/observability/prometheus_metrics_route.py`

职责：
- 通过 `runtime.metrics` 提供公共头字段 + 强类型扩展字段的指标运行时配置
- 在开启时暴露 `/metrics` Prometheus 文本出口
- 记录 HTTP 方法、低基数路由模板、状态码和耗时
- 输出应用 ready 状态
- 不记录完整 URL、请求体、Authorization、JWT、password、secret、token
- Grafana 仅通过 Prometheus 数据源消费指标，不直接接入应用代码

### 7.9 Auth Runtime
位置：
- `src/infrastructure/auth`

职责：
- 提供 OAuth2 Bearer 接入
- 提供 JWT access token / refresh token 生成与校验
- 提供密码散列、principal 解析、scope/role 校验
- 受控 bootstrap 管理员通过 `AUTH_BOOTSTRAP_ADMIN_PASSWORD` 注入明文，并在应用启动时写入数据库 Argon2 散列
- access token 的主体恢复以“已校验 JWT `sub/sid` + 会话状态 + 数据库当前授权快照”为准
- bootstrap 管理员配置统一采用 `role_bindings` 判别联合扩展体，不再使用平铺 `roles/scopes`
- 正式认证与授权统一基于数据库用户、角色、scope 与 refresh token 会话
- 为后续外部 OAuth Provider 预留适配接口，但首版不强制实现第三方登录

### 7.9 Error Code Catalog
位置：
- `src/core/exception_contract/error_code_catalog_contract.py`
- `src/domain/*/*_error_code.py`

职责：
- 统一定义错误码格式，推荐 `<domain>.<scenario>.<reason>`
- 明确错误码稳定性要求，禁止在无迁移说明的情况下随意改码
- 为 HTTP 响应、日志、任务失败记录、审计日志提供统一错误标识

### 7.10 ORM Runtime
位置：
- `src/infrastructure/persistence`

职责：
- 采用 SQLAlchemy 2.x 作为 ORM 基础
- 使用 Alembic 管理 schema migration
- 提供 engine、session factory、事务边界和 repository 实现
- UoW 是唯一事务边界，负责 `commit()`、`rollback()`、`flush()` 和 `dispose()`
- Repository 只消费 UoW 暴露的会话执行读写，禁止在仓储实现中自行 `commit()` 或 `rollback()`
- Repository 可以通过 `flush()` 暴露数据库约束错误；仅已冻结的幂等写入场景允许在 `SAVEPOINT` 边界内识别指定唯一约束冲突并回查既有记录，其他 `IntegrityError` 继续向上抛出
- `TaskExecutionRecordRepositoryImpl.upsert()` 当前采用插入优先、`SAVEPOINT` 冲突回查语义；历史“预查询命中复用”和“catch + rollback + query”描述已过期
- 当前运行时仅支持 PostgreSQL，统一通过 `psycopg` 驱动与 Alembic 迁移入口接入

### 7.11 Cache Runtime
位置：
- `src/infrastructure/cache`

职责：
- 提供 `CacheStore` 统一接口
- 提供 `CacheService` 作为缓存统一入口，负责键构造、信封编解码、TTL 策略解析与 Redis 不可用策略处理
- 缓存值采用“公共头字段 + 强类型扩展字段”模式；扩展体使用 Pydantic 判别联合，且启用 `extra="forbid"`
- 缓存策略采用 `CachePolicyEnvelope`，公共头包含 `kind`、`schema_version`、`detail_kind`、`namespace`，扩展字段按 `kind` 判别并校验外层内层一致
- `CacheRuntimeSettings.namespace_policies` 装载 `AUTH_THROTTLE`、`RATE_LIMIT`、`QUERY_RESULT` 等命名空间策略，`CachePolicyResolver` 负责解析默认 TTL 与故障模式
- 缓存 key 固定为 `key_prefix:namespace:segment...`，前缀和片段不能为空，片段不得包含 `:`，调用方不得直接写入令牌、密码等敏感原文
- TTL 优先级固定为：请求显式 TTL > 命名空间策略默认 TTL > `runtime.cache.default_ttl_seconds`
- Redis 不可用时按命名空间策略处理：认证、鉴权、限流类缓存 fail-closed，继续抛出 `system.cache.unavailable`；普通查询缓存可 fail-open，读取按未命中处理，写入和删除记录告警后跳过
- 缓存不可用日志只记录命名空间与键摘要，不输出令牌、密码、密钥或完整 Redis URL
- 当前缓存扩展体首个落地点为 `AuthThrottleStatePayload`
- 默认实现为进程内内存缓存，支持 TTL、命名空间、最大条目数与线程安全访问
- 可选实现为单机 Redis 适配，用于需要跨进程共享缓存时切换；Redis 适配仍把底层异常转换为 `system.cache.unavailable`
- 当前实际源码已以 `cache_runtime_base.toml` + `cache_runtime_test.toml` 收口缓存配置；若历史文档与源码冲突，以源码为准，旧文档可能过期

### 7.12 Message And Task Runtime
位置：
- `src/infrastructure/task`

职责：
- 提供消息发布与任务派发统一接口
- 默认实现为单进程本地消息总线和本地任务调度器
- 支持失败重试、最大重试次数、失败记录
- 短任务优先走本地任务队列，重任务或跨进程任务保留外部 broker 扩展点

### 7.13 Settings Reload Coordinator
位置：
- `src/infrastructure/settings/settings_reload_coordinator.py`

职责：
- 协调配置热更新流程
- 管理最近一次成功配置快照
- 在预检查失败时回滚
- 记录配置变更事件、失败原因和恢复结果

### 7.14 Test Harness
位置：
- `src/infrastructure/testing`
- `test`

职责：
- 提供测试应用工厂、fixture、fake adapter、测试数据准备入口
- 支持 unit、integration、api 三层测试
- 为鉴权、ORM、缓存、任务、配置热更新提供可替换测试实现

## 8. 首批 Web 模块

### 8.1 健康探针模块
目录：
- `src/api/endpoint_health_probe`

路由：
- `GET /health/live`
- `GET /health/ready`

### 8.2 系统概览模块
目录：
- `src/api/endpoint_system_overview`

路由：
- `GET /system/info`

### 8.3 认证访问模块
目录：
- `src/api/endpoint_auth_access`

路由：
- `POST /auth/token`
- `POST /auth/refresh`
- `POST /auth/revoke`
- `GET /auth/me`

## 9. 请求处理链路
标准处理顺序如下：

1. 请求进入应用
2. 建立 `request_id`，并在启用观测性时关联 `trace_id`
3. 建立请求上下文
4. 执行请求体限制
5. 完成认证信息提取与 principal 绑定
6. 追加安全响应头
7. 记录访问日志与耗时
8. 路由处理
9. application 用例执行
10. 在需要时开启事务、访问仓储、缓存或任务调度器
11. 异常统一映射为错误码和标准错误响应
12. 返回响应
13. 清理请求上下文

当前 `PayloadGuardMiddleware` 已改为真实前置防护：
- 先基于 `Content-Length` 做超限预拒绝。
- 对无 `Content-Length`、分块传输或伪造较小 `Content-Length` 的请求，按 ASGI `receive` 流式累计并在超限时立即中断。
- 超限响应继续复用统一 envelope 与 `413 Request Entity Too Large`。
- 旧的“先读完整 body 再判断”描述已过期，不再适用于当前源码。

当前访问日志也是条件装配：
- 只有 `runtime.web.enable_access_log = true` 时才会挂载 `AccessLogMiddleware`。
- 旧的“配置已声明但运行时未生效”描述已过期，不再适用于当前源码。

当前并发治理策略不是“全量 async”，而是“同步主干 + 显式桥接 + 局部异步资源”：
- `route_health_probe.py`、`route_system_overview.py`、`route_auth_access.py` 仍保持 `async` 路由签名，但同步 usecase 不再在事件循环中直接执行。
- `src/infrastructure/request_execution_bridge.py` 负责把同步阻塞链路按 `runtime.web.request_execution` 策略卸载到线程池，统一收口超时与异常语义。
- `authentication_binding_middleware.py` 中的主体恢复也通过同一桥接器执行，避免认证阶段的同步数据库访问阻塞事件循环。
- `runtime.web.outbound_http_client` 负责显式区分 `sync_http` 与 `async_http`；默认仍保留同步 HTTP 客户端，只有明确的高并发外部 HTTP 边界才切到异步客户端。
- 数据库、缓存、`funboost + RabbitMQ` 任务链路当前仍保持同步主干；若未来某个 I/O 边界需要 async 化，必须继续沿用“显式契约 + 局部接入”模式。

后台任务标准处理顺序如下：

1. 任务被 application 层派发
2. Task Dispatcher 记录任务元信息
3. Task Worker 执行任务处理器
4. 成功则记录完成状态
5. 失败则按策略重试
6. 超过重试上限则写入失败记录并附带错误码

## 10. 暂不纳入内容
- 分布式服务注册与服务发现
- Service Mesh
- 多租户隔离体系
- 跨地域多活部署
- 分布式 Saga / 工作流编排平台
- 第三方 OAuth 登录提供商的首版具体适配实现

## 11. 给 AI 的明确指令
- 基础设施代码统一收口在 `src/infrastructure`，Web 装配实现直接放在该目录下。
- 配置目录固定采用 `config/app_* + config/modules/* + config/runtime/*` 三层结构，不再使用 `settings.*`。
- 生成代码时不得退回 `router.py`、`schemas.py`、`manager.py` 这类单泛词文件名。
- 必须同时生成测试代码，至少覆盖 unit、integration、api 三层中的合理子集。
- 认证体系首版采用 OAuth2 Bearer + JWT access/refresh token 方案，外部 OAuth Provider 仅保留扩展接口。
- 必须提供统一错误码目录，并保证错误响应中稳定输出错误码、消息、`request_id`、`trace_id`。
- ORM 首版采用 SQLAlchemy 2.x + Alembic，运行时统一使用 PostgreSQL。
- 缓存首版默认提供内存实现，并预留 Redis 适配位。
- 消息与任务首版默认提供本地消息总线和本地任务调度器，不强依赖外部 broker。
- 配置部分必须支持“校验 -> 预检查 -> 原子切换 -> 失败回滚”的热更新治理链路。
- OpenTelemetry 属于可选能力，默认不应阻塞单机项目启动。
- Prometheus metrics 属于可选能力，默认关闭；开启后 `/metrics` 不进入统一 JSON 响应信封。
- 当前不内置 Grafana、Prometheus、Loki、Tempo、Promtail、Alertmanager 部署栈。

## 12. 2026-05-15 实际落地回归

### 12.1 实际配置层次

当前源码实际使用的配置层次如下，以下内容覆盖前文中未落地的环境模板描述：

```text
config/
  .env.example  # 已废弃，仅保留跳转说明
  app_base.toml
  app_development.toml
  app_test.toml
  modules/
    auth_module/
      auth_module_base.toml
      auth_module_development.toml
      auth_module_test.toml
    system_module/
      system_module_base.toml
    task_module/
      task_module_base.toml
  runtime/
    auth_runtime/
      auth_runtime_base.toml
      auth_runtime_test.toml
    cache_runtime/
      cache_runtime_base.toml
      cache_runtime_test.toml
    database_runtime/
      database_runtime_base.toml
      database_runtime_development.toml
      database_runtime_production.toml
      database_runtime_test.toml
    message_runtime/
      message_runtime_base.toml
    metrics_runtime/
      metrics_runtime_base.toml
      metrics_runtime_production.toml
      metrics_runtime_test.toml
    otel_runtime/
      otel_runtime_base.toml
    logging_runtime/
      logging_runtime_base.toml
      logging_runtime_test.toml
    security_runtime/
      security_runtime_base.toml
    task_runtime/
      task_runtime_base.toml
    web_runtime/
      web_runtime_base.toml
```

### 12.2 实际统一 HTTP 契约

当前统一响应采用嵌套头字段模式：

```json
{
  "header": {
    "code": "system.success.ok",
    "message": "中文消息",
    "request_id": "uuid",
    "trace_id": null
  },
  "data": {
    "kind": "health_probe",
    "schema_version": "1.0"
  }
}
```

统一错误扩展体实际字段如下：

```json
{
  "kind": "http_fault",
  "schema_version": "1.0",
  "status_code": 401,
  "error_code": "auth.token.invalid"
}
```

当前错误响应不再向客户端输出 `detail`。历史文档中“错误扩展体包含可选 detail”的描述已经过期；内部异常类名、堆栈、连接串、SQL、JWT、密码和配置路径只允许进入结构化日志。

认证主体与令牌扩展体以如下字段为准：

- `AuthenticatedPrincipal`: `kind`、`schema_version`、`subject_id`、`username`、`roles`、`scopes`、`is_admin`
- `AuthenticatedPrincipal` 的实际来源是 `已校验 JWT 主体 + token_session_id 会话校验 + 数据库授权快照`
- `TokenPayload`: `token_id`、`token_session_id`、`subject_id`、`username`、`roles`、`scopes`、`token_use`、`issued_at_epoch`、`expires_at_epoch`
- `TokenIssuePayload`: `access_token`、`refresh_token`、`token_type`、`expires_in_seconds`、`refresh_expires_in_seconds`
- `TokenRevokePayload`: `revoked`、`revoked_at_epoch`
- `RefreshTokenSessionPayload`: `refresh_token_id`、`token_session_id`、`user_id`、`subject_id`、`issued_at`、`expires_at`、`revoked_at`、`rotated_to_token_id`
- `app.modules.enabled`: `health_probe`、`system_overview`、`auth_access`
- `BootstrapRoleBindingV1`: `kind`、`schema_version`、`role_key`、`scope_codes`

任务消息实际契约采用“公共头 + 强类型扩展字段”模式：

```json
{
  "header": {
    "message_id": "uuid",
    "created_at_epoch": 1778819180
  },
  "payload": {
    "kind": "task_message",
    "schema_version": "1.0",
    "job_kind": "demo_task",
    "deduplication_key": "uuid",
    "retry_limit": 2,
    "payload_kind": "DemoTaskPayload",
    "payload_json": "{\"task_id\":\"usage-task\"}"
  }
}
```

### 12.3 实际测试入口与结果

本次真实执行入口与结果如下：

1. `python -m compileall src test`：通过
2. 本地 PostgreSQL 测试实例初始化并创建 `fastapi_web_skeleton_test`：通过
3. `pytest test/unit_test test/path_test test/boundary_test -q`：通过，`32 passed`
4. `pytest test/interface_test test/integration_test test/convention_usage_test -q`：通过，`16 passed`
5. `pytest -q`：全量通过，`78 passed`
6. 基于测试配置的烟雾验证：`/health/live`、`/auth/token`、`/auth/me` 均返回成功

### 12.4 实际落地说明

- 当前任务队列基建已形成双后端结构：`local` 继续承载单机回退与测试路径，`funboost + RabbitMQ` 作为真实生产路径。
- 当前任务注册已迁移为显式注册中心，注册项采用“公共头字段 + 强类型扩展字段”模式，扩展字段使用 Pydantic 判别联合，并要求 `kind`、`schema_version`、`extra="forbid"`。
- 当前 `RabbitMqMessageGateway` 已从单纯 URL 校验升级为连接参数校验与健康探测，`SharedResourceMount` 会按 `runtime.task.backend` 选择装配 `LocalTaskDispatcher` 或 `FunboostTaskDispatcher`。
- 历史文档中若仍出现“funboost 仅预留位”或“RabbitMQ 只做校验”的描述，视为过期，按当前源码为准。
- 当前未新增独立任务 HTTP 接口，任务派发通过应用用例与集成测试验证闭环。
- 当前 `app.modules.enabled` 会真实影响 Web 模块装配，并由系统概览返回实际已挂载模块清单。
- 当前 bootstrap 管理员配置示例应使用 `role_bindings`，旧的平铺 `roles/scopes` 文档若仍存在，视为过期。

### 12.5 2026-05-16 Web 主链路收口补记

本节覆盖当前源码在排除统一 HTTP 客户端、消息队列、任务队列、缓存、热更新后的最新收口状态；若与前文历史记录冲突，以当前源码与本节为准，`12.3` 仅表示 `2026-05-15` 的历史验收记录，不代表当前机器上的即时验收结果。

- 请求体保护已改为 ASGI 级前置/流式限额实现，不再通过 `request.body()` 先完整读入内存后再返回 `413`。
- `runtime.web.api_prefix` 已真实参与路由挂载；`""` 与 `"/"` 会归一为根路径，尾随斜杠会被去除。
- `runtime.web.enable_access_log` 已真实控制访问日志中间件是否装配。
- `runtime.logging` 已作为唯一日志运行时配置入口，承载 `enabled`、`level`、`sink`、`buffer_max_items` 与 `sink_detail`，不再保留 `app.logging`。
- 访问日志、异常日志、资源生命周期日志已统一收敛为 `header + detail` 结构化事件，并通过数据库日志写入器、缓冲派发器与结构化日志处理器落库到 `app_log_record`。
- `app_log_record` 已提供 `occurred_at`、`event_kind`、`request_id`、`trace_id`、`level` 索引，当前可按时间、级别、类型与链路字段检索。
- 当前日志失败策略为：优先批量写库；写库失败时按配置降级为标准错误输出；日志失败不改变 HTTP 响应语义。
- `HealthProbeUsecase`、`SystemOverviewUsecase`、`IssueAccessTokenUsecase`、`AuthorizationGuard` 的公共构造入口已改为显式窄 `Protocol` 依赖，不再暴露未标注的宽容器参数。
- `config/runtime/web_runtime/web_runtime_base.toml` 当前使用 `[runtime]` 表示该目录下的 Web 运行时片段，`api_prefix = ""` 与 `enable_access_log = true` 的示例含义已经与运行时实现保持一致。
- `2026-05-16` 本地真实测试结果为：`python -m compileall src test` 通过；非数据库定向回归通过；所有依赖 PostgreSQL 测试实例的分组在启动期均因 `127.0.0.1:55432` 连接超时而阻塞。
- 因此，当前源码在收窄范围内已完成主链路收口，但当前机器上仍缺少 PostgreSQL 可达条件下的最终端到端验收证明。

### 12.6 2026-05-18 数据库日志基建补记

- 本次真实执行已启动 `compose.yml` 中的 PostgreSQL 与 Redis 依赖容器，并基于项目 `.venv` 完成日志基建回归。
- 当前真实测试结果为：
  1. `python -m compileall src test`：通过
  2. `pytest test/contract_test/test_logging_contract.py test/path_test/test_logging_runtime_path.py -q`：通过，`7 passed`
  3. `pytest test/unit_test/test_logger_factory_unit.py test/unit_test/test_log_writer_unit.py test/initialization_test/test_logging_initialization.py -q`：通过，`6 passed`
  4. `AlembicRunner.upgrade_head(...)` 基于测试库执行迁移：通过
  5. `pytest test/exception_test/test_logging_exception_path.py test/integration_test/test_database_logging_integration.py test/integration_test/test_app_integration.py -q`：通过，`6 passed`
  6. `pytest -q`：全量通过，`123 passed`
- 当前测试环境仍会出现 `passlib` 访问 `argon2.__version__` 的上游弃用告警，但不影响本次日志基建功能与回归结论。

### 12.7 2026-05-20 Funboost + RabbitMQ 任务队列基建回归

- 本节覆盖 `funboost + RabbitMQ` 任务队列基建的最新真实落地结果；若与 `12.3`、`12.6` 或其他历史记录冲突，以当前源码与本节为准，旧记录仅代表当时的阶段性验收结果。
- 当前任务队列基建已经完成显式任务注册、任务级独立配置、统一装配入口、`local` 回退链路、`funboost + RabbitMQ` 真实发布路径、启动探测、失败记录与结构化日志收口。
- 任务相关契约统一采用“公共头字段 + 强类型扩展字段”模式；扩展字段使用 Pydantic 判别联合，要求 `kind`、`schema_version` 且启用 `extra="forbid"`。
- `SharedResourceMount` 当前会基于 `runtime.task.backend` 在启动阶段选择 `LocalTaskDispatcher` 或 `FunboostTaskDispatcher`，并复用统一任务注册中心与任务绑定装配链路。
- 当前真实执行结果为：
  1. `python -m compileall src test`：通过
  2. `pytest test/contract_test/test_task_registration_contract.py test/contract_test/test_logging_contract.py test/unit_test/test_task_registration_registry_unit.py test/unit_test/test_funboost_task_dispatcher_unit.py test/unit_test/test_rabbitmq_message_gateway_unit.py -q`：通过，`22 passed`
  3. `pytest test/path_test/test_task_runtime_path.py test/boundary_test/test_runtime_boundary.py test/initialization_test/test_task_runtime_initialization.py test/exception_test/test_runtime_exception.py -q`：通过，`31 passed`
  4. `docker compose up -d postgres redis rabbitmq`：通过
  5. `pytest test/integration_test/test_funboost_rabbitmq_integration.py test/integration_test/test_app_integration.py test/convention_usage_test/test_end_to_end_usage.py -q`：通过，`9 passed`
  6. `pytest -q`：全量通过，`150 passed`
  7. 在补充回归修复与关闭路径单测后，`pytest test/unit_test/test_funboost_task_dispatcher_unit.py test/initialization_test/test_task_runtime_initialization.py -q`：通过，`9 passed`
  8. 回归收口后的 `pytest -q`：全量通过，`151 passed`
- 当前仍存在一个第三方残余风险：`funboost` 在解释器退出期会触发 `publishers.base_publisher._at_exit` 日志，表现为 `ValueError: I/O operation on closed file.`。该问题不影响 `pytest` 退出码与断言结果，但在彻底修复前仍应视为退出期日志噪声。

### 12.8 2026-05-21 局部异步化与同步主干保留回归

- 本节覆盖当前源码对“是否要全量改 async”的最终落地结论；若与前文任何历史描述冲突，以本节与当前源码为准，旧描述仅代表历史阶段性判断。
- 当前项目没有迁移为全异步架构，实际落地的是：
  1. Web 入口保持 `async`；
  2. 同步 usecase、同步数据库访问、同步缓存访问、同步任务派发通过 `RequestExecutionBridge` 在线程池执行；
  3. 共享外部 HTTP 资源支持 `sync_http` / `async_http` 双模式，但默认仍为 `sync_http`。
- 当前真实生效的新增运行时配置位于：
  - `config/runtime/web_runtime/web_runtime_base.toml`
  - `config/runtime/web_runtime/web_runtime_test.toml`
- 当前 `runtime.web` 已新增并实际使用以下契约字段：
  - `request_execution.envelope_kind`
  - `request_execution.header.execution_name`
  - `request_execution.header.enabled`
  - `request_execution.header.mode`
  - `request_execution.detail.kind`
  - `request_execution.detail.offload_timeout_seconds`
  - `request_execution.detail.propagate_cancellation`
  - `outbound_http_client.envelope_kind`
  - `outbound_http_client.header.client_name`
  - `outbound_http_client.header.enabled`
  - `outbound_http_client.header.mode`
  - `outbound_http_client.detail.kind`
  - `outbound_http_client.detail.timeout_seconds`
  - `outbound_http_client.detail.max_connections`
  - `outbound_http_client.detail.max_keepalive_connections`
- 当前 `SharedResourceMount` 已统一装配以下与本次任务直接相关的资源：
  - `get_request_execution_bridge()`
  - `get_http_client()`
  - `get_async_http_client()`
- 当前源码中未发现必须迁移到异步 HTTP 客户端的真实外部 HTTP 调用点，因此 `async_http` 能力已落地，但仍保持按需接入，而不是为了“全异步”而强制扩散。
- 本次真实执行结果为：
  1. `.\.venv\Scripts\python.exe -m compileall src test`：通过
  2. 契约定向测试：通过，`6 passed`
  3. 单元 + 路径定向测试：通过，`7 passed`
  4. 初始化 + 集成 + 用法规约定向测试：通过，`11 passed`
  5. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器健康
  6. `test/integration_test/test_funboost_rabbitmq_integration.py -q`：通过，`2 passed`
  7. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`168 passed`
- 当前仍有一个第三方残余现象：`funboost` 在解释器退出期可能输出 `publishers.base_publisher._at_exit` 的 `stderr` 关闭日志噪声。该问题不影响测试退出码与断言结果，当前按第三方退出期日志噪声记录，不作为本次交付失败条件。

### 12.9 2026-05-21 快速开发阶段收口硬迁移最终回归

- 本节覆盖 `docs/2026_5_21_快速开发阶段收口硬迁移拆解/` 对应硬迁移方案的最终落地结果；若与前文历史阶段记录冲突，以本节与当前源码为准，旧记录可能过期。
- 热更新链路已经冻结为“候选资源先构建 -> 统一提交 -> 失败回滚 -> 成功后推进快照”的原子切换模式：
  1. `SharedResourceMount.apply_settings(...)` 负责候选 HTTP 资源、任务注册中心、消息总线与任务运行时的整体构建与统一切换；
  2. `SettingsApplyTransaction` 承担成功提交、失败回滚与恢复结果载荷输出；
  3. `SettingsReloadCoordinator` 仅在 `apply_settings(...)` 成功后保存快照，失败时恢复最近成功快照。
- 任务运行时契约已经冻结为强类型注册与强类型分发：
  1. `register_task_handler(...)` 与 `TaskWorkerSupervisor.register_handler(...)` 必须显式提供 `payload_model`；
  2. `TaskRegistrationRegistry` 拒绝 `BaseModel` 占位注册、重复 `job_kind` 与未声明注册项绑定；
  3. `LocalTaskDispatcher` 与 `FunboostTaskBootstrapper` 均在执行处理器前校验 `payload_kind` 与 `payload_json`；
  4. `TaskRegistrationRegistry` 中历史重复的 `build_bootstrap_snapshot` 已移除。
- Web 装配与热点拆分已经完成首轮落地：
  1. `WebBundleCatalog` 已切换为 provider/registry 形式；
  2. `DependencyContextAccessor` 已收缩为基于 `RouteDependencyContext` 的窄读取接口；
  3. `FastApiAppAssembler` 已改为通过 provider 目录统一装配；
  4. `AppSettingsLoader` 已拆出模块与运行时解析器，保留 `load`、`load_for_environment`、`load_from_mapping` 外部入口。
- 当前测试入口已按源码收口：
  1. `pyproject.toml` 已显式配置 `pythonpath = ["."]`；
  2. `pyproject.toml` 已显式配置 `testpaths = ["test"]`；
  3. `test/conftest.py` 统一负责测试数据库、环境变量与依赖装配。
- Funboost 退出期资源回收已补齐：`FunboostTaskBootstrapper.shutdown()` 当前会同时释放 `booster.publisher`、消费者内部 `_publisher_of_same_queue`、`_publisher_of_dlx_queue`、复杂路由消费者内部 `_rp` 以及全局缓存发布者，当前源码下不再复现解释器退出期残留发布者 `_at_exit` 噪声。
- 本次真实执行结果为：
  1. `docker compose -f compose.yml up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器健康；
  2. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_funboost_task_dispatcher_unit.py test\unit_test\test_settings_apply_transaction_unit.py`：通过，`10 passed`；
  3. `.\.venv\Scripts\python.exe -m pytest -q test\integration_test\test_funboost_rabbitmq_integration.py -vv`：通过，`2 passed`；
  4. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`181 passed`。
- 当前仍存在第三方告警但不影响验收结论：
  1. `passlib` 的 `argon2.__version__` 弃用告警；
  2. `funboost` 对 Pydantic V2 旧接口的弃用告警。
- 结论：快速开发阶段收口硬迁移已按一次性重构目标完成，当前源码、测试与回归文档已对齐；若旧设计条目与本节冲突，应判定为历史记录过期，以当前源码为准。

### 12.10 2026-05-23 安全基线加固回归

- 本节覆盖生产公网安全基线的最新落地结果；若前文或历史方案与当前源码冲突，以当前源码为准，旧记录可能过期。
- 生产部署边界已经拆分为：
  1. `compose.yml` 仅作为开发态编排，允许内部依赖端口绑定到 `127.0.0.1` 便于本地调试；
  2. `compose.production.yml` 作为生产覆盖文件，清空 Postgres、Redis、RabbitMQ 宿主机端口发布，只保留应用入口按需发布；
  3. 生产 Compose 必须显式提供 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`JWT_SECRET`、`RABBITMQ_DEFAULT_USER`、`RABBITMQ_DEFAULT_PASS` 等变量，或由等价编排系统注入。
- 应用生产运行时必须通过环境变量注入 `DATABASE_URL`、`REDIS_URL`、`RABBITMQ_URL` 和 `JWT_SECRET`；`AppSettingsLoader` 会拒绝缺失 JWT、弱 JWT、缺失 Redis/RabbitMQ/Database 连接串、Redis 无认证密码和 RabbitMQ `guest/guest`。
- `config/runtime/auth_runtime/auth_runtime_base.toml` 不再包含仓库默认 `jwt_secret`；生产 JWT 密钥只允许来自外部环境或等价 Secret 注入。
- 安全运行时契约位于 `src/core/http_contract/security_runtime_contract.py`，采用“公共头字段 + 强类型扩展字段”模式；`development_security` 与 `production_security` 使用 Pydantic 判别联合，并启用 `extra="forbid"`。
- OpenAPI 生产关闭通过 `FastAPI(openapi_url=None, docs_url=None, redoc_url=None)` 完成；当前不再采用“返回空 schema”作为关闭手段。历史文档中“OpenAPI 仅降级为空 schema”的描述已过期。
- `/system/info` 现在要求管理员角色或 `system:read` scope；匿名请求返回鉴权失败，管理员响应仍不得包含密钥、连接串和敏感配置。`/health/ready` 只返回 `status` 与 `ready`，不返回模块清单、版本或资源细节。
- `HttpFaultPayload` 仅包含稳定错误字段：`kind`、`schema_version`、`status_code`、`error_code`。验证错误和未预期异常的内部详情只写入结构化日志，不进入客户端响应。
- 安全响应头由 `security_header_middleware.py` 统一添加；生产安全运行时要求启用 HSTS、CSP、Referrer-Policy、Permissions-Policy 等策略。
- bootstrap admin 在生产默认关闭；若生产配置启用，加载器会直接拒绝启动。一次性初始化应在受控维护窗口完成，完成后移除明文密码环境变量并关闭 bootstrap 配置。
- JWT 密钥轮换后必须同步失效旧刷新令牌会话。当前仓储提供 `revoke_all_active_token_sessions(...)`，契约 `RefreshTokenInvalidationCommand` 支持全量、按主体和按会话三种失效模式。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，开发态 `postgres`、`redis`、`rabbitmq`、`app` 已启动；
  2. `.\.venv\Scripts\python.exe -m pytest -q test\contract_test\test_security_runtime_contract.py test\contract_test\test_http_contract.py`：通过，`14 passed`；
  3. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_settings_security_unit.py test\unit_test\test_fastapi_openapi_surface_unit.py test\unit_test\test_fastapi_exception_presenter_unit.py`：通过，`13 passed`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\boundary_test\test_security_boundary.py test\exception_test\test_security_exception.py test\initialization_test\test_security_initialization.py`：通过，`8 passed`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\interface_test\test_security_http_interface.py test\interface_test\test_http_interface.py`：通过，`19 passed`；
  6. `docker compose -f compose.yml config`：通过；
  7. `docker compose -f compose.yml -f compose.production.yml config`：通过，未发布 Postgres、Redis、RabbitMQ 宿主机端口，且未使用 RabbitMQ `guest/guest`；
  8. `docker compose -f compose.yml up -d postgres redis rabbitmq`：通过；
  9. `.\.venv\Scripts\python.exe -m pytest -q test\integration_test\test_security_production_integration.py test\integration_test\test_app_integration.py`：通过，`8 passed`；
  10. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`233 passed`。
- 当前仍存在第三方弃用告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic V1/V2 旧接口。这些告警不影响本次安全基线验收结论。

### 12.11 2026-05-23 快速开发骨架整改硬迁移回归

- 本节覆盖 `docs/2026_5_23_1332_快速开发骨架整改硬迁移拆解/` 对应硬迁移方案的最终落地结果；若与前文历史记录冲突，以当前源码与本节为准，旧记录可能过期。
- 本地开发配置加载已经收口为 `AppSettingsLoader` 门面编排：先解析有效 `AppEnvironment`，非生产环境读取仓库根目录 `.env`，再叠加进程环境变量；有效优先级为 `process env > explicit mapping override > local .env > TOML`。生产环境显式跳过仓库 `.env`，生产敏感配置仍必须来自进程环境变量或等价 Secret 注入。
- dotenv 读取实现位于 `src/infrastructure/settings/dotenv_settings_loader.py`，仅解析简单 `KEY=VALUE`，跳过空行与注释行，缺失文件返回空映射；来源契约采用 `SettingsSourceEnvelope` 公共头与 `DotenvSourceDetail` 强类型扩展字段。
- 异常日志脱敏由 `src/infrastructure/logging/sensitive_text_redactor.py` 统一处理，覆盖 URL 凭据、Bearer Token、JWT、`password=`、`*_PASSWORD=`、`*_TOKEN=` 与 `*_SECRET=` 样式字段。`LogEventBuilder` 写入异常 detail、traceback、资源生命周期 detail、任务失败 detail 前均会脱敏；`DatabaseLogWriter` 降级输出事件 JSON 前也会脱敏。
- 配置加载热点已经拆分：`settings_mapping_merger.py` 承担递归合并和判别联合切换整段替换，`settings_security_validator.py` 承担生产外部敏感配置、安全运行时和任务运行时一致性校验，`app_settings_loader.py` 保留文件读取、环境覆盖与模型构建门面职责。
- 资源挂载热点已经拆分：`runtime_resource_bootstrapper.py` 承担 HTTP、数据库、日志、缓存、消息和任务启动装配，`runtime_resource_releaser.py` 承担关闭释放顺序，`runtime_accessor_refresher.py` 承担鉴权与日志访问器快照刷新；`SharedResourceMount` 保留资源门面、热更新提交回滚和访问入口。
- 应用层端口已经收口到 `src/application/ports/`：鉴权、配置读取、任务派发均通过应用层端口契约注入，用例不再直接 import `src.infrastructure`。当前静态边界检查 `rg "from src\\.infrastructure" src/application -g "*.py"` 无命中。
- Web 模块新增流程已经收口到 `src/api/web_module_manifest.py`：健康、鉴权、系统信息模块通过 manifest 登记 provider 导入路径，`WebBundleCatalog` 动态导入 provider 并校验模块名一致、重复模块名、provider 缺失、导入失败与禁用模块。内置 `ApplicationModuleName` 仍用于避免拼写错误，但启用项与发现键使用字符串模块名，新增模块不再要求修改核心枚举。
- 本次新增或修改的主要测试入口包括：
  1. `test/unit_test/test_dotenv_settings_loader_unit.py`；
  2. `test/unit_test/test_sensitive_text_redactor_unit.py`；
  3. `test/exception_test/test_logging_redaction_exception.py`；
  4. `test/unit_test/test_application_port_boundary_unit.py`；
  5. `test/unit_test/test_web_module_manifest_unit.py`；
  6. `test/interface_test/test_local_startup_interface.py`；
  7. `test/path_test/test_fast_development_skeleton_path.py`。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器已启动且依赖健康；
  2. `.\.venv\Scripts\python.exe -m compileall -q src test`：通过；
  3. `rg "from src\\.infrastructure" src\application -g "*.py"`：无命中，退出码为 `1`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_dotenv_settings_loader_unit.py test\unit_test\test_sensitive_text_redactor_unit.py test\unit_test\test_web_module_manifest_unit.py`：通过，`17 passed`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\exception_test test\interface_test`：通过，`37 passed`；
  6. `.\.venv\Scripts\python.exe -m pytest -q test\path_test test\integration_test`：通过，`45 passed`；
  7. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`256 passed`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次硬迁移验收结论。
- 文档不包含真实 `.env` 值、真实生产连接串、真实 token 或生产密钥；示例值仅用于说明字段名和加载规则。

### 12.12 2026-05-23 Web 模块注册与启用校验收口回归

- 本节覆盖 `docs/2026_5_23_1818_Web模块注册与启用校验收口执行方案.md` 对应改造；若与前文历史记录冲突，以当前源码与本节为准，旧记录可能过期。
- Web provider 注册入口已收敛为 manifest provider import path：`WebBundleCatalog` 不再维护 `_provider_types` 注册表，也不再提供 `register_provider_type` 装饰器；健康、鉴权、系统概览 provider 类不再使用装饰器注册。
- `src/api/web_module_manifest.py` 仍是 Web 模块发现的唯一清单来源；`WebBundleCatalog` 负责按 manifest 动态导入 provider，并保留重复模块名、导入失败、provider 类型、provider 输出与 manifest 模块名一致性校验。
- `app.modules.enabled` 的未知模块校验已前移到应用装配阶段：`FastApiAppAssembler` 创建 `WebBundleCatalog` 后，会先调用 catalog 校验启用模块，再构建 bundle 与挂载路由；未知模块会以包含 `app.modules.enabled` 与未知模块名的错误直接失败，不再由 `FastApiRouteComposer` 静默忽略。
- 已知模块禁用行为保持不变：配置中未启用的已知模块不会挂载路由，鉴权模块禁用时 `/auth/token` 仍返回 404。
- 回归修复中同步补齐 `task_execution_record.backend` Alembic 迁移，并恢复默认任务绑定工厂；默认绑定会按当前配置已声明任务过滤，避免生产配置注册未声明的示例任务。
- 本次新增或修改的主要测试入口包括：
  1. `test/unit_test/test_web_module_manifest_unit.py`；
  2. `test/unit_test/test_web_module_registry_boundary_unit.py`；
  3. `test/boundary_test/test_runtime_boundary.py`；
  4. `test/integration_test/test_app_integration.py`；
  5. `test/unit_test/test_fastapi_app_assembler_unit.py`。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器已运行且依赖健康；
  2. `.\.venv\Scripts\python.exe -m compileall -q src test`：通过；
  3. `rg "register_provider_type" src/api -S`：无命中，退出码为 `1`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_web_module_manifest_unit.py test\unit_test\test_web_module_registry_boundary_unit.py`：通过，`9 passed`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\boundary_test\test_runtime_boundary.py`：通过，`20 passed`；
  6. `.\.venv\Scripts\python.exe -m pytest -q test\integration_test\test_app_integration.py test\path_test\test_web_execution_path.py`：通过，`9 passed`；
  7. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`277 passed`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.17 2026-05-25 鉴权与日志安全风险整改回归

- 本节覆盖 `docs/2026_5_25_1640_鉴权与日志安全风险整改执行方案.md` 对应整改；若前文、历史评审或图谱与当前源码冲突，以当前源码为准，旧记录可能过期。
- 异常日志链路已收口：`FastApiExceptionPresenter` 不再调用普通 `logger.exception(...)` 输出未脱敏 traceback；默认标准输出 handler 使用 `RedactingLogFormatter`，结构化异常事件、traceback、数据库日志降级输出继续由 `SensitiveTextRedactor` 脱敏 URL 凭据、Bearer、JWT、密码和 secret 字段。
- 鉴权失败节流已从缓存 `get/set` 读改写迁移为 `CacheStore.increment_with_expire(...)`：Redis 使用 Lua 包裹 `INCR` 与首次 `EXPIRE`，内存实现使用锁保护并仅作为 dev/test 边界；`AUTH_THROTTLE` 缓存不可用仍按 fail-closed 策略抛出。
- `TokenPayload.token_id` 与 `token_session_id` 已收窄为 `UUID`，JWT 对外 claim 仍序列化为字符串；合法签名但非法 `jti` / `sid` 会在 `JwtTokenService` 映射为 `401/auth.token.invalid`，usecase 与中间件不再裸 `UUID(...)` 强转。
- `AuthenticationBindingMiddleware` 对携带无效 Bearer 的请求直接返回鉴权失败响应，公共路由不再出现“无效 Bearer 仍 200”的语义；仓储、数据库等基础设施异常不伪装为 token 无效，仍进入统一未预期异常链路。
- `/auth/me` 与 `/system/info` 已通过路由级 `Depends` / `Security` 依赖声明授权要求，OpenAPI 中受保护路由包含 Bearer security；handler 内不再依赖人工记忆读取授权主体。
- refresh token 持久层补充 `subject_id -> auth_user.subject_id` 外键与 `rotated_to_token_id -> auth_refresh_token.refresh_token_id` 自关联外键，新增迁移 `202605251640_harden_refresh_token_constraints.py` 串接在当前 Alembic head 之后；`get_token_session_status()` 改为聚合读取并返回 `is_expired`、`is_inconsistent`，主体冲突或同一会话多个活跃 refresh token 都会被视为不一致状态，脏数据不再放大为 `MultipleResultsFound`。
- `AuthRuntimeSettings.jwt_secret` 已改为 `SecretStr`，装配 `AccessTokenPolicy` 时才通过 `get_secret_value()` 取真实值；生产安全校验要求 `require_external_jwt_secret` 与 `require_distributed_auth_throttle` 显式为真，且继续拒绝弱 JWT、内存缓存和生产 bootstrap admin。
- 禁用账号登录已收敛为与用户名不存在、密码错误一致的 `401/auth.access.invalid_credentials` 外部语义；`AuthRuntimePortDetail` 中无消费者的 token capability 标记已移除；撤销用例类名改为 `RevokeTokenSessionUsecase`，语义对应撤销 refresh token session。
- 本次新增或修改的主要测试入口包括：
  1. `test/unit_test/test_logger_factory_unit.py`；
  2. `test/unit_test/test_fastapi_exception_presenter_unit.py`；
  3. `test/exception_test/test_logging_redaction_exception.py`；
  4. `test/unit_test/test_cache_unit.py`；
  5. `test/integration_test/test_cache_integration.py`；
  6. `test/boundary_test/test_security_boundary.py`；
  7. `test/exception_test/test_runtime_exception.py`；
  8. `test/unit_test/test_auth_persistence_unit.py`；
  9. `test/interface_test/test_http_interface.py` 与 `test/interface_test/test_security_http_interface.py`；
  10. `test/unit_test/test_settings_security_unit.py` 与 `test/integration_test/test_security_production_integration.py`；
  11. `test/boundary_test/test_runtime_boundary.py`；
  12. `test/initialization_test/test_task_runtime_initialization.py` 与 `test/path_test/test_task_runtime_path.py`；
  13. `test/integration_test/test_funboost_rabbitmq_integration.py`；
  14. `test/initialization_test/test_cache_initialization.py`。
- 当前真实测试入口与结果如下：
  1. `docker compose build app`：通过；
  2. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器已启动且依赖健康；
  3. `.\.venv\Scripts\python.exe -m compileall -q src test`：通过；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_logger_factory_unit.py test\unit_test\test_fastapi_exception_presenter_unit.py test\exception_test\test_logging_redaction_exception.py`：通过，`9 passed`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_cache_unit.py test\integration_test\test_cache_integration.py`：通过，`16 passed`；
  6. `.\.venv\Scripts\python.exe -m pytest -q test\boundary_test\test_security_boundary.py test\exception_test\test_runtime_exception.py`：通过，`19 passed`；
  7. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_auth_persistence_unit.py`：通过，`11 passed`；
  8. `.\.venv\Scripts\python.exe -m pytest -q test\interface_test\test_http_interface.py test\interface_test\test_security_http_interface.py`：通过，`22 passed`；
  9. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_settings_security_unit.py test\integration_test\test_security_production_integration.py`：通过，`14 passed`；
  10. `.\.venv\Scripts\python.exe -m pytest -q test\boundary_test\test_runtime_boundary.py`：通过，`21 passed`；
  11. Docker 应用容器内执行全量回归主集：通过，`311 passed, 3 deselected`；其中 3 个被剔除用例依赖宿主机 `docker` / `rg` 工具；
  12. 宿主机补跑上述 3 个工具依赖用例：通过，`3 passed`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.16 2026-05-23 Repository 事务边界与缓存策略回归

- 本节覆盖 `docs/2026_5_23_2233_repository事务边界与缓存策略规范执行方案.md` 对应整改；若前文或历史方案与当前源码冲突，以当前源码与本节为准，旧记录可能过期。
- Repository 事务边界已收口：`TaskExecutionRecordRepositoryImpl.upsert()` 不再捕获 `IntegrityError` 后执行 `session.rollback()`；当前使用 `SAVEPOINT` 识别 dedup 唯一约束冲突并回查既有记录，其他 `IntegrityError` 继续向上抛出。
- `src/infrastructure/persistence/repository_impl/` 当前不包含 repository 内部 `commit()` / `rollback()` 调用；提交、回滚和释放仍由 UoW 调用方统一控制。
- 缓存命名空间补齐为 `AUTH_THROTTLE`、`RATE_LIMIT`、`QUERY_RESULT`；缓存 key 由 `CacheKeyBuilder` 统一校验前缀、命名空间和片段，拒绝空片段与包含 `:` 的片段。
- 缓存策略契约新增 `CachePolicyEnvelope` 与 `CacheFailureMode`，并通过 `runtime.cache.namespace_policies` 配置装载；`CachePolicyResolver` 按“显式 TTL > namespace TTL > runtime TTL”解析最终 TTL。
- Redis 不可用处理改为按策略分流：`AUTH_THROTTLE` 与 `RATE_LIMIT` fail-closed，继续抛出 `system.cache.unavailable`；`QUERY_RESULT` 默认 fail-open，读取返回未命中，写入和删除记录告警后跳过。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器已运行且依赖健康；
  2. `uv run python -m pytest -q test/unit_test/test_task_execution_record_repository_unit.py test/unit_test/test_cache_unit.py`：通过，`16 passed`；
  3. `uv run python -m pytest -q test/path_test/test_cache_runtime_path.py test/exception_test/test_runtime_exception.py`：通过，`19 passed`；
  4. `uv run python -m pytest -q test/initialization_test/test_cache_initialization.py`：通过，`3 passed`；
  5. `docker compose up -d redis; uv run python -m pytest -q test/integration_test/test_cache_integration.py`：通过，`2 passed`；
  6. `uv run python -m pytest -q`：通过，`299 passed`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。
- 文档不包含真实 `.env` 值、真实生产连接串、真实 token 或生产密钥；示例值仅用于说明字段名和加载规则。

### 12.18 2026-05-26 网络安全防护增强回归

- 本节覆盖 `docs/2026_5_26_0759_网络安全防护增强拆解` 对应落地；若历史设计、执行方案或图谱与当前源码冲突，以当前源码和本节为准。
- 安全运行时采用 `runtime.security.detail.protection.*`：`flow_control` 承载默认限流和 path/method 策略集合，`risk_control` 承载登录失败与密码喷洒风险信号，`ip_block` 承载封禁开关、缓存 TTL 和默认封禁时长，`token_binding` 默认关闭并按路径/token 用途生效，`outbound_url_safety` 承载 SSRF URL 校验策略。
- 流控链路已由 `RateLimitMiddleware` 接入请求入口：默认按 IP 摘要和 path+method 计数，策略可按 subject、path+method、认证字段摘要扩展。`/auth/token` 默认策略为 `10/300s`，`/auth/refresh` 默认策略为 `20/300s`，超限返回 `429` 与 `Retry-After`。
- IP 封禁链路已落库并缓存回填：`IpBlockGuard` 优先读取封禁缓存，miss 后查询 `security_ip_block_record` active 记录并回填，回填 TTL 不超过数据库 `blocked_until_epoch`；释放封禁会提交数据库状态并删除缓存。限流触发封禁时通过 `DistributedLockProvider` 防重复写入。
- 独立分布式锁运行时采用 `runtime.distributed_lock.header/detail.*`，锁 Provider 使用缓存命名空间构建 key，支持 SET NX EX 语义、owner 防误删、原子续租、租约过期后重新获取和 Redis/cache 不可用 fail-closed。
- 统一密钥管理运行时采用 `runtime.key_management.header/detail.key_families[]`，密钥族初始化幂等，密钥环快照包含 `current_key_id`、`candidate_key_ids` 与 `valid_key_digests`。轮转通过独立分布式锁保护，旧 key 在 `compatibility_window_seconds` 内可按 key id 读取；JWT 签发使用当前托管 key 并写入 `kid`，验签按 `kid` 查找有效 key。
- 安全事件采用 `SecurityEventEnvelope`，公共头包含 `decision`、`reason_code`、`status_code`、`subject_id`、`ip_digest`、`user_agent_digest`、`occurred_at_epoch`。当前实际接入事件包括 `auth.login.failure`、`auth.login.throttled`、`auth.password_spray_suspected`、`auth.refresh.reused`、`auth.token.invalid`、`rate_limit.blocked`、`payload.too_large`、`token_binding.mismatch`、`ssrf.blocked`。
- Token-IP 绑定已接入认证绑定主流程：开启后仅对配置声明路径和 token 用途生效；首次合法访问写入 token 摘要与 IP 摘要，不匹配时拒绝并生成 `token_binding.mismatch` 安全事件；当前实现保留原绑定，不在不匹配时自动删除。
- SSRF 防护已接入共享同步/异步 HTTP client 请求前钩子和连接层 transport：禁止空 host、非法端口、非 `http/https` scheme、localhost、loopback、private、link-local、reserved 与 metadata 地址；DNS 解析结果命中上述地址段会被拒绝。连接层会固定解析 IP 并校验真实 peer IP；production 默认启用目的域名允许清单，空清单表示拒绝全部未显式声明目的域名。
- 部署边界保持清晰：项目不内置完整 WAF、SIEM、外部 KMS/HSM、依赖漏洞扫描或 DAST 平台；应用侧限流不能替代边界层 DDoS 防护。生产环境继续关闭公开 OpenAPI，并启用 HSTS/CSP。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`app`、`postgres`、`redis`、`rabbitmq` 容器已运行且健康；
  2. `docker compose config --quiet`：通过；
  3. `uv run python -m compileall -q src test`：通过；
  4. 契约、单元、路径、异常、边界、接口、集成、初始化和既有 HTTP/metrics/redactor 批次均通过；
  5. `uv run python -m pytest -q`：通过，`372 passed, 71 warnings`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.14 2026-05-23 任务后端一致性与执行记录收口回归

- 本节覆盖 `docs/2026_5_23_1821_任务后端一致性与执行记录收口执行方案.md` 对应整改；若前文或历史方案与当前源码冲突，以当前源码与本节为准，旧记录可能过期。
- 任务分发入口已增加后端一致性强约束：`DispatchBackgroundJobUsecase` 会通过 `TaskRuntimePort.get_current_task_backend()` 与 `get_enabled_task_registration_for_backend()` 按当前 `runtime.task.backend` 读取注册项。本地运行时不能派发 Funboost 注册任务，Funboost 运行时不能派发本地注册任务。
- `TaskRegistrationRegistry.get_enabled_registration_for_backend()` 是后端一致性校验的统一入口；`LocalTaskDispatcher` 与 `FunboostTaskDispatcher` 也会在执行前做防御性后端校验，避免绕过用例层后发生跨后端执行。
- `TaskExecutionRecordEnvelope` 已补齐 `backend`、`queue_name` 与 `detail_kind` 公共头字段；执行记录扩展体改为按 `kind` 判别联合，每个扩展体保留 `schema_version`、`status`、`stage` 与状态相关时间或错误字段，并启用 `extra="forbid"`。
- 执行记录 ORM 新增 `backend` 字段与索引，迁移版本为 `202605231821_add_task_execution_backend.py`。历史记录迁移默认回填 `local`，若旧记录原本来自 Funboost 且缺失 backend，则历史语义可能不完整；新记录以当前源码写入为准。
- `TaskExecutionStore.mark_running()`、`mark_success()`、`mark_retrying()`、`mark_failed()` 均要求显式传入 `backend`、`queue_name`、`stage`。本地执行写入 `local/local_execution`，Funboost 发布写入 `funboost/dispatch`，Funboost 消费成功或失败写入 `funboost/consume_execution`。
- `FastApiAppAssembler` 不再隐式注入 demo/noop 任务绑定；示例任务绑定已隔离到 `src/infrastructure/testing/demo_task_binding_factory.py`，仅由测试工厂显式使用。`src/api/asgi_entry.py` 通过 `ApplicationTaskBindingProvider` 提供生产应用显式任务绑定入口；当前生产配置通过 `task_module_production.toml` 禁用 demo 注册，真实业务任务需要显式注册与绑定。
- 前文 `12.12` 中“恢复默认任务绑定工厂”的描述已过期；当前以“不自动注入默认 demo/noop binding”为准。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器已运行且依赖健康；
  2. `.\.venv\Scripts\python.exe -m compileall src test`：通过；
  3. `.\.venv\Scripts\python.exe -m pytest -q test\contract_test\test_task_execution_contract.py test\unit_test\test_task_registration_registry_unit.py test\unit_test\test_task_execution_record_repository_unit.py`：通过，`17 passed`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_local_task_dispatcher_unit.py test\unit_test\test_funboost_task_dispatcher_unit.py test\unit_test\test_fastapi_app_assembler_unit.py`：通过，`14 passed`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\path_test\test_task_runtime_path.py test\integration_test\test_task_execution_record_integration.py`：通过，`6 passed`；
  6. `.\.venv\Scripts\python.exe -m pytest -q test\integration_test\test_funboost_rabbitmq_integration.py -vv`：通过，`3 passed`；
  7. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`277 passed`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.13 2026-05-23 鉴权令牌安全缺陷修正回归

- 本节覆盖 `docs/2026_5_23_1820_鉴权令牌安全缺陷修正执行方案.md` 对应修正；若前文或历史方案与当前源码冲突，以当前源码与本节为准，旧记录可能过期。
- `AuthenticationBindingMiddleware` 只收敛已知 `HttpFaultException` 到 `request.state.auth_fault`；非法、过期、已撤销令牌仍按鉴权错误返回，数据库、仓储、资源挂载或线程桥接等未预期故障必须向上交给统一异常链路，不得伪装为 `401/auth.token.invalid`。
- refresh token rotation 发现旧 refresh token 被重复使用时，`RefreshAccessTokenUseCase` 会先按 `token_session_id` 撤销同会话全部活跃刷新令牌并提交事务，再对外返回 `401/auth.token.reused`；同会话已签发的 access token 后续访问会因会话撤销返回 `401/auth.token.revoked`。
- 刷新令牌失效契约继续采用“公共头字段 + 强类型扩展字段”模式：`RefreshTokenInvalidationCommand.header.mode` 必须与 `detail.kind` 一致，`TokenSessionInvalidationDetail` 使用 `kind="token_session"`、`schema_version` 和 `token_session_id`，并启用 `extra="forbid"`。
- JWT 有效期语义统一为半开区间 `[issued_at_epoch, expires_at_epoch)`；`JwtTokenService` 在 `now_epoch >= expires_at_epoch` 时判定令牌过期，access token 与 refresh token 均返回 `auth.token.expired`。历史“等于过期点仍有效”和“reuse 只返回 reused 不撤销 session”的描述已过期。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器已运行且依赖健康；
  2. `.\.venv\Scripts\python.exe -m pytest -q test\contract_test\test_refresh_token_invalidation_contract.py`：通过，`4 passed`；
  3. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_auth_persistence_unit.py`：通过，`8 passed`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\boundary_test\test_runtime_boundary.py`：通过，`20 passed`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\exception_test\test_runtime_exception.py`：通过，`11 passed`；
  6. `.\.venv\Scripts\python.exe -m pytest -q test\path_test\test_runtime_path.py test\interface_test\test_http_interface.py`：通过，`32 passed`；
  7. `.\.venv\Scripts\python.exe -m pytest -q test\convention_usage_test\test_end_to_end_usage.py test\integration_test\test_app_integration.py`：通过，`12 passed`；
  8. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_fastapi_app_assembler_unit.py`：通过，`2 passed`；
  9. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`277 passed`。
- 回归过程中同步清理过期 Alembic 字节码缓存，并修正任务绑定、任务执行记录、Redis 节流键隔离等与当前源码契约不一致的测试入口；这些修复不改变本次鉴权安全语义。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。
- 文档不包含真实 `.env` 值、真实生产连接串、真实 token 或生产密钥；示例值仅用于说明字段名和加载规则。

### 12.15 2026-05-23 资源挂载生命周期门面收口回归

- 本节覆盖 `docs/2026_5_23_2232_资源挂载生命周期门面收口执行方案.md` 对应整改；若前文或历史方案与当前源码冲突，以当前源码与本节为准，旧记录可能过期。
- `SharedResourceMount` 已成为资源生命周期字段的唯一写入门面，新增 `attach_http_runtime()`、`install_database_runtime()`、`install_logging_runtime()`、`install_cache_runtime()`、`install_task_runtime()`、`clear_*_runtime()`、`mark_runtime_resource_state()`、`refresh_runtime_accessors()` 等显式方法。
- `runtime_resource_bootstrapper.py`、`runtime_resource_releaser.py`、`runtime_accessor_refresher.py` 只负责资源构建、释放顺序和访问器快照生成，不再直接写入 `mount._http_runtime_accessor`、`mount._runtime_states`、`mount._session_factory`、`mount._cache_store`、`mount._task_runtime_accessor` 等生命周期字段。
- 资源挂载操作契约位于 `src/infrastructure/resource_mount/runtime_resource_mount_contract.py`，采用“公共头字段 + 强类型扩展字段”模式；HTTP、数据库、日志、缓存、任务、访问器刷新、资源状态变更扩展均使用 Pydantic 判别联合，并启用 `extra="forbid"`。
- 前文 `12.11` 中“`runtime_accessor_refresher.py` 承担鉴权与日志访问器快照刷新”的描述需要按当前源码理解为“生成访问器快照”；实际写入由 `SharedResourceMount.refresh_runtime_accessors()` 完成，helper 不再拥有 mount 内部字段写权限。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`postgres`、`redis`、`rabbitmq`、`app` 容器已运行且依赖健康；
  2. `.\.venv\Scripts\python.exe -m compileall src test`：通过；
  3. `.\.venv\Scripts\python.exe -m pytest -q test\contract_test\test_runtime_resource_mount_contract.py test\unit_test\test_resource_mount_lifecycle_unit.py`：通过，`8 passed`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\initialization_test\test_runtime_initialization.py test\initialization_test\test_bootstrap_initialization.py`：通过，`10 passed`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\path_test\test_runtime_path.py test\path_test\test_task_runtime_path.py`：通过，`23 passed`；
  6. `.\.venv\Scripts\python.exe -m pytest -q`：通过，`287 passed`；
  7. 并发复跑 `test_runtime_resource_mount_contract.py` 与 `test_resource_mount_lifecycle_unit.py`：通过，两个进程均为 `4 passed`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.19 2026-05-29 身份管理后台联调阻塞项整改回归

- 本节覆盖 `docs/2026_5_29_1041_身份管理后台联调阻塞项整改执行方案.md` 对应整改；若前文、历史方案或图谱与当前源码冲突，以当前源码、契约测试和本节为准，旧记录可能过期。
- 身份管理接口以 `AdminIdentityEnvelope` 为统一响应外壳，scope、role、user、business role 路由已完整挂载；OpenAPI 中 scope/role 写请求、成功响应 schema、`detail` 判别联合 `discriminator.propertyName/mapping` 均由测试精确断言。`OrjsonDocumentResponse` 继承 `JSONResponse`，避免路由响应 schema 被错误降级为字符串。
- `/auth/me` 是认证用户自省接口，不要求管理员授权；`admin`、`customer_service`、`business_operator` 可读取自身用户、角色、scope 和前端菜单初始化所需信息，未登录、过期、撤销或非法 token 仍按鉴权错误返回。非管理员自省不会放开管理员接口访问。
- 测试数据库准备继续由测试夹具集中负责，未设置 `TEST_DATABASE_RESET` 时等同 `TEST_DATABASE_RESET=1`，仅 `_test` 后缀数据库允许 drop/recreate；`TEST_DATABASE_RESET=0` 用于验证重复执行稳定性。测试数据库准备阶段持有跨 pytest 会话文件锁，避免并发回归进程互相删除测试库。会变更全局权限、bootstrap admin scope 或用户数据的测试必须使用唯一 subject/username，并在测试结束时恢复或清理资源。
- 任务执行记录幂等语义固定为 `job_kind + deduplication_key` 唯一；并发插入先尝试创建，唯一键冲突后在同一业务语义下回查既有记录，并返回 `TaskExecutionDedupeResult` 的 created/existing 判别联合结果。`TaskExecutionRecordRepositoryImpl.upsert()` 的旧“覆盖式 upsert”语义不再作为当前契约依据。
- PostgreSQL schema 现状以 Alembic 迁移为准：`auth_role_scope.scope_code` 引用 `auth_scope.scope_code`；`task_execution_record.record_id` 和 `job_kind + deduplication_key` 均有唯一约束；`app_log_record` ORM 已映射 `created_at` 与 `updated_at` 审计时间列，迁移和 ORM 保持一致。
- IP 封禁缓存 TTL 不得超过数据库 `blocked_until_epoch` 剩余有效期；数据库封禁到期后，应用层封禁判断应释放缓存命中并允许后续请求按当前记录状态重新评估。
- 任务 worker 禁用时沿用通用 `HttpFaultException` 错误语义；`TaskDispatchPolicyHeader` 与 `WorkerDisabledRejectDetail` 是方案阶段的叙述性名称，不是当前冻结运行时模型。`LocalMessageBus` 与 `FailedTaskRecorder` 使用有界内存策略，避免本地消息和失败记录无限增长。
- `RuntimeResourceReleaser.shutdown()` 采用 best-effort 释放并返回 `RuntimeResourceReleaseEnvelope`；`SharedResourceMount.shutdown()` 会返回并保存最近一次释放结果，调用方可通过 `get_last_resource_release_result()` 读取副本；单个资源释放失败不会阻断后续资源释放，失败项进入返回契约的 `detail.failures`。`ShutdownResultDetail` 不是当前源码中的独立冻结模型名称。
- `IpBlockCachePolicyHeader`、`IpBlockCacheTtlDetail` 与 `PersistenceSchemaDriftReport` 是本方案中的说明性名称；当前源码没有将它们作为公共运行时契约模型冻结，后续若需要对外暴露必须另行补齐源码、契约和测试。
- Docker healthcheck 读取 `AppSettingsLoader().load().runtime.web.api_prefix` 后拼接 `/health/live`，确保非空 API 前缀下仍命中真实健康检查路径。`flush_interval_seconds` 是 `LogBufferDispatcher.emit()` 在下一条日志进入时触发的间隔刷盘阈值，不创建后台定时线程；没有新日志进入时不会仅因时间到达自动刷盘，shutdown/manual flush 仍会显式刷盘。
- 当前真实测试入口与结果如下：
  1. `docker compose up -d`：通过，`app`、`postgres`、`redis`、`rabbitmq` 容器已运行且健康；
  2. `.\.venv\Scripts\python.exe -m compileall src test`：通过；
  3. `.\.venv\Scripts\python.exe -m pytest -q test\contract_test\admin_identity test\contract_test\test_task_execution_contract.py`：通过，`25 passed`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\interface_test\admin_identity test\interface_test\admin_audit`：通过，`19 passed, 1 warning`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_task_execution_record_repository_unit.py test\unit_test\test_ip_block_guard_unit.py test\unit_test\test_resource_mount_lifecycle_unit.py`：通过，`19 passed`；
  6. `$env:TEST_DATABASE_RESET='1'; .\.venv\Scripts\python.exe -m pytest -q test\integration_test\admin_identity test\integration_test\test_admin_smoke_integration.py test\integration_test\test_admin_business_console_smoke_integration.py`：通过，`6 passed, 1 warning`；
  7. `.\.venv\Scripts\python.exe -m pytest -q test\integration_test\test_task_execution_record_integration.py test\integration_test\test_security_ip_block_integration.py test\integration_test\test_migration_job_integration.py`：通过，`18 passed, 1 warning`；
  8. `$env:TEST_DATABASE_RESET='1'; .\.venv\Scripts\python.exe -m pytest -q test --ignore=test\integration_test`：通过，`532 passed, 65 warnings`；
  9. `$env:TEST_DATABASE_RESET='1'; .\.venv\Scripts\python.exe -m pytest -q test\integration_test`：通过，`42 passed, 61 warnings`；
  10. `$env:TEST_DATABASE_RESET='0'; .\.venv\Scripts\python.exe -m pytest -q test --ignore=test\integration_test` 连续执行两次：均通过，均为 `532 passed, 65 warnings`；
  11. `$env:TEST_DATABASE_RESET='1'; .\.venv\Scripts\python.exe -m pytest -q`：通过，`574 passed, 71 warnings`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.20 2026-06-20 统一心智模型代码检查整改回归

- 本节覆盖 `docs/2026_6_20_1458_统一心智模型代码检查整改执行方案.md` 对应整改；若前文、历史方案或图谱与当前源码冲突，以当前源码、契约测试和本节为准，旧记录可能过期。
- 后台路由依赖的内置 scope 已集中固化为系统保留能力，包含 `auth:read`、`auth:manage`、`security:manage`、`system:read`、`task:dispatch` 等当前路由授权集合。后台 scope 接口允许维护内置 scope 的名称和描述，但禁止禁用或删除这些受保护 scope；自定义业务 scope 仍按普通业务权限管理。
- 身份管理自锁规则覆盖 scope 禁用、角色 scope 替换、用户角色替换和当前用户停用路径。系统始终至少保留一个 active admin 且具备 `auth:manage` 能力；`security:manage` 等后台受保护 scope 不能被禁用或删除。
- `runtime.task.worker_enabled` 只表示当前节点是否消费或执行任务，不再阻断 producer-only 派发。Funboost 后端在 `worker_enabled=false` 时只注册发布元数据并按首次发布惰性构建 publisher booster，不启动本节点 consumer，也不要求本节点具备 handler。
- 本地任务后端使用 `inline_execute_enabled` 显式控制是否同进程执行 handler；handler 完整性校验只在 `worker_enabled=true` 的 Funboost 消费节点或 `inline_execute_enabled=true` 的本地内联执行节点触发。`runtime.task.backend=local` 与 `runtime.message.backend=rabbitmq` 的组合会在启动期拒绝，避免同一任务既本地执行又进入外部消息总线。
- `runtime.message.backend` 表示独立消息总线后端。其值为 `rabbitmq` 时，`shared_message_bus` 挂载 `RabbitMqMessageBus`，资源状态和管理端展示均标识 RabbitMQ 消息总线；Funboost RabbitMQ broker 仍由任务后端自身 bootstrapper 管理，两者不是同一个运行时对象。
- RabbitMQ 消息总线使用 `amqpstorm` 建立连接并声明配置中的 exchange，发布 `TaskMessageEnvelope` JSON 消息，设置 `content_type=application/json`、持久化 delivery mode、`message_id`、`correlation_id/request_id` 和 `trace_id` 头，并使用 `mandatory=true`。启用发布确认时按 broker 返回结果判定失败；无可达 binding、NACK 或 AMQP 异常均进入统一任务失败语义，不再把未路由消息当作成功。
- 安全防护事件中，限流首次超限并触发封禁仍记录 `rate_limit.blocked`；后续已封禁 IP 命中记录为 `ip_block`。IP 封禁缓存值为强类型 `IpBlockCacheEntry`，缓存命中时按 `blocked_until_epoch` 重新计算 `Retry-After`，不超过真实剩余封禁时间。
- `AdminAuditAction` 只暴露当前仓储可查询的后台审计动作，未实现的 `business_object_changed`、`business_action_triggered` 不再作为公开枚举选项。分布式锁运行时不再暴露 `failure_mode` 配置，Redis/cache 不可用时固定 fail-closed。`flush_interval_seconds` 仍是下一条日志进入时触发的 lazy flush 间隔阈值，shutdown/manual flush 会显式刷盘。
- 当前真实测试入口与结果如下：
  1. `docker compose -f compose.yml up -d`：通过，`app`、`postgres`、`redis`、`rabbitmq` 容器已运行且健康；宿主机 AMQP 使用 `127.0.0.1:5672`，RabbitMQ 管理端口为 `127.0.0.1:15672`；
  2. `.\.venv\Scripts\python.exe -m compileall -q src test`：通过；
  3. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\admin_identity test\interface_test\admin_identity\test_admin_scope_interface.py`：通过，`38 passed, 1 warning`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_local_task_dispatcher_unit.py test\unit_test\test_funboost_task_dispatcher_unit.py test\unit_test\test_rabbitmq_message_bus_unit.py test\initialization_test\test_task_runtime_initialization.py test\path_test\test_task_runtime_path.py`：通过，`33 passed, 3 warnings`；
  5. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_ip_block_guard_unit.py test\path_test\test_security_protection_path.py test\contract_test\test_security_protection_contract.py`：通过，`12 passed`；
  6. `.\.venv\Scripts\python.exe -m pytest -q test\unit_test\test_log_writer_unit.py test\unit_test\admin_audit test\contract_test\admin_audit test\contract_test\test_distributed_lock_contract.py test\unit_test\test_distributed_lock_provider_unit.py`：通过，`22 passed`；
  7. 设置 `RABBITMQ_INTEGRATION_ENABLED=1`、`RABBITMQ_TEST_URL=amqp://fastapi_dev:local-dev-rabbitmq-password@127.0.0.1:5672/%2F`、`REDIS_TEST_URL=redis://127.0.0.1:56379/0` 后执行 `.\.venv\Scripts\python.exe -m pytest -q -rs test\integration_test\admin_identity test\integration_test\test_security_ip_block_integration.py test\integration_test\test_funboost_rabbitmq_integration.py`：通过，`13 passed, 61 warnings`；
  8. 同一 Docker 依赖环境下执行 `.\.venv\Scripts\python.exe -m pytest -q -rs`：通过，`630 passed, 62 warnings`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.21 2026-06-21 统一心智模型整改回归

- 本节覆盖 `docs/2026_6_21_1144_统一心智模型整改执行方案.md` 对应整改；若前文、历史方案或图谱与当前源码冲突，以当前源码、契约测试和本节为准，旧记录可能过期。
- `create_app()` 不再在 API 入口提前构建默认 task binding；默认解析由 `FastApiAppAssembler` 通过 `TaskBindingSource` 和 `ApplicationTaskBindingProvider` 统一处理。显式 `task_bindings` 使用严格模式，provider/default 入口只装配当前注册表声明的绑定，避免 stale binding 被真实主入口误用。
- 管理端任务运行时返回已收口为 `task_runtime_mode`、`task_backend`、`transport_backend`、`configured_transport_backend`、`worker_enabled`、`inline_execute_enabled`、`default_job_kind` 和 `default_retry_limit`。其中 `TaskRuntimeMode` 明确区分 `local_inline`、`local_queued`、`funboost_producer`、`funboost_consumer`，任务后端与消息传输后端不再混写。
- `/admin/tasks/registrations` 返回全量注册快照，并为每条记录标注 `registration_backend`、`current_runtime_backend` 与 `active_for_current_runtime`。管理端可以同时看到未激活但已声明的 local/funboost 注册项。
- `MessagePublishResult` 已迁移为公共头字段加判别联合扩展字段。RabbitMQ 发布确认开启时只有 broker 确认成功才声明 `routed=true`；发布确认关闭时只声明已发布，不声明路由成功；mandatory 未路由、NACK 或 AMQP 异常均进入统一失败路径。
- `security_protection` 的 IP 封禁管理路由只负责请求契约、鉴权和响应封装，`list/create/get/release` 全部通过 `RequestExecutionBridge` 执行应用用例。应用用例依赖 `AdminSecurityIpBlockRuntimePort`，不再直接导入基础设施实现或 ORM 模型。
- 后台授权事实源集中在 `admin_route_authorization.py`，`system_overview` 与 `security_protection` 均使用中心化 `RouteAuthorizationRequirement`。`web_module_manifest` 会校验非 public 后台模块的 `admin_boundary_policy` 与授权 requirement 对齐。
- 安全链路新增统一 `ClientIpResolver`。默认只信任 loopback 代理来源；可信代理请求优先读取 `Forwarded`，再读取 `X-Forwarded-For`，非可信来源忽略伪造转发头并回退到连接来源 IP。token binding、限流、IP block、登录/刷新安全事件均复用该解析器。
- Funboost 消费最终失败回调在执行记录不存在时不再二次抛错覆盖原始失败；当前行为为尝试 `try_mark_failed()`，缺失时写入中文结构化警告，并继续走统一失败回调记录。
- 环境入口已统一：仓库根 `.env.docker.example` / `.env` 是开发与 Docker 入口，`config/.env.example` 只保留废弃跳转说明。开发数据库名为 `fastapi_web_skeleton_dev`，测试库默认推导为 `fastapi_web_skeleton_dev_test`，默认本地密码为 `local-dev-postgres-password`。
- Web CORS 运行时按环境拆分：base 默认关闭，development/test 显式允许 localhost，production 通过 `web_runtime_production.toml` 明确关闭 CORS，不再隐式继承本地 allowlist。
- 本轮真实测试入口与结果如下：
  1. `docker compose -f compose.yml up -d`：首次因历史 PostgreSQL 数据卷仍使用旧密码且缺少 `fastapi_web_skeleton_dev` 数据库导致 migration 失败；已在本地容器内执行 `ALTER USER postgres WITH PASSWORD 'local-dev-postgres-password'` 并创建 `fastapi_web_skeleton_dev`，随后同一命令通过，`app`、`postgres`、`redis`、`rabbitmq` 均运行且健康；
  2. `.\.venv\Scripts\python.exe -m compileall -q src test`：通过；
  3. `.\.venv\Scripts\python.exe -m pytest -q test/unit_test/test_fastapi_app_assembler_unit.py test/unit_test/test_request_execution_bridge_unit.py test/unit_test/test_rabbitmq_message_bus_unit.py test/unit_test/test_funboost_task_dispatcher_unit.py test/unit_test/test_ip_block_guard_unit.py test/unit_test/test_settings_security_unit.py`：通过，`49 passed, 2 warnings`；
  4. `.\.venv\Scripts\python.exe -m pytest -q test/interface_test/test_admin_task_interface.py test/interface_test/test_security_protection_admin_interface.py test/path_test/test_task_runtime_path.py test/initialization_test/test_task_runtime_initialization.py`：通过，`29 passed, 3 warnings`；
  5. `$env:RABBITMQ_INTEGRATION_ENABLED='1'; .\.venv\Scripts\python.exe -m pytest -q -rs test/integration_test/test_funboost_rabbitmq_integration.py test/integration_test/test_security_ip_block_integration.py`：通过，`9 passed, 61 warnings`，无 skip；
  6. `$env:RABBITMQ_INTEGRATION_ENABLED='1'; .\.venv\Scripts\python.exe -m pytest -q`：通过，`630 passed, 62 warnings`。
- 当前仍存在既有第三方或历史测试告警：`pythonjsonlogger` 包路径迁移、`invoke` 使用 `imp`、`passlib` 读取 `argon2.__version__`、`funboost` 使用 Pydantic 旧接口，以及 `TestRouteBinder` 因辅助类构造函数被 Pytest 跳过收集。这些告警不影响本次验收结论。

### 12.22 2026-07-30 WebSocket 与 SSE 统一流式基建回归

- 流式能力的唯一业务入口为 `StreamEventSourcePort[TCommand, TDetail]`。业务源只产生强类型扩展事件，`StreamExecutionOrchestrator` 统一补齐 started/completed/fault、严格递增 sequence、会话超时、单事件字节上限和有界队列背压。非流式 HTTP、SSE 与 WebSocket 均复用该入口。
- 公开事件、客户端控制、操作绑定、访问票据、有限重放和 local/redis 运行时继续遵循“公共头字段 + 强类型扩展字段”。判别 kind、schema_version 或额外字段不一致时直接拒绝，不使用自由字典承载稳定契约。
- 非流式 HTTP 通过 `collect()` 执行最大事件数、最大字节数和超时三重限制，并使用现有 `ResponseEnvelope` 交付；它不是独立业务实现。
- SSE 通过 `sse-starlette` 输出 `id/event/data/retry`，固定 `Cache-Control: no-cache, no-transform` 与 `X-Accel-Buffering: no`，注释心跳不占用业务 sequence。Bearer 浏览器使用 POST fetch streaming；native EventSource 使用 GET、URL 编码强类型 command 和短期单次票据，禁止长期 JWT 查询参数。
- WebSocket 在 accept 前完成 Origin、Bearer/票据、授权、IP、限流和会话配额校验；新连接首帧只允许 subscribe 或 resume，订阅运行中只允许 cancel/ping。中途 resume、重复 subscribe 或其他非法状态转换会发送 stream_fault 并以 1008 关闭。关闭码冻结为 1000、1001、1008、1009、1011、1013。
- 实时交付语义为至多一次。Redis 只提供绑定主体与操作、受 TTL 和最大事件数约束的有限恢复窗口，不充当持久消息队列；票据消费使用原子操作并 fail-closed，已建连会话的重放写入失败只关闭恢复能力，实时发送继续并记录中文告警。
- `RequestScopeMiddleware`、`ElapsedProbeMiddleware`、`AccessLogMiddleware` 和指标出口已按纯 ASGI 生命周期覆盖 HTTP、SSE、WebSocket。会话结束后才记录耗时和访问日志；指标标签仅使用受控 transport/outcome/reason/event_kind 集合。
- lifespan 顺序为同步共享资源启动后再启动流资源；关闭时先拒绝新会话、通知现有会话、在 grace 内等待、取消剩余任务、关闭状态存储，再释放其他共享资源。生成器执行 `aclose()`，`CancelledError` 保持传播，会话租约幂等释放。
- Uvicorn 由 `python -m src.cli.run_web_server` 启动，并从 `runtime.stream` 投影 WS 消息大小、ping interval、ping timeout 和优雅停机参数。Compose 设置 40 秒 stop grace、PID/内存边界并注入 `REDIS_URL`。
- 当前生产绑定是管理员任务执行观察流：`/admin/tasks/executions/watch/batch`、`/admin/tasks/executions/watch/stream`、`/admin/tasks/executions/watch/ws`；`/admin/tasks/executions/watch/ticket` 仅在 `require_browser_ticket=true` 时注册。测试专用 `/testing/stream/*` 不进入生产路由。
- 最终项目环境回归为 `921 passed, 241 warnings`，总覆盖率 `90.07%`；独立流容量与真实 SSE/WS 反复连接测试为 `2 passed, 16 warnings`，资源增长保持在冻结阈值内。
- 完整协议、浏览器示例、代理要求和当前测试基线见 [WebSocket 与 SSE 统一流式协议](WebSocket与SSE统一流式协议.md)。若历史流式描述与该文档或当前源码冲突，以当前强类型契约为准。
