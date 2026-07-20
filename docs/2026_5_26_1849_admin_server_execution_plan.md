# 管理员服务端能力补齐执行方案

## 边界回归说明

本方案中的管理员后台暴露范围已被
`docs/2026_5_28_1055_业务管理后台边界整改执行方案.md`
覆盖。当前源码以 `/admin/*` 作为业务管理后台，默认只暴露用户管理、
预定义业务角色只读/分配和业务审计；`admin_task`、`admin_settings`、
`admin_log`、`security_protection`、`system_overview` 以及
`/security/ip-blocks*` 均不再作为默认业务后台能力交付。

通用任务派发、配置热重载、原始日志、安全事件、IP 封禁、系统运行时和
指标入口如后续保留，必须迁移到默认关闭的 `/ops/*`、CLI 或部署流程。

## 任务目标

交付管理员后台所需的服务端能力，不实现前端页面。完成后，前端可基于现有 `/auth/*`、`/system/info`、`/health/*`、`/security/ip-blocks*` 以及新增 `/admin/*` 接口开发管理员页面。

完成判定：管理员服务端具备任务记录查询、任务运行时查看、任务注册查看、手动任务派发、配置热更新、日志与安全事件查询能力；接口完成装配、鉴权、契约、测试和文档回归。

## 全局约束

- 若文档、图谱、源码冲突，以源码为准；现有文档可能过期，回归时必须同步修正。
- 只做服务端能力，不新增任何前端目录、页面、样式、脚本。
- 遵守 `docs/standard` 下编码、命名、测试规范；Python 使用 3.11+ 现代类型标注。
- 管理员能力独立分层：HTTP 层使用 `endpoint_admin_*`，应用层使用 `application/admin`，查询端口放入 `application/ports`，不得把管理员编排逻辑混入业务用例或基础设施实现。
- 已有接口继续复用：`/auth/token`、`/auth/refresh`、`/auth/revoke`、`/auth/me`、`/system/info`、`/health/live`、`/health/ready`、`/security/ip-blocks*`。
- 新增 HTTP 路由统一放在 `/admin/*`，并通过 `WebModuleManifestRegistry` 与 `app.modules.enabled` 装配。
- 权限以后端校验为准；本轮不新增 scope，沿用现有 `admin`、`auth:read`、`system:read`、`security:manage`、`task:dispatch`。
- 管理员账号来自 bootstrap admin 同步；本轮不做用户 CRUD、角色 CRUD、scope CRUD。
- Prometheus `/metrics` 默认关闭，不作为管理员核心接口；非生产 OpenAPI `/docs` 只作为开发辅助入口。
- 契约必须使用“公共头字段 + 强类型扩展字段”：扩展字段使用 Pydantic 判别联合，必须包含 `kind`、`schema_version`，必须启用 `extra="forbid"`；禁止 `dict[str, Any]`、`metadata`、`extra_payload`；外层类型与内层扩展类型必须一致。
- 管理员手动任务派发只允许已注册、已启用、已绑定 handler 的任务；请求体中的业务 payload 以 `payload_json: str` 承载，并由后端按注册的 Pydantic payload model 校验。
- 默认配置不得启用需要业务 handler 的任务；当前 `demo_task` 注册项保持 `enabled=false`，测试如需派发任务必须显式注入测试 handler。
- 日志与安全事件查询必须脱敏，不暴露 refresh token、密码、密钥、完整客户端 IP、完整 user-agent 等敏感值。

## 验收标准

- 现有鉴权、系统、健康、安全 IP 封禁接口可作为管理员页面后端能力复用。
- `/admin/tasks/*` 支持任务记录列表/详情、运行时信息、注册信息、手动派发。
- `/admin/settings/reload/*` 支持候选版本读取和热更新执行，结果包含成功、回滚、原因、恢复资源、当前快照。
- `/admin/logs` 与 `/admin/security-events` 支持受控查询，返回脱敏后的结构化结果。
- 所有新增接口具备响应契约、权限校验、错误处理、接口测试、契约测试。
- `create_app + lifespan + GET /health/live` smoke test 通过。
- `uv run pytest` 完整回归通过。
- 文档、契约、测试说明与最终源码一致。

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

