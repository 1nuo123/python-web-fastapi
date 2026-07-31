# 日志运行时

## 1. 这是什么

详解结构化日志子系统：日志事件契约（5 种事件类型的 header+detail 信封）、两级持久化优先级（标准缓冲批刷 vs 审计关键同步落库）、缓冲派发器的线程模型、数据库写入器与 stdout 降级、脱敏器，以及普通文本日志（logger）与结构化事件的关系。

**最后更新范围**：覆盖 `src/core/logging_contract/` 3 个契约与 `src/infrastructure/logging/` 7 个实现文件、logging_runtime 配置。

## 2. 设计思想与动机

- **事件与文本双轨**：普通 `logging.Logger` 文本日志用于开发观察与进程 stdout；**结构化日志事件**（`LogEventEnvelope`）才是可检索、可审计的事实记录，落 PostgreSQL `app_log_record` 表，经 `/admin/logs` 查询。文本日志不承诺格式稳定，事件契约承诺。
- **审计与吞吐分级**：`LogPersistencePriority.AUDIT_CRITICAL`（当前白名单：`ADMIN_IDENTITY_CHANGED`、`CONFIG_SECURITY_REJECTED` 两类安全事件）在发射线程内**同步写库**，返回前完成事务——审计记录不允许因进程崩溃丢缓冲。其余事件走有界缓冲 + 后台单线程批量刷盘，用吞吐换延迟。
- **落库失败不影响业务**：写库失败按配置降级 stdout（`fallback_to_stdout=true`），失败计数进指标与告警；日志子系统的内部错误用独立 logger（`log_buffer.internal`，不进结构化管道）避免递归。
- **敏感信息不落原文**：`SensitiveTextRedactor` 对异常 detail/traceback 做模式脱敏（令牌、密码类片段）；client_ip 等敏感维度在安全事件中已是摘要。

## 3. 事件契约（LOG_EVENT_SCHEMA_VERSION = 1.1）

`LogEventEnvelope = header + detail(kind 判别)`：

| kind | detail 模型 | 产生点 |
| --- | --- | --- |
| `access` | 路径/方法/状态码/耗时/client_ip/user_agent/route_name | AccessLogMiddleware |
| `exception` | 路径/方法/状态码/error_code/异常类型/detail/traceback_text | 异常处理器、认证中间件 |
| `resource_lifecycle` | 资源名/动作(startup/shutdown/reload)/状态/detail | 资源启动器/释放器/热更新 |
| `task_failure` | task_id/job_kind/backend/stage/retry_count/queue/dedup_key/attempt | FailedTaskRecorder |
| `security` | 内嵌完整 `SecurityEventEnvelope` | emit_security_event |

header 公共字段：event_id、occurred_at、level、kind、persistence_priority、message、request_id/trace_id/authenticated_subject_id（可空）、source_module/source_component。`model_validator` 强制 header.kind 与 detail.kind、schema_version 两侧一致。

`LogEventBuilder`（290 行）是唯一事件构造器：从 Request/contextvar 提取请求上下文、决定 persistence_priority（按安全事件类型白名单）、调用脱敏器。

## 4. 管道与线程模型

```mermaid
flowchart LR
    E["emit_log_event / emit_security_event"] --> B["LogEventBuilder"]
    B -->|AUDIT_CRITICAL| SYNC["同步 write_batch<br/>（发射线程内，事务提交后返回）"]
    B -->|STANDARD| BUF["缓冲 list（容量 buffer_max_items=1000）"]
    BUF -->|容量/批大小(100)/时间窗(2s) 任一触发| Q["有界 Queue"]
    Q --> W["后台 worker 线程<br/>log-buffer-dispatcher-worker"]
    W --> DBW["DatabaseLogWriter.write_batch"]
    DBW -->|失败| STDOUT["stdout 降级 + 内部 logger + 指标 failed=true"]
    SYNC -->|失败| CNT["audit_write_failed 计数 + critical 告警"]
```

- 刷盘触发三条件（emit 内判断）：缓冲达 `buffer_max_items` 上限、达 `max_batch_size`、距上次刷盘超过 `flush_interval_seconds`。
- `flush(reason)` 显式刷（shutdown/手动/热更新提交后）：drain 缓冲 + `queue.join()` 等后台队列清空，同步写出。
- 积压可观测：`fastapi_log_buffer_pending_items`（缓冲+队列待写数）、`fastapi_log_buffer_flush_total{reason,failed}`（按批事件数累加）；饱和度指标 `runtime_saturation_ratio{resource="log_buffer"}`。
- 启动早期（日志运行时未就绪前）的事件暂存 `_pending_log_events`，日志资源就绪后由 `drain_pending_log_events` 补投——启动过程的资源生命周期事件不丢。

## 5. 文本日志与外部框架桥接

- `AppLoggerFactory`：构建 runtime logger（级别 = `runtime.logging.level`，热更新可改）；`StructuredLogHandler` 挂载后，经该 logger 写出的 warning+ 记录也会转结构化事件进缓冲。
- `LoggingEntryEnvironmentBridge`：把 `entry_project_name/entry_log_path` 写为 funboost/nb_log 需要的环境变量（这两个三方库有自己的日志入口约定）；容器内 `LOGGING_ENTRY_LOG_PATH=/tmp/logs`（read_only 根文件系统下唯一可写处）。

## 6. 配置（runtime.logging）

`enabled`、`level(INFO)`、`sink(database)`、`buffer_max_items(1000)`、`entry_project_name`、`entry_log_path`、`sink_detail{table_name=app_log_record, flush_interval_seconds=2, max_batch_size=100, fallback_to_stdout=true, retention_days=30}`。`enabled=false` 时日志资源标记 stopped，结构化管道整体停用（文本日志仍在）。`level` 可热更新，其余属 restart_required。

## 7. 注意事项

- `retention_days` 是声明性配置，当前代码内没有自动清理任务——库表清理需运维侧执行（见[运维检查清单](../07_configuration_deployment/operations_checklist.md)）。
- audit_critical 同步落库发生在发射线程（通常是请求线程池线程）：管理员变更类接口的延迟包含一次日志事务，属于设计成本。
- 缓冲有界：极端量下 emit 会先强制刷盘（BUFFER_LIMIT 原因）而不是无界膨胀；持续积压说明写库跟不上，看 pending_items 指标与数据库健康。
- kill -9 会丢弃未刷缓冲中的标准事件（audit_critical 不受影响）；正常停机路径（SIGTERM → lifespan shutdown）有两次显式 flush 兜底。
- 历史库记录若无法按当前契约解析，管理端查询以摘要占位显示，不会 500。

## 8. 测试覆盖

| 测试类型 | 文件 | 验证内容 |
| --- | --- | --- |
| unit | `test/unit_test/test_log_buffer_dispatcher_unit.py` | 触发条件、审计同步、失败计数。 |
| unit | `test/unit_test/test_log_event_builder_unit.py` | 事件构造与脱敏。 |
| contract | `test/contract_test/test_log_event_contract.py` | 信封一致性。 |
| initialization | `test/initialization_test/test_logging_initialization.py` | 资源装配与 pending 补投。 |
| path | `test/path_test/test_logging_path.py` | 端到端日志链路。 |

## 9. 相关文档

- [项目文档总览](../README.md)
- [管理员日志 API](../05_api_reference/admin_log_api.md)
- [可观测性](observability.md)
- [ORM 模型](../06_data/orm_models.md)
