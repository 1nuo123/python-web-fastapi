# 应用端口

## 1. 文档范围

`src/application/ports` 定义用例可见的外部能力和数据快照，使 application 不导入 `src.infrastructure`。边界由 `test/unit_test/test_application_port_boundary_unit.py` 直接扫描保护。

端口使用 `typing.Protocol` 的结构化子类型：生产实现无需显式继承，测试 fake 也只需实现被当前用例调用的方法。端口签名只暴露标准类型、application dataclass、core 契约或专用 snapshot，不暴露 ORM model。

## 2. `src/application/ports` 清单

| 文件 | Protocol / 契约 | 能力与主要消费者 |
| --- | --- | --- |
| `auth_runtime_port.py` | `AuthRuntimePort`、`AuthFailureThrottlePort`、`PasswordHasherPort`、`TokenServicePort`、`IssuedTokenBundlePort` | 登录/刷新节流；UoW 与身份/refresh repository 工厂；密码哈希；token pair 签发和按用途解码。供三个 token 用例使用。 |
| `task_runtime_port.py` | `TaskRuntimePort`、`TaskRegistrationRuntimeSnapshot` | 读取注册/后端/传输/节点模式/默认值，派发消息，查执行记录，列注册快照，按绑定 model 校验 payload JSON。 |
| `settings_reader_port.py` | `SettingsReaderPort`、`ApplicationSettingsSnapshot` | 只读应用/环境/模块/ready/资源状态；供健康探针和系统概览使用。 |
| `admin_identity_port.py` | `AdminIdentityPort`、query/page/snapshot/result | scope、role、user 和 initial-admin 的持久化能力。 |
| `admin_log_query_port.py` | `AdminLogQueryPort`、两类 filter、`AdminLogRecordSnapshot` | 结构化日志与安全事件查询；历史详情解析失败可返回 `AdminUnparsedLogDetail`。 |
| `admin_audit_query_port.py` | `AdminAuditQueryPort`、`AdminAuditAction/Result`、query/page/snapshot | 业务审计白名单查询，支持 actor/action/target/time/offset 分页。 |
| `admin_settings_reload_port.py` | `AdminSettingsReloadPort`、candidate/result snapshot | 构建配置候选与执行 reload。 |
| `application_port_contract.py` | `ApplicationPortEnvelope` | 端口自描述证据契约，只覆盖 auth/settings/task 三种 kind；不是运行时调用的总端口注册表。 |
| `admin_regression_result.py` | `AdminRegressionResult` | 业务后台回归证据信封，不是 Protocol。 |

## 3. 局部端口

以下 Protocol 与单一用例族紧密关联，因此定义在消费模块而不在 `ports` 目录：

| 位置 | Protocol | 原因 |
| --- | --- | --- |
| `authorization_guard.py` | `AuthorizationPolicyRuntimePort` | 只需获取纯领域 `AuthorizationPolicyEvaluator`。 |
| `admin/identity/initial_admin/create_initial_admin_usecase.py` | `InitialAdminCreatePort`、`PasswordHashPort` | CLI 初始化的最小能力，避免让用例依赖完整 `AdminIdentityPort/AuthRuntimePort`。 |
| `admin/security_protection/manage_admin_security_ip_blocks_usecase.py` | `AdminSecurityIpBlockRuntimePort` | 4 个 IP 封禁用例共享的局部管理端口。 |

## 4. 关键签名语义

### 4.1 `AuthRuntimePort`

- UoW 由 token 用例创建；`create_auth_identity_repository(session)` 和 `create_refresh_token_repository(session)` 接收同一个 `PersistenceSession`，允许一个事务内完成跨仓储编排。
- `decode_token(token, expected_use=...)` 必须区分 access/refresh 用途。
- 节流端口分别提供 assert/record/clear，计数时机由用例控制，而不是藏在 token service 中。

### 4.2 `TaskRuntimePort`

- `get_current_configured_transport_backend()` 返回配置声明的 `MessageBackend`；`get_current_transport_backend()` 返回实际挂载的 `MessageBusBackend`，两者不可混写。
- `list_task_execution_records` 当前是 `limit + status/job_kind`，没有 offset/total。
- `validate_task_payload_json` 返回绑定的 Pydantic `BaseModel`；未绑定 handler 是 `400 system.config.invalid`，模型校验失败是 `422 system.request.invalid`。