- Phase 1 是管理员服务端边界、模块装配、权限复用的基础，后续 Phase 均依赖它。
- Phase 2 依赖 Phase 1，并依赖现有 `TaskRuntimePort`、`DispatchBackgroundJobUsecase`、任务注册中心和任务执行记录存储。
- Phase 3 依赖 Phase 1，并依赖现有 `SettingsReloadCoordinator`。
- Phase 4 依赖 Phase 1，并依赖现有 `app_log_record`、`LogEventEnvelope`、`SecurityEventEnvelope`。
- Phase 5 依赖 Phase 1 至 Phase 4 的新增接口与契约稳定。

## 文件层次图

```text
src/
  core/
    http_contract/
      web_bundle_contract.py                    # 修改：补充管理员 Web 模块名
  api/
    dependency_context_accessor.py              # 修改：补充管理员用例与 reload coordinator 读取入口
    web_module_manifest.py                      # 修改：注册管理员服务端 provider
    endpoint_admin_task/
      __init__.py                               # 新增
      contract_admin_task.py                    # 新增：任务管理 HTTP 契约
      route_admin_task.py                       # 新增：任务管理路由
    endpoint_admin_settings/
      __init__.py                               # 新增
      contract_admin_settings.py                # 新增：配置热更新 HTTP 契约
      route_admin_settings.py                   # 新增：配置热更新路由
    endpoint_admin_log/
      __init__.py                               # 新增
      contract_admin_log.py                     # 新增：日志/安全事件查询 HTTP 契约
      route_admin_log.py                        # 新增：日志/安全事件查询路由
  application/
    ports/
      task_runtime_port.py                      # 修改：补任务注册/载荷校验查询能力
      admin_settings_reload_port.py             # 新增：配置热更新应用端口
      admin_log_query_port.py                   # 新增：日志查询应用端口
    admin/
      __init__.py                               # 新增：管理员应用层边界
      list_admin_task_execution_records_usecase.py
      get_admin_task_execution_record_usecase.py
      read_admin_task_runtime_usecase.py
      list_admin_task_registrations_usecase.py
      dispatch_admin_task_usecase.py
      build_admin_settings_reload_candidate_usecase.py
      apply_admin_settings_reload_usecase.py
      list_admin_log_records_usecase.py
      list_admin_security_events_usecase.py
  infrastructure/
    admin_settings_reload_adapter.py            # 新增：配置热更新基础设施适配器
    fastapi_app_assembler.py                    # 修改：注入管理员用例
    shared_resource_mount.py                    # 修改：实现新增端口方法
    persistence/
      repository_impl/
        log_record_repository_impl.py           # 修改：补日志查询过滤
config/
  app_base.toml                                 # 修改：启用管理员服务端模块
test/
  contract_test/
    test_admin_task_contract.py                 # 新增
    test_admin_settings_contract.py             # 新增
    test_admin_log_contract.py                  # 新增
  unit_test/
    test_admin_task_usecase_unit.py             # 新增
    test_admin_settings_usecase_unit.py         # 新增
    test_admin_log_query_unit.py                # 新增
  interface_test/
    test_admin_task_interface.py                # 新增
    test_admin_settings_interface.py            # 新增
    test_admin_log_interface.py                 # 新增
  integration_test/
    test_admin_smoke_integration.py             # 新增：create_app + lifespan + /health/live
docs/
  2026_5_26_1849_admin_server_execution_plan.md # 新增：本执行方案
```

## Phase 1

### 目标

建立管理员服务端隔离边界与模块装配基础。完成后，新增管理员 HTTP provider 可以被 manifest 发现，并按配置装配到 FastAPI。

### 依赖

依赖现有 `WebBundleCatalog`、`WebModuleManifestRegistry`、`FastApiAppAssembler`、`DependencyContextAccessor`、`AuthorizationGuard`、`ResponseEnvelope`。

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| AdminTaskModuleName | 管理员任务模块名 | 新增管理员任务 HTTP 模块标识，用于 manifest 与 `app.modules.enabled` 校验 |
| AdminSettingsModuleName | 管理员配置模块名 | 新增管理员配置热更新 HTTP 模块标识 |
| AdminLogModuleName | 管理员日志模块名 | 新增管理员日志/安全事件 HTTP 模块标识 |
| AdminRouteAuthorizationRequirement | 管理员路由授权要求 | 复用 `RouteAuthorizationRequirement`，要求 `admin` 角色和对应 scope |
| AdminApplicationUsecaseSet | 管理员应用用例集合 | 由 `FastApiAppAssembler` 注入，避免路由直接拼装基础设施对象 |

