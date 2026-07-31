# 管理员任务 API

## 1. 范围与源码

`admin_task` 是默认不启用的 `ops_only` 模块，提供执行记录、运行时/注册快照和受控任务派发。

| 源码 | 职责 |
| --- | --- |
| `src/api/endpoint_admin_task/route_admin_task.py` | 5 个 route 与两类权限。 |
| `src/api/endpoint_admin_task/contract_admin_task.py` | 请求/响应双层信封和 admin payload 映射。 |
| `src/application/admin/*admin_task*_usecase.py` | 查询、汇总、payload 校验与派发编排。 |
| `src/application/ports/task_runtime_port.py` | 任务运行时端口。 |
| `src/application/dispatch_background_job_usecase.py` | 通用 descriptor/message 构造。 |

## 2. 端点与权限

| 方法 | 路径 | 权限 | 响应 `data` |
| --- | --- | --- | --- |
| GET | `/admin/tasks/executions` | admin + `system:read` | `AdminTaskExecutionListEnvelope` |
| GET | `/admin/tasks/executions/{task_id}` | admin + `system:read` | `AdminTaskExecutionRecordEnvelope` |
| GET | `/admin/tasks/runtime` | admin + `system:read` | `AdminTaskRuntimeEnvelope` |
| GET | `/admin/tasks/registrations` | admin + `system:read` | `AdminTaskRegistrationListEnvelope` |
| POST | `/admin/tasks/dispatch` | admin + `task:dispatch` | `AdminTaskDispatchResultEnvelope` |

模块未加入 `app.modules.enabled` 时为 404。查询权限与派发权限相互独立：只有 `system:read` 不能 dispatch，只有 `task:dispatch` 也不能查运行时。

## 3. 执行记录查询

`GET /executions` 参数：

| 参数 | 类型 | 默认/约束 |
| --- | --- | --- |
| `status` | `pending|reserved|published|running|retrying|success|failed`? | null |
| `job_kind` | string? | null |
| `limit` | int | 50，1..200 |

这是 limit-only 的最近记录查询，没有 offset/total/cursor。列表 detail 为 `records[]`；每项包含：

- header 信息：`record_id/task_id/job_kind/deduplication_key/backend/queue_name/request_id/trace_id/created_at_epoch`。
- `runtime`：`status/stage/attempt_count/started_at_epoch/finished_at_epoch/failed_at_epoch/next_retry_at_epoch/last_error_type/last_error_message`。

详情 path 的 `task_id` 当前只要求 string；记录不存在由 `GetAdminTaskExecutionRecordUsecase` 返回 `404 system.request.invalid`，detail 携带 task id。

## 4. Runtime 快照

`GET /runtime` 的 detail 字段：

| 字段 | 含义 |
| --- | --- |
| `task_runtime_mode` | `local_inline/local_queued/funboost_producer/funboost_consumer`。 |
| `task_backend` | task 执行后端 `local|funboost`。 |
| `transport_backend` | 实际挂载的 message bus backend `local|rabbitmq`。 |
| `configured_transport_backend` | 配置声明的 message backend；用于识别配置与实际挂载差异。 |
| `worker_enabled` | 当前节点是否消费/运行 worker。 |
| `inline_execute_enabled` | local backend 是否内联执行；非 local 返回 false。 |
| `default_job_kind/default_retry_limit` | 派发缺省值。 |

不要用 `task_backend` 推断消息传输：Funboost 和 RabbitMQ 是不同维度，必须分别看 task/transport 字段。

## 5. 注册快照

`GET /registrations` 返回所有注册，不仅是当前 backend 的 active 项。每项：

`task_name`、`job_kind`、`enabled`、`registration_backend`、`current_runtime_backend`、`active_for_current_runtime`、`handler_bound`、`payload_model_name`、`retry_limit`、`queue_name`、`exchange_name`、`routing_key`。

Local 注册的 queue/exchange/routing 通常为 null；Funboost 项按注册 detail 映射。`active_for_current_runtime` 只表示 enabled 且 registration backend 等于当前 backend；能否从管理端安全派发还要求 `handler_bound=True` 和 payload model 可用。

## 6. Dispatch 请求

```json
{
  "header": {
    "kind": "admin_task_dispatch",
    "schema_version": "1.0",
    "operation_name": "dispatch"
  },
  "detail": {
    "kind": "admin_task_dispatch",
    "schema_version": "1.0",
    "job_kind": "example.job",
    "payload_json": "{\"value\":1}",
    "retry_limit": 2,
    "deduplication_key": "client-stable-key"
  }
}
```

