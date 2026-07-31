# 管理员身份 API

## 1. 范围与源码

`admin_identity` 是默认启用的 `business_admin` 模块，提供 scope、role、业务角色目录和用户管理，共 20 条 route。

| 源码 | 职责 |
| --- | --- |
| `src/api/endpoint_admin_identity/route_admin_identity.py` | 汇总 scope/role/user 三个 router catalog。 |
| `route_admin_identity_common.py` | 路径、权限 dependency、信封构造、高危确认和成功审计。 |
| `route_admin_scope.py`、`route_admin_role.py`、`route_admin_user.py` | 分域 route 与 API/application 映射。 |
| `contract_admin_identity_*.py` | 请求/响应 discriminator union。 |
| `src/application/admin/identity` | 19 个身份用例（含初始管理员）。 |
| `src/application/ports/admin_identity_port.py` | query/page/snapshot 与完整端口。 |

## 2. 通用认证、信封和分页

所有 route 要求 Bearer 和 `admin` 角色，再按操作检查 scope。外层响应统一为 `ResponseEnvelope[AdminIdentityEnvelope]`；写请求 body 本身是 `AdminIdentityEnvelope`：

```text
request:  { header: {kind, schema_version, operation_name}, detail: {...} }
response: { code, message, request_id, data: {header, detail}, ... }
```

内层 header/detail 都 `extra="forbid"`，`kind/schema_version` 必须一致，`operation_name` 必须允许当前 detail kind。版本固定 `1.0`。

分页不是统一形状：

- scope list：`keyword?`、`enabled?`、`limit=50`（1..200）；response 只有 `scopes[]`。
- role/business-role/user list：`page_size=50`（1..200）、`offset=0`（>=0），response 有 `page_size/offset/total`。
- role list 支持 `keyword`；user list 支持 `keyword/role_key/is_active`。

## 3. Scope 端点

| 方法 | 路径 | 权限 | 请求 detail | 响应 detail |
| --- | --- | --- | --- | --- |
| GET | `/admin/scopes` | `auth:read` | 无 | `admin_scope_list` |
| GET | `/admin/scopes/{scope_code}` | `auth:read` | 无 | `admin_scope` |
| POST | `/admin/scopes` | `auth:scope_manage` | `admin_scope_create` | `admin_scope` |
| PATCH | `/admin/scopes/{scope_code}` | `auth:scope_manage` | `admin_scope_update` | `admin_scope` |
| DELETE | `/admin/scopes/{scope_code}` | `auth:scope_manage` | 无 body | `admin_scope_delete_result` |

### 3.1 请求字段

- create：`scope_code` 必填 1..128、`scope_name` 必填非空、`description` 可空、`enabled` 默认 true。`scope_kind` 由服务端判定，客户端提交会因额外字段被拒绝。
- update：`scope_name?`、`description?`、`enabled?`；目标 code 只来自 path。未提交字段保持不变，`description=null` 的实际更新语义由仓储实现处理。
- response item：`scope_code/scope_name/description/scope_kind(builtin|custom)/enabled`。

### 3.2 业务约束

- 内置或重复 code 创建返回 conflict。
- 受保护后台 scope 不可禁用；内置 scope 不可删除；任何被 role 绑定的 scope 不可删除。
- 内置 scope 的名称/description 可以更新。
- `actor_subject_id` 由当前 principal 注入 update command，用于操作者自锁保护，不由 body 提供。

## 4. Role 端点

| 方法 | 路径 | 权限 | 请求 detail | 响应 detail |
| --- | --- | --- | --- | --- |
| GET | `/admin/roles` | `auth:read` | 无 | `admin_role_list` |
| GET | `/admin/business-roles` | `auth:read` | 无 | `admin_business_role_list` |
| GET | `/admin/roles/{role_key}` | `auth:read` | 无 | `admin_role` |
| POST | `/admin/roles` | `auth:role_manage`；条件追加 `auth:grant_admin` | `admin_role_create` | `admin_role` |
| PATCH | `/admin/roles/{role_key}` | `auth:role_manage` | `admin_role_update` | `admin_role` |
| PUT | `/admin/roles/{role_key}/scopes` | `auth:grant_admin` | `admin_role_scope_replace` | `admin_role` |
| DELETE | `/admin/roles/{role_key}` | `auth:role_manage` | 无 body | `admin_role_delete_result` |