### 任务清单

- [x] 在 `ApplicationModuleName` 增加管理员任务、配置、日志模块名。
- [x] 在 `web_module_manifest.py` 增加三个管理员 provider import path、route tag 和 manifest entry。
- [x] 在 `config/app_base.toml` 的 `app.modules.enabled` 增加管理员服务端模块。
- [x] 在 `ApplicationContainer` 增加管理员用例字段。
- [x] 在 `DependencyContextAccessor` 增加管理员用例、`reload_coordinator`、`resource_mount` 的显式读取入口。
- [x] 为管理员路由定义统一授权常量：任务查询 `admin + system:read`，任务派发 `admin + task:dispatch`，配置热更新 `admin + system:read`，日志/安全事件查询 `admin + system:read`。
- [x] 确认默认 `demo_task` 注册项保持 `enabled=false`，不依赖业务 handler 启动。

### 校验

- `WebBundleCatalog.validate_enabled_modules()` 能识别新增管理员模块名。
- 未启用管理员模块时不装配对应路由。
- 启用管理员模块但未登录时返回 401。
- 缺少要求 scope 时返回 403，并写入授权拒绝安全事件。

## Phase 2

### 目标

补齐任务管理服务端能力。完成后，管理员可通过 HTTP 查询任务执行记录、查看任务运行时和注册信息，并对已绑定任务执行手动派发。

### 依赖

依赖 Phase 1；依赖 `TaskRuntimePort`、`TaskExecutionRecordEnvelope`、`TaskRegistrationEnvelope`、`DispatchBackgroundJobUsecase`、`TaskRegistrationRegistry`。

### 模拟用法

```text
GET  /admin/tasks/executions?status=FAILED&job_kind=demo_task&limit=50
GET  /admin/tasks/executions/{task_id}
GET  /admin/tasks/runtime
GET  /admin/tasks/registrations
POST /admin/tasks/dispatch
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| AdminTaskQueryHeader | 任务查询公共头 | 承载 `kind`、`schema_version`、查询场景，外层与扩展类型保持一致 |
| AdminTaskExecutionListPayload | 任务记录列表载荷 | 返回任务执行记录列表，支持 `PENDING`、`RUNNING`、`RETRYING`、`SUCCESS`、`FAILED` |
| AdminTaskExecutionRecordPayload | 任务记录详情载荷 | 展示 `record_id`、`task_id`、`job_kind`、`deduplication_key`、`backend`、`queue_name`、`request_id`、`trace_id`、`created_at_epoch` |
| AdminTaskExecutionRuntimePayload | 任务运行详情载荷 | 展示 `attempt_count`、`started_at_epoch`、`finished_at_epoch`、`failed_at_epoch`、`next_retry_at_epoch`、`last_error_type`、`last_error_message` |
| AdminTaskRuntimePayload | 任务运行时载荷 | 展示当前 backend、默认 job kind、默认 retry limit |
| AdminTaskRegistrationListPayload | 任务注册列表载荷 | 展示任务名、job kind、启用状态、backend、retry limit、queue、exchange、routing key |
| AdminTaskDispatchRequest | 管理员任务派发请求 | 公共头 + 判别联合扩展；字段为 `job_kind`、`payload_json`、`retry_limit`、`deduplication_key` |
| AdminTaskDispatchResultPayload | 管理员任务派发结果 | 返回 `task_id`、backend、queue、状态、阶段、是否复用执行记录 |

### 任务清单

- [x] 扩展 `TaskRuntimePort`，增加任务注册列表读取和按 job kind 校验 payload JSON 的能力。
- [x] 在 `SharedResourceMount` 实现新增 `TaskRuntimePort` 方法，不向应用层暴露注册中心实现细节。
- [x] 新增 `list_admin_task_execution_records_usecase.py`，支持 `status`、`job_kind`、`limit`。
- [x] 新增 `get_admin_task_execution_record_usecase.py`，按 `task_id` 查询，不存在返回 404。
- [x] 新增 `read_admin_task_runtime_usecase.py`，返回当前 backend、默认 job kind、默认 retry limit。
- [x] 新增 `list_admin_task_registrations_usecase.py`，返回当前后端相关注册项和 handler 绑定状态。
- [x] 新增 `dispatch_admin_task_usecase.py`，先校验注册、启用、handler 绑定、payload JSON，再复用 `DispatchBackgroundJobUsecase` 派发。
- [x] 新增 `endpoint_admin_task` 契约与路由 provider。
- [x] 任务查询接口要求 `admin + system:read`，任务派发接口要求 `admin + task:dispatch`。
- [x] 对 `limit` 做 `1..200` 边界约束。

### 关键代码片段

```python
class AdminTaskDispatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: AdminTaskDispatchHeader
    detail: AdminTaskDispatchDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> "AdminTaskDispatchEnvelope":
        if self.header.kind != self.detail.kind:
            raise ValueError("任务派发 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务派发 schema_version 必须一致。")
        return self
