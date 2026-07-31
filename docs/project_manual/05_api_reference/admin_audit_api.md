# 管理员审计 API

## 1. 范围与源码

`admin_audit` 是默认启用的 `business_admin` 模块，只提供业务审计读取，不提供写入 endpoint。

| 源码 | 职责 |
| --- | --- |
| `src/api/endpoint_admin_audit/route_admin_audit.py` | route、权限、Query 到 application query 映射。 |
| `src/api/endpoint_admin_audit/contract_admin_audit.py` | header/detail/event/page 契约。 |
| `src/application/ports/admin_audit_query_port.py` | action/result/query/page/snapshot 与端口。 |
| `src/application/admin/audit/list_admin_audit_events_usecase.py` | 查询用例。 |
| `src/infrastructure/resource_mount/logging_resource_facade.py` | operation 白名单、数据库查询与快照构造。 |

## 2. 端点与权限

| 方法 | 路径 | 权限 | 响应 `data` |
| --- | --- | --- | --- |
| GET | `/admin/audit-events` | Bearer + role `admin` + scope `auth:read` | `AdminAuditEnvelope` |

模块未启用时 route 为 404；未认证为 401；已认证但缺 role/scope 为 `403 auth.authorization.permission_denied`。

## 3. Query 参数

| 参数 | 类型 | 默认/约束 | 语义 |
| --- | --- | --- | --- |
| `actor_subject_id` | string? | `null` | 精确过滤操作者主体。 |
| `action` | `AdminAuditAction`? | `null` | 枚举过滤；非法枚举为 422。 |
| `target_kind` | string? | `null`；提供时最短 1（由 query payload 二次校验） | 精确过滤目标类型。 |
| `target_id` | string? | 同上 | 精确过滤目标标识。 |
| `occurred_from` | datetime? | `null` | 含义为发生时间起点。 |
| `occurred_to` | datetime? | `null` | 含义为发生时间终点。 |
| `page_size` | int | 50，1..200 | 页大小。 |
| `offset` | int | 0，最小 0 | 偏移。 |

过滤、按时间倒序、offset/limit 与 count 均下推数据库；响应 `total` 是过滤后总数，不是当前页长度。当前 contract 没有 `next_cursor`。

## 4. 动作白名单

查询只扫描 `admin_identity_changed` 安全日志中 operation name 命中下表的记录。未知 operation 即使事件类型相同也不会返回。

| `action` 查询值 | 接受的 operation name |
| --- | --- |
| `user_created` | `user_create` |
| `user_updated` | `user_update` |
| `user_disabled` | `user_delete`、`user_disable` |
| `user_enabled` | `user_enable` |
| `password_reset` | `user_password_reset` |
| `role_assigned` | `user_role_replace` |
| `scope_changed` | `scope_create`、`scope_update`、`scope_delete` |
| `role_created` | `role_create` |
| `role_updated` | `role_update` |
| `role_deleted` | `role_delete` |
| `role_roles_replaced` | `role_scope_replace` |
| `settings_reloaded` | `settings_reload` |

`role_roles_replaced` 是当前对外枚举值，虽然其内部含义是“role 的 scopes 被替换”，兼容变更前不得自行改名。

## 5. 响应结构

外层为 `ResponseEnvelope[AdminAuditEnvelope]`。内层固定：

```text
data.header.kind = "admin_audit_event_list"
data.header.schema_version = "1.0"
data.header.operation_name = "event_list"
data.detail.kind = "admin_audit_event_list"
data.detail.schema_version = "1.0"
```

`data.detail` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `events` | array | 当前页事件。 |
| `page_size` | int | 回显请求页大小。 |
| `offset` | int | 回显偏移。 |
| `total` | int | 过滤后总数。 |

事件字段为 `event_id`、`action`、`actor_subject_id`、`target_kind`、`target_id`、`result`、`occurred_at`、`summary`。`summary` 是服务端由 actor/target/action 生成的无敏感参数摘要。

## 6. 写入与一致性边界

- identity route 在用例成功返回后发射变更事件；scope/role/user 的 repository 或 usecase 本身不发射。
- settings reload route 只在 `result.success=True` 时发射 `settings_reload`。
- `admin_identity_changed` 属 audit-critical 类型，`LoggingResourceFacade` 将其标记为 `persistence_priority=audit_critical`，绕过普通缓冲同步写库。
- 直接调用 repository/facade、CLI 初始管理员创建以及失败的 HTTP 身份变更，当前不会自动生成业务审计记录。
- `AdminAuditResult` 虽定义 `success/failed`，当前 snapshot builder 固定返回 `success`；不要把“失败枚举存在”误解为失败操作已被审计 API 覆盖。

## 7. 错误语义

| HTTP | 错误码 | 条件 |
| --- | --- | --- |
| 401 | `auth.token.invalid` | Bearer 缺失或访问令牌无效。 |
| 403 | `auth.access.account_disabled` | token 主体已停用。 |
| 403 | `auth.authorization.permission_denied` | 缺 admin 或 auth:read。 |
| 422 | `system.request.invalid` | action/datetime/page_size/offset/目标字段不满足 contract。 |
| 503 | `system.resource.not_ready` | 日志数据库资源未就绪。 |

业务审计不是普通日志全文搜索，不返回密码、token、请求 body 或任意 security event detail。

## 8. 事实核验测试

| 测试 | 覆盖事实 |
| --- | --- |
| `test/interface_test/admin_audit/test_admin_audit_interface.py` | 权限、actor/action/target/time 过滤、分页、脱敏、非白名单忽略。 |
| `test/contract_test/admin_audit/test_admin_audit_contract.py` | 内层信封和字段约束。 |
| `test/unit_test/admin_audit/test_admin_audit_query_unit.py` | 12 个 action 完整映射、SQL 过滤/排序/分页下推。 |
| `test/integration_test/test_audit_crash_safety_integration.py` | 审计关键写入的故障安全。 |

## 9. 相关文档

- [管理后台能力](../03_application_domain/admin_business_capabilities.md)
- [管理员身份 API](admin_identity_api.md)
- [管理员日志 API](admin_log_api.md)
- [API 总览](api_overview.md)