### 4.3 后台查询端口

- identity role/user 与 audit 使用 `page_size + offset + total`；scope 只用 `limit` 并返回 list。
- admin log/security-event 只用 `limit`，没有 total/cursor。
- audit `AdminAuditResult` 定义 `success/failed`，但当前快照构建只产出 `success`。

## 5. 生产实现位置

| 实现 | 实现的能力 |
| --- | --- |
| `resource_mount/shared_resource_accessor.py` | UoW/repository/runtime getter 和 `SettingsReaderPort`。 |
| `resource_mount/admin_identity_resource_facade.py` | `AdminIdentityPort`；为每次身份操作闭合 UoW，密码重置/角色替换/停用同时吊销 refresh sessions。 |
| `resource_mount/task_resource_facade.py` | `TaskRuntimePort`；连接注册表、执行记录、Outbox、dispatcher/message bus。 |
| `resource_mount/logging_resource_facade.py` | `AdminLogQueryPort`、`AdminAuditQueryPort` 和安全/日志发射。 |
| `resource_mount/admin_security_resource_facade.py` | `AdminSecurityIpBlockRuntimePort`。 |
| `admin_settings_reload_adapter.py` | `AdminSettingsReloadPort`；组合 `SharedResourceMount` 当前环境与 `SettingsReloadCoordinator`。 |

`SharedResourceMount` 通过多个 facade/mixin 组合这些能力，但 `AdminSettingsReloadPort` 是专用 adapter，不由 mount 直接实现。

## 6. 未就绪与错误契约

- 必需运行时资源缺失时，生产 getter 通常抛 `503 system.resource.not_ready`，不返回 `None` 让用例自行猜测。
- “查询可能不存在”只有签名明确允许时才返回 `None`，如 `get_task_execution_record`；对应 usecase 再转为 `404 system.request.invalid`。
- 业务校验失败用稳定领域/core 错误码；不可预期异常保持原异常链，交统一 exception presenter。
- Protocol 不应 import infrastructure 类型；application 也不得通过 `TYPE_CHECKING` 绕过该依赖方向。

## 7. 分页常量不是全局统一协议

| 能力 | 参数 | 响应元数据 |
| --- | --- | --- |
| identity scopes | `limit` 默认 50，1..200 | 无 offset/total |
| identity roles/users | `page_size` 默认 50，1..200；`offset >= 0` | `page_size/offset/total` |
| audit events | `page_size` 默认 50，1..200；`offset >= 0` | `page_size/offset/total` |
| task executions | `limit` 默认 50，1..200 | 无 offset/total |
| logs/security events | `limit` 默认 50，1..200 | 无 offset/total |

这些常量分别定义在各端口或 HTTP contract 中。修改时必须同步 route Query 约束、payload 字段和 contract/interface 测试，不能假定存在通用 `next_cursor`。

## 8. 扩展步骤

1. 从用例需要的最小能力设计方法，不以数据库表或基础设施组件为中心切接口。
2. 输入/输出使用已有 core 契约或不可变语义清晰的 dataclass snapshot。
3. 在对应 facade/adapter 实现并明确事务、未就绪和异常语义。
4. 用例构造器标注窄 Protocol，不标注具体 `SharedResourceMount`。
5. 更新容器接线，并补 boundary/unit/contract/integration 测试。

## 9. 事实核验测试

| 测试 | 覆盖事实 |
| --- | --- |
| `test/unit_test/test_application_port_boundary_unit.py` | application 禁止导入 infrastructure。 |
| `test/unit_test/test_admin_task_usecase_unit.py` | `TaskRuntimePort` 查询和 payload 校验调用顺序。 |
| `test/unit_test/test_admin_log_query_unit.py` | 日志端口 filter 与 snapshot 映射。 |
| `test/unit_test/admin_audit/test_admin_audit_query_unit.py` | 审计端口 action 映射、过滤和分页。 |
| `test/contract_test/admin_identity/test_admin_identity_business_boundary_contract.py` | 后台分页/回归信封边界。 |
| `test/unit_test/test_resource_mount_lifecycle_unit.py` | mount 资源生命周期与 getter 行为。 |

## 10. 相关文档

- [应用用例](application_usecases.md)
- [领域模型与常量](domain_model_and_constants.md)
- [分层架构](../01_architecture/layered_architecture.md)
- [依赖方向](../01_architecture/dependency_direction.md)