```

### 校验

- `GET /admin/tasks/executions` 可按状态、job kind、limit 查询。
- `GET /admin/tasks/executions/{task_id}` 对不存在记录返回 404。
- 无 handler 绑定或任务未启用时，`POST /admin/tasks/dispatch` 返回明确错误，不写入半成品任务。
- `payload_json` 不符合注册 payload model 时返回 422 或业务契约错误。

## Phase 3

### 目标

补齐配置热更新管理员 HTTP 能力。完成后，管理员可读取候选配置版本并触发当前环境配置热更新。

### 依赖

依赖 Phase 1；依赖 `SettingsReloadCoordinator.build_candidate()`、`SettingsReloadCoordinator.reload()`、`ReloadCandidatePayload`、`ReloadResultPayload`。

### 模拟用法

```text
GET  /admin/settings/reload/candidate
POST /admin/settings/reload
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| AdminSettingsReloadHeader | 配置热更新公共头 | 承载 `kind`、`schema_version`、操作名，外层与扩展类型保持一致 |
| AdminSettingsReloadCandidatePayload | 热更新候选版本载荷 | 展示 `candidate_version`、`digest` |
| AdminSettingsReloadRequest | 热更新请求 | 只触发当前 environment 的 reload，不接收任意配置覆盖 |
| AdminSettingsReloadResultPayload | 热更新结果载荷 | 展示 `success`、`rolled_back`、`reason`、`restored_resources`、`active_snapshot_id` |
| AdminSettingsReloadDetail | 热更新扩展字段 | Pydantic 判别联合扩展，禁止裸配置字典和任意 overrides |

### 任务清单

- [x] 新增 `build_admin_settings_reload_candidate_usecase.py`，读取当前 environment 并调用 reload coordinator 构建候选。
- [x] 新增 `apply_admin_settings_reload_usecase.py`，只对当前 environment 执行 reload。
- [x] 新增 `endpoint_admin_settings` 契约与路由 provider。
- [x] 配置热更新接口要求 `admin + system:read`。
- [x] 禁止 HTTP 请求传入任意 `overrides`、密钥原文或配置字典。
- [x] 对失败回滚结果保持原样返回，但不暴露敏感配置值。

### 关键代码片段

```python
class AdminSettingsReloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_settings_reload"] = "admin_settings_reload"
    schema_version: Literal["1.0"] = "1.0"
```

### 校验

- 候选接口返回稳定 `candidate_version` 与 `digest`。
- 热更新成功时返回 `success=true`、`rolled_back=false`。
- 热更新被安全策略拒绝时返回 `success=false` 与拒绝原因。
- 请求体携带未知字段时被 Pydantic 拒绝。

## Phase 4

### 目标

补齐应用日志与安全事件查询能力。完成后，管理员可按日志维度和安全事件维度查询结构化、脱敏后的记录。

### 依赖

