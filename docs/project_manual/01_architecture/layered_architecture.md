# 分层架构

## 1. 这是什么

本文详细定义 `src/api`、`src/application`、`src/core`、`src/domain`、`src/infrastructure` 五层各自"是什么、放什么、禁止放什么"，以及两个有意保留的契约例外（`WebBundle`、`PersistenceSession`）为什么存在。它是代码评审时判断"这段代码放错层了吗"的直接依据。

**最后更新范围**：覆盖五层全部子包、`src/application/ports` 端口清单、import-linter 契约与 Web 模块装配边界。

## 2. 设计思想与动机

分层的唯一目的：**让变化的代价与变化的频率匹配**。HTTP 表面、外部组件选型（换缓存/换消息队列）变化频繁，放在外层；业务规则与数据契约变化慢、影响大，放在内层。依赖只能由外向内，这样内层永远不需要"知道"外层的存在，就可以：

- 在测试中用 SQLite/内存 fake 替换 PostgreSQL/Redis 而不改用例代码；
- 热更新时整体替换 HTTP 客户端与任务运行时而不动路由；
- 保证 `src/core` 契约可以被 Web 进程与 task-worker 进程共同复用。

依赖方向不是靠约定维持，而是由 `pyproject.toml` 中 4 条 import-linter forbidden 契约在静态检查阶段强制：

```112:134:pyproject.toml
[[tool.importlinter.contracts]]
name = "核心层禁止反向依赖"
type = "forbidden"
source_modules = ["src.core"]
forbidden_modules = ["src.api", "src.application", "src.domain", "src.infrastructure"]

[[tool.importlinter.contracts]]
name = "领域层禁止依赖外层"
type = "forbidden"
source_modules = ["src.domain"]
forbidden_modules = ["src.api", "src.application", "src.infrastructure"]

[[tool.importlinter.contracts]]
name = "应用层禁止依赖适配器"
type = "forbidden"
source_modules = ["src.application"]
forbidden_modules = ["src.api", "src.infrastructure"]

[[tool.importlinter.contracts]]
name = "基础设施禁止依赖 API"
type = "forbidden"
source_modules = ["src.infrastructure"]
forbidden_modules = ["src.api"]
```

## 3. 各层内容清单

### 3.1 `src/core` —— 核心契约层

按能力域拆分为 11 个 `*_contract` 子包：`auth_contract`（令牌载荷、认证主体、授权策略、刷新令牌失效、节流状态）、`cache_contract`（命名空间、载荷编码、策略、运行时、存储 Protocol）、`concurrency_contract`（分布式锁、运行时容量）、`exception_contract`（`CoreErrorCode` 错误码目录、`HttpFaultException`）、`http_contract`（响应信封、请求作用域、请求执行策略、出站 HTTP 客户端、安全运行时、运行时资源状态、WebBundle）、`key_management_contract`、`logging_contract`（日志事件/运行时/写入器）、`observability_contract`（指标运行时、告警规则）、`persistence_contract`（仓储契约、UnitOfWork）、`security_contract`（安全事件、限流策略、IP 封禁、出站 URL 安全、Token 绑定）、`task_contract`（消息总线、调度器、执行记录、处理器、调用、注册、运行时）。

内容形态只允许四种：Pydantic 模型（一律 `extra="forbid"`）、`StrEnum`、`typing.Protocol`、异常类。**不允许任何 IO、任何框架对象**——唯一例外见 3.6。

### 3.2 `src/domain` —— 领域层

当前集中在 `src/domain/auth`：

- `admin_route_authorization_policy.py`：全部后台路由的 `RouteAuthorizationRequirement` 常量（14 个 requirement），`BUSINESS_ADMIN_/OPS_ONLY_` 两组集合，以及派生的 `PROTECTED_ADMIN_SCOPE_CODES` 受保护 scope 注册表（保护性 scope 不允许被后台 scope 管理接口删除）。
- `auth_role_key.py` / `auth_scope_code.py`：角色键（`admin`）与 10 个 scope code（`auth:read`、`auth:manage`、`auth:user_manage`、`auth:role_manage`、`auth:scope_manage`、`auth:password_reset`、`auth:grant_admin`、`security:manage`、`system:read`、`task:dispatch`）。
- `auth_error_code.py`：8 个稳定鉴权错误码（`auth.access.*`、`auth.token.*`、`auth.authorization.permission_denied`、`auth.request.throttled`）。
- `access_token_policy.py`：JWT 策略值对象。
- `authorization_policy_evaluator.py`：纯函数式的角色/scope 求值器。

领域层放"业务事实"，不放流程。判断标准：这条规则换一个 Web 框架、换一个数据库依然成立，就属于领域层。

### 3.3 `src/application` —— 应用层

- 根级用例：`health_probe_usecase`、`system_overview_usecase`、`issue_access_token_usecase`、`refresh_access_token_usecase`、`revoke_access_token_usecase`、`dispatch_background_job_usecase`、`authorization_guard`。
- `admin/` 子树：任务管理（5 个）、配置热更新（2 个）、日志查询（2 个）、安全 IP 封禁（4 个）、审计查询（1 个）、身份管理（`identity/user|role|scope` 各 5-7 个 + `initial_admin`）。每个用例一个文件、一个 `execute()` 入口。
- `ports/`：`auth_runtime_port`、`task_runtime_port`、`admin_identity_port`、`admin_log_query_port`、`admin_audit_query_port`、`admin_settings_reload_port`、`settings_reader_port` 等 Protocol。`SharedResourceMount` 是这些端口的统一实现者。

