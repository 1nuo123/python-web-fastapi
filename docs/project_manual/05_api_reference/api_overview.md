# API 总览

## 1. 这是什么

全部 Web API 的导航与横切约定：模块清单、启用状态、权限矩阵、统一响应/错误/分页约定。单个 API 的细节在各专题文档。

**最后更新范围**：覆盖 9 个 `src/api/endpoint_*` 模块、31 条路由与集中授权要求。

## 2. 模块与路由总表

| 模块 | 边界 | 路由 | 权限（角色 admin + scope） |
| --- | --- | --- | --- |
| health_probe | public | GET /health/live、GET /health/ready | 无需认证 |
| auth_access | public | POST /auth/token、POST /auth/refresh、POST /auth/revoke、GET /auth/me | 前三个匿名；/auth/me 需登录 |
| admin_identity | business_admin | /admin/scopes*（5）、/admin/roles* + /admin/business-roles（7）、/admin/users*（8） | auth:read（读）/ auth:scope_manage / auth:role_manage / auth:user_manage / auth:password_reset / auth:grant_admin（角色scope替换、用户角色替换） |
| admin_audit | business_admin | GET /admin/audit-events | auth:read |
| system_overview | ops_only | GET /system/info | system:read |
| security_protection | ops_only | GET/POST /security/ip-blocks、GET /security/ip-blocks/{record_id}、POST /security/ip-blocks/release | security:manage |
| admin_task | ops_only | GET /admin/tasks/executions、GET /admin/tasks/executions/{task_id}、GET /admin/tasks/runtime、GET /admin/tasks/registrations、POST /admin/tasks/dispatch | system:read（读）/ task:dispatch（派发） |
| admin_settings | ops_only | GET /admin/settings/reload/candidate、POST /admin/settings/reload | system:read |
| admin_log | ops_only | GET /admin/logs、GET /admin/security-events | system:read |

启用状态：`config/app_base.toml` 默认启用 health_probe、auth_access、admin_identity、admin_audit；ops_only 五模块需显式加入 `app.modules.enabled`。文档中的路径为模块自身路径，实际访问需加 `runtime.web.api_prefix`（默认空）。

## 3. 横切约定

- **响应**：一律 `ResponseEnvelope{header{code,message,request_id,trace_id},data}`；成功 `code=system.success.ok`。见[响应信封](../02_backend/response_envelope.md)。
- **错误**：401 `auth.token.*`（未认证/令牌问题）、403 `auth.authorization.permission_denied`（权限不足）、422 `system.request.invalid`（校验失败）、413 载荷超限、429 限流/节流、503 未就绪/容量耗尽、504 执行超时、500 未预期。错误码目录见[异常处理](../02_backend/exception_handling.md)。
- **认证**：`Authorization: Bearer <access_token>`；后台接口守卫链 = 认证中间件绑定主体 → 路由 `Security(HTTPBearer(auto_error=False))` + `read_authorized_principal(requirement)`。
- **分页**：查询参数 `page_size`（默认 50、上限 200，任务/日志/scope 列表用 `limit`，默认 50 上限 200）+ `offset`（≥0）；响应含 total/next_cursor（分页信封）。
- **响应头**：`X-Request-ID`（恒有）、`X-Trace-ID`（有 trace 时）、`X-Elapsed-Ms`；限流拒绝带 `Retry-After`。
- **OpenAPI**：`enable_openapi=true` 时 `/docs`、`/redoc`、`/openapi.json` 可用（生产默认关闭）；`/metrics` 不进 OpenAPI。

## 4. 专题文档

[鉴权](auth_api.md) · [健康探针](health_api.md) · [系统概览](system_overview_api.md) · [管理员身份](admin_identity_api.md) · [管理员审计](admin_audit_api.md) · [管理员任务](admin_task_api.md) · [管理员配置](admin_settings_api.md) · [管理员日志](admin_log_api.md) · [安全防护](security_protection_api.md)

## 5. 注意事项

- 新增 API：manifest/枚举/路由/契约/权限五处齐动，见[新增 API](../09_development_guide/adding_new_api.md)；对外契约变更需同步 `public_contract_snapshot_builder` 基线。
- 接口未出现在 OpenAPI 时依次检查：模块是否在 enabled 列表、环境是否关闭 OpenAPI、api_prefix 是否遗漏。

## 6. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_web_module_manifest_unit.py` | 模块清单与边界。 |
| interface | `test/interface_test/*` | 各模块 HTTP 表面。 |
| integration | `test/integration_test/test_app_integration.py` | 启用模块集成。 |

## 7. 相关文档

- [项目文档总览](../README.md)
- [API 模块注册](../02_backend/api_module_registration.md)
- [管理后台能力](../03_application_domain/admin_business_capabilities.md)