依赖 Phase 1；依赖 `app_log_record` 表、`LogEventEnvelope`、`LogDetailUnion`、`SecurityEventEnvelope`、`SecurityEventType`。

### 模拟用法

```text
GET /admin/logs?level=ERROR&event_kind=exception&limit=50
GET /admin/logs?request_id=req-xxx&trace_id=trace-xxx
GET /admin/security-events?event_type=auth.refresh.reused&limit=50
```

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| AdminLogQueryHeader | 日志查询公共头 | 承载 `kind`、`schema_version`、查询场景，外层与扩展类型保持一致 |
| AdminLogRecordListQuery | 日志列表查询 | 支持 `level`、`event_kind`、`request_id`、`trace_id`、时间范围、`limit` |
| AdminLogRecordPayload | 日志记录载荷 | 展示 event id、级别、事件类型、消息、时间、request id、trace id、主体、来源 |
| AdminLogRecordDetail | 日志详情扩展 | 复用强类型日志 detail，不返回裸 JSON 详情 |
| AdminSecurityEventListQuery | 安全事件查询 | 支持安全事件类型、严重级别、决策、时间范围、`limit` |
| AdminSecurityEventPayload | 安全事件载荷 | 展示登录失败、登录限流、密码喷洒疑似、刷新令牌复用、令牌无效、权限拒绝、IP 封禁/解封、限流拦截、payload 过大、SSRF 拦截、Token-IP 不匹配、配置安全拒绝 |
| AdminLogRecordListPayload | 日志列表响应 | 返回分页限制内的脱敏记录集合 |

### 任务清单

- [x] 新增 `AdminLogQueryPort`，定义日志记录查询和安全事件查询能力。
- [x] 在 `LogRecordRepositoryImpl` 增加查询方法，支持 level、event kind、request id、trace id、时间范围、limit。
- [x] 查询时将 `detail_json` 反序列化为 `LogEventEnvelope` 或对应 detail 强类型模型。
- [x] 新增 `list_admin_log_records_usecase.py`，返回脱敏日志列表。
- [x] 新增 `list_admin_security_events_usecase.py`，只返回 `event_kind=security` 的安全事件。
- [x] 新增 `endpoint_admin_log` 契约与路由 provider。
- [x] 日志与安全事件查询接口要求 `admin + system:read`。
- [x] 对不可解析的历史日志详情保守降级为摘要，不返回原始 JSON。

### 关键代码片段

```python
AdminLogRecordDetailUnion = Annotated[
    AdminAccessLogDetail
    | AdminExceptionLogDetail
    | AdminResourceLifecycleLogDetail
    | AdminTaskFailureLogDetail
    | AdminSecurityLogDetail,
    Field(discriminator="kind"),
]
```

### 校验

- `/admin/logs` 可按 level、event kind、request id、trace id、时间范围过滤。
- `/admin/security-events` 只返回安全事件，且可按 `SecurityEventType` 过滤。
- 返回结果不包含密码、refresh token、密钥、完整 IP。
- `limit=0`、`limit=201` 被拒绝或按契约归一，行为由测试固定。

## Phase 5

### 目标

完成服务端闭环验收：既有管理员可复用接口、新增 `/admin/*` 接口、默认配置、lifespan smoke 和完整回归都稳定。

### 依赖

依赖 Phase 1 至 Phase 4；依赖测试配置、bootstrap admin、默认禁用 demo task 的配置状态。

### 契约

| 英文名 | 中文名 | 中文说明 |
|---|---|---|
| AdminSmokeScenario | 管理员冒烟场景 | 覆盖 `create_app + lifespan + /health/live`，确认默认配置可启动 |
| AdminExistingApiReuseMatrix | 既有接口复用矩阵 | 明确 `/auth/*`、`/system/info`、`/health/*`、`/security/ip-blocks*` 无需新增重复管理员路由 |
| AdminRegressionResult | 管理员回归结果 | 记录本轮真实测试入口、结果和遗留风险 |

### 任务清单

