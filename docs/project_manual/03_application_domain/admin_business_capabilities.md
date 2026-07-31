# 管理后台能力

## 1. 文档范围

本文从业务动作、权限、事务、审计和模块启停五个角度汇总当前管理后台。后台共 7 个 API 模块：2 个业务后台模块和 5 个运维控制面模块；`auth_access` 是它们共同依赖的公开认证入口，不计入后台模块。

## 2. 模块边界与默认启用

| `AdminBoundaryPolicy` | 模块 | 默认 `config/app_base.toml` | 用途 |
| --- | --- | --- | --- |
| `business_admin` | `admin_identity`、`admin_audit` | 启用 | 业务账号/角色/scope 管理与审计查询。 |
| `ops_only` | `admin_task`、`admin_settings`、`admin_log`、`security_protection`、`system_overview` | 未启用 | 任务、热更新、日志、安全封禁、系统资源信息。 |

manifest 条目的 `enabled` 默认值不等于实际挂载；实际路由由 `app.modules.enabled` 选择。未启用模块表现为路由不存在（404），不是 401/403。模块启停属于 restart-required 配置。

## 3. 能力与权限矩阵

所有后台 route 都要求有效 Bearer、`admin` 角色以及表中 scope。

| 模块/能力 | 操作 | scope |
| --- | --- | --- |
| identity scope | list/get | `auth:read` |
| identity scope | create/update/delete | `auth:scope_manage` |
| identity role | list/business-list/get | `auth:read` |
| identity role | create/update/delete | `auth:role_manage`；创建含受保护 scope 的角色还要 `auth:grant_admin` + 确认短语 |
| identity role | replace scopes | `auth:grant_admin` + `confirm-admin-grant` |
| identity user | list/get | `auth:read` |
| identity user | create/update/enable/disable | `auth:user_manage` |
| identity user | reset password | `auth:password_reset`，另有目标级越权保护 |
| identity user | replace roles | `auth:grant_admin` + `confirm-admin-grant` |
| audit | list events | `auth:read` |
| task | executions/runtime/registrations | `system:read` |
| task | dispatch | `task:dispatch` |
| settings | candidate/apply | `system:read` |
| log | logs/security-events | `system:read` |
| security protection | IP block list/get/create/release | `security:manage` |
| system overview | read | `system:read` |

## 4. 身份管理

### 4.1 scope

- 列表支持 `keyword/enabled/limit`，返回完整 scope 项，不提供 offset/total。
- 内置 scope 与任何已绑定角色的 scope 不可删除。
- `PROTECTED_ADMIN_SCOPE_CODES` 中的 scope 不可禁用；名称和 description 可以修改。
- 自定义且未绑定的 scope 可禁用/删除。

### 4.2 role

- 完整角色列表暴露 `scope_codes` 和 `user_count`；业务角色列表只暴露 `role_key/role_name`，当前白名单为 `customer_service`、`business_operator`。
- 角色创建校验所有 scope 存在且启用。包含受保护后台 scope 时，route 追加 `auth:grant_admin` 与确认短语校验，仓储再检查 `grant_confirmed`。
- 角色 scope 替换是全量替换，不是增量 patch；若目标角色属于操作者，替换后必须仍保留操作者的 `admin + auth:manage` 能力。
- 内置 `admin` 角色、仍绑定用户的角色不可删除。

### 4.3 user

- 用户 API 只允许分配预定义业务角色，不能分配 `admin` 或任意技术角色。首个技术管理员必须走 `create_initial_admin` CLI；文档和客户端不得把 `/admin/users/{id}/roles` 当作“授予 admin”的入口。
- `PATCH /admin/users/{subject_id}` 只更新 username；启停必须走显式 enable/disable endpoint。
- 停用是软状态变更，禁止停用自己，并保证系统至少还有一个 active `admin + auth:manage` 用户。
- 密码重置禁止重置自己；具备 `admin + auth:manage` 的操作者不能重置同级管理者；低权限操作者不能重置 admin 或拥有 `auth:grant_admin` 的高权限目标。
- 密码重置、用户角色替换、用户停用都会在同一 UoW 内吊销目标主体的 active refresh sessions；启用不会恢复已吊销 session，用户需重新登录。

### 4.4 初始管理员

`CreateInitialAdminUsecase` 要求 `create-initial-admin` 确认短语。仓储锁定用户表（SQLite 跳过显式表锁），仅当不存在任何 admin 用户时创建，并确保 admin role 绑定全部 10 个内置 scope。重复执行返回结构化 `created/reason`，不创建第二个技术管理员。

## 5. 审计查询

