# 领域模型与常量

## 1. 文档范围

`src/domain` 当前只有 `auth` 领域，承载不依赖 FastAPI、数据库或消息系统的认证授权事实：角色、scope、稳定错误码、JWT 策略值对象、后台 route 授权要求和纯授权求值器。

领域层可以依赖 `src/core` 的通用契约；不能依赖 application/api/infrastructure。HTTP 状态码不定义在领域枚举中，而由 application 或 adapter 抛错位置决定。

## 2. 文件清单

| 文件 | 领域事实 |
| --- | --- |
| `auth_role_key.py` | `AuthRoleKey.ADMIN = "admin"`。 |
| `auth_scope_code.py` | 10 个内置 scope。 |
| `auth_error_code.py` | 8 个认证/令牌/授权稳定错误码。 |
| `admin_identity_error_code.py` | 身份管理 4 个稳定错误码。 |
| `access_token_policy.py` | JWT 签名、有效期、issuer/audience、refresh rotation 配置值对象。 |
| `authorization_policy_evaluator.py` | 无 IO 的角色/scope 全包含求值器。 |
| `admin_route_authorization_policy.py` | 14 个后台 route requirement、边界分组和受保护 scope 派生表。 |

## 3. 角色、scope 与业务角色

唯一内置技术角色是 `admin`。内置 scope 共 10 个：

| scope | 用途 |
| --- | --- |
| `auth:read` | 身份与业务审计读取。 |
| `auth:manage` | 管理能力不变量；当前没有 route 直接以它作为写接口 requirement。 |
| `auth:user_manage` | 用户创建、更新、启停。 |
| `auth:role_manage` | 角色创建、更新、删除。 |
| `auth:scope_manage` | scope 创建、更新、删除。 |
| `auth:password_reset` | 用户密码重置。 |
| `auth:grant_admin` | role scope/user role 替换，以及含受保护 scope 的角色创建。 |
| `security:manage` | 安全 IP 封禁管理。 |
| `system:read` | 任务/配置/日志/系统信息运维读取。 |
| `task:dispatch` | 管理端任务派发。 |

`BusinessAdminRoleKey` 不在 domain，而在 application port 中定义，当前只有 `customer_service`、`business_operator`。身份用户 API 只允许分配这两个预定义业务角色；`admin` 技术角色不能通过用户创建/角色替换 API 授予，首个技术管理员由初始化 CLI 创建。

## 4. 后台授权 requirement

每个 `RouteAuthorizationRequirement` 包含稳定的 `requirement_name`、`required_roles` 和 `required_scopes`；以下 14 项全部要求 `admin` 角色。

| 边界 | requirement name | scope | 主要 route |
| --- | --- | --- | --- |
| business_admin | `admin_identity_read` | `auth:read` | identity GET |
| business_admin | `admin_identity_manage` | `auth:manage` | 当前集中事实源保留，未直接绑定 identity route |
| business_admin | `admin_identity_user_manage` | `auth:user_manage` | 用户创建/更新/启停 |
| business_admin | `admin_identity_role_manage` | `auth:role_manage` | 角色创建/更新/删除 |
| business_admin | `admin_identity_scope_manage` | `auth:scope_manage` | scope 写操作 |
| business_admin | `admin_identity_password_reset` | `auth:password_reset` | 密码重置 |
| business_admin | `admin_identity_grant_admin` | `auth:grant_admin` | 高危角色/scope 关联变更 |
| business_admin | `admin_audit_read` | `auth:read` | 审计列表 |
| ops_only | `admin_task_query` | `system:read` | 任务查询 |
| ops_only | `admin_task_dispatch` | `task:dispatch` | 任务派发 |
| ops_only | `admin_settings_reload` | `system:read` | reload candidate/apply |
| ops_only | `admin_log_query` | `system:read` | 日志与安全事件查询 |
| ops_only | `system_info_read` | `system:read` | 系统概览 |
| ops_only | `security_protection_admin` | `security:manage` | IP 封禁管理 |

`BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS` 和 `OPS_ONLY_AUTHORIZATION_REQUIREMENTS` 被 Web module manifest 用于边界一致性校验。

## 5. 受保护 scope

`ProtectedAdminScopeRegistry.from_requirements()` 收集 14 个 requirement 的全部 required scopes，形成 import 时固化的 `PROTECTED_ADMIN_SCOPE_CODES`。当前集合是上述 10 个内置 scope。

仓储用它实现两层保护：

