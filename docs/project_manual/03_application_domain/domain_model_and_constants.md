# 领域模型与常量

## 1. 文档目的
说明当前领域层可确认的角色、scope、错误码和访问令牌策略，并标出后台应用端口中的业务常量边界。

**最后更新范围**：覆盖 `src/domain/auth`、相关 core auth contract、`src/domain/auth/admin_route_authorization_policy.py` 和后台身份/审计应用端口常量。

## 2. 适用读者
- 新人开发者
- 后端开发者
- 测试维护者
- 安全审查人员

## 3. 关联源码
| 路径 | 作用 |
| --- | --- |
| `src/domain/auth/auth_role_key.py` | 角色键。 |
| `src/domain/auth/auth_scope_code.py` | 授权 scope。 |
| `src/domain/auth/auth_error_code.py` | 认证和授权错误码。 |
| `src/domain/auth/admin_identity_error_code.py` | 管理员身份错误码。 |
| `src/domain/auth/access_token_policy.py` | 访问令牌策略对象。 |
| `src/domain/auth/admin_route_authorization_policy.py` | 后台受保护 scope 与授权要求。 |
| `src/application/ports/admin_identity_port.py` | 后台身份业务角色和 scope 类型常量。 |
| `src/application/ports/admin_audit_query_port.py` | 业务审计动作和结果常量。 |

## 4. 核心结论
- 领域角色枚举只有 `AuthRoleKey.ADMIN = "admin"`；业务后台预定义角色不在领域枚举中，而在 `BusinessAdminRoleKey` 中定义为 `customer_service`、`business_operator`。
- 当前后台受保护 scope 由 `PROTECTED_ADMIN_SCOPE_CODES` 从集中授权要求派生，包括 `auth:read`、`auth:manage`、`auth:user_manage`、`auth:role_manage`、`auth:scope_manage`、`auth:password_reset`、`auth:grant_admin`、`security:manage`、`system:read`、`task:dispatch`。
- 受保护 scope 不仅用于 role scope 替换，也用于 role create 的高危授权 gating；创建包含受保护后台 scope 的角色必须具备 `auth:grant_admin` 并提交确认短语。
- 密码重置的高权限目标包括绑定 `admin` 角色的用户，或通过角色具备 `auth:grant_admin` 能力的用户；仅具备 `auth:password_reset` 的低权限管理员不能重置这类目标。
- 认证错误码为 `auth.access.invalid_credentials`、`auth.access.account_disabled`、`auth.token.invalid`、`auth.token.expired`、`auth.token.revoked`、`auth.token.reused`、`auth.authorization.permission_denied`、`auth.request.throttled`。
- 管理员身份错误码为 `auth.admin_identity.not_found`、`auth.admin_identity.conflict`、`auth.admin_identity.invalid`、`auth.admin_identity.self_lock_blocked`。
- 业务审计动作常量定义在应用端口层，当前包括 `user_created`、`user_updated`、`user_disabled`、`user_enabled`、`password_reset`、`role_assigned`，结果枚举为 `success`、`failed`。

## 5. 结构说明
领域常量集中在 `src/domain/auth`，核心认证数据结构在 `src/core/auth_contract`；后台业务角色、scope 类型和审计动作属于应用端口层常量，不应回写进 `AuthRoleKey` 或 `AuthScopeCode`。

## 6. 工作流程
非流程类文档：本文件作为领域常量索引。

## 7. 关键实现
| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `AuthRoleKey` | `src/domain/auth/auth_role_key.py` | 角色键枚举。 |
| `AuthScopeCode` | `src/domain/auth/auth_scope_code.py` | scope 枚举。 |
| `AuthErrorCode` | `src/domain/auth/auth_error_code.py` | 认证错误码。 |
| `AdminIdentityErrorCode` | `src/domain/auth/admin_identity_error_code.py` | 管理员身份错误码。 |
| `BusinessAdminRoleKey` | `src/application/ports/admin_identity_port.py` | 业务后台预定义角色键。 |
| `AdminAuditAction` | `src/application/ports/admin_audit_query_port.py` | 业务审计查询动作枚举。 |

## 8. 如何修改或扩展
1. 新增真正的后台受保护 scope 先改 `AuthScopeCode`。
2. 更新 `admin_route_authorization.py` 的权限要求，并确认 `PROTECTED_ADMIN_SCOPE_CODES` 派生结果。
3. 更新后台身份仓储中 role create、role scope replace、password reset 的高危边界测试，确保新增 scope 不会绕过确认短语或高权限目标保护。
4. 新增业务后台预定义角色优先改 `BusinessAdminRoleKey` 和 bootstrap 同步逻辑，不要混入 `AuthRoleKey`。
5. 新增业务审计动作时同步 `AdminAuditAction` 与 `SharedResourceMount` 中的操作名白名单映射。
6. 同步 bootstrap role binding、契约测试和 API 权限文档。

## 9. 测试覆盖
| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| contract | `test/contract_test/test_refresh_token_invalidation_contract.py` | 刷新令牌契约。 |
| contract | `test/contract_test/admin_identity/test_admin_identity_business_boundary_contract.py` | 业务后台身份边界。 |
| contract | `test/contract_test/admin_audit/test_admin_audit_contract.py` | 业务审计动作契约。 |
| unit | `test/unit_test/test_auth_persistence_unit.py` | 认证持久化。 |
| unit | `test/unit_test/test_web_module_manifest_unit.py` | 受保护 scope 与后台边界。 |

## 10. 常见问题
- 新增 `AuthRoleKey`/`AuthScopeCode` 后如未同步初始管理员绑定，可能导致后台接口 403；新增 `BusinessAdminRoleKey` 时还需同步业务角色种子和业务边界测试。

## 11. 维护备注
领域常量变更时同步鉴权文档、API 权限表、配置和测试。



## 12. 相关文档
- [项目文档总览](../README.md)
- [鉴权与授权](../04_infrastructure/authentication_and_authorization.md)