`GET /admin/audit-events` 读取数据库结构化安全日志中的 `admin_identity_changed` 事件，并只接受 operation 白名单。身份 route 在写用例成功后发射；settings route 仅在 reload result `success=True` 后发射。事件为 audit-critical，绕过常规缓冲同步落库。

| `AdminAuditAction` | 真实 operation name |
| --- | --- |
| `user_created` | `user_create` |
| `user_updated` | `user_update` |
| `user_disabled` | `user_delete`、`user_disable` |
| `user_enabled` | `user_enable` |
| `password_reset` | `user_password_reset` |
| `role_assigned` | `user_role_replace` |
| `scope_changed` | `scope_create`、`scope_update`、`scope_delete` |
| `role_created/updated/deleted` | `role_create/role_update/role_delete` |
| `role_roles_replaced` | `role_scope_replace`（枚举名保留当前兼容拼写） |
| `settings_reloaded` | `settings_reload` |

当前查询生成的 `result` 固定为 `success`；失败的身份写入不会生成该审计事件，授权拒绝等其他 security event 也不会混入业务审计列表。

## 6. 运维控制面

### 6.1 任务

- 执行记录列表按 `status/job_kind` 过滤，`limit` 1..200；详情按 `task_id`。
- runtime 同时展示运行模式、task backend、配置 transport backend、实际 message bus backend、worker/inline 标志及默认 job/retry。
- registrations 展示所有注册及其是否对当前 backend 生效、是否绑定 handler/payload model。
- 派发先按当前 backend 的启用注册和绑定 model 校验 `payload_json`，再进入通用 dispatch；去重命中可返回 `reused_existing_record=True`。

### 6.2 配置热更新

- candidate API 只暴露 `candidate_version` 与 `digest`，不暴露完整 diff 或配置值。
- apply 请求 detail 没有业务字段；coordinator 负责允许/重启字段判断、应用和回滚。
- apply route 即使得到 `success=False` 的拒绝/回滚结果，也以 HTTP 200 返回结构化 `success/rolled_back/reason/restored_resources`；调用方必须检查 detail，而不能只看 HTTP 状态。
- 只有 `success=True` 才生成 `settings_reloaded` 业务审计；`config_security_rejected` 属安全日志，不等同于成功审计。

### 6.3 日志与安全事件

- `/admin/logs` 按 level/kind/request/trace/time 过滤；`/admin/security-events` 按 event type/severity/decision/time 过滤；两者均只有 `limit`，无 total/cursor。
- 查询结果执行输出侧脱敏。历史 schema/version 或 detail 无法解析时返回 `admin_unparsed_log_detail` 摘要，而不是让整页失败。

### 6.4 安全 IP 封禁与系统概览

- IP 封禁提供 list/get/create/release；释放保留记录与原因，不做物理删除。
- 系统概览读取应用版本、环境、模块、ready 和 runtime resources，不提供写操作。

## 7. 通用响应、分页与错误

- API 均使用外层 `ResponseEnvelope`；后台 identity/audit/task/settings/log 在 `data` 内再使用各自 header/detail 强类型信封。
- 不存在统一后台分页：role/user/audit 是 `page_size+offset+total`；scope/task/log 是 limit-only。
- 未认证通常 `401 auth.token.invalid`；缺 role/scope 为 `403 auth.authorization.permission_denied`；身份业务失败使用 `auth.admin_identity.*`；资源未就绪通常为 `503 system.resource.not_ready`。
- 所有后台 contract `extra="forbid"`，未知请求字段或 header/detail 不一致返回 `422 system.request.invalid`。

## 8. 事实核验测试

| 测试组 | 重点 |
| --- | --- |
| `test/interface_test/admin_identity/` | 20 个 identity route、权限、请求信封和显式启停。 |
| `test/integration_test/admin_identity/` | 真实仓储 CRUD、自锁、不变量、business-role 与 refresh session 吊销。 |
| `test/interface_test/admin_audit/test_admin_audit_interface.py` | 审计过滤、分页、白名单和脱敏。 |
| `test/interface_test/test_admin_task_interface.py` | task 模块启停、权限、查询与派发错误。 |
| `test/interface_test/test_admin_settings_interface.py` | reload 权限、请求契约与结果。 |
| `test/interface_test/test_admin_log_interface.py` | 日志过滤、脱敏、limit 和模块启停。 |
| `test/unit_test/test_web_module_manifest_unit.py` | business_admin/ops_only 边界一致性。 |

## 9. 相关文档

- [领域模型与常量](domain_model_and_constants.md)
- [应用用例](application_usecases.md)
- [管理员身份 API](../05_api_reference/admin_identity_api.md)
- [管理员审计 API](../05_api_reference/admin_audit_api.md)
- [管理员任务 API](../05_api_reference/admin_task_api.md)
