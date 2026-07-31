# 管理员日志 API

## 1. 范围与源码

`admin_log` 是默认不启用的 `ops_only` 模块，提供结构化日志列表与安全事件专用视图。

| 源码 | 职责 |
| --- | --- |
| `src/api/endpoint_admin_log/route_admin_log.py` | 2 个 GET、过滤参数和权限。 |
| `src/api/endpoint_admin_log/contract_admin_log.py` | 输出侧脱敏 payload 和双层信封。 |
| `src/application/ports/admin_log_query_port.py` | filter/snapshot/不可解析详情。 |
| `src/application/admin/list_admin_*events_usecase.py` | 两个薄查询用例。 |
| `src/infrastructure/resource_mount/logging_resource_facade.py` | 数据库查询、解析、过滤和兜底脱敏。 |

## 2. 端点与权限

| 方法 | 路径 | 权限 | 响应 `data` |
| --- | --- | --- | --- |
| GET | `/admin/logs` | Bearer + admin + `system:read` | `AdminLogRecordListEnvelope` |
| GET | `/admin/security-events` | Bearer + admin + `system:read` | `AdminSecurityEventListEnvelope` |

`admin_log` 未加入 `app.modules.enabled` 时 route 为 404。两个 endpoint 是 limit-only 查询，不返回 offset、total 或 next cursor。

## 3. `/admin/logs` 参数

| 参数 | 类型 | 默认/约束 | 过滤语义 |
| --- | --- | --- | --- |
| `level` | `DEBUG|INFO|WARNING|ERROR|CRITICAL`? | null | 精确日志级别。 |
| `event_kind` | `access|exception|resource_lifecycle|task_failure|security`? | null | 精确结构化事件类型。 |
| `request_id` | string? | null | 精确 request id。 |
| `trace_id` | string? | null | 精确 trace id。 |
| `occurred_from` | datetime? | null | 时间起点。 |
| `occurred_to` | datetime? | null | 时间终点。 |
| `limit` | int | 50，1..200 | 返回上限。 |

repository 对支持字段下推过滤和排序，再构建强类型 snapshot。

## 4. `/admin/security-events` 参数

| 参数 | 类型 | 默认/约束 | 过滤语义 |
| --- | --- | --- | --- |
| `event_type` | `SecurityEventType`? | null | 安全事件类型。 |
| `severity` | `info|warning|critical`? | null | 安全事件严重度枚举。 |
| `decision` | `allow|deny|record_only`? | null | 决策枚举。 |
| `occurred_from/occurred_to` | datetime? | null | 时间窗。 |
| `limit` | int | 50，1..200 | 命中过滤后的返回上限。 |

该 endpoint 只返回成功解析且包含 `security_event` 的 security log。severity/decision 等过滤必须在应用 limit 前得到满足；测试覆盖“前面的不匹配事件不能占掉 limit”。

## 5. 日志响应

外层为 `ResponseEnvelope`。`/admin/logs` 内层固定：

```text
data.header.kind = "admin_log_record_list"
data.header.operation_name = "log_record_list"
data.detail.kind = "admin_log_record_list"
data.detail.records = [...]
```

每条 record 字段：`event_id/event_kind/schema_version/level/message/occurred_at/request_id/trace_id/authenticated_subject_id/source_module/source_component/detail`。

`detail` 是以下输出侧 union，不直接回传原始数据库 JSON：

| kind | 字段摘要 | 明确移除/处理 |
| --- | --- | --- |
| `admin_access_log_detail` | path/method/status/elapsed/route | 不暴露 client IP、User-Agent 等原 access detail 身份信息。 |
| `admin_exception_log_detail` | path/method/status/error_code/exception_type | 不暴露 traceback/message 原始异常细节。 |
| `admin_resource_lifecycle_log_detail` | resource/action/status/detail | `detail` 再经 `SensitiveTextRedactor`。 |
| `admin_task_failure_log_detail` | task/job/backend/stage/retry/queue/payload kind/request/trace/dedup/attempt | 不回传 payload JSON 与原异常内容。 |
| `admin_security_log_detail` | `security_event` | 使用强类型安全事件契约；敏感主体通常是 digest。 |
| `admin_unparsed_log_detail` | `summary` | 历史版本或不兼容 JSON 的安全占位。 |

如果记录 schema version 不等于当前 `LogEventEnvelope` 版本、enum 无效或 detail 校验失败，门面返回摘要“历史日志详情无法按当前强类型契约解析”，不会让整个列表 500。

## 6. 安全事件响应

`/admin/security-events` 内层：

```text
data.header.kind = "admin_security_event_list"
data.header.operation_name = "security_event_list"
data.detail.kind = "admin_security_event_list"
data.detail.events = [...]
```

每条 event：`event_id/log_level/log_message/occurred_at/request_id/trace_id/source_module/source_component/security_event`。`security_event` 保留其 header/detail discriminator，例如 event type、severity、decision、reason/status/policy 与特定强类型 detail。

此专用响应不包含 `authenticated_subject_id` 顶层字段；主体信息只按安全事件契约提供。

## 7. 脱敏与数据来源

- 数据来自 `app_log_record` 结构化日志表，不读取普通文本日志文件。
- 写入链已执行日志安全处理，查询门面和 HTTP mapper 再做防御性输出裁剪。
- API 不提供全文搜索、原始 `detail_json` 下载、密码/token/request body 回放或日志删除。
- `limit` 是上限，不代表存在完整分页能力；需要翻页/导出时应先新增明确的稳定排序和 cursor contract。
- 业务身份审计应使用 `/admin/audit-events`；它基于 operation 白名单，不能用 security-events 代替业务审计语义。

## 8. 错误语义

| HTTP | 错误码 | 条件 |
| --- | --- | --- |
| 404 | route 不存在 | 模块未启用。 |
| 401 | `auth.token.invalid` | Bearer 缺失/无效。 |
| 403 | `auth.access.account_disabled` | 当前主体停用。 |
| 403 | `auth.authorization.permission_denied` | 缺 admin 或 system:read。 |
| 422 | `system.request.invalid` | enum、datetime 或 limit 不满足 Query contract。 |
| 503 | `system.resource.not_ready` | 日志数据库/repository 未就绪。 |

历史详情不可解析不是错误响应，而是单条 `admin_unparsed_log_detail`。

## 9. 事实核验测试

| 测试 | 覆盖事实 |
| --- | --- |
| `test/interface_test/test_admin_log_interface.py` | 两个 endpoint、权限、模块、所有过滤、limit、输出脱敏和 secret redaction。 |
| `test/contract_test/test_admin_log_contract.py` | header/detail union 与输出字段。 |
| `test/unit_test/test_admin_log_query_unit.py` | filter 传递、repository 下推和不可解析摘要。 |
| `test/integration_test/test_database_logging_integration.py` | 结构化日志真实落库。 |
| `test/exception_test/test_logging_redaction_exception.py` | 异常路径敏感信息保护。 |

## 10. 相关文档

- [管理后台能力](../03_application_domain/admin_business_capabilities.md)
- [管理员审计 API](admin_audit_api.md)
- [日志系统](../04_infrastructure/logging_system.md)
- [API 总览](api_overview.md)