### 4.1 请求与响应字段

- create：`role_key` 1..64、`role_name` 非空、`scope_codes[]` 默认空、`confirmation?` 最长 64。
- update：只有 `role_name`；role key 不可重命名。
- replace scopes：`scope_codes[]` 全量新集合；`confirmation` 必填。
- 完整 role response：`role_key/role_name/scope_codes/user_count`。
- business role response 刻意只暴露 `role_key/role_name`，不暴露 scope_codes；当前枚举仅 `customer_service`、`business_operator`。

### 4.2 高危创建和替换

创建普通自定义 scope 角色只要求 `auth:role_manage`。若 `scope_codes` 任一值命中 `PROTECTED_ADMIN_SCOPE_CODES`，route 必须：

1. 验证 `confirmation == "confirm-admin-grant"`；
2. 再校验当前 principal 具备 `auth:grant_admin`；
3. 将 `grant_confirmed=True` 传入仓储，仓储再次保护。

替换 role scopes 无条件要求 `auth:grant_admin` 和确认短语。所有 scope 必须存在且启用；内置 `admin` role 不可删除，绑定用户的 role 不可删除；操作者使用目标 role 时，替换后不能移除自己的最后一个 `admin + auth:manage` 能力。

## 5. User 端点

| 方法 | 路径 | 权限 | 请求 detail | 响应 detail |
| --- | --- | --- | --- | --- |
| GET | `/admin/users` | `auth:read` | 无 | `admin_user_list` |
| GET | `/admin/users/{subject_id}` | `auth:read` | 无 | `admin_user` |
| POST | `/admin/users` | `auth:user_manage` | `admin_user_create` | `admin_user` |
| PATCH | `/admin/users/{subject_id}` | `auth:user_manage` | `admin_user_update` | `admin_user` |
| POST | `/admin/users/{subject_id}/password` | `auth:password_reset` | `admin_user_password_reset` | `admin_user` |
| POST | `/admin/users/{subject_id}/disable` | `auth:user_manage` | `admin_user_disable` | `admin_user_status_result` |
| POST | `/admin/users/{subject_id}/enable` | `auth:user_manage` | `admin_user_enable` | `admin_user_status_result` |
| POST | `/admin/users/{subject_id}/roles` | `auth:grant_admin` | `admin_user_role_replace` | `admin_user` |

当前没有注册 `DELETE /admin/users/{subject_id}`。契约枚举仍保留 `user_delete/admin_user_delete_result` 兼容形状，但默认 OpenAPI 和 route surface 只有显式 `/disable`。

### 5.1 请求字段

- create：`username` 1..128、`password` 最短 1（`SecretStr`）、`role_keys[]` 默认空、`subject_id?` 最长 128。subject id 省略时生成 `user-<uuid>`。
- update：只有 `username?`；body 中 `is_active` 是未知字段并返回 422。
- password reset：只有 `password`（最短 1）。
- disable：`reason` **必填**、非空、最长 256。
- enable：`reason?`、最长 256，仅进入 status response，不恢复旧 token session。
- replace roles：`role_keys[]` 全量替换，`confirmation="confirm-admin-grant"`。

密码字段不会出现在响应。`admin_user` 只暴露 `subject_id/username/is_active/role_keys`；端口 snapshot 虽计算 effective scope_codes，HTTP user payload 当前不暴露它。

### 5.2 角色分配边界

用户 create/replace roles 只接受 `BusinessAdminRoleKey` 白名单，即 `customer_service`、`business_operator`。不能通过这些 API 分配 `admin`、自定义技术角色或任意新建 role；技术管理员由初始管理员 CLI 建立。