- [x] 确认 `/auth/token`、`/auth/refresh`、`/auth/revoke`、`/auth/me` 契约满足前端登录和会话续期。
- [x] 确认 `/system/info` 返回系统标题、应用名、版本、环境、enabled modules、ready、runtime resources。
- [x] 确认 `/health/live`、`/health/ready` 对 ready 503 的行为符合前端展示需要。
- [x] 确认 `/security/ip-blocks*` 已支持列表、详情、创建、释放、`released=false`。
- [x] 确认默认配置没有启用需要业务 handler 的任务。
- [x] 新增真实 `create_app + lifespan + GET /health/live` smoke test。
- [x] 汇总管理员服务端接口清单，标明“已存在复用”和“本轮新增”。

### 校验

- 默认 `create_app()` 可以完成 lifespan 启动和关闭。
- `GET /health/live` 在 lifespan 内返回 200。
- 新增管理员模块启用后，OpenAPI 能生成对应路由。
- 管理员开发可以在服务端能力闭环后开始。

## 新增或修改测试

本次测试覆盖新增行为、变更行为和回归行为。

- [x] 契约测试：`test_admin_task_contract.py` 覆盖任务查询、任务详情、运行时、注册列表、派发请求和未知字段拒绝。
- [x] 契约测试：`test_admin_settings_contract.py` 覆盖热更新候选、请求、结果和禁止 overrides。
- [x] 契约测试：`test_admin_log_contract.py` 覆盖日志、安全事件、判别联合、脱敏载荷。
- [x] 单元测试：`test_admin_task_usecase_unit.py` 覆盖任务列表过滤、详情不存在、运行时信息、注册信息、派发校验。
- [x] 单元测试：`test_admin_settings_usecase_unit.py` 覆盖候选读取、reload 成功、reload 拒绝、reload 回滚。
- [x] 单元测试：`test_admin_log_query_unit.py` 覆盖日志过滤、安全事件过滤、不可解析历史 detail 降级。
- [x] 接口测试：`test_admin_task_interface.py` 覆盖 401、403、200、404、422。
- [x] 接口测试：`test_admin_settings_interface.py` 覆盖候选读取、热更新执行、未知字段拒绝。
- [x] 接口测试：`test_admin_log_interface.py` 覆盖日志查询、安全事件查询、脱敏断言。
- [x] 集成测试：`test_admin_smoke_integration.py` 覆盖 `create_app + lifespan + GET /health/live`。
- [x] 回归测试：补充默认 demo task 禁用断言，避免默认启动依赖业务 handler。

## 真实测试

最终统一按以下顺序执行，全部通过才算完成。

```text
uv run pytest test/contract_test/test_admin_task_contract.py
uv run pytest test/contract_test/test_admin_settings_contract.py
uv run pytest test/contract_test/test_admin_log_contract.py
uv run pytest test/unit_test/test_admin_task_usecase_unit.py
uv run pytest test/unit_test/test_admin_settings_usecase_unit.py
uv run pytest test/unit_test/test_admin_log_query_unit.py
uv run pytest test/interface_test/test_admin_task_interface.py
uv run pytest test/interface_test/test_admin_settings_interface.py
uv run pytest test/interface_test/test_admin_log_interface.py
uv run pytest test/integration_test/test_admin_smoke_integration.py
uv run pytest
```

通过标准：所有测试退出码为 0；新增接口的 401、403、404、422、503、重复释放、reload 回滚、payload JSON 校验等场景都有明确断言。

## 回归修复

真实测试失败后按失败类型回归修复，并回跑对应最小测试集和最终完整测试。

- [x] 契约失败：优先修正 Pydantic 模型、判别联合、`extra="forbid"`、header/detail 一致性。
- [x] 权限失败：修正路由 `RouteAuthorizationRequirement` 和接口测试中的主体 scope。
- [x] 任务失败：检查 `TaskRuntimePort`、注册项启用状态、handler 绑定、payload JSON 校验和 `DispatchBackgroundJobUsecase` 调用。
- [x] 热更新失败：检查 `SettingsReloadCoordinator` 注入、当前 environment 读取、禁止 overrides、回滚结果映射。
- [x] 日志失败：检查 `LogRecordRepositoryImpl` 过滤条件、强类型 detail 反序列化和脱敏映射。
- [x] smoke 失败：检查默认配置、demo task 禁用状态、lifespan 资源启动顺序。
- [x] 修复后回跑失败用例对应测试文件。
- [x] 最后回跑 `uv run pytest`。

