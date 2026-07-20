# FastAPI Web 骨架硬迁移总览

## 任务概览

### 任务来源
- 原始大型任务文档：`docs/2026_5_14_1853_fastapi_web骨架执行方案.md`
- 约束来源：
  - `docs/design_docs/FastAPI统一Web基础设施实现规格.md`
  - `docs/standard/命名规范.md`
  - `docs/standard/编码规范.md`
  - `docs/standard/测试规范.md`
  - `docs/技术选型.md`

### 任务目标
- 最终要交付一套可直接运行、可持续扩展、可回归测试的 FastAPI Web 基础设施骨架。
- 必须严格对齐实现规格、三份标准规范与既定技术选型。
- 本方案为硬迁移方案，目标是一次性将整个模块重构至最佳实践状态，不采用任何渐进式迁移设计。

### 完成判定
- `src` 下形成可启动的 FastAPI 基础骨架。
- 配置、日志、统一响应、统一异常、请求上下文、鉴权、ORM、缓存、消息/任务、测试基座具备首版落点。
- 自动化测试可真实执行并覆盖核心路径。
- 文档、契约、测试与源码一致。

### 源码现状说明
- 当前 `src` 仍是空骨架，仅存在顶层目录与 `__init__.py`、`main.py` 空文件。
- 因此本拆解以原始执行方案为主，以源码现状作为落点边界说明；后续真实改码时若文档、图谱、源码冲突，以源码为准，并在回归时标记文档可能过期。

## 基本约束

### 编码与设计约束
- Python 版本固定为 `3.11+`。
- 严格遵守 `docs/standard` 下的命名、编码、测试规范。
- 函数、类、文件命名必须满足语义清晰、角色明确、避免泛名。
- 所有正式日志使用中文，不允许 `print` 代替日志。
- 所有新增功能必须同步补测试；缺少规定测试项不得视为完成。

### 契约约束
- 统一响应、统一错误、任务消息、鉴权主体等稳定结构，必须采用“公共头字段 + 强类型扩展字段”规则。
- 扩展字段必须使用 Pydantic 判别联合。
- 扩展字段必须包含 `kind`、`schema_version`。
- 扩展字段模型必须启用 `extra="forbid"`。
- 禁止使用 `dict[str, Any]`、`metadata`、`extra_payload` 承载稳定协议。
- 外层类型与内层扩展类型必须一致，例如 `response_kind="token"` 时，内部扩展体也必须是 `kind="token"`。

### 技术选型约束
- Web：`fastapi` + `uvicorn`
- 数据建模：`pydantic v2`
- 配置：`pydantic-settings` + `rtoml`
- JSON：`orjson`
- ORM：`sqlalchemy 2.x` + `alembic`
- 数据库：开发默认 `sqlite`，生产目标 `postgresql`
- 缓存：本地 `cachetools`，可选 `redis`
- 消息队列：`rabbitmq`
- 任务队列：`funboost`
- 重试：`tenacity`
- 时间：`whenever`
- 鉴权：FastAPI OAuth2 Bearer 接入，协议语义遵循 `oauthlib`，令牌实现使用 JWT
- 测试：`pytest`

### 目录与配置约束
- 基础设施代码统一收口在 `src/infrastructure`，Web 装配实现直接放在该目录下。
- 配置目录固定采用 `config/app_* + config/modules/* + config/runtime/*` 三层结构，不再使用 `settings.*`。
- 生成代码时不得退回 `router.py`、`schemas.py`、`manager.py` 这类单泛词文件名。

## 全局验收标准
- 应用可通过统一入口启动，并成功挂载健康探针、系统概览、认证接口。
- 统一响应与统一错误输出稳定，响应中可带 `request_id`、`trace_id`、错误码。
- 配置按 `config/app_* + config/modules/* + config/runtime/*` 加载，开发环境可直接运行。
- 鉴权、ORM、缓存、消息/任务、热更新治理均有首版实现与测试覆盖。
- 至少通过单元测试、路径测试、初始化测试、异常测试、边界条件测试、接口测试、契约测试、集成测试中的本次适用集合。
- 设计文档、执行方案、契约、测试结果与源码一致。

## 全局生命周期
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
- Phase 1 无前置代码依赖，是整个骨架的起点。
- Phase 2 依赖 Phase 1 的统一契约、配置装配、应用装配、测试基座。
- Phase 3 依赖 Phase 1 与 Phase 2 的运行时落点，负责热更新治理、观测性收口和整体联通。