因此 `/admin/users/{id}/roles` 的 `auth:grant_admin` 名称表示高危角色关联变更保护，不代表当前 HTTP API 能授予 `admin` 技术角色。

### 5.3 自锁、密码和 session

- 禁止操作者停用自己；任何停用/角色替换还必须保证至少一个 active `admin + auth:manage` 用户。
- 禁止管理员重置自己的密码；管理者不能重置同级 `admin + auth:manage` 用户；不具 `auth:grant_admin` 的低权限操作者不能重置 admin 或拥有 grant scope 的目标。
- 密码重置、roles 替换、disable 均在身份写事务内吊销目标的 active refresh sessions。旧 refresh 随即 401；enable 后需重新登录。
- username/subject 唯一冲突为 409；role 不存在或不属于业务白名单为 422。

## 6. 操作名与审计

每个成功写 route 在用例返回后发射 `admin_identity_changed`：

| HTTP 操作 | 审计 operation |
| --- | --- |
| scope create/update/delete | `scope_create/scope_update/scope_delete` |
| role create/update/replace scopes/delete | `role_create/role_update/role_scope_replace/role_delete` |
| user create/update/reset/replace roles/disable/enable | `user_create/user_update/user_password_reset/user_role_replace/user_disable/user_enable` |

失败写入不发该成功事件。事件 actor 永远取当前 principal，target id 取 path 或创建结果，不信任 body 中伪造 actor。

## 7. 删除/状态响应

- scope/role delete：`AdminIdentityDeleteResultPayload {kind,target_id,deleted,reason}`。
- user disable/enable：`AdminUserStatusResultPayload {kind,subject_id,status,is_active,reason}`，`status` 为 `disabled|enabled`。
- 所有成功 route 当前返回 HTTP 200，不用 201/204。

## 8. 错误码

| HTTP | 错误码 | 典型触发 |
| --- | --- | --- |
| 401 | `auth.token.invalid` | Bearer 缺失/无效。 |
| 403 | `auth.access.account_disabled` | 当前主体停用。 |
| 403 | `auth.authorization.permission_denied` | 缺 admin 或 route scope；含受保护 scope 的 role create 缺 grant scope。 |
| 404 | `auth.admin_identity.not_found` | scope/role/user 或必要 actor 不存在。 |
| 409 | `auth.admin_identity.conflict` | 重复键；内置/被绑定对象删除；受保护 scope 禁用。 |
| 422 | `auth.admin_identity.invalid` | 缺失/禁用 scope，非业务 role 分配，高权限密码重置越权，仓储高危确认失败。 |
| 409 | `auth.admin_identity.self_lock_blocked` | 停用自己、移除自身最后管理能力、破坏系统管理员存活不变量。 |
| 422 | `system.request.invalid` | Pydantic 信封/字段错误、detail 类型不匹配、确认短语错误。 |

## 9. 事实核验测试

| 测试组 | 覆盖事实 |
| --- | --- |
| `test/interface_test/admin_identity/test_admin_scope_interface.py` | scope route、protected scope、actor 传递。 |
| `test/interface_test/admin_identity/test_admin_role_interface.py` | role CRUD、business list、OpenAPI、高危确认。 |
| `test/interface_test/admin_identity/test_admin_user_interface.py` | user route、请求字段、权限和状态响应。 |
| `test/interface_test/admin_identity/test_admin_identity_business_boundary_interface.py` | 20-route surface、无 legacy DELETE、业务角色边界。 |
| `test/contract_test/admin_identity/test_admin_identity_contract.py` | discriminator、分页、密码不回显、未知字段。 |
| `test/integration_test/admin_identity/` | 真实仓储不变量、角色/scope 引用、session 吊销。 |

## 10. 相关文档

- [管理后台能力](../03_application_domain/admin_business_capabilities.md)
- [领域模型与常量](../03_application_domain/domain_model_and_constants.md)
- [管理员审计 API](admin_audit_api.md)
- [API 总览](api_overview.md)
