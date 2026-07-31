# Grafana 与 Prometheus 接入说明

> 修订时间：2026-07-20。本次修订与 `src/infrastructure/observability/prometheus_metrics_registry.py`、`config/observability/alert_rules.yml` 最终实现对齐；文档与源码冲突时以源码为准。

## 当前边界

当前项目只补应用侧可观测性接入点，不内置 Prometheus、Grafana、Loki、Tempo、Promtail、Alertmanager 部署栈。

- OpenTelemetry：配置与 FastAPI instrument 桥接已保留，默认关闭。
- Prometheus：通过 `runtime.metrics.header.enabled` 控制是否暴露 `/metrics`。
- Grafana：不直接接入应用代码，通过 Prometheus 数据源展示应用指标。
- 告警：应用不承载告警执行；告警规则基线随代码版本化在 `config/observability/alert_rules.yml`，由外部 Prometheus 挂载引用。

## 应用配置

指标运行时契约版本为 `1.1`（`metrics_runtime_contract.py`），除 HTTP 与 ready 开关外新增四个指标族开关：

```toml
[runtime.header]
enabled = true

[runtime.detail]
metrics_path = "/metrics"
include_http_metrics = true
include_runtime_metrics = true
include_security_metrics = true
include_task_metrics = true
include_log_buffer_metrics = true
include_saturation_metrics = true
```

`/metrics` 使用 Prometheus 文本格式返回，不使用项目统一 JSON 响应信封。开关关闭的指标族不注册、不出现在输出中。

## 指标清单

| 指标名 | 类型 | 标签 | 语义 |
|---|---|---|---|
| `fastapi_request_total` | Counter | `method`、`path`、`status_code` | HTTP 请求总数 |
| `fastapi_request_duration_seconds` | Histogram | `method`、`path`、`status_code` | HTTP 请求耗时 |
| `fastapi_runtime_ready` | Gauge | 无 | 应用 ready 状态 |
| `fastapi_security_event_total` | Counter | `event_type`、`decision`、`severity` | 安全事件总数，标签取值限定在 `SecurityEventType`/`SecurityEventDecision`/`SecurityEventSeverity` 封闭枚举 |
| `fastapi_log_buffer_flush_total` | Counter | `reason`（buffer_limit/interval/manual/shutdown/audit_critical）、`failed`（true/false） | 日志缓冲刷盘事件总数，按批次事件数量累加 |
| `fastapi_log_buffer_pending_items` | Gauge | 无 | 日志缓冲待落库事件数量（缓冲区 + 后台队列） |
| `fastapi_task_execution_total` | Counter | `task_name`（任务注册名）、`outcome`（success/failed/rejected） | 任务执行结果总数；`rejected` 表示去重拒绝复用既有记录 |
| `fastapi_runtime_saturation_ratio` | Gauge | `resource`（request_thread_pool/db_pool/task_queue/log_buffer） | 运行时有界资源饱和度（0-1），按容量策略上限折算 |

饱和度指标采用事件式刷新：应用启动完成、配置热更新提交与每次 `/metrics` 抓取时各刷新一次。

## Prometheus 抓取与告警规则引用示例

```yaml
scrape_configs:
  - job_name: fastapi-web-skeleton
    metrics_path: /metrics
    static_configs:
      - targets: ["app:8000"]
```

本地开发没有启动 Prometheus 的强制要求。只有部署监控系统时，才需要把目标地址替换为实际应用服务名和端口。

告警规则基线文件为 `config/observability/alert_rules.yml`，结构由 `src/core/observability_contract/alert_rule_contract.py` 判别联合契约约束，并由契约测试保证可解析、字段合法。该文件是随代码版本化的规则事实源：部署监控栈时由运维将其中六条规则的 `promql_expression`、`for_duration_seconds` 与 `severity` 转写为外部 Prometheus 的 rule group 并挂载；应用自身不评估告警。六条基线规则：