## 文件层次图
```text
docs/
  design_docs/
    FastAPI统一Web基础设施实现规格.md
  standard/
    命名规范.md
    编码规范.md
    测试规范.md
  技术选型.md
  2026_5_14_1853_fastapi_web骨架执行方案.md
  2026_5_14_fastapi_web骨架硬迁移拆解/
    fastapi_web骨架硬迁移总览.md
    phase_1_应用骨架与统一契约/
      应用骨架落地路线.md
      应用骨架勾检清单.md
    phase_2_鉴权与运行时底座/
      鉴权与底座落地路线.md
      鉴权与底座勾检清单.md
    phase_3_热更新与稳定化收口/
      热更新与收口路线.md
      热更新与收口勾检清单.md

config/
  .env.example
  app_base.toml
  app_development.toml
  app_test.toml
  modules/
    system_module/
      system_module_base.toml
    auth_module/
      auth_module_base.toml
    task_module/
      task_module_base.toml
  runtime/
    web_runtime/
      web_runtime_base.toml
    auth_runtime/
      auth_runtime_base.toml
    database_runtime/
      database_runtime_base.toml
    cache_runtime/
      cache_runtime_base.toml
    message_runtime/
      message_runtime_base.toml
    task_runtime/
      task_runtime_base.toml
    otel_runtime/
      otel_runtime_base.toml

src/
  main.py
  api/
    asgi_entry.py
    web_bundle_catalog.py
    dependency_context_accessor.py
    endpoint_health_probe/
      route_health_probe.py
      contract_health_probe.py
    endpoint_system_overview/
      route_system_overview.py
      contract_system_overview.py
    endpoint_auth_access/
      route_auth_access.py
      contract_auth_access.py
  application/
    health_probe_usecase.py
    system_overview_usecase.py
    issue_access_token_usecase.py
    refresh_access_token_usecase.py
    revoke_access_token_usecase.py
    dispatch_background_job_usecase.py
  core/
    http_contract/
      request_scope_contract.py
      response_envelope_contract.py
      runtime_resource_contract.py
      web_bundle_contract.py
    exception_contract/
      http_fault_contract.py
      error_code_catalog_contract.py
    auth_contract/
      authenticated_principal_contract.py
      token_payload_contract.py
      authorization_policy_contract.py
    persistence_contract/
      unit_of_work_contract.py
      repository_contract.py
    cache_contract/
      cache_store_contract.py
    task_contract/
      message_bus_contract.py
      task_dispatcher_contract.py
      task_handler_contract.py
  domain/
    auth/
      auth_error_code.py
      access_token_policy.py
  infrastructure/
    fastapi_app_assembler.py
    fastapi_route_composer.py
    fastapi_middleware_plan.py
    fastapi_exception_presenter.py
    fastapi_lifespan_orchestrator.py
    fastapi_openapi_surface.py
    fastapi_otel_bridge.py
    shared_resource_mount.py
    settings/
      app_settings_loader.py
      settings_snapshot_store.py
      settings_reload_coordinator.py
    logging/
      app_logger_factory.py
    context/
      request_context_manager_impl.py
    auth/
      jwt_token_service.py
      oauth2_scheme_provider.py
      authorization_policy_evaluator.py
      password_hasher.py
    persistence/
      sqlalchemy_engine_factory.py
      sqlalchemy_session_factory.py
      alembic_runner.py
      repository_impl/
    cache/
      memory_cache_store.py
      redis_cache_store.py
    task/
      local_message_bus.py
      local_task_dispatcher.py
      failed_task_recorder.py
      task_worker_supervisor.py
    middleware_chain/
      access_log_middleware.py
      elapsed_probe_middleware.py
      payload_guard_middleware.py
      request_scope_middleware.py
      security_header_middleware.py
      authentication_binding_middleware.py
    resource_slot/
      shared_http_client.py
      shared_db_session_manager.py
    testing/
      test_app_factory.py
      fake_clock.py
      fake_message_bus.py
      fake_cache_store.py

test/
  conftest.py
  unit_test/
  path_test/
  class_inheritance_test/
  initialization_test/
  exception_test/
  boundary_test/
  interface_test/
  contract_test/
  integration_test/
  convention_usage_test/
```

## 阶段拆解导航
- Phase 1：`phase_1_应用骨架与统一契约`
- Phase 2：`phase_2_鉴权与运行时底座`
- Phase 3：`phase_3_热更新与稳定化收口`

## 全局测试与回归收口