用例约束：构造函数只收端口；`execute()` 是唯一公开入口；事务边界（`create_unit_of_work` → commit/rollback/dispose）在用例内闭合；不 import ORM 模型、SQLAlchemy `Session`、FastAPI `Request`。

### 3.4 `src/api` —— 接口层与组合根

- `endpoint_*/`：9 个模块，每个模块固定为 `contract_*.py`（请求/响应 Pydantic 模型）+ `route_*.py`（`*RouteCatalog` 构建 `APIRouter` + `*BundleProvider` 输出 `WebBundle`）。
- `web_module_manifest.py` / `web_bundle_catalog.py`：模块清单与 provider 装载（动态 import + 五重一致性校验：模块名重复、import 路径、route tags、provider 类型、manifest/provider 模块名一致）。
- `dependency_context_accessor.py`：路由层唯一依赖读取器。
- `fastapi_app_assembler.py` / `asgi_entry.py`：组合根与 ASGI 工厂。
- `admin_list_page_contract.py`：后台列表分页通用契约。
- `testing/`：`TestAppFactory` 测试装配工厂（仅测试使用）。
- `evidence/`：公共契约快照构建器（证据链工具，不参与请求处理）。

### 3.5 `src/infrastructure` —— 基础设施层

按能力域分包：`persistence`（引擎/会话工厂/ORM/仓储/Alembic）、`cache`、`task`、`logging`、`security`、`observability`、`key_management`、`concurrency`、`settings`、`middleware_chain`、`context`、`resource_mount`、`resource_slot`、`auth`（密码哈希、JWT、OAuth2 提取、节流、bootstrap admin）、`evidence`、`testing`（fake，仅测试）。根级另有 FastAPI 粘合件：`fastapi_middleware_plan`、`fastapi_exception_presenter`、`fastapi_lifespan_orchestrator`、`fastapi_route_composer`、`fastapi_openapi_surface`、`fastapi_otel_bridge`、`request_execution_bridge`、`orjson_document_response`、`shared_resource_mount`。

### 3.6 两个有意的契约例外

| 例外 | 位置 | 为什么允许 |
| --- | --- | --- |
| `WebBundle` 持有 `fastapi.APIRouter` | `src/core/http_contract/web_bundle_contract.py` | Web 模块 provider（api 层）与路由组装器（infrastructure 层）需要一个交接类型；若不放 core 会造成 api ↔ infrastructure 直接依赖。它是 HTTP 表面装配契约，不代表业务契约可以引用 FastAPI。 |
| `PersistenceSession` 名义会话协议 | `src/core/persistence_contract/unit_of_work_contract.py` | 仓储工厂方法（`AuthRuntimePort.create_*_repository(session)`）需要一个会话类型参数。core 只暴露最小协议，具体的 `SqlAlchemyPersistenceSession`（同时继承 SQLAlchemy `Session` 与该协议）留在 infrastructure。 |

这两个例外的共同特点：都是**装配期交接契约**，不会出现在业务用例的签名里。

## 4. 怎么用：代码归属决策表

| 你要写的东西 | 放哪 | 例子 |
| --- | --- | --- |
| 请求/响应字段模型 | `src/api/endpoint_*/contract_*.py` | `TokenIssueRequest` |
| 跨进程/跨层复用的数据形状 | `src/core/*_contract` | `TaskMessageEnvelope` |
| 业务规则常量（角色、scope、错误码） | `src/domain` | `AuthScopeCode` |
| 一个业务动作的流程 | `src/application/*_usecase.py` | `RefreshAccessTokenUsecase` |
| 用例需要的新外部能力 | 先在 `src/application/ports` 定义 Protocol，再在 infrastructure 实现 | `AdminAuditQueryPort` |
| 对接外部组件的代码 | `src/infrastructure/<域>` | `RedisCacheStore` |
| 新中间件 | `src/infrastructure/middleware_chain` + 注册进 `FastApiMiddlewarePlan` | `RateLimitMiddleware` |

## 5. 注意事项

- 应用层"禁止依赖 domain"并不成立——application 可以用 domain（如 `AuthErrorCode`）；被禁的方向是 domain→application。
- `SharedResourceMount` 同时实现多个端口，用例侧仍应以窄端口类型注解（`runtime_port: AuthRuntimePort`），避免用例悄悄用上端口外能力。
- 新增 ports 时给每个方法写清语义化 docstring；`SharedResourceMount` 侧的实现分散在 `resource_mount/` 各门面 Mixin 中，找实现时从 `shared_resource_mount.py` 的 MRO 顺序入手：`SharedResourceAccessor` → `AdminIdentityResourceFacade` → `AdminSecurityResourceFacade` → `TaskResourceFacade` → `LoggingResourceFacade`。

## 6. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_application_port_boundary_unit.py` | 应用端口边界。 |
| contract | `test/contract_test/test_http_contract.py` | 核心 HTTP 契约。 |
| boundary | `test/boundary_test/test_hard_migration_module_boundary.py` | 模块与运行时边界。 |
| class_inheritance | `test/class_inheritance_test/test_runtime_contract_inheritance.py` | 运行时契约继承关系。 |
| static | `uv run nox -s static`（import-linter） | 四条分层依赖契约。 |

## 7. 相关文档

- [项目文档总览](../README.md)
- [架构总览](architecture_overview.md)
- [依赖方向](dependency_direction.md)
- [应用端口](../03_application_domain/application_ports.md)
- [评审清单](../09_development_guide/review_checklist.md)