| 规则名 | 级别 | 语义 |
|---|---|---|
| `http_5xx_error_rate_high` | critical | 5xx 错误率超过 5% 持续 5 分钟 |
| `http_p95_latency_high` | warning | P95 延迟超过 1 秒持续 5 分钟 |
| `runtime_ready_down` | critical | `fastapi_runtime_ready` 掉线或抓取缺失持续 2 分钟 |
| `log_buffer_flush_failure_growing` | warning | `fastapi_log_buffer_flush_total{failed="true"}` 在 10 分钟窗口内增长 |
| `audit_critical_write_failure` | critical | `fastapi_log_buffer_flush_total{reason="audit_critical",failed="true"}` 出现增长 |
| `task_execution_failure_rate_high` | warning | `fastapi_task_execution_total{outcome="failed"}` 失败率超过 20% 持续 10 分钟 |

## Grafana 数据源示例

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

Grafana 面板读取 Prometheus，不直接访问应用数据库、日志表或业务接口。

## 面板建议

- QPS：`sum(rate(fastapi_request_total[5m]))`
- 错误率：`sum(rate(fastapi_request_total{status_code=~"5.."}[5m])) / sum(rate(fastapi_request_total[5m]))`
- P95 耗时：`histogram_quantile(0.95, sum(rate(fastapi_request_duration_seconds_bucket[5m])) by (le))`
- ready 状态：`fastapi_runtime_ready`
- 日志缓冲失败：`sum(rate(fastapi_log_buffer_flush_total{failed="true"}[5m])) by (reason)`，配合积压面板 `fastapi_log_buffer_pending_items`
- 审计写失败：`sum(increase(fastapi_log_buffer_flush_total{reason="audit_critical",failed="true"}[5m]))`
- 任务失败率：`sum(rate(fastapi_task_execution_total{outcome="failed"}[10m])) by (task_name) / sum(rate(fastapi_task_execution_total[10m])) by (task_name)`
- 资源饱和度：`fastapi_runtime_saturation_ratio`，按 `resource` 标签分面展示线程池、数据库连接池、任务队列与日志缓冲

## 日志刷盘语义

`flush_interval_seconds` 是日志缓冲的 lazy flush 阈值：新日志进入 `LogBufferDispatcher.emit()` 时，若距离上次刷盘已超过该间隔，会在本次 emit 路径触发批量刷盘。它不是后台定时线程；没有新日志进入时，不会仅因时间到达自动刷盘。

审计关键事件（`persistence_priority = audit_critical`，覆盖管理员身份/scope/role 变更、配置热更新与安全配置拒绝）不进入缓冲：`emit()` 在发射线程内以 `reason="audit_critical"` 同步提交写请求，返回前即进入数据库事务提交路径，因此进程被强制终止不会丢失此类事件；写失败计入 `AuditWriteFailureCounter` 失败快照并反映到 `fastapi_log_buffer_flush_total{reason="audit_critical",failed="true"}`。

资源生命周期会显式收口日志缓冲：运行时关闭时执行 shutdown/manual flush，手动刷盘入口也会立即落库。日志缓冲积压与失败已通过 `fastapi_log_buffer_pending_items` 与 `fastapi_log_buffer_flush_total` 暴露，Grafana/Prometheus 不直接读取日志缓冲内容。

## 敏感信息约束

指标标签只使用低基数值：HTTP 方法、FastAPI 低基数路由模板、状态码、封闭枚举取值（安全事件类型/决策/级别、刷盘原因、任务结果、资源名）与任务注册名，不记录完整 URL、请求体、Authorization、JWT、password、secret 或 token。动态主流程路由会记录 `/users/{subject_id}` 这类 route template；无法解析模板或疑似原始动态路径时统一归入 `unknown`。安全事件指标执行白名单策略：事件类型不属于 `SecurityEventType` 封闭枚举时不打点。