### 新增或修改测试
本次需要新增、修改以下测试：
- 单元测试：配置加载、统一响应、统一错误、JWT 服务、授权评估、缓存实现、任务调度器、错误码映射。
- 路径测试：中间件顺序、鉴权成功/失败路径、热更新成功/失败/回滚路径。
- 类继承测试：`CacheStore`、`MessageBus`、`TaskDispatcher`、`Repository`、`UnitOfWork` 具体实现的契约保持。
- 初始化测试：应用装配、数据库 session、缓存实例、任务调度器、OTel no-op 装配。
- 异常测试：非法配置、JWT 失效、数据库连接失败、缓存后端失败、任务执行失败。
- 边界条件测试：token 过期边界、分页/limit 上界、TTL 边界、重试次数边界、请求体大小边界。
- 接口测试：健康探针、系统概览、认证接口、受保护接口。
- 契约测试：统一响应、统一错误、认证载荷、任务消息扩展体。
- 集成测试：应用启动到数据库/缓存/任务依赖联通的最小链路。
- 用法规约测试：从启动、签发 token、访问受保护接口、派发任务到返回标准响应的端到端场景。

任务清单：
- [x] 新增 `unit_test` 覆盖核心纯逻辑与基础设施动作函数。
- [x] 新增 `path_test` 覆盖关键分支与回滚路径。
- [x] 新增 `class_inheritance_test` 覆盖关键抽象契约及其具体实现。
- [x] 新增 `initialization_test` 覆盖应用装配与资源初始化。
- [x] 新增 `exception_test` 与 `boundary_test` 覆盖异常和边界。
- [x] 新增 `interface_test`、`contract_test` 覆盖对外 HTTP 契约。
- [x] 新增 `integration_test`、`convention_usage_test` 覆盖关键端到端流程。

### 真实测试
最终统一执行以下真实测试，执行顺序固定：

1. 静态与基础校验
   - `python -m compileall src test`
2. 单元与基础白盒测试
   - `pytest test/unit_test test/path_test test/class_inheritance_test test/initialization_test test/exception_test test/boundary_test`
3. 接口与契约测试
   - `pytest test/interface_test test/contract_test`
4. 集成与用法规约测试
   - `pytest test/integration_test test/convention_usage_test`
5. 启动级烟雾验证
   - 基于测试配置启动应用并请求 `/health/live`、`/auth/token`

通过标准：
- 所有测试命令退出码为 `0`。
- 不允许跳过新增功能的规定测试类型。
- 启动级烟雾验证必须成功。

### 回归修复
真实测试失败后按以下顺序修复：
- 先判断失败来自源码、测试还是文档。
- 若是源码问题，优先修复契约破坏、初始化失败、关键路径失败。
- 若是测试问题，修正错误断言、过时夹具、错误的测试依赖假设。
- 若是文档问题，修正文档与源码不一致项，并标记原文档已过期。

修复完成后必须回跑：
- 失败测试所在类型测试集。
- 受影响接口的接口测试与契约测试。
- 至少一轮完整 `pytest` 回归。

任务清单：
- [x] 记录失败测试、失败原因和影响范围。
- [x] 修复源码或测试中的根因问题。
- [x] 回跑失败测试与受影响关联测试。
- [x] 回跑完整真实测试集合。

### 文档回归
需要修正以下文档：
- `docs/design_docs/FastAPI统一Web基础设施实现规格.md`
- 本拆解目录中的新增文档
- 代码中直接暴露的契约说明、配置样例、测试样例

文档需与以下内容保持一致：
- `src` 中最终实际文件结构
- 统一响应、统一错误、鉴权、任务消息的实际契约
- 实际测试入口、测试目录与测试通过结果
- 实际依赖启用方式与开发环境启动方式

任务清单：
- [x] 对照源码修正实现规格中过期路径或过期命名。
- [x] 对照测试结果修正测试入口与覆盖说明。
- [x] 对照实际契约修正响应、错误、鉴权、任务消息文档。
- [x] 确认文档中的配置层次图与源码一致。

## 2026-05-15 回归摘要

- 全量 `pytest` 已通过，结果为 `41 passed`。
- 启动烟雾验证已通过，本地 `uvicorn` 成功返回 `/health/live` 与 `/auth/token`。
- 实际修复了两处回归问题：
  - `passlib+bcrypt` 环境兼容问题导致认证成功路径失败，已切换为 `pbkdf2_sha256`
  - 请求体超限异常未转换为统一响应，已在 `PayloadGuardMiddleware` 内直接返回 `413`
- 本轮继续完成了两项基建收口：
  - 演示账号配置改为 `SecretStr` 承载明文，运行时统一归一化为密码散列索引，认证阶段不再临时散列
  - 热更新摘要与差异比对改为基于真实敏感值计算，避免 `SecretStr` 脱敏后漏检配置变更