- 受保护 scope 不能被禁用或删除；内置 scope 的名称和说明仍可修改。
- 创建包含受保护 scope 的角色，必须由 route 完成 `auth:grant_admin` 校验和 `confirm-admin-grant` 二次确认，并把 `grant_confirmed=True` 传入仓储。

此外还有动态不变量：系统必须保留至少一个 active 且具备 `admin + auth:manage` 的用户；涉及用户停用、用户角色替换和角色 scope 替换时会在事务内加锁并复核。

## 6. 授权求值

`AuthorizationPolicyEvaluator.evaluate(principal, policy)` 是纯函数：

1. 先计算缺失 scopes；有缺失即 `allowed=False` 并给出“缺少权限范围”原因。
2. scopes 全部满足后再计算缺失 roles；有缺失返回“缺少角色”。
3. 两组要求都满足才 `allowed=True`。

集合语义是“全部包含”，不是任一匹配；空 required 集合自然通过。`AuthorizationGuard` 再把拒绝 decision 转为 `403 auth.authorization.permission_denied`。

## 7. 错误码

### 7.1 `AuthErrorCode`

| 错误码 | 常见 HTTP | 当前语义 |
| --- | --- | --- |
| `auth.access.invalid_credentials` | 401 | 用户不存在、停用或密码错误的登录统一外观。 |
| `auth.access.account_disabled` | 403 | refresh 或 access token 对应主体已停用。 |
| `auth.token.invalid` | 401 | 格式、签名、用途、数据库会话或主体/session 对应关系无效。 |
| `auth.token.expired` | 401 | token 超时。 |
| `auth.token.revoked` | 401 | refresh session 已吊销。 |
| `auth.token.reused` | 401 | 已轮换 refresh token 被重放。 |
| `auth.authorization.permission_denied` | 403 | 已认证但 role/scope 不满足。 |
| `auth.request.throttled` | 429 | 登录或刷新失败节流命中。 |

### 7.2 `AdminIdentityErrorCode`

| 错误码 | HTTP | 当前语义 |
| --- | --- | --- |
| `auth.admin_identity.not_found` | 404 | scope/role/user/操作者不存在。 |
| `auth.admin_identity.conflict` | 409 | 唯一键冲突、内置或被引用对象不可删除等状态冲突。 |
| `auth.admin_identity.invalid` | 422 | scope/role 不存在或禁用、非业务角色分配、密码重置越权等业务输入无效。 |
| `auth.admin_identity.self_lock_blocked` | 409 | 操作者自锁或破坏“至少一个可管理 admin”不变量。 |

## 8. `AccessTokenPolicy`

字段包括 `jwt_secret`、`jwt_algorithm`、access/refresh 有效期秒数、`issuer`、`audience`、`refresh_token_rotation_enabled`。它是配置到 `JwtTokenService` 的领域值对象，不持有 IO，也不执行轮换事务；数据库 refresh session 的轮换/重放处理由 application usecase 完成。

## 9. 修改规则

1. 新后台能力优先复用现有 requirement；权限语义不同才新增 requirement/scope。
2. 新 requirement 会自动把 required scope 加入受保护集合；部署前必须保证存量 admin 已拥有新 scope。
3. 新内置 scope 还要同步持久化 scope catalog/初始化迁移；只加 enum 不等于现有数据库已有记录。
4. 错误码是外部稳定契约，改名需同步 API 文档、客户端和回归测试。
5. domain 保持无 IO；流程、事务和 HTTP 适配不要下沉到领域层。

## 10. 事实核验测试

| 测试 | 覆盖事实 |
| --- | --- |
| `test/unit_test/test_core_unit.py` | 授权求值器的基础决策。 |
| `test/unit_test/test_auth_persistence_unit.py` | 授权 policy 与认证持久化协作。 |
| `test/unit_test/test_web_module_manifest_unit.py` | business_admin/ops_only 模块与 requirement 事实源一致。 |
| `test/contract_test/admin_identity/test_admin_identity_contract.py` | 受保护 scope 注册表和身份错误边界。 |
| `test/integration_test/admin_identity/test_admin_*_usecase_integration.py` | 自锁、存活不变量、技术/业务角色和 scope 引用保护。 |

## 11. 相关文档

- [应用端口](application_ports.md)
- [管理后台能力](admin_business_capabilities.md)
- [鉴权与授权](../04_infrastructure/authentication_and_authorization.md)
- [鉴权 API](../05_api_reference/auth_api.md)