## 文档回归

需要修正的文档只围绕本次服务端能力，不补前端页面文档。

- [x] 更新管理员服务端接口清单，区分“已有复用接口”和“新增 `/admin/*` 接口”。
- [x] 更新配置说明，标明默认任务注册项禁用、业务启用任务需提供 handler 绑定。
- [x] 更新安全说明，标明管理员接口权限、日志脱敏和安全事件类型。
- [x] 更新测试说明，记录新增测试入口和 smoke test。
- [x] 如实现与本方案不一致，以最终源码为准回写本文档或新增回归说明。

## 文档回归说明

### 管理员服务端接口清单

以下为 2026-05-26 原方案的历史接口清单；当前 `/admin/*` 已收敛为业务后台，
ops 能力不再默认进入业务后台。

原方案复用接口：`/auth/token`、`/auth/refresh`、`/auth/revoke`、`/auth/me`、`/system/info`、`/health/live`、`/health/ready`、`/security/ip-blocks*`。

原方案新增接口，当前已移出默认业务后台：`GET /admin/tasks/executions`、`GET /admin/tasks/executions/{task_id}`、`GET /admin/tasks/runtime`、`GET /admin/tasks/registrations`、`POST /admin/tasks/dispatch`、`GET /admin/settings/reload/candidate`、`POST /admin/settings/reload`、`GET /admin/logs`、`GET /admin/security-events`。

原方案后续管理员身份接口，当前仅默认保留用户管理、预定义业务角色只读和用户角色分配：
`GET /admin/scopes`、`GET /admin/scopes/{scope_code}`、`POST /admin/scopes`、`PATCH /admin/scopes/{scope_code}`、`DELETE /admin/scopes/{scope_code}`、`GET /admin/roles`、`GET /admin/roles/{role_key}`、`POST /admin/roles`、`PATCH /admin/roles/{role_key}`、`POST /admin/roles/{role_key}/scopes`、`DELETE /admin/roles/{role_key}`、`GET /admin/users`、`GET /admin/users/{subject_id}`、`POST /admin/users`、`PATCH /admin/users/{subject_id}`、`POST /admin/users/{subject_id}/password`、`POST /admin/users/{subject_id}/roles`、`DELETE /admin/users/{subject_id}`。

### 配置说明

本段为 2026-05-26 原管理员服务端方案的历史配置说明；当前默认配置已由
`docs/2026_5_28_1055_业务管理后台边界整改执行方案.md` 覆盖，业务后台不再默认启用
`admin_task`、`admin_settings`、`admin_log`、`security_protection` 与
`system_overview`。通用任务派发、配置热重载、原始日志、安全事件和系统运行时能力如需保留，
必须迁移到默认关闭的 `/ops/*`、CLI 或部署流程。测试与开发 bootstrap admin 默认角色绑定仍包含
`auth:manage`，仅用于身份初始化和受控测试场景。

### 安全说明

管理员查询类接口统一要求 `admin + system:read`，任务派发接口要求 `admin + task:dispatch`。管理员身份查询接口要求 `admin + auth:read`，用户、角色和 scope 写接口要求 `admin + auth:manage`。日志接口只返回强类型脱敏载荷，不返回原始 `detail_json`，访问日志不会暴露完整客户端 IP 或完整 user-agent；安全事件只暴露摘要、决策、类型和 digest 字段。管理员身份写操作会记录安全事件，不暴露密码原文和密码哈希。

### 测试说明

已新增管理员契约、单元、接口与冒烟集成测试，并在 Docker Compose 项目环境中执行 `uv run pytest -q` 完整回归。2026-05-27 管理员身份 CRUD 回归后，完整结果为 `482 passed, 71 warnings`。

### 实现回归说明

为遵守应用层边界，配置热更新用例通过 `AdminSettingsReloadPort` 访问热更新能力，由 `AdminSettingsReloadAdapter` 在基础设施层适配 `SettingsReloadCoordinator`。另修复请求执行桥接器在热更新过程中关闭当前线程池时可能触发的自 join 问题。