| 字段 | 约束/语义 |
| --- | --- |
| `job_kind` | 非空，必须存在当前 backend 的 enabled registration。 |
| `payload_json` | 非空 string；随后由绑定的 Pydantic payload model `model_validate_json` 校验。 |
| `retry_limit` | 可空，>=0；优先级为请求 > 注册 > 运行时默认。 |
| `deduplication_key` | 可空；空值/None 按缺省处理并生成 UUID，稳定非空值用于去重。 |

header/detail 都拒绝额外字段，kind/schema 必须一致。当前 `AdminTaskDispatchEnvelope` 将 `operation_name` 限制为任务操作枚举，但没有额外断言它必须等于 `dispatch`；规范客户端仍应发送 `dispatch`，不要依赖这一校验空隙。

## 7. Dispatch 流程与结果

1. `DispatchAdminTaskUsecase` 调 `validate_task_payload_json(job_kind,payload_json)`；先校验注册，再查 handler binding，再反序列化模型。
2. 通用用例按当前 backend 再取启用注册，构造 `task_id`、JSON payload、dedup/retry 和 request/trace header。
3. `TaskRuntimePort.dispatch_task_message` 负责执行记录、Outbox/发布或 local 执行。

结果 detail：`task_id/job_kind/dispatched/retry_limit/backend/queue_name/published/worker_enabled/inline_execute_enabled/execution_status/execution_stage/reused_existing_record`。

`reused_existing_record=True` 表示 deduplication key 命中既有记录；调用方应使用返回的 task id/状态，而不是假定每次 POST 都创建新任务。`published` 与 `dispatched`、worker 是否执行完毕是不同状态。

## 8. 信封固定值

| endpoint | `data.header.kind` | `operation_name` |
| --- | --- | --- |
| executions list | `admin_task_execution_list` | `execution_list` |
| execution detail | `admin_task_execution_record` | `execution_record` |
| runtime | `admin_task_runtime` | `runtime_read` |
| registrations | `admin_task_registration_list` | `registration_list` |
| dispatch response | `admin_task_dispatch_result` | `dispatch_result` |

版本均为 `1.0`，header.kind 与 detail.kind 必须相同。

## 9. 错误语义

| HTTP | 错误码 | 典型触发 |
| --- | --- | --- |
| 401 | `auth.token.invalid` | 未认证。 |
| 403 | `auth.authorization.permission_denied` | 缺 admin 或对应 scope。 |
| 404 | route 不存在 | 模块未启用。 |
| 404 | `system.request.invalid` | task execution record 不存在。 |
| 400 | `system.config.invalid` | job 已注册但 handler binding 缺失。 |
| 422 | `system.request.invalid` | query/body 不合法，或 payload JSON 不满足绑定 model。 |
| 500 | `system.config.invalid` | backend、注册或 dispatcher 配置不一致。 |
| 503/500 | `system.resource.not_ready` | task/message/Outbox 等资源未就绪；个别底层发布路径保持其实现状态码。 |
| 503 | `system.capacity.exhausted` | local dispatcher 容量耗尽。 |
| 500 | `system.task.failed` | local/Funboost/RabbitMQ 派发或执行失败。 |

失败发生在 payload validation 之前或期间时不会创建执行记录；interface 测试显式覆盖 disabled registration/handler missing 的“无脏记录”行为。

## 10. 事实核验测试

| 测试 | 覆盖事实 |
| --- | --- |
| `test/interface_test/test_admin_task_interface.py` | 模块、权限、查询、详情缺失、limit、payload 和派发错误。 |
| `test/contract_test/test_admin_task_contract.py` | 所有任务信封和 payload 字段。 |
| `test/unit_test/test_admin_task_usecase_unit.py` | filters、runtime 汇总、payload 校验先于 dispatch。 |
| `test/contract_test/test_task_execution_contract.py` | 执行记录/去重状态。 |
| `test/integration_test/test_task_execution_record_integration.py` | 真实执行记录持久化。 |

## 11. 相关文档

- [管理后台能力](../03_application_domain/admin_business_capabilities.md)
- [应用用例](../03_application_domain/application_usecases.md)
- [应用端口](../03_application_domain/application_ports.md)
- [API 总览](api_overview.md)
